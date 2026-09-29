"""Retention schedule, accessions and the destruction certificate."""
from flask import Blueprint, g

import domain
from core import (ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, ROLE_RECORDS,
                  STAFF_ROLES, ApiError, authorize, body_dict, db, fetch, fk,
                  invalid, listing, new_record, now_date, ok, opt_bool,
                  opt_enum, q, req_date, req_enum, req_int, req_str, touch)

bp = Blueprint("retention", __name__)

TRIGGERS = ("CREATION", "FISCAL_YEAR_END", "REQUEST_CLOSURE")
HOLDS = ("NONE", "LITIGATION_HOLD", "AUDIT_HOLD")


def _destruction_gates(series, item_count, cutoff_on):
    """PRD 3.9: hold -> permanent -> anchor -> elapsed -> count."""
    if series["legal_hold_status"] != "NONE":
        raise ApiError("ERR_SERIES_UNDER_LEGAL_HOLD", 409)
    if series["permanent"]:
        raise ApiError("ERR_SERIES_PERMANENT_RETENTION", 409)
    eligible = series["eligible_through_on"]
    if eligible is None:
        raise ApiError("ERR_RETENTION_ANCHOR_UNRESOLVED", 409)
    if eligible > now_date() or (cutoff_on is not None and cutoff_on > eligible):
        raise ApiError("ERR_RETENTION_PERIOD_NOT_ELAPSED", 409)
    if item_count > series["active_item_count"]:
        raise ApiError("ERR_DESTRUCTION_COUNT_EXCEEDS_ACTIVE", 422)


# ------------------------------------------------------- record series
@bp.route("/clerk/record-series", methods=["POST"])
def create_series():
    authorize((ROLE_RECORDS,))
    body = body_dict()
    series_code = req_str(body, "series_code")
    name = req_str(body, "name")
    retention_years = req_int(body, "retention_years", minimum=0, maximum=100)
    trigger = req_enum(body, "retention_trigger", TRIGGERS)
    permanent = opt_bool(body, "permanent", default=False)
    hold = opt_enum(body, "legal_hold_status", HOLDS, default="NONE")
    for existing in db.record_series.values():
        if existing["series_code"] == series_code:
            raise ApiError("ERR_DUPLICATE_SERIES_CODE", 422)
    series = new_record()
    series.update({
        "series_code": series_code,
        "name": name,
        "retention_years": retention_years,
        "retention_trigger": trigger,
        "permanent": permanent,
        "legal_hold_status": hold,
        "last_accessioned_on": None,
        "total_accessioned_count": 0,
        "active_item_count": 0,
        "destroyed_item_count": 0,
        "eligible_through_on": None,
    })
    db.record_series[series["id"]] = series
    return ok(series, 201)


@bp.route("/clerk/record-series/<series_id>", methods=["GET"])
def get_series(series_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.record_series, series_id, "ERR_SERIES_NOT_FOUND"))


@bp.route("/clerk/record-series/<series_id>", methods=["PUT"])
def update_series(series_id):
    authorize((ROLE_RECORDS,))
    series = fetch(db.record_series, series_id, "ERR_SERIES_NOT_FOUND")
    body = body_dict()
    hold = opt_enum(body, "legal_hold_status", HOLDS)
    permanent = opt_bool(body, "permanent")
    if hold is not None:
        series["legal_hold_status"] = hold
    if permanent is not None:
        series["permanent"] = permanent
    touch(series)
    domain.recompute_series_eligibility(series)
    return ok(series)


@bp.route("/clerk/record-series/<series_id>/accessions", methods=["POST"])
def create_accession(series_id):
    authorize((ROLE_RECORDS, ROLE_DEPUTY_CLERK))
    series = fetch(db.record_series, series_id, "ERR_SERIES_NOT_FOUND")
    body = body_dict()
    item_count = req_int(body, "item_count", minimum=0)
    accessioned_on = req_date(body, "accessioned_on")
    series["total_accessioned_count"] = series["total_accessioned_count"] + item_count
    series["active_item_count"] = series["active_item_count"] + item_count
    current = series["last_accessioned_on"]
    if current is None or accessioned_on > current:
        series["last_accessioned_on"] = accessioned_on
    touch(series)
    domain.recompute_series_eligibility(series)
    # PRD 4: an accession "returns the affected `RecordSeries` rather than a
    # separate accession record", so it is not a creation endpoint -- it mutates
    # an existing resource and therefore answers 200.
    return ok(series)


