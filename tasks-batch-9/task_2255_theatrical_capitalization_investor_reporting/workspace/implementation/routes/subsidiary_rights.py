"""Subsidiary rights licensing income (PRD 3.8)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (COMPTROLLER, GENERAL_MANAGER, INVESTOR, LEAD_PRODUCER,
                        ctx, endpoint, find_production, lookup)
from services import ledger

bp = Blueprint("subsidiary_rights", __name__)

SOURCES = ("CAST_ALBUM", "FILM_LICENSE", "STOCK_AND_AMATEUR",
           "TOURING_LICENSE", "MERCHANDISE")
INCOME_STATUSES = ("RECORDED", "ALLOCATED")
READ_ROLES = (GENERAL_MANAGER, COMPTROLLER, LEAD_PRODUCER, INVESTOR)


def _find_income(income_id):
    return lookup("subsidiary_rights_income", income_id,
                  errors.ERR_SUBSIDIARY_RIGHTS_INCOME_NOT_FOUND)


@bp.post("/subsidiary-rights-income")
@endpoint((GENERAL_MANAGER,))
def create_subsidiary_rights_income():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    source = v.req_enum(data, "source", SOURCES)
    gross_income = v.req_int(data, "gross_income_cents", 1)
    received_text, _ = v.req_date(data, "received_date")

    find_production(production_id)
    row = db.insert("subsidiary_rights_income", {
        "production_id": production_id,
        "source": source,
        "gross_income_cents": gross_income,
        "received_date": received_text,
        "investor_share_cents": 0,
        "status": "RECORDED",
    })
    return response.obj(row, 201)


@bp.post("/subsidiary-rights-income/<income_id>/allocate")
@endpoint((COMPTROLLER,))
def allocate_subsidiary_rights_income(income_id):
    income = _find_income(income_id)
    production = db.get("productions", income["production_id"])
    if income["status"] != "RECORDED":
        fail(errors.ERR_INVALID_INCOME_STATE,
             "Only RECORDED licensing income may be allocated.")
    if production["offering_status"] != "CAPITALIZED":
        fail(errors.ERR_PRODUCTION_NOT_CAPITALIZED,
             "Licensing income enters the cash ledger only once the production is CAPITALIZED.")

    ctx().force(production)
    ctx().watch(income)
    income["investor_share_cents"] = ledger.subsidiary_rights_investor_share(
        income, production)
    income["status"] = "ALLOCATED"
    ledger.recoupment_progress(ctx(), production)
    return response.obj(income)


@bp.get("/subsidiary-rights-income/<income_id>")
@endpoint(READ_ROLES)
def read_subsidiary_rights_income(income_id):
    return response.obj(_find_income(income_id))


@bp.get("/subsidiary-rights-income")
@endpoint(READ_ROLES)
def list_subsidiary_rights_income():
    production_id = v.q_str("production_id")
    status = v.q_enum("status", INCOME_STATUSES)
    source = v.q_enum("source", SOURCES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("subsidiary_rights_income")
            if (production_id is None or r["production_id"] == production_id)
            and (status is None or r["status"] == status)
            and (source is None or r["source"] == source)]
    return response.listing(rows, limit, offset)
