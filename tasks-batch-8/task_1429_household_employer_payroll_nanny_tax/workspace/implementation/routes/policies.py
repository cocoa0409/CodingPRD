"""WorkersCompPolicy endpoints (PRD 3.11)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STATE_RULES_MISSING,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services.posture import pack_for_state
from services.serializers import serialize_policy
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("policies", __name__)


def get_policy_or_404(policy_id: str) -> dict:
    pol = db.policies.get(policy_id)
    if pol is None:
        raise_err(ERR_NOT_FOUND, "WorkersCompPolicy id does not exist")
    return pol


@bp.route("/household-payroll/employers/<employer_id>/workers-comp-policies", methods=["POST"])
@require_roles("PayrollAdmin")
def create_policy(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    body = get_json_body()
    state_code = require_string(body, "state_code")
    policy_number = require_string(body, "policy_number")
    coverage_start = require_date(body, "coverage_start")
    coverage_end = require_date(body, "coverage_end")
    if coverage_end < coverage_start:
        raise_err(ERR_INVALID_REQUEST, "coverage_end must be on or after coverage_start (closed interval)")

    if pack_for_state(state_code) is None:
        raise_err(ERR_STATE_RULES_MISSING, "No StateRulePack exists for the policy state")

    pol = {
        "employer_id": employer_id,
        "state_code": state_code,
        "policy_number": policy_number,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "status": "QUOTED",
    }
    db.stamp_new(pol)
    db.policies[pol["id"]] = pol
    return success_object(serialize_policy(pol), 201)


@bp.route("/household-payroll/workers-comp-policies/<policy_id>/bind", methods=["POST"])
@require_roles("PayrollAdmin")
def bind_policy(policy_id: str, _user_id: str, _role: str):
    pol = get_policy_or_404(policy_id)
    if pol["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "Only a QUOTED policy can be bound")
    pol["status"] = "BOUND"
    db.touch(pol)
    # A BOUND policy whose coverage window already started activates
    # immediately (the same sweep the clock-set operation runs).
    if db.clock_today() >= pol["coverage_start"]:
        pol["status"] = "ACTIVE"
        db.touch(pol)
    return success_object(serialize_policy(pol))


@bp.route("/household-payroll/workers-comp-policies/<policy_id>/lapse", methods=["POST"])
@require_roles("PayrollAdmin")
def lapse_policy(policy_id: str, _user_id: str, _role: str):
    pol = get_policy_or_404(policy_id)
    if pol["status"] not in ("BOUND", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Only a BOUND or ACTIVE policy can be lapsed")
    pol["status"] = "LAPSED"
    db.touch(pol)
    return success_object(serialize_policy(pol))


@bp.route("/household-payroll/employers/<employer_id>/workers-comp-policies", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_policies(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [p for p in db.policies.values() if p["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_policy(p) for p in page], limit, offset, total)
