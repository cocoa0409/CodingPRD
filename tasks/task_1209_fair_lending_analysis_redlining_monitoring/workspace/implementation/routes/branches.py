"""Branches."""
from flask import Blueprint

import db
from errors import already_terminal
from middleware import (
    body, check_number, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj

bp = Blueprint("branches", __name__)

ALL = (
    "BankAdmin", "LendingDataOps", "LoanOfficer", "FairLendingAnalyst",
    "FairLendingOfficer", "ComplianceDirector", "RemediationSpecialist",
)


@bp.post("/fair-lending/branches")
@require_roles("BankAdmin")
def create_branch():
    data = body()
    market_id = require_field(data, "market_id")
    name = require_field(data, "name")
    tract = check_number(require_field(data, "tract_minority_pct"), "tract_minority_pct")
    if not (0 <= tract <= 100):
        from errors import invalid_request
        raise invalid_request("tract_minority_pct must be between 0 and 100")
    opened_on = require_field(data, "opened_on")
    get_or_404("markets", market_id, "Market")
    rec = db.new_record(
        {
            "market_id": market_id,
            "name": name,
            "tract_minority_pct": tract,
            "opened_on": opened_on,
            "status": "ACTIVE",
        }
    )
    db.STORES["branches"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/branches")
@require_roles(*ALL)
def list_branches():
    from flask import request
    page, total, limit, offset = list_page(
        "branches",
        {"market_id": request.args.get("market_id"), "status": request.args.get("status")},
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/branches/<branchId>")
@require_roles(*ALL)
def get_branch(branchId):
    rec = get_or_404("branches", branchId, "Branch")
    return success_obj(db.public(rec))


@bp.post("/fair-lending/branches/<branchId>/close")
@require_roles("BankAdmin")
def close_branch(branchId):
    rec = get_or_404("branches", branchId, "Branch")
    if rec["status"] == "CLOSED":
        raise already_terminal("Branch is already CLOSED")
    rec["status"] = "CLOSED"
    db.touch(rec)
    # Cascade: every ACTIVE loan officer of this branch -> SUSPENDED.
    for officer in db.STORES["officers"].values():
        if officer["branch_id"] == rec["id"] and officer["status"] == "ACTIVE":
            officer["status"] = "SUSPENDED"
            db.touch(officer)
    return success_obj(db.public(rec))
