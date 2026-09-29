"""Monitor-quarters: ingest, the hour budget, and the validation dimension."""
from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.common import (ensure_from_state, ensure_not_terminal, get_batch,
                           get_invalidation, get_monitor,
                           require_method_designated)
from services import cascade
from services import compute as K
from services import serialize as S

bp = Blueprint("batches", __name__)

BATCH_TERMINAL = ("INVALIDATED",)


def _read_batch_payload(data, prefix=""):
    """Exactly the per-quarter fields a single report carries."""
    return {
        "year": V.req_int(data, "year", lo=2000, hi=2100),
        "quarter": V.req_int(data, "quarter", lo=1, hi=4),
        "scheduled_hour_count": V.req_int(data, "scheduled_hour_count", lo=1, hi=2232),
        "quarterly_mean_concentration": V.req_number(data, "quarterly_mean_concentration", lo=0),
        "quarterly_mean_concentration_event_adjusted": V.opt_number(
            data, "quarterly_mean_concentration_event_adjusted", lo=0),
        "fourth_high_daily_max": V.opt_number(data, "fourth_high_daily_max", lo=0),
    }


def _new_batch(monitor_id, payload):
    rec = new_record()
    rec.update({
        "monitor_id": monitor_id,
        "validation_status": "RAW",
        "submission_status": "UNSUBMITTED",
        "validated_by_user_id": None,
        "invalidation_applied_by_user_ids": [],
        "batch_invalidation_reason": None,
        "reopen_count": 0,
    })
    rec.update(payload)
    store.data_batches[rec["id"]] = rec
    K.refresh_hour_accounting(rec)
    return rec


def _assert_period_unique(monitor_id, year, quarter, extra=()):
    for existing in store.data_batches.values():
        if (existing["monitor_id"] == monitor_id and existing["year"] == year
                and existing["quarter"] == quarter):
            raise ApiError("ERR_DUPLICATE_BATCH_PERIOD",
                           "A quarter %d Q%d already exists for this monitor." % (year, quarter))
    if (year, quarter) in extra:
        raise ApiError("ERR_DUPLICATE_BATCH_PERIOD",
                       "Two items of this request name the same period %d Q%d." % (year, quarter))


def _assert_period_ended(year, quarter):
    if K.next_quarter_start(year, quarter) > clock.now():
        raise ApiError("ERR_BATCH_PERIOD_NOT_ENDED",
                       "Quarter %d Q%d has not finished on the logical clock." % (year, quarter))


@bp.post("/data-batches")
@require("QaOfficer")
def report_batch():
    data = V.body()
    monitor_id = V.req_id(data, "monitor_id")
    payload = _read_batch_payload(data)
    get_monitor(monitor_id)
    _assert_period_unique(monitor_id, payload["year"], payload["quarter"])
    _assert_period_ended(payload["year"], payload["quarter"])
    rec = _new_batch(monitor_id, payload)
    return response.object_response(S.data_batch(rec), 201)


@bp.post("/data-batches/bulk-ingest")
@require("QaOfficer")
def bulk_ingest():
    data = V.body()
    monitor_id = V.req_id(data, "monitor_id")
    items = V.req_list(data, "batches", min_len=1)
    payloads = [_read_batch_payload(item) for item in items]
    get_monitor(monitor_id)
    seen = set()
    for payload in payloads:
        _assert_period_unique(monitor_id, payload["year"], payload["quarter"], seen)
        seen.add((payload["year"], payload["quarter"]))
    for payload in payloads:
        _assert_period_ended(payload["year"], payload["quarter"])
    created = [_new_batch(monitor_id, payload) for payload in payloads]
    return response.array_response([S.data_batch(b) for b in created], 201)


