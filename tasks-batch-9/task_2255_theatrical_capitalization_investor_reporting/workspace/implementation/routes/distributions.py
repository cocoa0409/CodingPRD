"""Investor distributions: declaration freezes the split, payment replays it.

PRD 3.9.
"""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (COMPTROLLER, GENERAL_MANAGER, INVESTOR, LEAD_PRODUCER,
                        ctx, endpoint, find_production, lookup)
from services import ledger

bp = Blueprint("distributions", __name__)

DISTRIBUTION_TYPES = ("RECOUPMENT_RETURN", "NET_PROFIT", "SUBSIDIARY_RIGHTS",
                      "RESERVE_RELEASE")
DISTRIBUTION_STATUSES = ("DECLARED", "PAID")
READ_ROLES = (GENERAL_MANAGER, COMPTROLLER, LEAD_PRODUCER, INVESTOR)


def _find_distribution(distribution_id):
    return lookup("investor_distributions", distribution_id,
                  errors.ERR_INVESTOR_DISTRIBUTION_NOT_FOUND)


@bp.post("/investor-distributions")
@endpoint((COMPTROLLER,))
def declare_distribution():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    distribution_type = v.req_enum(data, "distribution_type",
                                   DISTRIBUTION_TYPES)
    total_amount = v.req_int(data, "total_amount_cents", 1)
    expected_version = v.req_int(data, "expected_production_version")

    production = find_production(production_id)

    # Global validation step 10 (PRD 2.7).
    if expected_version != production["version"]:
        fail(errors.ERR_STALE_PRODUCTION_VERSION,
             "The production has been written since the client last read it.")

    # Fiscal ceilings 14c, 14d, 14e in exactly this order (PRD 2.11).
    breakdown = ledger.distribution_allocation(production, total_amount)
    if breakdown is None:
        fail(errors.ERR_NO_INVESTOR_ACCOUNTS,
             "The production has no capital account holding units.")
    if distribution_type == "NET_PROFIT" \
            and production["recoupment_status"] != "RECOUPED":
        fail(errors.ERR_NOT_YET_RECOUPED,
             "A NET_PROFIT distribution requires the production to be RECOUPED.")
    if total_amount > production["distributable_cash_cents"]:
        fail(errors.ERR_DISTRIBUTION_EXCEEDS_DISTRIBUTABLE,
             "The declaration exceeds distributable_cash_cents.")

    row = db.insert("investor_distributions", {
        "production_id": production_id,
        "distribution_type": distribution_type,
        "total_amount_cents": total_amount,
        "allocation_breakdown": breakdown,
        "status": "DECLARED",
    })
    ctx().created(row)
    ctx().force(production)
    for entry in breakdown:
        account = db.get("investor_accounts", entry["investor_account_id"])
        ctx().watch(account)
        account["declared_distribution_cents"] += entry["amount_cents"]
    ledger.recoupment_progress(ctx(), production)
    return response.obj(row, 201)


@bp.post("/investor-distributions/<distribution_id>/pay")
@endpoint((COMPTROLLER,))
def pay_distribution(distribution_id):
    distribution = _find_distribution(distribution_id)
    if distribution["status"] != "DECLARED":
        fail(errors.ERR_INVALID_DISTRIBUTION_STATE,
             "Only a DECLARED distribution may be paid.")

    ctx().watch(distribution)
    distribution["status"] = "PAID"
    # Payment replays the frozen breakdown and never recomputes it (PRD 3.9).
    for entry in distribution["allocation_breakdown"]:
        account = db.get("investor_accounts", entry["investor_account_id"])
        if account is None:
            continue
        ctx().watch(account)
        account["distributions_paid_cents"] += entry["amount_cents"]
    return response.obj(distribution)


@bp.get("/investor-distributions/<distribution_id>")
@endpoint(READ_ROLES)
def read_distribution(distribution_id):
    return response.obj(_find_distribution(distribution_id))


@bp.get("/investor-distributions")
@endpoint(READ_ROLES)
def list_distributions():
    production_id = v.q_str("production_id")
    status = v.q_enum("status", DISTRIBUTION_STATUSES)
    distribution_type = v.q_enum("distribution_type", DISTRIBUTION_TYPES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("investor_distributions")
            if (production_id is None or r["production_id"] == production_id)
            and (status is None or r["status"] == status)
            and (distribution_type is None
                 or r["distribution_type"] == distribution_type)]
    return response.listing(rows, limit, offset)
