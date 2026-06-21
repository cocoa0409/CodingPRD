"""InsurancePolicy resource (PRD §3.10)."""

from flask import Blueprint, request

import db
import services
from errors import invalid_request, not_found
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("insurance_policies", __name__)

PLAN_TYPES = {"EMPLOYER_GROUP", "MARKETPLACE", "MEDICAID"}
ENROLLMENT_STATUSES = {"PENDING", "ENROLLED", "SEP_EXPIRED", "DENIED", "TERMINATED"}


@bp.post("/insurance-policies")
def create_policy():
    require_roles("BenefitsCoordinator", "RegistrySupervisor")
    body = get_body()
    carrier_name = require_field(body, "carrier_name", str)
    subscriber_name = require_field(body, "subscriber_name", str)
    plan_type = require_field(body, "plan_type", str)
    require_enum(plan_type, "plan_type", PLAN_TYPES)
    coverage_effective_date = require_field(body, "coverage_effective_date", str)
    dependent_slots_max = require_field(body, "dependent_slots_max", int)
    if dependent_slots_max < 1:
        raise invalid_request("dependent_slots_max must be >= 1.")
    row = {
        "id": db.new_id(),
        "carrier_name": carrier_name,
        "subscriber_name": subscriber_name,
        "plan_type": plan_type,
        "coverage_effective_date": coverage_effective_date,
        "dependent_slots_max": dependent_slots_max,
        "dependents_added_count": 0,
    }
    db.stamp_create(row)
    db.insurance_policies[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/insurance-policies/<policy_id>")
def get_policy(policy_id):
    require_roles("BenefitsCoordinator", "RegistrySupervisor")
    row = db.insurance_policies.get(policy_id)
    if row is None:
        raise not_found("Insurance policy not found.")
    services.recompute_dependents_added_count(policy_id)
    return ok_object(db.public(row))


@bp.get("/insurance-policies/<policy_id>/dependent-enrollments")
def list_policy_enrollments(policy_id):
    require_roles("BenefitsCoordinator", "RegistrySupervisor")
    if db.insurance_policies.get(policy_id) is None:
        raise not_found("Insurance policy not found.")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = [e for e in db.dependent_enrollments.values() if e["policy_id"] == policy_id]
    if status is not None:
        require_enum(status, "status", ENROLLMENT_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)
