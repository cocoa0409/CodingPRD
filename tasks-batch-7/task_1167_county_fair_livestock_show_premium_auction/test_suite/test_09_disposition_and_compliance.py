"""Disposition logistics and health compliance: maker-checker segregation,
type/status compatibility, completion gates (health, withdrawal, schedule),
the logical clock boundary, affidavit uniqueness, and order rejection
(PRD §2.6, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_posture,
    api_client,
    approve_disposition,
    build_show_state,
    complete_disposition,
    create_affidavit_payload,
    create_disposition,
    create_exhibitor,
    create_fair,
    create_verified_entry,
    get_disposition,
    get_entry,
    make_admin_headers,
    make_exhibitor_headers,
    reject_disposition,
    set_clock,
    setup_approved_disposition,
    setup_sold_lot,
    sign_affidavit,
    validate_error,
)

ADMIN = TEST_USERS["admin"]


class TestAffidavitUniqueness:
    def test_affidavit_duplicate_returns_error(self, api):
        """PRD §3.8: "The drug-free affidavit is signed once per entry — a
        second affidavit for the same entry is rejected with
        `ERR_AFFIDAVIT_EXISTS` (HTTP 409)."

        Design: Corner/validations/affidavit_duplicate_returns_error
        """
        fair = create_fair(name="Fair V9")
        advance_posture(fair["id"], "ENTRIES_OPEN")
        exhibitor = create_exhibitor(fair["id"])
        entry = create_verified_entry(
            fair["id"], exhibitor, species="MARKET_GOAT", tag_number="G-001"
        )
        sign_affidavit(entry["id"], exhibitor)
        resp = api_client.create_affidavit(
            create_affidavit_payload(entry["id"]),
            make_exhibitor_headers(exhibitor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AFFIDAVIT_EXISTS)


class TestDispositionSegregation:
    def _shown_lamb_with_return_order(self, name):
        """SHOWN lamb with SIGNED affidavit and a REQUESTED RETURN order
        created by admin-a."""
        ctx = build_show_state(
            fair_overrides={"name": name},
            entries=[{"species": "MARKET_LAMB", "tag_number": "L-001",
                      "weight_lbs": 100}],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[{"qualified_species": ["MARKET_LAMB"]}],
            slots=[{"class_index": 0, "judge_index": 0}],
            placings=[{"slot_index": 0,
                       "lines": [{"entry_index": 0, "rank": 1,
                                  "award": "NONE"}]}],
            affidavit_entries=[0],
            advance_to="SHOWING",
        )
        entry_id = ctx["entries"][0]["id"]
        order = create_disposition(
            entry_id, creator_headers=make_admin_headers("admin-a"),
            disposition_type="RETURN", destination="Home Farm",
        )
        return ctx, entry_id, order

    def test_segregation_of_duties_disposition_maker_cannot_approve(self, api):
        """PRD §3.8: "Approval is a `FairBoardAdmin` checker step on a
        `REQUESTED` order, and its checks fire in order: the entry must carry
        a `SIGNED` affidavit (else `ERR_AFFIDAVIT_MISSING`) — the same
        requirement that guards premium approval — then the approver must
        differ from `created_by_user_id` unless the creator is `SYSTEM` (else
        `ERR_SEGREGATION_OF_DUTIES`), then type compatibility."

        Design: Corner/rbac/segregation_of_duties_disposition_maker_cannot_approve
        """
        _ctx, _entry_id, order = self._shown_lamb_with_return_order("Fair B5")

        maker = api_client.approve_disposition(
            order["id"], make_admin_headers("admin-a")
        )
        validate_error(maker, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_disposition(order["id"])["status"] == "REQUESTED"

        checker = approve_disposition(order["id"], approver_id="admin-b")
        assert checker["status"] == "APPROVED"
        assert checker["approved_by_user_id"] == "admin-b"

    def test_disposition_reject_then_fresh_order(self, api):
        """PRD §3.8: "Rejection supplies a `reason`, sets `reject_reason`, and
        moves the order `REQUESTED` → `REJECTED`."
        PRD §3.8: "An order is requested for an `entry_id` with a
        `disposition_type` of `HARVEST` or `RETURN`, an optional `destination`,
        and an optional `scheduled_date`; it starts `REQUESTED` with
        `created_by_user_id` set to the caller, or to `SYSTEM` when the sale
        cascade auto-creates it."

        Design: Corner/state_machines/disposition_reject_then_fresh_order
        """
        ctx, entry_id, order = self._shown_lamb_with_return_order("Fair S10")

        rejected = reject_disposition(
            order["id"], "incomplete paperwork", approver_id="admin-b"
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "incomplete paperwork"

        fresh = create_disposition(
            entry_id, creator_headers=make_admin_headers("admin-a"),
            disposition_type="RETURN", destination="Home Farm",
        )
        assert fresh["status"] == "REQUESTED", (
            "REJECTED is terminal for the order, not for the entry"
        )
        approved = approve_disposition(fresh["id"], approver_id="admin-b")
        assert approved["status"] == "APPROVED"


class TestDispositionTypeCompatibility:
    def test_return_disposition_on_sold_entry_rejected(self, api):
        """PRD §3.8: "Type compatibility is enforced at request time, again at
        approval, and again at completion against the entry's then-current
        status: `HARVEST` requires the entry to be `SOLD` or `NOT_SOLD`, and
        `RETURN` requires `SHOWN`, `NOT_SOLD`, or `DISQUALIFIED`; any mismatch
        is rejected with `ERR_DISPOSITION_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/validations/return_disposition_on_sold_entry_rejected
        """
        ctx = setup_sold_lot(fair_overrides={"name": "Fair V20"},
                             hammer_price_cents=50000)
        entry_id = ctx["entries"][0]["id"]
        assert get_entry(entry_id)["status"] == "SOLD"

        resp = api_client.create_disposition(
            {"entry_id": entry_id, "disposition_type": "RETURN",
             "destination": "Home Farm"},
            make_admin_headers("admin-a"),
        )
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_NOT_ALLOWED)


class TestDispositionCompletionGates:
    def test_disposition_complete_health_hold_beats_withdrawal_window(self, api):
        """PRD §3.8: "The latest health inspection for the entry, by
        `created_at`, must exist and be `PASS` — no inspection at all, or a
        latest of `QUARANTINE` or `FAIL`, is rejected with `ERR_HEALTH_HOLD`
        (HTTP 409). For `HARVEST` only, the affidavit's `withdrawal_end_date`
        must be null or the current logical time must be at or past it — a
        logical time strictly earlier is rejected with
        `ERR_WITHDRAWAL_NOT_CLEARED` (HTTP 409)."
        PRD §3.8: "Completing an `APPROVED` order is the last mile, and four
        gates stand in front of it, evaluated in order."

        Design: Difficulty/priority_pair_validation_conflict/disposition_complete_health_hold_beats_withdrawal_window
        """
        ctx = setup_approved_disposition(
            fair_overrides={"name": "Fair R5B"},
            entry_status_path="not_sold", disposition_type="HARVEST",
            withdrawal_end_date="2026-09-01T00:00:00Z",
            inspection_result="QUARANTINE",
        )
        # Both the health hold (latest QUARANTINE) and the withdrawal window
        # (logical clock 2026-05-01 < 2026-09-01) are violated; the earlier
        # gate wins.
        resp = api_client.complete_disposition(
            ctx["disposition"]["id"], make_admin_headers("admin-b")
        )
        validate_error(resp, ApiErrorId.ERR_HEALTH_HOLD)
        assert get_disposition(ctx["disposition"]["id"])["status"] == "APPROVED"

    def test_disposition_complete_health_hold_without_any_inspection(self, api):
        """PRD §3.8: "The latest health inspection for the entry, by
        `created_at`, must exist and be `PASS` — no inspection at all, or a
        latest of `QUARANTINE` or `FAIL`, is rejected with `ERR_HEALTH_HOLD`
        (HTTP 409)."
        PRD §3.8: "Completing an `APPROVED` order is the last mile, and four
        gates stand in front of it, evaluated in order."

        Design: Difficulty/priority_pair_validation_conflict/disposition_complete_health_hold_beats_withdrawal_window
        """
        ctx = setup_approved_disposition(
            fair_overrides={"name": "Fair R5B-none"},
            entry_status_path="not_sold", disposition_type="HARVEST",
            withdrawal_end_date="2026-09-01T00:00:00Z",
            inspection_result=None,
        )
        resp = api_client.complete_disposition(
            ctx["disposition"]["id"], make_admin_headers("admin-b")
        )
        validate_error(resp, ApiErrorId.ERR_HEALTH_HOLD)
        assert get_disposition(ctx["disposition"]["id"])["status"] == "APPROVED"

    def test_withdrawal_window_blocks_then_clock_clears_harvest_complete(self, api):
        """PRD §3.8: "For `HARVEST` only, the affidavit's
        `withdrawal_end_date` must be null or the current logical time must be
        at or past it — a logical time strictly earlier is rejected with
        `ERR_WITHDRAWAL_NOT_CLEARED` (HTTP 409)."
        PRD §3.8: "Completion moves the order to `COMPLETED`, and when the
        entry is `SOLD` or `NOT_SOLD` the entry itself moves to `CLEARED`."
        PRD §2.6: "The clock's startup default, before it is ever set, is
        exactly 2026-05-01T00:00:00Z, and the clock never falls back to
        wall-clock time on its own."

        Design: Corner/validations/withdrawal_window_blocks_then_clock_clears_harvest_complete
        """
        ctx = setup_approved_disposition(
            fair_overrides={"name": "Fair V18"},
            entry_status_path="not_sold", disposition_type="HARVEST",
            withdrawal_end_date="2026-09-01T00:00:00Z",
            inspection_result="PASS",
        )
        order_id = ctx["disposition"]["id"]
        entry_id = ctx["entries"][0]["id"]

        blocked = api_client.complete_disposition(
            order_id, make_admin_headers("admin-b")
        )
        validate_error(blocked, ApiErrorId.ERR_WITHDRAWAL_NOT_CLEARED)

        set_clock("2026-09-01T00:00:00Z")
        completed = complete_disposition(order_id, admin_id="admin-b")
        assert completed["status"] == "COMPLETED", (
            "logical time exactly at withdrawal_end_date is at-or-past it"
        )
        assert get_entry(entry_id)["status"] == "CLEARED", (
            "NOT_SOLD entry moves to CLEARED on harvest completion"
        )

    def test_disposition_complete_before_scheduled_date_returns_too_early(self, api):
        """PRD §3.8: "The `scheduled_date` must be null or the current logical
        time must be at or past it, else `ERR_DISPOSITION_TOO_EARLY`
        (HTTP 409)."
        PRD §3.8: "Completion moves the order to `COMPLETED`, and when the
        entry is `SOLD` or `NOT_SOLD` the entry itself moves to `CLEARED`."

        Design: Corner/validations/disposition_complete_before_scheduled_date_returns_too_early
        """
        ctx = setup_approved_disposition(
            fair_overrides={"name": "Fair V19"},
            entry_status_path="shown", disposition_type="RETURN",
            scheduled_date="2027-01-01T00:00:00Z",
            inspection_result="PASS",
        )
        order_id = ctx["disposition"]["id"]
        entry_id = ctx["entries"][0]["id"]

        blocked = api_client.complete_disposition(
            order_id, make_admin_headers("admin-b")
        )
        validate_error(blocked, ApiErrorId.ERR_DISPOSITION_TOO_EARLY)

        set_clock("2027-01-01T00:00:00Z")
        completed = complete_disposition(order_id, admin_id="admin-b")
        assert completed["status"] == "COMPLETED"
        assert get_entry(entry_id)["status"] == "SHOWN", (
            "CLEARED applies only to SOLD or NOT_SOLD entries"
        )
