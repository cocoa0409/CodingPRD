"""Reconciliation periods, billing-basis variants, tolerance gate, and the
reopen-recompute loop."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_reconciliation,
    create_reconciliation_payload,
    ApiErrorId, make_billing_headers,
    setup_live_line_item, post_snapshot, void_snapshot,
    create_reconciliation, create_and_reconcile, transition_reconciliation,
    get_line_item,
    file_verification_report, propose_make_good, decide_make_good,
)


def _live_with_snapshot(snapshot_impressions=40000, snapshot_clicks=200,
                        billing_basis="LOWER_OF", snapshot_date="2026-08-05",
                        flight_end="2026-08-10"):
    """LIVE line item (goal 100000 @ cpm 500) with one POSTED snapshot."""
    ctx = setup_live_line_item(
        io_overrides={"flight_start": "2026-08-01", "flight_end": flight_end,
                      "billing_basis": billing_basis},
        li_overrides={"goal_impressions": 100000, "cpm_rate_cents": 500,
                      "start_date": "2026-08-01", "end_date": flight_end})
    li_id = ctx["line_item"]["id"]
    post_snapshot(li_id, snapshot_date, snapshot_impressions, snapshot_clicks)
    return ctx, li_id


class TestBillingBasisVariants:
    def test_agency_platform_bills_agency_despite_discrepancy(self, api):
        """PRD §3.6: "Under `AGENCY_PLATFORM` it is the agency ad-server
        number, whatever the tag counted. Under `THIRD_PARTY_TAG` it is the
        third-party tag number, whatever the agency counted."
        PRD §3.6: "`billable_cents` is then `billing_impressions` multiplied
        by the line item's `cpm_rate_cents`, divided by 1000, rounded half up
        to a whole cent"

        Design: Difficulty/dual_variant_calc/billing_basis_variants_diverge
        """
        # AGENCY_PLATFORM: identical delivery bills the agency number.
        ctx_a, li_a = _live_with_snapshot(billing_basis="AGENCY_PLATFORM")
        rec_a = create_and_reconcile(li_a, third_party_impressions=34000)
        assert_reconciliation(rec_a)
        assert rec_a["agency_impressions"] == 40000
        assert rec_a["discrepancy_pct"] == pytest.approx(-0.15, abs=1e-9)
        assert rec_a["billing_impressions"] == 40000
        assert rec_a["billable_cents"] == 20000
        assert rec_a["status"] == "RECONCILED"

        # THIRD_PARTY_TAG: identical delivery bills the tag number.
        ctx_b, li_b = _live_with_snapshot(billing_basis="THIRD_PARTY_TAG")
        rec_b = create_and_reconcile(li_b, third_party_impressions=34000)
        assert rec_b["billing_impressions"] == 34000
        assert rec_b["billable_cents"] == 17000

        assert (rec_a["billing_impressions"]
                != rec_b["billing_impressions"]), (
                    "The two bases must diverge on identical delivery data")

    def test_lower_of_within_tolerance_bills_agency(self, api):
        """PRD §3.6: "otherwise it is the smaller of the two numbers only
        when the absolute value of `discrepancy_pct` exceeds ten percent, and
        the agency number when the discrepancy stays within that tolerance."

        Design: Difficulty/dual_variant_calc/billing_basis_variants_diverge
        """
        ctx_c, li_c = _live_with_snapshot(billing_basis="LOWER_OF")
        rec_c = create_and_reconcile(li_c, third_party_impressions=38000)
        assert rec_c["discrepancy_pct"] == pytest.approx(-0.05, abs=1e-9)
        assert rec_c["billing_impressions"] == 40000, (
            "|discrepancy| 0.05 <= 0.10 -> tolerance gate suppresses min()")
        assert rec_c["billable_cents"] == 20000


class TestLowerOfGatedMinBranch:
    def test_lower_of_min_branch_excludes_voided_snapshot(self, api):
        """PRD §3.6: "Reconciling (`OPEN` → `RECONCILED`) recomputes
        `agency_impressions` from the currently posted snapshots in the
        period"
        PRD §3.6: "otherwise it is the smaller of the two numbers only when
        the absolute value of `discrepancy_pct` exceeds ten percent"

        Design: Difficulty/combinatorial_formula/billing_lower_of_gated_min_branch
        """
        ctx, li_id = _live_with_snapshot(billing_basis="LOWER_OF")
        # Rebalance delivery to 25000 + 15000 POSTED with one VOIDED row:
        # agency base must be 40000 with the voided snapshot excluded.
        post_snapshot(li_id, "2026-08-03", 25000, 125)
        snaps = get_success_data(
            api.list_delivery_snapshots(li_id, make_billing_headers("bm-1")))
        seed = [s for s in snaps if s["snapshot_date"] == "2026-08-05"][0]
        void_snapshot(seed["id"])
        post_snapshot(li_id, "2026-08-04", 15000, 75)
        extra = post_snapshot(li_id, "2026-08-06", 5000, 25)
        void_snapshot(extra["id"])

        rec = create_reconciliation(li_id, third_party_impressions=34000)
        reconciled = transition_reconciliation(rec["id"], "RECONCILE",
                                               user_id="bm-1")
        assert reconciled["agency_impressions"] == 40000, (
            "VOIDED snapshots must be excluded from the agency sum")
        assert reconciled["discrepancy_pct"] == pytest.approx(-0.15, abs=1e-9)
        assert reconciled["billing_impressions"] == 34000, (
            "|discrepancy| 0.15 > 0.10 -> bill min(40000, 34000)")
        assert reconciled["billable_cents"] == 17000
        assert reconciled["status"] == "RECONCILED"

    def test_lower_of_min_branch_positive_discrepancy(self, api):
        """PRD §3.6: "otherwise it is the smaller of the two numbers only
        when the absolute value of `discrepancy_pct` exceeds ten percent, and
        the agency number when the discrepancy stays within that tolerance."

        Design: Difficulty/combinatorial_formula/billing_lower_of_gated_min_branch
        """
        ctx, li_id = _live_with_snapshot(billing_basis="LOWER_OF")
        rec = create_reconciliation(li_id, third_party_impressions=46000)
        reconciled = transition_reconciliation(rec["id"], "RECONCILE",
                                               user_id="bm-1")
        assert reconciled["agency_impressions"] == 40000
        assert reconciled["discrepancy_pct"] == pytest.approx(0.15, abs=1e-9)
        assert reconciled["billing_impressions"] == 40000, (
            "|discrepancy| 0.15 > 0.10 -> bill min(40000, 46000) = 40000")
        assert reconciled["billable_cents"] == 20000

    def test_discrepancy_exactly_at_tolerance_stays_agency(self, api):
        """PRD §3.6: "otherwise it is the smaller of the two numbers only
        when the absolute value of `discrepancy_pct` exceeds ten percent, and
        the agency number when the discrepancy stays within that tolerance."

        Design: Corner/calculations/discrepancy_exactly_at_tolerance_stays_agency
        """
        ctx, li_id = _live_with_snapshot(billing_basis="LOWER_OF")
        rec = create_reconciliation(li_id, third_party_impressions=44000)
        reconciled = transition_reconciliation(rec["id"], "RECONCILE",
                                               user_id="bm-1")
        assert reconciled["discrepancy_pct"] == pytest.approx(0.10, abs=1e-9)
        assert reconciled["billing_impressions"] == 40000, (
            "The tolerance gate is strict-greater: exactly 0.10 bills agency")

    def test_agency_zero_discrepancy_null_and_zero_billing(self, api):
        """PRD §3.6: "when the agency number is zero, `discrepancy_pct` is
        null."
        PRD §3.6: "Under `LOWER_OF` it is zero when `agency_impressions` is
        zero"

        Design: Corner/calculations/agency_zero_discrepancy_null_and_zero_billing
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10",
                          "billing_basis": "LOWER_OF"},
            li_overrides={"goal_impressions": 100000, "cpm_rate_cents": 500,
                          "start_date": "2026-08-01",
                          "end_date": "2026-08-10"})
        rec = create_reconciliation(ctx["line_item"]["id"],
                                    third_party_impressions=500)
        reconciled = transition_reconciliation(rec["id"], "RECONCILE",
                                               user_id="bm-1")
        assert reconciled["agency_impressions"] == 0
        assert reconciled["discrepancy_pct"] is None
        assert reconciled["billing_impressions"] == 0
        assert reconciled["billable_cents"] == 0


