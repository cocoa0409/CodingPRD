"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints and
uses the lenient success validator, so a broken precondition reports as a setup failure
rather than as a confusing assertion failure inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    branch_payload,
    clock_payload,
    closure_notice_payload,
    consolidation_case_payload,
    de_novo_plan_payload,
    impact_assessment_payload,
    leased_property_disposition_payload,
    market_area_payload,
    owned_property_disposition_payload,
    performance_snapshot_payload,
    receiving_branch_payload,
    retention_forecast_payload,
    staff_disposition_payload,
    transition_campaign_payload,
)
from .test_users import TEST_USERS, make_branch_manager_headers

STRATEGIST = TEST_USERS["strategist_headers"]
SECOND_STRATEGIST = TEST_USERS["second_strategist_headers"]
APPROVER = TEST_USERS["approver_headers"]
SECOND_APPROVER = TEST_USERS["second_approver_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
HR = TEST_USERS["hr_headers"]
REAL_ESTATE = TEST_USERS["real_estate_headers"]
OPS_ADMIN = TEST_USERS["ops_admin_headers"]


# ---------------------------------------------------------------- reads

def read_market(market_area_id: str) -> dict:
    return get_success_data(api_client.get_market_area(market_area_id, STRATEGIST))


def read_branch(branch_id: str) -> dict:
    return get_success_data(api_client.get_branch(branch_id, STRATEGIST))


def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_consolidation_case(case_id, STRATEGIST))


def read_forecast(forecast_id: str) -> dict:
    return get_success_data(api_client.get_retention_forecast(forecast_id, STRATEGIST))


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_impact_assessment(assessment_id, COMPLIANCE))


def read_notice(notice_id: str) -> dict:
    return get_success_data(api_client.get_closure_notice(notice_id, COMPLIANCE))


def read_staff_disposition(disposition_id: str) -> dict:
    return get_success_data(api_client.get_staff_disposition(disposition_id, HR))


def read_property_disposition(disposition_id: str) -> dict:
    return get_success_data(
        api_client.get_property_disposition(disposition_id, REAL_ESTATE)
    )


def read_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_transition_campaign(campaign_id, COMPLIANCE))


def read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_de_novo_plan(plan_id, STRATEGIST))


# ---------------------------------------------------------------- clock

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock and return the clock response payload."""
    return get_success_data(
        api_client.set_clock(clock_payload(to_iso8601), OPS_ADMIN)
    )


# ---------------------------------------------------------------- tier 1: trade area + branches

def setup_market(**overrides) -> dict:
    """Register one trade area. Returns the created trade area."""
    return get_success_data(
        api_client.create_market_area(market_area_payload(**overrides), STRATEGIST)
    )


def setup_branch(market_area_id: str, **overrides) -> dict:
    """Register one branch in a trade area. Returns the created branch."""
    return get_success_data(
        api_client.create_branch(branch_payload(market_area_id, **overrides), STRATEGIST)
    )


def setup_market_with_branches(market_overrides=None, closing_overrides=None,
                               receiving_overrides=None) -> dict:
    """Trade area + a closing candidate (RB-101) + a survivor (RB-102).

    Returns {"market", "closing_branch", "receiving_branch"}.
    """
    market = setup_market(**(market_overrides or {}))
    closing = get_success_data(
        api_client.create_branch(
            branch_payload(market["id"], **(closing_overrides or {})), STRATEGIST
        )
    )
    receiving = get_success_data(
        api_client.create_branch(
            receiving_branch_payload(market["id"], **(receiving_overrides or {})),
            STRATEGIST,
        )
    )
    return {"market": market, "closing_branch": closing, "receiving_branch": receiving}


def record_snapshot(branch_id: str, headers=None, **overrides) -> dict:
    """Record one immutable reporting period against a branch."""
    return get_success_data(
        api_client.create_performance_snapshot(
            branch_id, performance_snapshot_payload(**overrides), headers or STRATEGIST
        )
    )


def record_snapshot_as_owner(branch_id: str, **overrides) -> dict:
    """Record a reporting period using the acting branch's own manager identity."""
    return record_snapshot(branch_id, make_branch_manager_headers(branch_id), **overrides)


# ---------------------------------------------------------------- tier 2: case lifecycle

