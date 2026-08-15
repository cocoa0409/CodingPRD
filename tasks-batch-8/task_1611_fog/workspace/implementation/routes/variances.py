"""Variance request endpoints: file, list, read, request-info, provide-info,
approve, deny."""
import uuid

from flask import Blueprint, request

from db import STORE, now, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_ESTABLISHMENT_SUSPENDED,
    ERR_VARIANCE_ALREADY_OPEN,
    ERR_VARIANCE_WINDOW_OVERLAP,
)
from middleware import (
    auth,
    require_roles,
    forbid_unless,
    get_or_404,
    paginate,
    by_creation,
    filter_enum,
)
from response import success
from services.posture import touch_establishment
from services.serializers import ser_variance
from validation import body_json, v_str, v_int, v_enum, v_dt

bp = Blueprint("variances", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact"]
SCOPES = ("PUMPING_FREQUENCY", "INTERCEPTOR_SIZE")
STATUSES = ("UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED")
OPEN_STATUSES = ("UNDER_REVIEW", "INFO_REQUESTED")


@bp.post("/variance-requests")
def create_variance():
    uid, role = auth()
    body = body_json()
    est_id = v_str(body, "establishment_id")
    scope = v_enum(body, "scope", SCOPES)
    justification = v_str(body, "justification")
    effective_from = v_dt(body, "effective_from")
    effective_to = v_dt(body, "effective_to")
    if not effective_to > effective_from:
        raise ApiError(ERR_INVALID_REQUEST, 400, "effective_to must be after effective_from")
    if scope == "PUMPING_FREQUENCY":
        freq = v_int(body, "requested_frequency_days", min_val=1)
    else:
        if "requested_frequency_days" in body and body["requested_frequency_days"] is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "requested_frequency_days must be absent when scope is INTERCEPTOR_SIZE",
            )
        freq = None
    require_roles(role, ["FseContact"])
    forbid_unless(uid == est_id)
    get_or_404("establishments", est_id)
    for v in STORE["variances"].values():
        if (
            v["establishment_id"] == est_id
            and v["scope"] == scope
            and v["status"] in OPEN_STATUSES
        ):
            raise ApiError(ERR_VARIANCE_ALREADY_OPEN, 409, "An open variance already exists for this establishment and scope")
    current = now()
    v = {
        "id": str(uuid.uuid4()),
        "establishment_id": est_id,
        "scope": scope,
        "requested_frequency_days": freq,
        "justification": justification,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "UNDER_REVIEW",
        "approved_by_user_id": None,
        "decided_at": None,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["variances"][v["id"]] = v
    return success(ser_variance(v), 201)


@bp.get("/variance-requests")
def list_variances():
    uid, role = auth()
    require_roles(role, READERS)
    est_filter = request.args.get("establishment_id")
    status_filter = filter_enum(request.args, "status", STATUSES)
    scope_filter = filter_enum(request.args, "scope", SCOPES)
    items = list(STORE["variances"].values())
    if role == "FseContact":
        items = [v for v in items if v["establishment_id"] == uid]
    if est_filter is not None:
        items = [v for v in items if v["establishment_id"] == est_filter]
    if status_filter is not None:
        items = [v for v in items if v["status"] == status_filter]
    if scope_filter is not None:
        items = [v for v in items if v["scope"] == scope_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_variance(v) for v in page], 200, "array", meta)


@bp.get("/variance-requests/<vid>")
def get_variance(vid):
    uid, role = auth()
    require_roles(role, READERS)
    v = get_or_404("variances", vid)
    if role == "FseContact":
        forbid_unless(v["establishment_id"] == uid)
    return success(ser_variance(v))


@bp.post("/variance-requests/<vid>/request-info")
def request_info(vid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    v = get_or_404("variances", vid)
    if v["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Variance is not in UNDER_REVIEW status")
    v["status"] = "INFO_REQUESTED"
    v["updated_at"] = now()
    v["version"] += 1
    return success(ser_variance(v))


@bp.post("/variance-requests/<vid>/provide-info")
def provide_info(vid):
    uid, role = auth()
    body = body_json()
    justification = v_str(body, "justification")
    require_roles(role, ["FseContact"])
    v = get_or_404("variances", vid)
    forbid_unless(v["establishment_id"] == uid)
    if v["status"] != "INFO_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Variance is not in INFO_REQUESTED status")
    v["justification"] = justification
    v["status"] = "UNDER_REVIEW"
    v["updated_at"] = now()
    v["version"] += 1
    return success(ser_variance(v))


@bp.post("/variance-requests/<vid>/approve")
def approve_variance(vid):
    uid, role = auth()
    body = body_json()
    expected = v_int(body, "expected_establishment_version")
    require_roles(role, ["ComplianceOfficer"])
    v = get_or_404("variances", vid)
    if v["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Variance is not in UNDER_REVIEW status")
    est = get_or_404("establishments", v["establishment_id"])
    if expected != est["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_establishment_version does not match current version")
    if est["compliance_status"] == "SUSPENDED":
        raise ApiError(ERR_ESTABLISHMENT_SUSPENDED, 409, "Establishment is SUSPENDED")
    for other in STORE["variances"].values():
        if (
            other["id"] != v["id"]
            and other["establishment_id"] == v["establishment_id"]
            and other["scope"] == v["scope"]
            and other["status"] == "APPROVED"
            and v["effective_from"] < other["effective_to"]
            and other["effective_from"] < v["effective_to"]
        ):
            raise ApiError(ERR_VARIANCE_WINDOW_OVERLAP, 409, "Window overlaps an approved same-scope variance")
    current = now()
    v["status"] = "APPROVED"
    v["approved_by_user_id"] = uid
    v["decided_at"] = current
    v["updated_at"] = current
    v["version"] += 1
    if v["scope"] == "PUMPING_FREQUENCY":
        est["variance_override_frequency_days"] = v["requested_frequency_days"]
    # Single version advance for the approval cascade (PRD §3.7).
    touch_establishment(est, current, bump=True)
    return success(ser_variance(v))


@bp.post("/variance-requests/<vid>/deny")
def deny_variance(vid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    v = get_or_404("variances", vid)
    if v["status"] not in OPEN_STATUSES:
        raise ApiError(ERR_INVALID_STATE, 409, "Variance is not open")
    v["status"] = "DENIED"
    v["decided_at"] = now()
    v["updated_at"] = v["decided_at"]
    v["version"] += 1
    return success(ser_variance(v))
