"""Manufacturer and Retailer endpoints (PRD 3.1, 3.6)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from middleware import ALL_ROLES
from services import calc, domain

bp = Blueprint("parties", __name__)

MANUFACTURER_SPEC = {
    "legal_name": {"type": "string", "required": True, "min_len": 1, "max_len": 200},
    "gs1_company_prefix": {
        "type": "string",
        "required": True,
        "exact_len": 6,
        "digits": True,
    },
    "handling_fee_policy": {
        "type": "enum",
        "values": ["CONTRACT_RATE", "TIERED_RATE"],
        "default": "CONTRACT_RATE",
    },
    "dispute_window_days": {
        "type": "integer",
        "min": 1,
        "max": 180,
        "default": 45,
    },
}

RETAILER_SPEC = {
    "legal_name": {"type": "string", "required": True, "min_len": 1, "max_len": 200},
    "channel_capability": {
        "type": "enum",
        "values": ["MAIL_ONLY", "ELECTRONIC_ONLY", "BOTH"],
        "default": "BOTH",
    },
    "payment_terms": {
        "type": "enum",
        "values": ["NET_15", "NET_30", "NET_45"],
        "default": "NET_30",
    },
    "base_fee_tier": {
        "type": "enum",
        "values": ["PREFERRED", "STANDARD"],
        "default": "STANDARD",
    },
    "fraud_scoring_mode": {
        "type": "enum",
        "values": ["ROLLING_WINDOW", "LIFETIME_WEIGHTED"],
        "default": "ROLLING_WINDOW",
    },
}

REASON_SPEC = {
    "reason": {"type": "string", "required": True, "min_len": 1, "max_len": 500},
}


# ------------------------------------------------------------ manufacturers
@bp.route("/manufacturers", methods=["POST"])
def create_manufacturer():
    mw.authenticate(["ClearinghouseAdmin"])
    payload = mw.body()
    values = validate.parse(payload, MANUFACTURER_SPEC)
    for existing in db.db.manufacturers.values():
        if existing["gs1_company_prefix"] == values["gs1_company_prefix"]:
            raise ApiError(
                "ERR_DUPLICATE_GS1_PREFIX",
                "GS1 company prefix is already registered",
            )
    row = db.base_row()
    row.update(
        {
            "legal_name": values["legal_name"],
            "gs1_company_prefix": values["gs1_company_prefix"],
            "handling_fee_policy": values["handling_fee_policy"],
            "dispute_window_days": values["dispute_window_days"],
            "funded_total_cents": 0,
            "disbursed_total_cents": 0,
            "funding_balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.db.manufacturers[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/manufacturers/<mid>", methods=["GET"])
def get_manufacturer(mid):
    mw.authenticate(ALL_ROLES)
    row = mw.fetch("manufacturers", mid, "ERR_MANUFACTURER_NOT_FOUND")
    return response.object_response(row)


@bp.route("/manufacturers", methods=["GET"])
def list_manufacturers():
    mw.authenticate(["SettlementOfficer", "ClearinghouseAdmin"])
    limit, offset = mw.pagination()
    status = mw.str_arg("status")
    rows = [
        r
        for r in db.db.manufacturers.values()
        if status is None or r["status"] == status
    ]
    rows = sort_rows(rows, descending=True)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/manufacturers/<mid>/suspend", methods=["POST"])
def suspend_manufacturer(mid):
    mw.authenticate(["ClearinghouseAdmin"])
    row = mw.fetch("manufacturers", mid, "ERR_MANUFACTURER_NOT_FOUND")
    validate.parse(mw.body(), REASON_SPEC)
    if row["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Manufacturer is already SUSPENDED"
        )
    row["status"] = "SUSPENDED"
    touch(row)
    cascade = [
        o
        for o in db.db.offers.values()
        if o["manufacturer_id"] == row["id"]
        and o["status"] in ("DRAFT", "REGISTERED", "ACTIVE")
    ]
    for offer in sort_rows(cascade):
        domain.withdraw_offer(offer, "MANUFACTURER_SUSPENDED")
    return response.object_response(row)


# ----------------------------------------------------------------- retailers
@bp.route("/retailers", methods=["POST"])
def create_retailer():
    mw.authenticate(["ClearinghouseAdmin"])
    values = validate.parse(mw.body(), RETAILER_SPEC)
    row = db.base_row()
    row.update(
        {
            "legal_name": values["legal_name"],
            "channel_capability": values["channel_capability"],
            "payment_terms": values["payment_terms"],
            "base_fee_tier": values["base_fee_tier"],
            "handling_fee_tier": values["base_fee_tier"],
            "fraud_scoring_mode": values["fraud_scoring_mode"],
            "fraud_score_rolling_window": calc.ZERO_2,
            "fraud_score_lifetime_weighted": calc.ZERO_2,
            "fraud_score": calc.ZERO_2,
            "duplicate_rate": calc.ZERO_2,
            "misredemption_rate": calc.ZERO_2,
            "counterfeit_rate": calc.ZERO_2,
            "rejected_submission_count": 0,
            "unpaid_balance_cents": 0,
            "status": "ACTIVE",
            "last_rescored_at": None,
        }
    )
    db.db.retailers[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/retailers/<rid>", methods=["GET"])
def get_retailer(rid):
    mw.authenticate(ALL_ROLES)
    row = mw.fetch("retailers", rid, "ERR_RETAILER_NOT_FOUND")
    return response.object_response(row)


@bp.route("/retailers", methods=["GET"])
def list_retailers():
    mw.authenticate(["FraudAnalyst", "SettlementOfficer", "ClearinghouseAdmin"])
    limit, offset = mw.pagination()
    status = mw.str_arg("status")
    tier = mw.str_arg("handling_fee_tier")
    rows = [
        r
        for r in db.db.retailers.values()
        if (status is None or r["status"] == status)
        and (tier is None or r["handling_fee_tier"] == tier)
    ]
    rows = sort_rows(rows, descending=True)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/retailers/<rid>/suspend", methods=["POST"])
def suspend_retailer(rid):
    mw.authenticate(["ClearinghouseAdmin"])
    row = mw.fetch("retailers", rid, "ERR_RETAILER_NOT_FOUND")
    validate.parse(mw.body(), REASON_SPEC)
    if row["status"] not in ("ACTIVE", "WATCHLIST"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Retailer cannot be suspended from %s" % row["status"],
        )
    row["status"] = "SUSPENDED"
    row["handling_fee_tier"] = "PROBATION"
    touch(row)
    return response.object_response(row)


@bp.route("/retailers/<rid>/reinstate", methods=["POST"])
def reinstate_retailer(rid):
    mw.authenticate(["ClearinghouseAdmin"])
    row = mw.fetch("retailers", rid, "ERR_RETAILER_NOT_FOUND")
    validate.parse(mw.body(), REASON_SPEC)
    if row["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SUSPENDED retailer can be reinstated",
        )
    row["status"] = "ACTIVE"
    row["handling_fee_tier"] = row["base_fee_tier"]
    touch(row)
    return response.object_response(row)


@bp.route("/retailers/<rid>/fraud-rescore", methods=["POST"])
def rescore_retailer(rid):
    ctx = mw.authenticate(["FraudAnalyst"])
    row = mw.fetch("retailers", rid, "ERR_RETAILER_NOT_FOUND")
    values = validate.parse(
        mw.body(),
        {"expected_retailer_version": {"type": "integer", "required": True, "min": 0}},
    )
    if values["expected_retailer_version"] != row["version"]:
        raise ApiError(
            "ERR_STALE_RETAILER_VERSION",
            "Retailer version is %d" % row["version"],
        )
    domain.fraud_rescore(row)
    return response.object_response(row)
