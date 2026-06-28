"""TreatmentPlan endpoints (PRD §3.4-§3.6)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.listing import paginate
from services.minor import is_minor_for_case
from services.plan_service import (assert_assigned_and_licensed, approve_plan,
                                   decline_plan)
from services.store import get_plan, get_case, fk_case, fk_clinician
from validation import (get_body, require_str, require_int, optional_str,
                        optional_int, parse_pagination)

bp = Blueprint("plans", __name__)


@bp.route("/plans", methods=["POST"])
def create_plan():
    user_id, role = get_auth()
    require_roles(role, {"Clinician"})
    body = get_body()
    case_id = require_str(body, "case_id")
    author_clinician_id = require_str(body, "author_clinician_id")
    proposed_step_count = require_int(body, "proposed_step_count")
    weeks_per_step = require_int(body, "weeks_per_step")
    discount_code = optional_str(body, "discount_code")
    if proposed_step_count < 1:
        raise err("ERR_INVALID_REQUEST", "proposed_step_count must be >= 1.")
    if weeks_per_step < 1:
        raise err("ERR_INVALID_REQUEST", "weeks_per_step must be >= 1.")
    # FK existence
    fk_case(case_id)
    fk_clinician(author_clinician_id)

    rec = base_record(common_fields=True)
    rec.update({
        "case_id": case_id,
        "author_clinician_id": author_clinician_id,
        "revision": 1,
        "status": "DRAFT",
        "proposed_step_count": proposed_step_count,
        "weeks_per_step": weeks_per_step,
        "discount_code": discount_code,
    })
    db.plans[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/plans/<pid>", methods=["GET"])
def fetch_plan(pid):
    _, role = get_auth()
    require_roles(role, {"Clinician", "BillingAdmin", "Patient"})
    rec = get_plan(pid)
    return object_response(serialize(rec), status=200)


@bp.route("/plans", methods=["GET"])
def list_plans():
    _, role = get_auth()
    require_roles(role, {"Clinician", "BillingAdmin", "Patient"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    author_clinician_id = request.args.get("author_clinician_id")
    records = list(db.plans.values())
    if case_id is not None:
        records = [p for p in records if p["case_id"] == case_id]
    if author_clinician_id is not None:
        records = [p for p in records
                   if p["author_clinician_id"] == author_clinician_id]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    user_id, role = get_auth()
    require_roles(role, {"Clinician"})
    plan = get_plan(pid)
    case = get_case(plan["case_id"])
    if plan["status"] != "DRAFT" or case["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  "Plan must be DRAFT and case UNDER_REVIEW to submit.")
    assert_assigned_and_licensed(plan, case, user_id)
    plan["status"] = "SUBMITTED"
    touch(plan)
    return object_response(serialize(plan), status=200)


@bp.route("/plans/<pid>/request-changes", methods=["POST"])
def request_changes(pid):
    user_id, role = get_auth()
    require_roles(role, {"Clinician"})
    plan = get_plan(pid)
    case = get_case(plan["case_id"])
    if plan["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Plan must be SUBMITTED to request changes.")
    assert_assigned_and_licensed(plan, case, user_id)
    plan["status"] = "CHANGES_REQUESTED"
    touch(plan)
    return object_response(serialize(plan), status=200)


@bp.route("/plans/<pid>/resubmit", methods=["POST"])
def resubmit_plan(pid):
    user_id, role = get_auth()
    require_roles(role, {"Clinician"})
    plan = get_plan(pid)
    case = get_case(plan["case_id"])
    if plan["status"] != "CHANGES_REQUESTED":
        raise err("ERR_INVALID_STATE", "Plan must be CHANGES_REQUESTED to resubmit.")
    assert_assigned_and_licensed(plan, case, user_id)
    body = get_body()
    proposed_step_count = optional_int(body, "proposed_step_count")
    weeks_per_step = optional_int(body, "weeks_per_step")
    if "discount_code" in body:
        discount_code = optional_str(body, "discount_code")
        plan["discount_code"] = discount_code
    if proposed_step_count is not None:
        if proposed_step_count < 1:
            raise err("ERR_INVALID_REQUEST", "proposed_step_count must be >= 1.")
        plan["proposed_step_count"] = proposed_step_count
    if weeks_per_step is not None:
        if weeks_per_step < 1:
            raise err("ERR_INVALID_REQUEST", "weeks_per_step must be >= 1.")
        plan["weeks_per_step"] = weeks_per_step
    plan["revision"] += 1
    plan["status"] = "SUBMITTED"
    touch(plan)
    return object_response(serialize(plan), status=200)


@bp.route("/plans/<pid>/approve", methods=["POST"])
def approve(pid):
    user_id, role = get_auth()
    require_roles(role, {"Clinician"})
    plan = get_plan(pid)
    case = get_case(plan["case_id"])
    if plan["status"] != "SUBMITTED" or case["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  "Plan must be SUBMITTED and case UNDER_REVIEW to approve.")
    assert_assigned_and_licensed(plan, case, user_id)
    # guardian-consent gate (priority 11)
    if is_minor_for_case(case) and not case["guardian_consent"]:
        raise err("ERR_GUARDIAN_CONSENT_REQUIRED",
                  "A minor's case cannot be approved without guardian consent.")
    approve_plan(plan, case)
    return object_response(serialize(plan), status=200)


@bp.route("/plans/<pid>/decline-eligibility", methods=["POST"])
def decline_eligibility(pid):
    user_id, role = get_auth()
    require_roles(role, {"Clinician"})
    plan = get_plan(pid)
    case = get_case(plan["case_id"])
    if plan["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Plan must be SUBMITTED to decline.")
    assert_assigned_and_licensed(plan, case, user_id)
    decline_plan(plan, case)
    return object_response(serialize(plan), status=200)
