"""Registry cases: creation and inclusion, locking, triage adjudication, the
transfer-out pair and response-time documentation (PRD 3.2, 3.4, 3.5, 3.6)."""
from flask import Blueprint

import calc
import cascade
import serializers as ser
from auth import ALL_ROLES, identity, require_roles, require_scope
from common import D, new_record, num, sorted_records
from envelope import respond_list, respond_object, touch
from errors import ApiError
from store import clock_now, db
from validate import (
    check_enum,
    filter_eq,
    get_body,
    opt_dt,
    opt_str,
    paginate,
    req_dt,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("cases", __name__)

ED_DISPOSITIONS = ("ADMIT", "TRANSFER_OUT", "DISCHARGE", "MORGUE")
TRIAGE_OUTCOMES = ("UNDER_TRIAGE_CONFIRMED", "OVER_TRIAGE_CONFIRMED", "APPROPRIATE")
RESPONDER_ROLES = ("SURGEON", "ANESTHESIA", "NEUROSURGERY", "ORTHOPEDICS", "RADIOLOGY")
CASE_READ_ROLES = [
    "SystemAdmin",
    "TraumaProgramManager",
    "RegistryAbstractor",
    "RegistryValidator",
    "TraumaMedicalDirector",
    "VerificationReviewer",
]


def load_case(case_id):
    case = db.cases.get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return case


@bp.route("/registry-cases", methods=["POST"])
def create_case():
    user_id, role = identity()
    require_roles(role, ["RegistryAbstractor", "TraumaProgramManager"])
    body = get_body()
    center_raw = body.get("center_id")
    require_scope(user_id, role, center_raw if isinstance(center_raw, str) else None)
    center_id = req_str(body, "center_id")
    center = db.centers.get(center_id)
    if center is None:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    transfer_in = opt_str(body, "transfer_in_from_center_id")
    if transfer_in is not None and transfer_in not in db.centers:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    tier_id = req_str(body, "activation_tier_id")
    tier = db.tiers.get(tier_id)
    if tier is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    mrn = req_str(body, "mrn")
    arrival_at = req_dt(body, "arrival_at")
    iss = req_int(body, "injury_severity_score", 0, 75)
    los_hours = req_num(body, "los_hours", lo=0)
    ed_disposition = opt_str(body, "ed_disposition", "ADMIT")
    check_enum(ed_disposition, ED_DISPOSITIONS)
    for existing in db.cases.values():
        if existing["center_id"] == center_id and existing["mrn"] == mrn:
            raise ApiError("ERR_DUPLICATE_CASE_MRN")
    record = new_record()
    record.update(
        {
            "center_id": center_id,
            "activation_tier_id": tier_id,
            "mrn": mrn,
            "arrival_at": arrival_at,
            "injury_severity_score": iss,
            "los_hours": los_hours,
            "ed_disposition": ed_disposition,
            "transfer_in_from_center_id": transfer_in,
            "transfer_out_to_center_id": None,
            "abstraction_status": "PENDING",
            "triage_review_status": "UNREVIEWED",
            "effective_iss": iss,
            "inclusion_status": "INCLUDED",
            "inclusion_reason": "MEETS_INCLUSION_CRITERIA",
            "locked_at": None,
            "review_note": None,
        }
    )
    db.cases[record["id"]] = record
    calc.apply_inclusion(record)
    cascade.cascade_center(center)
    return respond_object(lambda: ser.case(record), 201)


@bp.route("/registry-cases/<case_id>", methods=["GET"])
def read_case(case_id):
    user_id, role = identity()
    require_roles(role, ALL_ROLES)
    case = load_case(case_id)
    return respond_object(lambda: ser.case(case))


@bp.route("/registry-cases", methods=["GET"])
def list_cases():
    user_id, role = identity()
    require_roles(role, ALL_ROLES)
    records = sorted_records(list(db.cases.values()))
    for field in (
        "center_id",
        "activation_tier_id",
        "transfer_in_from_center_id",
        "transfer_out_to_center_id",
        "abstraction_status",
        "inclusion_status",
        "triage_review_status",
    ):
        records = filter_eq(records, field)
    page, meta = paginate(records)
    return respond_list(lambda: [ser.case(r) for r in page], meta)


@bp.route("/registry-cases/<case_id>/lock", methods=["POST"])
def lock_case(case_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    case = load_case(case_id)
    require_scope(user_id, role, case["center_id"])
    center = db.centers.get(case["center_id"])
    if case["abstraction_status"] == "LOCKED":
        raise ApiError("ERR_CASE_ALREADY_LOCKED")
    if cascade.posture_of(center) == "SUSPENDED":
        raise ApiError("ERR_POSTURE_SUSPENDED")
    latest = calc.abstractions_of_case(case_id)
    if (
        case["abstraction_status"] != "VALIDATED"
        or not latest
        or latest[-1]["validation_status"] != "VALIDATED"
    ):
        raise ApiError("ERR_ABSTRACTION_NOT_VALIDATED")
    case["abstraction_status"] = "LOCKED"
    case["locked_at"] = clock_now()
    touch(case)
    return respond_object(lambda: ser.case(case))


@bp.route("/registry-cases/<case_id>/triage-review", methods=["POST"])
def triage_review(case_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector"])
    case = load_case(case_id)
    body = get_body()
    outcome = req_str(body, "triage_review_status")
    review_note = opt_str(body, "review_note")
    check_enum(outcome, TRIAGE_OUTCOMES)
    if case["triage_review_status"] != "UNREVIEWED":
        raise ApiError("ERR_TRIAGE_ALREADY_REVIEWED")
    if case["inclusion_status"] != "INCLUDED":
        # an excluded case is not part of the denominator the rates are computed over
        raise ApiError("ERR_TRIAGE_ALREADY_REVIEWED")
    case["triage_review_status"] = outcome
    if review_note is not None:
        case["review_note"] = review_note
    touch(case)
    center = db.centers.get(case["center_id"])
    cascade.cascade_center(center, rates=True, cycles=True)
    return respond_object(lambda: ser.case(case))


@bp.route("/registry-cases/<case_id>/transfer-out", methods=["POST"])
def transfer_out(case_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager", "RegistryAbstractor"])
    case = load_case(case_id)
    require_scope(user_id, role, case["center_id"])
    body = get_body()
    receiving_id = req_str(body, "transfer_out_to_center_id")
    if receiving_id not in db.centers:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    if case["abstraction_status"] == "LOCKED":
        raise ApiError("ERR_CASE_ALREADY_LOCKED")
    if case["transfer_out_to_center_id"] is not None:
        raise ApiError("ERR_CASE_ALREADY_LOCKED")
    agreement = calc.active_agreement_covering(
        case["center_id"], receiving_id, case["arrival_at"]
    )
    if agreement is None:
        raise ApiError("ERR_NO_ACTIVE_REFERRAL_AGREEMENT")
    case["transfer_out_to_center_id"] = receiving_id
    case["ed_disposition"] = "TRANSFER_OUT"
    touch(case)
    calc.apply_inclusion(case)
    center = db.centers.get(case["center_id"])
    cascade.cascade_center(center, rates=True, cycles=True)
    return respond_object(lambda: ser.case(case))


@bp.route("/registry-cases/<case_id>/transfer-out/rescind", methods=["POST"])
def rescind_transfer_out(case_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    case = load_case(case_id)
    require_scope(user_id, role, case["center_id"])
    body = get_body()
    reason = req_str(body, "rescind_reason")
    if case["abstraction_status"] == "LOCKED":
        raise ApiError("ERR_CASE_ALREADY_LOCKED")
    if case["transfer_out_to_center_id"] is None:
        raise ApiError("ERR_CASE_ALREADY_LOCKED")
    case["transfer_out_to_center_id"] = None
    case["ed_disposition"] = "ADMIT"
    case["rescind_reason"] = reason
    touch(case)
    calc.apply_inclusion(case)
    center = db.centers.get(case["center_id"])
    cascade.cascade_center(center, rates=True, cycles=True)
    return respond_object(lambda: ser.case(case))


# --- response logs --------------------------------------------------------


@bp.route("/registry-cases/<case_id>/response-logs", methods=["POST"])
def create_response_log(case_id):
    user_id, role = identity()
    require_roles(role, ["RegistryAbstractor", "TraumaProgramManager"])
    case = load_case(case_id)
    require_scope(user_id, role, case["center_id"])
    body = get_body()
    responder_role = req_str(body, "responder_role")
    responder_user_id = req_str(body, "responder_user_id")
    notified_at = req_dt(body, "notified_at")
    arrived_at = opt_dt(body, "arrived_at")
    check_enum(responder_role, RESPONDER_ROLES)
    minutes, limit, status = calc.response_compliance(
        case, responder_role, notified_at, arrived_at
    )
    record = new_record()
    record.update(
        {
            "case_id": case_id,
            "responder_role": responder_role,
            "responder_user_id": responder_user_id,
            "notified_at": notified_at,
            "arrived_at": arrived_at,
            "response_minutes": None if minutes is None else num(minutes),
            "applicable_limit_minutes": limit,
            "compliance_status": status,
        }
    )
    db.response_logs[record["id"]] = record
    center = db.centers.get(case["center_id"])
    if responder_role == "SURGEON" and status in ("LATE", "UNDOCUMENTED"):
        cascade.create_pi_event(
            center,
            "DELAYED_SURGEON",
            "HIGH",
            case_id=case_id,
            due_days=calc.LOOP_CLOSURE_DAYS,
        )
        cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.response_log(record), 201)


@bp.route("/registry-cases/<case_id>/response-logs", methods=["GET"])
def list_response_logs(case_id):
    user_id, role = identity()
    require_roles(role, CASE_READ_ROLES)
    case = load_case(case_id)
    records = sorted_records(
        [r for r in db.response_logs.values() if r["case_id"] == case_id]
    )
    records = filter_eq(records, "responder_role")
    records = filter_eq(records, "compliance_status")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.response_log(r) for r in page], meta)
