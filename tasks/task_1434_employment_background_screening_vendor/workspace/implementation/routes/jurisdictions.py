"""JurisdictionRule endpoints (OCC-guarded patch)."""
from flask import Blueprint

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_STALE, ERR_RULE_NOT_DRAFT,
    ERR_RULE_ALREADY_ACTIVE,
)
from middleware import (
    auth, require_role, get_body, req_str, req_enum, req_int, req_bool,
    opt_enum, opt_int, opt_bool, invalid, ALL_ROLES,
)
from response import success_object

bp = Blueprint("jurisdictions", __name__)

GATE_STAGES = ("POST_CONDITIONAL_OFFER", "ANYTIME")


@bp.route("/jurisdiction-rules", methods=["POST"])
def create_rule():
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()
    code = req_str(body, "jurisdiction_code")
    gate = req_enum(body, "screening_gate_stage", GATE_STAGES)
    lookback = req_int(body, "lookback_years_limit", minimum=0)
    arrests = req_bool(body, "arrest_records_considerable")
    exemption = opt_int(body, "lookback_exemption_salary_cents", minimum=0)
    if exemption is None:
        exemption = 0
    wait_days = req_int(body, "pre_adverse_wait_business_days", minimum=0)
    ia_required = req_bool(body, "individualized_assessment_required")
    credit_allowed = req_bool(body, "credit_check_allowed")
    rule = db.new_entity({
        "jurisdiction_code": code,
        "screening_gate_stage": gate,
        "lookback_years_limit": lookback,
        "arrest_records_considerable": arrests,
        "lookback_exemption_salary_cents": exemption,
        "pre_adverse_wait_business_days": wait_days,
        "individualized_assessment_required": ia_required,
        "credit_check_allowed": credit_allowed,
        "status": "DRAFT",
    })
    db.rules[rule["id"]] = rule
    return success_object(rule, 201)


def _load_rule(rule_id):
    rule = db.rules.get(rule_id)
    if rule is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction rule not found")
    return rule


@bp.route("/jurisdiction-rules/<rule_id>", methods=["GET"])
def get_rule(rule_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_rule(rule_id), 200)


@bp.route("/jurisdiction-rules/<rule_id>", methods=["PATCH"])
def patch_rule(rule_id):
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    rule = _load_rule(rule_id)
    body = get_body()
    # OCC (priority 3.5) — before request shape and state checks
    expected = body.get("expected_jurisdiction_rule_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            invalid("expected_jurisdiction_rule_version must be an integer")
        if expected != rule["version"]:
            raise ApiError(ERR_STALE, 412,
                           "expected_jurisdiction_rule_version does not match "
                           "current version")
    if expected is None:
        invalid("expected_jurisdiction_rule_version is required")
    gate = opt_enum(body, "screening_gate_stage", GATE_STAGES)
    lookback = opt_int(body, "lookback_years_limit", minimum=0)
    arrests = opt_bool(body, "arrest_records_considerable")
    exemption = opt_int(body, "lookback_exemption_salary_cents", minimum=0)
    wait_days = opt_int(body, "pre_adverse_wait_business_days", minimum=0)
    ia_required = opt_bool(body, "individualized_assessment_required")
    credit_allowed = opt_bool(body, "credit_check_allowed")
    if rule["status"] != "DRAFT":
        raise ApiError(ERR_RULE_NOT_DRAFT, 409, "Patch requires rule DRAFT")
    if gate is not None:
        rule["screening_gate_stage"] = gate
    if lookback is not None:
        rule["lookback_years_limit"] = lookback
    if arrests is not None:
        rule["arrest_records_considerable"] = arrests
    if exemption is not None:
        rule["lookback_exemption_salary_cents"] = exemption
    if wait_days is not None:
        rule["pre_adverse_wait_business_days"] = wait_days
    if ia_required is not None:
        rule["individualized_assessment_required"] = ia_required
    if credit_allowed is not None:
        rule["credit_check_allowed"] = credit_allowed
    bump(rule)
    return success_object(rule, 200)


@bp.route("/jurisdiction-rules/<rule_id>/activate", methods=["POST"])
def activate_rule(rule_id):
    auth_uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    rule = _load_rule(rule_id)
    if rule["status"] != "DRAFT":
        raise ApiError(ERR_RULE_NOT_DRAFT, 409,
                       "Activate requires rule DRAFT")
    for other in db.rules.values():
        if (other["id"] != rule["id"]
                and other["jurisdiction_code"] == rule["jurisdiction_code"]
                and other["status"] == "ACTIVE"):
            raise ApiError(ERR_RULE_ALREADY_ACTIVE, 409,
                           "Another ACTIVE rule exists for this jurisdiction_code")
    rule["status"] = "ACTIVE"
    bump(rule)
    return success_object(rule, 200)
