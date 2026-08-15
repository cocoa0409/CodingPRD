"""Re-forecast cadence, limits, category coverage, the spread computation
with pinned rounding, annual conservation, and accept-time OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_submit_reforecast,
    create_reforecast_payload,
    find_line,
    get_plan,
    get_success_data,
    lines_rent12,
    reforecast_lines,
    set_clock,
    setup_plan_scenario,
    setup_reforecast_context,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
ANALYST = TEST_USERS["analyst"]


def _rent_lines(api, plan_id):
    data, _ = validate_paginated(
        api.list_business_plan_budget_lines(plan_id, ANALYST, params={"limit": 100}))
    return data


class TestReforecastSpreadRemainder:
    """Difficulty instance: combinatorial_formula /
    reforecast_spread_remainder_to_final_month.

    Setup: FY2027 APPROVED plan (RENT 11,000,000/mo x12 + 9 singles), clock at
    2027-04-05 (fiscal month 4), actuals months 1-3 accepted at RENT
    11,000,000 each (ytd 33,000,000). RENT revised annual 133,000,000 leaves
    100,000,000 over 9 months: floor(100,000,000/9) = 11,111,111 for months
    4-11 and the single remainder 11,111,112 in month 12.
    """

    def _apply(self, api):
        ctx = setup_reforecast_context()
        rf = get_success_data(api.create_reforecast(
            create_reforecast_payload(ctx["plan"]["id"], reforecast_lines()), AM))
        rf = get_success_data(api.submit_reforecast(rf["id"], AM))
        plan = get_plan(ctx["plan"]["id"])
        applied = validate_success(api.accept_reforecast(
            rf["id"], {"expected_plan_version": plan["version"]}, DIRECTOR), 200)
        return ctx, rf, applied

    def test_reforecast_spread_floor_and_remainder_month(self, api):
        """PRD §3.3: "Divide the remaining amount by the count of months from
        `effective_from_month` through 12, rounded down to a whole cent, and
        write that figure into the category's line for every remaining month
        except the twelfth; month 12 absorbs the remainder, receiving the
        remaining amount minus the per-month figure times the count of earlier
        remaining months."

        Design: Difficulty/combinatorial_formula/reforecast_spread_remainder_to_final_month
        """
        ctx, rf, applied = self._apply(api)
        assert applied["status"] == "APPLIED"
        lines = _rent_lines(api, ctx["plan"]["id"])
        rent_m1 = find_line(lines, "RENT_REVENUE", 1)
        rent_m4 = find_line(lines, "RENT_REVENUE", 4)
        rent_m12 = find_line(lines, "RENT_REVENUE", 12)
        assert rent_m4["budget_amount_cents"] == 11111111, \
            "floor(100,000,000 / 9) per remaining month 4..11"
        assert rent_m12["budget_amount_cents"] == 11111112, \
            "month 12 absorbs 100,000,000 - 8*11,111,111"
        assert rent_m1["budget_amount_cents"] == 11000000, \
            "elapsed months are never touched"
        assert rent_m1["actual_amount_cents"] == 11000000

    def test_reforecast_label_month_and_count(self, api):
        """PRD §3.3: "At creation the server assigns the `label` — `R1`,
        `R2`, or `R3`, by creation sequence on the plan — and stamps
        `effective_from_month` with the plan's current fiscal month, which is
        therefore always one of 4, 7, or 10."
        PRD §3.3: "The plan's `total_revenue_budget_cents`,
        `total_opex_budget_cents`, and `budgeted_noi_cents` are then
        recomputed, `reforecast_count` increments by one, and the plan's
        `version` bumps."

        Design: Difficulty/combinatorial_formula/reforecast_spread_remainder_to_final_month
        """
        ctx, rf, applied = self._apply(api)
        assert rf["label"] == "R1"
        assert rf["effective_from_month"] == 4
        plan = get_plan(ctx["plan"]["id"])
        assert plan["reforecast_count"] == 1


class TestReforecastAnnualConserved:
    """Difficulty instance: compensating_invariant /
    reforecast_annual_total_conserved (same scenario as the spread sibling;
    the asserted conserved quantity is the revised annual total)."""

    def test_reforecast_annual_total_conserved_exactly(self, api):
        """PRD §3.3: "Rounding order is pinned — the per-month figure is
        floored first and the entire remainder lands in month 12 — so that
        after the apply, each reforecasted category's twelve-month column
        (posted actual where a line has one, budget otherwise) sums to R
        exactly."

        Design: Difficulty/compensating_invariant/reforecast_annual_total_conserved
        """
        ctx = setup_reforecast_context()
        rf = create_and_submit_reforecast(ctx["plan"]["id"])
        plan = get_plan(ctx["plan"]["id"])
        validate_success(api.accept_reforecast(
            rf["id"], {"expected_plan_version": plan["version"]}, DIRECTOR), 200)

        lines = _rent_lines(api, ctx["plan"]["id"])
        rent = [find_line(lines, "RENT_REVENUE", m) for m in range(1, 13)]
        column_total = sum(
            l["actual_amount_cents"] if l["has_actual"] else l["budget_amount_cents"]
            for l in rent)
        assert column_total == 133000000, (
            f"twelve-month column must equal the revised annual exactly, "
            f"got {column_total}")
        assert rent[3]["budget_amount_cents"] == 11111111
        assert rent[10]["budget_amount_cents"] == 11111111
        assert rent[11]["budget_amount_cents"] == 11111112
        for m in (0, 1, 2):
            assert rent[m]["budget_amount_cents"] == 11000000
            assert rent[m]["actual_amount_cents"] == 11000000

    def test_reforecast_updates_plan_revenue_total(self, api):
        """PRD §3.3: "The plan's `total_revenue_budget_cents`,
        `total_opex_budget_cents`, and `budgeted_noi_cents` are then
        recomputed". After the apply the revenue total is the RENT revision
        plus the untouched single-line PARKING and OTHER_REVENUE budgets:
        133,000,000 + 500,000 + 100,000 = 133,600,000.

        Design: Difficulty/compensating_invariant/reforecast_annual_total_conserved
        """
        ctx = setup_reforecast_context()
        rf = create_and_submit_reforecast(ctx["plan"]["id"])
        plan = get_plan(ctx["plan"]["id"])
        validate_success(api.accept_reforecast(
            rf["id"], {"expected_plan_version": plan["version"]}, DIRECTOR), 200)
        plan_after = get_plan(ctx["plan"]["id"])
        assert plan_after["total_revenue_budget_cents"] == 133600000


class TestReforecastCadenceAndLimits:
    def test_reforecast_wrong_month_rejected(self, api):
        """PRD §3.3: "creation is permitted only when the plan's current
        fiscal month is the fourth, seventh, or tenth
        (`ERR_REFORECAST_CADENCE`)".

        Design: Corner/validations/reforecast_wrong_month_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_rent12(),
                                  clock_iso="2027-02-10T00:00:00Z")
        res = api.create_reforecast(
            create_reforecast_payload(ctx["plan"]["id"], reforecast_lines()), AM)
        validate_error(res, ApiErrorId.ERR_REFORECAST_CADENCE)

    def test_clock_default_month8_cadence_rejected(self, api):
        """PRD §2.5: "Before any client call, the logical clock reads exactly
        2026-08-01T00:00:00Z, and it must never fall back to wall-clock time."
        PRD §3.3: "creation is permitted only when the plan's current fiscal
        month is the fourth, seventh, or tenth (`ERR_REFORECAST_CADENCE`)" —
        an FY2026 plan reads fiscal month 8 under the untouched clock.

        Design: Corner/validations/clock_default_month8_cadence_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2026, lines=lines_rent12())
        res = api.create_reforecast(
            create_reforecast_payload(ctx["plan"]["id"], reforecast_lines()), AM)
        validate_error(res, ApiErrorId.ERR_REFORECAST_CADENCE)

    def test_reforecast_fourth_rejected_limit(self, api):
        """PRD §3.3: "Three times a year at most, the plan may be re-forecast,
        and only at fixed checkpoints: creation is permitted only when the
        plan's current fiscal month is the fourth, seventh, or tenth
        (`ERR_REFORECAST_CADENCE`), and only while `reforecast_count` remains
        below three (`ERR_REFORECAST_LIMIT`)."

        Design: Corner/validations/reforecast_fourth_rejected_limit
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_rent12())
        for clock in ("2027-04-05T00:00:00Z", "2027-07-05T00:00:00Z",
                      "2027-10-05T00:00:00Z"):
            set_clock(clock)
            rf = create_and_submit_reforecast(ctx["plan"]["id"])
            plan = get_plan(ctx["plan"]["id"])
            validate_success(api.accept_reforecast(
                rf["id"], {"expected_plan_version": plan["version"]},
                DIRECTOR), 200)
        assert get_plan(ctx["plan"]["id"])["reforecast_count"] == 3

        res = api.create_reforecast(
            create_reforecast_payload(ctx["plan"]["id"], reforecast_lines()), AM)
        validate_error(res, ApiErrorId.ERR_REFORECAST_LIMIT)

    def test_reforecast_incomplete_categories_rejected(self, api):
        """PRD §3.3: "the entries must cover each of the nine non-`CAPITAL`
        categories exactly once, and `CAPITAL` itself is forbidden
        (`ERR_REFORECAST_CATEGORIES_INCOMPLETE`)."

        Design: Corner/validations/reforecast_incomplete_categories_rejected
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_rent12(),
                                  clock_iso="2027-04-05T00:00:00Z")
        res = api.create_reforecast(
            create_reforecast_payload(
                ctx["plan"]["id"],
                reforecast_lines(skip_category="OTHER_OPEX")), AM)
        validate_error(res, ApiErrorId.ERR_REFORECAST_CATEGORIES_INCOMPLETE)

    def test_reforecast_below_actuals_rejected(self, api):
        """PRD §3.3: "take the year-to-date posted actuals on that category's
        lines in months before `effective_from_month`, add the budget still
        sitting on that category's elapsed-but-unposted lines in those same
        months, and subtract both from R; the result is the remaining amount,
        which must not be negative (`ERR_REFORECAST_BELOW_ACTUALS`)."

        Design: Corner/validations/reforecast_below_actuals_rejected
        """
        ctx = setup_reforecast_context()
        # RENT YTD actuals 33,000,000; a 30,000,000 revision goes negative.
        rf = create_and_submit_reforecast(ctx["plan"]["id"], rent_revised=30000000)
        plan = get_plan(ctx["plan"]["id"])
        res = api.accept_reforecast(
            rf["id"], {"expected_plan_version": plan["version"]}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_REFORECAST_BELOW_ACTUALS)
        plan_after = get_plan(ctx["plan"]["id"])
        assert plan_after["reforecast_count"] == 0


class TestReforecastAcceptOCC:
    def test_occ_reforecast_accept_stale_plan_version(self, api):
        """PRD §2.7: "Accepting a reforecast
        (`POST /api/reforecasts/{id}/accept`) requires
        `expected_plan_version` matching the plan's current `version`; a
        mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_reforecast_accept_stale_plan_version
        """
        ctx = setup_reforecast_context()
        rf1 = create_and_submit_reforecast(ctx["plan"]["id"])
        rf2 = create_and_submit_reforecast(ctx["plan"]["id"])
        stale = get_plan(ctx["plan"]["id"])["version"]

        first = validate_success(api.accept_reforecast(
            rf1["id"], {"expected_plan_version": stale}, DIRECTOR), 200)
        assert first["status"] == "APPLIED"

        res = api.accept_reforecast(
            rf2["id"], {"expected_plan_version": stale}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_STALE_PLAN_VERSION)
        reforecasts, _ = validate_paginated(
            api.list_business_plan_reforecasts(ctx["plan"]["id"], ANALYST))
        rf2_after = [r for r in reforecasts if r["id"] == rf2["id"]][0]
        assert rf2_after["status"] == "SUBMITTED"
