"""Usage charging: provisional-vs-final variants, pinned rounding order,
external rate selection, and immediate read-after-write (PRD §2.5, §3.6–§3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_booking_payload, create_usage_log_payload,
    make_external_client_headers, make_researcher_headers,
    setup_canonical_stack, create_user, enroll_and_certify,
    create_booking_request, create_approved_booking, approve_booking, open_batch,
    run_session_to_completed, create_and_validate_usage_log,
    setup_completed_booking_with_entry, get_grant, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestProvisionalVsFinal:
    def _setup(self, api):
        """Canonical stack; booking 90 scheduled minutes APPROVED; session
        completed with 74 actual minutes; batch OPEN; log submitted."""
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)
        approved = approve_booking(b1["id"])
        batch = open_batch(2026, 9)
        completed = run_session_to_completed(
            approved, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        log = validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    completed["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
                ),
                STAFF,
            ),
            201,
        )
        validate_success(api.submit_usage_log(log["id"], STAFF), 200)
        return stack, approved, log

    def test_provisional_estimate_at_approval(self, api):
        """PRD §3.6: "The provisional estimate — `estimated_charge_cents` — is
        the scheduled minutes (the whole-minute difference between `end_at` and
        `start_at`) multiplied by the pinned hourly rate divided by sixty,
        rounded half-up to whole cents; this provisional variant applies no
        billing-increment ceiling, no minimum-charge floor, and no
        consumables."

        Design: Difficulty/dual_variant_calc/usage_charge_provisional_vs_final_on_booking
        """
        stack, approved, log = self._setup(api)
        assert approved["estimated_charge_cents"] == 18000, (
            "provisional variant: 90 scheduled min x 12000/60 = 18000"
        )

    def test_final_charge_at_validation_differs(self, api):
        """PRD §3.8: "`billable_minutes` is the actual minutes rounded *up* to
        the next whole multiple of the booking's `applied_increment_minutes`,
        then floored at `applied_min_charge_minutes` — the increment ceiling is
        applied first, the minimum-charge floor second. `usage_charge_cents` is
        `billable_minutes` multiplied by the pinned `applied_rate_cents_per_hour`
        and divided by sixty, rounded half-up to whole cents, with
        `consumable_fee_cents` added last and never itself rounded." PRD §3.8:
        "Validation computes the **final** charge, which differs from the
        provisional estimate whenever actual usage diverges from the schedule."

        Design: Difficulty/dual_variant_calc/usage_charge_provisional_vs_final_on_booking
        """
        stack, approved, log = self._setup(api)
        validated = validate_success(api.validate_usage_log(log["id"], STAFF2), 200)
        assert validated["billable_minutes"] == 75, "ceil(74/15)*15 = 75"
        assert validated["usage_charge_cents"] == 15000, "75 x 200 = 15000"
        booking = validate_success(api.get_booking(approved["id"], STAFF), 200)
        assert booking["estimated_charge_cents"] == 18000
        assert validated["usage_charge_cents"] != booking["estimated_charge_cents"]


class TestNestedRoundingOrder:
    def _setup(self, api):
        """Two approved+completed bookings: b1 scheduled 09:00-09:47 with 47
        actual minutes and a 500-cent consumable; b2 09:00-09:30 with 10 actual
        minutes. Batch 2026-09 OPEN. Returns (stack, b1, b2)."""
        stack = setup_canonical_stack()
        b1 = create_approved_booking(
            stack, start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T09:47:00Z"
        )
        b2 = create_approved_booking(
            stack, start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T09:30:00Z"
        )
        open_batch(2026, 9)
        completed1 = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T09:47:00Z"
        )
        log1 = validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    completed1["id"], "2026-09-01T09:00:00Z", "2026-09-01T09:47:00Z",
                    consumable_fee_cents=500,
                ),
                STAFF,
            ),
            201,
        )
        validate_success(api.submit_usage_log(log1["id"], STAFF), 200)
        completed2 = run_session_to_completed(
            b2, "2026-09-02T09:00:00Z", "2026-09-02T09:10:00Z"
        )
        log2 = validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    completed2["id"], "2026-09-02T09:00:00Z", "2026-09-02T09:10:00Z",
                ),
                STAFF,
            ),
            201,
        )
        validate_success(api.submit_usage_log(log2["id"], STAFF), 200)
        return stack, b1, b2, log1, log2

    def test_increment_ceil_before_rate_and_consumables_last(self, api):
        """PRD §2.5: "In usage charging, the billing-increment ceiling is
        applied first (in whole minutes), the minimum-charge floor second, the
        multiplication by the hourly rate and its half-up rounding to cents
        third, and the consumables fee is added last and is never itself
        rounded." PRD §2.5: "Computing money from un-ceiled minutes, or
        rounding only the final verdict, yields different cent values and is
        non-conformant."

        Design: Difficulty/combinatorial_formula/usage_charge_nested_rounding_order
        """
        stack, b1, b2, log1, log2 = self._setup(api)
        v1 = validate_success(api.validate_usage_log(log1["id"], STAFF2), 200)
        assert v1["billable_minutes"] == 60, "ceil(47/15)*15 = 60"
        assert v1["usage_charge_cents"] == 12500, "60 x 200 + 500 consumable"
        booking = validate_success(api.get_booking(b1["id"], STAFF), 200)
        assert booking["estimated_charge_cents"] == 9400, (
            "provisional: 47 scheduled min x 200, no ceil"
        )

    def test_min_charge_floor_applies_after_ceil(self, api):
        """PRD §3.8: "`billable_minutes` is the actual minutes rounded *up* to
        the next whole multiple of the booking's `applied_increment_minutes`,
        then floored at `applied_min_charge_minutes` — the increment ceiling is
        applied first, the minimum-charge floor second."

        Design: Difficulty/combinatorial_formula/usage_charge_nested_rounding_order
        """
        stack, b1, b2, log1, log2 = self._setup(api)
        v1 = validate_success(api.validate_usage_log(log1["id"], STAFF2), 200)
        v2 = validate_success(api.validate_usage_log(log2["id"], STAFF2), 200)
        assert v2["billable_minutes"] == 30, "max(ceil(10/15)*15 = 15, 30) = 30"
        assert v2["usage_charge_cents"] == 6000, "30 x 200 = 6000"
        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_used_cents"] == 18500, "12500 + 6000"


class TestExternalRatePinning:
    def test_external_booking_pins_external_rate(self, api):
        """PRD §3.6: "On approval the booking pins its rate snapshot from that
        effective set: `rate_set_id`, `applied_rate_cents_per_hour` (the
        internal rate for `INTERNAL` bookers, the external rate otherwise),
        `applied_increment_minutes`, and `applied_min_charge_minutes`." and
        "For an internal booking, `encumbered_cents` is set equal to
        `estimated_charge_cents` and the grant's `budget_encumbered_cents`
        increases by that amount; for an external booking, `encumbered_cents`
        stays zero."

        Design: Corner/calculations/external_booking_pins_external_rate
        """
        stack = setup_canonical_stack()
        u2 = create_user(affiliation="EXTERNAL", full_name="Eve Ext",
                         email="eve@acme.com")
        enroll_and_certify(u2["id"], stack["i1"]["id"])
        bx = validate_success(
            api.create_booking(
                create_booking_payload(
                    u2["id"], stack["i1"]["id"],
                    start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T10:00:00Z",
                ),
                make_external_client_headers(u2["id"]),
            ),
            201,
        )
        approved = validate_success(api.approve_booking(bx["id"], STAFF), 200)
        assert approved["applied_rate_cents_per_hour"] == 18000, (
            "external booker pins the external rate"
        )
        assert approved["estimated_charge_cents"] == 18000, "60 min x 300 cents/min"
        assert approved["encumbered_cents"] == 0, "external bookings never encumber"
        assert approved["rate_set_id"] == stack["rs"]["id"]


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD §3.6: "For an internal booking, `encumbered_cents` is set equal
        to `estimated_charge_cents` and the grant's `budget_encumbered_cents`
        increases by that amount; for an external booking, `encumbered_cents`
        stays zero. The grant's status is recomputed." PRD §2.10:
        "`budget_available_cents` is `budget_total_cents` minus the encumbered
        and used sums".

        Design: Corner/consistency_model/immediate_read_after_write
        """
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)
        approved = validate_success(api.approve_booking(b1["id"], STAFF), 200)
        assert approved["status"] == "APPROVED"
        assert approved["estimated_charge_cents"] == 18000
        assert approved["encumbered_cents"] == 18000
        assert approved["rate_set_id"] == stack["rs"]["id"]

        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_encumbered_cents"] == 18000, (
            "the very next read reflects the encumbrance"
        )
        assert grant["budget_available_cents"] == 82000
