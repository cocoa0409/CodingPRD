"""Resale transactions: submission, price approval, ROFR, buyer, close."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from services import calc, fund, lookup

bp = Blueprint("resale", __name__)

READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
              mw.DEVELOPER, mw.RESIDENT, mw.FUND_AUDITOR)

DECISIONS = ("WAIVE", "EXERCISE")

FILTER_FIELDS = ("unit_id", "prior_transaction_id", "seller_household_id",
                 "buyer_household_id", "buyer_certification_id", "state")


def _unit_of(txn):
    unit = lookup.maybe("unit", txn.get("unit_id"))
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND")
    return unit


def _agreement_of(unit):
    agreement = lookup.maybe("agreement", unit.get("agreement_id"))
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return agreement


# --------------------------------------------------------------------------
@bp.route("/iz-compliance/resale-transactions", methods=["POST"])
def create_transaction():
    user_id, role = mw.auth(mw.RESIDENT, mw.PROGRAM_ADMINISTRATOR,
                            mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    unit_id = mw.take_str(payload, "unit_id")
    expected_unit_version = mw.take_int(payload, "expected_unit_version", lo=0)
    proposed_price = mw.take_int(payload, "proposed_price_cents", lo=1)
    appraised_value = mw.take_int(payload, "appraised_value_cents", lo=1)
    capital_improvements = mw.take_int(payload, "capital_improvements_cents", lo=0)
    deferred_maintenance = mw.take_int(payload, "deferred_maintenance_cents", lo=0)
    broker_fee = mw.take_int(payload, "broker_fee_cents", lo=0)
    prior_transaction_id = mw.take_str(payload, "prior_transaction_id",
                                       required=False, default=None)

    # rung 6 -- body foreign keys, left to right
    unit = lookup.fetch("unit", unit_id)
    prior = None
    if prior_transaction_id is not None:
        prior = lookup.fetch("resale_transaction", prior_transaction_id)
    # rung 7 -- a Resident may only sell the unit it occupies
    lookup.require_unit_occupant(unit, user_id, role)
    # rung 8
    lookup.check_unit_version(unit, expected_unit_version)
    # rung 11
    if unit.get("restriction_state") != "RECORDED":
        raise ApiError("ERR_UNIT_NOT_RESTRICTED",
                       "A resale requires a RECORDED deed restriction.")
    # rung 22
    if unit.get("compliance_status") == "OUT_OF_COMPLIANCE":
        raise ApiError("ERR_UNIT_OUT_OF_COMPLIANCE")
    # rung 27
    ami = calc.select_ami_schedule()
    # rung 39
    closed_history = [row for row in lookup.unit_resales(unit_id)
                      if row.get("state") == "CLOSED"]
    if prior is not None:
        if prior.get("state") != "CLOSED" or prior.get("unit_id") != unit_id:
            raise ApiError("ERR_PRIOR_TRANSACTION_MISMATCH")
    elif closed_history:
        raise ApiError("ERR_PRIOR_TRANSACTION_MISMATCH")

    agreement = _agreement_of(unit)
    pricing = calc.max_resale_price(unit, agreement, ami, appraised_value,
                                    capital_improvements, deferred_maintenance)

    row = db.insert(db.resale_transactions, {
        "unit_id": unit_id,
        "prior_transaction_id": prior_transaction_id,
        "seller_household_id": unit.get("occupant_household_id"),
        "buyer_household_id": None,
        "buyer_certification_id": None,
        "proposed_price_cents": proposed_price,
        "appraised_value_cents": appraised_value,
        "capital_improvements_cents": capital_improvements,
        "deferred_maintenance_cents": deferred_maintenance,
        "broker_fee_cents": broker_fee,
        "resale_formula_applied": pricing["resale_formula_applied"],
        "indexed_base_cents": pricing["indexed_base_cents"],
        "improvement_credit_cents": pricing["improvement_credit_cents"],
        "max_resale_price_cents": pricing["max_resale_price_cents"],
        "net_proceeds_cents": 0,
        "seller_equity_cents": 0,
        "seller_improvement_credit_cents": 0,
        "seller_appreciation_share_cents": 0,
        "city_recapture_cents": 0,
        "state": "SUBMITTED",
        "price_approved_at": None,
        "price_approved_by_user_id": None,
        "rofr_deadline": None,
        "rofr_auto_waived": False,
        "closed_at": None,
    })

    # A fresh submission retires whatever was still open on this unit.
    for existing in lookup.unit_resales(unit_id):
        if existing["id"] == row["id"]:
            continue
        if existing.get("state") == "SUBMITTED":
            existing["state"] = "SUPERSEDED"
            db.touch(existing)

    db.touch(unit)
    return response.created(db.public(row))


@bp.route("/iz-compliance/resale-transactions/<resale_transaction_id>", methods=["GET"])
def get_transaction(resale_transaction_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(lookup.fetch("resale_transaction", resale_transaction_id)))


@bp.route("/iz-compliance/resale-transactions", methods=["GET"])
def list_transactions():
    mw.auth(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.resale_transactions, FILTER_FIELDS)
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


@bp.route("/iz-compliance/resale-transactions/<resale_transaction_id>/approve-price",
          methods=["POST"])
def approve_price(resale_transaction_id):
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    mw.body()

    txn = lookup.fetch("resale_transaction", resale_transaction_id)
    unit = _unit_of(txn)

    # rung 11
    if unit.get("restriction_state") != "RECORDED":
        raise ApiError("ERR_UNIT_NOT_RESTRICTED",
                       "Price approval requires a RECORDED deed restriction.")
    # rung 18
    if txn.get("state") != "SUBMITTED":
        raise ApiError("ERR_RESALE_STATE_INVALID",
                       "Price approval is permitted only from SUBMITTED.")
    # rung 22
    if unit.get("compliance_status") == "OUT_OF_COMPLIANCE":
        raise ApiError("ERR_UNIT_OUT_OF_COMPLIANCE")
    # rung 44 -- the ceiling is inclusive
    if int(txn.get("proposed_price_cents") or 0) > int(txn.get("max_resale_price_cents") or 0):
        raise ApiError("ERR_RESALE_PRICE_EXCEEDS_MAX")

    now = db.logical_now()
    txn["state"] = "PRICE_APPROVED"
    txn["price_approved_at"] = db.fmt_dt(now)
    txn["price_approved_by_user_id"] = user_id
    txn["rofr_deadline"] = db.fmt_dt(now + calc._days(calc.ROFR_WINDOW_DAYS))
    db.touch(txn)

    return response.ok(db.public(txn))


@bp.route("/iz-compliance/resale-transactions/<resale_transaction_id>/rofr-decision",
          methods=["POST"])
def rofr_decision(resale_transaction_id):
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()
    decision = mw.take_enum(payload, "decision", DECISIONS)

    txn = lookup.fetch("resale_transaction", resale_transaction_id)

    # rung 18
    if txn.get("state") != "PRICE_APPROVED":
        raise ApiError("ERR_RESALE_STATE_INVALID",
                       "A right-of-first-refusal decision requires PRICE_APPROVED.")
    # rung 37 -- the deadline instant itself is inclusive
    deadline = db.parse_dt(txn.get("rofr_deadline"))
    if deadline is not None and db.logical_now() > deadline:
        raise ApiError("ERR_ROFR_WINDOW_EXPIRED")

    if decision == "EXERCISE":
        # rung 49
        ledger = fund.ledger()
        if ledger["unencumbered_balance_cents"] < int(txn.get("proposed_price_cents") or 0):
            raise ApiError("ERR_INSUFFICIENT_FUND_BALANCE")
        txn["state"] = "ROFR_EXERCISED"
    else:
        txn["state"] = "ROFR_WAIVED"
    db.touch(txn)

    return response.ok(db.public(txn))


@bp.route("/iz-compliance/resale-transactions/<resale_transaction_id>/certify-buyer",
          methods=["POST"])
def certify_buyer(resale_transaction_id):
    user_id, _role = mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    payload = mw.body()
    buyer_household_id = mw.take_str(payload, "buyer_household_id")
    certification_id = mw.take_str(payload, "certification_id")

    txn = lookup.fetch("resale_transaction", resale_transaction_id)

    # rung 6 -- body foreign keys, left to right
    lookup.fetch("household", buyer_household_id)
    certification = lookup.fetch("certification", certification_id)

    # rung 18
    if txn.get("state") != "ROFR_WAIVED":
        raise ApiError("ERR_RESALE_STATE_INVALID",
                       "Buyer certification is permitted only from ROFR_WAIVED.")
    # rung 21
    if user_id == txn.get("price_approved_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who approved the price may not certify the buyer.")
    # rung 40
    if (certification.get("state") != "CERTIFIED"
            or certification.get("unit_id") != txn.get("unit_id")
            or certification.get("household_id") != buyer_household_id):
        raise ApiError("ERR_BUYER_CERTIFICATION_MISMATCH")

    txn["buyer_household_id"] = buyer_household_id
    txn["buyer_certification_id"] = certification_id
    txn["state"] = "BUYER_CERTIFIED"
    db.touch(txn)

    return response.ok(db.public(txn))


@bp.route("/iz-compliance/resale-transactions/<resale_transaction_id>/close",
          methods=["POST"])
def close_transaction(resale_transaction_id):
    mw.auth(mw.HOUSING_COMPLIANCE_OFFICER)
    mw.body()

    txn = lookup.fetch("resale_transaction", resale_transaction_id)

    # rung 18
    previous_state = txn.get("state")
    if previous_state not in ("BUYER_CERTIFIED", "ROFR_EXERCISED"):
        raise ApiError("ERR_RESALE_STATE_INVALID",
                       "Close is permitted only from BUYER_CERTIFIED or ROFR_EXERCISED.")

    unit = _unit_of(txn)
    agreement = _agreement_of(unit)
    via_exercise = previous_state == "ROFR_EXERCISED"

    txn["_original_purchase_price_cents"] = int(unit.get("original_purchase_price_cents") or 0)
    waterfall = calc.resale_waterfall(txn, agreement, via_exercise)
    txn.update(waterfall)
    txn["state"] = "CITY_PURCHASE_CLOSED" if via_exercise else "CLOSED"
    txn["closed_at"] = db.fmt_dt(db.logical_now())
    db.touch(txn)

    # CASCADE L2 -- the unit's price basis and occupancy are reset
    seller_household_id = txn.get("seller_household_id")
    unit["original_purchase_price_cents"] = int(txn.get("proposed_price_cents") or 0)
    ami = calc.active_ami_or_none()
    if ami is not None:
        unit["ami_income_at_purchase_cents"] = calc.current_median_for_unit(unit, ami)
    if via_exercise:
        unit["occupant_household_id"] = None
        unit["occupancy_status"] = "VACANT"
    else:
        unit["occupant_household_id"] = txn.get("buyer_household_id")
        unit["occupancy_status"] = "OCCUPIED"
    db.touch(unit)

    # CASCADE L3 -- the seller's live certification is retired
    for cert in lookup.unit_certifications(unit["id"]):
        if cert.get("state") != "CERTIFIED":
            continue
        if seller_household_id is not None and cert.get("household_id") != seller_household_id:
            continue
        cert["state"] = "SUPERSEDED"
        db.touch(cert)

    # CASCADE L4 -- the trust fund ledger is a computed read; nothing to store.
    return response.ok(db.public(txn))
