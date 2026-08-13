"""Entitlement gate boundaries, confirmation gates, notice tiers, contract-year rollover."""
import pytest

from test_helpers import (
    ApiErrorId,
    cancel_booking_ok,
    create_booking_ok,
    create_completed_booking,
    create_confirmed_booking,
    create_aircraft,
    get_booking,
    get_owner,
    get_share,
    make_owner_headers,
    set_clock,
    setup_owner_with_past_due_invoice,
    setup_program_with_share,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestEntitlementExactEquality:
    def test_exact_equality_confirm_succeeds_and_drains_to_zero(self, api):
        """PRD §3.3: "The entitlement gate then demands that `hours_remaining_cy` be at
        least `estimated_block_hours` — exact equality is permitted and simply drains the
        balance to zero — and a shortfall is rejected with `ERR_ENTITLEMENT_EXHAUSTED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/entitlement_exact_equality_confirm_allowed
        """
        sc = setup_program_with_share(
            program_code="FJX-BP1", class_code="LIGHT", fraction=(1, 16),
            purchase_price_cents=1200000,
        )
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        # 1/16 of 800 = exactly 50.00 hours of entitlement
        booking = create_booking_ok(
            share["id"], owner["id"], cls["id"],
            "2026-09-10T15:00:00Z", 50.00, expected_share_version=share["version"],
        )
        resp = api.confirm_booking(booking["id"], make_owner_headers(owner["id"]))
        data = validate_success(resp, 200)
        assert data["booking_status"] == "CONFIRMED", "exact equality must confirm"
        remaining = get_share(share["id"])["hours_remaining_cy"]
        assert remaining == pytest.approx(0.00, abs=0.005), (
            f"exact-equality confirm must drain the balance to zero, got {remaining}"
        )

    def test_zero_balance_rejects_further_confirm(self, api):
        """PRD §3.3: "The entitlement gate then demands that `hours_remaining_cy` be at
        least `estimated_block_hours` — exact equality is permitted and simply drains the
        balance to zero — and a shortfall is rejected with `ERR_ENTITLEMENT_EXHAUSTED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/entitlement_exact_equality_confirm_allowed
        """
        sc = setup_program_with_share(
            program_code="FJX-BP1B", class_code="LIGHT", fraction=(1, 16),
            purchase_price_cents=1200000,
        )
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        booking_a = create_confirmed_booking(
            share["id"], owner["id"], cls["id"],
            "2026-09-10T15:00:00Z", 50.00,
        )
        assert booking_a["booking_status"] == "CONFIRMED"
        assert get_share(share["id"])["hours_remaining_cy"] == pytest.approx(0.00, abs=0.005)

        booking_b = create_booking_ok(
            share["id"], owner["id"], cls["id"], "2026-09-12T15:00:00Z", 0.01,
        )
        resp = api.confirm_booking(booking_b["id"], make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_EXHAUSTED)
        assert resp.status_code == 422, "0.01h against a 0.00 balance is a shortfall"


class TestStateBeatsFiscalAtConfirm:
    def test_confirm_cancelled_booking_reports_state_error_not_fiscal(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and a
        failure at any stage reports that stage's error and masks all later stages."
        PRD §2.8: "The target entity is in a state that permits the requested transition
        — otherwise `ERR_INVALID_STATE` (HTTP 409); attempts to move an entity that has
        already reached a terminal state are rejected with `ERR_ALREADY_TERMINAL`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_vs_fiscal_priority
        """
        sc = setup_program_with_share(
            program_code="FJX-PP1", class_code="LIGHT", fraction=(1, 16),
            purchase_price_cents=1200000,
        )
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        # 60.00h against a 50.00h entitlement: the fiscal gate would fail too,
        # but the booking is first cancelled so the state stage must fire.
        booking = create_booking_ok(
            share["id"], owner["id"], cls["id"],
            "2026-09-10T15:00:00Z", 60.00, expected_share_version=share["version"],
        )
        cancel_booking_ok(booking["id"], owner["id"])
        resp = api.confirm_booking(booking["id"], make_owner_headers(owner["id"]))
        outcome = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
        )
        assert resp.status_code == 409, (
            f"the state stage (409) masks the fiscal stage (422); got {resp.status_code} "
            f"with {outcome}"
        )
        assert get_share(share["id"])["hours_remaining_cy"] == pytest.approx(50.00, abs=0.005), (
            "no debit may be attempted when the state stage rejects the confirm"
        )

    def test_confirm_shortfall_reports_entitlement_when_state_valid(self, api):
        """PRD §3.3: "The entitlement gate then demands that `hours_remaining_cy` be at
        least `estimated_block_hours` — exact equality is permitted and simply drains the
        balance to zero — and a shortfall is rejected with `ERR_ENTITLEMENT_EXHAUSTED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_vs_fiscal_priority
        """
        sc = setup_program_with_share(
            program_code="FJX-PP1C", class_code="LIGHT", fraction=(1, 16),
            purchase_price_cents=1200000,
        )
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        # REQUESTED booking (state stage passes) with a 60.00h estimate vs 50.00h
        booking = create_booking_ok(
            share["id"], owner["id"], cls["id"],
            "2026-09-10T15:00:00Z", 60.00, expected_share_version=share["version"],
        )
        resp = api.confirm_booking(booking["id"], make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_EXHAUSTED)
        assert resp.status_code == 422
        assert get_booking(booking["id"])["booking_status"] == "REQUESTED"
        assert get_share(share["id"])["hours_remaining_cy"] == pytest.approx(50.00, abs=0.005)


class TestOwnerStandingGate:
    def test_delinquent_owner_confirm_blocked(self, api):
        """PRD §2.8: "The owner-standing gate, applied to booking confirmation (the
        confirming owner must stand `GOOD`) and listing acceptance (the buyer must stand
        `GOOD`) — otherwise `ERR_OWNER_STANDING_BLOCKS` (HTTP 422)."
        PRD §2.10: "The moment any invoice of theirs enters `PAST_DUE`, standing degrades
        automatically to `DELINQUENT`, and booking confirmation is rejected while that
        standing holds."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_by_owner_standing
        """
        sc = setup_owner_with_past_due_invoice(program_code="FJX-CE1")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        assert owner["owner_standing"] == "DELINQUENT"
        booking = create_booking_ok(
            share["id"], owner["id"], cls["id"], "2026-11-15T15:00:00Z", 1.00,
        )
        resp = api.confirm_booking(booking["id"], make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNER_STANDING_BLOCKS)
        assert resp.status_code == 422
        assert get_booking(booking["id"])["booking_status"] == "REQUESTED"
        assert get_share(share["id"])["hours_remaining_cy"] == pytest.approx(100.00, abs=0.005)

    def test_suspended_owner_confirm_blocked(self, api):
        """PRD §2.8: "The owner-standing gate, applied to booking confirmation (the
        confirming owner must stand `GOOD`) and listing acceptance (the buyer must stand
        `GOOD`) — otherwise `ERR_OWNER_STANDING_BLOCKS` (HTTP 422)."
        PRD §2.10: "A `ProgramAdmin` may suspend an owner who stands `GOOD` or
        `DELINQUENT`; suspension blocks booking activity across every share that owner
        holds."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_by_owner_standing
        """
        sc = setup_program_with_share(program_code="FJX-CE1B", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        booking = create_booking_ok(
            share["id"], owner["id"], cls["id"], "2026-09-10T15:00:00Z", 1.00,
            expected_share_version=share["version"],
        )
        resp = api.suspend_owner(owner["id"], ADMIN)
        assert resp.status_code == 200, f"Setup step failed: {resp.text}"
        assert get_owner(owner["id"])["owner_standing"] == "SUSPENDED"
        resp = api.confirm_booking(booking["id"], make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNER_STANDING_BLOCKS)
        assert resp.status_code == 422
        assert get_booking(booking["id"])["booking_status"] == "REQUESTED"


class TestNoticeTierBoundaries:
    def test_notice_tier_at_72h_and_168h_boundaries(self, api):
        """PRD §3.3: "fewer than 72 hours between the confirm-time clock and the
        scheduled departure classifies as `TIER_24H`, at least 72 hours but fewer than
        168 hours classifies as `TIER_72H`, and 168 hours or more classifies as
        `TIER_7D`. A booking confirmed exactly 72 hours before departure lands in
        `TIER_72H`, and one confirmed exactly 168 hours out lands in `TIER_7D`."

        Design: Corner/calculations/notice_tier_boundary_72h_and_168h
        """
        sc = setup_program_with_share(
            program_code="FJX-CA1", class_code="MID", fraction=(1, 4),
            purchase_price_cents=24000000,
        )
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        # Confirm-time clock is the startup default 2026-08-01T00:00:00Z.
        cases = [
            ("2026-08-03T23:59:24Z", "TIER_24H"),   # 71.99h of notice
            ("2026-08-04T00:00:00Z", "TIER_72H"),   # exactly 72h
            ("2026-08-08T00:00:00Z", "TIER_7D"),    # exactly 168h
        ]
        for departure, expected_tier in cases:
            booking = create_confirmed_booking(
                share["id"], owner["id"], cls["id"], departure, 1.00,
            )
            assert booking["notice_tier"] == expected_tier, (
                f"departure {departure} should classify as {expected_tier}, "
                f"got {booking['notice_tier']}"
            )


class TestContractYearRollover:
    def test_rollover_resets_hours_and_increments_year_index(self, api):
        """PRD §2.4: "When the clock crosses a program's contract-year anniversary — the
        first day of the month named by the program's `contract_year_start_month`, at
        00:00 UTC — every share of that program in `ACTIVE` status rolls into a new
        contract year. The share's `contract_year_index` increments by one, and its
        `hours_remaining_cy` is reset to the full `annual_entitlement_hours`. Unused
        hours never carry over into the new contract year."

        Design: Corner/calculations/contract_year_rollover_resets_hours
        """
        sc = setup_program_with_share(program_code="FJX-CA6", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        tail = create_aircraft(sc["program"]["id"], cls["id"], tail_number="N444CA")
        # Consume 10.00h of the 100.00h entitlement in contract year 0
        _booking, _leg = create_completed_booking(
            share["id"], owner["id"], cls["id"], tail["id"],
            "2026-09-10T15:00:00Z", 10.00, 10.00,
        )
        mid = get_share(share["id"])
        assert mid["hours_remaining_cy"] == pytest.approx(90.00, abs=0.005)
        assert mid["contract_year_index"] == 0

        set_clock("2027-08-01T00:00:00Z")  # cross the August anniversary
        after = get_share(share["id"])
        assert after["contract_year_index"] == 1, (
            f"anniversary crossing must increment contract_year_index, got {after['contract_year_index']}"
        )
        assert after["hours_remaining_cy"] == pytest.approx(100.00, abs=0.005), (
            "the 90.00h balance must reset to the full 100.00h entitlement; "
            "unused hours never carry over"
        )