def setup_draft_case(ctx=None, case_overrides=None, pair_receiving=True) -> dict:
    """Trade area + two branches + a DRAFT consolidation case on RB-101.

    Returns the context dict extended with "case".
    """
    ctx = ctx or setup_market_with_branches()
    overrides = dict(case_overrides or {})
    if pair_receiving and "receiving_branch_id" not in overrides:
        overrides["receiving_branch_id"] = ctx["receiving_branch"]["id"]
    payload = consolidation_case_payload(
        ctx["closing_branch"]["id"], ctx["closing_branch"]["version"], **overrides
    )
    ctx["case"] = get_success_data(
        api_client.create_consolidation_case(payload, STRATEGIST)
    )
    return ctx


def setup_case_with_forecast(ctx=None, case_overrides=None, forecast_overrides=None) -> dict:
    """DRAFT case backed by one ACTIVE retention forecast. Adds "forecast"."""
    ctx = ctx if ctx and "case" in ctx else setup_draft_case(ctx, case_overrides)
    payload = retention_forecast_payload(
        ctx["case"]["id"], ctx["case"]["version"], **(forecast_overrides or {})
    )
    ctx["forecast"] = get_success_data(
        api_client.create_retention_forecast(payload, STRATEGIST)
    )
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def setup_submitted_case(ctx=None, case_overrides=None, forecast_overrides=None) -> dict:
    """Case walked DRAFT to SUBMITTED with its savings chain computed."""
    ctx = ctx if ctx and "forecast" in ctx else setup_case_with_forecast(
        ctx, case_overrides, forecast_overrides
    )
    ctx["case"] = get_success_data(
        api_client.submit_consolidation_case(ctx["case"]["id"], STRATEGIST)
    )
    return ctx


def setup_approved_case(ctx=None, case_overrides=None, forecast_overrides=None) -> dict:
    """Case walked through to APPROVED by an approver who is not its author."""
    ctx = ctx if ctx and "case" in ctx and ctx["case"]["status"] == "SUBMITTED" else (
        setup_submitted_case(ctx, case_overrides, forecast_overrides)
    )
    ctx["case"] = get_success_data(
        api_client.decide_consolidation_case(
            ctx["case"]["id"],
            {"decision": "APPROVE", "expected_case_version": ctx["case"]["version"]},
            APPROVER,
        )
    )
    return ctx


def setup_finalized_assessment(ctx, assessment_overrides=None) -> dict:
    """Record and finalise one community impact assessment. Adds "assessment"."""
    ctx["assessment"] = get_success_data(
        api_client.create_impact_assessment(
            ctx["case"]["id"],
            impact_assessment_payload(**(assessment_overrides or {})),
            COMPLIANCE,
        )
    )
    ctx["assessment"] = get_success_data(
        api_client.finalize_impact_assessment(ctx["assessment"]["id"], COMPLIANCE)
    )
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def setup_notice_filed_case(ctx=None, case_overrides=None, forecast_overrides=None,
                            assessment_overrides=None, notice_overrides=None) -> dict:
    """Case walked all the way to NOTICE_FILED behind a finalised assessment.

    Adds "assessment" and "notice"; refreshes "case" and "closing_branch".
    """
    if ctx and "notice" in ctx and ctx.get("case", {}).get("status") == "NOTICE_FILED":
        return ctx
    ctx = ctx if ctx and "case" in ctx and ctx["case"]["status"] == "APPROVED" else (
        setup_approved_case(ctx, case_overrides, forecast_overrides)
    )
    if "assessment" not in ctx:
        ctx = setup_finalized_assessment(ctx, assessment_overrides)
    ctx["notice"] = get_success_data(
        api_client.create_closure_notice(
            closure_notice_payload(ctx["case"]["id"], **(notice_overrides or {})),
            COMPLIANCE,
        )
    )
    ctx["case"] = read_case(ctx["case"]["id"])
    ctx["closing_branch"] = read_branch(ctx["closing_branch"]["id"])
    return ctx


# ---------------------------------------------------------------- tier 3: waves, premises, staff

def setup_campaign(ctx, launch=False, **overrides) -> dict:
    """Plan (and optionally launch) a customer transition wave. Adds "campaign"."""
    ctx["campaign"] = get_success_data(
        api_client.create_transition_campaign(
            transition_campaign_payload(ctx["case"]["id"], **overrides), COMPLIANCE
        )
    )
    if launch:
        ctx["campaign"] = get_success_data(
            api_client.launch_transition_campaign(ctx["campaign"]["id"], COMPLIANCE)
        )
    return ctx


