"""MeltIntervention endpoints."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, new_id, now_iso, _parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INTERVENTION_WINDOW_CONFLICT,
)
from middleware import require_roles
from response import success_object, success_list
from services.derived import recompute_melt_risk
from services.serializers import serialize_intervention, touch

bp = Blueprint("interventions", __name__, url_prefix="/enrollment/interventions")

BUFFER_MINUTES = 15
BUFFER_TYPES = {"OUTREACH_CALL", "ADVISOR_MEETING"}


@bp.route("", methods=["POST"])
def create_intervention():
    require_roles("EnrollmentManager", "AdmissionsOfficer")
    body = request.get_json(silent=True) or {}
    application_id = body.get("application_id")
    advisor_id = body.get("advisor_id")
    intervention_type = body.get("intervention_type")
    window_start = body.get("window_start_at")
    window_end = body.get("window_end_at")

    if application_id is None or application_id not in store.applications:
        raise ApiError(ERR_NOT_FOUND, 404, "application_id not found")
    for v, n in [(advisor_id, "advisor_id"), (intervention_type, "intervention_type"),
                 (window_start, "window_start_at"), (window_end, "window_end_at")]:
        if v is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} required")
    if intervention_type not in ("OUTREACH_CALL", "ADVISOR_MEETING", "EMAIL_CAMPAIGN"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "intervention_type invalid")
    if advisor_id == "AUTO_QUEUE":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "advisor_id AUTO_QUEUE is reserved for system use")

    ws = _parse_iso(window_start)
    we = _parse_iso(window_end)
    if ws is None or we is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window malformed")
    if we <= ws:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_end_at must be > window_start_at")

    app = store.applications[application_id]
    if app["status"] != "DEPOSITED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Application status {app['status']} does not permit intervention")

    # Buffer rule
    if intervention_type in BUFFER_TYPES:
        for other in store.interventions.values():
            if other["advisor_id"] != advisor_id:
                continue
            if other["status"] != "SCHEDULED":
                continue
            if other["intervention_type"] not in BUFFER_TYPES:
                continue
            os_ = _parse_iso(other["window_start_at"])
            oe = _parse_iso(other["window_end_at"])
            exclusion_end = oe + timedelta(minutes=BUFFER_MINUTES)
            # New window [ws, we) overlaps [os_, exclusion_end)
            if ws < exclusion_end and os_ < we:
                raise ApiError(ERR_INTERVENTION_WINDOW_CONFLICT, 409,
                               "Advisor buffer conflict")

    now = now_iso()
    intervention = {
        "id": new_id(),
        "application_id": application_id,
        "advisor_id": advisor_id,
        "intervention_type": intervention_type,
        "window_start_at": window_start,
        "window_end_at": window_end,
        "trigger_source": "MANUAL",
        "outcome": None,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.interventions[intervention["id"]] = intervention
    return success_object(serialize_intervention(intervention), status=201)


@bp.route("/<interventionId>", methods=["GET"])
def get_intervention(interventionId):
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer")
    i = store.interventions.get(interventionId)
    if not i:
        raise ApiError(ERR_NOT_FOUND, 404, "Intervention not found")
    return success_object(serialize_intervention(i))


@bp.route("", methods=["GET"])
def list_interventions():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer")
    application_id = request.args.get("application_id")
    advisor_id = request.args.get("advisor_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.interventions.values())
    if application_id:
        items = [i for i in items if i["application_id"] == application_id]
    if advisor_id:
        items = [i for i in items if i["advisor_id"] == advisor_id]
    if status:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_intervention(i) for i in page], limit, offset, total)


@bp.route("/<interventionId>/transition", methods=["POST"])
def transition_intervention(interventionId):
    require_roles("EnrollmentManager", "AdmissionsOfficer")
    i = store.interventions.get(interventionId)
    if not i:
        raise ApiError(ERR_NOT_FOUND, 404, "Intervention not found")
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if not to_status:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_status required")

    if i["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Intervention status {i['status']} does not permit transition")
    if to_status == "COMPLETED":
        outcome = body.get("outcome")
        if outcome not in ("REACHED_ENGAGED", "REACHED_CONFIRMED", "NO_CONTACT"):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "outcome required and must be REACHED_ENGAGED | REACHED_CONFIRMED | NO_CONTACT")
        i["outcome"] = outcome
        i["status"] = "COMPLETED"
        touch(i)
        app = store.applications.get(i["application_id"])
        if app:
            recompute_melt_risk(app)
            touch(app)
    elif to_status == "CANCELLED":
        i["status"] = "CANCELLED"
        touch(i)
    else:
        raise ApiError(ERR_INVALID_STATE, 409, f"Invalid to_status {to_status}")
    return success_object(serialize_intervention(i))
