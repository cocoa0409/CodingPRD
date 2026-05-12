"""Order routes."""
from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, request

import db
from db import (
    funds, investors, orders, holdings, idempotency_index, public,
    stamp_create, stamp_update,
)
from clock import now, iso, parse_iso, parse_iso_date, date_to_dt_utc
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import audit
from services.util import (
    get_body, require_field, check_version,
    RISK_TOLERANCE_INDEX, RISK_RATING_INDEX,
)
from services.calculations import assign_trade_date
from services.holdings import get_or_create_holding


bp = Blueprint("orders", __name__)


VALID_ORDER_TYPES = {"SUBSCRIBE", "REDEEM", "CONVERT"}


def _suitability_ok(investor: dict, fund: dict) -> bool:
    return RISK_TOLERANCE_INDEX[investor["risk_tolerance"]] >= RISK_RATING_INDEX[fund["risk_rating"]]


def _region_ok(investor: dict, fund: dict) -> bool:
    allowed = fund["allowed_country_codes"]
    if not allowed:
        return True
    return investor["country_code"] in allowed


def _shares_for_investor_fund(investor_id: str, fund_id: str) -> int:
    h = None
    for hh in holdings.values():
        if hh["investor_id"] == investor_id and hh["fund_id"] == fund_id:
            h = hh
            break
    return h["shares"] if h else 0


def _bodies_equal(a: dict, b: dict) -> bool:
    """Compare two order-creation request bodies for idempotency replay equivalence."""
    keys = ("fund_id", "order_type", "target_fund_id", "gross_amount_cents",
            "requested_shares", "idempotency_key")
    for k in keys:
        if a.get(k) != b.get(k):
            return False
    return True


