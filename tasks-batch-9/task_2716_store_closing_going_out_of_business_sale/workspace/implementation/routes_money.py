"""The money half of the service: expenses, lease disposition and settlement."""

from flask import Blueprint

import auth
import calc
import clock
import db
import helpers
import response
import serializers
import shape
from errors import ApiError

bp = Blueprint("money", __name__)


# ------------------------------------------------------------ expense items

@bp.post("/engagements/<engagement_id>/expense-items")
def create_expense_item(engagement_id):
    user_id, role = auth.begin(("LiquidationConsultant", "StoreManager"))
    body = shape.json_body()
    store_id = shape.field_str(body, "store_id", required=False, default=None)
    category = shape.field_enum(body, "expense_category", calc.EXPENSE_CATEGORIES)
    amount_cents = shape.field_int(body, "amount_cents", minimum=1)
    incurred_date = shape.field_date(body, "incurred_date")
    if store_id is not None:
        auth.scope_store(user_id, role, store_id)

    engagement = helpers.require("engagements", engagement_id)
    store = None
    if store_id is not None:
        store = helpers.require("stores", store_id)
    helpers.engagement_money_open(engagement)
    helpers.deny_frozen(engagement)

    row = db.insert(
        "expense_items",
        {
            "engagement_id": engagement["id"],
            "store_id": store["id"] if store is not None else None,
            "expense_category": category,
            "amount_cents": amount_cents,
            "incurred_date": incurred_date.isoformat(),
            "expense_status": "SUBMITTED",
            "liquidator_share_cents": 0,
            "retailer_share_cents": 0,
            "auto_generated": False,
            "submitted_by_user_id": user_id,
            "decided_by_user_id": None,
        },
    )
    return response.ok(serializers.expense_item(row), 201)


