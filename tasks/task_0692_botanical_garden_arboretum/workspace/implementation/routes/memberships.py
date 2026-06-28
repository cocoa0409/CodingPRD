"""Membership routes + lifecycle (PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import db, now
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize, calc, cascade
from services.common import (
    new_record, get_body, get_or_404, paginate, touch, check_owner,
    req_str, opt_str, opt_bool, req_str_array,
)

bp = Blueprint("memberships", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}
WRITE_ROLES = {"Visitor", "GardenStaff"}
RENEWAL_WINDOW = timedelta(days=30)
TERM = timedelta(days=365)


def _check_household_roster(plan, names):
    """Household-cap rule (PRD §3.2): HOUSEHOLD <= cap; others must be empty."""
    garden = db.gardens.get(plan["garden_id"])
    cap = garden["household_member_cap"] if garden is not None else 0
    if plan["tier"] == "HOUSEHOLD":
        if len(names) > cap:
            raise errors.household_cap_exceeded()
    else:
        if len(names) > 0:
            raise errors.household_cap_exceeded()


@bp.route("/v1/memberships", methods=["POST"])
def create_membership():
    _, role = get_identity()
    require_role(role, WRITE_ROLES)
    body = get_body()
    garden_id = req_str(body, "garden_id")
    plan_id = req_str(body, "plan_id")
    primary = req_str(body, "primary_member_name")
    household = req_str_array(body, "household_member_names", default=[])
    auto_renew = opt_bool(body, "auto_renew", False)

    # Existence left-to-right: garden then plan (PRD §2.7).
    get_or_404(db.gardens, garden_id)
    plan = get_or_404(db.membership_plans, plan_id)
    # Same-garden referential integrity (PRD §2.7).
    if plan["garden_id"] != garden_id:
        raise errors.cross_garden_reference()
    # Household cap guards creation (PRD §3.2).
    _check_household_roster(plan, household)

    rec = new_record({
        "garden_id": garden_id,
        "plan_id": plan_id,
        "primary_member_name": primary,
        "household_member_names": household,
        "status": "PENDING",
        "auto_renew": auto_renew,
        "term_start": None,
        "term_end": None,
        "paid_total_cents": 0,
        "guest_passes_remaining": 0,
        "renewal_count": 0,
    })
    db.memberships[rec["id"]] = rec
    return success(serialize.membership(rec), status=201)


@bp.route("/v1/memberships/<membership_id>", methods=["GET"])
def read_membership(membership_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.memberships, membership_id)
    return success(serialize.membership(rec), status=200)


@bp.route("/v1/memberships", methods=["GET"])
def list_memberships():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    records = list(db.memberships.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.membership(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/memberships/<membership_id>/activate", methods=["POST"])
def activate_membership(membership_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    m = get_or_404(db.memberships, membership_id)
    # Ownership: for a membership resource the owning membership is itself.
    check_owner(role, user_id, m["id"])
    # State (PRD §3.2): only PENDING may activate.
    if m["status"] != "PENDING":
        raise errors.invalid_state()
    plan = db.membership_plans.get(m["plan_id"])
    if plan is None:
        raise errors.not_found()
    if not plan["active"]:
        raise errors.plan_inactive()
    # Household check guards activation too (PRD §3.2).
    _check_household_roster(plan, m["household_member_names"])

    current = now()
    charge = calc.join_fee_charge(plan["annual_fee_cents"])
    m["status"] = "ACTIVE"
    m["paid_total_cents"] = charge
    m["term_start"] = current
    m["term_end"] = current + TERM
    garden = db.gardens.get(m["garden_id"])
    m["guest_passes_remaining"] = calc.guest_pass_grant(
        plan["tier"], garden["guest_pass_grant_household"],
        garden["guest_pass_grant_patron"])
    # renewal_count stays 0
    touch(m)
    return success(serialize.membership(m), status=200)


@bp.route("/v1/memberships/<membership_id>/renew", methods=["POST"])
def renew_membership(membership_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    m = get_or_404(db.memberships, membership_id)
    check_owner(role, user_id, m["id"])
    if m["status"] != "ACTIVE":
        raise errors.invalid_state()

    current = now()
    # Renewal window: now >= term_end - 30d, OR auto_renew is true (PRD §3.2).
    window_open = current >= (m["term_end"] - RENEWAL_WINDOW)
    if not window_open and not m["auto_renew"]:
        raise errors.renewal_window_not_open()

    plan = db.membership_plans.get(m["plan_id"])
    charge = calc.renewal_credit_charge(plan["annual_fee_cents"],
                                        m["term_end"], current)
    old_term_end = m["term_end"]
    m["paid_total_cents"] = m["paid_total_cents"] + charge
    m["term_start"] = old_term_end
    m["term_end"] = old_term_end + TERM
    garden = db.gardens.get(m["garden_id"])
    m["guest_passes_remaining"] = calc.guest_pass_grant(
        plan["tier"], garden["guest_pass_grant_household"],
        garden["guest_pass_grant_patron"])
    m["renewal_count"] = m["renewal_count"] + 1
    touch(m)
    return success(serialize.membership(m), status=200)


@bp.route("/v1/memberships/<membership_id>/reinstate", methods=["POST"])
def reinstate_membership(membership_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    m = get_or_404(db.memberships, membership_id)
    check_owner(role, user_id, m["id"])
    if m["status"] != "LAPSED":
        raise errors.invalid_state()
    plan = db.membership_plans.get(m["plan_id"])
    if plan is None:
        raise errors.not_found()
    if not plan["active"]:
        raise errors.plan_inactive()

    current = now()
    charge = calc.join_fee_charge(plan["annual_fee_cents"])
    m["status"] = "ACTIVE"
    m["paid_total_cents"] = m["paid_total_cents"] + charge
    m["term_start"] = current
    m["term_end"] = current + TERM
    garden = db.gardens.get(m["garden_id"])
    m["guest_passes_remaining"] = calc.guest_pass_grant(
        plan["tier"], garden["guest_pass_grant_household"],
        garden["guest_pass_grant_patron"])
    m["renewal_count"] = m["renewal_count"] + 1
    touch(m)
    return success(serialize.membership(m), status=200)


@bp.route("/v1/memberships/<membership_id>/lapse", methods=["POST"])
def lapse_membership_route(membership_id):
    _, role = get_identity()
    require_role(role, {"GardenAdmin", "GardenStaff"})
    m = get_or_404(db.memberships, membership_id)
    if m["status"] != "ACTIVE":
        raise errors.invalid_state()
    cascade.lapse_membership(m)
    return success(serialize.membership(m), status=200)


@bp.route("/v1/memberships/<membership_id>/cancel", methods=["POST"])
def cancel_membership_route(membership_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    m = get_or_404(db.memberships, membership_id)
    check_owner(role, user_id, m["id"])
    if m["status"] not in {"PENDING", "ACTIVE", "LAPSED"}:
        raise errors.invalid_state()
    cascade.cancel_membership(m)
    return success(serialize.membership(m), status=200)
