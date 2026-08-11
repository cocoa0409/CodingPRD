"""Composite setup helpers for multi-step test prerequisites.

All helpers use get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors. Identity threading: every entity-backed role call
passes the actual entity id through the make_*_headers builders (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BURN_DAY, BURN_DAY_TS
from .factories import (
    adjudicate_payload,
    assess_costs_payload,
    close_execution_payload,
    create_assignment_payload,
    create_association_payload,
    create_burn_boss_payload,
    create_burn_plan_payload,
    create_contingency_plan_payload,
    create_contractor_payload,
    create_cost_share_payload,
    create_execution_payload,
    create_ignition_plan_payload,
    create_incident_payload,
    create_landowner_payload,
    create_notification_payload,
    create_parcel_payload,
    create_permit_payload,
    create_smoke_approval_payload,
    create_weather_observation_payload,
    default_treatment_lines,
    go_no_go_payload,
    reject_reason_payload,
    set_clock_payload,
    submit_report_payload,
)
from .test_users import (
    ANY_READER_HEADERS,
    TEST_USERS,
    make_burn_boss_headers,
    make_contractor_headers,
    make_landowner_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AQO = TEST_USERS["aqo_headers"]
COMMANDER = TEST_USERS["commander_headers"]


# ─── Header helpers bound to a context dict ───────────

def ctx_author(ctx) -> dict:
    return make_burn_boss_headers(ctx["boss_a"]["id"])


def ctx_reviewer(ctx) -> dict:
    return make_reviewer_headers(ctx["boss_r"]["id"])


def ctx_landowner(ctx) -> dict:
    return make_landowner_headers(ctx["landowner"]["id"])


# ─── Tier 1: Registry and state progression ───────────

def setup_registry(fund: int = 10_000_000, airshed_cap: int = 500,
                   claim_cap: int = 500_000, landowner_cap: int = 1_000_000,
                   waiver_signed: bool = True) -> dict:
    """Association + landowner + author boss (RXB3) + reviewer boss (RXB3)."""
    ctx = {}
    ctx["assoc"] = get_success_data(api_client.create_association(
        create_association_payload(
            airshed_daily_acres_cap=airshed_cap,
            single_claim_cap_cents=claim_cap,
            landowner_liability_cap_cents=landowner_cap,
            initial_fund_cents=fund), ADMIN))
    ctx["landowner"] = get_success_data(api_client.create_landowner(
        create_landowner_payload(liability_waiver_signed=waiver_signed), ADMIN))
    ctx["boss_a"] = get_success_data(api_client.create_burn_boss(
        create_burn_boss_payload(name="Boss A"), ADMIN))
    ctx["boss_r"] = get_success_data(api_client.create_burn_boss(
        create_burn_boss_payload(name="Boss R"), ADMIN))
    return ctx


def ctx_add_landowner(ctx, key: str = "landowner2", **overrides) -> dict:
    lo = get_success_data(api_client.create_landowner(
        create_landowner_payload(name="Lo Two", contact_email="lo2@x.com", **overrides), ADMIN))
    ctx[key] = lo
    return lo


def ctx_add_boss(ctx, key: str = "boss_b", **overrides) -> dict:
    boss = get_success_data(api_client.create_burn_boss(
        create_burn_boss_payload(name="Boss B", **overrides), ADMIN))
    ctx[key] = boss
    return boss


def ctx_add_parcel(ctx, key: str = "parcel", **overrides) -> dict:
    parcel = get_success_data(api_client.create_parcel(
        create_parcel_payload(ctx["landowner"]["id"], **overrides), ctx_landowner(ctx)))
    ctx[key] = parcel
    return parcel


def ctx_add_plan(ctx, key: str = "plan", parcel_key: str = "parcel",
                 submit: bool = False, approve: bool = False, **overrides) -> dict:
    """Draft a plan against ctx[parcel_key] (OCC token re-read fresh), optionally
    submit and approve it. The stored plan always reflects the latest write."""
    parcel = get_success_data(api_client.get_parcel(ctx[parcel_key]["id"], ANY_READER_HEADERS))
    plan = get_success_data(api_client.create_burn_plan(
        create_burn_plan_payload(parcel["id"], parcel["version"], **overrides), ctx_author(ctx)))
    if submit or approve:
        plan = get_success_data(api_client.submit_plan(plan["id"], ctx_author(ctx)))
    if approve:
        plan = get_success_data(api_client.approve_plan(plan["id"], ctx_reviewer(ctx)))
    ctx[key] = plan
    return plan


def setup_approved_plan_ctx(fund: int = 10_000_000, parcel_overrides: dict = None,
                            plan_overrides: dict = None) -> dict:
    """Registry + parcel + plan walked to APPROVED."""
    ctx = setup_registry(fund=fund)
    ctx_add_parcel(ctx, **(parcel_overrides or {}))
    ctx_add_plan(ctx, approve=True, **(plan_overrides or {}))
    return ctx


# ─── Tier 2: Safety documents, permit, smoke, crews ───

def ctx_add_contingency(ctx, accept: bool = True) -> dict:
    cont = get_success_data(api_client.create_contingency_plan(
        ctx["plan"]["id"], create_contingency_plan_payload(), ctx_author(ctx)))
    if accept:
        cont = get_success_data(api_client.accept_contingency_plan(cont["id"], ctx_reviewer(ctx)))
    ctx["contingency"] = cont
    return cont


def ctx_add_ignition(ctx, accept: bool = True, **overrides) -> dict:
    plan = get_success_data(api_client.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS))
    ign = get_success_data(api_client.create_ignition_plan(
        plan["id"], create_ignition_plan_payload(plan["version"], **overrides), ctx_author(ctx)))
    if accept:
        ign = get_success_data(api_client.accept_ignition_plan(ign["id"], ctx_reviewer(ctx)))
    ctx["ignition"] = ign
    ctx["plan"] = get_success_data(api_client.get_burn_plan(plan["id"], ANY_READER_HEADERS))
    return ign


def ctx_add_permit(ctx, notifications_required: int = 1, confirm_count: int = None,
                   issue: bool = True) -> dict:
    """Permit + `confirm_count` confirmed notifications (default: all required),
    optionally issued. Issue requires the plan APPROVED and an ACCEPTED contingency."""
    perm = get_success_data(api_client.create_permit(
        ctx["plan"]["id"], create_permit_payload(notifications_required=notifications_required),
        ctx_author(ctx)))
    ctx["permit"] = perm
    ctx["notifications"] = []
    n = notifications_required if confirm_count is None else confirm_count
    for i in range(n):
        notif = get_success_data(api_client.create_notification(
            perm["id"], create_notification_payload(
                recipient_name=f"N{i + 1}", channel="MAIL" if i % 2 == 0 else "PHONE"),
            ctx_author(ctx)))
        notif = get_success_data(api_client.confirm_notification(notif["id"], ctx_author(ctx)))
        ctx["notifications"].append(notif)
    if issue:
        ctx["permit"] = get_success_data(api_client.issue_permit(perm["id"], ctx_reviewer(ctx)))
    return ctx["permit"]


def ctx_add_smoke(ctx, date: str = BURN_DAY, acres: int = None,
                  decision: str = "APPROVED") -> dict:
    acres = ctx["plan"]["planned_acres"] if acres is None else acres
    smoke = get_success_data(api_client.create_smoke_approval(
        ctx["plan"]["id"],
        create_smoke_approval_payload(requested_burn_date=date, requested_acres=acres),
        ctx_author(ctx)))
    if decision is not None:
        smoke = get_success_data(api_client.decide_smoke_approval(
            smoke["id"], {"decision": decision}, AQO))
    ctx["smoke"] = smoke
    return smoke


def ctx_add_order(ctx, fill: str = "full") -> dict:
    """Resource order with one contractor per required type, units == required_*.
    fill: "full" (all types confirmed), "engines_only", "none" (DRAFT, no submit),
    "submitted" (SUBMITTED, no assignments)."""
    order = get_success_data(api_client.create_resource_order(
        ctx["plan"]["id"], {}, ctx_author(ctx)))
    ctx["order"] = order
    ctx["contractors"] = {}
    ctx["assignments"] = []
    if fill == "none":
        return order
    ctx["order"] = get_success_data(api_client.submit_resource_order(order["id"], ctx_author(ctx)))
    if fill == "submitted":
        return ctx["order"]
    reqs = {
        "ENGINE": order["required_engines"],
        "HAND_CREW": order["required_hand_crews"],
        "DOZER": order["required_dozers"],
        "WATER_TENDER": order["required_water_tenders"],
    }
    for rtype, needed in reqs.items():
        if needed <= 0:
            continue
        if fill == "engines_only" and rtype != "ENGINE":
            continue
        contractor = get_success_data(api_client.create_contractor(
            create_contractor_payload(
                name=f"{rtype}Co", resource_type=rtype, capacity_units=needed,
                personnel_per_unit=5, day_rate_cents_per_unit=100_000), ADMIN))
        ctx["contractors"][rtype] = contractor
        asg = get_success_data(api_client.create_assignment(
            ctx["order"]["id"],
            create_assignment_payload(contractor["id"], units=needed), ctx_author(ctx)))
        asg = get_success_data(api_client.confirm_assignment(
            asg["id"], make_contractor_headers(contractor["id"])))
        ctx["assignments"].append(asg)
    ctx["order"] = get_success_data(api_client.get_resource_order(
        ctx["order"]["id"], ANY_READER_HEADERS))
    return ctx["order"]


# ─── Tier 3: Execution lifecycle shortcuts ────────────

def ctx_add_execution(ctx, date: str = BURN_DAY) -> dict:
    ex = get_success_data(api_client.create_execution(
        ctx["plan"]["id"], create_execution_payload(scheduled_date=date), ctx_author(ctx)))
    ctx["execution"] = ex
    return ex


def setup_burn_ready_ctx(fund: int = 10_000_000, notifications_required: int = 1,
                         burn_date: str = BURN_DAY, parcel_overrides: dict = None,
                         plan_overrides: dict = None) -> dict:
    """Full burn-ready state: plan APPROVED, ignition + contingency ACCEPTED,
    permit ISSUED, smoke APPROVED for burn_date, order FILLED, execution SCHEDULED."""
    ctx = setup_approved_plan_ctx(fund=fund, parcel_overrides=parcel_overrides,
                                  plan_overrides=plan_overrides)
    ctx_add_contingency(ctx)
    ctx_add_ignition(ctx)
    ctx_add_permit(ctx, notifications_required=notifications_required)
    ctx_add_smoke(ctx, date=burn_date)
    ctx_add_order(ctx, fill="full")
    ctx_add_execution(ctx, date=burn_date)
    return ctx


def ctx_set_burn_day(ctx, ts: str = BURN_DAY_TS, obs_overrides: dict = None) -> dict:
    """Advance the logical clock and record a weather observation stamped at `ts`."""
    get_success_data(api_client.set_clock(set_clock_payload(ts), ADMIN))
    obs = get_success_data(api_client.create_weather_observation(
        ctx["execution"]["id"],
        create_weather_observation_payload(observed_at=ts, **(obs_overrides or {})),
        ctx_author(ctx)))
    ctx["observation"] = obs
    return obs


def ctx_brief(ctx) -> dict:
    ctx["execution"] = get_success_data(api_client.brief_execution(
        ctx["execution"]["id"], ctx_author(ctx)))
    return ctx["execution"]


def ctx_go_no_go(ctx, results: dict = None) -> dict:
    checklist = get_success_data(api_client.submit_go_no_go(
        ctx["execution"]["id"], go_no_go_payload(results), ctx_author(ctx)))
    ctx["checklist"] = checklist
    ctx["execution"] = get_success_data(api_client.get_execution(
        ctx["execution"]["id"], ANY_READER_HEADERS))
    return checklist


def ctx_ignite(ctx) -> dict:
    ctx["execution"] = get_success_data(api_client.start_ignition(
        ctx["execution"]["id"], ctx_author(ctx)))
    return ctx["execution"]


def ctx_complete_ignition(ctx, acres: int) -> dict:
    ctx["execution"] = get_success_data(api_client.complete_ignition(
        ctx["execution"]["id"], {"acres_blackened": acres}, ctx_author(ctx)))
    return ctx["execution"]


def ctx_patrol_mopup_close(ctx, actual_lines: list) -> dict:
    get_success_data(api_client.begin_patrol(ctx["execution"]["id"], ctx_author(ctx)))
    get_success_data(api_client.begin_mop_up(ctx["execution"]["id"], ctx_author(ctx)))
    ctx["execution"] = get_success_data(api_client.close_execution(
        ctx["execution"]["id"], close_execution_payload(actual_lines), ctx_author(ctx)))
    return ctx["execution"]


def setup_closed_execution_ctx(fund: int = 10_000_000, acres_blackened: int = 80,
                               actual_lines: list = None,
                               plan_overrides: dict = None,
                               parcel_overrides: dict = None) -> dict:
    """Burn-ready plan driven all the way to CLOSED on the standard burn day."""
    ctx = setup_burn_ready_ctx(fund=fund, parcel_overrides=parcel_overrides,
                               plan_overrides=plan_overrides)
    ctx_set_burn_day(ctx)
    ctx_brief(ctx)
    ctx_go_no_go(ctx)
    ctx_ignite(ctx)
    ctx_complete_ignition(ctx, acres_blackened)
    lines = actual_lines if actual_lines is not None else default_treatment_lines(
        acres_blackened)
    ctx_patrol_mopup_close(ctx, lines)
    return ctx


def ctx_escape(ctx) -> dict:
    """Declare an escape; returns the auto-created ESCAPE incident."""
    get_success_data(api_client.declare_escape(ctx["execution"]["id"], ctx_author(ctx)))
    ctx["execution"] = get_success_data(api_client.get_execution(
        ctx["execution"]["id"], ANY_READER_HEADERS))
    incidents = get_success_data(api_client.list_execution_incidents(
        ctx["execution"]["id"], ANY_READER_HEADERS))
    ctx["incident"] = incidents[0]
    return ctx["incident"]


def setup_escaped_ctx(fund: int = 10_000_000) -> dict:
    """Burn-ready plan driven to IGNITION then ESCAPED; ctx carries the incident."""
    ctx = setup_burn_ready_ctx(fund=fund)
    ctx_set_burn_day(ctx)
    ctx_brief(ctx)
    ctx_go_no_go(ctx)
    ctx_ignite(ctx)
    ctx_escape(ctx)
    return ctx


def ctx_assess_and_file_claim(ctx, incident: dict, cost: int = 3_000_000,
                              acres: int = 60):
    """Walk an incident to ASSESSED, file a claim, begin investigation.
    Returns (incident, claim at UNDER_INVESTIGATION)."""
    get_success_data(api_client.confirm_incident(incident["id"], COMMANDER))
    get_success_data(api_client.mark_incident_contained(incident["id"], COMMANDER))
    get_success_data(api_client.close_incident(incident["id"], COMMANDER))
    incident = get_success_data(api_client.assess_incident_costs(
        incident["id"], assess_costs_payload(
            suppression_cost_cents=cost, escaped_acres=acres), COMMANDER))
    claim = get_success_data(api_client.create_liability_claim(incident["id"], {}, COMMANDER))
    claim = get_success_data(api_client.begin_claim_investigation(claim["id"], ADMIN))
    return incident, claim


# ─── Tier 4: Cost-share and monitoring ────────────────

def ctx_add_agreement(ctx, tier: str = "STANDARD", lines: list = None,
                      approve: bool = True) -> dict:
    lines = lines if lines is not None else default_treatment_lines(
        ctx["plan"]["planned_acres"])
    agr = get_success_data(api_client.create_cost_share_agreement(
        create_cost_share_payload(ctx["landowner"]["id"], ctx["plan"]["id"],
                                  funding_tier=tier, treatment_lines=lines),
        ctx_landowner(ctx)))
    if approve:
        get_success_data(api_client.begin_agreement_review(agr["id"], ADMIN))
        agr = get_success_data(api_client.approve_agreement(agr["id"], ADMIN))
    ctx["agreement"] = agr
    return agr


def ctx_reports(ctx) -> list:
    """The execution's monitoring reports, due_at ascending (PRD §3.8)."""
    return get_success_data(api_client.list_execution_monitoring_reports(
        ctx["execution"]["id"], ANY_READER_HEADERS))


