from flask import Blueprint, request

import db
from db import STORE
from errors import (
    ApiError,
    ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOTICE_DEADLINE_PASSED,
    ERR_TERMINATION_WINDOW_NOT_OPEN,
    ERR_VALIDATION,
    ERR_WORK_RIGHTS_TERMINATED,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import claim_view
from services import (
    claim_status, get_or_404, new_record, sorted_all, terminate_work_rights, touch,
)
from validators import body_json, paginate, pagination_params, req_dt, req_enum, req_str

bp = Blueprint("claims", __name__)

STATUTE_BASES = ["SEC_203", "SEC_304"]

WINDOW_OPEN_YEARS = 35
WINDOW_CLOSE_YEARS = 40
NOTICE_EARLIEST_YEARS = 10
NOTICE_LATEST_YEARS = 2


@bp.route("/termination-claims", methods=["POST"], strict_slashes=False)
def create_claim():
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    body = body_json()
    work_id = body.get("work_id")
    if not isinstance(work_id, str) or not work_id:
        raise ApiError(ERR_VALIDATION, 422, "work_id is required")
    work = get_or_404("works", work_id, "work")
    statute_basis = req_enum(body, "statute_basis", STATUTE_BASES)
    intended = req_dt(body, "intended_effective_date")
    window_open = db.add_years(work["grant_date"], WINDOW_OPEN_YEARS)
    window_close = db.add_years(work["grant_date"], WINDOW_CLOSE_YEARS)
    notice_earliest = db.add_years(intended, -NOTICE_EARLIEST_YEARS)
    notice_latest = db.add_years(intended, -NOTICE_LATEST_YEARS)
    if not (window_open < intended <= window_close):
        raise ApiError(ERR_EFFECTIVE_DATE_OUTSIDE_WINDOW, 409,
                       "intended_effective_date must fall strictly after "
                       "window_open_date and on or before window_close_date")
    c = new_record()
    c.update({
        "work_id": work_id,
        "statute_basis": statute_basis,
        "intended_effective_date": intended,
        "window_open_date": window_open,
        "window_close_date": window_close,
        "notice_earliest_date": notice_earliest,
        "notice_latest_date": notice_latest,
        "notice_ref": None,
        "notice_filed_at": None,
        "status": "TRACKING",
    })
    STORE["termination_claims"][c["id"]] = c
    return success(claim_view(c), status=201)


@bp.route("/termination-claims", methods=["GET"], strict_slashes=False)
def list_claims():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("termination_claims")
    work_id = request.args.get("work_id")
    status = request.args.get("status")
    if work_id is not None:
        items = [c for c in items if c["work_id"] == work_id]
    if status is not None:
        items = [c for c in items if claim_status(c) == status]
    page, meta = paginate(items, limit, offset)
    return success([claim_view(c) for c in page],
                   response_type="array", pagination=meta)


@bp.route("/termination-claims/<cid>", methods=["GET"], strict_slashes=False)
def get_claim(cid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    c = get_or_404("termination_claims", cid, "termination claim")
    return success(claim_view(c))


@bp.route("/termination-claims/<cid>/file-notice", methods=["POST"], strict_slashes=False)
def file_notice(cid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    c = get_or_404("termination_claims", cid, "termination claim")
    body = body_json()
    notice_ref = req_str(body, "notice_ref")
    derived = claim_status(c)
    now = db.clock_now()
    if derived == "TRACKING":
        raise ApiError(ERR_TERMINATION_WINDOW_NOT_OPEN, 409,
                       "the termination window has not opened yet")
    if derived != "NOTICE_WINDOW_OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "file-notice requires derived status NOTICE_WINDOW_OPEN")
    if now > c["notice_latest_date"]:
        raise ApiError(ERR_NOTICE_DEADLINE_PASSED, 409,
                       "the notice filing deadline has passed")
    work = STORE["works"][c["work_id"]]
    if work["copyright_status"] == "TERMINATED":
        raise ApiError(ERR_WORK_RIGHTS_TERMINATED, 409,
                       "the work's copyright is already TERMINATED")
    c["notice_ref"] = notice_ref
    c["notice_filed_at"] = now
    c["status"] = "NOTICE_FILED"
    touch(c)
    return success(claim_view(c))


@bp.route("/termination-claims/<cid>/make-effective", methods=["POST"], strict_slashes=False)
def make_effective(cid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    c = get_or_404("termination_claims", cid, "termination claim")
    if c["status"] != "NOTICE_FILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "make-effective requires status NOTICE_FILED")
    if db.clock_now() < c["intended_effective_date"]:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "the intended effective date has not been reached")
    c["status"] = "EFFECTIVE"
    touch(c)
    work = STORE["works"][c["work_id"]]
    terminate_work_rights(work)
    return success(claim_view(c))


@bp.route("/termination-claims/<cid>/reject", methods=["POST"], strict_slashes=False)
def reject_claim(cid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    c = get_or_404("termination_claims", cid, "termination claim")
    body = body_json()
    req_str(body, "reason")
    if c["status"] != "NOTICE_FILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "reject requires status NOTICE_FILED")
    c["status"] = "REJECTED"
    touch(c)
    return success(claim_view(c))
