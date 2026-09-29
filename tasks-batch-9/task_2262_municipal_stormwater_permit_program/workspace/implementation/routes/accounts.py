"""Stormwater utility accounts and the tiered fee chain."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, new_row, touch
from errors import ApiError
from middleware import body, get_enum, get_int, get_str, require
from routes.common import find, one, settle
from services import calc, derive

bp = Blueprint("accounts", __name__)


@bp.post("/accounts")
def create_account():
    require([mw.CLERK])
    payload = body()
    term_id = get_str(payload, "permit_term_id")
    parcel_id = get_str(payload, "parcel_id")
    owner_name = get_str(payload, "owner_name")
    parcel_class = get_enum(payload, "parcel_class", enums.PARCEL_CLASS)
    impervious = get_int(payload, "impervious_area_sqft", minimum=0)

    term = find("permit_terms", term_id)
    for existing in derive.accounts_of_term(term["id"]):
        if existing["parcel_id"] == parcel_id:
            raise ApiError("ERR_DUPLICATE_PARCEL_ID")

    fee = calc.tiered_fee(impervious, term.get("eru_sqft"), parcel_class)
    row = new_row(
        {
            "permit_term_id": term["id"],
            "parcel_id": parcel_id,
            "owner_name": owner_name,
            "parcel_class": parcel_class,
            "impervious_area_sqft": impervious,
            "eru_units": fee["eru_units"],
            "gross_fee_cents": fee["gross_fee_cents"],
            "class_surcharge_cents": fee["class_surcharge_cents"],
            "gross_billable_cents": fee["gross_billable_cents"],
            "total_credit_pct": 0.0000,
            "current_net_fee_cents": fee["gross_billable_cents"],
            "last_billed_run_type": None,
            "last_billed_net_cents": None,
            "last_billed_credit_pct": None,
            "last_billed_at": None,
        }
    )
    DB.accounts[row["id"]] = row
    settle(term)
    return one(row, 201)


@bp.get("/accounts/<account_id>")
def read_account(account_id):
    require([mw.CLERK, mw.MANAGER, mw.OWNER])
    return one(find("accounts", account_id))


@bp.post("/accounts/<account_id>/impervious-updates")
def update_impervious(account_id):
    require([mw.CLERK])
    payload = body()
    impervious = get_int(payload, "impervious_area_sqft", minimum=0)
    expected = get_int(payload, "expected_stormwater_account_version")
    account = find("accounts", account_id)
    if int(account.get("version") or 0) != expected:
        raise ApiError("ERR_ACCOUNT_VERSION_CONFLICT")

    account["impervious_area_sqft"] = impervious
    touch(account)
    term = DB.permit_terms.get(account["permit_term_id"])
    derive.recompute_account(account)
    settle(term)
    return one(account)
