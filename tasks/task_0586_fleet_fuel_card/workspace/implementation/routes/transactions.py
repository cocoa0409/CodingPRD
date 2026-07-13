"""Purchases: authorization, capture, settlement, void (PRD §3.4, §3.5)."""
from flask import Blueprint, g, request

import response
from db import base_record, db, touch
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, paginate, query_enum, req_enum,
                        req_int, req_num, req_str, require_roles)
from services import serialize
from services.cascade import void_transaction
from services.ledger import ledger, rebate_for
from services.mpg import all_vehicle_transactions
from services.store import (POSTING_STATUSES, PRODUCTS, account_of_transaction, card_transactions,
                            get_account, get_card, get_transaction, get_vehicle)
from util import dec, num, round_cents, round_half_up

bp = Blueprint("transactions", __name__)


def _covering_assignment(card_id, at):
    """The card's ACTIVE assignment whose half-open interval covers `at`."""
    for assignment in sorted(db.card_assignments.values(), key=lambda a: a["_seq"], reverse=True):
        if assignment["card_id"] != card_id or assignment["status"] != "ACTIVE":
            continue
        if assignment["_effective_from_dt"] > at:
            continue
        end = assignment["_effective_to_dt"]
        if end is not None and at >= end:
            continue
        return assignment
    return None


@bp.post("/transactions/authorize")
@require_roles("Merchant")
def authorize():
    data = body()
    card_id = req_str(data, "card_id")
    product = req_enum(data, "product", PRODUCTS)
    gallons = req_num(data, "gallons", exclusive_min=0)
    unit_price_cents = req_int(data, "unit_price_cents", exclusive_min=0)
    odometer = req_num(data, "odometer", minimum=0)
    jurisdiction = req_str(data, "jurisdiction")

    # 3. Existence.
    card = get_card(card_id)

    # 5. Transition state — the card must be ACTIVE.
    if card["status"] != "ACTIVE":
        raise err("ERR_CARD_NOT_ACTIVE")

    purchased_at_dt = db.clock.now()
    purchased_at = db.clock.now_iso()

    # 7. An ACTIVE assignment must cover purchased_at (resolves vehicle + driver).
    assignment = _covering_assignment(card_id, purchased_at_dt)
    if assignment is None:
        raise err("ERR_NO_ACTIVE_ASSIGNMENT")
    vehicle = get_vehicle(assignment["vehicle_id"])
    driver_id = assignment["driver_id"]

    # 6. The resolved vehicle must be in service.
    if vehicle["status"] in ("OUT_OF_SERVICE", "RETIRED"):
        raise err("ERR_VEHICLE_OUT_OF_SERVICE")

    # 8. Product control.
    if product not in card["allowed_products"]:
        raise err("ERR_PRODUCT_NOT_ALLOWED")

    # 9. Hours control — [allowed_start_hour, allowed_end_hour).
    hour = purchased_at_dt.hour
    if not (card["allowed_start_hour"] <= hour < card["allowed_end_hour"]):
        raise err("ERR_OUTSIDE_ALLOWED_HOURS")

    # 10. Per-transaction gallon control — equal is allowed, strictly greater is not.
    if dec(gallons) > dec(card["per_txn_gallon_limit"]):
        raise err("ERR_GALLON_LIMIT_EXCEEDED")

    gross_amount_cents = round_cents(dec(gallons) * dec(unit_price_cents))

    # 15. Daily spend control — this card's same-UTC-day held-and-settled spend.
    day = purchased_at_dt.date()
    same_day = sum(t["gross_amount_cents"] for t in card_transactions(card_id)
                   if t["posting_status"] in ("AUTHORIZED", "CAPTURED", "SETTLED")
                   and t["_purchased_at_dt"].date() == day)
    if same_day + gross_amount_cents > card["daily_dollar_limit_cents"]:
        raise err("ERR_DAILY_LIMIT_EXCEEDED")

    # 16. Account credit.
    account = get_account(card["fleet_account_id"])
    if ledger(account)["available_credit_cents"] < gross_amount_cents:
        raise err("ERR_CREDIT_EXCEEDED")

    # Fuel-economy snapshot: previous odometer on this vehicle, else starting_odometer.
    prior = all_vehicle_transactions(vehicle["id"])
    previous_odometer = dec(prior[-1]["odometer"]) if prior else dec(vehicle["starting_odometer"])
    segment_miles = dec(odometer) - previous_odometer
    mpg_snapshot = float(round_half_up(segment_miles / dec(gallons), 1))
    mpg_exception = bool(dec(mpg_snapshot) < dec(vehicle["expected_mpg_min"])
                         or dec(mpg_snapshot) > dec(vehicle["expected_mpg_max"]))

    record = base_record()
    record.update({
        "card_id": card_id,
        "vehicle_id": vehicle["id"],
        "driver_id": driver_id,
        "product": product,
        "gallons": gallons,
        "unit_price_cents": unit_price_cents,
        "odometer": odometer,
        "jurisdiction": jurisdiction,
        "gross_amount_cents": gross_amount_cents,
        "segment_miles": num(segment_miles),
        "mpg_snapshot": mpg_snapshot,
        "mpg_exception": mpg_exception,
        "purchased_at": purchased_at,
        "posting_status": "AUTHORIZED",
        "review_status": "CLEAN",
        "provisional_rebate_cents": 0,
        "final_rebate_cents": 0,
        "_purchased_at_dt": purchased_at_dt,
    })
    db.transactions[record["id"]] = record

    # Fraud engine: an over-tank fill still authorizes but is flagged for review.
    if dec(gallons) > dec(vehicle["tank_capacity_gallons"]):
        record["review_status"] = "FLAGGED"
        alert = base_record()
        alert.update({
            "transaction_id": record["id"],
            "card_id": card_id,
            "rule_code": "OVER_TANK_FILL",
            "status": "OPEN",
            "resolution_note": None,
        })
        db.fraud_alerts[alert["id"]] = alert

    return response.created(serialize.transaction(record))


