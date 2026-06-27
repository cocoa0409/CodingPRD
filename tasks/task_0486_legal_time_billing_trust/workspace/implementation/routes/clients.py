"""Client routes plus client-scoped reverse lookups and rate overrides."""

from flask import Blueprint, request

import db
import errors
from common import (get_json_body, stamp_create, require_str, require_enum,
                    require_int, paginate)
from middleware import authenticate, require_role
from middleware import ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY
from response import object_response, array_response
import serializers
from services import recompute_client_ar, ar_summary

bp = Blueprint("clients", __name__)

ALL_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}
WRITE_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK}
CLIENT_TYPES = {"INDIVIDUAL", "ORGANIZATION"}
ROLE_KINDS = {"PARTNER", "ASSOCIATE", "PARALEGAL"}


@bp.route("/firm/clients", methods=["POST"])
def create_client():
    _uid, role = authenticate()
    require_role(role, WRITE_ROLES)
    body = get_json_body()
    display_name = require_str(body, "display_name", 1, 200)
    client_type = require_enum(body, "client_type", CLIENT_TYPES)
    with db.LOCK:
        rec = {
            "display_name": display_name,
            "client_type": client_type,
            "status": "PROSPECT",
            "ar_balance_cents": 0,
        }
        stamp_create(rec)
        db.clients[rec["id"]] = rec
    return object_response(serializers.s_client(rec), status=201)


@bp.route("/firm/clients/<cid>", methods=["GET"])
def get_client(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.clients.get(cid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_client(rec))


@bp.route("/firm/clients", methods=["GET"])
def list_clients():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    items = list(db.clients.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_client(c) for c in page], limit, offset, total)


@bp.route("/firm/clients/<cid>/matters", methods=["GET"])
def list_client_matters(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.clients.get(cid) is None:
        raise errors.not_found()
    items = [m for m in db.matters.values() if m["client_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_matter(m) for m in page], limit, offset, total)


@bp.route("/firm/clients/<cid>/ar-summary", methods=["GET"])
def client_ar_summary(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    client = db.clients.get(cid)
    if client is None:
        raise errors.not_found()
    with db.LOCK:
        recompute_client_ar(client)
        summary = ar_summary(cid)
    return object_response(summary)


@bp.route("/firm/clients/<cid>/trust-ledgers", methods=["GET"])
def list_client_trust_ledgers(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.clients.get(cid) is None:
        raise errors.not_found()
    items = [l for l in db.client_trust_ledgers.values() if l["client_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_trust_ledger(l) for l in page], limit, offset, total)


@bp.route("/firm/clients/<cid>/conflict-checks", methods=["GET"])
def list_client_conflict_checks(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.clients.get(cid) is None:
        raise errors.not_found()
    # Conflict checks whose adverse_party_client_id OR matched_client_id is this client.
    items = [c for c in db.conflict_checks.values()
             if c.get("adverse_party_client_id") == cid or c.get("matched_client_id") == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_conflict_check(c) for c in page], limit, offset, total)


# ---------------- Rate overrides ----------------

@bp.route("/firm/clients/<cid>/rate-overrides", methods=["POST"])
def create_rate_override(cid):
    _uid, role = authenticate()
    require_role(role, WRITE_ROLES)
    client = db.clients.get(cid)
    if client is None:
        raise errors.not_found()
    body = get_json_body()
    role_kind = require_enum(body, "role_kind", ROLE_KINDS)
    rate_cents = require_int(body, "rate_cents", minimum=0)
    with db.LOCK:
        # Upsert: replace any prior override for (client_id, role_kind).
        existing_id = None
        for oid, ov in db.rate_overrides.items():
            if ov["client_id"] == cid and ov["role_kind"] == role_kind:
                existing_id = oid
                break
        if existing_id is not None:
            ov = db.rate_overrides[existing_id]
            ov["rate_cents"] = rate_cents
            rec = ov
        else:
            rec = {
                "id": db.new_id(),
                "client_id": cid,
                "role_kind": role_kind,
                "rate_cents": rate_cents,
                "_seq": db.next_seq(),
            }
            db.rate_overrides[rec["id"]] = rec
    return object_response(serializers.s_rate_override(rec), status=201)


@bp.route("/firm/clients/<cid>/rate-overrides", methods=["GET"])
def list_rate_overrides(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.clients.get(cid) is None:
        raise errors.not_found()
    items = [ov for ov in db.rate_overrides.values() if ov["client_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_rate_override(ov) for ov in page], limit, offset, total)
