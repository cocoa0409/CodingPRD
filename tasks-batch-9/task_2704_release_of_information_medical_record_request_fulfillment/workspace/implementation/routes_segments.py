"""Record segments: compilation tasks, dispositions and the redaction workflow."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from security import STAFF, actor

bp = Blueprint("segments", __name__)


def _get_segment(id):
    seg = store.segments.get(id)
    if seg is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")
    return seg


def _buffered_window(start, fac):
    buffer_delta = timedelta(minutes=fac["legacy_gateway_buffer_minutes"])
    job_delta = timedelta(minutes=fac["legacy_gateway_job_minutes"])
    return start - buffer_delta, start + job_delta + buffer_delta


@bp.post("/roi/record-segments")
def create_segment():
    uid, role = actor(["RecordsAnalyst"])
    body = v.body()

    request_id = v.req_id(body, "request_id")
    source_system = v.req_enum(body, "source_system", store.SOURCE_SYSTEMS)
    category = v.req_enum(body, "category", store.CATEGORIES)
    raw_start, start = v.opt_datetime(body, "legacy_job_start_at")
    # the strictly conditional legacy window (priority 4)
    if source_system == "LEGACY_ARCHIVE" and start is None:
        v.bad()
    if source_system != "LEGACY_ARCHIVE" and start is not None:
        v.bad()

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    fac = calc.facility_of(req)
    if fac is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")

    if source_system == "LEGACY_ARCHIVE":
        if not fac["legacy_archive_enabled"]:
            raise ApiError("ERR_LEGACY_ARCHIVE_DISABLED")
        new_from, new_to = _buffered_window(start, fac)
        for other in store.ordered(list(store.segments.values())):
            if other["source_system"] != "LEGACY_ARCHIVE":
                continue
            if other["retrieval_status"] not in ("PENDING", "RETRIEVED"):
                continue
            other_request = store.requests.get(other["request_id"])
            if other_request is None or other_request["facility_id"] != fac["id"]:
                continue
            other_start = store.parse_dt(other["legacy_job_start_at"])
            if other_start is None:
                continue
            other_from, other_to = _buffered_window(other_start, fac)
            # both windows are closed at both ends: touching already collides
            if new_from <= other_to and other_from <= new_to:
                raise ApiError("ERR_LEGACY_WINDOW_CONTENTION")

    seg = store.common_fields()
    seg["request_id"] = request_id
    seg["source_system"] = source_system
    seg["category"] = category
    seg["legacy_job_start_at"] = raw_start
    seg["legacy_job_end_at"] = None
    if start is not None:
        seg["legacy_job_end_at"] = store.fmt(
            start + timedelta(minutes=fac["legacy_gateway_job_minutes"]))
    seg["page_count"] = 0
    seg["retrieval_status"] = "PENDING"
    seg["sensitivity_status"] = "UNCLASSIFIED"
    seg["redaction_status"] = "NOT_REQUIRED"
    seg["redacted_page_count"] = 0
    seg["redaction_applied_by_user_id"] = None
    seg["redaction_approved_by_user_id"] = None
    seg["retrieved_at"] = None
    seg["unavailable_reason"] = None
    seg["amended"] = False
    store.segments[seg["id"]] = seg
    return created(store.public(seg))


@bp.get("/roi/record-segments/<id>")
def read_segment(id):
    actor(STAFF)
    return ok(store.public(_get_segment(id)))


@bp.get("/roi/record-segments")
def list_segments():
    actor(STAFF)
    limit, offset = v.paging()
    rows = store.ordered(list(store.segments.values()))
    for field in ("request_id", "source_system", "category", "sensitivity_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ disposition
DISPOSITION_REQUEST_STATES = {
    "RETRIEVED": ("COMPILATION",),
    "UNAVAILABLE": ("COMPILATION",),
    "WITHDRAWN": ("COMPILATION", "SENSITIVE_REVIEW", "REDACTION"),
}
DISPOSITION_SEGMENT_STATES = {
    "RETRIEVED": ("PENDING",),
    "UNAVAILABLE": ("PENDING",),
    "WITHDRAWN": ("PENDING", "RETRIEVED"),
}


@bp.post("/roi/record-segments/<id>/disposition")
def record_disposition(id):
    uid, role = actor(["RecordsAnalyst"])
    body = v.body()
    disposition = v.req_enum(body, "disposition",
                             ["RETRIEVED", "UNAVAILABLE", "WITHDRAWN"])
    page_count = v.opt_int(body, "page_count")
    unavailable_reason = v.opt_str(body, "unavailable_reason", max_len=500)
    if disposition == "RETRIEVED" and page_count is None:
        v.bad()

    seg = _get_segment(id)
    req = store.requests.get(seg["request_id"])
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")

    if req["fulfillment_status"] not in DISPOSITION_REQUEST_STATES[disposition]:
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    if seg["retrieval_status"] not in DISPOSITION_SEGMENT_STATES[disposition]:
        raise ApiError("ERR_SEGMENT_STATE_INVALID")

    if disposition == "RETRIEVED":
        seg["retrieval_status"] = "RETRIEVED"
        seg["page_count"] = page_count
        seg["retrieved_at"] = store.fmt(store.now())
        # segment_sensitivity_classification: one set-membership test, once only
        fac = calc.facility_of(req)
        sensitive = fac["sensitive_categories_requiring_specific_authorization"] if fac else []
        seg["sensitivity_status"] = (
            "SEGREGATED_PENDING_REVIEW" if seg["category"] in sensitive else "NOT_SENSITIVE"
        )
    elif disposition == "UNAVAILABLE":
        seg["retrieval_status"] = "UNAVAILABLE"
        seg["page_count"] = 0
        seg["unavailable_reason"] = unavailable_reason
        seg["sensitivity_status"] = "UNCLASSIFIED"
    else:
        seg["retrieval_status"] = "WITHDRAWN"
        seg["sensitivity_status"] = "UNCLASSIFIED"
        seg["redaction_status"] = "NOT_REQUIRED"
        seg["redacted_page_count"] = 0

    store.touch(seg)
    calc.refresh_page_ledger(req)
    if disposition == "WITHDRAWN":
        calc.bubble_up_from_redaction(req)
    store.touch(req)
    return ok(store.public(seg))


# ============================================================ applying a redaction
@bp.post("/roi/record-segments/<id>/redaction")
def apply_redaction(id):
    uid, role = actor(["RecordsAnalyst"])
    body = v.body()
    redacted_page_count = v.req_int(body, "redacted_page_count")
    v.opt_str(body, "redaction_note", max_len=500)

    seg = _get_segment(id)
    req = store.requests.get(seg["request_id"])
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")

    if req["fulfillment_status"] != "REDACTION":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    if seg["redaction_status"] not in ("OPEN", "REWORK"):
        raise ApiError("ERR_SEGMENT_STATE_INVALID")
    if redacted_page_count > seg["page_count"]:
        raise ApiError("ERR_REDACTION_PAGE_COUNT_INVALID")

    seg["redaction_status"] = "APPLIED"
    seg["redacted_page_count"] = redacted_page_count
    seg["redaction_applied_by_user_id"] = uid
    store.touch(seg)
    # the page ledger does not move yet: redacted pages count only once APPROVED
    calc.refresh_page_ledger(req)
    store.touch(req)
    return ok(store.public(seg))


# ============================================================ deciding a redaction
@bp.post("/roi/record-segments/<id>/redaction-decision")
def decide_redaction(id):
    uid, role = actor(["ReleaseReviewer"])
    body = v.body()
    decision = v.req_enum(body, "decision", ["APPROVE", "REWORK"])
    v.opt_str(body, "note", max_len=500)

    seg = _get_segment(id)
    req = store.requests.get(seg["request_id"])
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")

    # priority 9 — the approver may not be the analyst who applied
    if uid == seg.get("redaction_applied_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if seg["redaction_status"] != "APPLIED":
        raise ApiError("ERR_SEGMENT_STATE_INVALID")

    if decision == "APPROVE":
        seg["redaction_status"] = "APPROVED"
        seg["redaction_approved_by_user_id"] = uid
    else:
        seg["redaction_status"] = "REWORK"
        seg["redaction_applied_by_user_id"] = None
    store.touch(seg)

    calc.refresh_page_ledger(req)
    if decision == "APPROVE":
        calc.bubble_up_from_redaction(req)
    store.touch(req)
    return ok(store.public(seg))
