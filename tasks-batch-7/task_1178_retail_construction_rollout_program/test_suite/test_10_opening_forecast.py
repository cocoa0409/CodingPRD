"""Opening-date forecast: pinned evaluation order, provisional-ratio slip
factor, and the all-work-terminal collapse."""
from test_helpers import (
    approve_change_order_now,
    complete_vendor_window,
    create_vendor_mobilization,
    propose_change_order,
    read_commitment_for_site,
    read_site,
    recalculate_commitment,
    schedule_mobilization_ok,
    set_clock,
    setup_site_in_build,
    setup_site_in_punch,
    validate_success,
)


class TestCircularEvaluationOrder:
    def test_forecast_circular_evaluation_order_pinned(self, api):
        """PRD §3.8: "First the site's variance ratios and `budget_posture`
        are computed from the current change-order buckets (§3.6). Then a slip
        factor derives from the provisional ratio: 0 basis points when that
        ratio is at most 500, 500 when it is at most 1500, and 1500 beyond
        that. Then the forecast dates are computed, and only then is
        `protection_posture` derived."
        PRD §3.8: "Conservatively, the planned length is padded by the slip
        factor — multiplied by one plus the slip factor divided by 10000 — and
        rounded half up to whole days."
        PRD §3.8: "The conservative forecast `forecast_open_on` is today plus
        the conservative permit block plus the conservative vendor chain plus
        a fixed ten-day punch buffer; `forecast_optimistic_on` combines the
        optimistic block and chain with the same buffer. `slip_days` is the
        number of days by which the conservative forecast passes
        `committed_open_on`, floored at zero."

        Design: Difficulty/combinatorial_formula/forecast_circular_evaluation_order_pinned
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        # Approved +500000 on a 9000000 base: provisional ratio 556bp ->
        # slip factor 500bp for the conservative padding.
        co = propose_change_order(site_id, 500_000,
                                  description="Structural steel add")
        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        validate_success(resp)

        complete_vendor_window(site_id, "FIXTURE", "2026-06-01", "2026-06-21",
                               "2026-06-01", vendor_name="Fixtures R Us")
        complete_vendor_window(site_id, "IT", "2026-06-22", "2026-07-07",
                               "2026-06-22", vendor_name="NetCabling Co")
        vsig = create_vendor_mobilization(site_id, vendor_type="SIGNAGE",
                                          vendor_name="SignPros",
                                          planned_start_on="2026-08-10",
                                          planned_end_on="2026-08-25")
        schedule_mobilization_ok(vsig["id"])

        set_clock("2026-08-01T00:00:00Z")
        oc = read_commitment_for_site(site_id)
        result = recalculate_commitment(oc["id"])

        # Conservative: start 08-10, 15 planned days padded to
        # round_half_up(15 * 1.05) = 16 -> chain ends 08-26; +10 buffer.
        assert result["forecast_open_on"] == "2026-09-05"
        # Optimistic: same window unpadded -> 08-25 + 10 days.
        assert result["forecast_optimistic_on"] == "2026-09-04"
        assert result["forecast_open_on"] != result["forecast_optimistic_on"], (
            "the 500bp slip factor must be applied before the forecast step")
        assert result["slip_days"] == 4
        assert result["protection_posture"] == "WATCH"
        assert read_site(site_id)["budget_posture"] == "WATCH"

    def test_forecast_slip_factor_zero_at_five_hundred_bp_boundary(self, api):
        """PRD §3.8: "Then a slip factor derives from the provisional ratio: 0
        basis points when that ratio is at most 500, 500 when it is at most
        1500, and 1500 beyond that."
        PRD §3.8: "The conservative forecast `forecast_open_on` is today plus
        the conservative permit block plus the conservative vendor chain plus
        a fixed ten-day punch buffer; `forecast_optimistic_on` combines the
        optimistic block and chain with the same buffer."

        Design: Difficulty/combinatorial_formula/forecast_circular_evaluation_order_pinned
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        # +450000 on 9000000: provisional ratio exactly 500bp -> factor 0.
        co = propose_change_order(site_id, 450_000, description="Facade upgrade")
        resp = approve_change_order_now(co["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        validate_success(resp)

        complete_vendor_window(site_id, "FIXTURE", "2026-06-01", "2026-06-21",
                               "2026-06-01", vendor_name="Fixtures R Us")
        complete_vendor_window(site_id, "IT", "2026-06-22", "2026-07-07",
                               "2026-06-22", vendor_name="NetCabling Co")
        vsig = create_vendor_mobilization(site_id, vendor_type="SIGNAGE",
                                          vendor_name="SignPros",
                                          planned_start_on="2026-08-10",
                                          planned_end_on="2026-08-25")
        schedule_mobilization_ok(vsig["id"])

        set_clock("2026-08-01T00:00:00Z")
        oc = read_commitment_for_site(site_id)
        result = recalculate_commitment(oc["id"])

        # At exactly 500bp the padding is zero, so both variants agree.
        assert result["forecast_open_on"] == "2026-09-04"
        assert result["forecast_optimistic_on"] == "2026-09-04"
        assert result["slip_days"] == 3
        assert result["protection_posture"] == "WATCH"
        assert read_site(site_id)["budget_posture"] == "WITHIN"


class TestForecastInputSet:
    def test_forecast_with_all_work_terminal(self, api):
        """PRD §3.8: "For each incomplete type the forecast uses its
        non-terminal mobilization — one in `PLANNED`, `SCHEDULED`, or
        `ON_SITE`, choosing the earliest-created when several exist; a
        required type with no scheduled work contributes zero days, because
        the forecast prices only scheduled work."
        PRD §3.8: "The conservative forecast `forecast_open_on` is today plus
        the conservative permit block plus the conservative vendor chain plus
        a fixed ten-day punch buffer"

        Design: Corner/calculations/c_forecast_with_all_work_terminal
        """
        # Site reached PUNCH on 2026-05-13; every permit is terminal
        # (BUILDING permit ISSUED) and every vendor type COMPLETE.
        ctx = setup_site_in_punch()
        site = read_site(ctx["site"]["id"])
        assert site["status"] == "PUNCH"

        oc = read_commitment_for_site(ctx["site"]["id"])
        result = recalculate_commitment(oc["id"])
        # Empty input set: 2026-05-13 + 0 + 0 + 10-day punch buffer.
        assert result["forecast_open_on"] == "2026-05-23"
        assert result["slip_days"] == 0
        assert result["protection_posture"] == "PROTECTED"
