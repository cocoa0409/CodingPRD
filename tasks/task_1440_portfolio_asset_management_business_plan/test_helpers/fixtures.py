"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through the public API
(the harness restarts the server before every test, so each test starts
against an empty database). Internally these use the lenient
get_success_data() so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    budget_line_entry,
    create_actuals_report_payload,
    create_asset_payload,
    create_business_plan_payload,
    create_budget_lines_payload,
    create_capital_project_payload,
    create_covenant_payload,
    create_covenant_test_payload,
    create_disposition_decision_payload,
    create_funding_draw_payload,
    create_lease_strategy_payload,
    create_lender_report_payload,
    create_loan_payload,
    create_portfolio_payload,
    create_property_manager_payload,
    create_reforecast_payload,
    create_valuation_payload,
    actuals_line_entry,
)
from .test_users import TEST_USERS, make_property_manager_headers

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]          # user id "am-1"
AM2 = TEST_USERS["asset_manager2"]        # user id "am-2"
IC = TEST_USERS["committee"]              # user id "ic-1"
LENDER = TEST_USERS["lender"]
ANALYST = TEST_USERS["analyst"]


# ---------------------------------------------------------------------------
# Budget-line sets (creation order matters: listings are creation-ordered)
# ---------------------------------------------------------------------------

def lines_plan10(rent=11000000, capital=36000000):
    """Ten single month-1 lines covering every category."""
    return [
        budget_line_entry("RENT_REVENUE", 1, rent),
        budget_line_entry("PARKING_REVENUE", 1, 500000),
        budget_line_entry("OTHER_REVENUE", 1, 100000),
        budget_line_entry("CAM_EXPENSE", 1, 200000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 50000),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 90000),
        budget_line_entry("CAPITAL", 1, capital),
    ]


def lines_nine_no_capital(rent=11000000):
    """Nine non-CAPITAL single lines (CAPITAL deliberately absent)."""
    return [
        budget_line_entry("RENT_REVENUE", 1, rent),
        budget_line_entry("PARKING_REVENUE", 1, 500000),
        budget_line_entry("OTHER_REVENUE", 1, 100000),
        budget_line_entry("CAM_EXPENSE", 1, 200000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 50000),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 90000),
    ]


def lines_rent12(rent=11000000, capital=36000000):
    """RENT for months 1-12 plus the nine single month-1 lines (21 lines)."""
    lines = [budget_line_entry("RENT_REVENUE", m, rent) for m in range(1, 13)]
    lines += [
        budget_line_entry("PARKING_REVENUE", 1, 500000),
        budget_line_entry("OTHER_REVENUE", 1, 100000),
        budget_line_entry("CAM_EXPENSE", 1, 200000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 50000),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 90000),
        budget_line_entry("CAPITAL", 1, capital),
    ]
    return lines


def lines_rent_m1_m2(rent=11000000):
    """RENT months 1 and 2 plus the nine single month-1 lines (11 lines)."""
    lines = [
        budget_line_entry("RENT_REVENUE", 1, rent),
        budget_line_entry("RENT_REVENUE", 2, rent),
    ]
    lines += lines_plan10()[1:]
    return lines


def lines_zero_budget():
    """PLAN10 shape with INSURANCE_EXPENSE and OTHER_OPEX budgeted at zero."""
    return [
        budget_line_entry("RENT_REVENUE", 1, 11000000),
        budget_line_entry("PARKING_REVENUE", 1, 500000),
        budget_line_entry("OTHER_REVENUE", 1, 100000),
        budget_line_entry("CAM_EXPENSE", 1, 200000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 0),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 0),
        budget_line_entry("CAPITAL", 1, 36000000),
    ]


