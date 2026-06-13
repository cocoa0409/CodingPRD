"""Customer endpoints (PRD §3.1, §2.7) and the test-driving clock."""
from flask import Blueprint

import db
from errors import err, ERR_VALIDATION
from middleware import get_identity, authorize
from response import success, list_response
from services import domain, lookup
from services.common import (
    stamp_create, touch, get_json_body, require_str, require_int,
    optional_enum, parse_pagination, paginate,
)
from timeutil import parse_iso_ms

bp = Blueprint("customers", __name__)

CURRENCIES = {"USD", "EUR", "GBP"}


@bp.route("/ar/customers", methods=["POST"])
def create_customer():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    body = get_json_body()
    name = require_str(body, "name")
    currency = optional_enum(body, "currency", CURRENCIES, default="USD")
    credit_limit = require_int(body, "credit_limit_cents", minimum=0)

    c = {
        "name": name,
        "currency": currency,
        "credit_limit_cents": credit_limit,
        "credit_status": "GOOD",
        "collection_stage": "CURRENT",
        "exposure_cents": 0,
        "total_open_balance_cents": 0,
        "bad_debt_total_cents": 0,
        "manual_hold": False,
        "watch_floor": False,
    }
    stamp_create(c)
    db.customers[c["id"]] = c
    return success(domain.serialize_customer(c), status=201)


@bp.route("/ar/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "COLLECTIONS_AGENT", "AUDITOR"])
    c = lookup.get_customer(cid)
    # Recompute exposure, total_open_balance, credit_status before responding.
    domain.recompute_customer(c, recompute_stage=False)
    return success(domain.serialize_customer(c), status=200)


@bp.route("/ar/customers", methods=["GET"])
def list_customers():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "COLLECTIONS_AGENT", "AUDITOR"])
    from flask import request

    limit, offset = parse_pagination()
    credit_status = request.args.get("credit_status")
    collection_stage = request.args.get("collection_stage")

    items = list(db.customers.values())
    if credit_status is not None:
        items = [c for c in items if c["credit_status"] == credit_status]
    if collection_stage is not None:
        items = [c for c in items if c["collection_stage"] == collection_stage]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_customer(c) for c in page], limit, offset, total)


@bp.route("/ar/customers/<cid>/hold", methods=["POST"])
def hold(cid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    c = lookup.get_customer(cid)
    c["manual_hold"] = True
    touch(c)
    domain.recompute_customer(c, recompute_stage=False, already_touched=True)
    return success(domain.serialize_customer(c), status=200)


@bp.route("/ar/customers/<cid>/release-hold", methods=["POST"])
def release_hold(cid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    c = lookup.get_customer(cid)
    c["manual_hold"] = False
    touch(c)
    domain.recompute_customer(c, recompute_stage=False, already_touched=True)
    return success(domain.serialize_customer(c), status=200)


@bp.route("/ar/customers/<cid>/statements", methods=["GET"])
def list_customer_statements(cid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "AUDITOR"])
    lookup.get_customer(cid)
    limit, offset = parse_pagination()
    items = [s for s in db.statements.values() if s["customer_id"] == cid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_statement(s) for s in page], limit, offset, total)


@bp.route("/ar/customers/<cid>/dunning-pauses", methods=["GET"])
def list_customer_pauses(cid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    lookup.get_customer(cid)
    limit, offset = parse_pagination()
    items = [p for p in db.dunning_pauses.values() if p["customer_id"] == cid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_pause(p) for p in page], limit, offset, total)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER"])
    body = get_json_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err(ERR_VALIDATION, "to_iso8601 required")
    ms = parse_iso_ms(body["to_iso8601"])
    db.set_clock_ms(ms)
    return success({}, status=200)