@bp.get("/engagements/<engagement_id>/expense-items")
def list_engagement_expense_items(engagement_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    limit, offset = shape.pagination()
    expense_status = shape.query_enum("expense_status", calc.EXPENSE_STATUSES)
    store_id = shape.query_str("store_id")
    engagement = helpers.require("engagements", engagement_id)
    rows = db.expense_items_of_engagement(engagement["id"])
    if expense_status is not None:
        rows = [r for r in rows if r["expense_status"] == expense_status]
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    return helpers.paginate(rows, serializers.expense_item, limit, offset)


@bp.get("/expense-items/<row_id>")
def read_expense_item(row_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    row = helpers.require("expense_items", row_id)
    return response.ok(serializers.expense_item(row))


@bp.post("/expense-items/<row_id>/decision")
def decide_expense_item(row_id):
    user_id, _role = auth.begin(("RetailerController",))
    item = db.get("expense_items", row_id)
    auth.deny_self_decision(user_id, item, "submitted_by_user_id")
    body = shape.json_body()
    action = shape.field_enum(body, "action", ("APPROVE", "VOID"))
    shape.field_str(body, "decision_note", required=False, default=None)
    if item is None:
        raise ApiError("ERR_EXPENSE_ITEM_NOT_FOUND")

    engagement = db.get("engagements", item["engagement_id"])
    if action == "APPROVE":
        if item["expense_status"] != "SUBMITTED":
            raise ApiError("ERR_EXPENSE_STATE_INVALID")
        if engagement is not None:
            helpers.engagement_money_open(engagement)
        item["expense_status"] = "APPROVED"
        item["decided_by_user_id"] = user_id
        liquidator, retailer = calc.expense_responsibility_split(
            engagement, item["amount_cents"]
        )
        item["liquidator_share_cents"] = liquidator
        item["retailer_share_cents"] = retailer
    else:
        if item["expense_status"] not in ("SUBMITTED", "APPROVED"):
            raise ApiError("ERR_EXPENSE_STATE_INVALID")
        item["expense_status"] = "VOIDED"
        item["decided_by_user_id"] = user_id
        item["liquidator_share_cents"] = 0
        item["retailer_share_cents"] = 0
    db.touch(item)

    if engagement is not None:
        calc.recompute_engagement(engagement)
        db.touch(engagement)
    return response.ok(serializers.expense_item(item))


# -------------------------------------------------------- lease dispositions

@bp.get("/lease-dispositions/<row_id>")
def read_lease(row_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    row = helpers.require("leases", row_id)
    return response.ok(serializers.lease(row))


@bp.post("/lease-dispositions/<row_id>/offer")
def send_offer(row_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    offered = shape.field_int(body, "offered_surrender_payment_cents", minimum=0)
    lease = helpers.require("leases", row_id)
    if lease["disposition_status"] not in ("DRAFT", "LANDLORD_COUNTERED"):
        raise ApiError("ERR_LEASE_STATE_INVALID")
    if lease["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_MAX_NEGOTIATION_ROUNDS")

    lease["disposition_status"] = "OFFER_SENT"
    lease["negotiation_round"] += 1
    lease["offered_surrender_payment_cents"] = offered
    db.touch(lease)
    return response.ok(serializers.lease(lease))


@bp.post("/lease-dispositions/<row_id>/landlord-response")
def landlord_response(row_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    answer = shape.field_enum(body, "response", ("COUNTER", "ACCEPT", "REJECT"))
    counter = shape.field_int(
        body, "landlord_counter_amount_cents", required=False, default=None, minimum=0
    )
    lease = helpers.require("leases", row_id)
    if lease["disposition_status"] != "OFFER_SENT":
        raise ApiError("ERR_LEASE_STATE_INVALID")

    if answer == "COUNTER":
        lease["disposition_status"] = "LANDLORD_COUNTERED"
        lease["landlord_counter_amount_cents"] = counter
    elif answer == "ACCEPT":
        lease["disposition_status"] = "AGREED"
        lease["agreed_surrender_payment_cents"] = lease["offered_surrender_payment_cents"]
        lease["landlord_agreed_date"] = clock.today().isoformat()
    else:
        lease["disposition_status"] = "REJECTED_FINAL"
    db.touch(lease)
    return response.ok(serializers.lease(lease))


@bp.post("/lease-dispositions/<row_id>/surrender")
def surrender_lease(row_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    fixture_price = shape.field_int(body, "fixture_sale_price_cents", minimum=0)
    reserve_waived = shape.field_bool(
        body, "reserve_waived", required=False, default=False
    )
    lease = helpers.require("leases", row_id)
    if lease["disposition_status"] != "AGREED":
        raise ApiError("ERR_LEASE_STATE_INVALID")
    store = db.get("stores", lease["store_id"])
    if store is None or store["store_status"] != "CLOSED":
        raise ApiError("ERR_STORE_NOT_SELLING")

    today = clock.today()
    jurisdiction = helpers.jurisdiction_of_store(store)
    notice_days = jurisdiction["surrender_notice_days"] if jurisdiction else 0
    agreed = calc.as_date(lease["landlord_agreed_date"])
    if agreed is not None and (today - agreed).days < notice_days:
        raise ApiError("ERR_SURRENDER_NOTICE_SHORT")
    if fixture_price < lease["fixture_reserve_price_cents"] and reserve_waived is not True:
        raise ApiError("ERR_FIXTURE_BELOW_RESERVE")

    deadline = calc.as_date(lease["surrender_deadline_date"])
    holdover_days = (today - deadline).days if deadline is not None else 0
    if holdover_days < 0:
        holdover_days = 0
    penalty = calc.holdover_penalty(lease, holdover_days)

    lease["fixture_sale_price_cents"] = fixture_price
    lease["holdover_days"] = holdover_days
    lease["holdover_penalty_cents"] = penalty
    lease.update(calc.lease_surrender_waterfall(lease, penalty, fixture_price))
    lease["disposition_status"] = "SURRENDERED"
    lease["surrendered_at"] = clock.iso_now()
    db.touch(lease)

    store["store_status"] = "SURRENDERED"
    db.touch(store)
    return response.ok(serializers.lease(lease))


# --------------------------------------------------------------- settlements

def _blank_settlement(engagement_id, basis):
    return {
        "engagement_id": engagement_id,
        "settlement_basis": basis,
        "settlement_status": "DRAFT",
        "gross_recovery_cents": None,
        "original_net_sales_cents": None,
        "recovery_ratio": None,
        "fee_rate": None,
        "liquidator_fee_cents": None,
        "guaranty_amount_cents": None,
        "expense_total_cents": None,
        "liquidator_expense_cents": None,
        "retailer_expense_cents": None,
        "retailer_proceeds_cents": None,
        "liquidator_proceeds_cents": None,
        "retention_accrual_cents": None,
        "dispute_reason": None,
        "dispute_round": 0,
        "computed_at": None,
        "proposed_by_user_id": None,
    }


@bp.post("/engagements/<engagement_id>/settlements")
def create_settlement(engagement_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    basis = shape.field_enum(body, "settlement_basis", calc.SETTLEMENT_BASES)
    expected_version = shape.field_int(body, "expected_engagement_version", minimum=0)
    supersede_open = shape.field_bool(
        body, "supersede_open", required=False, default=False
    )

    engagement = helpers.require("engagements", engagement_id)
    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")
    helpers.engagement_money_open(engagement)
    if basis == "FINAL" and engagement["engagement_status"] != "WIND_DOWN":
        raise ApiError("ERR_SETTLEMENT_BASIS_INVALID")

    incumbents = [
        s
        for s in db.settlements_of_engagement(engagement["id"])
        if s["settlement_status"] in ("DRAFT", "PROPOSED", "DISPUTED", "ACCEPTED")
    ]
    for incumbent in incumbents:
        if incumbent["settlement_status"] == "ACCEPTED" or supersede_open is not True:
            raise ApiError("ERR_SETTLEMENT_ALREADY_OPEN")
    for incumbent in incumbents:
        incumbent["settlement_status"] = "SUPERSEDED"
        db.touch(incumbent)

    row = db.insert("settlements", _blank_settlement(engagement["id"], basis))
    db.touch(engagement)
    return response.ok(serializers.settlement(row), 201)


@bp.get("/engagements/<engagement_id>/settlements")
def list_settlements(engagement_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    limit, offset = shape.pagination()
    settlement_status = shape.query_enum(
        "settlement_status", calc.SETTLEMENT_STATUSES
    )
    engagement = helpers.require("engagements", engagement_id)
    rows = db.settlements_of_engagement(engagement["id"])
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    return helpers.paginate(rows, serializers.settlement, limit, offset)


@bp.get("/settlements/<row_id>")
def read_settlement(row_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    row = helpers.require("settlements", row_id)
    return response.ok(serializers.settlement(row))


@bp.post("/settlements/<row_id>/propose")
def propose_settlement(row_id):
    user_id, _role = auth.begin(("LiquidationConsultant",))
    settlement = helpers.require("settlements", row_id)
    if settlement["settlement_status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    engagement = db.get("engagements", settlement["engagement_id"])
    if settlement["settlement_basis"] == "FINAL":
        if engagement is None or engagement["engagement_status"] != "WIND_DOWN":
            raise ApiError("ERR_SETTLEMENT_BASIS_INVALID")
        for store in db.stores_of_engagement(engagement["id"]):
            if store["store_status"] not in calc.CLOSED_STORE_STATUSES:
                raise ApiError("ERR_STORES_NOT_CLOSED")

    calc.compute_settlement_split(settlement, engagement)
    settlement["settlement_status"] = "PROPOSED"
    settlement["computed_at"] = clock.iso_now()
    settlement["proposed_by_user_id"] = user_id
    db.touch(settlement)
    return response.ok(serializers.settlement(settlement))


@bp.post("/settlements/<row_id>/response")
def respond_settlement(row_id):
    user_id, _role = auth.begin(("RetailerController",))
    settlement = db.get("settlements", row_id)
    auth.deny_self_decision(user_id, settlement, "proposed_by_user_id")
    body = shape.json_body()
    answer = shape.field_enum(body, "response", ("ACCEPT", "DISPUTE"))
    dispute_reason = shape.field_str(
        body, "dispute_reason", required=False, default=None
    )
    if settlement is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND")
    if settlement["settlement_status"] != "PROPOSED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")

    if answer == "ACCEPT":
        settlement["settlement_status"] = "ACCEPTED"
    else:
        settlement["settlement_status"] = "DISPUTED"
        settlement["dispute_reason"] = dispute_reason
        settlement["dispute_round"] += 1
    db.touch(settlement)
    return response.ok(serializers.settlement(settlement))


@bp.post("/settlements/<row_id>/finalize")
def finalize_settlement(row_id):
    auth.begin(("LiquidationConsultant",))
    settlement = helpers.require("settlements", row_id)
    if settlement["settlement_status"] != "ACCEPTED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    if settlement["settlement_basis"] != "FINAL":
        raise ApiError("ERR_SETTLEMENT_BASIS_INVALID")

    engagement = db.get("engagements", settlement["engagement_id"])
    stores = db.stores_of_engagement(engagement["id"]) if engagement else []
    for store in stores:
        if store["store_status"] not in calc.CLOSED_STORE_STATUSES:
            raise ApiError("ERR_STORES_NOT_CLOSED")
    for store in stores:
        disposed = False
        for lease in db.leases_of_store(store["id"]):
            if lease["disposition_status"] in ("SURRENDERED", "REJECTED_FINAL"):
                disposed = True
                break
        if not disposed:
            raise ApiError("ERR_LEASE_NOT_DISPOSED")
    items = db.expense_items_of_engagement(engagement["id"]) if engagement else []
    for item in items:
        if item["expense_status"] == "SUBMITTED":
            raise ApiError("ERR_LEASE_NOT_DISPOSED")

    settlement["settlement_status"] = "FINALIZED"
    db.touch(settlement)
    for item in items:
        if item["expense_status"] == "APPROVED":
            item["expense_status"] = "SETTLED"
            db.touch(item)
    if engagement is not None:
        engagement["engagement_status"] = "CLOSED"
        calc.recompute_engagement(engagement)
        db.touch(engagement)
    return response.ok(serializers.settlement(settlement))