def lines_fix_a1(rent=4200000, cam=500000, months=4):
    """RENT `rent`/mo and CAM `cam`/mo for months 1..`months` + 8 singles."""
    lines = [budget_line_entry("RENT_REVENUE", m, rent) for m in range(1, months + 1)]
    lines += [budget_line_entry("CAM_EXPENSE", m, cam) for m in range(1, months + 1)]
    lines += [
        budget_line_entry("PARKING_REVENUE", 1, 100000),
        budget_line_entry("OTHER_REVENUE", 1, 50000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 50000),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 90000),
        budget_line_entry("CAPITAL", 1, 36000000),
    ]
    return lines


def lines_fix_a2(rent=3200000, cam=500000):
    """RENT `rent`/mo x12 and CAM `cam`/mo x12 + 8 singles (32 lines)."""
    lines = [budget_line_entry("RENT_REVENUE", m, rent) for m in range(1, 13)]
    lines += [budget_line_entry("CAM_EXPENSE", m, cam) for m in range(1, 13)]
    lines += [
        budget_line_entry("PARKING_REVENUE", 1, 100000),
        budget_line_entry("OTHER_REVENUE", 1, 50000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 50000),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 90000),
        budget_line_entry("CAPITAL", 1, 36000000),
    ]
    return lines


def lines_fix_a2_lite(rent=3200000, cam=500000):
    """Month-1-only variant: RENT + CAM at month 1 plus 8 singles (10 lines)."""
    return [
        budget_line_entry("RENT_REVENUE", 1, rent),
        budget_line_entry("CAM_EXPENSE", 1, cam),
        budget_line_entry("PARKING_REVENUE", 1, 100000),
        budget_line_entry("OTHER_REVENUE", 1, 50000),
        budget_line_entry("TAX_EXPENSE", 1, 300000),
        budget_line_entry("INSURANCE_EXPENSE", 1, 50000),
        budget_line_entry("UTILITIES_EXPENSE", 1, 80000),
        budget_line_entry("MANAGEMENT_FEE_EXPENSE", 1, 120000),
        budget_line_entry("OTHER_OPEX", 1, 90000),
        budget_line_entry("CAPITAL", 1, 36000000),
    ]


def find_line(lines, category, month_index):
    """Locate a created budget line by (category, month_index)."""
    for line in lines:
        if line["category"] == category and line["month_index"] == month_index:
            return line
    raise AssertionError(f"Setup failed: no line ({category}, month {month_index})")


# ---------------------------------------------------------------------------
# Tier 1/2: base hierarchy and plan progression
# ---------------------------------------------------------------------------

def setup_base_asset(acquisition_date="2024-06-15", hold_period_years=5,
                     asset_name="A1", asset_class="OFFICE", sqft=100000,
                     acquisition_price_cents=800000000, firm_name="PM Co",
                     fiscal_year_start_month=1, portfolio_name="P1"):
    """Portfolio + property manager + OWNED asset.

    Returns dict(portfolio, manager, asset). The manager is entity-backed:
    ownership-gated calls must use make_property_manager_headers(manager["id"]).
    """
    portfolio = get_success_data(api_client.create_portfolio(
        create_portfolio_payload(name=portfolio_name,
                                 fiscal_year_start_month=fiscal_year_start_month),
        DIRECTOR))
    manager = get_success_data(api_client.create_property_manager(
        create_property_manager_payload(firm_name=firm_name), DIRECTOR))
    asset = get_success_data(api_client.create_asset(
        create_asset_payload(
            portfolio["id"], manager["id"], name=asset_name,
            asset_class=asset_class, net_rentable_sqft=sqft,
            acquisition_price_cents=acquisition_price_cents,
            acquisition_date=acquisition_date, hold_period_years=hold_period_years),
        DIRECTOR))
    return {"portfolio": portfolio, "manager": manager, "asset": asset}