# --------------------------------------------------- destruction batches
@bp.route("/clerk/destruction-batches", methods=["POST"])
def create_batch():
    authorize((ROLE_RECORDS, ROLE_DEPUTY_CLERK))
    body = body_dict()
    series = fk(body, "series_id", db.record_series, "ERR_SERIES_NOT_FOUND")
    item_count = req_int(body, "item_count", minimum=1)
    cutoff_on = req_date(body, "cutoff_on")
    if series is None:
        raise invalid("Field 'series_id' is required.")
    _destruction_gates(series, item_count, cutoff_on)
    batch = new_record()
    batch.update({
        "series_id": series["id"],
        "item_count": item_count,
        "cutoff_on": cutoff_on,
        "eligible_through_on": series["eligible_through_on"],
        "status": "PROPOSED",
        "blocking_request_id": domain.blocking_request_for(series["id"]),
        "proposed_by_officer_id": g.user_id,
        "certifying_officer_id": None,
        "certified_on": None,
        "rescind_reason": None,
    })
    db.batches[batch["id"]] = batch
    return ok(batch, 201)


@bp.route("/clerk/destruction-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.batches, batch_id, "ERR_BATCH_NOT_FOUND"))


@bp.route("/clerk/destruction-batches", methods=["GET"])
def list_batches():
    authorize(STAFF_ROLES)
    return listing(list(db.batches.values()), {
        "series_id": q("series_id"),
        "blocking_request_id": q("blocking_request_id"),
        "status": q("status"),
    })


@bp.route("/clerk/destruction-batches/<batch_id>/certify", methods=["POST"])
def certify_batch(batch_id):
    authorize((ROLE_CITY_CLERK, ROLE_RECORDS))
    batch = fetch(db.batches, batch_id, "ERR_BATCH_NOT_FOUND")
    body = body_dict()
    certified_on = req_date(body, "certified_on")
    if batch["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_BATCH_STATE", 409)
    if g.user_id == batch["proposed_by_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    series = db.record_series.get(batch["series_id"])
    if series is None:
        raise ApiError("ERR_SERIES_NOT_FOUND", 404)
    if series["legal_hold_status"] != "NONE":
        raise ApiError("ERR_SERIES_UNDER_LEGAL_HOLD", 409)
    if series["permanent"]:
        raise ApiError("ERR_SERIES_PERMANENT_RETENTION", 409)
    # recomputed at this moment: a request filed after the proposal still stops it
    blocking = domain.blocking_request_for(series["id"])
    if blocking is not None:
        raise ApiError("ERR_SERIES_HAS_OPEN_REQUEST", 409)
    if batch["item_count"] > series["active_item_count"]:
        raise ApiError("ERR_DESTRUCTION_COUNT_EXCEEDS_ACTIVE", 422)
    batch["blocking_request_id"] = blocking
    batch["status"] = "CERTIFIED"
    batch["certifying_officer_id"] = g.user_id
    batch["certified_on"] = certified_on
    touch(batch)
    series["active_item_count"] = series["active_item_count"] - batch["item_count"]
    series["destroyed_item_count"] = (series["destroyed_item_count"]
                                     + batch["item_count"])
    touch(series)
    return ok(batch)


@bp.route("/clerk/destruction-batches/<batch_id>/rescind", methods=["POST"])
def rescind_batch(batch_id):
    authorize((ROLE_RECORDS,))
    batch = fetch(db.batches, batch_id, "ERR_BATCH_NOT_FOUND")
    body = body_dict()
    reason = req_str(body, "rescind_reason")
    if batch["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_BATCH_STATE", 409)
    batch["status"] = "RESCINDED"
    batch["rescind_reason"] = reason
    touch(batch)
    series = db.record_series.get(batch["series_id"])
    if series is not None:
        # compensating action: the custody triple returns to its pre-certify values
        series["active_item_count"] = series["active_item_count"] + batch["item_count"]
        series["destroyed_item_count"] = (series["destroyed_item_count"]
                                         - batch["item_count"])
        touch(series)
    return ok(batch)
