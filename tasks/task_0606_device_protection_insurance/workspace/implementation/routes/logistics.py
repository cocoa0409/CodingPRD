"""Fraud screens (GET), repair orders, advanced exchanges, trade-ins, clock."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import calculations as calc
from clock import clock, parse_iso, to_iso
from db import db, new_id
from helpers import (serialize, base_system_fields, touch, get_or_404,
                     parse_pagination, paginate, sorted_by_created,
                     body, require_str, require_int)
from middleware import require_auth, require_role
from response import ok, ok_list

bp = Blueprint("logistics", __name__)


# ---------------- Fraud screens (read-only) ----------------
@bp.route("/fraud-screens", methods=["GET"])
def list_fraud_screens():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster"})
    limit, offset = parse_pagination()
    vals = list(db.fraud_screens.values())
    claim_f = request.args.get("claim_id")
    cust_f = request.args.get("customer_id")
    if claim_f is not None:
        vals = [f for f in vals if f["claim_id"] == claim_f]
    if cust_f is not None:
        vals = [f for f in vals if f["customer_id"] == cust_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(f) for f in page], limit, offset, total)


@bp.route("/fraud-screens/<fid>", methods=["GET"])
def get_fraud_screen(fid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster"})
    fs = get_or_404(db.fraud_screens, fid)
    return ok(serialize(fs), 200)


# ---------------- Repair orders ----------------
@bp.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster", "LogisticsAgent"})
    limit, offset = parse_pagination()
    vals = list(db.repair_orders.values())
    claim_f = request.args.get("claim_id")
    if claim_f is not None:
        vals = [r for r in vals if r["claim_id"] == claim_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster", "LogisticsAgent"})
    ro = get_or_404(db.repair_orders, rid)
    return ok(serialize(ro), 200)


@bp.route("/repair-orders/<rid>/complete", methods=["POST"])
def complete_repair_order(rid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ro = get_or_404(db.repair_orders, rid)
    if ro["status"] != "OPEN":
        errors.fail(errors.ERR_INVALID_STATE, "RepairOrder not OPEN")
    claim = db.claims[ro["claim_id"]]
    if claim["status"] != "ROUTED_REPAIR":
        errors.fail(errors.ERR_INVALID_STATE, "Claim not ROUTED_REPAIR")
    ro["status"] = "COMPLETED"
    touch(ro)
    claim["status"] = "FULFILLED"
    touch(claim)
    enr = db.enrollments[claim["enrollment_id"]]
    if enr["open_claim_id"] == claim["id"]:
        enr["open_claim_id"] = None
        touch(enr)
    return ok(serialize(ro), 200)


# ---------------- Advanced exchanges ----------------
@bp.route("/advanced-exchanges", methods=["GET"])
def list_advanced_exchanges():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster", "LogisticsAgent"})
    limit, offset = parse_pagination()
    vals = list(db.advanced_exchanges.values())
    claim_f = request.args.get("claim_id")
    sku_f = request.args.get("replacement_sku_id")
    if claim_f is not None:
        vals = [a for a in vals if a["claim_id"] == claim_f]
    if sku_f is not None:
        vals = [a for a in vals if a["replacement_sku_id"] == sku_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(a) for a in page], limit, offset, total)


@bp.route("/advanced-exchanges/<aid>", methods=["GET"])
def get_advanced_exchange(aid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster", "LogisticsAgent"})
    ax = get_or_404(db.advanced_exchanges, aid)
    return ok(serialize(ax), 200)


@bp.route("/advanced-exchanges/<aid>/ship", methods=["POST"])
def ship_exchange(aid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ax = get_or_404(db.advanced_exchanges, aid)
    if ax["status"] != "RESERVED":
        errors.fail(errors.ERR_INVALID_STATE, "Exchange not RESERVED")
    claim = db.claims[ax["claim_id"]]
    if claim["status"] != "ROUTED_REPLACE":
        errors.fail(errors.ERR_INVALID_STATE, "Parent claim not ROUTED_REPLACE")
    b = body()
    expected = require_int(b, "expected_claim_version")
    if expected != claim["version"]:
        errors.fail(errors.ERR_STALE_CLAIM_VERSION, "Stale claim version")
    ax["status"] = "SHIPPED"
    ax["return_due_at"] = clock.now() + timedelta(days=calc.RETURN_WINDOW_DAYS)
    touch(ax)
    return ok(serialize(ax), 200)


@bp.route("/advanced-exchanges/<aid>/deliver", methods=["POST"])
def deliver_exchange(aid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ax = get_or_404(db.advanced_exchanges, aid)
    if ax["status"] != "SHIPPED":
        errors.fail(errors.ERR_INVALID_STATE, "Exchange not SHIPPED")
    ax["status"] = "DELIVERED"
    touch(ax)
    return ok(serialize(ax), 200)


@bp.route("/advanced-exchanges/<aid>/close", methods=["POST"])
def close_exchange(aid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ax = get_or_404(db.advanced_exchanges, aid)
    if ax["status"] != "DELIVERED":
        errors.fail(errors.ERR_INVALID_STATE, "Exchange not DELIVERED")
    # precondition: a TradeIn exists in CREDITED or RECYCLED for this exchange
    has_terminal_tradein = any(
        t["advanced_exchange_id"] == ax["id"] and t["status"] in ("CREDITED", "RECYCLED")
        for t in db.trade_ins.values()
    )
    if not has_terminal_tradein:
        errors.fail(errors.ERR_INVALID_STATE, "Requires a CREDITED or RECYCLED trade-in")
    ax["status"] = "CLOSED"
    touch(ax)
    claim = db.claims[ax["claim_id"]]
    claim["status"] = "FULFILLED"
    touch(claim)
    enr = db.enrollments[claim["enrollment_id"]]
    if enr["open_claim_id"] == claim["id"]:
        enr["open_claim_id"] = None
        touch(enr)
    return ok(serialize(ax), 200)


@bp.route("/advanced-exchanges/<aid>/cancel", methods=["POST"])
def cancel_exchange(aid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ax = get_or_404(db.advanced_exchanges, aid)
    if ax["status"] != "RESERVED":
        errors.fail(errors.ERR_INVALID_STATE, "Exchange not RESERVED")
    ax["status"] = "CANCELLED"
    sku = db.replacement_skus[ax["replacement_sku_id"]]
    sku["stock_on_hand"] += 1
    touch(ax)
    return ok(serialize(ax), 200)


# ---------------- Trade-ins ----------------
VALID_GRADES = {"A", "B", "C", "EWASTE"}


@bp.route("/trade-ins", methods=["POST"])
def create_tradein():
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    b = body()
    ax_id = require_str(b, "advanced_exchange_id")
    grade = b.get("condition_grade")
    if grade not in VALID_GRADES:
        errors.fail(errors.ERR_VALIDATION, "condition_grade invalid")
    ax = get_or_404(db.advanced_exchanges, ax_id)
    tid = new_id()
    ti = {
        "id": tid,
        "advanced_exchange_id": ax_id,
        "condition_grade": grade,
        "credit_cents": 0,
        "status": "RECEIVED",
        "_seq": db.next_seq(),
    }
    ti.update(base_system_fields(versioned=True))
    db.trade_ins[tid] = ti
    return ok(serialize(ti), 201)


@bp.route("/trade-ins", methods=["GET"])
def list_tradeins():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "LogisticsAgent"})
    limit, offset = parse_pagination()
    vals = list(db.trade_ins.values())
    ax_f = request.args.get("advanced_exchange_id")
    if ax_f is not None:
        vals = [t for t in vals if t["advanced_exchange_id"] == ax_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(t) for t in page], limit, offset, total)


@bp.route("/trade-ins/<tid>", methods=["GET"])
def get_tradein(tid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "LogisticsAgent"})
    ti = get_or_404(db.trade_ins, tid)
    return ok(serialize(ti), 200)


def _tradein_basis(ti):
    """Depreciated value pre-cap, recomputed at grade-time clock."""
    ax = db.advanced_exchanges[ti["advanced_exchange_id"]]
    claim = db.claims[ax["claim_id"]]
    enr = db.enrollments[claim["enrollment_id"]]
    sku = db.replacement_skus[enr["replacement_sku_id"]]
    return calc.depreciated_value(sku, enr["device_purchase_date"], clock.now())


@bp.route("/trade-ins/<tid>/grade", methods=["POST"])
def grade_tradein(tid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ti = get_or_404(db.trade_ins, tid)
    if ti["status"] != "RECEIVED":
        errors.fail(errors.ERR_INVALID_STATE, "TradeIn not RECEIVED")
    ax = db.advanced_exchanges[ti["advanced_exchange_id"]]
    if ax["status"] not in ("SHIPPED", "DELIVERED", "RETURN_DUE"):
        errors.fail(errors.ERR_INVALID_STATE, "Parent exchange not in a gradeable state")
    base = _tradein_basis(ti)
    ti["credit_cents"] = calc.tradein_credit(base, ti["condition_grade"])
    ti["status"] = "GRADED"
    touch(ti)
    return ok(serialize(ti), 200)


@bp.route("/trade-ins/<tid>/credit", methods=["POST"])
def credit_tradein(tid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ti = get_or_404(db.trade_ins, tid)
    if ti["status"] != "GRADED":
        errors.fail(errors.ERR_INVALID_STATE, "TradeIn not GRADED")
    if ti["condition_grade"] == "EWASTE":
        errors.fail(errors.ERR_GRADE_PATH_MISMATCH, "Cannot credit an EWASTE trade-in")
    ti["status"] = "CREDITED"
    ax = db.advanced_exchanges[ti["advanced_exchange_id"]]
    if ax["status"] == "RETURN_DUE":
        ax["nonreturn_fee_cents"] = 0
        ax["status"] = "DELIVERED"
        touch(ax)
    touch(ti)
    return ok(serialize(ti), 200)


@bp.route("/trade-ins/<tid>/recycle", methods=["POST"])
def recycle_tradein(tid):
    _, role = require_auth()
    require_role(role, {"LogisticsAgent"})
    ti = get_or_404(db.trade_ins, tid)
    if ti["status"] != "GRADED":
        errors.fail(errors.ERR_INVALID_STATE, "TradeIn not GRADED")
    if ti["condition_grade"] != "EWASTE":
        errors.fail(errors.ERR_GRADE_PATH_MISMATCH, "Can only recycle EWASTE trade-in")
    ti["status"] = "RECYCLED"
    touch(ti)
    return ok(serialize(ti), 200)


# ---------------- Clock / sweeps ----------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    target = b.get("to_iso8601")
    if target is None or not isinstance(target, str):
        errors.fail(errors.ERR_VALIDATION, "to_iso8601 required")
    try:
        dt = parse_iso(target)
    except ValueError:
        errors.fail(errors.ERR_VALIDATION, "to_iso8601 invalid")
    clock.set(dt)
    return ok({"current_utc": to_iso(clock.now())}, 200)


@bp.route("/_clock/run_return_sweep", methods=["POST"])
def run_return_sweep():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    swept = []
    for ax in list(db.advanced_exchanges.values()):
        if ax["status"] != "DELIVERED":
            continue
        if ax["return_due_at"] is None or clock.now() <= ax["return_due_at"]:
            continue
        has_tradein = any(t["advanced_exchange_id"] == ax["id"] for t in db.trade_ins.values())
        if has_tradein:
            continue
        claim = db.claims[ax["claim_id"]]
        enr = db.enrollments[claim["enrollment_id"]]
        sku = db.replacement_skus[enr["replacement_sku_id"]]
        ax["status"] = "RETURN_DUE"
        ax["nonreturn_fee_cents"] = calc.nonreturn_fee(sku)
        touch(ax)
        swept.append(ax["id"])
    return ok({"swept_exchange_ids": swept}, 200)
