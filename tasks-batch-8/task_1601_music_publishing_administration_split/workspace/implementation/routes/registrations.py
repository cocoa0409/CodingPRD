from flask import Blueprint, request

import db
from db import STORE
from errors import (
    ApiError,
    ERR_DUPLICATE_SOCIETY_REGISTRATION,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_CONFIRMED_SPLIT_SET,
    ERR_VALIDATION,
    ERR_WORK_RIGHTS_TERMINATED,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import registration_view
from services import confirmed_split_set, get_or_404, new_record, sorted_all, touch
from validators import body_json, opt_str, paginate, pagination_params, req_str

bp = Blueprint("registrations", __name__)

ACTIVE_REG_STATUSES = ("DRAFT", "SUBMITTED", "ACKNOWLEDGED", "REGISTERED")


@bp.route("/society-registrations", methods=["POST"], strict_slashes=False)
def create_registration():
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    body = body_json()
    work_id = body.get("work_id")
    if not isinstance(work_id, str) or not work_id:
        raise ApiError(ERR_VALIDATION, 422, "work_id is required")
    work = get_or_404("works", work_id, "work")
    society_id = body.get("society_id")
    if not isinstance(society_id, str) or not society_id:
        raise ApiError(ERR_VALIDATION, 422, "society_id is required")
    get_or_404("societies", society_id, "society")
    for existing in STORE["society_registrations"].values():
        if (existing["work_id"] == work_id
                and existing["society_id"] == society_id
                and existing["status"] in ACTIVE_REG_STATUSES):
            raise ApiError(
                ERR_DUPLICATE_SOCIETY_REGISTRATION, 409,
                "a registration for this (work_id, society_id) already exists")
    r = new_record()
    r.update({
        "work_id": work_id,
        "society_id": society_id,
        "status": "DRAFT",
        "society_work_number": None,
        "rejection_reason": None,
        "submitted_at": None,
        "registered_at": None,
    })
    STORE["society_registrations"][r["id"]] = r
    return success(registration_view(r), status=201)


@bp.route("/society-registrations", methods=["GET"], strict_slashes=False)
def list_registrations():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("society_registrations")
    work_id = request.args.get("work_id")
    society_id = request.args.get("society_id")
    status = request.args.get("status")
    if work_id is not None:
        items = [r for r in items if r["work_id"] == work_id]
    if society_id is not None:
        items = [r for r in items if r["society_id"] == society_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success([registration_view(r) for r in page],
                   response_type="array", pagination=meta)


@bp.route("/society-registrations/<rid>", methods=["GET"], strict_slashes=False)
def get_registration(rid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    r = get_or_404("society_registrations", rid, "society registration")
    return success(registration_view(r))


@bp.route("/society-registrations/<rid>/submit", methods=["POST"], strict_slashes=False)
def submit_registration(rid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    r = get_or_404("society_registrations", rid, "society registration")
    if r["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "submit requires status DRAFT or REJECTED")
    work = STORE["works"][r["work_id"]]
    if work["copyright_status"] == "TERMINATED":
        raise ApiError(ERR_WORK_RIGHTS_TERMINATED, 409,
                       "the work's copyright is TERMINATED")
    if confirmed_split_set(work["id"]) is None:
        raise ApiError(ERR_NO_CONFIRMED_SPLIT_SET, 409,
                       "the work has no CONFIRMED split set")
    r["status"] = "SUBMITTED"
    r["rejection_reason"] = None
    r["submitted_at"] = db.clock_now()
    touch(r)
    if work["registration_status"] == "UNREGISTERED":
        work["registration_status"] = "PENDING_SOCIETY"
        touch(work)
    return success(registration_view(r))


@bp.route("/society-registrations/<rid>/acknowledge", methods=["POST"], strict_slashes=False)
def acknowledge_registration(rid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    r = get_or_404("society_registrations", rid, "society registration")
    body = body_json()
    number = req_str(body, "society_work_number")
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "acknowledge requires status SUBMITTED")
    r["status"] = "ACKNOWLEDGED"
    r["society_work_number"] = number
    touch(r)
    return success(registration_view(r))


@bp.route("/society-registrations/<rid>/register", methods=["POST"], strict_slashes=False)
def register_registration(rid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    r = get_or_404("society_registrations", rid, "society registration")
    body = body_json()
    iswc = opt_str(body, "iswc")
    if r["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "register requires status ACKNOWLEDGED")
    r["status"] = "REGISTERED"
    r["registered_at"] = db.clock_now()
    touch(r)
    work = STORE["works"][r["work_id"]]
    work["registration_status"] = "REGISTERED"
    society = STORE["societies"][r["society_id"]]
    if society["society_type"] == "PRO" and work["iswc"] is None and iswc is not None:
        work["iswc"] = iswc
    touch(work)
    return success(registration_view(r))


@bp.route("/society-registrations/<rid>/reject", methods=["POST"], strict_slashes=False)
def reject_registration(rid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    r = get_or_404("society_registrations", rid, "society registration")
    body = body_json()
    reason = req_str(body, "reason")
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "reject requires status SUBMITTED")
    r["status"] = "REJECTED"
    r["rejection_reason"] = reason
    touch(r)
    work = STORE["works"][r["work_id"]]
    any_other_active = any(
        other["id"] != r["id"]
        and other["work_id"] == work["id"]
        and other["status"] in ACTIVE_REG_STATUSES
        for other in STORE["society_registrations"].values()
    )
    if not any_other_active and work["registration_status"] != "UNREGISTERED":
        work["registration_status"] = "UNREGISTERED"
        touch(work)
    return success(registration_view(r))
