"""Burn execution, weather observation, go/no-go checklist, and incident routes."""
from datetime import timedelta

from flask import Blueprint

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    clock,
    ok,
    paginate,
    parse_date,
    parse_datetime,
    require_role,
    stamp_new,
    touch,
)
from domain import (
    EXECUTION_TERMINAL,
    REQUIRED_CHECKLIST_ITEMS,
    accepted_contingency,
    accepted_ignition,
    active_order,
    closed_executions_on_parcel,
    get_assignment,
    get_execution,
    get_incident,
    get_plan,
    in_prescription,
    latest_observation,
    non_terminal_execution_on_parcel,
    non_terminal_execution_on_plan,
    observation_fresh,
    open_incidents,
    order_confirmed,
    permit_rollups,
    plan_permit,
    ser_checklist,
    ser_execution,
    ser_incident,
    ser_observation,
    valid_smoke_for,
    wildfire_cascade,
)

bp = Blueprint("executions", __name__)


def _author_or_403(plan, uid):
    if plan is None or uid != plan["author_boss_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the plan's author")


def _plan_of_execution(ex):
    return DB["plans"].get(ex["burn_plan_id"])


def _parcel_of_plan(plan):
    return DB["parcels"].get(plan["parcel_id"]) if plan else None


# ---------------------------------------------------------------------------
# Executions
# ---------------------------------------------------------------------------


