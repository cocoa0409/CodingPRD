"""Customer endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_VALIDATION, ERR_INSUFFICIENT_STORE_CREDIT
from middleware import require_roles, get_auth
from response import success
from services import serialize, derive
from services.common import (
    parse_body, require_str, require_int, require_enum, paginate, lookup,
    get_pagination,
)
from datetime import timedelta
from services.calc import compute_return_risk, round_half_up_4

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    # exempt from auth (Anonymous or StoreAdmin may call; no header needed)
    body = parse_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    # unique email
    for c in db.customers.values():
        if c["email"] == email:
            raise err(ERR_VALIDATION, "email already registered")
    rec = {"email": email, "full_name": full_name}
    db.stamp_create(rec)
    db.customers[rec["id"]] = rec
    return success(serialize.customer(rec), status=201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_roles(["Customer", "StoreAdmin"])
    rec = lookup(db.customers, cid)
    return success(serialize.customer(rec))


@bp.route("/customers/<cid>/risk", methods=["GET"])
def get_customer_risk(cid):
    require_roles(["StoreAdmin"])
    rec = lookup(db.customers, cid)
    window_raw = request.args.get("window_days")
    if window_raw is None:
        return success(serialize.customer(rec))
    # trailing-window variant
    try:
        window_days = int(window_raw)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "window_days must be an integer")
    if window_days < 0:
        raise err(ERR_VALIDATION, "window_days must be >= 0")
    cutoff = db.current_clock - timedelta(days=window_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S.") + f"{cutoff.microsecond // 1000:03d}Z"

    purchased = 0
    for o in db.orders.values():
        if o["customer_id"] == cid and o["payment_status"] in derive.PURCHASED_STATES \
                and o["created_at"] >= cutoff_iso:
            purchased += o["captured_total_cents"]
    refunded = 0
    for r in db.refunds.values():
        if r["customer_id"] == cid and r["status"] == "SETTLED" \
                and r["created_at"] >= cutoff_iso:
            refunded += r["amount_cents"]
    score = compute_return_risk(purchased, refunded)

    out = serialize.customer(rec)
    out["lifetime_purchased_cents"] = purchased
    out["lifetime_refunded_cents"] = refunded
    out["return_risk_score"] = score
    return success(out)


@bp.route("/customers/<cid>/orders", methods=["GET"])
def list_customer_orders(cid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.customers, cid)
    rows = [o for o in db.orders.values() if o["customer_id"] == cid]
    data, meta = paginate(rows, serialize.order)
    return success(data, pagination=meta)


@bp.route("/customers/<cid>/credit-entries", methods=["GET"])
def list_customer_credit_entries(cid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.customers, cid)
    rows = [e for e in db.credit_ledger_entries.values() if e["customer_id"] == cid]
    data, meta = paginate(rows, serialize.credit_ledger_entry)
    return success(data, pagination=meta)


@bp.route("/customers/<cid>/refunds", methods=["GET"])
def list_customer_refunds(cid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.customers, cid)
    rows = [r for r in db.refunds.values() if r["customer_id"] == cid]
    data, meta = paginate(rows, serialize.refund)
    return success(data, pagination=meta)


@bp.route("/customers/<cid>/returns", methods=["GET"])
def list_customer_returns(cid):
    require_roles(["Customer", "StoreAdmin"])
    lookup(db.customers, cid)
    rows = [r for r in db.return_authorizations.values() if r["customer_id"] == cid]
    data, meta = paginate(rows, serialize.return_authorization)
    return success(data, pagination=meta)


@bp.route("/customers/<cid>/credit-adjustments", methods=["POST"])
def create_credit_adjustment(cid):
    require_roles(["StoreAdmin"])
    rec_customer = lookup(db.customers, cid)
    body = parse_body()
    amount = require_int(body, "amount_cents")
    kind = require_enum(body, "kind", {"REFUND_CREDIT", "ADMIN_ADJUSTMENT", "REDEMPTION"})
    # would it drive balance below 0?
    current = derive.customer_store_credit_cents(cid)
    if current + amount < 0:
        raise err(ERR_INSUFFICIENT_STORE_CREDIT, "Adjustment would drive store credit below 0")
    entry = {
        "customer_id": cid,
        "refund_id": body.get("refund_id"),
        "amount_cents": amount,
        "kind": kind,
    }
    db.stamp_create(entry, common_fields=False)
    db.credit_ledger_entries[entry["id"]] = entry
    # store_credit_cents recomputed; bump customer
    db.touch(rec_customer)
    return success(serialize.credit_ledger_entry(entry), status=201)
