from datetime import timedelta

from flask import Blueprint, request

import response
from db import store, new_rec, touch, serialize
from errors import (
    ApiError,
    ERR_NOT_ENGAGEMENT_CLIENT,
    ERR_NOT_ASSIGNED_APPRAISER,
    ERR_NOT_ASSIGNED_REVIEWER,
    ERR_INVALID_STATE,
    ERR_STALE_REPORT,
    ERR_INDEPENDENCE,
    ERR_REVISION_WINDOW_CLOSED,
)
from middleware import auth, require_role, get_body, req_enum, req_str, req_int, opt_int
from response import sort_by_creation
from services import domain

bp = Blueprint("revisions", __name__)

CATEGORIES = (
    "FACTUAL_CORRECTION",
    "CLARIFICATION",
    "METHODOLOGY_QUESTION",
    "VALUE_PRESSURE",
)


@bp.post("/reports/<reportId>/revision-requests")
def create_revision_request(reportId):
    uid, role = auth()
    require_role(role, {"Client"})
    report = domain.get_report(reportId)
    body = get_body()
    category = req_enum(body, "category", CATEGORIES)
    requested_change = req_str(body, "requested_change")
    proposed_value_cents = opt_int(body, "proposed_value_cents")
    eng = domain.engagement_of_report(report)
    if eng["client_id"] != uid:
        raise ApiError(
            ERR_NOT_ENGAGEMENT_CLIENT, 403, "Caller is not the engagement's client"
        )
    if report["status"] != "CLIENT_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Report is not in CLIENT_REVIEW")
    if store.clock > report["issued_to_client_at"] + timedelta(days=30):
        raise ApiError(
            ERR_REVISION_WINDOW_CLOSED,
            409,
            "Revision request is past the 30-day window",
        )
    rec = new_rec(
        {
            "report_id": report["id"],
            "category": category,
            "requested_change": requested_change,
            "proposed_value_cents": proposed_value_cents,
            "value_adjustment_cents": None,
            "resolution_note": None,
            "submitted_at": store.clock,
            "status": "OPEN",
        }
    )
    store.revision_requests[rec["id"]] = rec
    report["status"] = "REVISION_REQUESTED"
    touch(report)
    return response.success(serialize(rec), status=201)


@bp.get("/revision-requests/<requestId>")
def get_revision_request(requestId):
    auth()
    rec = domain.get_revision_request(requestId)
    return response.success(serialize(rec))


@bp.get("/revision-requests")
def list_revision_requests():
    auth()
    items = list(store.revision_requests.values())
    for field in ("report_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])


@bp.post("/revision-requests/<requestId>/accept")
def accept_revision_request(requestId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    rr = domain.get_revision_request(requestId)
    body = get_body()
    expected = req_int(body, "expected_report_version")
    resolution_note = req_str(body, "resolution_note")
    value_adjustment_cents = opt_int(body, "value_adjustment_cents")
    report = domain.get_report(rr["report_id"])
    eng = domain.engagement_of_report(report)
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    if rr["status"] != "OPEN" or report["status"] != "REVISION_REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Revision request is not OPEN on a REVISION_REQUESTED report",
        )
    if expected != report["version"]:
        raise ApiError(
            ERR_STALE_REPORT,
            412,
            "expected_report_version does not match the report's version",
        )
    if rr["category"] == "VALUE_PRESSURE":
        raise ApiError(
            ERR_INDEPENDENCE,
            409,
            "A VALUE_PRESSURE revision request may never be accepted",
        )
    rr["resolution_note"] = resolution_note
    rr["value_adjustment_cents"] = value_adjustment_cents
    rr["status"] = "ACCEPTED"
    touch(rr)
    if value_adjustment_cents is not None:
        report["value_conclusion_cents"] += value_adjustment_cents
    touch(report)
    return response.success(serialize(rr))


@bp.post("/revision-requests/<requestId>/decline")
def decline_revision_request(requestId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser", "ReviewAppraiser"})
    rr = domain.get_revision_request(requestId)
    body = get_body()
    resolution_note = req_str(body, "resolution_note")
    report = domain.get_report(rr["report_id"])
    eng = domain.engagement_of_report(report)
    if rr["status"] == "OPEN":
        if eng["author_appraiser_id"] != uid:
            raise ApiError(
                ERR_NOT_ASSIGNED_APPRAISER,
                403,
                "Caller is not the engagement's author appraiser",
            )
    elif rr["status"] == "ESCALATED":
        if eng["reviewer_appraiser_id"] != uid:
            raise ApiError(
                ERR_NOT_ASSIGNED_REVIEWER,
                403,
                "Caller is not the engagement's reviewer appraiser",
            )
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Revision request is not in a declinable state",
        )
    rr["resolution_note"] = resolution_note
    rr["status"] = "DECLINED"
    touch(rr)
    return response.success(serialize(rr))


@bp.post("/revision-requests/<requestId>/escalate")
def escalate_revision_request(requestId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    rr = domain.get_revision_request(requestId)
    report = domain.get_report(rr["report_id"])
    eng = domain.engagement_of_report(report)
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    if rr["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Revision request is not OPEN")
    rr["status"] = "ESCALATED"
    touch(rr)
    return response.success(serialize(rr))


@bp.post("/revision-requests/<requestId>/withdraw")
def withdraw_revision_request(requestId):
    uid, role = auth()
    require_role(role, {"Client"})
    rr = domain.get_revision_request(requestId)
    report = domain.get_report(rr["report_id"])
    eng = domain.engagement_of_report(report)
    if eng["client_id"] != uid:
        raise ApiError(
            ERR_NOT_ENGAGEMENT_CLIENT, 403, "Caller is not the engagement's client"
        )
    if rr["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Revision request is not OPEN")
    rr["status"] = "WITHDRAWN"
    touch(rr)
    return response.success(serialize(rr))
