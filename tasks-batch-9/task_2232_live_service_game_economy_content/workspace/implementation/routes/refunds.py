"""Refund requests: player submission, compliance decision, compensating execution (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate, require_owner
from response import list_response, object_response, touch
from services import calc, cascades, ledger

bp = Blueprint("refunds", __name__)

READ_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_PLAYER,
)
LIST_ROLES = (config.ROLE_LIVEOPS_COMMANDER, config.ROLE_COMPLIANCE_OFFICER)

LIVE_REFUND_STATUSES = ("SUBMITTED", "APPROVED", "EXECUTED")


@bp.post("/refund-requests")
def create_refund_request():
    user_id, role = authenticate(config.ROLE_PLAYER)
    payload = v.body()
    purchase = resolve.body_fk(payload, "purchase_id", db.db.purchases, "ERR_PURCHASE_NOT_FOUND")
    v.req_string(payload, "purchase_id")
    reason_code = v.req_enum(payload, "reason_code", config.REFUND_REASON_CODES)

    require_owner(role, user_id, purchase["player_id"])

    if purchase["status"] != "SETTLED":
        fail("ERR_PURCHASE_INVALID_STATE", "Only a SETTLED purchase can be refunded.")
    deadline = purchase["settled_at"] + timedelta(days=config.REFUND_WINDOW_DAYS)
    if db.now() > deadline:
        fail("ERR_REFUND_WINDOW_EXPIRED", "The 14-day refund window has expired.")
    for existing in db.db.refunds.values():
        if existing["purchase_id"] == purchase["id"] and existing["status"] in LIVE_REFUND_STATUSES:
            fail("ERR_REFUND_ALREADY_REQUESTED", "A live refund request already exists.")

    record = db.insert(
        db.db.refunds,
        {
            "purchase_id": purchase["id"],
            "reason_code": reason_code,
            "status": "SUBMITTED",
            "consumed_ratio_bp": 0,
            "refund_base_minor": 0,
            "restock_fee_minor": 0,
            "refund_amount_minor": 0,
            "goodwill_credit_minor": 0,
            "decision_note": None,
            "decided_by_user_id": None,
            "executed_at": None,
        },
    )
    return object_response(serialize(record), 201)


@bp.get("/refund-requests/<request_id>")
def read_refund_request(request_id):
    user_id, role = authenticate(*READ_ROLES)
    record = resolve.refund_request(request_id)
    purchase = db.db.purchases.get(record["purchase_id"])
    owner_id = purchase["player_id"] if purchase is not None else None
    require_owner(role, user_id, owner_id)
    return object_response(serialize(record))


@bp.get("/refund-requests")
def list_refund_requests():
    authenticate(*LIST_ROLES)
    purchase_id = request.args.get("purchase_id")
    status = v.query_enum("status", config.REFUND_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.db.refunds.values())
    if purchase_id is not None:
        rows = [r for r in rows if r["purchase_id"] == purchase_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    records = [serialize(r) for r in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/refund-requests/<request_id>/decision")
def decide_refund_request(request_id):
    user_id, _role = authenticate(config.ROLE_COMPLIANCE_OFFICER)
    record = resolve.refund_request(request_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("APPROVE", "DENY"))
    decision_note = v.opt_string(payload, "decision_note")

    if record["status"] != "SUBMITTED":
        fail("ERR_REFUND_INVALID_STATE", "Only a SUBMITTED request can be decided.")
    purchase = db.db.purchases.get(record["purchase_id"])

    if decision == "DENY":
        record["status"] = "DENIED"
    else:
        if purchase is None or purchase["status"] != "SETTLED":
            fail("ERR_PURCHASE_INVALID_STATE", "The underlying purchase is no longer SETTLED.")
        player = db.db.players.get(purchase["player_id"])
        pinned = calc.refund_settlement(purchase, player)
        record.update(pinned)
        record["status"] = "APPROVED"
    record["decided_by_user_id"] = user_id
    record["decision_note"] = decision_note
    touch(record)
    return object_response(serialize(record))


@bp.post("/refund-requests/<request_id>/execute")
def execute_refund_request(request_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    record = resolve.refund_request(request_id)

    if record["status"] != "APPROVED":
        fail("ERR_REFUND_INVALID_STATE", "Only an APPROVED request can be executed.")
    purchase = db.db.purchases.get(record["purchase_id"])
    if purchase is None or purchase["status"] != "SETTLED":
        fail("ERR_PURCHASE_INVALID_STATE", "The underlying purchase is no longer SETTLED.")

    player = db.db.players.get(purchase["player_id"])
    offer = db.db.offers.get(purchase["offer_id"])
    season = db.db.seasons.get(offer["season_id"]) if offer is not None else None

    # Level 1/2/3 -- compensating ledger entries, account totals, season totals.
    originals = ledger.entries_for_purchase(purchase["id"], "PURCHASE_GRANT")
    remaining_consumption = purchase["granted_consumed_minor"]
    for original in originals:
        allocated = min(remaining_consumption, original["amount_minor"])
        remaining_consumption -= allocated
        reverse = max(0, original["amount_minor"] - allocated)
        if reverse == 0:
            continue
        account = db.db.accounts.get(original["currency_account_id"])
        if account is None:
            continue
        ledger.append_entry(
            account,
            "SINK",
            reverse,
            "REFUND_REVERSAL",
            original["season_id"],
            purchase_id=purchase["id"],
            reversal_of_entry_id=original["id"],
        )

    # Level 4 -- season revenue, purchase status, request status, player spend.
    if season is not None:
        season["settled_revenue_minor"] = max(
            0, season["settled_revenue_minor"] - purchase["price_paid_minor"]
        )
        touch(season)

    purchase["status"] = "REFUNDED"
    touch(purchase)

    record["status"] = "EXECUTED"
    record["executed_at"] = db.now()
    touch(record)

    if player is not None:
        cascades.reevaluate_spend_state(player, "REFUND")

    if record["goodwill_credit_minor"] > 0 and player is not None:
        soft_coin = None
        for account in ordered([a for a in db.db.accounts.values() if a["player_id"] == player["id"]]):
            if account["currency_code"] == "SOFT_COIN":
                soft_coin = account
                break
        if soft_coin is not None:
            ledger.append_entry(
                soft_coin,
                "FAUCET",
                record["goodwill_credit_minor"],
                "ADMIN_ADJUSTMENT",
                season["id"] if season is not None else None,
            )
    return object_response(serialize(record))
