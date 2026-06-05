"""Investigation routes (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("investigations", __name__)

SAFETY_FACTORS = {"NO_FOOD", "VIOLENCE_PRESENT", "SUPERVISION_ABSENT", "MEDICAL_NEGLECT", "DRUG_ENV", "UNSAFE_SLEEP"}


@bp.route("/investigations", methods=["POST"])
def create_investigation():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    body = helpers.get_body()
    referral_id = helpers.require_str(body, "referral_id")
    investigator_id = helpers.require_str(body, "investigator_id")
    safety_factors = helpers.require_enum_array(body, "safety_factors", SAFETY_FACTORS, optional=True)
    protective_capacity = None
    if "protective_capacity" in body and body["protective_capacity"] is not None:
        protective_capacity = helpers.require_int(body, "protective_capacity")
        if protective_capacity < 0 or protective_capacity > 10:
            raise errors.validation_limit("protective_capacity must be between 0 and 10.")

    # Existence: body FKs resolved left-to-right (referral, then investigator).
    referral = db.referrals.get(referral_id)
    if referral is None:
        raise errors.not_found("Referral not found.")
    investigator = db.caseworkers.get(investigator_id)
    if investigator is None:
        raise errors.not_found("Investigator (caseworker) not found.")

    # Referral must be SCREENED_IN.
    if referral["status"] != "SCREENED_IN":
        raise errors.referral_not_screened_in()

    # Segregation of duties: investigator_id must not equal screened_in_by.
    if investigator_id == referral.get("screened_in_by"):
        raise errors.sod_conflict()

    record = {
        "referral_id": referral_id,
        "investigator_id": investigator_id,
        "status": "ASSIGNED",
        "safety_factors": safety_factors,
        "protective_capacity": protective_capacity,
        "safety_decision_score": None,
        "removal_recommended": None,
    }
    db.stamp_create(record)
    db.investigations[record["id"]] = record
    return response.success(serialize.investigation(record), 201)


@bp.route("/investigations/<iid>", methods=["GET"])
def get_investigation(iid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Investigator"})
    record = db.investigations.get(iid)
    if record is None:
        raise errors.not_found("Investigation not found.")
    return response.success(serialize.investigation(record), 200)


@bp.route("/investigations", methods=["GET"])
def list_investigations():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Investigator"})
    limit, offset = helpers.pagination()
    referral_id = request.args.get("referral_id")
    investigator_id = request.args.get("investigator_id")
    status = request.args.get("status")
    records = list(db.investigations.values())
    if referral_id is not None:
        records = [r for r in records if r["referral_id"] == referral_id]
    if investigator_id is not None:
        records = [r for r in records if r["investigator_id"] == investigator_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.investigation(r) for r in page], limit, offset, total)


@bp.route("/investigations/<iid>/start", methods=["POST"])
def start_investigation(iid):
    user_id, role = middleware.authenticate()
    middleware.authorize(role, {"Investigator"})
    record = db.investigations.get(iid)
    if record is None:
        raise errors.not_found("Investigation not found.")
    # Only the assigned investigator may act; otherwise the state guard fails.
    if record["status"] != "ASSIGNED" or record["investigator_id"] != user_id:
        raise errors.invalid_state("Investigation cannot be started by this actor or from this state.")
    record["status"] = "IN_PROGRESS"
    db.bump(record)
    return response.success(serialize.investigation(record), 200)


@bp.route("/investigations/<iid>/decision", methods=["POST"])
def decide_investigation(iid):
    user_id, role = middleware.authenticate()
    middleware.authorize(role, {"Investigator"})
    record = db.investigations.get(iid)
    if record is None:
        raise errors.not_found("Investigation not found.")
    body = helpers.get_body()
    safety_factors = helpers.require_enum_array(body, "safety_factors", SAFETY_FACTORS, optional=False)
    protective_capacity = helpers.require_int(body, "protective_capacity")
    if protective_capacity < 0 or protective_capacity > 10:
        raise errors.validation_limit("protective_capacity must be between 0 and 10.")
    # State + actor guard: only IN_PROGRESS and the assigned investigator.
    if record["status"] != "IN_PROGRESS" or record["investigator_id"] != user_id:
        raise errors.invalid_state("Decision cannot be recorded by this actor or from this state.")

    record["safety_factors"] = safety_factors
    record["protective_capacity"] = protective_capacity
    score, status, removal = compute.safety_assessment_score(safety_factors, protective_capacity)
    record["safety_decision_score"] = score
    record["removal_recommended"] = removal
    record["status"] = status
    db.bump(record)
    return response.success(serialize.investigation(record), 200)
