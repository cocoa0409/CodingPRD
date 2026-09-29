"""Offer ingestion, the sell-price build and the publish/suppress cycle (PRD 3.4)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("offers", __name__)

STATUSES = ("PENDING", "LIVE", "SUPPRESSED", "CLOSED", "SUPERSEDED")
CERTIFIED_LEVELS = ("PROVISIONAL", "CERTIFIED")


def _guard_horizon(travel_date):
    today = clock.today()
    low = today.isoformat()
    high = clock.plus_days(today, calc.MAX_HORIZON_DAYS).isoformat()
    if travel_date < low or travel_date > high:
        raise ApiError("ERR_TRAVEL_DATE_OUT_OF_RANGE")


@bp.post("/rate-plans/<plan_id>/offers")
def create_offer(plan_id):
    actor = auth.authenticate(("SupplierUser", "CommercialManager"))
    plan = common.find("rate_plans", plan_id)
    auth.require_supplier_scope(actor, plan["supplier_id"])
    data = validate.body()
    travel_date = validate.date_req(data, "travel_date")
    net_rate_cents = validate.int_req(data, "net_rate_cents", 1)
    allotment_total = validate.int_req(data, "allotment_total", 1)
    expected = validate.int_req(data, "expected_rate_plan_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION")
    common.guard_offboarded(common.plan_supplier(plan))
    _guard_horizon(travel_date)
    agreement = calc.active_agreement_for_date(plan["supplier_id"], travel_date)
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    for prior in cascade.offers_of_plan(plan["id"], ("PENDING", "LIVE", "SUPPRESSED")):
        if prior["travel_date"] != travel_date:
            continue
        if prior["allotment_held"] == 0 and prior["allotment_sold"] == 0:
            prior["status"] = "SUPERSEDED"
            touch(prior)
    fields = {
        "rate_plan_id": plan["id"],
        "travel_date": travel_date,
        "net_rate_cents": net_rate_cents,
        "allotment_total": allotment_total,
        "allotment_held": 0,
        "allotment_sold": 0,
        "allotment_remaining": allotment_total,
        "status": "PENDING",
        "suppression_reason": None,
    }
    fields.update(calc.price_offer(plan, agreement, travel_date, net_rate_cents))
    offer = store.new_row("offers", fields)
    touch(plan)
    return response.obj(offer, 201)


@bp.get("/offers/<offer_id>")
def read_offer(offer_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("offers", offer_id), 200)


@bp.get("/offers")
def list_offers():
    auth.authenticate(auth.ALL_ROLES)
    rate_plan_id = validate.filter_str("rate_plan_id")
    travel_date = validate.filter_date("travel_date")
    status = validate.filter_enum("status", STATUSES)
    rows = []
    for row in db["offers"].values():
        if rate_plan_id is not None and row["rate_plan_id"] != rate_plan_id:
            continue
        if travel_date is not None and row["travel_date"] != travel_date:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/offers/<offer_id>/publish")
def publish_offer(offer_id):
    actor = auth.authenticate(("SupplierUser", "CommercialManager"))
    offer = common.find("offers", offer_id)
    plan = common.offer_plan(offer)
    auth.require_supplier_scope(actor, plan["supplier_id"])
    data = validate.body()
    validate.str_opt(data, "note")
    supplier = common.plan_supplier(plan)
    common.guard_offboarded(supplier)
    if offer["status"] not in ("PENDING", "SUPPRESSED") or plan["status"] != "ACTIVE":
        raise ApiError("ERR_OFFER_NOT_PUBLISHABLE")
    if supplier["certification_level"] not in CERTIFIED_LEVELS \
            or supplier["visibility_status"] != "ACTIVE":
        raise ApiError("ERR_SUPPLIER_NOT_CERTIFIED")
    if calc.active_agreement_for_date(supplier["id"], offer["travel_date"]) is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    offer["status"] = "LIVE"
    offer["suppression_reason"] = None
    touch(offer)
    return response.obj(offer, 200)


@bp.post("/offers/<offer_id>/suppress")
def suppress_offer(offer_id):
    auth.authenticate(("ParityAnalyst", "ComplianceOfficer", "CommercialManager"))
    offer = common.find("offers", offer_id)
    data = validate.body()
    reason = validate.str_req(data, "suppression_reason")
    common.guard_offboarded(common.offer_supplier(offer))
    if offer["status"] != "LIVE":
        raise ApiError("ERR_OFFER_NOT_LIVE")
    cascade.suppress_offer(offer, reason)
    return response.obj(offer, 200)


@bp.post("/offers/<offer_id>/close-out")
def close_out(offer_id):
    actor = auth.authenticate(("SupplierUser", "CommercialManager"))
    offer = common.find("offers", offer_id)
    plan = common.offer_plan(offer)
    auth.require_supplier_scope(actor, plan["supplier_id"])
    data = validate.body()
    validate.str_opt(data, "note")
    common.guard_offboarded(common.plan_supplier(plan))
    if offer["status"] not in ("PENDING", "LIVE", "SUPPRESSED"):
        raise ApiError("ERR_OFFER_NOT_LIVE")
    if offer["status"] in ("LIVE", "SUPPRESSED") and offer["allotment_held"] != 0:
        raise ApiError("ERR_OFFER_NOT_LIVE",
                       "Inventory is currently held by a reservation.")
    offer["status"] = "CLOSED"
    touch(offer)
    return response.obj(offer, 200)
