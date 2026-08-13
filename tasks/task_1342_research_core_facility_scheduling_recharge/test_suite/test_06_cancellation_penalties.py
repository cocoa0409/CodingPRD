"""Cancellation and no-show penalties: tiered branches, the free-window
boundary, and the full-estimate no-show branch (PRD §3.7)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, make_researcher_headers,
    setup_canonical_stack, create_booking_request, create_approved_booking,
    open_batch, set_clock, get_booking, get_grant, find_entries,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestTieredBranching:
    def _setup(self, api):
        """b1 APPROVED 2026-09-01 (estimate 18000); b2 REQUESTED 2026-09-03;
        batch 2026-09 OPEN; clock moved to 2026-08-31T10:00 (23 h before b1)."""
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        b2 = create_booking_request(
            stack, start_at="2026-09-03T09:00:00Z", end_at="2026-09-03T10:30:00Z"
        )
        batch = open_batch(2026, 9)
        set_clock("2026-08-31T10:00:00Z")
        return stack, b1, b2, batch

    def test_requested_cancel_free_and_late_approved_cancel_penalty(self, api):
        """PRD §3.7: "Cancelling a `REQUESTED` booking is always free:
        `penalty_cents` becomes zero." and "Otherwise, notice is the
        whole-minute difference between `start_at` and the current logical
        time; when that notice is at least the instrument's
        `cancellation_free_notice_hours` converted to minutes, the cancellation
        is free (notice exactly equal to the free window is free — the
        comparison is inclusive). Inside the window, `penalty_cents` is the
        booking's `estimated_charge_cents` multiplied by the instrument's
        `late_cancel_penalty_pct`, rounded half-up to cents."

        Design: Difficulty/combinatorial_formula/cancellation_penalty_tiered_branching
        """
        stack, b1, b2, batch = self._setup(api)
        owner = make_researcher_headers(stack["u1"]["id"])

        cancelled_requested = validate_success(api.cancel_booking(b2["id"], owner), 200)
        assert cancelled_requested["status"] == "CANCELLED"
        assert cancelled_requested["penalty_cents"] == 0

        # 23 h notice < 24 h free window: round_half_up(18000 x 0.5) = 9000.
        cancelled_approved = validate_success(api.cancel_booking(b1["id"], owner), 200)
        assert cancelled_approved["status"] == "CANCELLED"
        assert cancelled_approved["penalty_cents"] == 9000
        assert cancelled_approved["penalty_waived"] is False

    def test_penalty_entry_posts_and_grant_ledger_moves(self, api):
        """PRD §3.7: "Whenever `penalty_cents` exceeds zero, a `PENALTY`
        `RechargeEntry` — with `amount_cents` equal to the penalty,
        `subsidy_offset_cents` zero, and `net_amount_cents` equal to the
        penalty — posts into the currently `OPEN` `RechargeBatch` (none open
        means `ERR_BATCH_NOT_OPEN`), debiting the grant or, for external users,
        accruing to their invoice." and "The booking's grant encumbrance is
        released on any cancellation from `APPROVED`: the grant's
        `budget_encumbered_cents` drops by the booking's `encumbered_cents`,
        the booking's `encumbered_cents` zeroes, and the grant's status is
        recomputed."

        Design: Difficulty/combinatorial_formula/cancellation_penalty_tiered_branching
        """
        stack, b1, b2, batch = self._setup(api)
        owner = make_researcher_headers(stack["u1"]["id"])
        validate_success(api.cancel_booking(b2["id"], owner), 200)
        validate_success(api.cancel_booking(b1["id"], owner), 200)

        penalties = find_entries(booking_id=b1["id"], kind="PENALTY")
        assert len(penalties) == 1, f"exactly one PENALTY entry: {penalties!r}"
        entry = penalties[0]
        assert entry["batch_id"] == batch["id"]
        assert entry["amount_cents"] == 9000
        assert entry["subsidy_offset_cents"] == 0
        assert entry["net_amount_cents"] == 9000

        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_used_cents"] == 9000, (
            "the penalty debits the grant (PENDING USAGE/PENALTY counts as used)"
        )
        assert grant["budget_encumbered_cents"] == 0


class TestFreeWindowBoundary:
    def _setup(self, api):
        """b1 APPROVED 2026-09-01 09:00; b2 APPROVED 2026-09-02 09:00; batch
        2026-09 OPEN. Both estimates are 18000."""
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        b2 = create_approved_booking(
            stack, start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T10:30:00Z"
        )
        batch = open_batch(2026, 9)
        return stack, b1, b2, batch

    def test_notice_exactly_at_free_window_is_free(self, api):
        """PRD §3.7: "when that notice is at least the instrument's
        `cancellation_free_notice_hours` converted to minutes, the cancellation
        is free (notice exactly equal to the free window is free — the
        comparison is inclusive)."

        Design: Difficulty/boundary_precision_check/penalty_free_window_exact_boundary
        """
        stack, b1, b2, batch = self._setup(api)
        owner = make_researcher_headers(stack["u1"]["id"])
        set_clock("2026-08-31T09:00:00Z")  # exactly 1440 minutes before start
        cancelled = validate_success(api.cancel_booking(b1["id"], owner), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 0, (
            "notice exactly equal to the 24 h free window is free (>= semantics)"
        )

    def test_notice_one_minute_inside_window_charges_full_penalty(self, api):
        """PRD §3.7: "Inside the window, `penalty_cents` is the booking's
        `estimated_charge_cents` multiplied by the instrument's
        `late_cancel_penalty_pct`, rounded half-up to cents." and "Whenever
        `penalty_cents` exceeds zero, a `PENALTY` `RechargeEntry` — with
        `amount_cents` equal to the penalty, `subsidy_offset_cents` zero, and
        `net_amount_cents` equal to the penalty — posts into the currently
        `OPEN` `RechargeBatch` (none open means `ERR_BATCH_NOT_OPEN`), debiting
        the grant or, for external users, accruing to their invoice."

        Design: Difficulty/boundary_precision_check/penalty_free_window_exact_boundary
        """
        stack, b1, b2, batch = self._setup(api)
        owner = make_researcher_headers(stack["u1"]["id"])
        # 2026-09-01T09:00:01Z is 1439 whole minutes before b2's start.
        set_clock("2026-09-01T09:00:01Z")
        cancelled = validate_success(api.cancel_booking(b2["id"], owner), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 9000, (
            "1439 < 1440 minutes: round_half_up(18000 x 0.5) = 9000"
        )
        penalties = find_entries(batch_id=batch["id"], kind="PENALTY")
        assert len(penalties) == 1 and penalties[0]["amount_cents"] == 9000, (
            f"exactly one 9000-cent PENALTY entry must exist: {penalties!r}"
        )


class TestNoShow:
    def test_no_show_penalty_full_estimate(self, api):
        """PRD §3.7: "Marking a no-show is permitted only once the current
        logical time has passed `start_at`; it sets the booking to `NO_SHOW`,
        computes `penalty_cents` as the instrument's `no_show_penalty_pct`
        multiplied by `estimated_charge_cents` rounded half-up to cents with
        `penalty_waived` false, releases the encumbrance, and posts a `PENALTY`
        entry to the open batch exactly as on cancellation when the penalty
        exceeds zero."

        Design: Corner/calculations/no_show_penalty_full_estimate
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)  # estimate 18000
        batch = open_batch(2026, 9)
        set_clock("2026-09-01T10:00:00Z")  # past start, no check-in
        marked = validate_success(api.no_show_booking(b1["id"], STAFF), 200)
        assert marked["status"] == "NO_SHOW"
        assert marked["penalty_cents"] == 18000, "no_show_penalty_pct 1.0 x 18000"
        assert marked["penalty_waived"] is False

        penalties = find_entries(booking_id=b1["id"], kind="PENALTY")
        assert len(penalties) == 1
        assert penalties[0]["batch_id"] == batch["id"]
        assert penalties[0]["amount_cents"] == 18000
        assert penalties[0]["subsidy_offset_cents"] == 0, (
            "penalties are never subsidized (PRD §3.8)"
        )

        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_encumbered_cents"] == 0, "encumbrance released"
        assert grant["budget_used_cents"] == 18000
