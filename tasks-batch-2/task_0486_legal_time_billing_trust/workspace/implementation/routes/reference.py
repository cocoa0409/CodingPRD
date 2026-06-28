"""Reference data: timekeepers, billing codes, trust accounts, and the clock."""

from flask import Blueprint

import db
import errors
from clock import clock, parse_iso8601
from common import (get_json_body, stamp_create, require_str, require_enum,
                    require_int, optional_bool, paginate)
from middleware import authenticate, require_role
from middleware import ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY
from response import object_response, array_response
import serializers
from services import reage_all_invoices

bp = Blueprint("reference", __name__)

ALL_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}
ROLE_KINDS = {"PARTNER", "ASSOCIATE", "PARALEGAL"}
CODE_KINDS = {"TASK", "ACTIVITY", "EXPENSE"}


# ---------------- Timekeepers ----------------

@bp.route("/firm/timekeepers", methods=["POST"])
def create_timekeeper():
    _uid, role = authenticate()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    full_name = require_str(body, "full_name", 1, 200)
    role_kind = require_enum(body, "role_kind", ROLE_KINDS)
    standard_rate = require_int(body, "standard_rate_cents", minimum=0)
    is_active = optional_bool(body, "is_active", True)
    with db.LOCK:
        rec = {
            "full_name": full_name,
            "role_kind": role_kind,
            "standard_rate_cents": standard_rate,
            "is_active": is_active,
        }
        stamp_create(rec)
        db.timekeepers[rec["id"]] = rec
    return object_response(serializers.s_timekeeper(rec), status=201)


@bp.route("/firm/timekeepers/<tid>", methods=["GET"])
def get_timekeeper(tid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.timekeepers.get(tid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_timekeeper(rec))


@bp.route("/firm/timekeepers", methods=["GET"])
def list_timekeepers():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    items = list(db.timekeepers.values())
    is_active = request.args.get("is_active")
    if is_active is not None:
        want = is_active.lower() == "true"
        items = [t for t in items if t["is_active"] == want]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_timekeeper(t) for t in page], limit, offset, total)


# ---------------- Billing codes ----------------

@bp.route("/firm/billing-codes", methods=["POST"])
def create_billing_code():
    _uid, role = authenticate()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    code = require_str(body, "code", 2, 10)
    kind = require_enum(body, "kind", CODE_KINDS)
    label = require_str(body, "label", 1, 120)
    with db.LOCK:
        for existing in db.billing_codes.values():
            if existing["code"] == code:
                raise errors.duplicate_code()
        now_seq_rec = {"code": code, "kind": kind, "label": label}
        # BillingCode is lean: id + created_at only.
        from clock import server_now_iso
        now_seq_rec["id"] = db.new_id()
        now_seq_rec["created_at"] = server_now_iso()
        now_seq_rec["_seq"] = db.next_seq()
        db.billing_codes[now_seq_rec["id"]] = now_seq_rec
    return object_response(serializers.s_billing_code(now_seq_rec), status=201)


@bp.route("/firm/billing-codes", methods=["GET"])
def list_billing_codes():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    items = list(db.billing_codes.values())
    kind = request.args.get("kind")
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_billing_code(c) for c in page], limit, offset, total)


# ---------------- Trust accounts ----------------

@bp.route("/firm/trust-accounts", methods=["POST"])
def create_trust_account():
    _uid, role = authenticate()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    name = require_str(body, "name", 1, 120)
    with db.LOCK:
        rec = {"name": name, "book_balance_cents": 0, "bank_balance_cents": 0}
        stamp_create(rec)
        db.trust_accounts[rec["id"]] = rec
    return object_response(serializers.s_trust_account(rec), status=201)


@bp.route("/firm/trust-accounts/<aid>", methods=["GET"])
def get_trust_account(aid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.trust_accounts.get(aid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_trust_account(rec))


@bp.route("/firm/trust-accounts/<aid>/ledgers", methods=["GET"])
def list_account_ledgers(aid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.trust_accounts.get(aid) is None:
        raise errors.not_found()
    items = [l for l in db.client_trust_ledgers.values() if l["trust_account_id"] == aid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_trust_ledger(l) for l in page], limit, offset, total)


@bp.route("/firm/trust-accounts/<aid>/reconciliation", methods=["GET"])
def account_reconciliation(aid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.trust_accounts.get(aid) is None:
        raise errors.not_found()
    from services import reconciliation
    return object_response(reconciliation(aid))


# ---------------- Logical clock ----------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    body = get_json_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise errors.invalid_request("Missing required field 'to_iso8601'.")
    raw = body["to_iso8601"]
    if not isinstance(raw, str):
        raise errors.invalid_request("Field 'to_iso8601' must be a string.")
    try:
        dt = parse_iso8601(raw)
    except Exception:
        raise errors.invalid_request("Field 'to_iso8601' is not a valid ISO 8601 timestamp.")
    with db.LOCK:
        clock.set(dt)
        reage_all_invoices()
    return object_response({"current_utc": clock.now_iso()})


@bp.route("/firm/health", methods=["GET"])
def health():
    # No authentication (PRD §4).
    return object_response({"status": "ok", "current_utc": clock.now_iso()})