class TestReconciliationPeriods:
    def test_half_open_adjacency_allowed_overlap_rejected(self, api,
                                                          billing_headers):
        """PRD §3.6: "The period is a half-open interval: `period_start` is
        inclusive and `period_end` exclusive, so adjacency is allowed — one
        reconciliation's `period_end` may equal the next one's
        `period_start` without conflict — while any true overlap with an
        existing reconciliation of the same line item is rejected with
        `ERR_RECONCILIATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/reconciliation_periods_half_open_adjacency
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        create_reconciliation(li_id, period_start="2026-08-01",
                              period_end="2026-08-10",
                              third_party_impressions=100)

        adjacent = create_reconciliation(li_id, period_start="2026-08-10",
                                         period_end="2026-08-20",
                                         third_party_impressions=100)
        assert adjacent["status"] == "OPEN", (
            "A period starting exactly at the previous period_end must be "
            "accepted under half-open semantics")

        res = api.create_reconciliation(
            create_reconciliation_payload(
                li_id, period_start="2026-08-09", period_end="2026-08-15",
                third_party_impressions=100),
            billing_headers)
        validate_error(res, ApiErrorId.ERR_RECONCILIATION_OVERLAP.value, 409)

    def test_contained_and_identical_periods_rejected(self, api,
                                                      billing_headers):
        """PRD §3.6: "any true overlap with an existing reconciliation of
        the same line item is rejected with `ERR_RECONCILIATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/reconciliation_periods_half_open_adjacency
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        create_reconciliation(li_id, period_start="2026-08-01",
                              period_end="2026-08-10",
                              third_party_impressions=100)

        contained = api.create_reconciliation(
            create_reconciliation_payload(
                li_id, period_start="2026-08-03", period_end="2026-08-05",
                third_party_impressions=100),
            billing_headers)
        validate_error(
            contained, ApiErrorId.ERR_RECONCILIATION_OVERLAP.value, 409)

        identical = api.create_reconciliation(
            create_reconciliation_payload(
                li_id, period_start="2026-08-01", period_end="2026-08-10",
                third_party_impressions=100),
            billing_headers)
        validate_error(
            identical, ApiErrorId.ERR_RECONCILIATION_OVERLAP.value, 409)


class TestReopenRecomputeLoop:
    def test_reopen_reconcile_recomputes_from_current_snapshots(self, api):
        """PRD §3.6: "A reconciliation may also be reopened (`RECONCILED` →
        `OPEN`), which clears `reconciled_by_user_id` to null and lets the
        period be restated and reconciled again — the reopen loop may
        repeat."
        PRD §3.6: "Reconciling (`OPEN` → `RECONCILED`) recomputes
        `agency_impressions` from the currently posted snapshots in the
        period"

        Design: Difficulty/non_linear_state_machine/reconciliation_reopen_recompute_loop
        """
        ctx, li_id = _live_with_snapshot(billing_basis="LOWER_OF")
        snaps = get_success_data(
            api.list_delivery_snapshots(li_id, make_billing_headers("bm-1")))
        snap_id = snaps[0]["id"]
        rec = create_reconciliation(li_id, third_party_impressions=34000)

        first = transition_reconciliation(rec["id"], "RECONCILE",
                                          user_id="bm-1")
        assert first["billing_impressions"] == 34000

        transition_reconciliation(rec["id"], "REOPEN", user_id="bm-1")
        void_snapshot(snap_id)
        second = transition_reconciliation(rec["id"], "RECONCILE",
                                           user_id="bm-1")
        assert second["agency_impressions"] == 0
        assert second["discrepancy_pct"] is None
        assert second["billing_impressions"] == 0
        assert second["billable_cents"] == 0
        assert second["status"] == "RECONCILED"

    def test_reopen_clears_reconciled_by(self, api):
        """PRD §3.6: "A reconciliation may also be reopened (`RECONCILED` →
        `OPEN`), which clears `reconciled_by_user_id` to null and lets the
        period be restated and reconciled again — the reopen loop may
        repeat."
        PRD §3.6: "the reconciling manager's `X-User-ID` is recorded as
        `reconciled_by_user_id`."

        Design: Difficulty/non_linear_state_machine/reconciliation_reopen_recompute_loop
        """
        ctx, li_id = _live_with_snapshot(billing_basis="LOWER_OF")
        rec = create_reconciliation(li_id, third_party_impressions=34000)

        reconciled = transition_reconciliation(rec["id"], "RECONCILE",
                                               user_id="bm-1")
        assert reconciled["reconciled_by_user_id"] == "bm-1"

        reopened = transition_reconciliation(rec["id"], "REOPEN",
                                             user_id="bm-1")
        assert reopened["status"] == "OPEN"
        assert reopened["reconciled_by_user_id"] is None


class TestLockGuards:
    def test_lock_blocked_by_open_make_good(self, api):
        """PRD §3.6: "And no make-good on a verification report of this line
        item whose measurement period overlaps the reconciliation period may
        still be `PROPOSED` or `APPROVED`; an outstanding proposal or
        approval blocks the lock with `ERR_UNRESOLVED_MAKE_GOODS`."

        Design: Corner/validations/recon_lock_blocked_by_open_make_good
        """
        ctx = setup_live_line_item(
            io_overrides={"billing_basis": "AGENCY_PLATFORM"})
        li_id = ctx["line_item"]["id"]
        post_snapshot(li_id, "2026-08-03", 1000, 10)
        report = file_verification_report(
            li_id, vendor="MOAT", measured_impressions=100000,
            viewable_impressions=80000, ivt_impressions=5000)
        mg = propose_make_good(report["id"], kind="CREDIT", credit_cents=1000)
        rec = create_and_reconcile(li_id, period_start="2026-08-01",
                                   period_end="2026-08-10",
                                   third_party_impressions=950,
                                   reconciler="bm-1")

        res = api.transition_reconciliation(rec["id"], {"action": "LOCK"},
                                            make_billing_headers("bm-2"))
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_MAKE_GOODS.value, 409)

        decide_make_good(mg["id"], "REJECT", user_id="bm-2")
        locked = transition_reconciliation(rec["id"], "LOCK", user_id="bm-2")
        assert locked["status"] == "LOCKED", (
            "Once the make-good is terminal the same LOCK must succeed")