def _validation_gates(batch, caller):
    """The four checks of PRD 3.5, in their fixed order."""
    monitor = K.monitor_of_batch(batch)
    require_method_designated(K.method_of_monitor(monitor) if monitor is not None else None)
    if caller in batch["invalidation_applied_by_user_ids"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who invalidated hours of this quarter may not validate it.")
    if monitor is not None and K.effective_qc_posture(monitor) == "QC_DELINQUENT":
        raise ApiError("ERR_MONITOR_QC_DELINQUENT",
                       "The quarter's instrument is delinquent on its span checks.")


def _mark_validated(batch, caller):
    batch["validation_status"] = "VALIDATED"
    batch["validated_by_user_id"] = caller
    batch["batch_invalidation_reason"] = None
    K.refresh_hour_accounting(batch)
    touch(batch)
    cascade.rerun_rollups_for_batch(batch)


@bp.post("/data-batches/bulk-validate")
@require("QaOfficer")
def bulk_validate():
    data = V.body()
    monitor_id = V.req_id(data, "monitor_id")
    year = V.opt_int(data, "year", lo=2000, hi=2100)
    get_monitor(monitor_id)
    matched = [b for b in K.batches_of_monitor(monitor_id)
               if b["validation_status"] == "RAW" and (year is None or b["year"] == year)]
    if not matched:
        raise ApiError("ERR_NO_ELIGIBLE_BATCHES",
                       "No RAW quarter matches the bulk-validate selector.")
    matched.sort(key=lambda b: (b["year"], b["quarter"], b["created_at"], b["_seq"]))
    caller = actor()
    for batch in matched:
        _validation_gates(batch, caller)
    for batch in matched:
        _mark_validated(batch, caller)
    return response.array_response([S.data_batch(b) for b in matched])


@bp.post("/data-batches/<batch_id>/begin-validation")
@require("QaOfficer")
def begin_validation(batch_id):
    V.body()
    batch = get_batch(batch_id)
    ensure_not_terminal(batch["validation_status"], BATCH_TERMINAL, "data batch")
    ensure_from_state(batch["validation_status"], ("RAW", "REOPENED"), "data batch")
    batch["validation_status"] = "IN_VALIDATION"
    batch["validated_by_user_id"] = None
    touch(batch)
    return response.object_response(S.data_batch(batch))


@bp.post("/data-batches/<batch_id>/validate")
@require("QaOfficer")
def validate_batch(batch_id):
    data = V.body()
    V.opt_string(data, "validation_note")
    batch = get_batch(batch_id)
    ensure_not_terminal(batch["validation_status"], BATCH_TERMINAL, "data batch")
    ensure_from_state(batch["validation_status"], ("IN_VALIDATION",), "data batch")
    caller = actor()
    _validation_gates(batch, caller)
    _mark_validated(batch, caller)
    return response.object_response(S.data_batch(batch))


@bp.post("/data-batches/<batch_id>/invalidate")
@require("QaOfficer")
def invalidate_batch(batch_id):
    data = V.body()
    V.opt_string(data, "invalidation_note")
    batch = get_batch(batch_id)
    ensure_not_terminal(batch["validation_status"], BATCH_TERMINAL, "data batch")
    ensure_from_state(batch["validation_status"], ("IN_VALIDATION", "REOPENED"), "data batch")
    batch["validation_status"] = "INVALIDATED"
    batch["batch_invalidation_reason"] = "QA_REJECTED"
    batch["validated_by_user_id"] = None
    K.refresh_hour_accounting(batch)
    touch(batch)
    cascade.rerun_rollups_for_batch(batch)
    return response.object_response(S.data_batch(batch))


@bp.post("/data-batches/<batch_id>/reopen")
@require("QaOfficer")
def reopen_batch(batch_id):
    data = V.body()
    V.req_string(data, "reopen_reason", min_len=1)
    batch = get_batch(batch_id)
    ensure_not_terminal(batch["validation_status"], BATCH_TERMINAL, "data batch")
    ensure_from_state(batch["validation_status"], ("VALIDATED",), "data batch")
    if batch["submission_status"] == "CERTIFIED":
        raise ApiError("ERR_BATCH_CERTIFIED", "Certified data cannot be reopened.")
    batch["validation_status"] = "REOPENED"
    batch["reopen_count"] += 1
    batch["validated_by_user_id"] = None
    touch(batch)
    cascade.supersede_for_batch(batch, "BATCH_REVALIDATED")
    monitor = K.monitor_of_batch(batch)
    site = store.sites.get(monitor["site_id"]) if monitor is not None else None
    if site is not None:
        site["current_attainment_status"] = K.current_attainment_status(site["id"])
    cascade.rerun_rollups_for_batch(batch)
    return response.object_response(S.data_batch(batch))


@bp.get("/data-batches/<batch_id>")
@require(*ALL_ROLES)
def read_batch(batch_id):
    return response.object_response(S.data_batch(get_batch(batch_id)))


@bp.get("/data-batches")
@require(*ALL_ROLES)
def list_batches():
    limit, offset = V.pagination()
    monitor_id = V.q_string("monitor_id")
    year = V.q_int("year")
    quarter = V.q_int("quarter")
    validation_status = V.q_enum("validation_status", C.VALIDATION_STATUSES)
    submission_status = V.q_enum("submission_status", C.SUBMISSION_STATUSES)
    eligible = V.q_bool("regulatory_use_eligible")
    rows = list(store.data_batches.values())
    for row in rows:
        K.refresh_hour_accounting(row)
    if monitor_id is not None:
        rows = [b for b in rows if b["monitor_id"] == monitor_id]
    if year is not None:
        rows = [b for b in rows if b["year"] == year]
    if quarter is not None:
        rows = [b for b in rows if b["quarter"] == quarter]
    if validation_status is not None:
        rows = [b for b in rows if b["validation_status"] == validation_status]
    if submission_status is not None:
        rows = [b for b in rows if b["submission_status"] == submission_status]
    if eligible is not None:
        rows = [b for b in rows if b["regulatory_use_eligible"] == eligible]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.data_batch(b) for b in page], pagination=meta)