@bp.get("/transactions/<transaction_id>")
@require_roles("Merchant", "FleetManager", "ProgramAdmin")
def fetch_transaction(transaction_id):
    txn = get_transaction(transaction_id)
    check_fleet(account_of_transaction(txn))
    return response.ok(serialize.transaction(txn))


@bp.get("/transactions")
@require_roles("Merchant", "FleetManager", "ProgramAdmin")
def list_transactions():
    card_filter = request.args.get("card_id")
    vehicle_filter = request.args.get("vehicle_id")
    driver_filter = request.args.get("driver_id")
    jurisdiction_filter = request.args.get("jurisdiction")
    posting_filter = query_enum("posting_status", POSTING_STATUSES)

    records = list(db.transactions.values())
    if is_fleet_manager():
        records = [t for t in records if account_of_transaction(t) == g.user_id]
    if card_filter is not None:
        records = [t for t in records if t["card_id"] == card_filter]
    if vehicle_filter is not None:
        records = [t for t in records if t["vehicle_id"] == vehicle_filter]
    if driver_filter is not None:
        records = [t for t in records if t["driver_id"] == driver_filter]
    if jurisdiction_filter is not None:
        records = [t for t in records if t["jurisdiction"] == jurisdiction_filter]
    if posting_filter is not None:
        records = [t for t in records if t["posting_status"] == posting_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.transaction(t) for t in page], limit, offset, total)


@bp.post("/transactions/<transaction_id>/capture")
@require_roles("Merchant")
def capture(transaction_id):
    txn = get_transaction(transaction_id)
    if txn["posting_status"] != "AUTHORIZED":
        raise err("ERR_INVALID_TXN_STATE", "Only an AUTHORIZED transaction can be captured.")

    account = get_account(account_of_transaction(txn))
    txn["posting_status"] = "CAPTURED"
    # month-to-date gallons now include this transaction (provisional variant)
    txn["provisional_rebate_cents"] = rebate_for(account, txn)
    touch(txn)
    return response.ok(serialize.transaction(txn))


@bp.post("/transactions/<transaction_id>/settle")
@require_roles("Merchant")
def settle(transaction_id):
    txn = get_transaction(transaction_id)
    if txn["posting_status"] != "CAPTURED":
        raise err("ERR_INVALID_TXN_STATE", "Only a CAPTURED transaction can be settled.")

    account = get_account(account_of_transaction(txn))
    txn["posting_status"] = "SETTLED"
    # whole-month total gallons re-rate the transaction (final variant); the hold
    # releases and the gross moves into settled_spend (both derived from status).
    txn["final_rebate_cents"] = rebate_for(account, txn)
    touch(txn)
    return response.ok(serialize.transaction(txn))


@bp.post("/transactions/<transaction_id>/void")
@require_roles("Merchant")
def void(transaction_id):
    txn = get_transaction(transaction_id)
    if txn["posting_status"] not in ("AUTHORIZED", "CAPTURED"):
        raise err("ERR_INVALID_TXN_STATE",
                  "Only an AUTHORIZED or CAPTURED transaction can be voided.")
    void_transaction(txn)
    return response.ok(serialize.transaction(txn))
