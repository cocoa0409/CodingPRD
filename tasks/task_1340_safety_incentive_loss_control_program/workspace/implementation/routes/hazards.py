"""Hazards and their nested control items (PRD 3.3)."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import calc, core, ops

bp = Blueprint("hazards", __name__)


@bp.route("/safety/hazards", methods=["POST"])
def create_hazard():
    auth(["Supervisor", "SafetyManager", "EHSAdmin"])
    body = core.body_json()
    program_id = core.req_str(body, "program_id")
    identified_by = core.req_str(body, "identified_by")
    location = core.req_str(body, "location")
    description = core.req_str(body, "description")
    p = core.get_or_404("programs", program_id, "SafetyProgram")
    core.get_or_404("employees", identified_by, "Employee")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409,
                       "Hazards can be reported only against an ACTIVE program")
    h = core.stamp_new({
        "id": core.new_id(),
        "program_id": p["id"],
        "location": location,
        "description": description,
        "identified_by": identified_by,
        "severity": None,
        "probability": None,
        "risk_score": None,
        "risk_band": None,
        "response_sla_due": None,
        "sla_breached": False,
        "overdue_control_count": 0,
        "status": "OPEN",
    })
    db.DB["hazards"][h["id"]] = h
    return ok(core.hazard_view(h), 201)


@bp.route("/safety/hazards", methods=["GET"])
def list_hazards():
    auth(ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    risk_band = request.args.get("risk_band")
    identified_by = request.args.get("identified_by")
    items = list(db.DB["hazards"].values())
    if program_id is not None:
        items = [h for h in items if h["program_id"] == program_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    if risk_band is not None:
        items = [h for h in items if h["risk_band"] == risk_band]
    if identified_by is not None:
        items = [h for h in items if h["identified_by"] == identified_by]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.hazard_view(h) for h in page], total, limit, offset)


@bp.route("/safety/hazards/<hid>", methods=["GET"])
def get_hazard(hid):
    auth(ALL_ROLES)
    h = core.get_or_404("hazards", hid, "Hazard")
    return ok(core.hazard_view(h))


def _req_1_to_5(body, name):
    v = core.req_int(body, name)
    if v < 1 or v > 5:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{name} must be an integer in 1..5")
    return v


@bp.route("/safety/hazards/<hid>/assess", methods=["POST"])
def assess_hazard(hid):
    auth(["SafetyManager"])
    h = core.get_or_404("hazards", hid, "Hazard")
    body = core.body_json()
    severity = _req_1_to_5(body, "severity")
    probability = _req_1_to_5(body, "probability")
    if h["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN hazard can be assessed")
    score, band, sla_due = calc.risk_assessment(severity, probability, CLOCK.now())
    h["severity"] = severity
    h["probability"] = probability
    h["risk_score"] = score
    h["risk_band"] = band
    h["response_sla_due"] = sla_due
    h["status"] = "ASSESSED"
    core.touch(h)
    return ok(core.hazard_view(h))


@bp.route("/safety/hazards/<hid>/reopen", methods=["POST"])
def reopen_hazard(hid):
    auth(["SafetyManager"])
    h = core.get_or_404("hazards", hid, "Hazard")
    body = core.body_json()
    core.req_str(body, "reason")
    if h["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CLOSED hazard can be reopened")
    p = db.DB["programs"].get(h["program_id"])
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "SafetyProgram not found")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409,
                       "Hazards can reopen only while the program is ACTIVE")
    h["status"] = "OPEN"
    h["sla_breached"] = False
    h["severity"] = None
    h["probability"] = None
    h["risk_score"] = None
    h["risk_band"] = None
    h["response_sla_due"] = None
    core.touch(h)
    # The breach-flag input changed; keep the program counter honest (PRD 2.11).
    new_count = sum(1 for x in db.DB["hazards"].values()
                    if x["program_id"] == p["id"] and x["status"] != "CLOSED"
                    and x["sla_breached"])
    if new_count != p["sla_breach_count"]:
        p["sla_breach_count"] = new_count
        core.touch(p)
    return ok(core.hazard_view(h))


@bp.route("/safety/hazards/<hid>/controls", methods=["POST"])
def create_control(hid):
    auth(["SafetyManager", "EHSAdmin"])
    h = core.get_or_404("hazards", hid, "Hazard")
    body = core.body_json()
    description = core.req_str(body, "description")
    implementer_id = core.req_str(body, "implementer_id")
    due_date = core.req_datetime(body, "due_date")
    core.get_or_404("employees", implementer_id, "Employee")
    if h["status"] not in ("ASSESSED", "CONTROLS_PLANNED", "IN_PROGRESS",
                           "PENDING_VERIFICATION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Controls can be added only to an assessed, open hazard")
    c = core.stamp_new({
        "id": core.new_id(),
        "hazard_id": h["id"],
        "description": description,
        "implementer_id": implementer_id,
        "due_date": due_date,
        "implemented_at": None,
        "verified_by": None,
        "verified_at": None,
        "outcome_note": None,
        "status": "PLANNED",
    })
    db.DB["controls"][c["id"]] = c
    # The first control advances the hazard ASSESSED -> CONTROLS_PLANNED.
    ops.advance_hazard(h)
    return ok(core.control_view(c), 201)


@bp.route("/safety/hazards/<hid>/controls", methods=["GET"])
def list_hazard_controls(hid):
    auth(ALL_ROLES)
    h = core.get_or_404("hazards", hid, "Hazard")
    items = [c for c in db.DB["controls"].values() if c["hazard_id"] == h["id"]]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.control_view(c) for c in page], total, limit, offset)
