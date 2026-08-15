"""Consult request endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
    ERR_CONSULT_INVALID_STATE, ERR_CONSULT_REOPEN_WINDOW_EXPIRED,
    ERR_PATIENT_NOT_ADMITTED,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import make_entity, touch, round2, SLA_MINUTES, REOPEN_WINDOW_HOURS
from services import serializers
import clock

bp = Blueprint("consults", __name__)

ALL_ROLES = ["GroupAdmin", "Hospitalist", "ConsultingSpecialist"]
SPECIALTIES = {"CARDIOLOGY", "NEUROLOGY", "SURGERY", "INFECTIOUS_DISEASE", "NEPHROLOGY"}
PRIORITIES = {"STAT", "URGENT", "ROUTINE"}
ACK_STATES = {"OPEN", "ESCALATED", "REOPENED"}


def _paginate(items, serializer):
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameters", 400)
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(i) for i in page], limit, offset, total)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be an object", 400)
    return data


@bp.route("/patients/<patient_id>/consult-requests", methods=["POST"])
def create_consult(patient_id):
    role, uid = require_roles(["Hospitalist"])
    body = _body()
    specialty = body.get("specialty")
    priority = body.get("priority")
    reason = body.get("reason")
    if specialty not in SPECIALTIES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid specialty", 400)
    if priority not in PRIORITIES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid priority", 400)
    if not reason or not isinstance(reason, str):
        raise ApiError(ERR_INVALID_REQUEST, "reason is required", 400)

    patient = store["patients"].get(patient_id)
    if patient is None:
        raise ApiError(ERR_NOT_FOUND, "Patient not found", 404)

    # ownership: caller must hold the patient's ACTIVE assignment
    has_active = any(
        a["patient_id"] == patient_id and a["hospitalist_id"] == uid and a["status"] == "ACTIVE"
        for a in store["assignments"].values()
    )
    if not has_active:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "caller does not hold the patient's ACTIVE assignment", 403)

    if patient["admission_status"] != "ADMITTED":
        raise ApiError(ERR_PATIENT_NOT_ADMITTED, "patient is not ADMITTED", 409)

    now = clock.now()
    sla = now + timedelta(minutes=SLA_MINUTES[priority])
    c = make_entity({
        "patient_id": patient_id,
        "requesting_hospitalist_id": uid,
        "specialty": specialty,
        "priority": priority,
        "reason": reason,
        "status": "OPEN",
        "requested_at": now,
        "sla_deadline": sla,
        "sla_breached": False,
        "acknowledged_at": None,
        "completed_at": None,
        "escalation_count": 0,
        "response_minutes": None,
    })
    store["consult_requests"][c["id"]] = c
    return success_object(serializers.consult_request(c), 201)


@bp.route("/consult-requests", methods=["GET"])
def list_consults():
    require_roles(ALL_ROLES)
    items = list(store["consult_requests"].values())
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [c for c in items if c["patient_id"] == pid]
    rid = request.args.get("requesting_hospitalist_id")
    if rid is not None:
        items = [c for c in items if c["requesting_hospitalist_id"] == rid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    pr = request.args.get("priority")
    if pr is not None:
        items = [c for c in items if c["priority"] == pr]
    return _paginate(items, serializers.consult_request)


@bp.route("/consult-requests/<cid>", methods=["GET"])
def get_consult(cid):
    require_roles(ALL_ROLES)
    c = store["consult_requests"].get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ConsultRequest not found", 404)
    return success_object(serializers.consult_request(c))


@bp.route("/consult-requests/<cid>/acknowledge", methods=["POST"])
def acknowledge_consult(cid):
    require_roles(["ConsultingSpecialist"])
    c = store["consult_requests"].get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ConsultRequest not found", 404)
    if c["status"] not in ACK_STATES:
        raise ApiError(ERR_CONSULT_INVALID_STATE, "acknowledge requires OPEN, ESCALATED, or REOPENED", 409)
    now = clock.now()
    c["status"] = "ACKNOWLEDGED"
    c["acknowledged_at"] = now
    c["sla_breached"] = now > c["sla_deadline"]
    touch(c)
    return success_object(serializers.consult_request(c))


@bp.route("/consult-requests/<cid>/complete", methods=["POST"])
def complete_consult(cid):
    require_roles(["ConsultingSpecialist"])
    _body()  # optional summary; no validation needed
    c = store["consult_requests"].get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ConsultRequest not found", 404)
    if c["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_CONSULT_INVALID_STATE, "complete requires ACKNOWLEDGED", 409)
    now = clock.now()
    c["status"] = "COMPLETED"
    c["completed_at"] = now
    elapsed_seconds = Decimal(str((now - c["requested_at"]).total_seconds()))
    c["response_minutes"] = round2(elapsed_seconds / Decimal("60"))
    touch(c)
    return success_object(serializers.consult_request(c))


@bp.route("/consult-requests/<cid>/reopen", methods=["POST"])
def reopen_consult(cid):
    role, uid = require_roles(["Hospitalist"])
    _body()  # optional reason
    c = store["consult_requests"].get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ConsultRequest not found", 404)
    if c["requesting_hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the requesting hospitalist may reopen", 403)
    if c["status"] != "COMPLETED":
        raise ApiError(ERR_CONSULT_INVALID_STATE, "reopen requires COMPLETED", 409)
    now = clock.now()
    if now > c["completed_at"] + timedelta(hours=REOPEN_WINDOW_HOURS):
        raise ApiError(ERR_CONSULT_REOPEN_WINDOW_EXPIRED, "reopen window has expired", 422)
    c["status"] = "REOPENED"
    touch(c)
    return success_object(serializers.consult_request(c))
