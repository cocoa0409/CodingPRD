"""Shrink periods: creation validation, disjoint closed intervals, OCC on
record-count, dual accrual bases, variance reconciliation with auto-case, and
store close gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    advance_case,
    attach_evidence,
    close_period,
    document_interview,
    get_case,
    get_period,
    hold_interview,
    make_admin_headers,
    make_analyst_headers,
    make_manager_headers,
    make_period,
    make_pos_feed_headers,
    make_store,
    make_store_with_period,
    post_event,
    reconcile_period,
    record_count,
    schedule_interview,
    set_clock,
    setup_case_closed_substantiated,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ADMIN_1, ANALYST_1, MANAGER_1, POS_FEED_1


class TestPeriodCreation:
    def test_period_book_inventory_zero_returns_invalid_request(self, api):
        """PRD §3.9: "An `LPAdmin` opens one with `store_id`, a `period_start`
        at the closed interval's start, a `period_end` at the closed interval's
        end that must be on or after the start (`ERR_INVALID_REQUEST`), the
        merchandising feed's `book_inventory_cents` (greater than zero), and
        `period_sales_cents` (zero or more)."

        Design: Corner/entities/period_book_inventory_zero_returns_invalid_request
        """
        store = make_store(store_number="S026", name="Store 26")
        resp = api.create_shrink_period(
            {"store_id": store["id"],
             "period_start": "2026-01-01T00:00:00Z",
             "period_end": "2026-03-31T23:59:59Z",
             "book_inventory_cents": 0, "period_sales_cents": 100},
            make_admin_headers(ADMIN_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_touching_period_rejected(self, api):
        """PRD §3.9: "Periods of the same store must be strictly disjoint:
        because the intervals are closed on both ends, even touching at an
        endpoint conflicts, and an overlapping or abutting new period fails
        with `ERR_PERIOD_OVERLAP`."

        P2's start equals P1's closed end (2026-03-31T23:59:59Z): touching
        closed intervals conflict.

        Design: Difficulty/resource_temporal_overlap/shrink_period_overlap_closed_interval_touching_rejected
        """
        store = make_store(store_number="S221", name="Store 221")
        make_period(store["id"], period_start="2026-01-01T00:00:00Z",
                    period_end="2026-03-31T23:59:59Z",
                    book_inventory_cents=1000000, period_sales_cents=1000000)
        resp = api.create_shrink_period(
            {"store_id": store["id"],
             "period_start": "2026-03-31T23:59:59Z",
             "period_end": "2026-06-30T23:59:59Z",
             "book_inventory_cents": 1000000, "period_sales_cents": 1000000},
            make_admin_headers(ADMIN_1),
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)

    def test_next_instant_period_accepted(self, api):
        """PRD §3.9: "Periods of the same store must be strictly disjoint:
        because the intervals are closed on both ends, even touching at an
        endpoint conflicts, and an overlapping or abutting new period fails
        with `ERR_PERIOD_OVERLAP`."
        PRD §3.9: "A new period starts `OPEN` with `known_loss_posted_cents` at
        zero; that figure then moves only when a case adjudication posts loss
        into the period or a reopen reverses one (§2.10)."

        Starting the next second after P1's closed end is disjoint.

        Design: Difficulty/resource_temporal_overlap/shrink_period_overlap_closed_interval_touching_rejected
        """
        store = make_store(store_number="S221", name="Store 221")
        p1 = make_period(store["id"], period_start="2026-01-01T00:00:00Z",
                         period_end="2026-03-31T23:59:59Z",
                         book_inventory_cents=1000000, period_sales_cents=1000000)
        p3 = make_period(store["id"], period_start="2026-04-01T00:00:00Z",
                         period_end="2026-06-30T23:59:59Z",
                         book_inventory_cents=1000000, period_sales_cents=1000000)
        assert p3["status"] == "OPEN"
        p1_after = get_period(p1["id"])
        assert p1_after["status"] == "OPEN"
        assert p1_after["known_loss_posted_cents"] == 0


class TestCountAndReconcile:
    def test_occ_record_count_stale_period_version(self, api):
        """PRD §2.8: "Recording a physical count requires the request to carry
        `expected_shrink_period_version` equal to the shrink period's current
        `version`. A mismatch is rejected with `ERR_STALE_PERIOD_VERSION`
        (HTTP 412). A recount on a `COUNTED` period legitimately supersedes the
        prior count, so a request carrying the current version succeeds; only a
        stale `expected_shrink_period_version` fails."
        PRD §3.9: "Recording against an `OPEN` period moves it to `COUNTED`;
        recording against a `COUNTED` period is a recount that supersedes the
        prior count in place. Either way `counted_at` is stamped from the
        logical clock and the period's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/occ_record_count_stale_period_version
        """
        store = make_store(store_number="S401", name="Store 401")
        period = make_period(store["id"])
        v0 = period["version"]
        counted = record_count(period["id"], 4950000,
                               expected_shrink_period_version=v0)
        assert counted["status"] == "COUNTED"
        assert counted["version"] == v0 + 1, "one increment per accepted count"
        resp = api.record_shrink_count(
            period["id"],
            {"counted_inventory_cents": 4940000,
             "expected_shrink_period_version": v0},
            make_admin_headers(ADMIN_1),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PERIOD_VERSION)
        recounted = record_count(period["id"], 4940000,
                                 expected_shrink_period_version=v0 + 1)
        assert recounted["counted_inventory_cents"] == 4940000
        assert recounted["status"] == "COUNTED"
        assert recounted["version"] == v0 + 2

    def test_period_reconcile_without_count_returns_count_required(self, api):
        """PRD §3.9: "Reconciling an `OPEN` period — one with no count yet —
        fails with `ERR_COUNT_REQUIRED`; reconciling a `COUNTED` period
        snapshots two figures: `variance_cents`, the counted inventory minus
        the loss-adjusted book (that is, `book_inventory_cents` minus
        `known_loss_posted_cents`), and `variance_pct`, the variance divided by
        `book_inventory_cents` rounded half up to four decimal places."

        Design: Corner/state_machines/period_reconcile_without_count_returns_count_required
        """
        store = make_store(store_number="S043", name="Store 43")
        period = make_period(store["id"], book_inventory_cents=1000000,
                             period_sales_cents=1000000)
        resp = api.reconcile_shrink_period(period["id"], make_admin_headers(ADMIN_1))
        validate_error(resp, ApiErrorId.ERR_COUNT_REQUIRED)
        assert get_period(period["id"])["status"] == "OPEN"

    def test_period_close_from_counted_returns_invalid_state(self, api):
        """PRD §3.9: "Finally, an administrator closes a `RECONCILED` period
        to `CLOSED`; remember from §3.1 that a store cannot close while any of
        its periods is `OPEN` or `COUNTED`."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        A count alone is not reconciliation.

        Design: Corner/state_machines/period_close_from_counted_returns_invalid_state
        """
        store = make_store(store_number="S044", name="Store 44")
        period = make_period(store["id"], book_inventory_cents=1000000,
                             period_sales_cents=1000000)
        record_count(period["id"], 999000)
        resp = api.close_shrink_period(period["id"], make_admin_headers(ADMIN_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAccrualBases:
    """One period read exposes both accrual variants over identical data."""

    def _setup_posted_period(self, api):
        """Store with period (book 10000000, sales 8000000); an EXTERNAL case
        with manual loss 150000 adjudicated SUBSTANTIATED (waived) at the
        default clock, posting 150000 into the period."""
        store = make_store(store_number="S101", name="Store 101")
        period = make_period(store["id"], book_inventory_cents=10000000,
                             period_sales_cents=8000000)
        ctx = setup_case_closed_substantiated(
            store["id"], manual_loss_cents=150000, evidence_type="PHOTO",
            captured_at="2026-07-20T09:00:00Z", retention_class="EXTENDED",
        )
        return store, period, ctx

    def test_case_basis_accrual_tracks_posted_loss(self, api):
        """PRD §3.9: "The case-posted basis, `accrual_case_basis_cents`, simply
        equals `known_loss_posted_cents`; it is the officially reported accrual
        while the period is `OPEN` or `COUNTED`, and it moves only with case
        activity."
        PRD §3.5: "The chosen period's `known_loss_posted_cents` rises by the
        posted amount, its case-basis accrual recomputes, the case records the
        target in `loss_posted_period_id`, and the store's
        `total_adjudicated_loss_cents` rises by the same amount."

        Design: Difficulty/dual_variant_calc/shrink_accrual_case_posted_vs_sales_ratio_same_period
        """
        _store, period, ctx = self._setup_posted_period(api)
        assert ctx["case"]["loss_posted_period_id"] == period["id"]
        assert ctx["case"]["loss_posted_cents"] == 150000
        p = get_period(period["id"])
        assert p["known_loss_posted_cents"] == 150000
        assert p["accrual_case_basis_cents"] == 150000

    def test_sales_basis_accrual_diverges_from_case_basis(self, api):
        """PRD §3.9: "The sales-ratio basis, `accrual_sales_basis_cents`, is
        the period's net sales multiplied by 0.0125 and rounded half up to
        whole cents; it is a comparative estimate, never the reported figure."

        Same period data: sales basis round_half_up(8000000 * 0.0125) = 100000
        while the case basis is 150000.

        Design: Difficulty/dual_variant_calc/shrink_accrual_case_posted_vs_sales_ratio_same_period
        """
        _store, period, _ctx = self._setup_posted_period(api)
        p = get_period(period["id"])
        assert p["accrual_sales_basis_cents"] == 100000
        assert p["accrual_case_basis_cents"] != p["accrual_sales_basis_cents"]

    def test_accrual_sales_ratio_half_cent_rounding(self, api):
        """PRD §3.9: "The sales-ratio basis, `accrual_sales_basis_cents`, is
        the period's net sales multiplied by 0.0125 and rounded half up to
        whole cents; it is a comparative estimate, never the reported figure."
        PRD §2.6: "Where a computation requires rounding, the method is always
        round half up: an alert's `score` is carried to 2 decimal places; a
        shrink period's `variance_pct` is carried to 4 decimal places; the
        percentage portions inside the statutory penalty tiers, the statutory
        penalty after its prior-offense multiplier, and the sales-basis accrual
        are each rounded half up to whole cents."

        Sales 8000120 -> 100001.50 rounds half up to 100002 (a floor would give
        100001); sales 8000100 -> 100001.25 rounds to 100001.

        Design: Corner/calculations/accrual_sales_ratio_half_cent_rounding
        """
        store = make_store(store_number="S054", name="Store 54")
        pa = make_period(store["id"], period_start="2026-01-01T00:00:00Z",
                         period_end="2026-03-31T23:59:59Z",
                         book_inventory_cents=5000000, period_sales_cents=8000120)
        pb = make_period(store["id"], period_start="2026-04-01T00:00:00Z",
                         period_end="2026-06-30T23:59:59Z",
                         book_inventory_cents=5000000, period_sales_cents=8000100)
        assert get_period(pa["id"])["accrual_sales_basis_cents"] == 100002
        assert get_period(pb["id"])["accrual_sales_basis_cents"] == 100001
        assert get_period(pa["id"])["accrual_case_basis_cents"] == 0
        assert get_period(pb["id"])["accrual_case_basis_cents"] == 0


class TestVarianceFeedbackLoop:
    """Reconcile breach spawns a SHRINK_VARIANCE case; its later adjudication
    posts to the period containing the adjudication date — never retroactively
    to the reconciled source period."""

    def _setup_reconciled_with_auto_case(self, api):
        store = make_store(store_number="S130", name="Store 130")
        p1 = make_period(store["id"], period_start="2026-07-01T00:00:00Z",
                         period_end="2026-09-30T23:59:59Z",
                         book_inventory_cents=10000000, period_sales_cents=8000000)
        p2 = make_period(store["id"], period_start="2026-10-01T00:00:00Z",
                         period_end="2026-12-31T23:59:59Z",
                         book_inventory_cents=9000000, period_sales_cents=7000000)
        # Counted 9750000 against book 10000000 with nothing posted:
        # variance 9750000 - (10000000 - 0) = -250000, pct -0.0250.
        record_count(p1["id"], 9750000)
        reconciled = reconcile_period(p1["id"])
        return store, p1, p2, reconciled

    def test_reconcile_breach_spawns_shrink_variance_case(self, api):
        """PRD §3.9: "When the absolute value of `variance_pct` is at least
        0.0200 — the boundary is inclusive — the system auto-creates a
        shrink-investigation case with `source` SHRINK_VARIANCE, `subject_type`
        UNKNOWN, `manual_loss_cents` set to the negation of `variance_cents`
        when the variance is negative and to zero otherwise, and status `OPEN`,
        and records it on the period as `auto_case_id`."
        PRD §3.9: "Reconciling an `OPEN` period — one with no count yet — fails
        with `ERR_COUNT_REQUIRED`; reconciling a `COUNTED` period snapshots two
        figures: `variance_cents`, the counted inventory minus the
        loss-adjusted book (that is, `book_inventory_cents` minus
        `known_loss_posted_cents`), and `variance_pct`, the variance divided by
        `book_inventory_cents` rounded half up to four decimal places."

        variance = 9750000 - (10000000 - 0) = -250000; pct -0.0250 breaches.

        Design: Difficulty/combinatorial_formula/shrink_variance_feedback_loop_pinned_order
        """
        _store, p1, _p2, reconciled = self._setup_reconciled_with_auto_case(api)
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["variance_cents"] == -250000
        assert reconciled["variance_pct"] == pytest.approx(-0.025, abs=1e-6)
        auto_case_id = reconciled["auto_case_id"]
        assert auto_case_id, "breach must auto-create a shrink-investigation case"
        auto_case = get_case(auto_case_id)
        assert auto_case["source"] == "SHRINK_VARIANCE"
        assert auto_case["subject_type"] == "UNKNOWN"
        assert auto_case["manual_loss_cents"] == 250000
        assert auto_case["status"] == "OPEN"

    def test_auto_case_loss_posts_to_current_period_not_reconciled_source(self, api):
        """PRD §3.9: "The evaluation order is pinned to break the apparent
        circularity — first the variance snapshot reads the live posted-loss
        figure, then the period transitions to `RECONCILED` and stops accepting
        loss postings, and the auto-case's eventual adjudication posts its loss
        to whichever period contains the adjudication date in `OPEN` or
        `COUNTED` status, never retroactively to this reconciled period."
        PRD §3.9: "The snapshot uses the period's live `known_loss_posted_cents`
        at the instant of the reconcile call."

        The auto-case is resolved to EXTERNAL (assign first, then
        resolve-subject while INVESTIGATING), walked through the pipeline, and
        adjudicated at clock 2026-10-15 — inside P2.

        Design: Difficulty/combinatorial_formula/shrink_variance_feedback_loop_pinned_order
        """
        _store, p1, p2, reconciled = self._setup_reconciled_with_auto_case(api)
        ac = reconciled["auto_case_id"]
        set_clock("2026-10-15T00:00:00Z")  # inside P2
        # Assign first (OPEN -> INVESTIGATING); resolve-subject is defined from
        # INVESTIGATING/READY_FOR_INTERVIEW per PRD §3.3.
        validate_success(api.assign_case(
            ac, {"analyst_id": ANALYST_1}, make_manager_headers(MANAGER_1)
        ))
        validate_success(api.resolve_case_subject(
            ac, {"subject_type": "EXTERNAL"}, make_manager_headers(MANAGER_1)
        ))
        attach_evidence(ac, ANALYST_1, evidence_type="TRANSACTION_LOG",
                        captured_at="2026-09-25T10:00:00Z",
                        retention_class="EXTENDED")
        advance_case(ac, ANALYST_1)
        interview = schedule_interview(
            ac, ANALYST_1, ANALYST_1,
            scheduled_start="2026-10-16T10:00:00Z",
            scheduled_end="2026-10-16T11:00:00Z",
        )
        hold_interview(interview["id"], ANALYST_1, outcome="DENIED")
        document_interview(interview["id"], ANALYST_1,
                           notes="Inventory variance review documented.")
        advance_case(ac, ANALYST_1)
        case = adjudicate_case(ac, MANAGER_1, decision="SUBSTANTIATED",
                               restitution_waived=True)
        assert case["status"] == "CLOSED_SUBSTANTIATED"
        assert case["loss_posted_period_id"] == p2["id"]
        p2_after = get_period(p2["id"])
        assert p2_after["known_loss_posted_cents"] == 250000
        p1_after = get_period(p1["id"])
        assert p1_after["known_loss_posted_cents"] == 0, (
            "reconciled source period never retro-adjusted"
        )
        assert p1_after["variance_cents"] == -250000, "snapshot immutable"
        assert p1_after["status"] == "RECONCILED"


class TestStoreClose:
    def test_store_close_blocked_by_open_period_then_children_rejected(self, api):
        """PRD §3.1: "When a banner closes, the same administrator closes the
        store; the close is refused with `ERR_PERIOD_LOCKED` while any shrink
        period of that store is still `OPEN` or `COUNTED`, and with
        `ERR_INVALID_STATE_TRANSITION` when the store is not `ACTIVE`. Once a
        store reaches `CLOSED`, it refuses all new child records: registering
        an employee, ingesting an exception event, creating a case, or opening
        a shrink period against a closed store fails with `ERR_STORE_CLOSED`."

        The counted/reconciled variance here is -10000 on book 1000000 ->
        variance_pct -0.01, below the 0.0200 breach, so no auto-case appears.

        Design: Corner/errors/store_close_blocked_by_open_period_then_children_rejected
        """
        store = make_store(store_number="S081", name="Store 81")
        period = make_period(store["id"], period_start="2026-01-01T00:00:00Z",
                             period_end="2026-03-31T23:59:59Z",
                             book_inventory_cents=1000000,
                             period_sales_cents=1000000)
        resp1 = api.close_store(store["id"], make_admin_headers(ADMIN_1))
        validate_error(resp1, ApiErrorId.ERR_PERIOD_LOCKED)
        record_count(period["id"], 990000)
        reconciled = reconcile_period(period["id"])
        assert reconciled["variance_cents"] == -10000
        assert reconciled["variance_pct"] == pytest.approx(-0.01, abs=1e-6)
        assert reconciled.get("auto_case_id") in (None, ""), "below breach: no auto-case"
        close_period(period["id"])
        closed = validate_success(api.close_store(store["id"], make_admin_headers(ADMIN_1)))
        assert closed["status"] == "CLOSED"
        resp2 = api.create_exception_event(
            {"store_id": store["id"], "register_ref": "R1", "txn_ref": "T1",
             "exception_type": "NO_SALE_DRAWER", "amount_cents": 100,
             "occurred_at": "2026-07-10T10:00:00Z"},
            make_pos_feed_headers(POS_FEED_1),
        )
        validate_error(resp2, ApiErrorId.ERR_STORE_CLOSED)
