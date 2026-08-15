"""Wrap report generation guards, per-reconciliation rounding, attribution
variants and tie-breaking, and campaign close."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_wrap_report, assert_attribution_sums_to_total,
    create_wrap_report_payload,
    ApiErrorId, TEST_USERS,
    create_io, create_line_item, transition_io, transition_line_item,
    create_creative, walk_creative_to_tagged,
    setup_live_line_item, post_snapshot, set_clock, get_io,
    file_verification_report, propose_make_good, decide_make_good,
    create_and_lock_reconciliation, create_and_reconcile,
    complete_line_item, complete_io, create_wrap_report,
)


def _attribution_map(wrap):
    return {e["line_item_id"]: e["attributed_conversions"]
            for e in wrap["attribution"]}


class TestWrapGenerationGuards:
    def test_wrap_generate_before_io_completed_rejected(
            self, api, billing_headers):
        """PRD §3.7: "Generation requires the order to be `COMPLETED` — any
        other status fails with `ERR_INVALID_STATE` — and every
        reconciliation across the order's line items to be `LOCKED`, or the
        request is refused with `ERR_RECONCILIATION_NOT_LOCKED`."

        Design: Corner/state_machines/wrap_generate_before_io_completed_rejected
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10"},
            li_overrides={"start_date": "2026-08-01",
                          "end_date": "2026-08-10"},
            activate_io=True)
        res = api.create_wrap_report(
            create_wrap_report_payload(ctx["io"]["id"],
                                       attribution_model="LINEAR_CLICKS",
                                       total_conversions=10),
            billing_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_wrap_blocked_by_unlocked_reconciliation(self, api,
                                                     billing_headers):
        """PRD §3.7: "Generation requires the order to be `COMPLETED` — any
        other status fails with `ERR_INVALID_STATE` — and every
        reconciliation across the order's line items to be `LOCKED`, or the
        request is refused with `ERR_RECONCILIATION_NOT_LOCKED`."

        Design: Corner/validations/wrap_blocked_by_unlocked_reconciliation
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10",
                          "billing_basis": "AGENCY_PLATFORM"},
            li_overrides={"start_date": "2026-08-01",
                          "end_date": "2026-08-10"},
            activate_io=True)
        li_id = ctx["line_item"]["id"]
        post_snapshot(li_id, "2026-08-03", 1000, 10)
        create_and_reconcile(li_id, period_start="2026-08-01",
                             period_end="2026-08-10",
                             third_party_impressions=950, reconciler="bm-1")
        set_clock("2026-08-11T00:00:00Z")
        complete_line_item(li_id)
        complete_io(ctx["io"]["id"])

        res = api.create_wrap_report(
            create_wrap_report_payload(ctx["io"]["id"],
                                       attribution_model="LINEAR_CLICKS",
                                       total_conversions=5),
            billing_headers)
        validate_error(
            res, ApiErrorId.ERR_RECONCILIATION_NOT_LOCKED.value, 409)


class TestWrapTotalsAndRounding:
    def _setup_two_line_completed_io(self):
        """Two LIVE line items (goal 100000 @ cpm 250 each) with one POSTED
        snapshot of 1001 imps / 50 clicks each; a 75-cent credit make-good
        APPLIED on LI1; both reconciliations LOCKED; IO COMPLETED."""
        set_clock("2026-08-01T00:00:00Z")
        io = create_io(total_budget_cents=100000, flight_start="2026-08-01",
                       flight_end="2026-08-10",
                       billing_basis="AGENCY_PLATFORM")
        li1 = create_line_item(io["id"], name="LI1", goal_impressions=100000,
                               cpm_rate_cents=250, start_date="2026-08-01",
                               end_date="2026-08-10")
        li2 = create_line_item(io["id"], name="LI2", goal_impressions=100000,
                               cpm_rate_cents=250, start_date="2026-08-01",
                               end_date="2026-08-10")
        transition_io(io["id"], "APPROVE")
        for li, tag in ((li1, "<script>1</script>"), (li2, "<script>2</script>")):
            cr = create_creative(li["id"])
            walk_creative_to_tagged(cr["id"], ad_tag=tag)
            transition_line_item(li["id"], "TRAFFIC")
            transition_line_item(li["id"], "LAUNCH")
        transition_io(io["id"], "ACTIVATE")

        post_snapshot(li1["id"], "2026-08-03", 1001, 50)
        post_snapshot(li2["id"], "2026-08-03", 1001, 50)

        report = file_verification_report(
            li1["id"], vendor="MOAT", period_start="2026-08-01",
            period_end="2026-08-10", measured_impressions=100000,
            viewable_impressions=69000, ivt_impressions=2100)
        mg = propose_make_good(report["id"], kind="CREDIT", credit_cents=75)
        decide_make_good(mg["id"], "APPROVE", user_id="bm-2")
        decide_make_good(mg["id"], "APPLY", user_id="bm-2")

        create_and_lock_reconciliation(li1["id"], period_start="2026-08-01",
                                       period_end="2026-08-10",
                                       third_party_impressions=900)
        create_and_lock_reconciliation(li2["id"], period_start="2026-08-01",
                                       period_end="2026-08-10",
                                       third_party_impressions=900)

        set_clock("2026-08-11T00:00:00Z")
        complete_line_item(li1["id"])
        complete_line_item(li2["id"])
        complete_io(io["id"])
        return io, li1, li2

    def test_wrap_net_billable_per_recon_rounding(self, api):
        """PRD §3.7: "`total_billable_cents` sums `billable_cents` over only
        the `LOCKED` reconciliations of those line items, with each
        reconciliation's cent value rounded first and the rounded values then
        summed; `total_applied_credit_cents` copies the order's
        `total_applied_credit_cents` at generation time; and
        `net_billable_cents` is `total_billable_cents` minus
        `total_applied_credit_cents`, floored at zero so that heavy credits
        never turn the bill negative."

        Design: Difficulty/combinatorial_formula/wrap_net_billable_per_recon_rounding
        """
        io, li1, li2 = self._setup_two_line_completed_io()

        wrap = create_wrap_report(io["id"], attribution_model="LINEAR_CLICKS",
                                  total_conversions=10)
        assert_wrap_report(wrap)
        # Per-snapshot spend: round_half_up(1001 * 250 / 1000) = 250 each.
        assert wrap["total_delivered_impressions"] == 2002
        assert wrap["total_spend_cents"] == 500
        # Per-reconciliation billable: round_half_up(1001 * 250 / 1000) = 250
        # each, summed AFTER rounding -> 500 (sum-then-round would give 501).
        assert wrap["total_billable_cents"] == 500
        assert wrap["total_applied_credit_cents"] == 75
        assert wrap["net_billable_cents"] == 425
        attr = _attribution_map(wrap)
        assert attr == {li1["id"]: 5, li2["id"]: 5}
        assert_attribution_sums_to_total(wrap)

    def test_wrap_finalize_closes_parent_order(self, api, billing_headers):
        """PRD §3.7: "Finalizing the report (`DRAFT` → `FINALIZED`) locks
        those stored values, increments the report's `version` by one, and —
        as its system side effect — moves the parent insertion order from
        `COMPLETED` to `CLOSED`, ending the campaign lifecycle."

        Design: Difficulty/combinatorial_formula/wrap_net_billable_per_recon_rounding
        """
        io, _li1, _li2 = self._setup_two_line_completed_io()
        wrap = create_wrap_report(io["id"], attribution_model="LINEAR_CLICKS",
                                  total_conversions=10)
        assert wrap["status"] == "DRAFT"
        assert get_io(io["id"])["status"] == "COMPLETED"

        res = api.transition_wrap_report(wrap["id"], {"action": "FINALIZE"},
                                         billing_headers)
        finalized = validate_success(res, 200)
        assert finalized["status"] == "FINALIZED"
        assert get_io(io["id"])["status"] == "CLOSED"


class TestAttribution:
    def _setup_three_line_completed_io(self):
        """Three LIVE line items (goal 100000 @ cpm 500 each, IO budget
        200000), each with one POSTED snapshot of 1000 imps / 10 clicks;
        IO COMPLETED; no reconciliations."""
        set_clock("2026-08-01T00:00:00Z")
        io = create_io(total_budget_cents=200000, flight_start="2026-08-01",
                       flight_end="2026-08-10", billing_basis="LOWER_OF")
        line_items = []
        for i in (1, 2, 3):
            li = create_line_item(io["id"], name=f"LI{i}",
                                  goal_impressions=100000, cpm_rate_cents=500,
                                  start_date="2026-08-01",
                                  end_date="2026-08-10")
            line_items.append(li)
        transition_io(io["id"], "APPROVE")
        for i, li in enumerate(line_items, start=1):
            cr = create_creative(li["id"], name=f"C{i}")
            walk_creative_to_tagged(cr["id"], ad_tag=f"<script>{i}</script>")
            transition_line_item(li["id"], "TRAFFIC")
            transition_line_item(li["id"], "LAUNCH")
        transition_io(io["id"], "ACTIVATE")
        for li in line_items:
            post_snapshot(li["id"], "2026-08-03", 1000, 10)
        set_clock("2026-08-11T00:00:00Z")
        for li in line_items:
            complete_line_item(li["id"])
        complete_io(io["id"])
        return io, line_items

    def test_attribution_tie_broken_by_created_at(self, api):
        """PRD §3.7: "largest-remainder rounding converts the raw shares into
        integers that sum exactly to `total_conversions`; ties on fractional
        remainder are broken in favor of the line item created earlier,
        ordered by `created_at` ascending."

        Design: Corner/calculations/attribution_tie_broken_by_created_at
        """
        io, line_items = self._setup_three_line_completed_io()
        li1, li2, li3 = line_items

        wrap = create_wrap_report(io["id"], attribution_model="LINEAR_CLICKS",
                                  total_conversions=4)
        assert_wrap_report(wrap)
        assert wrap["total_delivered_impressions"] == 3000
        attr = _attribution_map(wrap)
        # Equal clicks (10/10/10) -> raw shares 4/3 each; the leftover
        # conversion goes to the earliest-created line item.
        assert attr[li1["id"]] == 2
        assert attr[li2["id"]] == 1
        assert attr[li3["id"]] == 1
        assert_attribution_sums_to_total(wrap)

    def _setup_two_line_completed_io_with_reports(self):
        """Two LIVE line items: LI1 3000 imps / 150 clicks with viewable
        70000; LI2 2000 imps / 100 clicks with viewable 30000. IO COMPLETED,
        no reconciliations."""
        set_clock("2026-08-01T00:00:00Z")
        io = create_io(total_budget_cents=100000, flight_start="2026-08-01",
                       flight_end="2026-08-10", billing_basis="LOWER_OF")
        li1 = create_line_item(io["id"], name="LI1", goal_impressions=100000,
                               cpm_rate_cents=500, start_date="2026-08-01",
                               end_date="2026-08-10")
        li2 = create_line_item(io["id"], name="LI2", goal_impressions=100000,
                               cpm_rate_cents=500, start_date="2026-08-01",
                               end_date="2026-08-10")
        transition_io(io["id"], "APPROVE")
        for i, li in ((1, li1), (2, li2)):
            cr = create_creative(li["id"], name=f"C{i}")
            walk_creative_to_tagged(cr["id"], ad_tag=f"<script>{i}</script>")
            transition_line_item(li["id"], "TRAFFIC")
            transition_line_item(li["id"], "LAUNCH")
        transition_io(io["id"], "ACTIVATE")
        post_snapshot(li1["id"], "2026-08-03", 3000, 150)
        post_snapshot(li2["id"], "2026-08-03", 2000, 100)
        # LI1: 0.70 == threshold -> PASS. LI2: 0.30 < 0.70 -> viewability-only
        # BREACH (ivt 0 -> no fraud cascade).
        file_verification_report(
            li1["id"], vendor="DOUBLEVERIFY", period_start="2026-08-01",
            period_end="2026-08-10", measured_impressions=100000,
            viewable_impressions=70000, ivt_impressions=0)
        file_verification_report(
            li2["id"], vendor="DOUBLEVERIFY", period_start="2026-08-01",
            period_end="2026-08-10", measured_impressions=100000,
            viewable_impressions=30000, ivt_impressions=0)
        set_clock("2026-08-11T00:00:00Z")
        complete_line_item(li1["id"])
        complete_line_item(li2["id"])
        complete_io(io["id"])
        return io, li1, li2

    def test_attribution_view_weighted_variant(self, api):
        """PRD §3.7: "Under `LINEAR_CLICKS` a line item's weight is its
        `delivered_clicks` divided by the summed delivered clicks of all
        participating line items. Under `VIEW_WEIGHTED` the weight comes from
        the vendor side instead: the sum of `viewable_impressions` over all
        of the line item's verification reports, regardless of their
        assessment, divided by that same total across the participating line
        items — so the two models can diverge on identical delivery data."

        Design: Corner/calculations/attribution_view_weighted_variant
        """
        io, li1, li2 = self._setup_two_line_completed_io_with_reports()

        wrap_linear = create_wrap_report(io["id"],
                                         attribution_model="LINEAR_CLICKS",
                                         total_conversions=100)
        assert wrap_linear["status"] == "DRAFT"
        attr_linear = _attribution_map(wrap_linear)
        assert attr_linear[li1["id"]] == 60
        assert attr_linear[li2["id"]] == 40
        assert_attribution_sums_to_total(wrap_linear)

        wrap_view = create_wrap_report(io["id"],
                                       attribution_model="VIEW_WEIGHTED",
                                       total_conversions=100)
        assert wrap_view["status"] == "DRAFT"
        attr_view = _attribution_map(wrap_view)
        assert attr_view[li1["id"]] == 70
        assert attr_view[li2["id"]] == 30
        assert_attribution_sums_to_total(wrap_view)

        assert attr_linear != attr_view, (
            "The two models must diverge on identical delivery data")
