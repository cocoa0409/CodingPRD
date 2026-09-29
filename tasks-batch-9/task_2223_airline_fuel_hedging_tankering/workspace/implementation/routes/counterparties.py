"""Counterparty and manual collateral-requirement endpoints (PRD 3.1, 3.5)."""

from flask import Blueprint

import calc
import domain
import fetch
import serializers as ser
import validators as v
from calc import r2
from db import db
from errors import fail
from middleware import (FUEL_OPS_CONTROLLER, FUEL_ANALYST, HEDGE_ACCOUNTANT,
                        RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, endpoint,
                        new_row, touch)
from response import created, ok, ok_list

bp = Blueprint("counterparties", __name__)

POSTING_STATUSES = ("REQUIRED", "POSTED", "RETURNED")
POSTING_ORIGINS = ("MANUAL", "MTM_MARGIN_CALL")


@bp.post("/fuel/counterparties")
@endpoint(RISK_POLICY_ADMIN)
def create_counterparty():
    data = v.body()
    code = v.get_string(data, "counterparty_code", min_len=1, max_len=16)
    legal_name = v.get_string(data, "legal_name", min_len=1, max_len=120)
    rating = v.get_enum(data, "credit_rating", calc.CREDIT_RATINGS)
    limit = v.get_number(data, "credit_limit_usd", exclusive_minimum=0, places=2)

    for row in db.counterparties.values():
        if row["counterparty_code"] == code:
            fail("ERR_DUPLICATE_COUNTERPARTY_CODE",
                 "counterparty_code %r is already in use." % code)

    row = new_row()
    row.update({
        "counterparty_code": code,
        "legal_name": legal_name,
        "credit_rating": rating,
        "credit_limit_usd": limit,
        "status": "SUSPENDED" if rating == "BB" else "APPROVED",
        "last_review_note": None,
    })
    db.counterparties[row["id"]] = row
    return created(ser.counterparty(row))


@bp.get("/fuel/counterparties/<counterparty_id>")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER,
          HEDGE_ACCOUNTANT, FUEL_OPS_CONTROLLER)
def read_counterparty(counterparty_id):
    return ok(ser.counterparty(fetch.counterparty(counterparty_id)))


@bp.post("/fuel/counterparties/<counterparty_id>/credit-review")
@endpoint(TREASURY_RISK_MANAGER, RISK_POLICY_ADMIN)
def credit_review(counterparty_id):
    data = v.body()
    rating = v.get_enum(data, "credit_rating", calc.CREDIT_RATINGS)
    note = v.get_string(data, "review_note", min_len=1)
    limit = v.get_number(data, "credit_limit_usd", required=False,
                         exclusive_minimum=0, places=2)

    row = fetch.counterparty(counterparty_id)
    row["credit_rating"] = rating
    if limit is not None:
        row["credit_limit_usd"] = limit
    row["status"] = "SUSPENDED" if rating == "BB" else "APPROVED"
    row["last_review_note"] = note
    touch(row)
    return ok(ser.counterparty(row))


@bp.post("/fuel/counterparties/<counterparty_id>/collateral-postings")
@endpoint(RISK_POLICY_ADMIN)
def create_posting(counterparty_id):
    data = v.body()
    instrument_id = v.get_string(data, "hedge_instrument_id", min_len=1)
    collateral_type = v.get_enum(data, "collateral_type", calc.COLLATERAL_TYPES)
    expected = v.get_int(data, "expected_counterparty_version")

    counterparty = fetch.counterparty(counterparty_id)
    instrument = fetch.instrument(instrument_id)

    if instrument["trade_status"] != "EXECUTED":
        fail("ERR_INSTRUMENT_INVALID_TRADE_STATE",
             "Collateral may only be required against an EXECUTED trade.")
    if expected != counterparty["version"]:
        fail("ERR_STALE_VERSION",
             "expected_counterparty_version %s does not match current version %s."
             % (expected, counterparty["version"]))

    outstanding = instrument["margin_requirement_usd"] - domain.instrument_collateral_posted(instrument)
    if outstanding < 0:
        outstanding = r2(0)

    row = new_row()
    row.update({
        "counterparty_id": counterparty["id"],
        "hedge_instrument_id": instrument["id"],
        "collateral_type": collateral_type,
        "required_amount_usd": r2(outstanding),
        "posted_amount_usd": r2(0),
        "status": "REQUIRED",
        "origin": "MANUAL",
        "posted_at": None,
        "returned_at": None,
    })
    db.postings[row["id"]] = row
    touch(counterparty)
    return created(ser.posting(row))


@bp.get("/fuel/counterparties/<counterparty_id>/collateral-postings")
@endpoint(RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_counterparty_postings(counterparty_id):
    limit, offset = v.pagination()
    status = v.enum_filter("status", POSTING_STATUSES)
    origin = v.enum_filter("origin", POSTING_ORIGINS)
    counterparty = fetch.counterparty(counterparty_id)

    rows = domain.counterparty_postings(counterparty["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.posting(r) for r in page], limit, offset, total)
