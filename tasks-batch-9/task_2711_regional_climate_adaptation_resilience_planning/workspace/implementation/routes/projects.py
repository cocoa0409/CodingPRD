"""PRD 3.5 and 3.6 -- proposing, screening, linking and analysing projects."""

from flask import Blueprint

import calc
import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import (ROLE_PROJECT_SPONSOR, ROLE_REGIONAL_ADMINISTRATOR, acting_user,
                  guard, require_owned_jurisdiction)
from errors import fail

bp = Blueprint("projects", __name__)

HAZARD_TYPES = ("HEAT", "FLOOD", "DROUGHT", "STORM")
STRATEGY_TYPES = ("PROTECT", "ACCOMMODATE", "RETREAT", "AVOID")
BCA_METHODS = ("DISCOUNTED_NPV", "ANNUALIZED_EQUIVALENT")
PROPOSABLE_CYCLE_STATES = ("DRAFT", "ENGAGEMENT", "REVISION")


@bp.post("/resilience/projects")
@guard(ROLE_PROJECT_SPONSOR)
def create_project():
    body = validate.json_body()
    cycle = lookup.need_ref("plan_cycle", body, "plan_cycle_id")
    if cycle is None:
        validate.bad("plan_cycle_id", "is required.")
    jurisdiction = lookup.need_ref("jurisdiction", body, "jurisdiction_id")
    if jurisdiction is None:
        validate.bad("jurisdiction_id", "is required.")
    prerequisite = lookup.need_ref("project", body, "prerequisite_project_id")

    require_owned_jurisdiction(jurisdiction["id"], roles=(ROLE_PROJECT_SPONSOR,))

    name = validate.string_field(body, "name", required=True, min_len=1, max_len=120)
    hazard_type = validate.enum_field(body, "hazard_type", HAZARD_TYPES, required=True)
    strategy_type = validate.enum_field(body, "strategy_type", STRATEGY_TYPES, required=True)
    base_cost = validate.int_field(body, "base_cost_cents", required=True, minimum=1)
    service_life = validate.int_field(
        body, "service_life_years", required=True, minimum=10, maximum=75
    )
    cobenefit = validate.int_field(
        body, "cobenefit_points", required=True, minimum=0, maximum=20
    )
    feasibility = validate.dec_field(
        body, "feasibility_score", required=True, minimum=0, maximum=1
    )
    indicator_code = validate.string_field(body, "indicator_code", min_len=1, max_len=40)
    indicator_target = validate.dec_field(body, "indicator_target_value", exclusive_minimum=0)

    if jurisdiction["status"] != "ACTIVE":
        fail("ERR_JURISDICTION_NOT_ACTIVE", "The sponsoring jurisdiction is not ACTIVE.")
    if cycle["status"] not in PROPOSABLE_CYCLE_STATES:
        fail(
            "ERR_PLAN_CYCLE_STATE_INVALID",
            "The plan cycle accepts no new projects in %s." % cycle["status"],
        )

    record = {
        "plan_cycle_id": cycle["id"],
        "jurisdiction_id": jurisdiction["id"],
        "prerequisite_project_id": prerequisite["id"] if prerequisite is not None else None,
        "capital_program_id": None,
        "name": name,
        "hazard_type": hazard_type,
        "strategy_type": strategy_type,
        "base_cost_cents": base_cost,
        "service_life_years": service_life,
        "cobenefit_points": cobenefit,
        "feasibility_score": feasibility,
        "screening_status": "PROPOSED",
        "screen_score": None,
        "analysis_status": "NOT_ANALYZED",
        "program_status": "UNPROGRAMMED",
        "escalated_cost_cents": None,
        "admin_rate_bps": None,
        "admin_fee_cents": None,
        "total_program_cost_cents": None,
        "grant_match_share_bps": None,
        "allocated_cents": 0,
        "equity_benefit_share_bps": None,
        "priority_score": None,
        "equity_waiver_granted": False,
        "waiver_rationale": None,
        "grant_hold_flag": False,
        "grant_funder": None,
        "grant_submitted_at": None,
        "awarded_at": None,
        "indicator_code": indicator_code,
        "indicator_target_value": indicator_target,
        "indicator_latest_value": None,
        "indicator_attainment_pct": None,
        "latest_period_label": None,
        "reported_period_count": 0,
        "implementation_status": "NOT_STARTED",
    }
    store.insert(store.projects, record)
    try:
        cascades.walk_project_chain(record["id"], record["prerequisite_project_id"])
    except Exception:
        del store.projects[record["id"]]
        raise
    return envelope.created(serialize.project(record))