def ctx_submit_report(ctx, report: dict, lines: list) -> dict:
    return get_success_data(api_client.submit_monitoring_report(
        report["id"], submit_report_payload(lines), ctx_author(ctx)))


def ctx_accept_report(ctx, report: dict) -> dict:
    return get_success_data(api_client.accept_monitoring_report(report["id"], ctx_reviewer(ctx)))


def ctx_disburse(ctx) -> dict:
    ctx["agreement"] = get_success_data(api_client.disburse_agreement(
        ctx["agreement"]["id"], ADMIN))
    return ctx["agreement"]


# ─── Tier 5: Full fiscal lifecycle ────────────────────

def setup_partially_disbursed_ctx(fund: int = 10_000_000, tier: str = "LEGACY",
                                  agreement_lines: list = None,
                                  acres_blackened: int = 14,
                                  actual_lines: list = None) -> dict:
    """Full chain: burn CLOSED, agreement APPROVED, provisional installment disbursed."""
    if actual_lines is None:
        actual_lines = [
            {"category": "BROADCAST", "rate_class": "GRASS", "acres": 11},
            {"category": "UNDERSTORY", "rate_class": "BRUSH", "acres": 3},
        ]
    if agreement_lines is None:
        agreement_lines = [
            {"category": "BROADCAST", "rate_class": "GRASS", "acres": 12},
            {"category": "UNDERSTORY", "rate_class": "BRUSH", "acres": 3},
        ]
    ctx = setup_burn_ready_ctx(fund=fund)
    ctx_add_agreement(ctx, tier=tier, lines=agreement_lines)
    ctx_set_burn_day(ctx)
    ctx_brief(ctx)
    ctx_go_no_go(ctx)
    ctx_ignite(ctx)
    ctx_complete_ignition(ctx, acres_blackened)
    ctx_patrol_mopup_close(ctx, actual_lines)
    ctx_disburse(ctx)
    return ctx


