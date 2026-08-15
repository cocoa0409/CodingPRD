"""Handoff endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
    ERR_HANDOFF_INVALID_STATE, ERR_STALE_VERSION, ERR_HANDOFF_INCOMPLETE,
    ERR_HANDOFF_SELF_ACCEPT,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import make_entity, touch, compute_handoff_counts
from services import serializers
import clock

bp = Blueprint("handoffs", __name__)

ALL_ROLES = ["GroupAdmin", "Hospitalist", "ConsultingSpecialist"]


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


@bp.route("/shifts/<shift_id>/handoffs", methods=["POST"])
def create_handoff(shift_id):
    role, uid = require_roles(["Hospitalist"])
    body = _body()

    shift = store["shifts"].get(shift_id)
    if shift is None:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)

    # ownership: author must be the shift's owner
    if shift["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the shift owner may author a handoff", 403)

    receiving = body.get("receiving_hospitalist_id")
    patient_ids = body.get("patient_ids")
    if not receiving or not isinstance(receiving, str):
        raise ApiError(ERR_INVALID_REQUEST, "receiving_hospitalist_id is required", 400)
    if not isinstance(patient_ids, list) or not all(isinstance(x, str) for x in patient_ids):
        raise ApiError(ERR_INVALID_REQUEST, "patient_ids must be an array of ids", 400)

    rh = store["hospitalists"].get(receiving)
    if rh is None:
        raise ApiError(ERR_NOT_FOUND, "Receiving hospitalist not found", 404)

    h = make_entity({
        "shift_id": shift_id,
        "receiving_hospitalist_id": receiving,
        "patient_ids": list(patient_ids),
        "status": "DRAFT",
        "required_patient_count": 0,
        "covered_patient_count": 0,
        "open_item_count": 0,
        "completeness_score": None,
        "submitted_at": None,
        "reviewed_at": None,
        "return_reason": None,
    })
    compute_handoff_counts(h)
    store["handoffs"][h["id"]] = h
    return success_object(serializers.handoff(h), 201)


@bp.route("/handoffs", methods=["GET"])
def list_handoffs():
    require_roles(ALL_ROLES)
    items = list(store["handoffs"].values())
    sid = request.args.get("shift_id")
    if sid is not None:
        items = [h for h in items if h["shift_id"] == sid]
    rid = request.args.get("receiving_hospitalist_id")
    if rid is not None:
        items = [h for h in items if h["receiving_hospitalist_id"] == rid]
    st = request.args.get("status")
    if st is not None:
        items = [h for h in items if h["status"] == st]
    return _paginate(items, serializers.handoff)


@bp.route("/handoffs/<hid>", methods=["GET"])
def get_handoff(hid):
    require_roles(ALL_ROLES)
    h = store["handoffs"].get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Handoff not found", 404)
    return success_object(serializers.handoff(h))


@bp.route("/handoffs/<hid>", methods=["PUT"])
def revise_handoff(hid):
    role, uid = require_roles(["Hospitalist"])
    body = _body()

    if "expected_handoff_version" not in body:
        raise ApiError(ERR_INVALID_REQUEST, "expected_handoff_version is required", 400)
    expected = body.get("expected_handoff_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_handoff_version must be an integer", 400)

    h = store["handoffs"].get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Handoff not found", 404)

    shift = store["shifts"].get(h["shift_id"])
    if shift is None or shift["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the shift owner may revise the handoff", 403)

    if h["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_HANDOFF_INVALID_STATE, "revision requires status DRAFT or RETURNED", 409)

    if expected != h["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_handoff_version does not match current version", 412)

    if "patient_ids" in body:
        patient_ids = body["patient_ids"]
        if not isinstance(patient_ids, list) or not all(isinstance(x, str) for x in patient_ids):
            raise ApiError(ERR_INVALID_REQUEST, "patient_ids must be an array of ids", 400)
        h["patient_ids"] = list(patient_ids)
    if "receiving_hospitalist_id" in body:
        receiving = body["receiving_hospitalist_id"]
        if not isinstance(receiving, str):
            raise ApiError(ERR_INVALID_REQUEST, "receiving_hospitalist_id must be an id", 400)
        rh = store["hospitalists"].get(receiving)
        if rh is None:
            raise ApiError(ERR_NOT_FOUND, "Receiving hospitalist not found", 404)
        h["receiving_hospitalist_id"] = receiving

    compute_handoff_counts(h)
    touch(h)
    return success_object(serializers.handoff(h))


@bp.route("/handoffs/<hid>/submit", methods=["POST"])
def submit_handoff(hid):
    role, uid = require_roles(["Hospitalist"])
    h = store["handoffs"].get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Handoff not found", 404)
    shift = store["shifts"].get(h["shift_id"])
    if shift is None or shift["hospitalist_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the shift owner may submit the handoff", 403)
    if h["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_HANDOFF_INVALID_STATE, "submit requires status DRAFT or RETURNED", 409)

    compute_handoff_counts(h)
    if h["open_item_count"] != 0:
        raise ApiError(ERR_HANDOFF_INCOMPLETE, "patient_ids do not cover every ACTIVE assignment", 422)

    h["status"] = "SUBMITTED"
    h["submitted_at"] = clock.now()
    touch(h)
    return success_object(serializers.handoff(h))


@bp.route("/handoffs/<hid>/accept", methods=["POST"])
def accept_handoff(hid):
    role, uid = require_roles(["Hospitalist"])
    h = store["handoffs"].get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Handoff not found", 404)
    if uid != h["receiving_hospitalist_id"]:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the receiving hospitalist may accept", 403)
    if h["status"] != "SUBMITTED":
        raise ApiError(ERR_HANDOFF_INVALID_STATE, "accept requires status SUBMITTED", 409)
    shift = store["shifts"].get(h["shift_id"])
    if shift is not None and uid == shift["hospitalist_id"]:
        raise ApiError(ERR_HANDOFF_SELF_ACCEPT, "shift owner may not accept own signout", 409)
    h["status"] = "ACCEPTED"
    h["reviewed_at"] = clock.now()
    touch(h)
    return success_object(serializers.handoff(h))


@bp.route("/handoffs/<hid>/return", methods=["POST"])
def return_handoff(hid):
    role, uid = require_roles(["Hospitalist"])
    body = _body()
    return_reason = body.get("return_reason")
    if not return_reason or not isinstance(return_reason, str):
        raise ApiError(ERR_INVALID_REQUEST, "return_reason is required", 400)

    h = store["handoffs"].get(hid)
    if h is None:
        raise ApiError(ERR_NOT_FOUND, "Handoff not found", 404)
    if uid != h["receiving_hospitalist_id"]:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, "only the receiving hospitalist may return", 403)
    if h["status"] != "SUBMITTED":
        raise ApiError(ERR_HANDOFF_INVALID_STATE, "return requires status SUBMITTED", 409)
    h["status"] = "RETURNED"
    h["return_reason"] = return_reason
    touch(h)
    return success_object(serializers.handoff(h))
