"""Budget-line batching, actuals posting rules, line variance edge cases,
and the trailing-vs-budget NOI variant split."""
import pytest

from test_helpers import (
    ApiErrorId,
    actuals_line_entry,
    budget_line_entry,
    create_actuals_report_payload,
    create_business_plan_payload,
    create_budget_lines_payload,
    create_draft_plan,
    create_property_manager_payload,
    find_line,
    get_asset,
    get_plan,
    get_success_data,
    lines_plan10,
    lines_rent_m1_m2,
    lines_zero_budget,
    make_property_manager_headers,
    setup_asset_with_noi,
    setup_base_asset,
    setup_plan_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
ANALYST = TEST_USERS["analyst"]


class TestNoiDualVariants:
    """Difficulty instance: dual_variant_calc / noi_trailing_vs_budget_baseline.

    Setup (identical for both tests): FY2026 APPROVED plan, RENT budget
    3,200,000/mo x12 + CAM 500,000/mo x12 + 8 single month-1 lines; actuals
    months 1-4 accepted at RENT 3,000,000 / CAM 500,000 — ytd NOI 10,000,000
    over M=4 months, so the TRAILING_ACTUALS annualized NOI is
    round_half_up(10,000,000 * 12 / 4) = 30,000,000, while the static
    BUDGET_BASELINE NOI is 38,550,000 - 6,640,000 = 31,910,000.
    """

    def _setup(self, api):
        return setup_asset_with_noi(fiscal_year=2026, months=4)

    def test_variance_summary_trailing_and_budget_noi_diverge(self, api):
        """PRD §3.2: "a variance-summary read on the plan returns its
        `plan_id`, a per-category rollup in `categories`, and three headline
        figures: `total_budget_noi_cents`, the static full-year budget NOI
        computed as budgeted revenue minus budgeted operating expense with no
        regard to actuals; ... and `annualized_actual_noi_cents`, the
        trailing-actuals annualization of §3.3."
        PRD §3.3: "the annualized figure is that year-to-date sum times
        twelve, divided by M, rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/noi_trailing_vs_budget_baseline
        """
        ctx = self._setup(api)
        summary = validate_success(
            api.get_business_plan_variance_summary(ctx["plan"]["id"], ANALYST), 200)
        assert summary["annualized_actual_noi_cents"] == 30000000, (
            "TRAILING_ACTUALS: round_half_up(10,000,000 * 12 / 4)")
        assert summary["total_budget_noi_cents"] == 31910000, (
            "BUDGET_BASELINE: 38,550,000 revenue - 6,640,000 opex")
        assert summary["annualized_actual_noi_cents"] != \
            summary["total_budget_noi_cents"], (
                "identical plan data must yield divergent variant figures")

    def test_asset_and_plan_fields_use_trailing_variant(self, api):
        """PRD §3.3: "The TRAILING_ACTUALS variant — used by covenant tests,
        internal-cap valuations, lender reports, and the asset's
        `current_annualized_noi_cents`".
        PRD §3.2: "`ytd_actual_noi_cents`, the signed sum of posted actuals
        (revenue positive, expense negative) over lines whose `has_actual` is
        true".

        Design: Difficulty/dual_variant_calc/noi_trailing_vs_budget_baseline
        """
        ctx = self._setup(api)
        asset = get_asset(ctx["asset"]["id"])
        assert asset["current_annualized_noi_cents"] == 30000000
        plan = get_plan(ctx["plan"]["id"])
        assert plan["ytd_actual_noi_cents"] == 10000000, (
            "4 months x (3,000,000 RENT - 500,000 CAM)")


def test_budget_line_duplicate_bulk_atomic_rejected(api):
    """PRD §3.2: "Creation is atomic: any failure rejects the whole request.
    Uniqueness is enforced per plan, category, and month — a second line for
    the same triple is `ERR_DUPLICATE_BUDGET_LINE`."

    Design: Corner/validations/budget_line_duplicate_bulk_atomic_rejected
    """
    ctx = setup_base_asset()
    plan = get_success_data(api.create_business_plan(
        create_business_plan_payload(ctx["asset"]["id"], 2027,
                                     ctx["asset"]["version"]), AM))
    get_success_data(api.create_budget_lines(
        create_budget_lines_payload(
            plan["id"], [budget_line_entry("RENT_REVENUE", 1, 11000000)]), AM))

    res = api.create_budget_lines(
        create_budget_lines_payload(plan["id"], [
            budget_line_entry("RENT_REVENUE", 1, 12000000),
            budget_line_entry("CAM_EXPENSE", 1, 200000),
        ]), AM)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BUDGET_LINE)

    data, meta = validate_paginated(
        api.list_business_plan_budget_lines(plan["id"], ANALYST))
    assert meta["total_count"] == 1, (
        "the CAM line in the failed bulk call must NOT persist (atomicity)")


