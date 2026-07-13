"""Customers, the tier checkpoint and the points ledger."""
from flask import Blueprint, request

from db import base_record, db, public
from errors import ApiError
from middleware import (
    as_enum,
    as_int,
    as_str,
    authenticate,
    body,
    get_customer,
    get_ledger_entry,
    own_customer,
    page,
    pagination,
    required,
)
from response import created, ok, ok_list
from services.loyalty import append_ledger, tier_evaluation_checkpoint
from util import iso

bp = Blueprint("loyalty", __name__)

TIERS = ("INSIDER", "VIB", "ROUGE")


@bp.post("/customers")
def create_customer():
    authenticate("MerchandisingAdmin")
    payload = body()

    email = as_str(required(payload, "email"), "email")
    name = as_str(required(payload, "name"), "name")

    tier = payload.get("initial_tier")
    tier = as_enum(tier, "initial_tier", TIERS) if tier is not None else "INSIDER"

    initial_points = payload.get("initial_points")
    initial_points = as_int(initial_points, "initial_points", minimum=0) if initial_points is not None else 0

    initial_spend = payload.get("initial_qualifying_spend_cents")
    initial_spend = as_int(initial_spend, "initial_qualifying_spend_cents", minimum=0) if initial_spend is not None else 0

    customer = base_record()
    customer.update({
        "email": email,
        "name": name,
        "tier": tier,
        "points_balance": 0,
        "qualifying_spend_cents": initial_spend,
        "lifetime_spend_cents": 0,
        "cycle_started_at": iso(db.clock),
        "hygiene_strikes": 0,
        "return_privilege": "ACTIVE",
    })
    db.customers[customer["id"]] = customer

    # points are conserved from the very first instant: seed through the ledger
    if initial_points > 0:
        append_ledger(customer, "SEED", initial_points, None)

    return created(public(customer))


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    auth = authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    customer = get_customer(customer_id)
    own_customer(auth, customer["id"])
    return ok(public(customer))


@bp.post("/customers/<customer_id>/tier-checkpoint")
def tier_checkpoint(customer_id):
    authenticate("MerchandisingAdmin")
    customer = get_customer(customer_id)
    tier_evaluation_checkpoint(customer)
    return ok(public(customer))


@bp.get("/points-ledger/<entry_id>")
def read_ledger_entry(entry_id):
    auth = authenticate("MerchandisingAdmin", "Customer")
    entry = get_ledger_entry(entry_id)
    own_customer(auth, entry["customer_id"])
    return ok(public(entry))


@bp.get("/points-ledger")
def list_ledger():
    auth = authenticate("MerchandisingAdmin", "Customer")
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    order_id = request.args.get("order_id")

    if auth.is_customer:
        if customer_id and customer_id != auth.user_id:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "the ledger belongs to another customer")
        customer_id = auth.user_id

    records = list(db.ledger.values())
    if customer_id:
        records = [e for e in records if e["customer_id"] == customer_id]
    if order_id:
        records = [e for e in records if e["order_id"] == order_id]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)
