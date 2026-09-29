"""Feed syndication: queueing, window contention, slots, fees, responses and requeue."""
from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import (get_content_version, get_job, get_listing, get_rejection_error, job_out,
                      rejection_error_out, require_attribute_key)
from errors import ApiError
from store import base_row, db, in_order, now, touch

bp = Blueprint("syndication", __name__)

OUTCOMES = ("ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED")
SEVERITIES = ("BLOCKING", "WARNING")
RESOLUTION_MODES = ("FIX", "WAIVE")
BLOCKED_SHELF_STATES = ("SUSPENDED", "UNAUTHORIZED")


def _closed_intervals_intersect(a_start, a_end, b_start, b_end):
    """Closed-interval test: touching endpoints DO intersect (PRD 3.6)."""
    return a_start <= b_end and b_start <= a_end


def _window_guards(listing, retailer, job_version, slot_count, window_start, window_end,
                   exclude_job_id=None):
    """Evaluation steps 34, 36, 42, 44 and 45 in their pinned order."""
    if listing["shelf_state"] in BLOCKED_SHELF_STATES:
        raise ApiError("ERR_LISTING_SHELF_BLOCKED")
    if job_version is None or job_version["state"] != "PINNED" \
            or job_version["product_id"] != listing["product_id"]:
        raise ApiError("ERR_VERSION_NOT_PINNED")
    if calc.dec(listing.get("completeness_score_certified") or 0) < calc.COMPLETENESS_GATE:
        raise ApiError("ERR_COMPLETENESS_BELOW_THRESHOLD")
    overlapping = 0
    for other in calc.jobs_of_retailer(retailer["id"]):
        if other["state"] not in calc.HOLDING_JOB_STATES:
            continue
        if exclude_job_id is not None and other["id"] == exclude_job_id:
            continue
        if _closed_intervals_intersect(window_start, window_end,
                                       other["window_start"], other["window_end"]):
            overlapping += 1
    if overlapping >= int(retailer["max_concurrent_feed_windows"]):
        raise ApiError("ERR_FEED_WINDOW_CONFLICT")
    reserved = calc.feed_slots_reserved(retailer["id"])
    if reserved + int(slot_count) > int(retailer["feed_slot_capacity"]):
        raise ApiError("ERR_FEED_CAPACITY_EXCEEDED")


@bp.route("/syndication-jobs", methods=["POST"])
@endpoint(["SyndicationOperator"])
def create_job():
    data = validate.body()
    listing_id = validate.req_str(data, "retailer_listing_id", 1)
    version_id = validate.req_str(data, "content_version_id", 1)
    slot_count = validate.req_int(data, "slot_count", 1, 10)
    window_start = validate.window_dt(data, "window_start")
    window_end = validate.window_dt(data, "window_end")
    expected_retailer_version = validate.req_int(data, "expected_retailer_version")
    if window_end <= window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    job_version = get_content_version(version_id)
    listing = get_listing(listing_id)
    retailer = db.retailers.get(listing["retailer_id"])
    if retailer is None:
        raise ApiError("ERR_RETAILER_NOT_FOUND")
    if expected_retailer_version != retailer["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if retailer["status"] != "ACTIVE":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE")
    _window_guards(listing, retailer, job_version, slot_count, window_start, window_end)

    job = base_row()
    job.update({
        "retailer_listing_id": listing["id"],
        "content_version_id": job_version["id"],
        "slot_count": slot_count,
        "window_start": window_start,
        "window_end": window_end,
        "state": "QUEUED",
        "attempt_no": 1,
        "readiness_at_queue": calc.dec(listing.get("readiness_score") or 0),
        "service_fee_cents": calc.service_fee_cents(slot_count, window_start, now()),
        "transmitted_at": None,
        "responded_at": None,
    })
    db.jobs[job["id"]] = job
    recompute.bump_retailer_ledger(retailer)
    if listing["syndication_state"] == "NOT_SYNDICATED":
        recompute.set_syndication_state(listing, "PENDING")
    return envelope.created(job_out(job))


