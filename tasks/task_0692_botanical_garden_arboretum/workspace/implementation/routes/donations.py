"""Donation routes + void with compensation (PRD §3.7)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize, calc
from services.common import (
    new_record, get_body, get_or_404, paginate, touch,
    req_str, opt_str, req_int, opt_enum,
)

bp = Blueprint("donations", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


def _fund_for_garden(garden_id):
    for f in db.conservancy_funds.values():
        if f["garden_id"] == garden_id:
            return f
    return None


@bp.route("/v1/donations", methods=["POST"])
def create_donation():
    _, role = get_identity()
    require_role(role, {"Visitor", "DevelopmentOfficer", "GardenStaff"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    amount_cents = req_int(body, "amount_cents", min_value=1)
    designation = opt_enum(body, "designation",
                           {"GENERAL", "CONSERVANCY", "CAPITAL"}, "GENERAL")
    membership_id = opt_str(body, "membership_id", "")

    get_or_404(db.gardens, garden_id)
    membership = None
    if membership_id:
        membership = get_or_404(db.memberships, membership_id)
        if membership["garden_id"] != garden_id:
            raise errors.cross_garden_reference()

    tax_deductible_cents = calc.donation_deductible_cents(amount_cents, designation)

    # Track the match this donation contributed (for void compensation).
    contributed_match = 0
    fund = None
    if designation == "CONSERVANCY":
        fund = _fund_for_garden(garden_id)
        if fund is not None:
            campaign_open = fund["campaign_status"] == "OPEN"
            contributed_match = calc.conservancy_applied_match(
                amount_cents, campaign_open, fund["match_ratio"],
                fund["match_cap_cents"], fund["matched_total_cents"])

    rec = new_record({
        "garden_id": garden_id,
        "membership_id": membership_id,
        "amount_cents": amount_cents,
        "designation": designation,
        "tax_deductible_cents": tax_deductible_cents,
        "status": "RECORDED",
        "_contributed_match": contributed_match,
    })
    db.donations[rec["id"]] = rec

    # Side effect on the fund (PRD §3.7): pledge always added; match added.
    if designation == "CONSERVANCY" and fund is not None:
        fund["pledged_total_cents"] = fund["pledged_total_cents"] + amount_cents
        fund["matched_total_cents"] = fund["matched_total_cents"] + contributed_match
        touch(fund)

    return success(serialize.donation(rec), status=201)


@bp.route("/v1/donations/<donation_id>", methods=["GET"])
def read_donation(donation_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.donations, donation_id)
    return success(serialize.donation(rec), status=200)


@bp.route("/v1/donations", methods=["GET"])
def list_donations():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    membership_id = request.args.get("membership_id")
    designation = request.args.get("designation")
    status = request.args.get("status")
    records = list(db.donations.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if designation is not None:
        records = [r for r in records if r["designation"] == designation]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.donation(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/donations/<donation_id>/void", methods=["POST"])
def void_donation(donation_id):
    _, role = get_identity()
    require_role(role, {"DevelopmentOfficer"})
    rec = get_or_404(db.donations, donation_id)
    if rec["status"] != "RECORDED":
        raise errors.donation_voided()

    rec["status"] = "VOIDED"
    touch(rec)

    # Compensating reversal for CONSERVANCY gifts (PRD §3.7).
    if rec["designation"] == "CONSERVANCY":
        fund = _fund_for_garden(rec["garden_id"])
        if fund is not None:
            fund["pledged_total_cents"] = fund["pledged_total_cents"] - rec["amount_cents"]
            fund["matched_total_cents"] = fund["matched_total_cents"] - rec["_contributed_match"]
            touch(fund)

    return success(serialize.donation(rec), status=200)
