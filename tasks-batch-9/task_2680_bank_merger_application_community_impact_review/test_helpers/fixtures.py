"""Composite setup helpers.

Each helper drives the public API only and returns the created records so a test
can assert on them. Every helper that acts on an application threads the acting
filer identity from the acquirer institution's own id, as the PRD requires of a
`Filer`'s `X-User-ID`.
"""
from prd_bench_local_runner.testing import (
    get_success_data, validate_success, validate_paginated,
)

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH, WELL_CAPITALIZED_ADJUSTMENTS, UNDERCAPITALIZED_ADJUSTMENTS,
    STANDARD_LINE_ITEMS,
)
from .factories import (
    acquirer_payload, target_payload, third_party_payload, institution_payload,
    deposit_market_payload, branch_payload, merger_application_payload,
    pro_forma_schedule_payload, competitive_analysis_payload, comment_period_payload,
    public_comment_payload, hearing_request_payload, benefits_plan_payload,
    line_item_payload, approval_decision_payload, approval_condition_payload,
    conversion_plan_payload, performance_report_payload,
)
from .test_users import (
    TEST_USERS, make_filer_headers, make_commenter_headers,
    ANALYST_USER_ID, MONITOR_USER_ID, OFFICIAL_USER_ID, COMMENTER_USER_ID,
)