@bp.route("/syndication-jobs/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_job(row_id):
    return envelope.ok(job_out(get_job(row_id)))


@bp.route("/syndication-jobs", methods=["GET"])
@endpoint(ALL_ROLES)
def list_jobs():
    limit, offset = envelope.page_params()
    rows = in_order(list(db.jobs.values()))
    for arg in ("retailer_listing_id", "content_version_id", "state"):
        value = request.args.get(arg)
        if value is not None:
            rows = [r for r in rows if r.get(arg) == value]
    return envelope.paged_with(rows, job_out, limit, offset)


@bp.route("/syndication-jobs/<row_id>/transmit", methods=["POST"])
@endpoint(["SyndicationOperator"])
def transmit_job(row_id):
    job = get_job(row_id)
    listing = db.listings.get(job["retailer_listing_id"])
    retailer = db.retailers.get(listing["retailer_id"]) if listing else None
    if retailer is None or retailer["status"] != "ACTIVE":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE")
    if job["state"] != "QUEUED":
        raise ApiError("ERR_INVALID_JOB_STATE")
    job["state"] = "TRANSMITTED"
    job["transmitted_at"] = now()
    touch(job)
    return envelope.ok(job_out(job))


@bp.route("/syndication-jobs/<row_id>/cancel", methods=["POST"])
@endpoint(["SyndicationOperator"])
def cancel_job(row_id):
    job = get_job(row_id)
    if job["state"] not in calc.HOLDING_JOB_STATES:
        raise ApiError("ERR_INVALID_JOB_STATE")
    job["state"] = "CANCELLED"
    touch(job)
    listing = db.listings.get(job["retailer_listing_id"])
    retailer = db.retailers.get(listing["retailer_id"]) if listing else None
    if retailer is not None:
        recompute.bump_retailer_ledger(retailer)
    for row in calc.rejection_errors_of_job(job["id"]):
        if row["state"] != "OPEN":
            continue
        row["state"] = "WAIVED"
        row["resolution_mode"] = "WAIVE"
        row["resolution_note"] = "CANCELLED_WITH_JOB"
        row["resolved_at"] = now()
        touch(row)
    if listing is not None:
        before = listing["syndication_state"]
        recompute.settle_syndication_state_after_release(listing)
        recompute.recompute_listing_readiness(listing)
        if before != listing["syndication_state"]:
            product = db.products.get(listing["product_id"])
            if product is not None:
                recompute.recompute_product_health(product)
    return envelope.ok(job_out(job))


def _parse_error_rows(data, outcome):
    """Step 8 body shape for errors[] plus step 20 attribute-key resolution."""
    raw = data.get("errors")
    if raw is None:
        rows = []
    elif not isinstance(raw, list):
        validate.bad("errors")
        rows = []
    else:
        rows = raw
    parsed = []
    for element in rows:
        if not isinstance(element, dict):
            validate.bad("errors")
        parsed.append({
            "retailer_error_code": validate.req_str(element, "retailer_error_code", 1, 40),
            "attribute_key": validate.opt_str(element, "attribute_key", 1, 40),
            "severity": validate.req_enum(element, "severity", SEVERITIES),
            "message": validate.req_str(element, "message", 1, 500),
        })
    blocking = [p for p in parsed if p["severity"] == "BLOCKING"]
    if outcome == "ACCEPTED":
        if parsed:
            validate.bad("errors")
    elif outcome == "PARTIALLY_ACCEPTED":
        if not parsed or blocking:
            validate.bad("errors")
    else:
        if not parsed or not blocking:
            validate.bad("errors")
    for element in parsed:
        if element["attribute_key"] is not None:
            require_attribute_key(element["attribute_key"])
    return parsed


@bp.route("/syndication-jobs/<row_id>/retailer-response", methods=["POST"])
@endpoint(["RetailerIntegration"])
def retailer_response(row_id):
    job = get_job(row_id)
    listing = db.listings.get(job["retailer_listing_id"])
    if listing is None or listing["retailer_id"] != g.user_id:
        raise ApiError("ERR_RETAILER_SCOPE_VIOLATION")
    data = validate.body()
    outcome = validate.req_enum(data, "outcome", OUTCOMES)
    error_rows = _parse_error_rows(data, outcome)
    if job["state"] != "TRANSMITTED":
        raise ApiError("ERR_INVALID_JOB_STATE")

    # ---- hop 1: the job state write and the per-row rejection errors
    job["state"] = outcome
    job["responded_at"] = now()
    touch(job)
    for element in error_rows:
        row = base_row()
        row.update({
            "syndication_job_id": job["id"],
            "retailer_error_code": element["retailer_error_code"],
            "attribute_key": element["attribute_key"],
            "severity": element["severity"],
            "message": element["message"],
            "state": "OPEN",
            "resolution_mode": None,
            "resolved_by_user_id": None,
            "resolution_note": None,
            "resolved_at": None,
        })
        db.rejection_errors[row["id"]] = row
    retailer = db.retailers.get(listing["retailer_id"])
    if retailer is not None:
        recompute.bump_retailer_ledger(retailer)

    product = db.products.get(listing["product_id"])
    if outcome == "REJECTED":
        # ---- hop 2: blocking rows hold the listing on ERROR_HOLD
        recompute.recompute_listing_blocking(listing)
        recompute.set_syndication_state(listing, "ERROR_HOLD")
        recompute.recompute_listing_readiness(listing)
        # ---- hop 3: the listing now qualifies for the health input set
        alert = None
        if product is not None:
            recompute.recompute_product_health(product)
            alert = recompute.maybe_health_degraded(listing, product)
            # ---- hop 4: the alert roll-up
            recompute.recompute_product_alerts(product)
            if alert is not None:
                touch(product)
    else:
        recompute.set_syndication_state(listing, "LIVE")
        recompute.recompute_listing_blocking(listing)
        recompute.recompute_listing_readiness(listing)
        if product is not None:
            recompute.recompute_product_health(product)
    return envelope.ok(job_out(job))


@bp.route("/syndication-jobs/<row_id>/rejection-errors", methods=["GET"])
@endpoint(ALL_ROLES)
def list_rejection_errors(row_id):
    limit, offset = envelope.page_params()
    job = get_job(row_id)
    rows = calc.rejection_errors_of_job(job["id"])
    severity = request.args.get("severity")
    state = request.args.get("state")
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return envelope.paged_with(rows, rejection_error_out, limit, offset)


@bp.route("/rejection-errors/<row_id>/resolve", methods=["POST"])
@endpoint(["SyndicationOperator", "ShelfAdmin"])
def resolve_rejection_error(row_id):
    data = validate.body()
    mode = validate.req_enum(data, "resolution_mode", RESOLUTION_MODES)
    note = validate.req_str(data, "resolution_note", 1)
    row = get_rejection_error(row_id)
    if row["state"] != "OPEN":
        raise ApiError("ERR_REJECTION_ERROR_ALREADY_CLOSED")
    if mode == "WAIVE" and row["severity"] == "BLOCKING" and g.role != "ShelfAdmin":
        raise ApiError("ERR_WAIVE_NOT_PERMITTED")
    row["state"] = "RESOLVED" if mode == "FIX" else "WAIVED"
    row["resolution_mode"] = mode
    row["resolution_note"] = note
    row["resolved_by_user_id"] = g.user_id
    row["resolved_at"] = now()
    touch(row)

    job = db.jobs.get(row["syndication_job_id"])
    listing = db.listings.get(job["retailer_listing_id"]) if job else None
    if listing is not None:
        recompute.recompute_listing_blocking(listing)
        holding = [j for j in calc.jobs_of_listing(listing["id"])
                   if j["state"] in calc.HOLDING_JOB_STATES]
        changed = False
        if (int(listing["open_blocking_error_count"]) == 0 and not holding
                and listing["syndication_state"] == "ERROR_HOLD"):
            changed = recompute.set_syndication_state(listing, "NOT_SYNDICATED")
        recompute.recompute_listing_readiness(listing)
        if changed:
            product = db.products.get(listing["product_id"])
            if product is not None:
                recompute.recompute_product_health(product)
    return envelope.ok(rejection_error_out(row))


@bp.route("/syndication-jobs/<row_id>/requeue", methods=["POST"])
@endpoint(["SyndicationOperator"])
def requeue_job(row_id):
    data = validate.body()
    slot_count = validate.opt_int(data, "slot_count", 1, 10)
    new_start = validate.window_dt(data, "window_start", required=False)
    new_end = validate.window_dt(data, "window_end", required=False)
    expected_retailer_version = validate.opt_int(data, "expected_retailer_version")
    if new_start is not None and new_end is not None and new_end <= new_start:
        raise ApiError("ERR_WINDOW_INVALID")
    job = get_job(row_id)
    window_start = new_start if new_start is not None else job["window_start"]
    window_end = new_end if new_end is not None else job["window_end"]
    if window_end <= window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    effective_slots = slot_count if slot_count is not None else int(job["slot_count"])

    listing = db.listings.get(job["retailer_listing_id"])
    if listing is None:
        raise ApiError("ERR_LISTING_NOT_FOUND")
    retailer = db.retailers.get(listing["retailer_id"])
    if retailer is None:
        raise ApiError("ERR_RETAILER_NOT_FOUND")
    if expected_retailer_version is not None and expected_retailer_version != retailer["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if retailer["status"] != "ACTIVE":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE")
    if job["state"] not in ("REJECTED", "PARTIALLY_ACCEPTED"):
        raise ApiError("ERR_INVALID_JOB_STATE")
    for row in calc.rejection_errors_of_job(job["id"]):
        if row["severity"] == "BLOCKING" and row["state"] not in ("RESOLVED", "WAIVED"):
            raise ApiError("ERR_BLOCKING_ERRORS_UNRESOLVED")
    job_version = db.content_versions.get(job["content_version_id"])
    _window_guards(listing, retailer, job_version, effective_slots, window_start, window_end,
                   exclude_job_id=job["id"])

    job["state"] = "QUEUED"
    job["attempt_no"] = int(job["attempt_no"]) + 1
    job["slot_count"] = effective_slots
    job["window_start"] = window_start
    job["window_end"] = window_end
    job["transmitted_at"] = None
    job["responded_at"] = None
    job["readiness_at_queue"] = calc.dec(listing.get("readiness_score") or 0)
    job["service_fee_cents"] = calc.service_fee_cents(effective_slots, window_start, now())
    touch(job)
    recompute.bump_retailer_ledger(retailer)
    before = listing["syndication_state"]
    recompute.set_syndication_state(listing, "PENDING")
    recompute.recompute_listing_readiness(listing)
    if before == "LIVE":
        # The listing leaves the health input set until the new attempt resolves.
        product = db.products.get(listing["product_id"])
        if product is not None:
            recompute.recompute_product_health(product)
    return envelope.ok(job_out(job))
