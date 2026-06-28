"""ConservancyFund routes (PRD §3.7)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize
from services.common import (
    new_record, get_body, get_or_404, paginate, touch,
    req_str, opt_int, opt_number,
)

bp = Blueprint("conservancy_funds", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


@bp.route("/v1/conservancy-funds", methods=["POST"])
def create_fund():
    _, role = get_identity()
    require_role(role, {"DevelopmentOfficer", "GardenAdmin"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    get_or_404(db.gardens, garden_id)
    # One fund per garden (PRD §3.7).
    for f in db.conservancy_funds.values():
        if f["garden_id"] == garden_id:
            raise errors.fund_already_exists()
    rec = new_record({
        "garden_id": garden_id,
        "pledged_total_cents": 0,
        "matched_total_cents": 0,
        "match_ratio": opt_number(body, "match_ratio", 0.0),
        "match_cap_cents": opt_int(body, "match_cap_cents", 0),
        "campaign_status": "OPEN",
    })
    db.conservancy_funds[rec["id"]] = rec
    return success(serialize.conservancy_fund(rec), status=201)


@bp.route("/v1/conservancy-funds/<fund_id>", methods=["GET"])
def read_fund(fund_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.conservancy_funds, fund_id)
    return success(serialize.conservancy_fund(rec), status=200)


@bp.route("/v1/conservancy-funds", methods=["GET"])
def list_funds():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    records = list(db.conservancy_funds.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.conservancy_fund(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/conservancy-funds/<fund_id>/close-campaign", methods=["POST"])
def close_campaign(fund_id):
    _, role = get_identity()
    require_role(role, {"DevelopmentOfficer"})
    rec = get_or_404(db.conservancy_funds, fund_id)
    if rec["campaign_status"] != "OPEN":
        raise errors.campaign_closed()
    rec["campaign_status"] = "CLOSED"
    touch(rec)
    return success(serialize.conservancy_fund(rec), status=200)
