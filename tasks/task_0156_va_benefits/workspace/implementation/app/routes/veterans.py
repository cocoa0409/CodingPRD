"""Veteran routes."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..errors import ApiError
from ..serializers import serialize_claim, serialize_dependent, serialize_ledger_entry, serialize_veteran
from ..services.veterans import create_veteran, get_projection, update_veteran
from ..util import paginate, parse_pagination
from ._common import get_json_body, get_store, respond_array, respond_object

bp = Blueprint("veterans", __name__)


@bp.route("/veterans", methods=["POST"])
@require_auth(["VAClerk", "PlatformAdmin"])
def post_veterans():
    body = get_json_body()
    store = get_store()
    with store.lock:
        v = create_veteran(store, body)
    return respond_object(serialize_veteran(v), status=201)


@bp.route("/veterans/<vid>", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "Rater", "Counselor", "PlatformAdmin"])
def get_veteran(vid: str):
    store = get_store()
    v = store.veterans.get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")
    # Veteran can only read self.
    if g.user_role == "Veteran" and g.user_id != vid:
        raise ApiError("ERR_FORBIDDEN", "veterans can only read their own record")
    return respond_object(serialize_veteran(v))


@bp.route("/veterans/<vid>", methods=["PATCH"])
@require_auth(["VAClerk", "PlatformAdmin"])
def patch_veteran(vid: str):
    body = get_json_body()
    store = get_store()
    with store.lock:
        if vid not in store.veterans:
            raise ApiError("ERR_NOT_FOUND", "veteran not found")
        v = update_veteran(store, vid, body)
    return respond_object(serialize_veteran(v))


@bp.route("/veterans/<vid>/entitlement-projection", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "PlatformAdmin"])
def projection(vid: str):
    store = get_store()
    if vid not in store.veterans:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")
    if g.user_role == "Veteran" and g.user_id != vid:
        raise ApiError("ERR_FORBIDDEN", "veteran can only read own projection")
    include = request.args.get("include_certified", "false").lower() in ("true", "1", "yes")
    return respond_object(get_projection(store, vid, include))


@bp.route("/veterans/<vid>/dependents", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "PlatformAdmin"])
def list_dependents(vid: str):
    store = get_store()
    if vid not in store.veterans:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")
    if g.user_role == "Veteran" and g.user_id != vid:
        raise ApiError("ERR_FORBIDDEN", "veteran can only read own dependents")
    status_filter = request.args.get("status")
    limit, offset = parse_pagination(request.args)
    items = [d for d in store.dependents.values() if d["veteran_id"] == vid]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    items.sort(key=lambda d: d["created_at"])
    page, total = paginate(items, limit, offset)
    return respond_array([serialize_dependent(d) for d in page], limit=limit, offset=offset, total_count=total)


@bp.route("/veterans/<vid>/claims", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "Rater", "PlatformAdmin"])
def list_claims(vid: str):
    store = get_store()
    if vid not in store.veterans:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")
    if g.user_role == "Veteran" and g.user_id != vid:
        raise ApiError("ERR_FORBIDDEN", "veteran can only read own claims")
    status_filter = request.args.get("status")
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.claims.values() if c["veteran_id"] == vid]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return respond_array([serialize_claim(c) for c in page], limit=limit, offset=offset, total_count=total)


@bp.route("/veterans/<vid>/ledger", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "PlatformAdmin"])
def list_ledger(vid: str):
    store = get_store()
    if vid not in store.veterans:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")
    if g.user_role == "Veteran" and g.user_id != vid:
        raise ApiError("ERR_FORBIDDEN", "veteran can only read own ledger")
    source_filter = request.args.get("source_entity")
    limit, offset = parse_pagination(request.args)
    items = [l for l in store.ledger_entries.values() if l["veteran_id"] == vid]
    if source_filter:
        items = [l for l in items if l["source_entity"] == source_filter]
    items.sort(key=lambda l: l["created_at"])
    page, total = paginate(items, limit, offset)
    return respond_array([serialize_ledger_entry(l) for l in page], limit=limit, offset=offset, total_count=total)
