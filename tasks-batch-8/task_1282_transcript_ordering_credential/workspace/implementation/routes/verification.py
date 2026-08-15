"""VerificationRequest endpoints (third-party credential verification)."""
from flask import Blueprint, request

from db import DB, new_id, parse_iso
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    CONSENT_SCOPES,
    VERIFICATION_ARCHIVE_SURCHARGE_CENTS,
    VERIFICATION_BASE_CENTS,
    VERIFICATION_SCOPE_SURCHARGE,
    _SCOPE_RANK,
    get_student,
    get_verification_request,
    logical_now,
    ref_lookup,
    ser_verification_request,
    sorted_created,
    stamp,
    touch,
    verification_block_hold_exists,
)
from util import as_enum, as_str, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("verification", __name__)

READ_ROLES = [
    "RegistrarAdmin",
    "RegistrarOperator",
    "RegistrarReviewer",
    "VerificationRequester",
]
STUDENT_READ = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]
REVIEWER = ["RegistrarReviewer"]


@bp.post("/registrar/verification-requests")
def create_verification_request():
    user_id, role = auth(["VerificationRequester"])
    data = body()
    reject_unknown_fields(
        data, {"requester_name", "subject_student_id", "scope", "consent_grant_id"}
    )
    requester_name = as_str(required(data, "requester_name"), "requester_name")
    subject_student_id = required(data, "subject_student_id")
    scope = as_enum(required(data, "scope"), "scope", CONSENT_SCOPES)
    consent_grant_id = data.get("consent_grant_id")
    ref_lookup("students", subject_student_id, "Student")
    if consent_grant_id is not None:
        ref_lookup("consent_grants", consent_grant_id, "ConsentGrant")

    rec = {
        "id": new_id(),
        "requester_name": requester_name,
        "subject_student_id": subject_student_id,
        "consent_grant_id": consent_grant_id,
        "scope": scope,
        "status": "RECEIVED",
        "fee_cents": 0,
        "denial_reason": None,
    }
    stamp(rec)
    DB["verification_requests"][rec["id"]] = rec
    return ok(ser_verification_request(rec), status=201)


@bp.get("/registrar/verification-requests")
def list_verification_requests():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["verification_requests"].values())
    sid = request.args.get("subject_student_id")
    if sid is not None:
        items = [v for v in items if v["subject_student_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    sc = request.args.get("scope")
    if sc is not None:
        items = [v for v in items if v["scope"] == sc]
    cg = request.args.get("consent_grant_id")
    if cg is not None:
        items = [v for v in items if v.get("consent_grant_id") == cg]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_verification_request(v) for v in page], total, limit, offset)


@bp.get("/registrar/verification-requests/<vid>")
def get_one_verification_request(vid):
    auth(READ_ROLES)
    return ok(ser_verification_request(get_verification_request(vid)))


@bp.get("/registrar/students/<sid>/verification-requests")
def list_student_verification_requests(sid):
    auth(STUDENT_READ)
    get_student(sid)
    limit, offset = pagination_args()
    items = [
        v for v in DB["verification_requests"].values() if v["subject_student_id"] == sid
    ]
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_verification_request(v) for v in page], total, limit, offset)


@bp.post("/registrar/verification-requests/<vid>/begin-review")
def begin_review(vid):
    auth(REVIEWER)
    rec = get_verification_request(vid)
    if rec["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "VerificationRequest is not RECEIVED")
    rec["status"] = "CONSENT_CHECK"
    touch(rec)
    return ok(ser_verification_request(rec))


@bp.post("/registrar/verification-requests/<vid>/approve")
def approve_verification(vid):
    user_id, role = auth(REVIEWER)
    rec = get_verification_request(vid)
    subject = get_student(rec["subject_student_id"])

    # Checks evaluated in the PRD 3.9 pinned order:
    # 1) FERPA consent, 2) hold screen, 3) segregation of duties, 4) state.
    if subject["ferpa_restricted"] or rec["scope"] != "ENROLLMENT_ONLY":
        now = logical_now()
        covered = False
        for g in DB["consent_grants"].values():
            if (
                g["student_id"] == subject["id"]
                and g["grantee_name"] == rec["requester_name"]
                and g["status"] == "ACTIVE"
                and _SCOPE_RANK[g["scope"]] >= _SCOPE_RANK[rec["scope"]]
                and parse_iso(g["expires_at"]) > now
            ):
                covered = True
                break
        if not covered:
            raise ApiError(
                "ERR_FERPA_CONSENT_REQUIRED",
                422,
                "No ACTIVE consent grant covers this request",
            )

    if verification_block_hold_exists(subject["id"]):
        raise ApiError(
            "ERR_HOLD_BLOCKING",
            422,
            "An ACTIVE hold with blocking_scope ALL exists on the subject",
        )

    if user_id == subject["id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Reviewer may not approve a verification of themselves",
        )

    if rec["status"] != "CONSENT_CHECK":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "VerificationRequest is not in CONSENT_CHECK"
        )

    fee = (
        VERIFICATION_BASE_CENTS
        + VERIFICATION_SCOPE_SURCHARGE[rec["scope"]]
        + (VERIFICATION_ARCHIVE_SURCHARGE_CENTS if subject["archived_record_flag"] else 0)
    )
    rec["fee_cents"] = fee
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(ser_verification_request(rec))


@bp.post("/registrar/verification-requests/<vid>/deny")
def deny_verification(vid):
    auth(REVIEWER)
    rec = get_verification_request(vid)
    data = body()
    reject_unknown_fields(data, {"denial_reason"})
    reason = as_str(required(data, "denial_reason"), "denial_reason")
    if rec["status"] != "CONSENT_CHECK":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "VerificationRequest is not in CONSENT_CHECK"
        )
    rec["status"] = "DENIED"
    rec["denial_reason"] = reason
    touch(rec)
    return ok(ser_verification_request(rec))
