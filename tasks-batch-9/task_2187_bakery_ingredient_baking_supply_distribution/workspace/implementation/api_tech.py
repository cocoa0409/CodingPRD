"""Formulation support engagements and fee attachment (PRD §3.11)."""
from flask import Blueprint

import calc
import envelope
import serialize
import store
import validate as v
from auth import authenticate
from common import fk_lookup, path_lookup
from errors import fail
from store import D

bp = Blueprint("tech", __name__)

ENGAGEMENT_STATES = ("OPEN", "BILLABLE", "ATTACHED", "WAIVED")
READ_ROLES = ("TechnicalSpecialist", "AccountManager", "PricingController",
              "CustomerBuyer", "PlatformAdmin")


def _hours(value):
    return store.round_half_up(D(value), 1)


@bp.post("/tech-engagements")
def create_engagement():
    actor = authenticate(("TechnicalSpecialist",))
    body = v.body()
    customer_id = v.string(body, "customer_id", min_len=1)
    product_id = v.string(body, "product_id", min_len=1)
    fk_lookup("customers", customer_id)
    fk_lookup("products", product_id)
    rec = store.base_record()
    rec.update({
        "customer_id": customer_id,
        "product_id": product_id,
        "order_id": None,
        "status": "OPEN",
        "hours_logged": D("0.0"),
        "attach_fee_cents": 0,
        "assigned_specialist_user_id": actor.user_id,
    })
    store.insert("engagements", rec)
    return envelope.created(serialize.engagement(rec))


@bp.get("/tech-engagements")
def list_engagements():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    customer_id = v.q_str("customer_id")
    product_id = v.q_str("product_id")
    order_id = v.q_str("order_id")
    status = v.q_enum("status", ENGAGEMENT_STATES)
    rows = [e for e in store.all_of("engagements")
            if (customer_id is None or e["customer_id"] == customer_id)
            and (product_id is None or e["product_id"] == product_id)
            and (order_id is None or e["order_id"] == order_id)
            and (status is None or e["status"] == status)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.engagement)
    return envelope.listing(data, limit, offset, total)


@bp.get("/tech-engagements/<eid>")
def read_engagement(eid):
    authenticate(READ_ROLES)
    return envelope.ok(serialize.engagement(path_lookup("engagements", eid)))


@bp.post("/tech-engagements/<eid>/hours")
def log_hours(eid):
    authenticate(("TechnicalSpecialist",))
    body = v.body()
    hours = v.number(body, "hours", exclusive_min=0)
    v.string(body, "work_note", required=False, max_len=500)
    rec = path_lookup("engagements", eid)
    if rec["status"] not in ("OPEN", "BILLABLE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Bench time cannot be posted to a %s engagement" % rec["status"])
    rec["hours_logged"] = _hours(D(rec["hours_logged"]) + D(hours))
    customer = store.get("customers", rec["customer_id"])
    tier = customer["risk_tier"] if customer is not None else "GREEN"
    if rec["status"] == "OPEN" and D(rec["hours_logged"]) >= calc.BILLABLE_HOURS_THRESHOLD:
        rec["status"] = "BILLABLE"
        rec["attach_fee_cents"] = calc.attach_fee(rec["hours_logged"], tier)
    elif rec["status"] == "BILLABLE":
        rec["attach_fee_cents"] = calc.attach_fee(rec["hours_logged"], tier)
    store.bump(rec)
    return envelope.ok(serialize.engagement(rec))


@bp.post("/tech-engagements/<eid>/attach")
def attach_engagement(eid):
    actor = authenticate(("TechnicalSpecialist",))
    body = v.body()
    order_id = v.string(body, "order_id", min_len=1)
    rec = path_lookup("engagements", eid)
    order = fk_lookup("orders", order_id)
    if rec["status"] != "BILLABLE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A %s engagement cannot be attached" % rec["status"])
    if order["pricing_status"] != "PROVISIONAL":
        fail("ERR_ORDER_DIMENSION_GATE",
             "A support fee may only be attached to a PROVISIONAL order")
    if actor.user_id != rec["assigned_specialist_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Only the assigned specialist may attach the engagement")
    if rec["customer_id"] != order["customer_id"]:
        fail("ERR_ENTITY_LINK_MISMATCH",
             "The engagement and the order belong to different bakeries")
    rec["order_id"] = order["id"]
    rec["status"] = "ATTACHED"
    store.bump(rec)
    order["tech_attach_fee_cents"] = rec["attach_fee_cents"]
    per_line, totals = calc.price_order(order, "provisional_order_date")
    calc.apply_pricing(order, per_line, totals)
    store.bump(order)
    calc.recompute_open_exposure(store.get("customers", order["customer_id"]))
    return envelope.ok(serialize.engagement(rec))


@bp.post("/tech-engagements/<eid>/waive")
def waive_engagement(eid):
    authenticate(("AccountManager",))
    body = v.body()
    v.string(body, "waiver_reason", min_len=1, max_len=200)
    rec = path_lookup("engagements", eid)
    if rec["status"] not in ("OPEN", "BILLABLE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A %s engagement cannot be waived" % rec["status"])
    if rec["order_id"] is not None:
        fail("ERR_INVALID_STATE_TRANSITION",
             "An engagement already billed onto an order cannot be waived")
    rec["status"] = "WAIVED"
    rec["attach_fee_cents"] = 0
    store.bump(rec)
    return envelope.ok(serialize.engagement(rec))
