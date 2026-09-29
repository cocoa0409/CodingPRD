"""Denial decisions with their second-officer review, and amendment requests."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from events import append_event
from security import ALL_ROLES, actor, own_request

bp = Blueprint("reviews", __name__)

DENIAL_ORIGINS = (
    "INTAKE_REVIEW", "AUTH_DEFECT_PENDING", "COMPILATION",
    "SENSITIVE_REVIEW", "REDACTION",
)


def _get_denial(id):
    den = store.denials.get(id)
    if den is None:
        raise ApiError("ERR_DENIAL_NOT_FOUND")
    return den


# ============================================================ issuing a denial
@bp.post("/roi/denials")
def create_denial():
    uid, role = actor(["PrivacyOfficer"])
    body = v.body()

    request_id = v.req_id(body, "request_id")
    denial_type = v.req_enum(body, "denial_type", ["FULL", "PARTIAL"])
    grounds = v.req_enum(body, "grounds", store.DENIAL_GROUNDS)
    rationale = v.req_str(body, "rationale", max_len=500)

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    if req["fulfillment_status"] not in DENIAL_ORIGINS:
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    # an open denial always leaves the request in DENIED, which the gate above
    # already rejects; the guard is kept for completeness
    for other in calc.denials_of(req["id"]):
        if other["status"] in ("ISSUED", "UNDER_REVIEW"):
            raise ApiError("ERR_REQUEST_STATE_INVALID")

    issued_at = store.now()
    den = store.common_fields()
    den["request_id"] = req["id"]
    den["denial_type"] = denial_type
    den["grounds"] = grounds
    den["rationale"] = rationale
    den["reviewable"] = grounds in store.REVIEWABLE_GROUNDS
    den["issued_by_user_id"] = uid
    den["reviewer_user_id"] = None
    den["status"] = "ISSUED"
    den["issued_at"] = store.fmt(issued_at)
    den["review_due_at"] = store.fmt(
        issued_at + timedelta(seconds=store.REVIEW_WINDOW_DAYS * store.SECONDS_PER_DAY))
    den["decided_at"] = None
    store.denials[den["id"]] = den

    # the denial does not stop the clock: DENIED is non-terminal and keeps accruing
    req["fulfillment_status"] = "DENIED"
    append_event(req["id"], "DENIAL_ISSUED", uid,
                 days_late=calc.turnaround(req)["days_late_strict"],
                 detail="grounds=%s" % grounds)
    calc.refresh_statutory_due_at(req)
    calc.refresh_penalties(req, uid)
    store.touch(req)
    return created(store.public(den))


@bp.get("/roi/denials/<id>")
def read_denial(id):
    uid, role = actor(ALL_ROLES)
    den = store.denials.get(id)
    own_request(role, uid, store.requests.get(den["request_id"]) if den else None)
    if den is None:
        raise ApiError("ERR_DENIAL_NOT_FOUND")
    return ok(store.public(den))


@bp.get("/roi/denials")
def list_denials():
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    rows = store.ordered(list(store.denials.values()))
    if role == "Requester":
        rows = [r for r in rows
                if (store.requests.get(r["request_id"]) or {}).get("requester_id") == uid]
    for field in ("request_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ second-officer review
@bp.post("/roi/denials/<id>/review")
def review_denial(id):
    uid, role = actor(["PrivacyOfficer"])
    body = v.body()
    action = v.req_enum(body, "action", ["START_REVIEW", "UPHOLD", "OVERTURN"])
    rationale = v.opt_str(body, "rationale", max_len=500)

    den = _get_denial(id)

    # priority 9 — the reviewing officer may never be the issuing officer
    if uid == den["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # priority 15 — the origin set is per action
    origins = {
        "START_REVIEW": ("ISSUED",),
        "UPHOLD": ("ISSUED", "UNDER_REVIEW"),
        "OVERTURN": ("UNDER_REVIEW",),
    }[action]
    if den["status"] not in origins:
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    # priority 43 — reviewability gates both START_REVIEW and OVERTURN
    if action in ("START_REVIEW", "OVERTURN") and not den["reviewable"]:
        raise ApiError("ERR_DENIAL_NOT_REVIEWABLE")
    # a reviewable denial must pass through review before it can be upheld
    if action == "UPHOLD" and den["status"] == "ISSUED" and den["reviewable"]:
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    req = store.requests.get(den["request_id"])
    if rationale is not None:
        den["rationale"] = rationale

    if action == "START_REVIEW":
        den["status"] = "UNDER_REVIEW"
        den["reviewer_user_id"] = uid
        store.touch(den)
        return ok(store.public(den))

    decided_at = store.now()
    den["decided_at"] = store.fmt(decided_at)

    if action == "UPHOLD":
        den["status"] = "UPHELD"
        store.touch(den)
        if req is not None:
            req["fulfillment_status"] = "CLOSED"
            req["closed_at"] = store.fmt(decided_at)
            if req["billing_status"] == "PENDING_INVOICE":
                req["billing_status"] = "NOT_BILLABLE"
            calc.refresh_penalties(req, uid, completion_at=decided_at)
            store.touch(req)
        return ok(store.public(den))

    den["status"] = "OVERTURNED"
    store.touch(den)
    if req is not None:
        # the withheld set must be decided again from scratch
        for seg in calc.segments_of(req["id"]):
            dirty = False
            if seg["sensitivity_status"] == "WITHHELD":
                seg["sensitivity_status"] = "SEGREGATED_PENDING_REVIEW"
                dirty = True
                if seg["redaction_status"] in ("APPLIED", "APPROVED", "REWORK"):
                    seg["redaction_status"] = "OPEN"
                    seg["redaction_approved_by_user_id"] = None
            if dirty:
                store.touch(seg)
        req["fulfillment_status"] = "COMPILATION"
        calc.refresh_page_ledger(req)
        calc.refresh_statutory_due_at(req)
        append_event(req["id"], "DENIAL_OVERTURNED", uid,
                     days_late=calc.turnaround(req)["days_late_strict"],
                     detail="denial_id=%s" % den["id"])
        calc.refresh_penalties(req, uid)
        store.touch(req)
    return ok(store.public(den))


# ============================================================ amendment requests
def _get_amendment(id):
    amd = store.amendments.get(id)
    if amd is None:
        raise ApiError("ERR_AMENDMENT_NOT_FOUND")
    return amd


@bp.post("/roi/amendment-requests")
def create_amendment():
    uid, role = actor(["Requester"])
    body = v.body()

    request_id = v.req_id(body, "request_id")
    patient_id = v.req_id(body, "patient_id")
    record_segment_id = v.req_id(body, "record_segment_id")
    requested_change = v.req_str(body, "requested_change", max_len=500)

    req = store.requests.get(request_id)
    own_request(role, uid, req)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    seg = store.segments.get(record_segment_id)
    if seg is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")

    # priority 26 — the amendment must concern the request's own patient
    if patient_id != req["patient_id"]:
        raise ApiError("ERR_PATIENT_IDENTITY_MISMATCH")

    # the target must actually have been disclosed
    if not req.get("released_at") or seg["retrieval_status"] != "RETRIEVED":
        raise ApiError("ERR_AMENDMENT_TARGET_NOT_RELEASED")

    amd = store.common_fields()
    amd["request_id"] = req["id"]
    amd["patient_id"] = patient_id
    amd["record_segment_id"] = seg["id"]
    amd["requested_change"] = requested_change
    amd["additional_information"] = None
    amd["status"] = "SUBMITTED"
    amd["submission_count"] = 1
    amd["decision_due_at"] = store.fmt(
        store.parse_dt(amd["created_at"])
        + timedelta(seconds=store.AMENDMENT_WINDOW_DAYS * store.SECONDS_PER_DAY))
    amd["rationale"] = None
    amd["decided_at"] = None
    store.amendments[amd["id"]] = amd
    return created(store.public(amd))


@bp.get("/roi/amendment-requests/<id>")
def read_amendment(id):
    uid, role = actor(ALL_ROLES)
    amd = store.amendments.get(id)
    own_request(role, uid, store.requests.get(amd["request_id"]) if amd else None)
    if amd is None:
        raise ApiError("ERR_AMENDMENT_NOT_FOUND")
    return ok(store.public(amd))


@bp.get("/roi/amendment-requests")
def list_amendments():
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    rows = store.ordered(list(store.amendments.values()))
    if role == "Requester":
        rows = [r for r in rows
                if (store.requests.get(r["request_id"]) or {}).get("requester_id") == uid]
    for field in ("patient_id", "record_segment_id", "request_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


AMENDMENT_ORIGINS = {
    "START_REVIEW": ("SUBMITTED",),
    "REQUEST_INFO": ("UNDER_REVIEW",),
    "ACCEPT": ("UNDER_REVIEW",),
    "DENY": ("UNDER_REVIEW",),
}


@bp.post("/roi/amendment-requests/<id>/decision")
def decide_amendment(id):
    uid, role = actor(["PrivacyOfficer"])
    body = v.body()
    decision = v.req_enum(body, "decision",
                          ["START_REVIEW", "REQUEST_INFO", "ACCEPT", "DENY"])
    rationale = v.opt_str(body, "rationale", max_len=500)

    amd = _get_amendment(id)
    # priority 15
    if amd["status"] not in AMENDMENT_ORIGINS[decision]:
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    seg = store.segments.get(amd["record_segment_id"])
    if decision == "ACCEPT":
        if seg is None or seg["retrieval_status"] != "RETRIEVED":
            raise ApiError("ERR_AMENDMENT_TARGET_NOT_RELEASED")

    if rationale is not None:
        amd["rationale"] = rationale

    if decision == "START_REVIEW":
        amd["status"] = "UNDER_REVIEW"
    elif decision == "REQUEST_INFO":
        amd["status"] = "INFO_REQUESTED"
    elif decision == "DENY":
        amd["status"] = "DENIED"
        amd["decided_at"] = store.fmt(store.now())
    else:
        amd["status"] = "ACCEPTED"
        amd["decided_at"] = store.fmt(store.now())
        seg["amended"] = True
        store.touch(seg)
        req = store.requests.get(amd["request_id"])
        if req is not None:
            # an accepted amendment only obliges notice where pages already went out
            if req.get("released_at"):
                req["amendment_notice_required"] = True
            append_event(req["id"], "AMENDMENT_NOTICE_REQUIRED", uid,
                         detail="amendment_request_id=%s" % amd["id"])
            store.touch(req)

    store.touch(amd)
    return ok(store.public(amd))


@bp.post("/roi/amendment-requests/<id>/resubmission")
def resubmit_amendment(id):
    uid, role = actor(["Requester"])
    amd = store.amendments.get(id)
    own_request(role, uid,
                store.requests.get(amd["request_id"]) if amd else None)

    body = v.body()
    additional_information = v.req_str(body, "additional_information", max_len=500)

    if amd is None:
        raise ApiError("ERR_AMENDMENT_NOT_FOUND")
    # priority 15 — only a parked amendment may be resubmitted
    if amd["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    amd["status"] = "SUBMITTED"
    amd["additional_information"] = additional_information
    amd["submission_count"] = amd["submission_count"] + 1
    store.touch(amd)
    return ok(store.public(amd))
