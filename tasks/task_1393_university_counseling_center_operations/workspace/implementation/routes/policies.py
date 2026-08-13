"""SemesterPolicy endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POLICY_CONFLICT,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("policies", __name__)


@bp.route("/ucc/policies", methods=["POST"])
@require_roles("ClinicalDirector")
def create_policy(_user_id: str, _role: str):
    body = get_json_body()
    academic_term = require_string(body, "academic_term")
    base_session_limit = require_int(body, "base_session_limit", minimum=0)
    no_show_strike_limit = require_int(body, "no_show_strike_limit", minimum=1)
    late_cancel_window_hours = require_int(body, "late_cancel_window_hours", minimum=0)

    policy = {
        "academic_term": academic_term,
        "base_session_limit": base_session_limit,
        "no_show_strike_limit": no_show_strike_limit,
        "late_cancel_window_hours": late_cancel_window_hours,
        "policy_status": "DRAFT",
    }
    db.stamp_new(policy)
    db.policies[policy["id"]] = policy
    return success_object(serialize(policy), 201)


@bp.route("/ucc/policies/<policy_id>", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "TriageScreener", "ClinicalDirector", "ReferralCoordinator", "Registrar")
def get_policy(policy_id: str, _user_id: str, _role: str):
    p = db.policies.get(policy_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "SemesterPolicy id does not exist")
    return success_object(serialize(p))


@bp.route("/ucc/policies", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "TriageScreener", "ClinicalDirector", "ReferralCoordinator", "Registrar")
def list_policies(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.policies.values()))
    items = apply_filters(items, ["academic_term", "policy_status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/policies/<policy_id>/publish", methods=["POST"])
@require_roles("ClinicalDirector")
def publish_policy(policy_id: str, _user_id: str, _role: str):
    p = db.policies.get(policy_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "SemesterPolicy id does not exist")
    if p.get("policy_status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "SemesterPolicy is not DRAFT")
    # No other PUBLISHED policy for the same term.
    for other in db.policies.values():
        if (
            other.get("id") != p["id"]
            and other.get("academic_term") == p["academic_term"]
            and other.get("policy_status") == "PUBLISHED"
        ):
            raise_err(ERR_POLICY_CONFLICT, "Another PUBLISHED policy exists for this term")
    p["policy_status"] = "PUBLISHED"
    db.touch(p)
    # Posture sweep: recompute every student's booking_posture under new limit.
    for student in db.students.values():
        domain.recompute_strikes_and_posture(student)
    return success_object(serialize(p))


@bp.route("/ucc/policies/<policy_id>/retire", methods=["POST"])
@require_roles("ClinicalDirector")
def retire_policy(policy_id: str, _user_id: str, _role: str):
    p = db.policies.get(policy_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "SemesterPolicy id does not exist")
    if p.get("policy_status") != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, "SemesterPolicy is not PUBLISHED")
    # A DRAFT replacement for the same term must exist.
    has_draft_replacement = any(
        other.get("id") != p["id"]
        and other.get("academic_term") == p["academic_term"]
        and other.get("policy_status") == "DRAFT"
        for other in db.policies.values()
    )
    if not has_draft_replacement:
        raise_err(ERR_POLICY_CONFLICT, "No DRAFT replacement exists for this term")
    p["policy_status"] = "RETIRED"
    db.touch(p)
    return success_object(serialize(p))