@bp.get("/resilience/projects")
@guard()
def list_projects():
    rows = envelope.match(
        store.ordered(store.projects),
        plan_cycle_id=envelope.str_filter("plan_cycle_id"),
        jurisdiction_id=envelope.str_filter("jurisdiction_id"),
        prerequisite_project_id=envelope.str_filter("prerequisite_project_id"),
        capital_program_id=envelope.str_filter("capital_program_id"),
        hazard_type=envelope.str_filter("hazard_type"),
        strategy_type=envelope.str_filter("strategy_type"),
        screening_status=envelope.str_filter("screening_status"),
        analysis_status=envelope.str_filter("analysis_status"),
        program_status=envelope.str_filter("program_status"),
        implementation_status=envelope.str_filter("implementation_status"),
    )
    return envelope.listing(rows, serialize.project)


@bp.get("/resilience/projects/<project_id>")
@guard()
def get_project(project_id):
    row = lookup.need("project", project_id)
    return envelope.ok(serialize.project(row))


@bp.patch("/resilience/projects/<project_id>")
@guard(ROLE_PROJECT_SPONSOR)
def amend_project(project_id):
    project = lookup.need("project", project_id)
    body = validate.json_body()
    prerequisite = lookup.need_ref("project", body, "prerequisite_project_id")
    require_owned_jurisdiction(project["jurisdiction_id"], roles=(ROLE_PROJECT_SPONSOR,))

    indicator_code = validate.string_field(body, "indicator_code", min_len=1, max_len=40)
    indicator_target = validate.dec_field(body, "indicator_target_value", exclusive_minimum=0)

    if project["program_status"] != "UNPROGRAMMED":
        fail(
            "ERR_PROJECT_ALREADY_PROGRAMMED",
            "A programmed project's prerequisite and indicator definition are frozen.",
        )

    prerequisite_id = project["prerequisite_project_id"]
    if "prerequisite_project_id" in body:
        prerequisite_id = prerequisite["id"] if prerequisite is not None else None
    cascades.walk_project_chain(project["id"], prerequisite_id)

    project["prerequisite_project_id"] = prerequisite_id
    if indicator_code is not None:
        project["indicator_code"] = indicator_code
    if indicator_target is not None:
        project["indicator_target_value"] = indicator_target
    store.touch(project)
    return envelope.ok(serialize.project(project))


@bp.post("/resilience/projects/<project_id>/screen")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def screen_project(project_id):
    project = lookup.need("project", project_id)
    if project["screening_status"] != "PROPOSED":
        fail("ERR_PROJECT_ALREADY_SCREENED", "The project has already been screened.")

    escalated, admin_rate, admin_fee, total, match_share = calc.cost_stack(
        project["base_cost_cents"], project["strategy_type"]
    )
    score = calc.screen_score(total, project["cobenefit_points"], project["feasibility_score"])
    project["escalated_cost_cents"] = escalated
    project["admin_rate_bps"] = admin_rate
    project["admin_fee_cents"] = admin_fee
    project["total_program_cost_cents"] = total
    project["grant_match_share_bps"] = match_share
    project["screen_score"] = score
    project["screening_status"] = (
        "SCREENED_IN" if score >= calc.SCREEN_FLOOR else "SCREENED_OUT"
    )
    store.touch(project)
    return envelope.ok(serialize.project(project))