@bp.route("/orders", methods=["POST"])
@require_auth(roles={"Investor"})
def create_order():
    body = get_body()
    require_field(body, "fund_id")
    require_field(body, "order_type")
    require_field(body, "idempotency_key")

    investor_id = g.user_id
    inv = investors.get(investor_id)
    if not inv:
        # For Investor role X-User-ID must reference an Investor entity.
        raise err("ERR_FORBIDDEN", "X-User-ID does not reference a valid investor")

    # Existence: fund_id must exist
    fund_id = body["fund_id"]
    fund = funds.get(fund_id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")

    # Idempotency replay (priority 4 — before invalid_state)
    idem_key = body["idempotency_key"]
    tup = (investor_id, idem_key)
    if tup in idempotency_index:
        existing_id = idempotency_index[tup]
        existing = orders.get(existing_id)
        if existing is None:
            raise err("ERR_IDEMPOTENCY_REPLAY", "Conflicting idempotency record")
        existing_body = {
            "fund_id": existing["fund_id"],
            "order_type": existing["order_type"],
            "target_fund_id": existing.get("target_fund_id"),
            "gross_amount_cents": existing.get("gross_amount_cents"),
            "requested_shares": existing.get("requested_shares"),
            "idempotency_key": existing["idempotency_key"],
        }
        if _bodies_equal(existing_body, body):
            return success(public(existing), 200)
        raise err("ERR_IDEMPOTENCY_REPLAY", "Body differs for same idempotency key")

    order_type = body["order_type"]
    if order_type not in VALID_ORDER_TYPES:
        raise err("ERR_VALIDATION", "invalid order_type")

    # Build order shell (so we can record SUBMITTED -> REJECTED with rejection_error_id)
    submitted_at = now()
    target_fund_id = body.get("target_fund_id")
    gross_amount_cents = body.get("gross_amount_cents")
    requested_shares = body.get("requested_shares")

    order = {
        "fund_id": fund_id,
        "investor_id": investor_id,
        "order_type": order_type,
        "target_fund_id": target_fund_id,
        "gross_amount_cents": gross_amount_cents,
        "requested_shares": requested_shares,
        "submitted_at": iso(submitted_at),
        "trade_date": None,
        "confirm_date": None,
        "status": "SUBMITTED",
        "confirmed_nav_per_share_micros": None,
        "confirmed_shares": None,
        "confirmed_amount_cents": None,
        "subscription_fee_cents": None,
        "redemption_fee_cents": None,
        "back_end_load_fee_cents": None,
        "conversion_fee_cents": None,
        "large_redemption_pct_bps": None,
        "rejection_error_id": None,
        "idempotency_key": idem_key,
    }

    # Run synchronous acceptance checks. Order them per validation priority §2.10
    # state(5) handled by Fund.status==ON_SHELF below; KYC(9), suitability(10), region(11),
    # convert target(12), order limit(16), insufficient cash(18)/shares(19).

    def _reject(error_id: str, message: str):
        """Persist order in REJECTED status with rejection_error_id, audit, then raise."""
        order["status"] = "REJECTED"
        order["rejection_error_id"] = error_id
        stamp_create(order, common_fields=True)
        orders[order["id"]] = order
        idempotency_index[(investor_id, idem_key)] = order["id"]
        audit.write(g.user_id, g.user_role, "ORDER_STATUS_CHANGE", "Order",
                    order["id"], "SUBMITTED", "REJECTED",
                    {"rejection_error_id": error_id})
        raise err(error_id, message)

    # state(5): Fund.status == ON_SHELF
    if fund["status"] != "ON_SHELF":
        _reject("ERR_INVALID_STATE", f"Fund.status is {fund['status']}, expected ON_SHELF")

    # 9: KYC approved
    if inv["kyc_status"] != "APPROVED":
        _reject("ERR_KYC_NOT_APPROVED", "Investor KYC not APPROVED")

    # 10: suitability
    if not _suitability_ok(inv, fund):
        _reject("ERR_SUITABILITY_MISMATCH", "Investor risk tolerance below fund risk rating")

    # 11: region
    if not _region_ok(inv, fund):
        _reject("ERR_REGION_RESTRICTED", "Investor country not allowed by fund")

    # 12: convert target validity
    if order_type == "CONVERT":
        if not target_fund_id or target_fund_id == fund_id:
            _reject("ERR_CONVERSION_INVALID_TARGET", "target_fund_id must differ from source")
        target = funds.get(target_fund_id)
        if not target:
            _reject("ERR_CONVERSION_INVALID_TARGET", "target fund not found")
        if target["status"] != "ON_SHELF":
            _reject("ERR_CONVERSION_INVALID_TARGET", "target fund not ON_SHELF")
        if not _suitability_ok(inv, target):
            _reject("ERR_CONVERSION_INVALID_TARGET", "investor not suitable for target fund")

    # 16: order limit
    if order_type == "SUBSCRIBE":
        if gross_amount_cents is None or not isinstance(gross_amount_cents, int) or isinstance(gross_amount_cents, bool):
            _reject("ERR_ORDER_LIMIT_VIOLATED", "gross_amount_cents required and must be integer")
        if gross_amount_cents <= 0:
            _reject("ERR_ORDER_LIMIT_VIOLATED", "gross_amount_cents must be positive")
        min_amt = fund["min_subscription_amount_cents"]
        max_amt = fund.get("max_subscription_amount_cents")
        if gross_amount_cents < min_amt:
            _reject("ERR_ORDER_LIMIT_VIOLATED", "amount below minimum")
        if max_amt is not None and gross_amount_cents > max_amt:
            _reject("ERR_ORDER_LIMIT_VIOLATED", "amount above maximum")
    else:  # REDEEM or CONVERT
        if requested_shares is None or not isinstance(requested_shares, int) or isinstance(requested_shares, bool):
            _reject("ERR_ORDER_LIMIT_VIOLATED", "requested_shares required and must be integer")
        if requested_shares <= 0:
            _reject("ERR_ORDER_LIMIT_VIOLATED", "requested_shares must be positive")
        if requested_shares < fund["min_redemption_shares"]:
            _reject("ERR_ORDER_LIMIT_VIOLATED", "shares below minimum")

    # 18: insufficient cash for SUBSCRIBE
    if order_type == "SUBSCRIBE":
        if inv["cash_balance_cents"] < gross_amount_cents:
            _reject("ERR_INSUFFICIENT_CASH", "Insufficient cash for subscription")

    # 19: insufficient shares for REDEEM/CONVERT
    if order_type in ("REDEEM", "CONVERT"):
        held = _shares_for_investor_fund(investor_id, fund_id)
        if held < requested_shares:
            _reject("ERR_INSUFFICIENT_SHARES", "Insufficient shares for redeem/convert")

    # All checks passed: assign trade_date and confirm_date, ACCEPTED.
    trade_date = assign_trade_date(submitted_at)
    confirm_cycle = fund.get("confirmation_cycle_days")
    if confirm_cycle is None:
        # ON_SHELF guarantees this is set, but guard.
        from services.calculations import confirmation_cycle_days_for_type
        confirm_cycle = confirmation_cycle_days_for_type(fund["fund_type"])
    confirm_date = trade_date + timedelta(days=confirm_cycle)

    order["trade_date"] = iso(date_to_dt_utc(trade_date))
    order["confirm_date"] = iso(date_to_dt_utc(confirm_date))
    order["status"] = "ACCEPTED"
    stamp_create(order, common_fields=True)
    orders[order["id"]] = order
    idempotency_index[(investor_id, idem_key)] = order["id"]

    audit.write(g.user_id, g.user_role, "ORDER_STATUS_CHANGE", "Order", order["id"],
                "SUBMITTED", "ACCEPTED",
                {"trade_date": str(trade_date), "confirm_date": str(confirm_date)})

    return success(public(order), 201)


@bp.route("/orders/<id>/cancel", methods=["POST"])
@require_auth(roles={"Investor"})
def cancel_order(id):
    order = orders.get(id)
    if not order:
        raise err("ERR_NOT_FOUND", "Order not found")
    if g.user_id != order["investor_id"]:
        raise err("ERR_FORBIDDEN", "Only the order's investor may cancel")
    body = get_body()
    check_version(body, order)
    if order["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", f"Order.status is {order['status']}, cannot cancel")

    # Cancel-cutoff: clock < trade_date 15:00 UTC
    trade_dt = parse_iso(order["trade_date"])
    cutoff = trade_dt.replace(hour=15, minute=0, second=0, microsecond=0)
    if now() >= cutoff:
        raise err("ERR_CANCEL_WINDOW_CLOSED", "Cancel window has closed")
    order["status"] = "CANCELLED"
    stamp_update(order)
    audit.write(g.user_id, g.user_role, "ORDER_STATUS_CHANGE", "Order", order["id"],
                "ACCEPTED", "CANCELLED", {})
    return success(public(order), 200)


@bp.route("/orders/<id>", methods=["GET"])
@require_auth(roles={"Investor", "ClearingOperator", "ComplianceReviewer", "PlatformAdmin"})
def read_order(id):
    order = orders.get(id)
    if not order:
        raise err("ERR_NOT_FOUND", "Order not found")
    if g.user_role == "Investor" and g.user_id != order["investor_id"]:
        raise err("ERR_FORBIDDEN", "Investor may only read their own order")
    return success(public(order), 200)


@bp.route("/orders", methods=["GET"])
@require_auth(roles={"ClearingOperator", "ComplianceReviewer", "PlatformAdmin", "Investor"})
def list_orders():
    items = list(orders.values())
    if g.user_role == "Investor":
        items = [o for o in items if o["investor_id"] == g.user_id]
    investor_q = request.args.get("investor_id")
    fund_q = request.args.get("fund_id")
    status_q = request.args.get("status")
    trade_date_q = request.args.get("trade_date")
    if investor_q:
        items = [o for o in items if o["investor_id"] == investor_q]
    if fund_q:
        items = [o for o in items if o["fund_id"] == fund_q]
    if status_q:
        items = [o for o in items if o["status"] == status_q]
    if trade_date_q:
        try:
            target_d = parse_iso_date(trade_date_q)
        except Exception:
            target_d = None
        if target_d is not None:
            def _match(o):
                if not o.get("trade_date"):
                    return False
                try:
                    return parse_iso_date(o["trade_date"]) == target_d
                except Exception:
                    return False
            items = [o for o in items if _match(o)]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([public(o) for o in page], limit, offset, total, 200)
