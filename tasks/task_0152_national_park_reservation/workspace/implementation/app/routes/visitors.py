"""Visitor and pass routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_PARK_ADMIN,
    ROLE_SYSTEM_OPERATOR,
    ROLE_VISITOR,
    require_auth,
)
from ..envelope import parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import (
    serialize_ledger_entry,
    serialize_pass,
    serialize_visitor,
)
from ..services.common import stamp_create, stamp_update
from ..store import get_store
from ..util import new_id, new_pass_serial, parse_iso8601
from ..validators import get_json_body, require_string, validate_email
from ._helpers import filter_visitor_owned, lookup_visitor, require_visitor_ownership

bp = Blueprint("visitors", __name__)


_VALID_PASS_TYPES = {
    "ANNUAL",
    "SENIOR_ANNUAL",
    "SENIOR_LIFETIME",
    "MILITARY",
    "ACCESS",
    "VOLUNTEER",
    "FOURTH_GRADE",
}


@bp.post("/visitors")
@require_auth([ROLE_SYSTEM_OPERATOR])
def create_visitor():
    body = get_json_body()
    email = validate_email(require_string(body, "email", min_len=3, max_len=320))
    full_name = require_string(body, "full_name", min_len=1, max_len=120)
    store = get_store()
    with store.lock:
        if email.lower() in store.visitor_emails:
            raise APIError("ERR_VALIDATION", "email not unique", 422)
        visitor = {
            "id": new_id(),
            "email": email,
            "full_name": full_name,
            "wallet_balance_cents": 0,
            "lottery_strikes": 0,
        }
        stamp_create(visitor)
        store.visitors[visitor["id"]] = visitor
        store.visitor_emails[email.lower()] = visitor["id"]
    return jsonify(success_object(serialize_visitor(visitor))), 201


@bp.get("/visitors/<visitor_id>")
@require_auth([ROLE_SYSTEM_OPERATOR, ROLE_VISITOR])
def get_visitor(visitor_id: str):
    require_visitor_ownership(visitor_id)
    v = lookup_visitor(visitor_id)
    return jsonify(success_object(serialize_visitor(v))), 200


@bp.get("/visitors/<visitor_id>/ledger")
@require_auth([ROLE_SYSTEM_OPERATOR, ROLE_VISITOR])
def list_ledger(visitor_id: str):
    require_visitor_ownership(visitor_id)
    lookup_visitor(visitor_id)
    limit, offset = parse_pagination()
    store = get_store()
    entries = [e for e in store.ledger_entries.values() if e["visitor_id"] == visitor_id]
    entries.sort(key=lambda e: e["created_at"])
    total = len(entries)
    page = [serialize_ledger_entry(e) for e in entries[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


@bp.post("/visitors/<visitor_id>/passes")
@require_auth([ROLE_PARK_ADMIN])
def create_pass(visitor_id: str):
    visitor = lookup_visitor(visitor_id)
    body = get_json_body()
    pass_type = require_string(body, "pass_type", min_len=1)
    if pass_type not in _VALID_PASS_TYPES:
        raise APIError("ERR_VALIDATION", f"Unknown pass_type: {pass_type}", 422)
    valid_from = require_string(body, "valid_from", min_len=1)
    valid_until = require_string(body, "valid_until", min_len=1)
    vf = parse_iso8601(valid_from)
    vu = parse_iso8601(valid_until)
    if vf is None or vu is None:
        raise APIError("ERR_VALIDATION", "valid_from / valid_until must be ISO 8601", 422)
    if vu <= vf:
        raise APIError("ERR_VALIDATION", "valid_until must be after valid_from", 422)
    store = get_store()
    with store.lock:
        serial = new_pass_serial()
        while serial in store.pass_serials:
            serial = new_pass_serial()
        p = {
            "id": new_id(),
            "visitor_id": visitor_id,
            "pass_type": pass_type,
            "serial": serial,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": "ACTIVE",
        }
        stamp_create(p)
        store.passes[p["id"]] = p
        store.pass_serials[serial] = p["id"]
    return jsonify(success_object(serialize_pass(p))), 201


@bp.get("/visitors/<visitor_id>/passes")
@require_auth([ROLE_SYSTEM_OPERATOR, ROLE_VISITOR, ROLE_PARK_ADMIN])
def list_passes(visitor_id: str):
    require_visitor_ownership(visitor_id)
    lookup_visitor(visitor_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [p for p in store.passes.values() if p["visitor_id"] == visitor_id]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = [serialize_pass(p) for p in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


@bp.post("/visitors/<visitor_id>/passes/<pass_id>/revoke")
@require_auth([ROLE_PARK_ADMIN])
def revoke_pass(visitor_id: str, pass_id: str):
    lookup_visitor(visitor_id)
    store = get_store()
    p = store.passes.get(pass_id)
    if p is None or p["visitor_id"] != visitor_id:
        raise APIError("ERR_NOT_FOUND", "Pass not found", 404)
    if p["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", "Pass is not ACTIVE", 409)
    with store.lock:
        p["status"] = "REVOKED"
        stamp_update(p)
    return jsonify(success_object(serialize_pass(p))), 200
