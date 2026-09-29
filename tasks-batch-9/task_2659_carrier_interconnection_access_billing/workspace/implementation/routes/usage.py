"""Usage batches, call detail records, jurisdictionalisation and rating (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate, carrier_of_batch,
                  carrier_of_cdr, scope_check, scope_filter)
from constants import BATCH_DIRECTIONS, NPANXX_PATTERN, STATE_PATTERN
from dec import ceil_div, q4
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_carrier, get_cdr, get_usage_batch
from services.rating import jurisdictionalize, rate_batch
from store import base_record, db, now, ordered, touch

bp = Blueprint("usage", __name__)

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")


@bp.post("/usage-batches")
def open_batch():
    authenticate((ACCESS_BILLING_ANALYST,))
    payload = v.body()
    carrier_id = v.string(payload, "carrier_id")
    period_start = v.timestamp(payload, "period_start")
    period_end = v.timestamp(payload, "period_end")
    direction = v.enum(payload, "direction", BATCH_DIRECTIONS)
    exchange_reference = v.string(payload, "exchange_reference")

    carrier = get_carrier(carrier_id)

    for existing in ordered(db.usage_batches):
        if existing["carrier_id"] != carrier["id"]:
            continue
        if existing["direction"] != direction:
            continue
        # Periods are closed intervals: they may neither overlap nor touch.
        if period_start <= existing["period_end"] and existing["period_start"] <= period_end:
            raise ApiError("ERR_BATCH_PERIOD_OVERLAP",
                           "the period overlaps or touches an existing batch period")

    if period_end <= period_start or period_end >= now():
        raise ApiError("ERR_INVALID_USAGE_PERIOD",
                       "period_end must be after period_start and strictly before the clock")

    batch = base_record()
    batch.update({
        "carrier_id": carrier["id"],
        "period_start": period_start,
        "period_end": period_end,
        "direction": direction,
        "exchange_reference": exchange_reference,
        "status": "SUBMITTED",
        "record_count": 0,
        "total_billable_minutes": ZERO4,
        "signaling_determined_minutes": ZERO4,
        "indeterminate_minutes": ZERO4,
        "interstate_minutes": ZERO4,
        "intrastate_minutes": ZERO4,
        "local_minutes": ZERO4,
        "traffic_factor_filing_id": None,
        "factor_source": None,
        "interstate_amount_usd": ZERO2,
        "intrastate_amount_usd": ZERO2,
        "local_amount_usd": ZERO2,
        "rated_amount_usd": ZERO2,
        "rating_variant": None,
        "rerate_count": 0,
        "jurisdictionalized_at": None,
        "rated_at": None,
    })
    db.usage_batches[batch["id"]] = batch
    return object_response(batch, 201)


@bp.get("/usage-batches/<batch_id>")
def read_batch(batch_id):
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    batch = get_usage_batch(batch_id)
    scope_check(actor, batch["carrier_id"])
    return object_response(batch)


@bp.get("/usage-batches")
def list_batches():
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    rows = ordered(db.usage_batches)
    carrier_id = request.args.get("carrier_id")
    if carrier_id:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    filing_id = request.args.get("traffic_factor_filing_id")
    if filing_id:
        rows = [r for r in rows if r["traffic_factor_filing_id"] == filing_id]
    direction = request.args.get("direction")
    if direction:
        rows = [r for r in rows if r["direction"] == direction]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = scope_filter(actor, rows, carrier_of_batch)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/usage-batches/<batch_id>/call-detail-records")
def append_cdr(batch_id):
    actor = authenticate((ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE))
    batch = get_usage_batch(batch_id)
    payload = v.body()
    originating_npanxx = v.string(payload, "originating_npanxx", pattern=NPANXX_PATTERN)
    terminating_npanxx = v.string(payload, "terminating_npanxx", pattern=NPANXX_PATTERN)
    duration_seconds = v.integer(payload, "duration_seconds", ge=1)
    signaling_cpn_present = v.boolean(payload, "signaling_cpn_present")
    jip_state_code = v.string(payload, "jip_state_code", required=False,
                              pattern=STATE_PATTERN)
    originating_state_code = v.string(payload, "originating_state_code",
                                      required=False, pattern=STATE_PATTERN)
    terminating_state_code = v.string(payload, "terminating_state_code",
                                      required=False, pattern=STATE_PATTERN)
    same_local_calling_area = v.boolean(payload, "same_local_calling_area")

    scope_check(actor, batch["carrier_id"])

    if batch["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BATCH_STATE",
                       "records may only be appended while the batch is SUBMITTED")
    if terminating_state_code is None:
        raise ApiError("ERR_CDR_UNRATEABLE",
                       "a record without a terminating_state_code is unrateable")

    cdr = base_record(with_version=False)
    cdr.update({
        "usage_batch_id": batch["id"],
        "originating_npanxx": originating_npanxx,
        "terminating_npanxx": terminating_npanxx,
        "duration_seconds": duration_seconds,
        "signaling_cpn_present": signaling_cpn_present,
        "jip_state_code": jip_state_code,
        "originating_state_code": originating_state_code,
        "terminating_state_code": terminating_state_code,
        "same_local_calling_area": same_local_calling_area,
        "billable_minutes": ceil_div(duration_seconds, 60),
        "jurisdiction": None,
        "jurisdiction_source": None,
        "rated_amount_usd": None,
    })
    db.cdrs[cdr["id"]] = cdr

    batch["record_count"] += 1
    batch["total_billable_minutes"] = q4(batch["total_billable_minutes"]
                                         + cdr["billable_minutes"])
    touch(batch)
    return object_response(cdr, 201)


@bp.get("/usage-batches/<batch_id>/call-detail-records")
def list_batch_cdrs(batch_id):
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    batch = get_usage_batch(batch_id)
    scope_check(actor, batch["carrier_id"])
    rows = [c for c in ordered(db.cdrs) if c["usage_batch_id"] == batch["id"]]
    jurisdiction = request.args.get("jurisdiction")
    if jurisdiction:
        rows = [r for r in rows if r["jurisdiction"] == jurisdiction]
    source = request.args.get("jurisdiction_source")
    if source:
        rows = [r for r in rows if r["jurisdiction_source"] == source]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/call-detail-records/<cdr_id>")
def read_cdr(cdr_id):
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    cdr = get_cdr(cdr_id)
    scope_check(actor, carrier_of_cdr(cdr))
    return object_response(cdr)


@bp.get("/call-detail-records")
def list_cdrs():
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    rows = ordered(db.cdrs)
    batch_id = request.args.get("usage_batch_id")
    if batch_id:
        rows = [r for r in rows if r["usage_batch_id"] == batch_id]
    jurisdiction = request.args.get("jurisdiction")
    if jurisdiction:
        rows = [r for r in rows if r["jurisdiction"] == jurisdiction]
    source = request.args.get("jurisdiction_source")
    if source:
        rows = [r for r in rows if r["jurisdiction_source"] == source]
    rows = scope_filter(actor, rows, carrier_of_cdr)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/usage-batches/<batch_id>/jurisdictionalize")
def jurisdictionalize_batch(batch_id):
    authenticate((ACCESS_BILLING_ANALYST,))
    batch = get_usage_batch(batch_id)

    if batch["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BATCH_STATE",
                       "only a SUBMITTED batch may be jurisdictionalised")
    if batch["record_count"] < 1:
        raise ApiError("ERR_INVALID_BATCH_STATE",
                       "an empty batch cannot be jurisdictionalised")

    jurisdictionalize(batch)
    batch["status"] = "JURISDICTIONALIZED"
    batch["jurisdictionalized_at"] = now()
    touch(batch)
    return object_response(batch)


@bp.post("/usage-batches/<batch_id>/rate")
def rate_usage_batch(batch_id):
    authenticate((ACCESS_BILLING_ANALYST,))
    batch = get_usage_batch(batch_id)

    if batch["status"] != "JURISDICTIONALIZED":
        raise ApiError("ERR_INVALID_BATCH_STATE",
                       "only a JURISDICTIONALIZED batch may be rated")

    rate_batch(batch, enforce=True)
    batch["status"] = "RATED"
    batch["rated_at"] = now()
    touch(batch)
    return object_response(batch)
