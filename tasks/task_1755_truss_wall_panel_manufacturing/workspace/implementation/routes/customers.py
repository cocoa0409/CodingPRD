"""CustomerAccount endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role, get_or_404, ALL_ROLES, INTERNAL_ROLES
from response import success, success_list
from services import serializers
from util import as_bool, as_enum, as_int, as_str, body, paginate

bp = Blueprint("customers", __name__)

DELIVERY_TERMS = {"FOB_PLANT", "DELIVERED"}


@bp.route("/plant/customer-accounts", methods=["POST"])
def create_customer():
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    data = body()
    company_name = as_str(data.get("company_name"), "company_name", required=True)
    credit_limit_cents = as_int(data.get("credit_limit_cents"), "credit_limit_cents", required=True)
    delivery_terms = as_enum(data.get("delivery_terms"), "delivery_terms", DELIVERY_TERMS, required=True)
    rec = db.new_record({
        "company_name": company_name,
        "credit_limit_cents": credit_limit_cents,
        "credit_hold": as_bool(data.get("credit_hold"), "credit_hold", default=False),
        "storage_free_days": as_int(data.get("storage_free_days"), "storage_free_days", default=2),
        "storage_daily_fee_cents": as_int(data.get("storage_daily_fee_cents"), "storage_daily_fee_cents", default=15000),
        "storage_fee_cap_cents": as_int(data.get("storage_fee_cap_cents"), "storage_fee_cap_cents", default=300000),
        "max_drops_per_day": as_int(data.get("max_drops_per_day"), "max_drops_per_day", default=2),
        "delivery_terms": delivery_terms,
    })
    db.customers[rec["id"]] = rec
    return success(serializers.customer(rec), status=201)


@bp.route("/plant/customer-accounts/<cid>", methods=["GET"])
def get_customer(cid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.customers, cid, "customer account")
    return success(serializers.customer(rec))


@bp.route("/plant/customer-accounts", methods=["GET"])
def list_customers():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.customers.values())
    raw = request.args.get("credit_hold")
    if raw is not None:
        records = [c for c in records if (raw.lower() == "true") == c["credit_hold"]]
    page, meta = paginate(records)
    return success_list([serializers.customer(c) for c in page], meta)


@bp.route("/plant/customer-accounts/<cid>", methods=["PATCH"])
def update_customer(cid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.customers, cid, "customer account")
    data = body()
    if "credit_hold" in data:
        rec["credit_hold"] = as_bool(data.get("credit_hold"), "credit_hold")
    if "credit_limit_cents" in data:
        rec["credit_limit_cents"] = as_int(data.get("credit_limit_cents"), "credit_limit_cents")
    if "storage_free_days" in data:
        rec["storage_free_days"] = as_int(data.get("storage_free_days"), "storage_free_days")
    if "storage_daily_fee_cents" in data:
        rec["storage_daily_fee_cents"] = as_int(data.get("storage_daily_fee_cents"), "storage_daily_fee_cents")
    if "storage_fee_cap_cents" in data:
        rec["storage_fee_cap_cents"] = as_int(data.get("storage_fee_cap_cents"), "storage_fee_cap_cents")
    if "max_drops_per_day" in data:
        rec["max_drops_per_day"] = as_int(data.get("max_drops_per_day"), "max_drops_per_day")
    db.touch(rec)
    # Posture of every job of this customer is derived; reads recompute it.
    return success(serializers.customer(rec))
