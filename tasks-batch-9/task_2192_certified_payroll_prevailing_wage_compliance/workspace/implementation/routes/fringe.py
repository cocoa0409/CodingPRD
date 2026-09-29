"""Fringe benefit plans and the agency approval decision."""

from flask import Blueprint, request

import calc
import db
import serializers as s
import validators as v
from auth import ALL_ROLES, acting_staff, authenticate, require_ownership
from response import created, ok, paginated, pagination

bp = Blueprint("fringe", __name__)

PLAN_TYPES = ("BONA_FIDE_TRUST", "UNFUNDED", "CASH_IN_LIEU")


def get_plan(plan_id):
    return v.lookup(db.fringe_plans, plan_id, "ERR_FRINGE_PLAN_NOT_FOUND")


def _recompute_credits(plan):
    annualized, claimed = calc.fringe_hourly_credit(plan)
    plan["annualized_credit_cents"] = annualized
    plan["claimed_credit_cents"] = claimed


@bp.route("/contractors/<contractor_id>/fringe-plans", methods=["POST"])
def declare_plan(contractor_id):
    actor = authenticate(["PayrollPreparer"])
    contractor = v.lookup(db.contractors, contractor_id, "ERR_CONTRACTOR_NOT_FOUND")
    payload = v.body()
    staff = acting_staff(actor)
    require_ownership(staff, contractor["id"])

    plan_name = v.req_string(payload, "plan_name", min_len=1)
    plan_type = v.req_enum(payload, "plan_type", PLAN_TYPES)
    annual_contribution_cents = v.req_int(payload, "annual_contribution_cents", minimum=0)
    annual_total_hours = v.req_hours(payload, "annual_total_hours")
    annual_public_works_hours = v.req_hours(payload, "annual_public_works_hours")
    if annual_total_hours <= 0:
        v.bad("annual_total_hours must be strictly greater than zero.")
    if annual_public_works_hours <= 0:
        v.bad("annual_public_works_hours must be strictly greater than zero.")
    if annual_public_works_hours > annual_total_hours:
        v.bad("annual_public_works_hours may not exceed annual_total_hours.")

    v.unique_or_reject(
        db.fringe_plans,
        lambda r: r["contractor_id"] == contractor["id"] and r["plan_name"] == plan_name,
        "plan_name must be unique within the contractor.",
    )

    row = db.base_row()
    row.update(
        {
            "contractor_id": contractor["id"],
            "plan_name": plan_name,
            "plan_type": plan_type,
            "annual_contribution_cents": annual_contribution_cents,
            "annual_total_hours": annual_total_hours,
            "annual_public_works_hours": annual_public_works_hours,
            "approval_status": "PENDING_APPROVAL",
            "annualized_credit_cents": 0,
            "claimed_credit_cents": 0,
        }
    )
    _recompute_credits(row)
    db.fringe_plans[row["id"]] = row
    return created(s.fringe_plan(row))


@bp.route("/contractors/<contractor_id>/fringe-plans", methods=["GET"])
def list_plans(contractor_id):
    authenticate(ALL_ROLES)
    contractor = v.lookup(db.contractors, contractor_id, "ERR_CONTRACTOR_NOT_FOUND")
    limit, offset = pagination()
    approval_status = request.args.get("approval_status")
    plan_type = request.args.get("plan_type")

    def keep(row):
        if row["contractor_id"] != contractor["id"]:
            return False
        if approval_status is not None and row["approval_status"] != approval_status:
            return False
        if plan_type is not None and row["plan_type"] != plan_type:
            return False
        return True

    return paginated(db.ordered(db.fringe_plans, keep), s.fringe_plan, limit, offset)


@bp.route("/fringe-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    authenticate(["AgencyComplianceOfficer"])
    plan = get_plan(plan_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("APPROVE", "REJECT"))

    plan["approval_status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    _recompute_credits(plan)
    db.touch(plan)
    return ok(s.fringe_plan(plan))
