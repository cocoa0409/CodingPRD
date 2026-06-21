"""TitleSearch routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_APPLICANT_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_subresource_or_404

bp = Blueprint("title_searches", __name__)


def ts_to_dict(ts: dict) -> dict:
    return {
        "id": ts["id"],
        "application_id": ts["application_id"],
        "status": ts["status"],
        "exception_summary": ts.get("exception_summary"),
        "created_at": ts["created_at"],
        "updated_at": ts["updated_at"],
        "version": ts["version"],
    }


@bp.post("/title-searches")
@require_auth(roles=["LoanOfficer"])
def create_title_search():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    with db.lock:
        ts = {
            **new_common_fields(),
            "application_id": application_id,
            "status": "ORDERED",
            "exception_summary": None,
        }
        db.title_searches[ts["id"]] = ts
    return response.ok(ts_to_dict(ts), status=201)


@bp.get("/title-searches/<ts_id>")
@require_auth(roles=["LoanOfficer", "Underwriter", "TitleAgent"])
def read_title_search(ts_id: str):
    ts = get_subresource_or_404(db.title_searches, ts_id)
    return response.ok(ts_to_dict(ts))


@bp.get("/title-searches")
@require_auth(roles=["LoanOfficer", "Underwriter", "TitleAgent"])
def list_title_searches():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(db.title_searches.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([ts_to_dict(x) for x in page], limit, offset, total)


def _parent_app_ok(app_id: str) -> dict:
    la = db.loan_applications.get(app_id)
    if la is None:
        raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
    if la["status"] not in ("PREQUALIFIED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, "Parent application not in PREQUALIFIED/UNDER_REVIEW.")
    return la


@bp.post("/title-searches/<ts_id>/mark-clear")
@require_auth(roles=["TitleAgent"])
def mark_clear(ts_id: str):
    ts = get_subresource_or_404(db.title_searches, ts_id)
    with db.lock:
        if ts["status"] != "ORDERED":
            raise ApiError(ERR_INVALID_STATE, "Title search is not ORDERED.")
        _parent_app_ok(ts["application_id"])
        ts["status"] = "CLEAR"
        bump(ts)
    return response.ok(ts_to_dict(ts))


@bp.post("/title-searches/<ts_id>/raise-exception")
@require_auth(roles=["TitleAgent"])
def raise_exception(ts_id: str):
    ts = get_subresource_or_404(db.title_searches, ts_id)
    with db.lock:
        if ts["status"] != "ORDERED":
            raise ApiError(ERR_INVALID_STATE, "Title search is not ORDERED.")
        _parent_app_ok(ts["application_id"])
        body = get_json_body()
        summary = require_str(body, "exception_summary")
        ts["exception_summary"] = summary
        ts["status"] = "EXCEPTIONS_FOUND"
        bump(ts)
    return response.ok(ts_to_dict(ts))


@bp.post("/title-searches/<ts_id>/cure")
@require_auth(roles=["TitleAgent"])
def cure(ts_id: str):
    ts = get_subresource_or_404(db.title_searches, ts_id)
    with db.lock:
        if ts["status"] != "EXCEPTIONS_FOUND":
            raise ApiError(ERR_INVALID_STATE, "Title search is not EXCEPTIONS_FOUND.")
        _parent_app_ok(ts["application_id"])
        ts["status"] = "CURED"
        bump(ts)
    return response.ok(ts_to_dict(ts))
