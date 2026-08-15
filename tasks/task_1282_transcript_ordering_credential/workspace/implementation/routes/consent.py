"""ConsentGrant endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    CONSENT_SCOPES,
    get_consent_grant,
    get_student,
    logical_now,
    ref_lookup,
    ser_consent_grant,
    sorted_created,
    stamp,
    touch,
)
from db import parse_iso
from util import as_enum, as_iso_dt, as_str, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("consent", __name__)

READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]


@bp.post("/registrar/consent-grants")
def create_consent_grant():
    user_id, role = auth(["Student"])
    data = body()
    reject_unknown_fields(data, {"student_id", "grantee_name", "scope", "expires_at"})
    student_id = required(data, "student_id")
    grantee_name = as_str(required(data, "grantee_name"), "grantee_name")
    scope = as_enum(required(data, "scope"), "scope", CONSENT_SCOPES)
    expires_at = as_iso_dt(required(data, "expires_at"), "expires_at")
    ref_lookup("students", student_id, "Student")

    # Temporal: expiry must lie strictly in the future at creation.
    if parse_iso(expires_at) <= logical_now():
        raise ApiError(
            "ERR_CONSENT_EXPIRED", 422, "expires_at must be in the future"
        )

    rec = {
        "id": new_id(),
        "student_id": student_id,
        "grantee_name": grantee_name,
        "scope": scope,
        "status": "ACTIVE",
        "expires_at": expires_at,
    }
    stamp(rec)
    DB["consent_grants"][rec["id"]] = rec
    return ok(ser_consent_grant(rec), status=201)


@bp.get("/registrar/consent-grants")
def list_consent_grants():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["consent_grants"].values())
    sid = request.args.get("student_id")
    if sid is not None:
        items = [g for g in items if g["student_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [g for g in items if g["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_consent_grant(g) for g in page], total, limit, offset)


@bp.get("/registrar/students/<sid>/consent-grants")
def list_student_consent_grants(sid):
    auth(READ_ROLES)
    get_student(sid)
    limit, offset = pagination_args()
    items = [g for g in DB["consent_grants"].values() if g["student_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [g for g in items if g["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_consent_grant(g) for g in page], total, limit, offset)


@bp.get("/registrar/consent-grants/<gid>")
def get_one_consent_grant(gid):
    auth(READ_ROLES)
    return ok(ser_consent_grant(get_consent_grant(gid)))


@bp.post("/registrar/consent-grants/<gid>/revoke")
def revoke_consent_grant(gid):
    user_id, role = auth(["Student"])
    grant = get_consent_grant(gid)
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "ConsentGrant is not ACTIVE")
    # Student may only revoke own grant.
    if grant["student_id"] != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Student may only revoke their own grant"
        )
    grant["status"] = "REVOKED"
    touch(grant)
    # Cascade: VerificationRequests referencing this grant in CONSENT_CHECK
    # are denied with CONSENT_REVOKED.
    for vr in DB["verification_requests"].values():
        if vr.get("consent_grant_id") == grant["id"] and vr["status"] == "CONSENT_CHECK":
            vr["status"] = "DENIED"
            vr["denial_reason"] = "CONSENT_REVOKED"
            touch(vr)
    return ok(ser_consent_grant(grant))
