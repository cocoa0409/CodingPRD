"""Management plan endpoints: drafting and OCC-guarded activation (PRD 3.5)."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CADENCE_TOO_LONG,
    ERR_CASE_NOT_PLANNABLE,
    ERR_LE_REFERRAL_REQUIRED,
    ERR_NO_FINALIZED_ASSESSMENT,
    ERR_NOT_FOUND,
    ERR_PLAN_NOT_DRAFT,
    ERR_STALE_CASE_VERSION,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import (
    get_json_body,
    optional_int,
    require_enum,
    require_int,
    require_non_empty_string_list,
    require_string,
)

bp = Blueprint("plans", __name__)

CADENCE_MODES = {"FROM_COMPLETION", "FIXED_ANCHOR"}


def _get_plan_or_404(plan_id: str) -> dict:
    plan = db.management_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "Management plan id does not exist")
    return plan


@bp.route("/management-plans", methods=["POST"])
@require_roles("ThreatAssessor")
def create_plan(_user_id: str, _role: str):
    body = get_json_body()
    case_id = require_string(body, "case_id")
    cadence_mode = require_enum(body, "cadence_mode", CADENCE_MODES)
    conditions = require_non_empty_string_list(body, "conditions")
    cadence_days = optional_int(body, "cadence_days", minimum=1)

    case = domain.get_case_or_404(case_id)
    if case["status"] not in ("UNDER_ASSESSMENT", "PLAN_ACTIVE"):
        raise_err(ERR_CASE_NOT_PLANNABLE,
                  "Plan creation requires status UNDER_ASSESSMENT or PLAN_ACTIVE")
    if not domain.has_finalized_assessment(case["id"]):
        raise_err(ERR_NO_FINALIZED_ASSESSMENT,
                  "Plan creation requires a FINALIZED risk assessment for the case")

    risk_level = case["risk_level"]
    if cadence_days is None:
        cadence_days = domain.DEFAULT_CADENCE_DAYS[risk_level]
    elif cadence_days > domain.MAX_CADENCE_DAYS[risk_level]:
        raise_err(ERR_CADENCE_TOO_LONG,
                  f"cadence_days exceeds the maximum for risk level {risk_level}")

    plan = {
        "case_id": case["id"],
        "cadence_mode": cadence_mode,
        "cadence_days": cadence_days,
        "conditions": conditions,
        "status": "DRAFT",
        "needs_review": False,
        "created_by_user_id": _user_id,
        "activated_at": None,
    }
    db.stamp_new(plan)
    db.management_plans[plan["id"]] = plan
    return success_object(db.public(plan), 201)


@bp.route("/management-plans/<plan_id>/activate", methods=["POST"])
@require_roles("TeamLead")
def activate_plan(plan_id: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_version = require_int(body, "expected_threat_case_version")

    plan = _get_plan_or_404(plan_id)
    case = domain.get_case_or_404(plan["case_id"])

    # OCC runs before any state or business rule (PRD section 2.6).
    if expected_version != case["version"]:
        raise_err(ERR_STALE_CASE_VERSION,
                  "expected_threat_case_version does not match the case's current version")

    # Gates, in the PRD-pinned order.
    if plan["status"] != "DRAFT":
        raise_err(ERR_PLAN_NOT_DRAFT, "Activation requires plan status DRAFT")
    if case["status"] not in ("UNDER_ASSESSMENT", "PLAN_ACTIVE"):
        raise_err(ERR_CASE_NOT_PLANNABLE,
                  "Plan activation requires status UNDER_ASSESSMENT or PLAN_ACTIVE")
    if case["risk_level"] in ("HIGH", "IMMINENT") and not domain.has_acknowledged_le_referral(case["id"]):
        raise_err(ERR_LE_REFERRAL_REQUIRED,
                  "HIGH/IMMINENT case plan activation requires an ACKNOWLEDGED "
                  "LAW_ENFORCEMENT referral")
    if not domain.has_finalized_assessment(case["id"]):
        raise_err(ERR_NO_FINALIZED_ASSESSMENT,
                  "Plan activation requires a FINALIZED risk assessment for the case")

    # Side effects.
    plan["status"] = "ACTIVE"
    plan["activated_at"] = db.now_logical_iso()
    db.touch(plan)

    # Prior ACTIVE plan supersedes; it also sheds any needs_review flag.
    for other in domain.case_children(db.management_plans, case["id"]):
        if other["id"] != plan["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            other["needs_review"] = False
            db.touch(other)
            domain.audit(case["id"], "PLAN_SUPERSEDED",
                         f"Prior ACTIVE plan {other['id']} superseded by plan {plan['id']}",
                         _user_id, _role)

    case["status"] = "PLAN_ACTIVE"
    case["monitoring_cadence_days"] = plan["cadence_days"]
    case["escalation_flag"] = False  # plan activation is the only way the flag comes down
    db.touch(case)  # exactly one case-version increment for the activation

    domain.audit(case["id"], "PLAN_ACTIVATED",
                 f"Management plan {plan['id']} activated with cadence {plan['cadence_days']} "
                 f"days ({plan['cadence_mode']})", _user_id, _role)

    # First monitoring check-in, due current date + cadence_days, unless a
    # SCHEDULED/MISSED check-in already occupies that calendar day.
    first_due = (db.clock().date() + timedelta(days=plan["cadence_days"])).isoformat()
    domain.auto_create_checkin(case["id"], first_due, respect_day_exclusion=True)

    return success_object(db.public(plan))