def create_draft_plan(asset, fiscal_year, lines):
    """Create a DRAFT plan on the asset and bulk-add its budget lines.

    `asset` must carry the current version (this helper performs the only
    mutation between reading asset.version and the plan create).
    Returns (plan_dict, lines_list). The returned plan dict is re-read after
    the line batch, so its version reflects the line-creation bump.
    """
    plan = get_success_data(api_client.create_business_plan(
        create_business_plan_payload(asset["id"], fiscal_year, asset["version"]), AM))
    created = get_success_data(api_client.create_budget_lines(
        create_budget_lines_payload(plan["id"], lines), AM))
    plan = get_success_data(api_client.get_business_plan(plan["id"], ANALYST))
    return plan, created


def submit_plan(plan_id):
    return get_success_data(api_client.submit_business_plan(plan_id, AM))


def approve_plan(plan_id):
    return get_success_data(api_client.approve_business_plan(plan_id, DIRECTOR))


def setup_plan_scenario(fiscal_year=2027, lines=None, clock_iso=None,
                        accept_actuals=None, submit=True, approve=True,
                        acquisition_date="2024-06-15", hold_period_years=5):
    """Base hierarchy + plan with lines, optionally submitted/approved, with an
    optional clock advance and optional rounds of accepted actuals.

    accept_actuals: list of {"month_index": m, "entries": [(category,
    line_month, actual_amount_cents), ...]} — each round is posted by the
    asset's property manager and accepted by the asset manager.

    Returns dict(portfolio, manager, asset, plan, lines).
    """
    ctx = setup_base_asset(acquisition_date=acquisition_date,
                           hold_period_years=hold_period_years)
    plan, created_lines = create_draft_plan(ctx["asset"], fiscal_year,
                                            lines if lines is not None
                                            else lines_plan10())
    if submit:
        plan = submit_plan(plan["id"])
    if approve:
        plan = approve_plan(plan["id"])
    if clock_iso is not None:
        set_clock(clock_iso)
    if accept_actuals:
        pm_headers = make_property_manager_headers(ctx["manager"]["id"])
        for rnd in accept_actuals:
            entries = []
            for category, line_month, amount in rnd["entries"]:
                line = find_line(created_lines, category, line_month)
                entries.append(actuals_line_entry(line["id"], amount))
            report = get_success_data(api_client.create_actuals_report(
                create_actuals_report_payload(plan["id"], rnd["month_index"],
                                              entries),
                pm_headers))
            get_success_data(api_client.accept_actuals_report(report["id"], AM))
    plan = get_success_data(api_client.get_business_plan(plan["id"], ANALYST))
    ctx.update({"plan": plan, "lines": created_lines})
    return ctx


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def get_plan(plan_id):
    return get_success_data(api_client.get_business_plan(plan_id, ANALYST))


def get_asset(asset_id):
    return get_success_data(api_client.get_asset(asset_id, ANALYST))


def get_portfolio(portfolio_id):
    return get_success_data(api_client.get_portfolio(portfolio_id, ANALYST))


def get_manager(manager_id):
    return get_success_data(api_client.get_property_manager(manager_id, ANALYST))


def get_loan(loan_id):
    return get_success_data(api_client.get_loan(loan_id, ANALYST))


def get_covenant(covenant_id):
    return get_success_data(api_client.get_covenant(covenant_id, ANALYST))


# ---------------------------------------------------------------------------
# Tier 3: loan / covenant / valuation / project lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_loan(asset_id, principal=300000000, rate_bps=1000,
                origination="2026-01-01", maturity="2028-06-30",
                lender_name="Bank"):
    return get_success_data(api_client.create_loan(
        create_loan_payload(asset_id, lender_name=lender_name,
                            principal_balance_cents=principal,
                            annual_interest_rate_bps=rate_bps,
                            origination_date=origination,
                            maturity_date=maturity),
        DIRECTOR))


def create_covenant(loan_id, covenant_type="MIN_DSCR", threshold_bps=12500,
                    test_frequency="QUARTERLY", cure_period_days=None):
    overrides = {}
    if cure_period_days is not None:
        overrides["cure_period_days"] = cure_period_days
    return get_success_data(api_client.create_covenant(
        create_covenant_payload(loan_id, covenant_type=covenant_type,
                                threshold_bps=threshold_bps,
                                test_frequency=test_frequency, **overrides),
        DIRECTOR))