def test_actuals_duplicate_month_rejected(api):
    """PRD §3.3: "At most one report per plan and month may ever reach
    `ACCEPTED`, and no referenced line may already have `has_actual` set —
    both surface as `ERR_DUPLICATE_ACTUALS`."

    Design: Corner/validations/actuals_duplicate_month_rejected
    """
    ctx = setup_plan_scenario(fiscal_year=2026, lines=lines_rent_m1_m2())
    pm_headers = make_property_manager_headers(ctx["manager"]["id"])
    rent_m1 = find_line(ctx["lines"], "RENT_REVENUE", 1)
    rent_m2 = find_line(ctx["lines"], "RENT_REVENUE", 2)

    first = get_success_data(api.create_actuals_report(
        create_actuals_report_payload(
            ctx["plan"]["id"], 1, [actuals_line_entry(rent_m1["id"], 11000000)]),
        pm_headers))
    get_success_data(api.accept_actuals_report(first["id"], AM))

    dup = api.create_actuals_report(
        create_actuals_report_payload(
            ctx["plan"]["id"], 1, [actuals_line_entry(rent_m1["id"], 11000001)]),
        pm_headers)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACTUALS)

    other_month = validate_success(api.create_actuals_report(
        create_actuals_report_payload(
            ctx["plan"]["id"], 2, [actuals_line_entry(rent_m2["id"], 11000000)]),
        pm_headers), 201)
    assert other_month["status"] == "SUBMITTED", (
        "month-2 slot is unaffected by the month-1 acceptance — "
        "duplicate semantics are per (plan, month)")


def test_actuals_line_month_mismatch_rejected(api):
    """PRD §3.3: "Every referenced line must belong to that plan and carry a
    `month_index` equal to the report's month (`ERR_REFERENTIAL_INTEGRITY`)."

    Design: Corner/validations/actuals_line_month_mismatch_rejected
    """
    ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_rent_m1_m2())
    pm_headers = make_property_manager_headers(ctx["manager"]["id"])
    rent_m1 = find_line(ctx["lines"], "RENT_REVENUE", 1)
    res = api.create_actuals_report(
        create_actuals_report_payload(
            ctx["plan"]["id"], 2, [actuals_line_entry(rent_m1["id"], 11000000)]),
        pm_headers)
    validate_error(res, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


def test_line_variance_zero_budget_rules(api):
    """PRD §3.3: "`variance_cents` is the posted actual minus the budget, and
    `variance_bps` scales that difference by ten thousand against the budget,
    rounded half-up to a whole basis point. Two edge cases are pinned: when
    the budget is zero and the actual is also zero, `variance_bps` is 0; when
    the budget is zero and the actual is positive, `variance_bps` is exactly
    1000000 — a pinned cap of ten-thousand percent, never infinity."

    Design: Corner/calculations/line_variance_zero_budget_rules
    """
    ctx = setup_plan_scenario(
        fiscal_year=2026, lines=lines_zero_budget(),
        accept_actuals=[{"month_index": 1,
                         "entries": [("INSURANCE_EXPENSE", 1, 0),
                                     ("OTHER_OPEX", 1, 250000)]}])
    data, _ = validate_paginated(
        api.list_business_plan_budget_lines(ctx["plan"]["id"], ANALYST))
    ins = find_line(data, "INSURANCE_EXPENSE", 1)
    opex = find_line(data, "OTHER_OPEX", 1)
    assert ins["variance_cents"] == 0
    assert ins["variance_bps"] == 0, "zero budget + zero actual -> 0 bps"
    assert opex["variance_cents"] == 250000
    assert opex["variance_bps"] == 1000000, \
        "zero budget + positive actual -> pinned 10000% cap"


def test_actuals_create_by_non_managing_pm_rejected(api):
    """PRD §2.1: "ownership checks on any asset-scoped write compare the
    asset's `property_manager_id` field to `X-User-ID`, and a mismatch is
    rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §3.3: "the ownership comparison of §2.1 applies here as everywhere".

    Design: Corner/validations/actuals_create_by_non_managing_pm_rejected
    """
    ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10())
    other_manager = get_success_data(api.create_property_manager(
        create_property_manager_payload(firm_name="Other Co",
                                        contact_email="o@x.com"), DIRECTOR))
    outsider_headers = make_property_manager_headers(other_manager["id"])
    res = api.create_actuals_report(
        create_actuals_report_payload(ctx["plan"]["id"], 1, []),
        outsider_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
