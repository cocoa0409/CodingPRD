"""Markets."""
from flask import Blueprint, request

import db
from errors import invalid_request
from middleware import (
    body, check_number, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj
from services.cap import penetration_report

bp = Blueprint("markets", __name__)

ALL = (
    "BankAdmin", "LendingDataOps", "LoanOfficer", "FairLendingAnalyst",
    "FairLendingOfficer", "ComplianceDirector", "RemediationSpecialist",
)
ANALYTICS = ("FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")


@bp.post("/fair-lending/markets")
@require_roles("BankAdmin")
def create_market():
    data = body()
    name = require_field(data, "name")
    msa_code = require_field(data, "msa_code")
    share = check_number(
        require_field(data, "protected_group_population_share"),
        "protected_group_population_share",
    )
    if not (0 <= share <= 1):
        raise invalid_request("protected_group_population_share must be between 0 and 1")
    peer_group_code = require_field(data, "peer_group_code")
    for m in db.STORES["markets"].values():
        if m["msa_code"] == msa_code:
            raise invalid_request("msa_code must be unique across markets")
    rec = db.new_record(
        {
            "name": name,
            "msa_code": msa_code,
            "protected_group_population_share": share,
            "peer_group_code": peer_group_code,
        }
    )
    db.STORES["markets"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/markets")
@require_roles(*ALL)
def list_markets():
    page, total, limit, offset = list_page("markets")
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/markets/<marketId>")
@require_roles(*ALL)
def get_market(marketId):
    rec = get_or_404("markets", marketId, "Market")
    return success_obj(db.public(rec))


@bp.get("/fair-lending/markets/<marketId>/penetration-report")
@require_roles(*ANALYTICS)
def market_penetration(marketId):
    market = get_or_404("markets", marketId, "Market")
    period_start = request.args.get("period_start")
    period_end = request.args.get("period_end")
    if not period_start or not period_end:
        raise invalid_request("period_start and period_end query parameters are required")
    return success_obj(penetration_report(market, period_start, period_end))