def record_covenant_test(covenant_id, period_label):
    return get_success_data(api_client.create_covenant_test(
        create_covenant_test_payload(covenant_id, period_label), ANALYST))


def create_valuation_draft(asset_id, effective_date, method="EXTERNAL_APPRAISAL",
                           appraised_value_cents=None, cap_rate_bps=None):
    overrides = {}
    if appraised_value_cents is not None:
        overrides["appraised_value_cents"] = appraised_value_cents
    if cap_rate_bps is not None:
        overrides["cap_rate_bps"] = cap_rate_bps
    return get_success_data(api_client.create_valuation(
        create_valuation_payload(asset_id, effective_date, method, **overrides),
        ANALYST))


def confirm_valuation_fresh(valuation_id, asset_id):
    """Confirm a valuation with the asset's CURRENT version (fresh OCC read)."""
    asset = get_asset(asset_id)
    return get_success_data(api_client.confirm_valuation(
        valuation_id, {"expected_asset_version": asset["version"]}, DIRECTOR))


def create_project(asset_id, plan_id, amount, sched_start, sched_end,
                   name="X", is_emergency=None, proposer_headers=None):
    overrides = {}
    if is_emergency is not None:
        overrides["is_emergency"] = is_emergency
    return get_success_data(api_client.create_capital_project(
        create_capital_project_payload(asset_id, plan_id, name, amount,
                                       sched_start, sched_end, **overrides),
        proposer_headers or AM))


def approve_project(project_id, plan_id, approver_headers=None):
    """Approve a capital project with a freshly read plan version (OCC)."""
    plan = get_plan(plan_id)
    return get_success_data(api_client.approve_capital_project(
        project_id, {"expected_plan_version": plan["version"]},
        approver_headers or IC))


def create_and_release_draw(project_id, amount_cents):
    """Draw requested by AM, approved by IC, released by the director."""
    draw = get_success_data(api_client.create_funding_draw(
        create_funding_draw_payload(project_id, amount_cents), AM))
    get_success_data(api_client.approve_funding_draw(draw["id"], IC))
    return get_success_data(api_client.release_funding_draw(draw["id"], DIRECTOR))


def create_and_recommend_strategy(asset_id, space_type, occupancy, proposed, market,
                                  creator_headers=None):
    strategy = get_success_data(api_client.create_lease_strategy(
        create_lease_strategy_payload(asset_id, space_type, occupancy, proposed,
                                      market),
        creator_headers or AM))
    recommended = get_success_data(
        api_client.recommend_lease_strategy(strategy["id"], ANALYST))
    return recommended


def ratify_decision(decision_id, ratifier_headers=None):
    """Advance a decision SCREENING -> COMMITTEE_REVIEW -> RATIFIED."""
    get_success_data(api_client.submit_disposition_review(decision_id, AM))
    return get_success_data(api_client.ratify_disposition_decision(
        decision_id, ratifier_headers or IC))


def create_and_ratify_decision(asset_id, trigger_type, creator_headers=None,
                               ratifier_headers=None):
    decision = get_success_data(api_client.create_disposition_decision(
        create_disposition_decision_payload(asset_id, trigger_type),
        creator_headers or AM))
    ratified = ratify_decision(decision["id"], ratifier_headers)
    return decision, ratified


# ---------------------------------------------------------------------------
# Tier 4: composite scenario fixtures
# ---------------------------------------------------------------------------

