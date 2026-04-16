from flask import Blueprint, request
from db import (
    adoption_applications,
    adopters,
    home_visits,
    animals,
    gen_id,
    now_iso,
    utc_now,
    parse_iso,
)
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATES,
    ERR_HOME_VISIT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ASSESSOR_MISMATCH,
)
from middleware import require_roles, parse_pagination, get_auth
from response import success_response, list_response
from services.animal_service import (
    serialize_home_visit,
    compute_home_visit_score_and_result,
)

home_visits_bp = Blueprint("home_visits", __name__)


@home_visits_bp.route("/petcare/home-visits", methods=["POST"])
def create_home_visit():
    user_id, _ = require_roles("CaseWorker")
    body = request.get_json(silent=True) or {}

    application_id = body.get("application_id")
    scheduled_date = body.get("scheduled_date")

    if not application_id or not isinstance(application_id, str):
        raise_error(ERR_INVALID_REQUEST, "application_id is required")
    if not scheduled_date:
        raise_error(ERR_INVALID_REQUEST, "scheduled_date is required")

    app = adoption_applications.get(application_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "HOME_VISIT_REQUIRED":
        raise_error(ERR_INVALID_STATE, "Application must be HOME_VISIT_REQUIRED")

    scheduled_dt = parse_iso(scheduled_date)
    if scheduled_dt is None:
        raise_error(ERR_INVALID_DATES, "Invalid scheduled_date")
    if scheduled_dt <= utc_now():
        raise_error(ERR_INVALID_DATES, "scheduled_date must be in the future")

    hv_id = gen_id()
    ts = now_iso()
    hv = {
        "id": hv_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "application_id": application_id,
        "adopter_id": app["adopter_id"],
        "case_worker_id": user_id,
        "scheduled_date": scheduled_date,
        "yard_adequate": None,
        "space_adequate": None,
        "safety_hazards_found": None,
        "existing_pets_compatible": None,
        "notes": None,
        "overall_score": None,
        "result": None,
        "status": "SCHEDULED",
    }
    home_visits[hv_id] = hv

    # Application transitions HOME_VISIT_REQUIRED -> HOME_VISIT_SCHEDULED
    app["status"] = "HOME_VISIT_SCHEDULED"
    app["home_visit_id"] = hv_id
    app["updated_at"] = now_iso()
    app["version"] += 1

    return success_response(serialize_home_visit(hv), status_code=201)


@home_visits_bp.route("/petcare/home-visits", methods=["GET"])
def list_home_visits():
    require_roles("ShelterManager", "CaseWorker")
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    adopter_id = request.args.get("adopter_id")
    status = request.args.get("status")
    items = []
    for hv in home_visits.values():
        if application_id and hv["application_id"] != application_id:
            continue
        if adopter_id and hv.get("adopter_id") != adopter_id:
            continue
        if status and hv["status"] != status:
            continue
        items.append(hv)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_home_visit(x) for x in page], total, limit, offset)


@home_visits_bp.route("/petcare/home-visits/<hv_id>", methods=["GET"])
def get_home_visit(hv_id):
    require_roles("ShelterManager", "CaseWorker")
    hv = home_visits.get(hv_id)
    if not hv:
        raise_error(ERR_HOME_VISIT_NOT_FOUND, "Home visit not found")
    return success_response(serialize_home_visit(hv))


@home_visits_bp.route("/petcare/home-visits/<hv_id>/complete", methods=["POST"])
def complete_home_visit(hv_id):
    user_id, _ = require_roles("CaseWorker")
    hv = home_visits.get(hv_id)
    if not hv:
        raise_error(ERR_HOME_VISIT_NOT_FOUND, "Home visit not found")
    if hv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Home visit must be SCHEDULED")
    if hv.get("case_worker_id") != user_id:
        raise_error(ERR_ASSESSOR_MISMATCH, "Only the assigned case worker may complete")
    body = request.get_json(silent=True) or {}

    required_keys = ("yard_adequate", "space_adequate", "safety_hazards_found",
                     "existing_pets_compatible", "notes")
    for key in required_keys:
        if key not in body:
            raise_error(ERR_INVALID_REQUEST, f"{key} is required")

    yard = body["yard_adequate"]
    space = body["space_adequate"]
    hazards = body["safety_hazards_found"]
    compat = body["existing_pets_compatible"]
    notes = body["notes"]

    for val, name in ((yard, "yard_adequate"), (space, "space_adequate"),
                       (hazards, "safety_hazards_found"), (compat, "existing_pets_compatible")):
        if not isinstance(val, bool):
            raise_error(ERR_INVALID_REQUEST, f"{name} must be a boolean")
    if not isinstance(notes, str):
        raise_error(ERR_INVALID_REQUEST, "notes must be a string")

    app = adoption_applications.get(hv["application_id"])
    animal = animals.get(app["animal_id"]) if app else None

    score, result = compute_home_visit_score_and_result(animal, yard, space, hazards, compat)

    hv["yard_adequate"] = yard
    hv["space_adequate"] = space
    hv["safety_hazards_found"] = hazards
    hv["existing_pets_compatible"] = compat
    hv["notes"] = notes
    hv["overall_score"] = score
    hv["result"] = result
    hv["status"] = "COMPLETED"
    hv["updated_at"] = now_iso()
    hv["version"] += 1

    # Application transitions
    if app and app["status"] == "HOME_VISIT_SCHEDULED":
        if result in ("PASS", "CONDITIONAL_PASS"):
            app["status"] = "REVIEWED"
        else:
            app["status"] = "REJECTED"
            app["rejection_reason"] = "Home visit failed"
        app["updated_at"] = now_iso()
        app["version"] += 1

    return success_response(serialize_home_visit(hv))


@home_visits_bp.route("/petcare/home-visits/<hv_id>/cancel", methods=["POST"])
def cancel_home_visit(hv_id):
    require_roles("CaseWorker")
    hv = home_visits.get(hv_id)
    if not hv:
        raise_error(ERR_HOME_VISIT_NOT_FOUND, "Home visit not found")
    if hv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Home visit must be SCHEDULED")
    hv["status"] = "CANCELLED"
    hv["updated_at"] = now_iso()
    hv["version"] += 1

    app = adoption_applications.get(hv["application_id"])
    if app and app["status"] == "HOME_VISIT_SCHEDULED":
        app["status"] = "HOME_VISIT_REQUIRED"
        app["home_visit_id"] = None
        app["updated_at"] = now_iso()
        app["version"] += 1

    return success_response(serialize_home_visit(hv))


@home_visits_bp.route("/petcare/home-visits/expire-due", methods=["POST"])
def expire_due():
    require_roles("ShelterManager")
    now = utc_now()
    expired_ids = []
    for hv in list(home_visits.values()):
        if hv["status"] != "SCHEDULED":
            continue
        sched = parse_iso(hv["scheduled_date"])
        if sched is None or sched >= now:
            continue
        hv["status"] = "EXPIRED"
        hv["updated_at"] = now_iso()
        hv["version"] += 1
        expired_ids.append(hv["id"])
        app = adoption_applications.get(hv["application_id"])
        if app and app["status"] == "HOME_VISIT_SCHEDULED":
            app["status"] = "HOME_VISIT_REQUIRED"
            app["home_visit_id"] = None
            app["updated_at"] = now_iso()
            app["version"] += 1

    return success_response({"expired_count": len(expired_ids), "expired_ids": expired_ids})
