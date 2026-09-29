"""Abstraction submission, the pinned data-dictionary scan and adjudication
(PRD 3.3)."""
from flask import Blueprint

import calc
import cascade
import serializers as ser
from common import D, days, new_record, num, rhu, sorted_records
from auth import identity, require_roles
from envelope import respond_list, respond_object, touch
from errors import ApiError
from store import clock_now, db
from validate import (
    filter_eq,
    get_body,
    opt_int,
    opt_str,
    paginate,
    req_int,
    req_str,
)
from common import parse_dt
from routes.cases import CASE_READ_ROLES, load_case

bp = Blueprint("abstractions", __name__)


def load_abstraction(abstraction_id):
    record = db.abstractions.get(abstraction_id)
    if record is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return record


@bp.route("/registry-cases/<case_id>/abstractions", methods=["POST"])
def submit_abstraction(case_id):
    user_id, role = identity()
    require_roles(role, ["RegistryAbstractor"])
    case = load_case(case_id)
    body = get_body()
    expected_version = req_int(body, "expected_case_version")
    iss_abstracted = opt_int(body, "iss_abstracted")
    gcs_arrival = opt_int(body, "gcs_arrival")
    mechanism_code = opt_str(body, "mechanism_code")
    ed_departure_raw = body.get("ed_departure_at")
    ed_departure_at = None
    if ed_departure_raw is not None:
        if not isinstance(ed_departure_raw, str):
            raise ApiError("ERR_INVALID_REQUEST")
        ed_departure_at = parse_dt(ed_departure_raw)
        if ed_departure_at is None:
            raise ApiError("ERR_INVALID_REQUEST")
    # Band D: optimistic concurrency on the parent case version
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    # Band E: the case must still be abstractable
    if case["abstraction_status"] not in ("PENDING", "ABSTRACTED", "REJECTED"):
        raise ApiError("ERR_CASE_NOT_ABSTRACTABLE")
    center = db.centers.get(case["center_id"])
    values = {
        "iss_abstracted": iss_abstracted,
        "gcs_arrival": gcs_arrival,
        "mechanism_code": mechanism_code,
        "ed_departure_at": ed_departure_raw,
    }
    # STEP 1: the band reads the score as persisted at the start of this request
    score_at_request_start = D(center["registry_compliance_score"])
    multiplier = calc.band_multiplier(score_at_request_start)
    # STEP 2: find the violations
    violations, error_count, raw_penalty = calc.dictionary_scan(values)
    # Band F: any CRITICAL violation refuses the submission before STEP 3 runs
    for rule in violations:
        if rule["severity"] == "CRITICAL":
            raise ApiError("ERR_DICTIONARY_CRITICAL_VIOLATION")
    # Band G: the 60-day abstraction window
    if clock_now() > case["arrival_at"] + days(calc.ABSTRACTION_WINDOW_DAYS):
        raise ApiError("ERR_ABSTRACTION_WINDOW_CLOSED")
    # STEP 3 and STEP 4
    applied = rhu(D(raw_penalty) * multiplier)
    center["registry_compliance_score"] = num(
        max(D("0.00"), score_at_request_start - applied)
    )
    for prior in calc.abstractions_of_case(case_id):
        if prior["validation_status"] == "SUBMITTED":
            prior["validation_status"] = "REJECTED"
            prior["rejection_reason"] = "SUPERSEDED_BY_RESUBMISSION"
    record = new_record()
    record.update(
        {
            "case_id": case_id,
            "submitted_by_user_id": user_id,
            "iss_abstracted": iss_abstracted,
            "gcs_arrival": gcs_arrival,
            "mechanism_code": mechanism_code,
            "ed_departure_at": ed_departure_at,
            "validation_status": "SUBMITTED",
            "validated_by_user_id": None,
            "rejection_reason": None,
            "dictionary_error_count": error_count,
            "applied_penalty_points": num(applied),
            "band_multiplier_used": float(multiplier),
        }
    )
    db.abstractions[record["id"]] = record
    case["abstraction_status"] = "ABSTRACTED"
    touch(case)
    cascade.cascade_center(
        center, cycles=True, cycle_statuses=cascade.ABSTRACTION_REFRESH_STATUSES
    )
    return respond_object(lambda: ser.abstraction(record), 201)


@bp.route("/registry-cases/<case_id>/abstractions", methods=["GET"])
def list_abstractions(case_id):
    user_id, role = identity()
    require_roles(role, CASE_READ_ROLES)
    case = load_case(case_id)
    records = calc.abstractions_of_case(case_id)
    records = filter_eq(records, "validation_status")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.abstraction(r) for r in page], meta)


@bp.route("/abstractions/<abstraction_id>/validate", methods=["POST"])
def validate_abstraction(abstraction_id):
    user_id, role = identity()
    require_roles(role, ["RegistryValidator"])
    record = load_abstraction(abstraction_id)
    if record["validation_status"] != "SUBMITTED":
        raise ApiError("ERR_ABSTRACTION_ALREADY_ADJUDICATED")
    if user_id == record["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    record["validation_status"] = "VALIDATED"
    record["validated_by_user_id"] = user_id
    case = db.cases.get(record["case_id"])
    center = db.centers.get(case["center_id"]) if case else None
    if case is not None:
        case["abstraction_status"] = "VALIDATED"
        touch(case)
        calc.apply_inclusion(case)
    cascade.cascade_center(center, rates=True)
    return respond_object(lambda: ser.abstraction(record))


@bp.route("/abstractions/<abstraction_id>/reject", methods=["POST"])
def reject_abstraction(abstraction_id):
    user_id, role = identity()
    require_roles(role, ["RegistryValidator"])
    record = load_abstraction(abstraction_id)
    body = get_body()
    reason = req_str(body, "rejection_reason")
    if record["validation_status"] != "SUBMITTED":
        raise ApiError("ERR_ABSTRACTION_ALREADY_ADJUDICATED")
    if user_id == record["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    record["validation_status"] = "REJECTED"
    record["validated_by_user_id"] = user_id
    record["rejection_reason"] = reason
    case = db.cases.get(record["case_id"])
    center = db.centers.get(case["center_id"]) if case else None
    if case is not None:
        case["abstraction_status"] = "REJECTED"
        touch(case)
    if center is not None:
        # restore exactly the penalty points this record had deducted
        restored = D(center["registry_compliance_score"]) + D(record["applied_penalty_points"])
        center["registry_compliance_score"] = num(min(D("100.00"), restored))
    cascade.cascade_center(center)
    return respond_object(lambda: ser.abstraction(record))