def setup_leased_property_disposition(ctx, branch_id=None, **overrides) -> dict:
    """Open the premises and ATM disposition for a leased branch. Adds "property"."""
    ctx["property"] = get_success_data(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                branch_id or ctx["closing_branch"]["id"], ctx["case"]["id"], **overrides
            ),
            REAL_ESTATE,
        )
    )
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def setup_owned_property_disposition(ctx, branch_id=None, **overrides) -> dict:
    """Open the premises and ATM disposition for an owned branch. Adds "property"."""
    ctx["property"] = get_success_data(
        api_client.create_property_disposition(
            owned_property_disposition_payload(
                branch_id or ctx["closing_branch"]["id"], ctx["case"]["id"], **overrides
            ),
            REAL_ESTATE,
        )
    )
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def setup_staff_disposition(ctx, notify=False, **overrides) -> dict:
    """Propose one employee disposition against the case. Returns the disposition."""
    disposition = get_success_data(
        api_client.create_staff_disposition(
            staff_disposition_payload(ctx["case"]["id"], **overrides), HR
        )
    )
    if notify:
        disposition = get_success_data(
            api_client.notify_staff_disposition(disposition["id"], HR)
        )
    ctx["case"] = read_case(ctx["case"]["id"])
    return disposition


# ---------------------------------------------------------------- tier 4: executed closure

def setup_execution_ready_case(ctx=None, case_overrides=None, forecast_overrides=None,
                               assessment_overrides=None, notice_overrides=None,
                               campaign_overrides=None, property_overrides=None) -> dict:
    """Every execution precondition satisfied except the elapsed notice period.

    Walks: trade area, two branches, case, forecast, submit, approve, assessment,
    finalise, regulatory notice, launched wave, leased premises disposition.
    """
    ctx = setup_notice_filed_case(
        ctx, case_overrides, forecast_overrides, assessment_overrides, notice_overrides
    )
    if "campaign" not in ctx:
        ctx = setup_campaign(ctx, launch=True, **(campaign_overrides or {}))
    if "property" not in ctx:
        ctx = setup_leased_property_disposition(ctx, **(property_overrides or {}))
    return ctx


def setup_executed_closure(ctx=None, execution_date="2026-11-01T00:00:00Z", **kwargs) -> dict:
    """Execution-ready case with the clock advanced past the effective date and the
    closure executed. Adds "clock_response"; refreshes case, branches and premises."""
    ctx = setup_execution_ready_case(ctx, **kwargs)
    ctx["clock_response"] = set_clock(execution_date)
    ctx["case"] = get_success_data(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE)
    )
    ctx["closing_branch"] = read_branch(ctx["closing_branch"]["id"])
    ctx["receiving_branch"] = read_branch(ctx["receiving_branch"]["id"])
    ctx["market"] = read_market(ctx["market"]["id"])
    ctx["property"] = read_property_disposition(ctx["property"]["id"])
    return ctx


# ---------------------------------------------------------------- tier 5: de novo growth

def setup_de_novo_plan(market_area_id: str, **overrides) -> dict:
    """Record one de novo site plan and return it with its computed site score."""
    return get_success_data(
        api_client.create_de_novo_plan(
            de_novo_plan_payload(market_area_id, **overrides), STRATEGIST
        )
    )


def setup_approved_de_novo_plan(market_area_id: str, **overrides) -> dict:
    """Record a plan and carry it to APPROVED."""
    plan = setup_de_novo_plan(market_area_id, **overrides)
    return get_success_data(
        api_client.decide_de_novo_plan(plan["id"], {"decision": "APPROVE"}, APPROVER)
    )


def setup_opened_de_novo_branch(market_area_id: str, open_overrides=None,
                                **plan_overrides) -> dict:
    """Plan approved and opened as a live ramping branch. Returns (plan, branch)."""
    plan = setup_approved_de_novo_plan(market_area_id, **plan_overrides)
    body = {
        "branch_type": "LIMITED_SERVICE",
        "tenure_class": "LEASED",
        "onboarding_capacity_households_per_day": 40,
    }
    body.update(open_overrides or {})
    plan = get_success_data(api_client.open_de_novo_plan(plan["id"], body, STRATEGIST))
    return {"plan": plan, "branch": read_branch(plan["opened_branch_id"])}
