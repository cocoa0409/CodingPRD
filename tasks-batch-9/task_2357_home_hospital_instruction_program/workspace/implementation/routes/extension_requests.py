"""Extension of the certified window (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import EXTENSION_STATUSES, listing
from services import logic
from validation import parse_date

bp = Blueprint("extension_requests", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "NurseReviewer"]

MAX_EXTENSIONS = 2
MAX_RESUBMITS = 2

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "certification_id": {"type": "string", "required": True},
    "requested_additional_days": {"type": "integer", "required": True, "min": 1, "max": 90},
    "justification": {"type": "string", "required": True},
    "expected_case_version": {"type": "integer", "required": True},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "certification_id": {"type": "string"},
    "status": {"type": "string", "enum": EXTENSION_STATUSES},
}


def load_request(request_id):
    row = db.get("extension_requests", request_id)
    if row is None:
        raise ApiError("ERR_EXTENSION_REQUEST_NOT_FOUND")
    return row


def _check_certification(case, certification_id):
    """Tier 12: the backing documentation must belong to the case and be accepted."""
    cert = db.get("certifications", certification_id)
    if cert is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND")
    return cert


def _validate_certification(case, cert):
    if cert["case_id"] != case["id"]:
        raise ApiError("ERR_CERT_CASE_MISMATCH")
    if cert["status"] != "ACCEPTED":
        raise ApiError("ERR_CERT_NOT_ACCEPTED")


@bp.post("/hhi/extension-requests")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_request():
    body = middleware.body()

    case = db.get("cases", body["case_id"])                       # tier 5
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    cert = _check_certification(case, body["certification_id"])

    if body["expected_case_version"] != case["version"]:          # tier 7
        raise ApiError("ERR_STALE_CASE_VERSION")

    if case["service_status"] != "ACTIVE":                        # tier 8
        raise ApiError("ERR_INVALID_CASE_STATE")

    _validate_certification(case, cert)                           # tier 12

    if case["extension_count"] >= MAX_EXTENSIONS:                 # tier 14
        raise ApiError("ERR_EXTENSION_LIMIT_REACHED")

    row = db.insert(
        "extension_requests",
        {
            "case_id": case["id"],
            "certification_id": cert["id"],
            "requested_additional_days": body["requested_additional_days"],
            "justification": body["justification"],
            "status": "SUBMITTED",
            "submitted_by_user_id": middleware.user_id(),
            "decided_by_user_id": None,
            "decision_note": None,
            "info_note": None,
            "resubmit_count": 0,
        },
    )

    db.set_field(case, "service_status", "EXTENSION_PENDING")
    db.touch(case)
    return middleware.obj(row)


@bp.get("/hhi/extension-requests/<request_id>")
@endpoint(READ_ROLES)
def read_request(request_id):
    return middleware.obj(load_request(request_id))


@bp.get("/hhi/extension-requests")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_requests():
    return listing("extension_requests", LIST_QUERY)


@bp.post("/hhi/extension-requests/<request_id>/start-review")
@endpoint(["ProgramAdministrator"])
def start_review(request_id):
    row = load_request(request_id)
    if row["status"] != "SUBMITTED":                              # tier 8
        raise ApiError("ERR_EXTENSION_STATE_INVALID")
    db.set_field(row, "status", "UNDER_REVIEW")
    return middleware.obj(row)


@bp.post("/hhi/extension-requests/<request_id>/request-info")
@endpoint(["ProgramAdministrator"], body={"info_note": {"type": "string", "required": True}})
def request_info(request_id):
    row = load_request(request_id)
    if row["status"] != "UNDER_REVIEW":                           # tier 8
        raise ApiError("ERR_EXTENSION_STATE_INVALID")
    db.set_field(row, "status", "INFO_REQUESTED")
    db.set_field(row, "info_note", middleware.body()["info_note"])
    return middleware.obj(row)


@bp.post("/hhi/extension-requests/<request_id>/resubmit")
@endpoint(["CaseManager"], body={"certification_id": {"type": "string", "required": True}})
def resubmit(request_id):
    row = load_request(request_id)
    cert = db.get("certifications", middleware.body()["certification_id"])   # tier 5
    if cert is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND")

    if row["status"] != "INFO_REQUESTED":                         # tier 8
        raise ApiError("ERR_EXTENSION_STATE_INVALID")
    if row["resubmit_count"] >= MAX_RESUBMITS:
        raise ApiError("ERR_EXTENSION_RESUBMIT_LIMIT")

    case = db.get("cases", row["case_id"])
    _validate_certification(case, cert)                           # tier 12

    db.set_field(row, "certification_id", cert["id"])
    db.set_field(row, "resubmit_count", row["resubmit_count"] + 1)
    db.set_field(row, "status", "UNDER_REVIEW")
    return middleware.obj(row)


@bp.post("/hhi/extension-requests/<request_id>/decide")
@endpoint(
    ["ProgramAdministrator"],
    body={
        "decision": {"type": "string", "required": True, "enum": ["APPROVED", "DENIED"]},
        "decision_note": {"type": "string"},
    },
)
def decide(request_id):
    row = load_request(request_id)
    if row["status"] != "UNDER_REVIEW":                           # tier 8
        raise ApiError("ERR_EXTENSION_STATE_INVALID")
    if middleware.user_id() == row["submitted_by_user_id"]:       # tier 9
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    body = middleware.body()
    case = db.get("cases", row["case_id"])

    db.set_field(row, "status", body["decision"])
    db.set_field(row, "decided_by_user_id", middleware.user_id())
    if "decision_note" in body:
        db.set_field(row, "decision_note", body["decision_note"])

    if body["decision"] == "APPROVED":
        end = parse_date(case["certified_end_date"])
        if end is not None:
            db.set_field(
                case,
                "certified_end_date",
                (end + timedelta(days=row["requested_additional_days"])).isoformat(),
            )
        db.set_field(case, "extension_count", case["extension_count"] + 1)
        logic.recompute_weekly_entitlement(case)
        logic.recompute_allocation(case)

    if case["service_status"] == "EXTENSION_PENDING":
        db.set_field(case, "service_status", "ACTIVE")
    db.touch(case)
    return middleware.obj(row)
