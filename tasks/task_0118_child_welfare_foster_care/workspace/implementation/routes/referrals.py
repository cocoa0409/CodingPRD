"""Referral routes (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("referrals", __name__)

REPORTER_TYPES = {"MANDATED", "ANONYMOUS", "RELATIVE", "SELF"}
MALTREATMENT_TYPES = {"PHYSICAL_ABUSE", "SEXUAL_ABUSE", "NEGLECT", "EMOTIONAL_ABUSE"}
PRIORITY_FACTORS = {"PRIOR_REPORT", "CAREGIVER_SUBSTANCE", "INJURY_VISIBLE", "AGE_UNDER_3", "NO_CAREGIVER"}


@bp.route("/referrals", methods=["POST"])
def create_referral():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"IntakeScreener"})
    body = helpers.get_body()
    reporter_type = helpers.require_enum(body, "reporter_type", REPORTER_TYPES)
    child_name = helpers.require_str(body, "child_name")
    alleged = helpers.require_enum(body, "alleged_maltreatment", MALTREATMENT_TYPES)
    factors = helpers.require_enum_array(body, "priority_factors", PRIORITY_FACTORS, optional=True)
    record = {
        "status": "RECEIVED",
        "reporter_type": reporter_type,
        "child_name": child_name,
        "alleged_maltreatment": alleged,
        "priority_factors": factors,
        "response_priority": None,
        "screening_score": None,
        "screened_in_by": None,
        "linked_case_id": None,
    }
    db.stamp_create(record)
    db.referrals[record["id"]] = record
    return response.success(serialize.referral(record), 201)


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "IntakeScreener", "Investigator", "Caseworker"})
    record = db.referrals.get(rid)
    if record is None:
        raise errors.not_found("Referral not found.")
    return response.success(serialize.referral(record), 200)


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "IntakeScreener", "Caseworker"})
    limit, offset = helpers.pagination()
    status = request.args.get("status")
    screened_in_by = request.args.get("screened_in_by")
    linked_case_id = request.args.get("linked_case_id")
    records = list(db.referrals.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if screened_in_by is not None:
        records = [r for r in records if r.get("screened_in_by") == screened_in_by]
    if linked_case_id is not None:
        records = [r for r in records if r.get("linked_case_id") == linked_case_id]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.referral(r) for r in page], limit, offset, total)


@bp.route("/referrals/<rid>/screen", methods=["POST"])
def screen_referral(rid):
    user_id, role = middleware.authenticate()
    middleware.authorize(role, {"IntakeScreener"})
    record = db.referrals.get(rid)
    if record is None:
        raise errors.not_found("Referral not found.")
    if record["status"] != "RECEIVED":
        raise errors.invalid_state("Referral is not in RECEIVED status.")
    score, priority = compute.intake_screening_score(record)
    record["screening_score"] = score
    record["response_priority"] = priority
    if score >= compute.SCREEN_IN_THRESHOLD:
        record["status"] = "SCREENED_IN"
        record["screened_in_by"] = user_id
    else:
        record["status"] = "SCREENED_OUT"
        # screened_in_by stays null on the screen-out branch
    db.bump(record)
    return response.success(serialize.referral(record), 200)
