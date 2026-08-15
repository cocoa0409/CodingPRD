"""Interpreter endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("interpreters", __name__)

INTERP_READERS = {"SchoolAdmin", "FrontOfficeStaff", "Interpreter"}


@bp.route("/conf/interpreters", methods=["POST"])
def create_interpreter():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    util.require_fields(body, ["full_name", "languages", "max_consecutive_minutes",
                               "base_minutes_per_window", "hourly_rate_cents"])
    full_name = util.require_string(body, "full_name")
    languages = util.require_string_list(body, "languages", allow_empty=False)
    max_consecutive = util.require_int(body, "max_consecutive_minutes", min_value=1)
    base_minutes = util.require_int(body, "base_minutes_per_window", min_value=1)
    hourly_rate = util.require_int(body, "hourly_rate_cents", min_value=0)
    supports_in_person = util.optional_bool(body, "supports_in_person", default=True)
    supports_virtual = util.optional_bool(body, "supports_virtual", default=True)

    now = util.now_iso()
    interp = {
        "id": util.new_id(),
        "full_name": full_name,
        "languages": languages,
        "supports_in_person": supports_in_person,
        "supports_virtual": supports_virtual,
        "max_consecutive_minutes": max_consecutive,
        "base_minutes_per_window": base_minutes,
        "hourly_rate_cents": hourly_rate,
        "status": "ACTIVE",
        "created_seq": db.next_seq(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.interpreters[interp["id"]] = interp
    return response.success_object(serializers.interpreter_view(interp), status=201)


@bp.route("/conf/interpreters", methods=["GET"])
def list_interpreters():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, INTERP_READERS)
    limit, offset = util.parse_pagination(request.args)
    status = request.args.get("status")
    language = request.args.get("language")
    items = list(db.interpreters.values())
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if language is not None:
        items = [i for i in items if language in i["languages"]]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.interpreter_view(i) for i in page],
                                 total, limit, offset)


@bp.route("/conf/interpreters/<iid>", methods=["GET"])
def get_interpreter(iid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, INTERP_READERS)
    interp = core.get_interpreter_or_404(iid)
    middleware.check_interpreter_owns(role, uid, interp["id"])
    return response.success_object(serializers.interpreter_view(interp))


@bp.route("/conf/interpreters/<iid>", methods=["PATCH"])
def update_interpreter(iid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    interp = core.get_interpreter_or_404(iid)

    if "full_name" in body and body["full_name"] is not None:
        if not isinstance(body["full_name"], str) or body["full_name"] == "":
            raise errors.validation("full_name must be a non-empty string")
    if "languages" in body and body["languages"] is not None:
        util.require_string_list(body, "languages", allow_empty=False)
    for f, minv in (("max_consecutive_minutes", 1), ("base_minutes_per_window", 1),
                    ("hourly_rate_cents", 0)):
        if f in body and body[f] is not None:
            util.require_int(body, f, min_value=minv)
    for f in ("supports_in_person", "supports_virtual"):
        if f in body and body[f] is not None and not isinstance(body[f], bool):
            raise errors.validation(f"{f} must be a boolean")
    if "status" in body and body["status"] is not None:
        util.require_enum(body, "status", {"ACTIVE", "INACTIVE"})

    if "full_name" in body and body["full_name"] is not None:
        interp["full_name"] = body["full_name"]
    if "languages" in body and body["languages"] is not None:
        interp["languages"] = body["languages"]
    for f in ("max_consecutive_minutes", "base_minutes_per_window", "hourly_rate_cents"):
        if f in body and body[f] is not None:
            interp[f] = body[f]
    for f in ("supports_in_person", "supports_virtual"):
        if f in body and body[f] is not None:
            interp[f] = body[f]

    new_status = body.get("status")
    if new_status is not None and new_status != interp["status"]:
        if new_status == "INACTIVE":
            interp["status"] = "INACTIVE"
            interp["version"] += 1
            interp["updated_at"] = util.now_iso()
            core.interpreter_deactivation_cascade(interp)
            return response.success_object(serializers.interpreter_view(interp))
        else:
            interp["status"] = "ACTIVE"

    interp["version"] += 1
    interp["updated_at"] = util.now_iso()
    return response.success_object(serializers.interpreter_view(interp))


@bp.route("/conf/interpreters/<iid>/summary", methods=["GET"])
def interpreter_summary(iid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, INTERP_READERS)
    interp = core.get_interpreter_or_404(iid)
    middleware.check_interpreter_owns(role, uid, interp["id"])
    window_id = request.args.get("window_id")
    if not window_id:
        raise errors.validation("window_id query parameter is required")
    core.get_window_or_404(window_id)

    committed, allowance, capacity, headroom = core.interpreter_capacity(iid, window_id)
    confirmed_count = sum(1 for r in db.interpreter_requests.values()
                          if r["interpreter_id"] == iid
                          and r["window_id"] == window_id
                          and r["status"] == "CONFIRMED")
    summary = {
        "interpreter_id": iid,
        "window_id": window_id,
        "committed_minutes_in_window": committed,
        "break_allowance_minutes": allowance,
        "capacity_minutes": capacity,
        "headroom_minutes": headroom,
        "confirmed_assignments": confirmed_count,
        "pay_estimate_cents": core.interpreter_pay_estimate(iid, window_id),
    }
    return response.success_object(summary)
