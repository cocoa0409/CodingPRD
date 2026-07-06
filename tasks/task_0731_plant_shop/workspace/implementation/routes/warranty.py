"""Warranty claims: submit, approve, deny, list, read."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
from flask import Blueprint, request
from clock import iso_now, get_now, parse_iso
from db import DB
from errors import (
    not_found, invalid_request, invalid_state, unauthorized,
    ApiError, ERR_WARRANTY_EXPIRED, ERR_WARRANTY_NOT_ELIGIBLE,
    ERR_REFUND_CAP_EXCEEDED,
)
from middleware import (
    auth_context, require_role, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common, bump
from services.validation import require_fields, require_enum
from services.loyalty import compute_reversal_for_line, append_ledger

bp = Blueprint("warranty", __name__)

REASONS = {"MORTALITY", "DAMAGED", "MISDELIVERY", "OTHER"}
STATUSES = {"SUBMITTED", "APPROVED", "DENIED"}

MANDATORY_CARE_INTERVAL_COUNT = 3
DEDUCTION_PCT = Decimal("0.20")
REFUND_CAP_CENTS = 20000  # customer 30-day refund cap


@bp.post("/warranty-claims")
def submit_claim():
    role, user_id = auth_context()
    require_role(role, {"Customer"})
    payload = require_json()
    require_fields(payload, ["orderline_id", "customer_id", "reason"])
    ol_id = payload["orderline_id"]
    cid = payload["customer_id"]
    if user_id != cid:
        raise unauthorized("Customer may only claim as self")
    require_enum(payload["reason"], REASONS, "reason")

    line = DB.order_lines.get(ol_id)
    if not line:
        raise not_found("OrderLine")
    if cid not in DB.customers:
        raise not_found("Customer")
    order = DB.orders[line["order_id"]]

    # Eligibility (business_safety before business_referential): warranty
    # expiry (priority 9) — but note owner mismatch is business_referential
    # (priority 16) - so expiry evaluates FIRST.
    plant = DB.plants[line["plant_id"]]
    delivered_at = line.get("delivered_at")
    if not delivered_at:
        # Order not delivered yet — must be state precondition, but the
        # scaffold doesn't explicitly list one on submission. Use invalid_state
        # because there is nothing to compute a warranty window against.
        raise invalid_state("order line not delivered")
    delivered_dt = parse_iso(delivered_at)
    now = get_now()
    elapsed_days = int((now - delivered_dt).total_seconds() // 86400)
    if elapsed_days > plant["warranty_days"]:
        raise ApiError(ERR_WARRANTY_EXPIRED, 422, "warranty expired")

    # Referential: customer must own the parent order.
    if order["customer_id"] != cid:
        raise ApiError(ERR_WARRANTY_NOT_ELIGIBLE, 422, "not order owner")

    # Provisional refund = full base, no deductions.
    base = line["line_subtotal_cents"]
    provisional = base

    entity = {
        **stamp_common(full=True),
        "orderline_id": ol_id,
        "customer_id": cid,
        "reason": payload["reason"],
        "submitted_at": iso_now(),
        "status": "SUBMITTED",
        "refund_amount_cents_provisional": provisional,
        "refund_amount_cents_final": 0,
    }
    DB.warranty_claims[entity["id"]] = entity
    line["refund_status"] = "PENDING_REVIEW"
    return created(entity)


def _count_mandatory_care_events(stock_unit_id: str, from_ts: str, to_ts: str) -> int:
    from_dt = parse_iso(from_ts)
    to_dt = parse_iso(to_ts)
    count = 0
    for e in DB.care_log_entries.values():
        if e["stock_unit_id"] != stock_unit_id:
            continue
        if e["entry_type"] not in ("WATER", "LIGHT_CHECK", "PRUNE"):
            continue
        ts = parse_iso(e["entered_at"])
        if from_dt <= ts <= to_dt:
            count += 1
    return count


@bp.post("/warranty-claims/<cid>/approve")
def approve_claim(cid):
    role, _ = auth_context()
    require_role(role, {"Horticulturist", "Manager"})
    claim = DB.warranty_claims.get(cid)
    if not claim:
        raise not_found("WarrantyClaim")
    line = DB.order_lines[claim["orderline_id"]]
    order = DB.orders[line["order_id"]]

    if claim["status"] != "SUBMITTED":
        raise invalid_state("claim not SUBMITTED")
    if line["refund_status"] != "PENDING_REVIEW":
        raise invalid_state("orderline not PENDING_REVIEW")
    if order["fulfillment_status"] != "DELIVERED":
        raise invalid_state("order not DELIVERED")

    # Compute final refund.
    stock_unit_id = line["stock_unit_id"]
    delivered_at = line["delivered_at"]
    observed = _count_mandatory_care_events(stock_unit_id, delivered_at, claim["submitted_at"])
    missing = max(0, MANDATORY_CARE_INTERVAL_COUNT - observed)
    deductions = min(missing, 3)
    base = line["line_subtotal_cents"]
    factor = Decimal("1.0") - DEDUCTION_PCT * deductions
    final = int((Decimal(base) * factor).to_integral_value(rounding=ROUND_FLOOR))

    # Fiscal: 30-day rolling refund cap.
    now = get_now()
    thirty_days_ago = now - timedelta(days=30)
    cumulative = 0
    for other in DB.warranty_claims.values():
        if other["customer_id"] != claim["customer_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        # approved_at is not stored explicitly; use updated_at.
        ts_str = other.get("approved_at") or other.get("updated_at")
        ts = parse_iso(ts_str)
        if ts is None:
            continue
        if ts >= thirty_days_ago:
            cumulative += other.get("refund_amount_cents_final", 0)
    if cumulative + final > REFUND_CAP_CENTS:
        raise ApiError(ERR_REFUND_CAP_EXCEEDED, 422, "30-day refund cap exceeded")

    # Cascade.
    customer = DB.customers[claim["customer_id"]]
    su = DB.stock_units[stock_unit_id]
    tier_at_delivery = customer["loyalty_tier"]  # Approximation.

    claim["status"] = "APPROVED"
    claim["refund_amount_cents_final"] = final
    claim["approved_at"] = iso_now()
    line["refund_status"] = "REFUNDED"
    line["refund_amount_cents"] = final
    customer["wallet_credit_cents"] = customer.get("wallet_credit_cents", 0) + final

    # StockUnit: SOLD -> RETURNED -> SHRINK with shrink_reason=WARRANTY_RETURN.
    if su["sale_status"] == "SOLD":
        su["sale_status"] = "RETURNED"
        bump(su)
    su["sale_status"] = "SHRINK"
    su["shrink_reason"] = "WARRANTY_RETURN"
    bump(su)

    # Loyalty reversal.
    magnitude = compute_reversal_for_line(line["line_subtotal_cents"], tier_at_delivery)
    append_ledger(claim["customer_id"], order["id"], "REVERSAL", -magnitude)

    bump(claim)
    return ok(claim)


@bp.post("/warranty-claims/<cid>/deny")
def deny_claim(cid):
    role, _ = auth_context()
    require_role(role, {"Horticulturist", "Manager"})
    claim = DB.warranty_claims.get(cid)
    if not claim:
        raise not_found("WarrantyClaim")
    line = DB.order_lines[claim["orderline_id"]]
    if claim["status"] != "SUBMITTED":
        raise invalid_state("claim not SUBMITTED")
    claim["status"] = "DENIED"
    line["refund_status"] = "DENIED"
    bump(claim)
    return ok(claim)


@bp.get("/warranty-claims")
def list_claims():
    role, user_id = auth_context()
    require_role(role, {"Customer", "Horticulturist", "Manager"})
    limit, offset = parse_pagination(request.args)
    customer_id = request.args.get("customer_id")
    orderline_id = request.args.get("orderline_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in STATUSES:
        raise invalid_request("invalid status filter")
    rows = list(DB.warranty_claims.values())
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if orderline_id:
        rows = [r for r in rows if r["orderline_id"] == orderline_id]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if role == "Customer":
        rows = [r for r in rows if r["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/warranty-claims/<cid>")
def get_claim(cid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Horticulturist", "Manager"})
    claim = DB.warranty_claims.get(cid)
    if not claim:
        raise not_found("WarrantyClaim")
    if role == "Customer" and user_id != claim["customer_id"]:
        raise unauthorized("not claim owner")
    return ok(claim)
