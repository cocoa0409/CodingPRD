"""ResearchRequest routes (PRD §3.6)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_TOO_MANY_ITEMS, ERR_ITEM_NOT_AVAILABLE, ERR_RESEARCHER_SUSPENDED,
    ERR_OWNERSHIP_MISMATCH,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from util import get_json_body, as_str, as_enum, as_str_list, check_no_duplicates, paginate, public_view

bp = Blueprint("requests", __name__)

PURPOSES = {"PERSONAL", "ACADEMIC", "COMMERCIAL", "PUBLICATION"}
MAX_REQUEST_ITEMS = 10


def serialize_request(r: dict) -> dict:
    return public_view(r)


def get_request(rid: str) -> dict:
    r = db.requests.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"ResearchRequest not found: {rid}")
    return r


@bp.route("/research-requests", methods=["POST"])
@require_roles("Researcher")
def create_request(_user_id: str, _role: str):
    body = get_json_body()
    # priority 3: shape — arity 1..10 (11+ -> ERR_TOO_MANY_ITEMS), duplicate-free
    item_ids = as_str_list(body, "item_ids", required=True)
    if len(item_ids) > MAX_REQUEST_ITEMS:
        raise_err(ERR_TOO_MANY_ITEMS, "A research request may reference at most 10 items")
    if len(item_ids) == 0:
        raise_err(ERR_INVALID_REQUEST, "item_ids must contain at least one entry")
    check_no_duplicates(item_ids)
    topic = as_str(body, "topic", required=True)
    purpose = as_enum(body, "purpose", PURPOSES, required=True)

    # priority 4: existence — caller's researcher record, then each item in order
    researcher = db.researchers.get(_user_id)
    if researcher is None:
        raise_err(ERR_NOT_FOUND, f"Researcher not found: {_user_id}")
    for iid in item_ids:
        if iid not in db.items:
            raise_err(ERR_NOT_FOUND, f"Item not found: {iid}")

    # priority 7: researcher ACTIVE, then every item AVAILABLE (first offender
    # in item_ids order is reported)
    if researcher["status"] != "ACTIVE":
        raise_err(ERR_RESEARCHER_SUSPENDED, "The researcher is SUSPENDED")
    for iid in item_ids:
        if db.items[iid]["status"] != "AVAILABLE":
            raise_err(ERR_ITEM_NOT_AVAILABLE, f"Item is not AVAILABLE: {iid}")

    req = {
        **db.make_common_fields(),
        "researcher_id": _user_id,
        "item_ids": list(item_ids),
        "topic": topic,
        "purpose": purpose,
        "status": "SUBMITTED",
        "decision_reason": None,
    }
    db.requests[req["id"]] = req
    return success_object(serialize_request(req), 201)


@bp.route("/research-requests", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_requests(_user_id: str, _role: str):
    researcher_id = request.args.get("researcher_id")
    status = request.args.get("status")
    rows = list(db.requests.values())
    if researcher_id is not None:
        rows = [r for r in rows if r["researcher_id"] == researcher_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_request(r) for r in page], limit, offset, total)


@bp.route("/research-requests/<rid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_one_request(rid: str, _user_id: str, _role: str):
    return success_object(serialize_request(get_request(rid)))


@bp.route("/research-requests/<rid>/begin-review", methods=["POST"])
@require_roles("ReadingRoomStaff")
def begin_review(rid: str, _user_id: str, _role: str):
    r = get_request(rid)
    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED request may begin review")
    r["status"] = "IN_REVIEW"
    db.touch(r)
    return success_object(serialize_request(r))


@bp.route("/research-requests/<rid>/approve", methods=["POST"])
@require_roles("ReadingRoomStaff")
def approve_request(rid: str, _user_id: str, _role: str):
    r = get_request(rid)
    if r["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an IN_REVIEW request may be approved")
    r["status"] = "APPROVED"
    db.touch(r)
    return success_object(serialize_request(r))


@bp.route("/research-requests/<rid>/deny", methods=["POST"])
@require_roles("ReadingRoomStaff")
def deny_request(rid: str, _user_id: str, _role: str):
    body = get_json_body()
    decision_reason = as_str(body, "decision_reason", required=False, default=None)
    r = get_request(rid)
    if r["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an IN_REVIEW request may be denied")
    r["status"] = "DENIED"
    r["decision_reason"] = decision_reason
    db.touch(r)
    return success_object(serialize_request(r))


@bp.route("/research-requests/<rid>/cancel", methods=["POST"])
@require_roles("Researcher")
def cancel_request(rid: str, _user_id: str, _role: str):
    r = get_request(rid)
    if r["status"] not in ("SUBMITTED", "IN_REVIEW"):
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED or IN_REVIEW request may be cancelled")
    if r["researcher_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the owning researcher may cancel the request")
    r["status"] = "CANCELLED"
    db.touch(r)
    return success_object(serialize_request(r))
