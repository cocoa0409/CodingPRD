"""Trade-ins, recalls, recall acks, clock (PRD §3.11)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok, created, list_ok
import helpers as h
import services as svc

bp = Blueprint("misc", __name__)

GRADES = {"A", "B", "C"}
APPLY_TO = {"STORE_CREDIT", "CASH"}
SEVERITIES = {"ADVISORY", "MANDATORY"}


# ---------------- TradeIn ----------------
@bp.route("/shop/trade-ins", methods=["POST"])
def create_tradein():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        description = h.require_str(body, "description")
        condition_grade = h.require_enum(body, "condition_grade", GRADES)
        appraised_value = h.require_int(body, "appraised_value_cents", minimum=0)
        apply_to = h.optional_enum(body, "apply_to", APPLY_TO, default="STORE_CREDIT")
        h.must_exist(db.customers, customer_id)
        rec = {
            "customer_id": customer_id,
            "description": description,
            "condition_grade": condition_grade,
            "appraised_value_cents": appraised_value,
            "offer_cents": 0,
            "apply_to": apply_to,
            "status": "APPRAISED",
        }
        h.stamp_create(rec)
        db.trade_ins[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/trade-ins/<tid>", methods=["GET"])
def read_tradein(tid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.trade_ins, tid)
        return ok(h.public(rec))


@bp.route("/shop/trade-ins", methods=["GET"])
def list_tradeins():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.trade_ins.values())
        v = request.args.get("customer_id")
        if v is not None:
            recs = [r for r in recs if r["customer_id"] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/trade-ins/<tid>/accept", methods=["POST"])
def accept_tradein(tid):
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.trade_ins, tid)
        if rec["status"] != "APPRAISED":
            raise ApiError("ERR_INVALID_STATE", "Accept requires APPRAISED.")
        svc.tradein_offer(rec)
        if rec["apply_to"] == "STORE_CREDIT" and rec["offer_cents"] > 0:
            customer = db.customers[rec["customer_id"]]
            customer["store_credit_cents"] += rec["offer_cents"]
            h.touch(customer)
        rec["status"] = "ACCEPTED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/trade-ins/<tid>/reject", methods=["POST"])
def reject_tradein(tid):
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.trade_ins, tid)
        if rec["status"] != "APPRAISED":
            raise ApiError("ERR_INVALID_STATE", "Reject requires APPRAISED.")
        rec["status"] = "REJECTED"
        h.touch(rec)
        return ok(h.public(rec))


# ---------------- RecallNotice ----------------
@bp.route("/shop/recall-notices", methods=["POST"])
def create_recall_notice():
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    body = h.get_body()
    with db.LOCK:
        sku_id = h.require_str(body, "sku_id")
        severity = h.require_enum(body, "severity", SEVERITIES)
        remedy = h.require_str(body, "remedy")
        h.must_exist(db.skus, sku_id)
        rec = {
            "sku_id": sku_id,
            "severity": severity,
            "remedy": remedy,
        }
        h.stamp_create(rec, ledger=True)
        db.recall_notices[rec["id"]] = rec
        # recompute open_recall_count for affected customers
        for c in db.customers.values():
            svc.customer_open_recall_count(c)
        return created(h.public(rec))


@bp.route("/shop/recall-notices/<rid>", methods=["GET"])
def read_recall_notice(rid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.recall_notices, rid)
        return ok(h.public(rec))


@bp.route("/shop/recall-notices", methods=["GET"])
def list_recall_notices():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        recs = list(db.recall_notices.values())
        v = request.args.get("sku_id")
        if v is not None:
            recs = [r for r in recs if r["sku_id"] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- RecallAck ----------------
@bp.route("/shop/recall-acks", methods=["POST"])
def create_recall_ack():
    _, role = authenticate()
    require_roles(role, ["Customer", "ServiceAdvisor", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        recall_id = h.require_str(body, "recall_id")
        customer_id = h.require_str(body, "customer_id")
        h.must_exist(db.recall_notices, recall_id)
        h.must_exist(db.customers, customer_id)
        # priority 19: at most once per (recall, customer)
        for ra in db.recall_acks.values():
            if ra["recall_id"] == recall_id and ra["customer_id"] == customer_id:
                raise ApiError("ERR_ALREADY_ACKNOWLEDGED", "Already acknowledged.")
        rec = {
            "recall_id": recall_id,
            "customer_id": customer_id,
        }
        h.stamp_create(rec, ledger=True)
        db.recall_acks[rec["id"]] = rec
        svc.customer_open_recall_count(db.customers[customer_id])
        return created(h.public(rec))


@bp.route("/shop/recall-acks/<rid>", methods=["GET"])
def read_recall_ack(rid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.recall_acks, rid)
        return ok(h.public(rec))


@bp.route("/shop/recall-acks", methods=["GET"])
def list_recall_acks():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        recs = list(db.recall_acks.values())
        for f in ("recall_id", "customer_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- Clock (test-driving) ----------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    body = h.get_body()
    with db.LOCK:
        to_iso = h.require_str(body, "to_iso8601")
        try:
            db._parse_iso(to_iso)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601.")
        db.set_clock(to_iso)
        return ok({})
