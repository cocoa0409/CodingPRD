from flask import Blueprint, request

import errors as E
import response
from db import store, new_record, touch, serialize, parse_dt
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response
from services.domain import OFFICES

bp = Blueprint("grants", __name__)

GRANT_READ_ROLES = ["CaseManager", "BITChair", "PrivacyOfficer", "DeanOfStudents", "CounselingEvaluator"]
SCOPES = ("SUMMARY_ONLY", "FULL_RECORD", "SAFETY_MINIMUM")


@bp.post("/bit/disclosure-grants")
def create_grant():
    uid, _ = require_auth(["CaseManager"])
    b = body()
    case_id = b.get("case_id")
    case = None
    if isinstance(case_id, str):
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"care case not found: {case_id}")

    # Rank 9: field validity, then window sanity.
    if case is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_id is required")
    to_office = b.get("to_office")
    if to_office not in OFFICES:
        raise ApiError(E.ERR_VALIDATION, 400, "to_office must be a declared office value")
    scope = b.get("scope")
    if scope not in SCOPES:
        raise ApiError(E.ERR_VALIDATION, 400, "scope must be SUMMARY_ONLY, FULL_RECORD, or SAFETY_MINIMUM")
    effective_from = parse_dt(b.get("effective_from"))
    if effective_from is None:
        raise ApiError(E.ERR_VALIDATION, 400, "effective_from must be an ISO 8601 UTC timestamp")
    expires_at = parse_dt(b.get("expires_at"))
    if expires_at is None:
        raise ApiError(E.ERR_VALIDATION, 400, "expires_at must be an ISO 8601 UTC timestamp")
    purpose = b.get("purpose")
    if not isinstance(purpose, str) or not purpose:
        raise ApiError(E.ERR_VALIDATION, 400, "purpose is required")
    if not expires_at > effective_from:
        raise ApiError(
            E.ERR_DISCLOSURE_WINDOW_INVALID, 400, "expires_at must be later than effective_from"
        )

    # Rank 10: half-open overlap on the same (case_id, to_office) among REQUESTED/APPROVED.
    for g in store.grants.values():
        if (
            g["case_id"] == case["id"]
            and g["to_office"] == to_office
            and g["status"] in ("REQUESTED", "APPROVED")
            and effective_from < g["expires_at"]
            and g["effective_from"] < expires_at
        ):
            raise ApiError(
                E.ERR_DISCLOSURE_WINDOW_OVERLAP,
                409,
                "requested window intersects an existing REQUESTED/APPROVED grant for this case and office",
            )

    rec = new_record()
    rec.update(
        {
            "case_id": case["id"],
            "requested_by": uid,
            "approved_by": None,
            "to_office": to_office,
            "scope": scope,
            "effective_from": effective_from,
            "expires_at": expires_at,
            "purpose": purpose,
            "auto_approved": False,
            "status": "REQUESTED",
        }
    )
    store.grants[rec["id"]] = rec
    return response.obj(serialize(rec), 201)


@bp.get("/bit/disclosure-grants/<gid>")
def get_grant(gid):
    require_auth(GRANT_READ_ROLES)
    rec = get_or_404(store.grants, gid, "disclosure grant")
    return response.obj(serialize(rec))


@bp.get("/bit/disclosure-grants")
def list_grants():
    require_auth(GRANT_READ_ROLES)
    q = request.args
    return list_response(
        store.grants,
        [
            ("case_id", q.get("case_id")),
            ("requested_by", q.get("requested_by")),
            ("approved_by", q.get("approved_by")),
            ("to_office", q.get("to_office")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/disclosure-grants/<gid>/approve")
def approve_grant(gid):
    uid, _ = require_auth(["PrivacyOfficer"])
    rec = get_or_404(store.grants, gid, "disclosure grant")
    if rec["status"] != "REQUESTED":
        raise ApiError(E.ERR_GRANT_NOT_REQUESTED, 409, "approve requires grant REQUESTED")
    rec["status"] = "APPROVED"
    rec["approved_by"] = uid
    touch(rec)
    return response.obj(serialize(rec))


@bp.post("/bit/disclosure-grants/<gid>/deny")
def deny_grant(gid):
    require_auth(["PrivacyOfficer"])
    rec = get_or_404(store.grants, gid, "disclosure grant")
    if rec["status"] != "REQUESTED":
        raise ApiError(E.ERR_GRANT_NOT_REQUESTED, 409, "deny requires grant REQUESTED")
    rationale = body().get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ApiError(E.ERR_VALIDATION, 400, "rationale is required")
    rec["status"] = "DENIED"
    touch(rec)
    return response.obj(serialize(rec))


@bp.post("/bit/disclosure-grants/<gid>/revoke")
def revoke_grant(gid):
    require_auth(["PrivacyOfficer"])
    rec = get_or_404(store.grants, gid, "disclosure grant")
    if rec["status"] != "APPROVED":
        raise ApiError(E.ERR_GRANT_NOT_APPROVED, 409, "revoke requires grant APPROVED")
    rec["status"] = "REVOKED"
    touch(rec)
    return response.obj(serialize(rec))
