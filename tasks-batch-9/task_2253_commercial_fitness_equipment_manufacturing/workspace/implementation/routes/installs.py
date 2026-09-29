"""Delivery and installation jobs (PRD 3.7). Half-open, travel-buffered geometry."""

from datetime import timedelta

from flask import Blueprint

import calc
from auth import (
    check_facility_scope,
    check_partner_filter,
    check_partner_scope,
    get_install_job,
    get_order,
    get_partner,
    require,
)
from constants import (
    INSTALL_JOB_OPEN,
    INSTALL_JOB_STATUSES,
    INSTALL_TRAVEL_BUFFER_MINUTES,
    WEEKDAYS,
)
from envelope import created, ok, ok_list
from errors import ApiError
from store import mutate, new_entity, store
from validation import (
    field_datetime,
    field_decimal,
    field_id,
    field_int,
    field_str,
    get_body,
    paginate,
    paging,
    query_enum,
    query_str,
)

bp = Blueprint("installs", __name__)


def _training_current(partner):
    """Ladder rung 17."""
    expiry = calc.dt(partner["training_current_until"])
    if expiry is None or expiry <= store.now():
        raise ApiError(
            "ERR_PARTNER_TRAINING_EXPIRED",
            "The service partner's training currency has lapsed.",
        )


def _effective_end(window_end_dt):
    return window_end_dt + timedelta(minutes=INSTALL_TRAVEL_BUFFER_MINUTES)


@bp.post("/install-jobs")
@require("OrderPlanner")
def create_install_job():
    body = get_body()
    order_id = field_id(body, "order_id")
    service_partner_id = field_id(body, "service_partner_id")
    window_start, start_dt = field_datetime(body, "window_start")
    window_end, end_dt = field_datetime(body, "window_end")
    estimated_labor_hours = field_decimal(
        body, "estimated_labor_hours", exclusive_min=0, maximum=400
    )

    # rung 8 — window sanity
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW", "window_end must be strictly after window_start."
        )

    # rung 9 — body reference existence
    order = get_order(order_id)
    partner = get_partner(service_partner_id)

    # rung 11 — declared transition
    if order["config_status"] != "CONFIRMED" or order["fulfillment_status"] not in (
        "IN_PRODUCTION",
        "STAGED",
    ):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The order must be CONFIRMED and IN_PRODUCTION or STAGED.",
        )

    # rung 17 — training currency
    _training_current(partner)

    # rung 18 — category certification
    for category in sorted(calc.order_categories(order)):
        if category not in partner["certified_categories"]:
            raise ApiError(
                "ERR_PARTNER_NOT_CERTIFIED_FOR_CATEGORY",
                "The partner is not certified for category %s." % category,
            )

    # rung 29 — order has lines
    if not calc.has_active_line(order):
        raise ApiError("ERR_ORDER_HAS_NO_LINES", "The order has no ACTIVE line.")

    # rung 30 — one open install job per order
    for job in store.install_jobs.values():
        if job["order_id"] == order["id"] and job["status"] in INSTALL_JOB_OPEN:
            raise ApiError(
                "ERR_INSTALL_JOB_ALREADY_OPEN",
                "The order already has an open install job.",
            )

    # rung 31 — blackout weekdays, both endpoint dates in UTC, inclusive
    facility = store.facilities[order["facility_id"]]
    blackout = facility["install_blackout_weekdays"] or []
    for moment in (start_dt, end_dt):
        if WEEKDAYS[moment.weekday()] in blackout:
            raise ApiError(
                "ERR_INSTALL_BLACKOUT_DAY",
                "The install window touches a blacked-out weekday.",
            )

    # rung 32 — partner calendar conflict, HALF-OPEN with travel buffer
    new_effective_end = _effective_end(end_dt)
    for job in calc.partner_jobs(partner["id"]):
        if job["status"] not in INSTALL_JOB_OPEN:
            continue
        existing_start = calc.dt(job["window_start"])
        existing_effective_end = _effective_end(calc.dt(job["window_end"]))
        if start_dt < existing_effective_end and existing_start < new_effective_end:
            raise ApiError(
                "ERR_INSTALL_WINDOW_CONFLICT",
                "The partner's crew calendar is already occupied.",
            )

    # rung 34 — partner hour capacity
    committed = calc.partner_committed_hours(partner)
    if committed + estimated_labor_hours > calc.dec(partner["certified_hours_capacity"]):
        raise ApiError(
            "ERR_PARTNER_CAPACITY_EXCEEDED",
            "The booking would exceed the partner's certified hours capacity.",
        )

    job = new_entity(
        {
            "order_id": order["id"],
            "service_partner_id": partner["id"],
            "window_start": window_start,
            "window_end": window_end,
            "travel_buffer_minutes": INSTALL_TRAVEL_BUFFER_MINUTES,
            "estimated_labor_hours": estimated_labor_hours,
            "actual_labor_hours": None,
            "punch_list_open_count": 0,
            "status": "SCHEDULED",
            "completed_at": None,
        }
    )
    store.install_jobs[job["id"]] = job
    calc.recompute_partner(partner)
    return created(job)


