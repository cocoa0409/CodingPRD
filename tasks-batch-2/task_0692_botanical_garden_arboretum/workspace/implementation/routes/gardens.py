"""Garden + MembershipPlan routes (PRD §3.1)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize
from services.common import (
    new_record, get_body, get_or_404, paginate,
    req_str, opt_str, opt_number, opt_int, opt_bool, req_int, req_enum,
)

bp = Blueprint("gardens", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


# --- Garden -----------------------------------------------------------------
@bp.route("/v1/gardens", methods=["POST"])
def create_garden():
    _, role = get_identity()
    require_role(role, {"GardenAdmin"})
    body = get_body()
    rec = new_record({
        "name": req_str(body, "name"),
        "timezone": opt_str(body, "timezone", "America/New_York"),
        "reciprocal_network_code": opt_str(body, "reciprocal_network_code", ""),
        "reciprocal_discount_pct": opt_number(body, "reciprocal_discount_pct", 0.5),
        "household_member_cap": opt_int(body, "household_member_cap", 2),
        "guest_pass_grant_household": opt_int(body, "guest_pass_grant_household", 4),
        "guest_pass_grant_patron": opt_int(body, "guest_pass_grant_patron", 8),
    })
    db.gardens[rec["id"]] = rec
    return success(serialize.garden(rec), status=201)


@bp.route("/v1/gardens/<garden_id>", methods=["GET"])
def read_garden(garden_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.gardens, garden_id)
    return success(serialize.garden(rec), status=200)


# --- MembershipPlan ---------------------------------------------------------
@bp.route("/v1/membership-plans", methods=["POST"])
def create_plan():
    _, role = get_identity()
    require_role(role, {"GardenAdmin"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    tier = req_enum(body, "tier", {"INDIVIDUAL", "HOUSEHOLD", "PATRON"})
    annual_fee_cents = req_int(body, "annual_fee_cents", min_value=0)
    # Existence: garden must exist (PRD §2.7).
    get_or_404(db.gardens, garden_id)
    rec = new_record({
        "garden_id": garden_id,
        "tier": tier,
        "annual_fee_cents": annual_fee_cents,
        "admission_included": opt_bool(body, "admission_included", True),
        "event_discount_pct": opt_number(body, "event_discount_pct", 0.2),
        "program_discount_pct": opt_number(body, "program_discount_pct", 0.1),
        "active": opt_bool(body, "active", True),
    })
    db.membership_plans[rec["id"]] = rec
    return success(serialize.membership_plan(rec), status=201)


@bp.route("/v1/membership-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.membership_plans, plan_id)
    return success(serialize.membership_plan(rec), status=200)


@bp.route("/v1/membership-plans", methods=["GET"])
def list_plans():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    tier = request.args.get("tier")
    records = list(db.membership_plans.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if tier is not None:
        records = [r for r in records if r["tier"] == tier]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.membership_plan(r) for r in page],
                        limit, offset, total)