@bp.post("/burn-plans/<pid>/executions")
def schedule_execution(pid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_or_403(plan, uid)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    # uniqueness (priority 11): one non-terminal execution per plan / per parcel
    if non_terminal_execution_on_plan(plan["id"]) is not None:
        raise ApiError(
            "ERR_EXECUTION_ALREADY_OPEN", 409, "Plan already has a non-terminal execution"
        )
    if non_terminal_execution_on_parcel(plan["parcel_id"]) is not None:
        raise ApiError(
            "ERR_PARCEL_EXECUTION_WINDOW_CONFLICT",
            409,
            "Another non-terminal execution exists on the parcel",
        )
    # temporal (priority 12): inside plan window, then parcel monitoring gap
    sd = parse_date(data.get("scheduled_date"))
    if sd is not None:
        if sd < plan["planned_window_start"] or sd > plan["planned_window_end"]:
            raise ApiError(
                "ERR_SCHEDULED_DATE_OUTSIDE_WINDOW",
                422,
                "scheduled_date is outside the plan's prescription window",
            )
        for prev in closed_executions_on_parcel(plan["parcel_id"]):
            if prev["closed_at"] is not None:
                gap_end = (prev["closed_at"] + timedelta(days=30)).date()
                if sd <= gap_end:
                    raise ApiError(
                        "ERR_PARCEL_EXECUTION_WINDOW_CONFLICT",
                        409,
                        "scheduled_date must be more than 30 days after the prior "
                        "closed execution on the parcel",
                    )
    v = Validator(data, {"scheduled_date"})
    v.date("scheduled_date")
    v.finish()
    execution = stamp_new(
        {
            "burn_plan_id": plan["id"],
            "scheduled_date": sd,
            "plan_version_at_schedule": plan["version"],
            "acres_blackened": None,
            "actual_treatment_lines": None,
            "closed_at": None,
            "phase": "SCHEDULED",
        }
    )
    DB["executions"][execution["id"]] = execution
    return ok(ser_execution(execution), 201)


@bp.get("/executions/<eid>")
def get_one_execution(eid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_execution(get_execution(eid)))


@bp.get("/burn-plans/<pid>/executions")
def list_plan_executions(pid):
    _, role = auth()
    require_role(role, None)
    plan = get_plan(pid)
    items = [e for e in DB["executions"].values() if e["burn_plan_id"] == plan["id"]]
    return paginate(items, ser_execution)


@bp.post("/executions/<eid>/cancel")
def cancel_execution(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] != "SCHEDULED":
        raise ApiError("ERR_EXECUTION_NOT_SCHEDULED", 409, "Execution must be SCHEDULED")
    ex["phase"] = "CANCELLED"
    touch(ex)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/brief")
def brief_execution(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    plan = _plan_of_execution(ex)
    _author_or_403(plan, uid)
    if ex["phase"] != "SCHEDULED":
        raise ApiError("ERR_EXECUTION_NOT_SCHEDULED", 409, "Execution must be SCHEDULED")
    # burn-day safety conditions (priority 8)
    order = active_order(plan)
    if order is None or order["status"] != "FILLED":
        raise ApiError(
            "ERR_HOLDING_FORCE_INADEQUATE", 422, "The plan's resource order is not FILLED"
        )
    if accepted_ignition(plan["id"]) is None:
        raise ApiError(
            "ERR_IGNITION_PLAN_NOT_ACCEPTED", 409, "No ACCEPTED ignition plan for the plan"
        )
    if accepted_contingency(plan["id"]) is None:
        raise ApiError(
            "ERR_CONTINGENCY_NOT_ACCEPTED", 409, "No ACCEPTED contingency plan for the plan"
        )
    permit = plan_permit(plan["id"])
    if permit is None or permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "The plan's permit must be ISSUED")
    if valid_smoke_for(plan["id"], ex["scheduled_date"]) is None:
        raise ApiError(
            "ERR_SMOKE_APPROVAL_NOT_VALID",
            409,
            "No APPROVED/CONDITIONALLY_APPROVED smoke approval matches the scheduled_date",
        )
    # referential (priority 10): pinned plan version
    if ex["plan_version_at_schedule"] != plan["version"]:
        raise ApiError(
            "ERR_STALE_PLAN_VERSION",
            409,
            "Plan has changed since the execution was scheduled",
        )
    # temporal (priority 12)
    if clock().date() != ex["scheduled_date"]:
        raise ApiError(
            "ERR_WRONG_BURN_DAY", 422, "Current clock date is not the scheduled_date"
        )
    _, notified_at = permit_rollups(permit)
    if notified_at is None or clock() < notified_at + timedelta(hours=48):
        raise ApiError(
            "ERR_NOTIFICATION_LEAD_TIME_UNMET",
            422,
            "Fewer than 48 hours since the last confirmed notification",
        )
    ex["phase"] = "BRIEFED"
    touch(ex)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/weather-observations")
def record_observation(eid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    plan = _plan_of_execution(ex)
    _author_or_403(plan, uid)
    if ex["phase"] in EXECUTION_TERMINAL:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Weather observations require a non-terminal execution",
        )
    v = Validator(
        data,
        {"observed_at", "wind_mph", "fuel_moisture_pct", "rh_pct", "temp_f", "mixing_height_ft"},
    )
    v.datetime("observed_at")
    for f in ("wind_mph", "fuel_moisture_pct", "rh_pct", "temp_f", "mixing_height_ft"):
        v.req(f, int)
    v.finish()
    obs = stamp_new(
        {
            "burn_execution_id": ex["id"],
            "observed_at": parse_datetime(data["observed_at"]),
            "wind_mph": data["wind_mph"],
            "fuel_moisture_pct": data["fuel_moisture_pct"],
            "rh_pct": data["rh_pct"],
            "temp_f": data["temp_f"],
            "mixing_height_ft": data["mixing_height_ft"],
        },
        with_version=False,
    )
    obs["in_prescription"] = in_prescription(plan, obs)
    DB["observations"][obs["id"]] = obs
    return ok(ser_observation(obs), 201)


@bp.get("/executions/<eid>/weather-observations")
def list_observations(eid):
    _, role = auth()
    require_role(role, None)
    ex = get_execution(eid)
    items = [o for o in DB["observations"].values() if o["burn_execution_id"] == ex["id"]]
    return paginate(items, ser_observation)


@bp.post("/executions/<eid>/go-no-go")
def go_no_go(eid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    plan = _plan_of_execution(ex)
    _author_or_403(plan, uid)
    if ex["phase"] != "BRIEFED":
        raise ApiError("ERR_EXECUTION_NOT_BRIEFED", 409, "Execution must be BRIEFED")
    # checklist completeness (determines GO/NO_GO branch)
    answers = data.get("checklist_answers")
    incomplete = False
    if not isinstance(answers, list):
        incomplete = True
    else:
        seen = {}
        for a in answers:
            if not isinstance(a, dict):
                incomplete = True
                break
            item = a.get("item")
            result = a.get("result")
            if item not in REQUIRED_CHECKLIST_ITEMS or result not in ("PASS", "FAIL"):
                incomplete = True
                break
            if item in seen:
                incomplete = True
                break
            seen[item] = result
        if not incomplete and set(seen.keys()) != REQUIRED_CHECKLIST_ITEMS:
            incomplete = True
    if incomplete:
        raise ApiError(
            "ERR_INCOMPLETE_CHECKLIST",
            422,
            "checklist_answers must cover exactly the six required items with PASS|FAIL",
        )
    verdict = "GO" if all(a["result"] == "PASS" for a in answers) else "NO_GO"
    latest = latest_observation(ex["id"])
    if verdict == "GO":
        # safety (priority 8): in-prescription + holding force
        if latest is not None and not latest["in_prescription"]:
            raise ApiError(
                "ERR_WEATHER_OUT_OF_PRESCRIPTION",
                422,
                "Latest observation is outside the plan's prescription",
            )
        order = active_order(plan)
        if order is None:
            raise ApiError(
                "ERR_HOLDING_FORCE_INADEQUATE", 422, "Holding force is inadequate"
            )
        c = order_confirmed(order)
        if not (
            c["ENGINE"] >= order["required_engines"]
            and c["HAND_CREW"] >= order["required_hand_crews"]
            and c["DOZER"] >= order["required_dozers"]
            and c["WATER_TENDER"] >= order["required_water_tenders"]
        ):
            raise ApiError(
                "ERR_HOLDING_FORCE_INADEQUATE", 422, "Holding force is inadequate"
            )
        # temporal (priority 12): freshness
        if latest is None or not observation_fresh(latest):
            raise ApiError(
                "ERR_WEATHER_OBSERVATION_STALE",
                422,
                "No observation or latest observation older than 60 minutes",
            )
    checklist = stamp_new(
        {
            "burn_execution_id": ex["id"],
            "weather_observation_id": latest["id"] if latest else None,
            "answers": answers,
            "verdict": verdict,
            "evaluated_at": clock(),
        },
        with_version=False,
    )
    DB["checklists"][checklist["id"]] = checklist
    ex["phase"] = "TEST_FIRE" if verdict == "GO" else "STOOD_DOWN"
    touch(ex)
    return ok(ser_checklist(checklist))


@bp.get("/executions/<eid>/checklists")
def list_checklists(eid):
    _, role = auth()
    require_role(role, None)
    ex = get_execution(eid)
    items = [c for c in DB["checklists"].values() if c["burn_execution_id"] == ex["id"]]
    return paginate(items, ser_checklist)


@bp.post("/executions/<eid>/stand-down")
def stand_down(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] != "BRIEFED":
        raise ApiError("ERR_EXECUTION_NOT_BRIEFED", 409, "Execution must be BRIEFED")
    ex["phase"] = "STOOD_DOWN"
    touch(ex)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/start-ignition")
def start_ignition(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] != "TEST_FIRE":
        raise ApiError(
            "ERR_EXECUTION_NOT_IN_TEST_FIRE", 409, "Execution must be TEST_FIRE"
        )
    latest = latest_observation(ex["id"])
    if latest is not None and not latest["in_prescription"]:
        raise ApiError(
            "ERR_WEATHER_OUT_OF_PRESCRIPTION",
            422,
            "Latest observation is outside the plan's prescription",
        )
    if latest is None or not observation_fresh(latest):
        raise ApiError(
            "ERR_WEATHER_OBSERVATION_STALE",
            422,
            "No observation or latest observation older than 60 minutes",
        )
    ex["phase"] = "IGNITION"
    touch(ex)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/complete-ignition")
def complete_ignition(eid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] != "IGNITION":
        raise ApiError("ERR_EXECUTION_NOT_IGNITING", 409, "Execution must be IGNITION")
    v = Validator(data, {"acres_blackened"})
    v.req("acres_blackened", int)
    if v.typed("acres_blackened", int) is not None and v.typed("acres_blackened", int) < 0:
        v.invalid("acres_blackened must be >= 0")
    v.finish()
    ex["acres_blackened"] = data["acres_blackened"]
    ex["phase"] = "HOLDING"
    touch(ex)
    return ok(ser_execution(ex))


def _no_open_incidents(ex):
    if open_incidents(ex["id"]):
        raise ApiError(
            "ERR_OPEN_INCIDENTS_EXIST",
            409,
            "Incidents in REPORTED or CONFIRMED block this transition",
        )


@bp.post("/executions/<eid>/begin-patrol")
def begin_patrol(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] != "HOLDING":
        raise ApiError("ERR_EXECUTION_NOT_HOLDING", 409, "Execution must be HOLDING")
    _no_open_incidents(ex)
    ex["phase"] = "PATROL"
    touch(ex)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/begin-mop-up")
def begin_mop_up(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] != "PATROL":
        raise ApiError("ERR_EXECUTION_NOT_PATROLLING", 409, "Execution must be PATROL")
    _no_open_incidents(ex)
    ex["phase"] = "MOP_UP"
    touch(ex)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/close")
def close_execution(eid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    plan = _plan_of_execution(ex)
    _author_or_403(plan, uid)
    if ex["phase"] != "MOP_UP":
        raise ApiError("ERR_EXECUTION_NOT_MOPPING_UP", 409, "Execution must be MOP_UP")
    _no_open_incidents(ex)
    v = Validator(data, {"actual_treatment_lines"})
    lines = data.get("actual_treatment_lines")
    if lines is None:
        v.invalid("Missing required field: actual_treatment_lines")
    elif not isinstance(lines, list):
        v.invalid("actual_treatment_lines must be an array")
    else:
        for idx, line in enumerate(lines):
            if not isinstance(line, dict):
                v.invalid(f"actual_treatment_lines[{idx}] must be an object")
                break
            extra = set(line.keys()) - {"category", "rate_class", "acres"}
            if extra:
                v.invalid(f"actual_treatment_lines[{idx}] has unknown field")
                break
            cat, rc, acres = line.get("category"), line.get("rate_class"), line.get("acres")
            if cat is None or rc is None or acres is None:
                v.invalid(f"actual_treatment_lines[{idx}] is missing a field")
                break
            if not isinstance(cat, str) or not isinstance(rc, str):
                v.invalid(f"actual_treatment_lines[{idx}] has an invalid type")
                break
            if cat not in ("BROADCAST", "UNDERSTORY", "PILE_BURN"):
                v._set("ERR_INVALID_ENUM", f"actual_treatment_lines[{idx}].category is invalid")
                break
            if rc not in ("GRASS", "BRUSH", "TIMBER"):
                v._set("ERR_INVALID_ENUM", f"actual_treatment_lines[{idx}].rate_class is invalid")
                break
            if not (isinstance(acres, int) and not isinstance(acres, bool)) or acres < 0:
                v.invalid(f"actual_treatment_lines[{idx}].acres must be a non-negative integer")
                break
    v.finish()
    ex["actual_treatment_lines"] = lines
    ex["closed_at"] = clock()
    ex["phase"] = "CLOSED"
    touch(ex)
    # spawn the three monitoring reports
    for report_type, delta in (
        ("FIRST_24H", timedelta(hours=24)),
        ("SEVEN_DAY", timedelta(days=7)),
        ("THIRTY_DAY", timedelta(days=30)),
    ):
        report = stamp_new(
            {
                "burn_execution_id": ex["id"],
                "report_type": report_type,
                "due_at": ex["closed_at"] + delta,
                "actual_treatment_lines": None,
                "effectiveness_score": None,
                "deficiency_reason": None,
                "status": "DUE",
            }
        )
        DB["reports"][report["id"]] = report
    # complete every CONFIRMED crew assignment on the plan's orders
    for order in DB["orders"].values():
        if order["burn_plan_id"] != plan["id"]:
            continue
        for a in DB["assignments"].values():
            if a["resource_order_id"] == order["id"] and a["status"] == "CONFIRMED":
                a["status"] = "COMPLETED"
                touch(a)
    return ok(ser_execution(ex))


@bp.post("/executions/<eid>/declare-escape")
def declare_escape(eid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ex = get_execution(eid)
    _author_or_403(_plan_of_execution(ex), uid)
    if ex["phase"] not in ("TEST_FIRE", "IGNITION", "HOLDING", "PATROL"):
        raise ApiError(
            "ERR_EXECUTION_NOT_ESCAPABLE",
            409,
            "Execution must be in TEST_FIRE, IGNITION, HOLDING, or PATROL",
        )
    ex["phase"] = "ESCAPED"
    touch(ex)
    incident = stamp_new(
        {
            "burn_execution_id": ex["id"],
            "incident_type": "ESCAPE",
            "response_status": "REPORTED",
            "billing_status": "UNASSESSED",
            "suppression_cost_cents": None,
            "escaped_acres": None,
        }
    )
    DB["incidents"][incident["id"]] = incident
    return ok(ser_execution(ex))


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@bp.post("/executions/<eid>/incidents")
def report_incident(eid):
    data = body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    ex = get_execution(eid)
    if ex["phase"] not in ("TEST_FIRE", "IGNITION", "HOLDING", "PATROL", "ESCAPED"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Execution is not in a phase that accepts incident reports",
        )
    v = Validator(data, {"incident_type"})
    v.enum("incident_type", {"SPOT", "SMOKE_INTRUSION"})
    v.finish()
    incident = stamp_new(
        {
            "burn_execution_id": ex["id"],
            "incident_type": data["incident_type"],
            "response_status": "REPORTED",
            "billing_status": "UNASSESSED",
            "suppression_cost_cents": None,
            "escaped_acres": None,
        }
    )
    DB["incidents"][incident["id"]] = incident
    return ok(ser_incident(incident), 201)


@bp.get("/incidents/<iid>")
def get_one_incident(iid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_incident(get_incident(iid)))


@bp.get("/executions/<eid>/incidents")
def list_incidents(eid):
    _, role = auth()
    require_role(role, None)
    ex = get_execution(eid)
    items = [i for i in DB["incidents"].values() if i["burn_execution_id"] == ex["id"]]
    return paginate(items, ser_incident)


@bp.post("/incidents/<iid>/confirm")
def confirm_incident(iid):
    body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["response_status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_NOT_REPORTED", 409, "Incident must be REPORTED")
    incident["response_status"] = "CONFIRMED"
    touch(incident)
    return ok(ser_incident(incident))


@bp.post("/incidents/<iid>/dismiss")
def dismiss_incident(iid):
    body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["response_status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_NOT_REPORTED", 409, "Incident must be REPORTED")
    incident["response_status"] = "DISMISSED"
    touch(incident)
    return ok(ser_incident(incident))


@bp.post("/incidents/<iid>/mark-contained")
def mark_contained(iid):
    body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["response_status"] != "CONFIRMED":
        raise ApiError("ERR_INCIDENT_NOT_CONFIRMED", 409, "Incident must be CONFIRMED")
    incident["response_status"] = "CONTAINED"
    touch(incident)
    return ok(ser_incident(incident))


@bp.post("/incidents/<iid>/declare-wildfire")
def declare_wildfire(iid):
    body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["response_status"] != "CONFIRMED":
        raise ApiError("ERR_INCIDENT_NOT_CONFIRMED", 409, "Incident must be CONFIRMED")
    incident["response_status"] = "DECLARED_WILDFIRE"
    touch(incident)
    wildfire_cascade(incident)
    return ok(ser_incident(incident))


@bp.post("/incidents/<iid>/close")
def close_incident(iid):
    body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["response_status"] != "CONTAINED":
        raise ApiError("ERR_INCIDENT_NOT_CONTAINED", 409, "Incident must be CONTAINED")
    incident["response_status"] = "CLOSED"
    touch(incident)
    return ok(ser_incident(incident))


@bp.post("/incidents/<iid>/assess-costs")
def assess_costs(iid):
    data = body()
    _, role = auth()
    require_role(role, {"IncidentCommander"})
    incident = get_incident(iid)
    if incident["billing_status"] != "UNASSESSED":
        raise ApiError(
            "ERR_BILLING_NOT_UNASSESSED", 409, "Incident billing must be UNASSESSED"
        )
    if incident["response_status"] not in ("CONTAINED", "CLOSED", "DECLARED_WILDFIRE"):
        raise ApiError(
            "ERR_INCIDENT_NOT_COSTABLE",
            409,
            "Incident must be CONTAINED, CLOSED, or DECLARED_WILDFIRE",
        )
    v = Validator(data, {"suppression_cost_cents", "escaped_acres"})
    v.req("suppression_cost_cents", int)
    v.req("escaped_acres", int)
    if v.typed("suppression_cost_cents", int) is not None and v.typed("suppression_cost_cents", int) < 0:
        v.invalid("suppression_cost_cents must be >= 0")
    if v.typed("escaped_acres", int) is not None and v.typed("escaped_acres", int) < 0:
        v.invalid("escaped_acres must be >= 0")
    v.finish()
    incident["suppression_cost_cents"] = data["suppression_cost_cents"]
    incident["escaped_acres"] = data["escaped_acres"]
    incident["billing_status"] = "ASSESSED"
    touch(incident)
    return ok(ser_incident(incident))