ANALYST = TEST_USERS["analyst_headers"]
OFFICIAL = TEST_USERS["official_headers"]
MONITOR = TEST_USERS["monitor_headers"]
COMMENTER = TEST_USERS["commenter_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(now: str) -> dict:
    """Move the server's logical UTC clock; only a CaseAnalyst may drive it."""
    return validate_success(api_client.set_clock(now, ANALYST))


def reset_clock_to_epoch() -> dict:
    return set_clock(CLOCK_EPOCH)


# ---------------------------------------------------------------------------
# Institutions, markets and branches
# ---------------------------------------------------------------------------
def create_institution(payload=None, **overrides) -> dict:
    body = payload if payload is not None else institution_payload(**overrides)
    return validate_success(api_client.create_institution(body, ANALYST), 201)


def create_acquirer(**overrides) -> dict:
    return validate_success(api_client.create_institution(acquirer_payload(**overrides), ANALYST), 201)


def create_target(**overrides) -> dict:
    return validate_success(api_client.create_institution(target_payload(**overrides), ANALYST), 201)


def create_third_party(**overrides) -> dict:
    return validate_success(api_client.create_institution(third_party_payload(**overrides), ANALYST), 201)


def create_two_institutions() -> tuple:
    """Northbay National Bank as acquirer and Harbor Community Bank as target."""
    return create_acquirer(), create_target()


def create_market(**overrides) -> dict:
    return validate_success(api_client.create_deposit_market(deposit_market_payload(**overrides), ANALYST), 201)


def create_branch(institution_id, market_id, **overrides) -> dict:
    payload = branch_payload(institution_id, market_id, **overrides)
    return validate_success(api_client.create_branch(payload, ANALYST), 201)


# ---------------------------------------------------------------------------
# Merger applications
# ---------------------------------------------------------------------------
def create_application(acquirer_id, target_id, **overrides) -> dict:
    payload = merger_application_payload(acquirer_id, target_id, **overrides)
    return validate_success(
        api_client.create_merger_application(payload, make_filer_headers(acquirer_id)), 201
    )


def read_application(application_id, acquirer_id) -> dict:
    return validate_success(
        api_client.get_merger_application(application_id, make_filer_headers(acquirer_id))
    )


def application_version(application_id, acquirer_id) -> int:
    return read_application(application_id, acquirer_id)["version"]


def create_regulatory_schedule(application_id, acquirer_id, expected_version=None, **overrides) -> dict:
    """A CURRENT REGULATORY_ADJUSTED schedule that comes out WELL_CAPITALIZED."""
    if expected_version is None:
        expected_version = application_version(application_id, acquirer_id)
    payload = pro_forma_schedule_payload(application_id, expected_version, **overrides)
    return validate_success(
        api_client.create_pro_forma_schedule(payload, make_filer_headers(acquirer_id)), 201
    )


def create_undercapitalized_schedule(application_id, acquirer_id, expected_version=None) -> dict:
    """A REGULATORY_ADJUSTED schedule whose adjustments band UNDERCAPITALIZED."""
    return create_regulatory_schedule(
        application_id, acquirer_id, expected_version, **UNDERCAPITALIZED_ADJUSTMENTS
    )


def create_stress_schedule(application_id, acquirer_id, expected_version=None, **overrides) -> dict:
    overrides.setdefault("basis", "INTERNAL_STRESS")
    return create_regulatory_schedule(application_id, acquirer_id, expected_version, **overrides)


def submit_application(application_id, acquirer_id) -> dict:
    return validate_success(
        api_client.submit_merger_application(application_id, make_filer_headers(acquirer_id))
    )


def accept_application(application_id) -> dict:
    return validate_success(api_client.accept_merger_application(application_id, ANALYST))


def list_comment_periods(application_id) -> list:
    response = api_client.list_comment_periods(ANALYST, params={"application_id": application_id})
    records, _meta = validate_paginated(response)
    return records


def auto_comment_period(application_id) -> dict:
    """The comment period the service opens when a filing is accepted for review."""
    periods = list_comment_periods(application_id)
    assert periods, "acceptance must create a public comment period for the application"
    return periods[0]


# ---------------------------------------------------------------------------
# Composite worlds
# ---------------------------------------------------------------------------
def two_bank_world() -> dict:
    """Clock at the epoch, an acquirer, a target and a DRAFT application between them."""
    reset_clock_to_epoch()
    acquirer, target = create_two_institutions()
    application = create_application(acquirer["id"], target["id"])
    return {
        "acquirer": acquirer,
        "target": target,
        "application": application,
        "filer_headers": make_filer_headers(acquirer["id"]),
    }


def kestrel_market_world() -> dict:
    """The Kestrel MSA: a 1,000,000,000 includable base across three participants.

    Northbay holds 200,000,000, Harbor holds 60,000,000 plus 40,000,000 and the
    unrelated Lakeside Trust Company holds 700,000,000.
    """
    reset_clock_to_epoch()
    market = create_market()
    acquirer = create_acquirer()
    target = create_target()
    other = create_third_party()
    branch_acq = create_branch(acquirer["id"], market["id"],
                               branch_name="Northbay Kestrel Main", deposits_usd=200_000_000)
    branch_tgt_east = create_branch(target["id"], market["id"],
                                    branch_name="Harbor Kestrel East", deposits_usd=60_000_000)
    branch_tgt_west = create_branch(target["id"], market["id"],
                                    branch_name="Harbor Kestrel West", deposits_usd=40_000_000)
    branch_other = create_branch(other["id"], market["id"],
                                 branch_name="Lakeside Kestrel Center", deposits_usd=700_000_000)
    application = create_application(acquirer["id"], target["id"])
    return {
        "market": market,
        "acquirer": acquirer,
        "target": target,
        "other": other,
        "branch_acquirer": branch_acq,
        "branch_target_east": branch_tgt_east,
        "branch_target_west": branch_tgt_west,
        "branch_other": branch_other,
        "application": application,
        "filer_headers": make_filer_headers(acquirer["id"]),
    }


def rosewood_market_world() -> dict:
    """The Rosewood MSA: a 1,000,000,000 base across five participants.

    Northbay 200,000,000 and Harbor 50,000,000 combine against unrelated holdings
    of 400,000,000, 250,000,000 and 100,000,000.
    """
    reset_clock_to_epoch()
    market = create_market(market_code="ROSEWOOD-MSA", market_name="Rosewood MSA",
                           market_type="MSA")
    acquirer = create_acquirer()
    target = create_target()
    rosewood = create_institution(legal_name="Rosewood Savings Bank", charter_type="SAVINGS",
                                  primary_regulator="FDIC", cet1_capital_usd=400_000_000,
                                  tier1_capital_usd=410_000_000, total_capital_usd=440_000_000,
                                  risk_weighted_assets_usd=3_200_000_000,
                                  average_total_assets_usd=4_000_000_000,
                                  total_loans_usd=2_400_000_000)
    fairhaven = create_institution(legal_name="Fairhaven State Bank", charter_type="STATE_MEMBER",
                                   primary_regulator="FRB", cet1_capital_usd=250_000_000,
                                   tier1_capital_usd=255_000_000, total_capital_usd=280_000_000,
                                   risk_weighted_assets_usd=2_000_000_000,
                                   average_total_assets_usd=2_500_000_000,
                                   total_loans_usd=1_500_000_000)
    mill_creek = create_institution(legal_name="Mill Creek Bank", charter_type="STATE_NONMEMBER",
                                    primary_regulator="FDIC", cet1_capital_usd=100_000_000,
                                    tier1_capital_usd=102_000_000, total_capital_usd=115_000_000,
                                    risk_weighted_assets_usd=800_000_000,
                                    average_total_assets_usd=1_000_000_000,
                                    total_loans_usd=600_000_000)
    branch_acq = create_branch(acquirer["id"], market["id"], branch_name="Northbay Rosewood",
                               deposits_usd=200_000_000)
    branch_tgt = create_branch(target["id"], market["id"], branch_name="Harbor Rosewood",
                               deposits_usd=50_000_000)
    create_branch(rosewood["id"], market["id"], branch_name="Rosewood Savings Main",
                  deposits_usd=400_000_000)
    create_branch(fairhaven["id"], market["id"], branch_name="Fairhaven Rosewood",
                  deposits_usd=250_000_000)
    create_branch(mill_creek["id"], market["id"], branch_name="Mill Creek Rosewood",
                  deposits_usd=100_000_000)
    application = create_application(acquirer["id"], target["id"],
                                     consideration_type="ALL_CASH",
                                     total_consideration_usd=90_000_000)
    return {
        "market": market,
        "acquirer": acquirer,
        "target": target,
        "branch_acquirer": branch_acq,
        "branch_target": branch_tgt,
        "application": application,
        "filer_headers": make_filer_headers(acquirer["id"]),
    }


def run_competitive_analysis(application_id, market_id) -> dict:
    payload = competitive_analysis_payload(application_id, market_id)
    return validate_success(api_client.create_competitive_analysis(payload, ANALYST), 201)


def designate_for_divestiture(branch_id, application_id, acquirer_id) -> dict:
    return validate_success(api_client.designate_branch(
        branch_id,
        {"application_id": application_id, "designation_type": "DIVESTITURE"},
        make_filer_headers(acquirer_id),
    ))


def designate_for_closure(branch_id, application_id, acquirer_id,
                          notice_sent_at, planned_closure_date) -> dict:
    return validate_success(api_client.designate_branch(
        branch_id,
        {
            "application_id": application_id,
            "designation_type": "CLOSURE",
            "notice_sent_at": notice_sent_at,
            "planned_closure_date": planned_closure_date,
        },
        make_filer_headers(acquirer_id),
    ))


def rescind_designation(branch_id, acquirer_id) -> dict:
    return validate_success(
        api_client.rescind_branch_designation(branch_id, make_filer_headers(acquirer_id))
    )


# ---------------------------------------------------------------------------
# The public comment record
# ---------------------------------------------------------------------------
def open_comment_period(application_id, opens_at, **overrides) -> dict:
    payload = comment_period_payload(application_id, opens_at, **overrides)
    return validate_success(api_client.create_comment_period(payload, ANALYST), 201)


def close_comment_period(period_id) -> dict:
    return validate_success(api_client.close_comment_period(period_id, ANALYST))


def file_comment(period_id, commenter_user_id=COMMENTER_USER_ID, **overrides) -> dict:
    payload = public_comment_payload(period_id, **overrides)
    return validate_success(
        api_client.create_public_comment(payload, make_commenter_headers(commenter_user_id)), 201
    )


def file_substantive_protest(period_id, commenter_user_id=COMMENTER_USER_ID, **overrides) -> dict:
    """A substantive PROTEST — the only kind of comment that founds a hearing petition."""
    overrides.setdefault("stance", "PROTEST")
    overrides.setdefault("substantive", True)
    return file_comment(period_id, commenter_user_id, **overrides)


def respond_to_comment(comment_id, acquirer_id, disposition="RESPONDED", response_body=None) -> dict:
    payload = {"disposition": disposition}
    if disposition == "RESPONDED":
        payload["response_body"] = response_body or "Branch access will be preserved by the retained offices."
    elif response_body is not None:
        payload["response_body"] = response_body
    return validate_success(
        api_client.respond_to_public_comment(comment_id, payload, make_filer_headers(acquirer_id))
    )


def request_hearing(application_id, comment_id, commenter_user_id=COMMENTER_USER_ID, **overrides) -> dict:
    payload = hearing_request_payload(application_id, comment_id, **overrides)
    return validate_success(
        api_client.create_hearing_request(payload, make_commenter_headers(commenter_user_id)), 201
    )


def decide_hearing(request_id, outcome="GRANTED", rationale=None, headers=None) -> dict:
    payload = {
        "outcome": outcome,
        "decision_rationale": rationale or "Material community impact questions remain open.",
    }
    return validate_success(
        api_client.decide_hearing_request(request_id, payload, headers or OFFICIAL)
    )


def withdraw_hearing(request_id, commenter_user_id=COMMENTER_USER_ID) -> dict:
    return validate_success(
        api_client.withdraw_hearing_request(request_id, make_commenter_headers(commenter_user_id))
    )


# ---------------------------------------------------------------------------
# Community benefits plans
# ---------------------------------------------------------------------------
def propose_plan(application_id, acquirer_id, expected_version=None, **overrides) -> dict:
    if expected_version is None:
        expected_version = application_version(application_id, acquirer_id)
    payload = benefits_plan_payload(application_id, expected_version, **overrides)
    return validate_success(
        api_client.create_benefits_plan(payload, make_filer_headers(acquirer_id)), 201
    )


def add_line_item(plan_id, acquirer_id, category, committed_usd) -> dict:
    payload = line_item_payload(plan_id, category, committed_usd)
    return validate_success(
        api_client.create_line_item(payload, make_filer_headers(acquirer_id)), 201
    )


def add_standard_line_items(plan_id, acquirer_id) -> dict:
    """The four standard commitments totalling 392,000,000."""
    items = {}
    for category, committed in STANDARD_LINE_ITEMS:
        items[category] = add_line_item(plan_id, acquirer_id, category, committed)
    return items


def execute_plan(plan_id, acquirer_id) -> dict:
    return validate_success(
        api_client.execute_benefits_plan(plan_id, make_filer_headers(acquirer_id))
    )


def executed_standard_plan(application_id, acquirer_id, measurement_basis="CUMULATIVE_TO_DATE",
                           term_years=3) -> dict:
    """An EXECUTED plan carrying the four standard commitments (392,000,000 total)."""
    plan = propose_plan(application_id, acquirer_id, term_years=term_years,
                        measurement_basis=measurement_basis)
    line_items = add_standard_line_items(plan["id"], acquirer_id)
    executed = execute_plan(plan["id"], acquirer_id)
    return {"plan": executed, "line_items": line_items}


# ---------------------------------------------------------------------------
# Decisions, conditions and consummation
# ---------------------------------------------------------------------------
def recommend_application(application_id, recommendation="APPROVE_WITH_CONDITIONS",
                          headers=None) -> dict:
    return validate_success(api_client.recommend_merger_application(
        application_id, {"recommendation": recommendation}, headers or ANALYST
    ))


def issue_decision(application_id, decision="CONDITIONALLY_APPROVED", headers=None, **overrides) -> dict:
    payload = approval_decision_payload(application_id, decision, **overrides)
    return validate_success(
        api_client.create_approval_decision(payload, headers or OFFICIAL), 201
    )


def attach_condition(decision_id, condition_type="DIVESTITURE", timing="PRE_CONSUMMATION",
                     headers=None, **overrides) -> dict:
    payload = approval_condition_payload(decision_id, condition_type, timing, **overrides)
    return validate_success(
        api_client.create_approval_condition(payload, headers or OFFICIAL), 201
    )


def satisfy_condition(condition_id, headers=None) -> dict:
    return validate_success(
        api_client.satisfy_approval_condition(condition_id, headers or MONITOR)
    )


def consummate(decision_id, acquirer_id) -> dict:
    return validate_success(
        api_client.consummate(decision_id, make_filer_headers(acquirer_id))
    )


# ---------------------------------------------------------------------------
# Systems conversion
# ---------------------------------------------------------------------------
def register_conversion_plan(application_id, acquirer_id, **overrides) -> dict:
    payload = conversion_plan_payload(application_id, **overrides)
    return validate_success(
        api_client.create_conversion_plan(payload, make_filer_headers(acquirer_id)), 201
    )


def disclose_conversion(plan_id, acquirer_id, channels=None) -> dict:
    payload = {"disclosure_channels": channels or ["MAIL", "ONLINE_BANKING"]}
    return validate_success(
        api_client.disclose_conversion_plan(plan_id, payload, make_filer_headers(acquirer_id))
    )


def complete_conversion(plan_id, acquirer_id) -> dict:
    return validate_success(
        api_client.convert_conversion_plan(plan_id, make_filer_headers(acquirer_id))
    )


# ---------------------------------------------------------------------------
# Performance reports
# ---------------------------------------------------------------------------
def file_report(plan_id, acquirer_id, period_label, period_index, achieved_by_category) -> dict:
    payload = performance_report_payload(plan_id, period_label, period_index, achieved_by_category)
    return validate_success(
        api_client.create_performance_report(payload, make_filer_headers(acquirer_id)), 201
    )


def review_report(report_id, headers=None) -> dict:
    return validate_success(api_client.review_performance_report(report_id, headers or MONITOR))


def reopen_report(report_id, headers=None) -> dict:
    return validate_success(api_client.reopen_performance_report(report_id, headers or MONITOR))


def read_plan(plan_id, headers=None) -> dict:
    return validate_success(api_client.get_benefits_plan(plan_id, headers or MONITOR))


def read_line_item(line_item_id, headers=None) -> dict:
    return validate_success(api_client.get_line_item(line_item_id, headers or MONITOR))


def read_report(report_id, headers=None) -> dict:
    return validate_success(api_client.get_performance_report(report_id, headers or MONITOR))


def read_condition(condition_id, headers=None) -> dict:
    return validate_success(api_client.get_approval_condition(condition_id, headers or MONITOR))


def read_decision(decision_id, headers=None) -> dict:
    return validate_success(api_client.get_approval_decision(decision_id, headers or OFFICIAL))


def read_analysis(analysis_id, headers=None) -> dict:
    return validate_success(api_client.get_competitive_analysis(analysis_id, headers or ANALYST))


def read_market(market_id, headers=None) -> dict:
    return validate_success(api_client.get_deposit_market(market_id, headers or ANALYST))


def read_branch(branch_id, headers=None) -> dict:
    return validate_success(api_client.get_branch(branch_id, headers or ANALYST))


def read_institution(institution_id, headers=None) -> dict:
    return validate_success(api_client.get_institution(institution_id, headers or ANALYST))


def read_period(period_id, headers=None) -> dict:
    return validate_success(api_client.get_comment_period(period_id, headers or ANALYST))


def read_comment(comment_id, headers=None) -> dict:
    return validate_success(api_client.get_public_comment(comment_id, headers or ANALYST))


def read_hearing_request(request_id, headers=None) -> dict:
    return validate_success(api_client.get_hearing_request(request_id, headers or ANALYST))


def read_schedule(schedule_id, headers=None) -> dict:
    return validate_success(api_client.get_pro_forma_schedule(schedule_id, headers or ANALYST))


def read_conversion_plan(plan_id, headers=None) -> dict:
    return validate_success(api_client.get_conversion_plan(plan_id, headers or ANALYST))


# ---------------------------------------------------------------------------
# Whole-case progressions
# ---------------------------------------------------------------------------
def application_under_review(with_market=False) -> dict:
    """An application taken DRAFT -> SUBMITTED -> UNDER_REVIEW with its comment period open.

    Acceptance opens a 30-day window at the clock instant, so with the clock at the
    epoch the period runs 2026-08-01 to 2026-08-31.
    """
    world = kestrel_market_world() if with_market else two_bank_world()
    application = world["application"]
    acquirer_id = world["acquirer"]["id"]
    world["schedule"] = create_regulatory_schedule(application["id"], acquirer_id)
    world["application"] = submit_application(application["id"], acquirer_id)
    world["application"] = accept_application(application["id"])
    world["period"] = auto_comment_period(application["id"])
    return world


def application_recommended(with_market=False, recommendation="APPROVE_WITH_CONDITIONS",
                            recommend_at="2026-09-15T00:00:00Z", analyze_market=True) -> dict:
    """An application taken all the way to RECOMMENDED with its comment record closed.

    The comment period is closed, which sets `earliest_decision_at` to that period's
    `closes_at` plus 15 days of post-comment review, and the clock is then advanced
    past that instant so the recommendation is permitted.
    """
    world = application_under_review(with_market=with_market)
    application_id = world["application"]["id"]
    if with_market and analyze_market:
        world["analysis"] = run_competitive_analysis(application_id, world["market"]["id"])
    close_comment_period(world["period"]["id"])
    set_clock(recommend_at)
    world["application"] = recommend_application(application_id, recommendation)
    return world


def application_decided(with_market=False, decision="CONDITIONALLY_APPROVED",
                        recommendation="APPROVE_WITH_CONDITIONS",
                        recommend_at="2026-09-15T00:00:00Z", analyze_market=True) -> dict:
    """A RECOMMENDED application carrying an ISSUED order from a second official.

    The order is issued by `official-1` while the recommendation was recorded by
    `analyst-1`, so the two identifiers differ and segregation of duties holds.
    """
    world = application_recommended(with_market=with_market, recommendation=recommendation,
                                    recommend_at=recommend_at, analyze_market=analyze_market)
    world["decision"] = issue_decision(world["application"]["id"], decision)
    return world


def application_consummated(with_market=False, consummate_at="2026-09-20T00:00:00Z",
                            with_plan=False, measurement_basis="ANNUAL_PRO_RATA") -> dict:
    """A CONSUMMATED application, optionally with an EXECUTED benefits plan behind it."""
    world = application_decided(with_market=with_market)
    application_id = world["application"]["id"]
    acquirer_id = world["acquirer"]["id"]
    if with_plan:
        executed = executed_standard_plan(application_id, acquirer_id,
                                          measurement_basis=measurement_basis)
        world["plan"] = executed["plan"]
        world["line_items"] = executed["line_items"]
    set_clock(consummate_at)
    world["decision"] = consummate(world["decision"]["id"], acquirer_id)
    world["application"] = read_application(application_id, acquirer_id)
    return world


def monitoring_world(measurement_basis="ANNUAL_PRO_RATA") -> dict:
    """A consummated case under post-closing monitoring with an EXECUTED plan.

    The application has no deposit markets, so no competitive analysis is required
    and the order is expedited: `waiting_period_days` is the 5-day floor.
    """
    return application_consummated(with_plan=True, measurement_basis=measurement_basis)


def fernwood_closure_world() -> dict:
    """A single target branch in the Fernwood MSA behind a DRAFT systems-conversion window.

    The conversion window runs 2027-06-01 through 2027-06-15 inclusive, which is what a
    later closure designation's buffered window is tested against.
    """
    reset_clock_to_epoch()
    market = create_market(market_code="FERNWOOD-MSA", market_name="Fernwood MSA",
                           market_type="MSA")
    acquirer = create_acquirer()
    target = create_target()
    branch = create_branch(target["id"], market["id"], branch_name="Harbor Fernwood Annex",
                           deposits_usd=35_000_000, service_type="LIMITED_SERVICE")
    application = create_application(acquirer["id"], target["id"])
    conversion_plan = register_conversion_plan(
        application["id"], acquirer["id"],
        conversion_start_date="2027-06-01", conversion_end_date="2027-06-15",
    )
    return {
        "market": market,
        "acquirer": acquirer,
        "target": target,
        "branch": branch,
        "application": application,
        "conversion_plan": conversion_plan,
        "filer_headers": make_filer_headers(acquirer["id"]),
    }


def community_benefits_monitoring_world(measurement_basis="ANNUAL_PRO_RATA") -> dict:
    """A consummated case under monitoring with an OPEN post-closing benefits condition.

    The order carries no deposit-market analyses, so it is expedited and its waiting
    period lands on the 5-day floor; the clock is advanced to the instant the window
    opens and the transaction closes there.
    """
    world = application_decided()
    application_id = world["application"]["id"]
    acquirer_id = world["acquirer"]["id"]
    executed = executed_standard_plan(application_id, acquirer_id,
                                      measurement_basis=measurement_basis)
    world["plan"] = executed["plan"]
    world["line_items"] = executed["line_items"]
    world["condition"] = attach_condition(
        world["decision"]["id"], condition_type="COMMUNITY_BENEFITS", timing="POST_CLOSING",
        description="Deliver the community benefits package on the agreed quarterly schedule.",
    )
    set_clock("2026-09-20T00:00:00Z")
    world["decision"] = consummate(world["decision"]["id"], acquirer_id)
    world["application"] = read_application(application_id, acquirer_id)
    return world


def rosewood_consummation_world() -> dict:
    """A Rosewood MSA case issued as APPROVED and standing at the instant closing opens.

    Harbor also keeps a 30,000,000 office in the Fernwood MSA where Northbay holds
    nothing, so Fernwood is not an overlap market and needs no analysis. Harbor's
    Rosewood office is designated for divestiture before the window closes, the order
    is issued at 2026-09-15 with no protest and no hearing, and the clock is left at
    2026-09-20 where the expedited 5-day waiting period elapses.
    """
    world = rosewood_market_world()
    application_id = world["application"]["id"]
    acquirer_id = world["acquirer"]["id"]
    far_market = create_market(market_code="FERNWOOD-MSA", market_name="Fernwood MSA",
                               market_type="MSA")
    world["far_market"] = far_market
    world["branch_far"] = create_branch(world["target"]["id"], far_market["id"],
                                        branch_name="Harbor Fernwood",
                                        deposits_usd=30_000_000)
    world["schedule"] = create_regulatory_schedule(application_id, acquirer_id)
    world["application"] = submit_application(application_id, acquirer_id)
    world["application"] = accept_application(application_id)
    world["period"] = auto_comment_period(application_id)
    world["analysis"] = run_competitive_analysis(application_id, world["market"]["id"])
    designate_for_divestiture(world["branch_target"]["id"], application_id, acquirer_id)
    close_comment_period(world["period"]["id"])
    set_clock("2026-09-15T00:00:00Z")
    world["application"] = recommend_application(application_id, "APPROVE")
    world["decision"] = issue_decision(application_id, "APPROVED")
    set_clock("2026-09-20T00:00:00Z")
    return world


def pinehill_rural_world() -> dict:
    """A RURAL_COUNTY market whose 1,000,000,000 base is split across six firms.

    Northbay 150,000,000 and Harbor 100,000,000 sit beside four unrelated holdings of
    200,000,000, 200,000,000, 200,000,000 and 150,000,000.
    """
    reset_clock_to_epoch()
    market = create_market(market_code="PINEHILL-RURAL", market_name="Pinehill County",
                           market_type="RURAL_COUNTY")
    acquirer = create_acquirer()
    target = create_target()
    lakeside = create_third_party()
    crestline = create_institution(legal_name="Crestline Bank", charter_type="NATIONAL",
                                   primary_regulator="OCC")
    rosewood = create_institution(legal_name="Rosewood Savings", charter_type="SAVINGS",
                                  primary_regulator="FDIC", cet1_capital_usd=90_000_000,
                                  tier1_capital_usd=92_000_000, total_capital_usd=100_000_000,
                                  risk_weighted_assets_usd=900_000_000,
                                  average_total_assets_usd=1_100_000_000,
                                  total_loans_usd=700_000_000)
    fairhaven = create_institution(legal_name="Fairhaven State Bank", charter_type="STATE_MEMBER",
                                   primary_regulator="FRB", cet1_capital_usd=80_000_000,
                                   tier1_capital_usd=82_000_000, total_capital_usd=90_000_000,
                                   risk_weighted_assets_usd=800_000_000,
                                   average_total_assets_usd=1_000_000_000,
                                   total_loans_usd=600_000_000)
    create_branch(acquirer["id"], market["id"], branch_name="Northbay Pinehill",
                  deposits_usd=150_000_000)
    create_branch(target["id"], market["id"], branch_name="Harbor Pinehill",
                  deposits_usd=100_000_000)
    create_branch(lakeside["id"], market["id"], branch_name="Lakeside Pinehill",
                  deposits_usd=200_000_000)
    create_branch(crestline["id"], market["id"], branch_name="Crestline Pinehill",
                  deposits_usd=200_000_000)
    create_branch(rosewood["id"], market["id"], branch_name="Rosewood Savings Pinehill",
                  deposits_usd=200_000_000)
    create_branch(fairhaven["id"], market["id"], branch_name="Fairhaven Pinehill",
                  deposits_usd=150_000_000)
    application = create_application(acquirer["id"], target["id"])
    return {
        "market": market,
        "acquirer": acquirer,
        "target": target,
        "application": application,
        "filer_headers": make_filer_headers(acquirer["id"]),
    }


def granite_market_world() -> dict:
    """An MSA where the merger posts a presumptive violation: 300M + 200M against 500M.

    The 1,000,000,000 base gives hhi_pre_merger 3800, hhi_post_unmitigated 5000 and a
    delta of 1200, and an analysis is already on file for the overlap market.
    """
    reset_clock_to_epoch()
    market = create_market(market_code="GRANITE-MSA", market_name="Granite MSA",
                           market_type="MSA")
    acquirer = create_acquirer()
    target = create_target()
    lakeside = create_third_party()
    branch_acq = create_branch(acquirer["id"], market["id"], branch_name="Northbay Granite",
                               deposits_usd=300_000_000)
    branch_tgt = create_branch(target["id"], market["id"], branch_name="Harbor Granite",
                               deposits_usd=200_000_000)
    create_branch(lakeside["id"], market["id"], branch_name="Lakeside Granite",
                  deposits_usd=500_000_000)
    application = create_application(acquirer["id"], target["id"])
    analysis = run_competitive_analysis(application["id"], market["id"])
    return {
        "market": market,
        "acquirer": acquirer,
        "target": target,
        "branch_acquirer": branch_acq,
        "branch_target": branch_tgt,
        "application": application,
        "analysis": analysis,
        "filer_headers": make_filer_headers(acquirer["id"]),
    }
