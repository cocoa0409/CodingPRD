"""Customers, Skus, TuneUpTiers — catalog & intake (PRD §3.1, §3.2)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok, created, list_ok
import helpers as h
import services as svc

bp = Blueprint("catalog", __name__)

CATEGORIES = {"BIKE", "PART", "ACCESSORY"}
WARRANTY_CLASSES = {"NONE", "COMPONENT", "FRAME_AND_COMPONENT"}
TIER_CODES = {"BASIC", "STANDARD", "PREMIUM"}


# ---------------- Customers ----------------
@bp.route("/shop/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ShopManager"])
    body = h.get_body()
    with db.LOCK:
        full_name = h.require_str(body, "full_name")
        email = h.require_email(body, "email")
        # priority 7: case-insensitive email uniqueness
        for c in db.customers.values():
            if c["email"].lower() == email.lower():
                raise ApiError("ERR_DUPLICATE_EMAIL", "Email already in use.")
        rec = {
            "full_name": full_name,
            "email": email,
            "store_credit_cents": 0,
            "open_recall_count": 0,
        }
        h.stamp_create(rec)
        db.customers[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/customers/<cid>", methods=["GET"])
def read_customer(cid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.customers, cid)
        if role == "Customer":
            # ownership read of own resource
            pass
        svc.customer_open_recall_count(rec)
        return ok(h.public(rec))


@bp.route("/shop/customers", methods=["GET"])
def list_customers():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        for c in db.customers.values():
            svc.customer_open_recall_count(c)
        items, limit, offset, total = h.paginate(list(db.customers.values()))
        return list_ok(items, limit, offset, total)


# ---------------- Skus ----------------
@bp.route("/shop/skus", methods=["POST"])
def create_sku():
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    body = h.get_body()
    with db.LOCK:
        name = h.require_str(body, "name")
        category = h.require_enum(body, "category", CATEGORIES)
        list_price = h.require_int(body, "list_price_cents", minimum=1)
        on_hand = h.optional_int(body, "on_hand", default=0, minimum=0)
        warranty_class = h.optional_enum(body, "warranty_class", WARRANTY_CLASSES, default="NONE")
        is_serialized = h.require_bool(body, "is_serialized", default=False)
        rec = {
            "name": name,
            "category": category,
            "list_price_cents": list_price,
            "on_hand": on_hand,
            "reserved": 0,
            "available": on_hand,
            "warranty_class": warranty_class,
            "is_serialized": is_serialized,
        }
        h.stamp_create(rec)
        db.skus[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/skus/<sid>", methods=["GET"])
def read_sku(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.skus, sid)
        svc.reconcile_sku(rec)
        return ok(h.public(rec))


@bp.route("/shop/skus", methods=["GET"])
def list_skus():
    from flask import request
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        category = request.args.get("category")
        recs = list(db.skus.values())
        if category is not None:
            recs = [s for s in recs if s["category"] == category]
        for s in recs:
            svc.reconcile_sku(s)
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/skus/<sid>/restock", methods=["POST"])
def restock_sku(sid):
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    body = h.get_body()
    with db.LOCK:
        rec = h.must_exist(db.skus, sid)
        units = h.require_int(body, "units", minimum=1)
        rec["on_hand"] += units
        h.touch(rec)
        svc.reconcile_sku(rec)
        return ok(h.public(rec))


@bp.route("/shop/skus/<sid>/reservations", methods=["GET"])
def list_sku_reservations(sid):
    from flask import request
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        h.must_exist(db.skus, sid)
        status = request.args.get("status")
        recs = [r for r in db.reservations.values() if r["sku_id"] == sid]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/skus/<sid>/recalls", methods=["GET"])
def list_sku_recalls(sid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        h.must_exist(db.skus, sid)
        recs = [r for r in db.recall_notices.values() if r["sku_id"] == sid]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- TuneUpTiers ----------------
@bp.route("/shop/tune-up-tiers", methods=["POST"])
def create_tier():
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    body = h.get_body()
    with db.LOCK:
        code = h.require_enum(body, "code", TIER_CODES)
        base_labor = h.require_int(body, "base_labor_cents", minimum=0)
        turnaround = h.require_int(body, "turnaround_hours", minimum=1)
        rush = h.optional_int(body, "rush_multiplier_bps", default=5000, minimum=0)
        rec = {
            "code": code,
            "base_labor_cents": base_labor,
            "turnaround_hours": turnaround,
            "rush_multiplier_bps": rush,
        }
        h.stamp_create(rec)
        db.tune_up_tiers[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/tune-up-tiers/<tid>", methods=["GET"])
def read_tier(tid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.tune_up_tiers, tid)
        return ok(h.public(rec))


@bp.route("/shop/tune-up-tiers", methods=["GET"])
def list_tiers():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        items, limit, offset, total = h.paginate(list(db.tune_up_tiers.values()))
        return list_ok(items, limit, offset, total)