# --------------------------------------------------------------------------
# hour-range invalidations
# --------------------------------------------------------------------------
def check_hour_range(batch, start, end, error_id):
    """0 <= start < end <= scheduled_hour_count; an empty, negative or
    overrunning range is out of bounds (PRD 3.4 and 3.6)."""
    if start < 0 or end <= start or end > batch["scheduled_hour_count"]:
        raise ApiError(error_id,
                       "Hour range [%s, %s) is outside the quarter's %d scheduled hours."
                       % (start, end, batch["scheduled_hour_count"]))


def applied_invalidations(batch_id):
    return [i for i in K.invalidations_of_batch(batch_id) if i["status"] == "APPLIED"]


def ranges_intersect(a_start, a_end, b_start, b_end):
    """Half-open intervals with no buffer, so abutting ranges do not intersect."""
    return a_start < b_end and b_start < a_end


@bp.post("/data-batches/<batch_id>/invalidations")
@require("QaOfficer")
def create_invalidation(batch_id):
    data = V.body()
    start = V.req_int(data, "start_hour_index")
    end = V.req_int(data, "end_hour_index")
    code = V.req_enum(data, "invalidation_code", C.INVALIDATION_CODES)
    expected = V.req_int(data, "expected_data_batch_version")
    batch = get_batch(batch_id)
    if expected != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION",
                       "expected_data_batch_version %d does not match the quarter's current "
                       "version %d." % (expected, batch["version"]))
    if batch["validation_status"] == "INVALIDATED":
        raise ApiError("ERR_INVALID_STATE",
                       "The quarter has been written off wholesale; its hour ledger is closed.")
    check_hour_range(batch, start, end, "ERR_INVALIDATION_RANGE_OUT_OF_BOUNDS")
    for other in applied_invalidations(batch_id):
        if ranges_intersect(start, end, other["start_hour_index"], other["end_hour_index"]):
            raise ApiError("ERR_INVALIDATION_RANGE_OVERLAP",
                           "Hour range [%s, %s) intersects an applied invalidation." % (start, end))
    caller = actor()
    rec = new_record()
    rec.update({
        "data_batch_id": batch_id,
        "start_hour_index": start,
        "end_hour_index": end,
        "hours_affected": end - start,
        "invalidation_code": code,
        "status": "APPLIED",
        "applied_by_user_id": caller,
        "withdrawn_reason": None,
    })
    store.invalidations[rec["id"]] = rec
    # The author list is append-only and ordered by first append.
    if caller not in batch["invalidation_applied_by_user_ids"]:
        batch["invalidation_applied_by_user_ids"].append(caller)
    K.refresh_hour_accounting(batch)
    touch(batch)
    cascade.rerun_rollups_for_batch(batch)
    return response.object_response(S.invalidation(rec), 201)


@bp.post("/data-invalidations/<invalidation_id>/withdraw")
@require("QaOfficer")
def withdraw_invalidation(invalidation_id):
    data = V.body()
    withdrawn_reason = V.req_string(data, "withdrawn_reason", min_len=1)
    inv = get_invalidation(invalidation_id)
    batch = store.data_batches.get(inv["data_batch_id"])
    if batch is not None and batch["validation_status"] == "INVALIDATED":
        raise ApiError("ERR_INVALID_STATE",
                       "The quarter has been written off wholesale; its hour ledger is closed.")
    ensure_not_terminal(inv["status"], ("WITHDRAWN",), "data invalidation")
    ensure_from_state(inv["status"], ("APPLIED",), "data invalidation")
    inv["status"] = "WITHDRAWN"
    inv["withdrawn_reason"] = withdrawn_reason
    touch(inv)
    if batch is not None:
        K.refresh_hour_accounting(batch)
        touch(batch)
        cascade.rerun_rollups_for_batch(batch)
    return response.object_response(S.invalidation(inv))


@bp.get("/data-batches/<batch_id>/invalidations")
@require(*ALL_ROLES)
def list_batch_invalidations(batch_id):
    limit, offset = V.pagination()
    status = V.q_enum("status", C.INVALIDATION_STATUSES)
    code = V.q_enum("invalidation_code", C.INVALIDATION_CODES)
    get_batch(batch_id)
    rows = K.invalidations_of_batch(batch_id)
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if code is not None:
        rows = [i for i in rows if i["invalidation_code"] == code]
    rows.sort(key=lambda i: (i["start_hour_index"], i["created_at"], i["_seq"]))
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.invalidation(i) for i in page], pagination=meta)


@bp.get("/data-batches/<batch_id>/exclusions")
@require(*ALL_ROLES)
def list_batch_exclusions(batch_id):
    limit, offset = V.pagination()
    status = V.q_enum("status", C.EXCLUSION_STATUSES)
    get_batch(batch_id)
    rows = K.exclusions_of_batch(batch_id)
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=lambda e: (e["start_hour_index"], e["created_at"], e["_seq"]))
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.exclusion(e) for e in page], pagination=meta)