@bp.get("/install-jobs")
@require("OrderPlanner", "ServicePartnerTech", "ServiceOpsAdmin", "FacilityManager")
def list_install_jobs():
    limit, offset = paging()
    check_partner_filter()
    order_id = query_str("order_id")
    service_partner_id = query_str("service_partner_id")
    status = query_enum("status", INSTALL_JOB_STATUSES)

    rows = list(store.install_jobs.values())
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if service_partner_id is not None:
        rows = [r for r in rows if r["service_partner_id"] == service_partner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/install-jobs/<job_id>")
@require("OrderPlanner", "ServicePartnerTech", "ServiceOpsAdmin", "FacilityManager")
def read_install_job(job_id):
    job = get_install_job(job_id)
    order = store.orders[job["order_id"]]
    check_facility_scope(order["facility_id"])
    check_partner_scope(job["service_partner_id"])
    return ok(job)


@bp.post("/install-jobs/<job_id>/arrive")
@require("ServicePartnerTech")
def arrive_install_job(job_id):
    job = get_install_job(job_id)
    check_partner_scope(job["service_partner_id"])
    get_body()

    order = store.orders[job["order_id"]]
    if job["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a SCHEDULED job reports arrival."
        )
    if order["fulfillment_status"] != "STAGED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "The order must be STAGED for arrival."
        )

    partner = store.service_partners[job["service_partner_id"]]
    _training_current(partner)

    with mutate(job):
        job["status"] = "ON_SITE"
    with mutate(order):
        order["fulfillment_status"] = "INSTALLING"
    return ok(job)


@bp.post("/install-jobs/<job_id>/complete")
@require("ServicePartnerTech")
def complete_install_job(job_id):
    job = get_install_job(job_id)
    check_partner_scope(job["service_partner_id"])
    body = get_body()
    actual_labor_hours = field_decimal(body, "actual_labor_hours", exclusive_min=0)
    punch_list_open_count = field_int(body, "punch_list_open_count", minimum=0)

    if job["status"] != "ON_SITE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only an ON_SITE job may be completed."
        )

    with mutate(job):
        job["actual_labor_hours"] = actual_labor_hours
        job["punch_list_open_count"] = punch_list_open_count

    if punch_list_open_count >= 1:
        with mutate(job):
            job["status"] = "PUNCH_LIST"
        return ok(job)

    calc.install_completion_cascade(job)
    return ok(job)


@bp.post("/install-jobs/<job_id>/resolve-punch-list")
@require("ServicePartnerTech")
def resolve_punch_list(job_id):
    job = get_install_job(job_id)
    check_partner_scope(job["service_partner_id"])
    body = get_body()
    field_str(body, "resolution_note", min_len=1)

    if job["status"] != "PUNCH_LIST":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a PUNCH_LIST job may have its punch list resolved.",
        )

    calc.install_completion_cascade(job)
    return ok(job)


@bp.post("/install-jobs/<job_id>/abort")
@require("OrderPlanner", "ServicePartnerTech")
def abort_install_job(job_id):
    job = get_install_job(job_id)
    check_partner_scope(job["service_partner_id"])
    body = get_body()
    field_str(body, "abort_reason", min_len=1)

    if job["status"] not in ("SCHEDULED", "ON_SITE"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SCHEDULED or ON_SITE job may be aborted.",
        )

    was_on_site = job["status"] == "ON_SITE"
    with mutate(job):
        job["status"] = "ABORTED"
    if was_on_site:
        order = store.orders[job["order_id"]]
        if order["fulfillment_status"] == "INSTALLING":
            with mutate(order):
                order["fulfillment_status"] = "STAGED"
    calc.recompute_partner(store.service_partners[job["service_partner_id"]])
    return ok(job)
