"""Observations and near misses: submission and triage (PRD 3.4)."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import calc, core, ops

bp = Blueprint("observations", __name__)


@bp.route("/safety/observations", methods=["POST"])
def create_observation():
    auth(["Employee", "Supervisor", "SafetyManager"])
    body = core.body_json()
    program_id = core.req_str(body, "program_id")
    reporter_id = core.req_str(body, "reporter_id")
    kind = core.req_enum(body, "kind", ("OBSERVATION", "NEAR_MISS"))
    description = core.req_str(body, "description")
    occurred_at = core.req_datetime(body, "occurred_at")
    p = core.get_or_404("programs", program_id, "SafetyProgram")
    core.get_or_404("employees", reporter_id, "Employee")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409,
                       "Observations can be submitted only against an ACTIVE program")
    if occurred_at > CLOCK.now():
        raise ApiError("ERR_FUTURE_DATE_NOT_ALLOWED", 422,
                       "occurred_at must not be in the future")
    o = core.stamp_new({
        "id": core.new_id(),
        "program_id": p["id"],
        "reporter_id": reporter_id,
        "kind": kind,
        "description": description,
        "occurred_at": occurred_at,
        "linked_hazard_id": None,
        "status": "SUBMITTED",
    })
    db.DB["observations"][o["id"]] = o
    return ok(core.observation_view(o), 201)


@bp.route("/safety/observations", methods=["GET"])
def list_observations():
    auth(ALL_ROLES)
    program_id = request.args.get("program_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    reporter_id = request.args.get("reporter_id")
    linked_hazard_id = request.args.get("linked_hazard_id")
    items = list(db.DB["observations"].values())
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    if kind is not None:
        items = [o for o in items if o["kind"] == kind]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if reporter_id is not None:
        items = [o for o in items if o["reporter_id"] == reporter_id]
    if linked_hazard_id is not None:
        items = [o for o in items if o["linked_hazard_id"] == linked_hazard_id]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.observation_view(o) for o in page], total, limit, offset)


@bp.route("/safety/observations/<oid>", methods=["GET"])
def get_observation(oid):
    auth(ALL_ROLES)
    o = core.get_or_404("observations", oid, "Observation")
    return ok(core.observation_view(o))


@bp.route("/safety/observations/<oid>/triage", methods=["POST"])
def triage_observation(oid):
    user_id, _ = auth(["SafetyManager"])
    o = core.get_or_404("observations", oid, "Observation")
    body = core.body_json()
    action = core.req_enum(body, "action",
                           ("LINK_EXISTING", "CREATE_HAZARD", "NO_ACTION"))
    # Action-specific well-formedness and body-FK existence.
    target = None
    severity = probability = None
    location = description = None
    if action == "LINK_EXISTING":
        hazard_id = core.req_str(body, "hazard_id")
        target = core.get_or_404("hazards", hazard_id, "Hazard")
    elif action == "CREATE_HAZARD":
        severity = core.req_int(body, "severity")
        probability = core.req_int(body, "probability")
        for name, v in (("severity", severity), ("probability", probability)):
            if v < 1 or v > 5:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               f"{name} must be an integer in 1..5")
        location = core.opt_str(body, "location", default=None)
        description = core.opt_str(body, "description", default=None)

    if o["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED observation can be triaged")
    if user_id == o["reporter_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "The triager must differ from the reporter")

    if action == "NO_ACTION":
        o["status"] = "NO_ACTION"
        core.touch(o)
        return ok(core.observation_view(o))

    if action == "LINK_EXISTING":
        if target["status"] == "CLOSED":
            raise ApiError("ERR_HAZARD_NOT_OPEN", 422,
                           "The link target hazard is CLOSED")
        o["linked_hazard_id"] = target["id"]
        o["status"] = "LINKED"
        core.touch(o)
        return ok(core.observation_view(o))

    # CREATE_HAZARD: spin up an ASSESSED hazard and link the observation.
    now = CLOCK.now()
    score, band, sla_due = calc.risk_assessment(severity, probability, now)
    h = core.stamp_new({
        "id": core.new_id(),
        "program_id": o["program_id"],
        "location": location,
        "description": description if description is not None else o["description"],
        "identified_by": o["reporter_id"],
        "severity": severity,
        "probability": probability,
        "risk_score": score,
        "risk_band": band,
        "response_sla_due": sla_due,
        "sla_breached": False,
        "overdue_control_count": 0,
        "status": "ASSESSED",
    })
    db.DB["hazards"][h["id"]] = h
    o["linked_hazard_id"] = h["id"]
    o["status"] = "LINKED"
    core.touch(o)
    return ok(core.observation_view(o))