def setup_asset_with_noi(fiscal_year=2026, months=4, rent_budget=None,
                         cam_budget=500000, rent_actual=3000000,
                         cam_actual=500000, line_set="fix_a2"):
    """Approved plan with `months` of accepted RENT+CAM actuals.

    Defaults land the trailing-actuals annualized NOI at exactly 30,000,000
    (ytd 2,500,000 per month over M months, times 12 / M).
    Returns the scenario context dict (portfolio, manager, asset, plan, lines).
    """
    if line_set == "fix_a1":
        lines = lines_fix_a1(rent=rent_budget or 4200000, cam=cam_budget)
    elif line_set == "fix_a2_lite":
        lines = lines_fix_a2_lite(rent=rent_budget or 3200000, cam=cam_budget)
    else:
        lines = lines_fix_a2(rent=rent_budget or 3200000, cam=cam_budget)
    rounds = [{"month_index": m,
               "entries": [("RENT_REVENUE", m, rent_actual),
                           ("CAM_EXPENSE", m, cam_actual)]}
              for m in range(1, months + 1)]
    return setup_plan_scenario(fiscal_year=fiscal_year, lines=lines,
                               accept_actuals=rounds)


def setup_loan_and_covenant(ctx, principal=500000000, rate_bps=500,
                            covenant_type="MIN_DSCR", threshold_bps=12500,
                            origination="2026-01-01", maturity="2027-06-30"):
    """Attach a loan and one covenant to the scenario's asset."""
    loan = create_loan(ctx["asset"]["id"], principal=principal, rate_bps=rate_bps,
                       origination=origination, maturity=maturity)
    covenant = create_covenant(loan["id"], covenant_type=covenant_type,
                               threshold_bps=threshold_bps)
    ctx.update({"loan": loan, "covenant": covenant})
    return ctx


def setup_reforecast_context(rent_revised=133000000):
    """FY2027 plan (RENT 11M x12 + 9 singles) APPROVED; clock at 2027-04-05
    (fiscal month 4, cadence open); actuals months 1-3 accepted with RENT
    11,000,000 each (ytd RENT actual 33,000,000)."""
    ctx = setup_plan_scenario(
        fiscal_year=2027, lines=lines_rent12(), clock_iso="2027-04-05T00:00:00Z",
        accept_actuals=[{"month_index": m,
                         "entries": [("RENT_REVENUE", m, 11000000)]}
                        for m in (1, 2, 3)])
    return ctx


def reforecast_lines(rent_revised=133000000, skip_category=None,
                     include_capital=False):
    """Nine non-CAPITAL reforecast entries; single-month categories carry
    their original month-1 budget so their remaining spread is zero."""
    amounts = {
        "RENT_REVENUE": rent_revised,
        "PARKING_REVENUE": 500000,
        "OTHER_REVENUE": 100000,
        "CAM_EXPENSE": 200000,
        "TAX_EXPENSE": 300000,
        "INSURANCE_EXPENSE": 50000,
        "UTILITIES_EXPENSE": 80000,
        "MANAGEMENT_FEE_EXPENSE": 120000,
        "OTHER_OPEX": 90000,
    }
    if skip_category is not None:
        amounts.pop(skip_category)
    if include_capital:
        amounts["CAPITAL"] = 36000000
    return [{"category": c, "revised_annual_amount_cents": a}
            for c, a in amounts.items()]


def create_and_submit_reforecast(plan_id, rent_revised=133000000):
    rf = get_success_data(api_client.create_reforecast(
        create_reforecast_payload(plan_id, reforecast_lines(rent_revised)), AM))
    return get_success_data(api_client.submit_reforecast(rf["id"], AM))


def setup_listed_asset(acquisition_date="2021-06-15", hold_period_years=5):
    """Asset moved OWNED -> LISTED_FOR_SALE via an executed SELL decision
    (sell_signal armed by elapsed hold years at the default clock)."""
    ctx = setup_base_asset(acquisition_date=acquisition_date,
                           hold_period_years=hold_period_years)
    decision, _ = create_and_ratify_decision(ctx["asset"]["id"], "SELL")
    get_success_data(api_client.execute_disposition_decision(
        decision["id"], {}, DIRECTOR))
    ctx["decision"] = decision
    return ctx
