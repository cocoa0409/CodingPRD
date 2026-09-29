"""Network-change requests and the approval cascade (PRD 3.9)."""
from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.common import (ensure_from_state, ensure_not_terminal, get_assessment,
                           get_change_request, get_site, network_of)
from services import cascade
from services import serialize as S

bp = Blueprint("change_requests", __name__)

REPLACEMENT_ELIGIBLE_STATUSES = ("SITING_APPROVED", "OPERATING")


def _site_operating(site):
    if site["status"] != "OPERATING":
        raise ApiError("ERR_SITE_NOT_OPERATING",
                       "The target site is in status %s rather than OPERATING." % site["status"])


@bp.post("/site-change-requests")
@require("ProgramManager")
def raise_change_request():
    data = V.body()
    site_id = V.req_id(data, "site_id")
    request_type = V.req_enum(data, "request_type", C.CHANGE_REQUEST_TYPES)
    justification = V.req_string(data, "justification", min_len=1, max_len=2000)
    assessment_id = V.req_id(data, "assessment_id")
    replacement_site_id = V.opt_id(data, "replacement_site_id")
    get_site(site_id)
    get_assessment(assessment_id)
    if replacement_site_id is not None:
        get_site(replacement_site_id)
    if request_type == "RELOCATION" and replacement_site_id is None:
        raise ApiError("ERR_REPLACEMENT_SITE_REQUIRED",
                       "A RELOCATION request must nominate a replacement_site_id.")
    if request_type != "RELOCATION" and replacement_site_id is not None:
        raise ApiError("ERR_REPLACEMENT_SITE_REQUIRED",
                       "replacement_site_id must be absent for a %s request." % request_type)
    rec = new_record()
    rec.update({
        "site_id": site_id,
        "replacement_site_id": replacement_site_id,
        "assessment_id": assessment_id,
        "request_type": request_type,
        "justification": justification,
        "status": "DRAFT",
        "revision_request_count": 0,
        "decided_by_user_id": None,
        "decided_at": None,
        "effective_at": None,
    })
    store.change_requests[rec["id"]] = rec
    return response.object_response(S.change_request(rec), 201)


@bp.post("/site-change-requests/<change_request_id>/submit")
@require("ProgramManager")
def submit_change_request(change_request_id):
    data = V.body()
    V.opt_string(data, "submission_note")
    rec = get_change_request(change_request_id)
    ensure_not_terminal(rec["status"], C.CHANGE_REQUEST_TERMINAL, "change request")
    ensure_from_state(rec["status"], ("DRAFT",), "change request")
    site = store.sites.get(rec["site_id"])
    if site is not None:
        _site_operating(site)
    rec["status"] = "SUBMITTED"
    touch(rec)
    return response.object_response(S.change_request(rec))


@bp.post("/site-change-requests/<change_request_id>/decision")
@require("EpaRegionalReviewer")
def decide_change_request(change_request_id):
    data = V.body()
    decision = V.req_enum(data, "decision", C.CHANGE_REQUEST_DECISIONS)
    V.opt_string(data, "decision_note")
    rec = get_change_request(change_request_id)
    ensure_not_terminal(rec["status"], C.CHANGE_REQUEST_TERMINAL, "change request")
    ensure_from_state(rec["status"], ("SUBMITTED",), "change request")
    if decision == "REQUEST_REVISION":
        rec["status"] = "DRAFT"
        rec["revision_request_count"] += 1
        touch(rec)
        return response.object_response(S.change_request(rec))
    if decision == "DENY":
        # The deny branch has no cascade at all.
        rec["status"] = "DENIED"
        rec["decided_by_user_id"] = actor()
        rec["decided_at"] = clock.now()
        touch(rec)
        return response.object_response(S.change_request(rec))
    # APPROVE -- three gates in the order PRD 2.11 lays down.
    site = store.sites.get(rec["site_id"])
    if site is None:
        raise ApiError("ERR_SITE_NOT_FOUND", "The target site no longer exists.")
    _site_operating(site)
    assessment = store.assessments.get(rec["assessment_id"])
    if (assessment is None or assessment["status"] != "APPROVED"
            or assessment["network_id"] != site["network_id"]):
        raise ApiError("ERR_ASSESSMENT_NOT_APPROVED",
                       "The cited assessment is not an approved assessment of the site's network.")
    replacement = None
    if rec["request_type"] == "RELOCATION":
        replacement = store.sites.get(rec["replacement_site_id"])
        if (replacement is None
                or replacement["status"] not in REPLACEMENT_ELIGIBLE_STATUSES
                or replacement["network_id"] != site["network_id"]):
            raise ApiError("ERR_REPLACEMENT_SITE_NOT_ELIGIBLE",
                           "The nominated replacement site is not eligible to take over "
                           "monitoring.")
    now = clock.now()
    rec["status"] = "APPROVED"
    rec["decided_by_user_id"] = actor()
    rec["decided_at"] = now
    rec["effective_at"] = now
    touch(rec)
    network = network_of(site)
    if rec["request_type"] == "SEASONAL_SUSPENSION":
        cascade.seasonal_suspension(site, network)
    elif rec["request_type"] == "SHUTDOWN":
        cascade.shutdown_cascade(site, network)
    else:
        cascade.relocation_cascade(site, replacement, network)
    return response.object_response(S.change_request(rec))


@bp.get("/site-change-requests/<change_request_id>")
@require(*ALL_ROLES)
def read_change_request(change_request_id):
    return response.object_response(S.change_request(get_change_request(change_request_id)))


@bp.get("/site-change-requests")
@require(*ALL_ROLES)
def list_change_requests():
    limit, offset = V.pagination()
    site_id = V.q_string("site_id")
    replacement_site_id = V.q_string("replacement_site_id")
    assessment_id = V.q_string("assessment_id")
    request_type = V.q_enum("request_type", C.CHANGE_REQUEST_TYPES)
    status = V.q_enum("status", C.CHANGE_REQUEST_STATUSES)
    rows = list(store.change_requests.values())
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if replacement_site_id is not None:
        rows = [r for r in rows if r["replacement_site_id"] == replacement_site_id]
    if assessment_id is not None:
        rows = [r for r in rows if r["assessment_id"] == assessment_id]
    if request_type is not None:
        rows = [r for r in rows if r["request_type"] == request_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.change_request(r) for r in page], pagination=meta)
