"""UtilizationCase endpoints: open, list, get, discharge."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_STATE, ERR_VALIDATION_FAILED
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.calculations import midnight_count, benchmark_met
from services.clock import parse_iso
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_string, validate_datetime,
)

bp = Blueprint("cases", __name__)

ADMISSION_STATUSES = {"INPATIENT", "OBSERVATION"}
REVIEW_STATUSES = {"INTAKE", "ADMISSION_REVIEWED", "MONITORING", "CLOSED"}
AUTH_STATUSES = {"AUTH_PENDING", "AUTH_IN_PROGRESS", "AUTHORIZED", "DENIED"}

CASE_CREATE_FIELDS = [
    "patient_mrn", "payer_id", "attending_physician_id",
    "admit_at", "expected_discharge_at", "requested_admission_status",
]


def case_view(case):
    """Serialize a case with current computed values."""
    return dict(case)


@bp.post("/api/utilization-cases")
def create_case():
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, CASE_CREATE_FIELDS)
    validate_string(body, "patient_mrn")
    validate_string(body, "payer_id")
    validate_string(body, "attending_physician_id")
    admit_at = validate_datetime(body, "admit_at")
    expected_discharge_at = validate_datetime(body, "expected_discharge_at")
    validate_enum(body, "requested_admission_status", ADMISSION_STATUSES)

    # Referential existence: payer and attending physician must exist
    lookup(db.payers, body["payer_id"], "Payer")
    lookup(db.physicians, body["attending_physician_id"], "Physician")

    expected_midnights = midnight_count(admit_at, expected_discharge_at)
    case = {
        **init_common(),
        "patient_mrn": body["patient_mrn"],
        "payer_id": body["payer_id"],
        "attending_physician_id": body["attending_physician_id"],
        "admit_at": body["admit_at"],
        "expected_discharge_at": body["expected_discharge_at"],
        "discharge_at": None,
        "requested_admission_status": body["requested_admission_status"],
        "current_admission_status": body["requested_admission_status"],
        "review_status": "INTAKE",
        "auth_status": "AUTH_PENDING",
        "expected_midnight_count": expected_midnights,
        "actual_midnight_count": None,
        "two_midnight_benchmark_met": benchmark_met(expected_midnights),
        "benchmark_basis": "PROVISIONAL",
        "certified_day_count": 0,
        "certified_inpatient_day_count": 0,
        "certified_observation_day_count": 0,
        "open_avoidable_day_count": 0,
        "escalation_tier": 0,
    }
    db.utilization_cases[case["id"]] = case
    append_audit(case["id"], "CASE_OPENED", role, user_id,
                 f"Case opened for patient {case['patient_mrn']}")
    return success_object(case_view(case), 201)


@bp.get("/api/utilization-cases")
def list_cases():
    any_authenticated()
    items = sorted(db.utilization_cases.values(), key=lambda c: c["created_at"])
    for param, allowed in (
        ("payer_id", None),
        ("attending_physician_id", None),
        ("review_status", REVIEW_STATUSES),
        ("auth_status", AUTH_STATUSES),
    ):
        if param in request.args:
            v = request.args[param]
            if allowed is not None and v not in allowed:
                raise ApiError(ERR_VALIDATION_FAILED, f"Invalid {param}: {v}", 400)
            items = [c for c in items if c[param] == v]
    return paginate([case_view(c) for c in items])


@bp.get("/api/utilization-cases/<cid>")
def get_case(cid):
    any_authenticated()
    return success_object(case_view(lookup(db.utilization_cases, cid, "UtilizationCase")))


@bp.post("/api/utilization-cases/<cid>/discharge")
def discharge_case(cid):
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, ["discharge_at"])
    discharge_at = validate_datetime(body, "discharge_at")

    case = lookup(db.utilization_cases, cid, "UtilizationCase")

    # State-machine legality: repeated discharge fails
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "Case is already CLOSED", 409)

    # FINAL two-midnight variant
    admit_at = parse_iso(case["admit_at"])
    actual_midnights = midnight_count(admit_at, discharge_at)
    case["discharge_at"] = body["discharge_at"]
    case["actual_midnight_count"] = actual_midnights
    case["two_midnight_benchmark_met"] = benchmark_met(actual_midnights)
    case["benchmark_basis"] = "FINAL"
    case["review_status"] = "CLOSED"

    # Cascade: non-terminal AuthorizationRequests -> WITHDRAWN
    for ar in db.authorization_requests.values():
        if ar["case_id"] == cid and ar["status"] in ("SUBMITTED", "PENDED"):
            ar["status"] = "WITHDRAWN"
            touch(ar)
            append_audit(cid, "AUTH_WITHDRAWN", role, user_id,
                         f"Authorization request {ar['id']} withdrawn on discharge")

    # Cascade: OPEN/ACKNOWLEDGED escalations -> RESOLVED
    for esc in db.escalation_cases.values():
        if esc["case_id"] == cid and esc["status"] in ("OPEN", "ACKNOWLEDGED"):
            esc["status"] = "RESOLVED"
            esc["resolution_note"] = "auto: case discharged"
            touch(esc)
            append_audit(cid, "ESCALATION_RESOLVED", role, user_id,
                         f"Escalation {esc['id']} auto-resolved on discharge")

    touch(case)
    append_audit(cid, "CASE_DISCHARGED", role, user_id,
                 f"Case discharged at {body['discharge_at']}")
    return success_object(case_view(case), 200)