def setup_thirty_day_accepted_ctx(**kwargs) -> dict:
    """Partially disbursed + THIRTY_DAY report submitted with actuals and ACCEPTED."""
    ctx = setup_partially_disbursed_ctx(**kwargs)
    report = ctx_reports(ctx)[2]
    lines = kwargs.get("actual_lines") or [
        {"category": "BROADCAST", "rate_class": "GRASS", "acres": 11},
        {"category": "UNDERSTORY", "rate_class": "BRUSH", "acres": 3},
    ]
    ctx["report_30d"] = ctx_submit_report(ctx, report, lines)
    ctx["report_30d"] = ctx_accept_report(ctx, ctx["report_30d"])
    return ctx


def setup_adjudicated_claim_ctx(fund: int = 10_000_000, outcome: str = "ASSOCIATION_LIABLE",
                                negligence: bool = False, cost: int = 3_000_000,
                                acres: int = 60) -> dict:
    """Escaped execution -> incident assessed -> claim UNDER_INVESTIGATION -> adjudicated."""
    ctx = setup_escaped_ctx(fund=fund)
    incident, claim = ctx_assess_and_file_claim(ctx, ctx["incident"], cost=cost, acres=acres)
    ctx["incident"] = incident
    ctx["claim"] = get_success_data(api_client.adjudicate_claim(
        claim["id"], adjudicate_payload(outcome, negligence), ADMIN))
    return ctx
