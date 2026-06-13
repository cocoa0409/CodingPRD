"""CleaningJob endpoints (PRD §3.2, §3.3) — CRUD, rooms, add-ons, lifecycle.

Ownership: a CleaningJob is owned by the customer in its customer_id; rooms and
add-ons are owned transitively through their parent job (PRD §2.1). A
Customer-role mutation on a job/room/add-on they do not own ->
ERR_NOT_RESOURCE_OWNER (priority 5).
"""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_CUSTOMER_SUSPENDED,
    ERR_DUPLICATE_ADDON,
    ERR_INVALID_REQUEST,
    ERR_JOB_ALREADY_BILLED,
    ERR_JOB_NOT_BOOKED,
    ERR_JOB_NOT_DRAFT,
    ERR_JOB_NOT_IN_PROGRESS,
    ERR_JOB_NOT_QUOTED,
    ERR_NO_ROOMS,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SLOT_NOT_RESERVED,
)
from middleware import is_customer, require
from response import ok_array, ok_object
from services.calculations import (
    compute_addon_line_price,
    compute_quoted_price,
)
from services.common import (
    by_created_asc,
    get_json_body,
    init_common,
    optional_bool,
    optional_str,
    paginate,
    parse_pagination,
    public,
    public_list,
    require_enum,
    require_int,
    require_str,
    touch,
)
from services.computed import (
    addons_of_job,
    recompute_total_sqft,
    rooms_of_job,
)
from services.lookups import (
    get_catalog,
    get_crew,
    get_customer,
    get_job,
    get_plan,
)
from services.scheduling import book_onto_crew

bp = Blueprint("jobs", __name__)

SOILING_LEVELS = {"LIGHT", "MODERATE", "HEAVY"}
ADDON_TYPES = {"STAIN", "PET", "PROTECTANT"}

JOB_FK_FILTERS = [
    "customer_id", "service_catalog_id", "recurring_plan_id",
    "origin_job_id", "scheduled_slot_id", "invoice_id",
]


# ---------------------------------------------------------------------------
# Ownership helper
# ---------------------------------------------------------------------------
def _check_job_owner(job):
    """Customer-role ownership gate (priority 5). Operator roles bypass."""
    if is_customer() and job["customer_id"] != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Customer does not own this job")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs")
def create_job():
    require(["Customer", "ServiceManager"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    service_catalog_id = require_str(body, "service_catalog_id")
    recurring_plan_id = optional_str(body, "recurring_plan_id")
    move_furniture = optional_bool(body, "move_furniture", default=False)

    # existence (priority 3, left-to-right): customer, catalog, then optional plan
    get_customer(customer_id)
    get_catalog(service_catalog_id)
    if recurring_plan_id is not None:
        get_plan(recurring_plan_id)

    # ownership (priority 5): a Customer may only create a job for themselves
    if is_customer() and customer_id != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Customer does not own this job")

    record = init_common({
        "customer_id": customer_id,
        "service_catalog_id": service_catalog_id,
        "recurring_plan_id": recurring_plan_id,
        "origin_job_id": None,
        "move_furniture": move_furniture,
        "total_sqft": 0,
        "quoted_price_cents": None,
        "settled_price_cents": None,
        "lifecycle_status": "DRAFT",
        "billing_status": "UNBILLED",
        "completed_at_minute": None,
        "scheduled_slot_id": None,
        "invoice_id": None,
    })
    db.cleaning_jobs[record["id"]] = record
    return ok_object(public(record), 201)


@bp.get("/cleaning-jobs/<jid>")
def get_job_ep(jid):
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    j = get_job(jid)
    return ok_object(public(j), 200)


@bp.get("/cleaning-jobs")
def list_jobs():
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    limit, offset = parse_pagination()
    rows = list(db.cleaning_jobs.values())
    for fk in JOB_FK_FILTERS:
        val = request.args.get(fk)
        if val is not None:
            rows = [j for j in rows if j.get(fk) == val]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        rows = [j for j in rows if j["lifecycle_status"] == lifecycle]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/rooms")
def add_room(jid):
    require(["Customer", "ServiceManager"])
    job = get_job(jid)
    body = get_json_body()
    area_label = require_str(body, "area_label")
    area_sqft = require_int(body, "area_sqft", minimum=1)
    soiling_level = require_enum(body, "soiling_level", SOILING_LEVELS)

    _check_job_owner(job)

    # rooms may only be added while DRAFT (priority 6) -> ERR_JOB_NOT_DRAFT
    if job["lifecycle_status"] != "DRAFT":
        raise APIError(ERR_JOB_NOT_DRAFT, 409, "Rooms may only be added to a DRAFT job")

    room = init_common({
        "cleaning_job_id": job["id"],
        "area_label": area_label,
        "area_sqft": area_sqft,
        "soiling_level": soiling_level,
    })
    db.room_assessments[room["id"]] = room
    # recompute job.total_sqft (only while DRAFT) — mutates the job
    recompute_total_sqft(job)
    return ok_object(public(room), 201)


@bp.get("/cleaning-jobs/<jid>/rooms")
def list_rooms(jid):
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    get_job(jid)
    limit, offset = parse_pagination()
    rows = by_created_asc(rooms_of_job(jid))
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/add-ons")
def add_addon(jid):
    require(["Customer", "ServiceManager"])
    job = get_job(jid)
    body = get_json_body()
    addon_type = require_enum(body, "addon_type", ADDON_TYPES)

    _check_job_owner(job)

    # add-ons only while DRAFT (priority 6) -> ERR_JOB_NOT_DRAFT
    if job["lifecycle_status"] != "DRAFT":
        raise APIError(ERR_JOB_NOT_DRAFT, 409, "Add-ons may only be added to a DRAFT job")

    # at most one add-on per type per job (priority 12) -> ERR_DUPLICATE_ADDON
    for a in addons_of_job(jid):
        if a["addon_type"] == addon_type:
            raise APIError(ERR_DUPLICATE_ADDON, 409, "An add-on of this type already exists")

    catalog = db.service_catalogs[job["service_catalog_id"]]
    line_price = compute_addon_line_price(addon_type, catalog, job["total_sqft"])

    addon = init_common({
        "cleaning_job_id": job["id"],
        "addon_type": addon_type,
        "line_price_cents": line_price,
    })
    db.add_ons[addon["id"]] = addon
    # Adding an add-on is a mutation of the parent job (it changes the priced set).
    touch(job)
    return ok_object(public(addon), 201)


@bp.get("/cleaning-jobs/<jid>/add-ons")
def list_addons(jid):
    require(["Customer", "ServiceManager", "Dispatcher", "Billing"])
    get_job(jid)
    limit, offset = parse_pagination()
    rows = by_created_asc(addons_of_job(jid))
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Lifecycle: quote
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/quote")
def quote_job(jid):
    require(["Customer", "ServiceManager"])
    job = get_job(jid)

    _check_job_owner(job)

    # state gate (priority 6): must be DRAFT
    if job["lifecycle_status"] != "DRAFT":
        raise APIError(ERR_JOB_NOT_DRAFT, 409, "Only a DRAFT job can be quoted")

    rooms = rooms_of_job(jid)
    # at least one room (priority 7) -> ERR_NO_ROOMS
    if len(rooms) == 0:
        raise APIError(ERR_NO_ROOMS, 409, "Cannot quote a job with zero rooms")

    # owning customer must be ACTIVE -> ERR_CUSTOMER_SUSPENDED
    customer = db.customers[job["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise APIError(ERR_CUSTOMER_SUSPENDED, 409, "Customer is suspended")

    catalog = db.service_catalogs[job["service_catalog_id"]]
    plan = db.recurring_plans.get(job["recurring_plan_id"]) if job["recurring_plan_id"] else None
    addons = addons_of_job(jid)

    # freeze total_sqft (already maintained while DRAFT) and quoted_price_cents
    job["total_sqft"] = sum(r["area_sqft"] for r in rooms)
    job["quoted_price_cents"] = compute_quoted_price(catalog, job, rooms, addons, plan)
    job["lifecycle_status"] = "QUOTED"
    touch(job)
    return ok_object(public(job), 200)


# ---------------------------------------------------------------------------
# Lifecycle: book
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/book")
def book_job(jid):
    require(["Dispatcher", "ServiceManager"])
    job = get_job(jid)
    body = get_json_body()
    # crew_id must be present/well-formed to resolve crew existence (priority 3)
    crew_id = require_str(body, "crew_id")
    crew = get_crew(crew_id)
    # remaining body well-formedness (priority 4)
    start_minute = require_int(body, "start_minute", minimum=0)
    end_minute = require_int(body, "end_minute")
    expected_crew_version = require_int(body, "expected_crew_version")
    if end_minute <= start_minute:
        raise APIError(ERR_INVALID_REQUEST, 422, "end_minute must be > start_minute")

    # state gate (priority 6): must be QUOTED
    if job["lifecycle_status"] != "QUOTED":
        raise APIError(ERR_JOB_NOT_QUOTED, 409, "Only a QUOTED job can be booked")

    book_onto_crew(job, crew, start_minute, end_minute, expected_crew_version)
    job["lifecycle_status"] = "BOOKED"
    touch(job)
    return ok_object(public(job), 200)


# ---------------------------------------------------------------------------
# Lifecycle: reschedule
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/reschedule")
def reschedule_job(jid):
    require(["Dispatcher", "ServiceManager"])
    job = get_job(jid)
    body = get_json_body()
    crew_id = require_str(body, "crew_id")
    crew = get_crew(crew_id)
    start_minute = require_int(body, "start_minute", minimum=0)
    end_minute = require_int(body, "end_minute")
    expected_crew_version = require_int(body, "expected_crew_version")
    if end_minute <= start_minute:
        raise APIError(ERR_INVALID_REQUEST, 422, "end_minute must be > start_minute")

    # state gate (priority 6): reschedule applies to a BOOKED job
    if job["lifecycle_status"] != "BOOKED":
        raise APIError(ERR_JOB_NOT_BOOKED, 409, "Only a BOOKED job can be rescheduled")

    # Validate the new booking BEFORE releasing the old slot (atomicity): if a
    # check fails, the existing slot must remain intact. We do this by snapshot:
    # the overlap check ignores the job's own current slot only if it is on the
    # same crew — but per PRD the new slot is created fresh and the old released
    # as hop 1. To keep the old-slot-untouched-on-failure guarantee, we run all
    # four checks first via book_onto_crew AFTER releasing only on success.
    #
    # book_onto_crew performs checks then creates the slot and repoints. To
    # avoid the old reserved slot counting as an overlap against itself, release
    # it first ONLY after checks pass. We therefore replicate: release old slot,
    # attempt booking; if booking raises, the operation is rejected and (since
    # checks happen before any slot is created) we must restore the old slot.
    old_slot_id = job.get("scheduled_slot_id")
    old_slot = db.scheduled_slots.get(old_slot_id) if old_slot_id else None

    # Temporarily mark the old slot RELEASED so it does not self-overlap, but
    # remember enough to roll back if a precondition fails.
    prev_status = old_slot["status"] if old_slot else None
    if old_slot is not None:
        old_slot["status"] = "RELEASED"
    try:
        book_onto_crew(job, crew, start_minute, end_minute, expected_crew_version)
    except Exception:
        # roll back the old slot's status; no new slot/version was committed
        if old_slot is not None:
            old_slot["status"] = prev_status
        raise

    # commit: the old slot stays RELEASED (hop 1) with its own mutation stamp,
    # the new slot is RESERVED (hop 2), scheduled_slot_id repointed, new crew
    # version bumped (done inside book_onto_crew).
    if old_slot is not None:
        touch(old_slot)
    touch(job)
    return ok_object(public(job), 200)


# ---------------------------------------------------------------------------
# Lifecycle: start
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/start")
def start_job(jid):
    require(["Dispatcher", "ServiceManager"])
    job = get_job(jid)

    # state gate (priority 6): must be BOOKED
    if job["lifecycle_status"] != "BOOKED":
        raise APIError(ERR_JOB_NOT_BOOKED, 409, "Only a BOOKED job can be started")

    # scheduled slot must still be RESERVED -> ERR_SLOT_NOT_RESERVED
    slot = db.scheduled_slots.get(job.get("scheduled_slot_id"))
    if slot is None or slot["status"] != "RESERVED":
        raise APIError(ERR_SLOT_NOT_RESERVED, 409, "Scheduled slot is not RESERVED")

    job["lifecycle_status"] = "IN_PROGRESS"
    touch(job)
    return ok_object(public(job), 200)


# ---------------------------------------------------------------------------
# Lifecycle: complete
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/complete")
def complete_job(jid):
    require(["Dispatcher", "ServiceManager"])
    job = get_job(jid)
    body = get_json_body()
    completed_at_minute = require_int(body, "completed_at_minute", minimum=0)

    # state gate (priority 6): must be IN_PROGRESS
    if job["lifecycle_status"] != "IN_PROGRESS":
        raise APIError(ERR_JOB_NOT_IN_PROGRESS, 409, "Only an IN_PROGRESS job can be completed")

    job["completed_at_minute"] = completed_at_minute
    job["lifecycle_status"] = "COMPLETED"

    # release the job's slot (RESERVED -> RELEASED)
    slot = db.scheduled_slots.get(job.get("scheduled_slot_id"))
    if slot is not None and slot["status"] == "RESERVED":
        slot["status"] = "RELEASED"
        touch(slot)

    # bubble-up: active plan completed_visit_count += 1
    plan_id = job.get("recurring_plan_id")
    if plan_id:
        plan = db.recurring_plans.get(plan_id)
        if plan is not None and plan["status"] == "ACTIVE":
            plan["completed_visit_count"] = plan.get("completed_visit_count", 0) + 1
            touch(plan)

    touch(job)
    return ok_object(public(job), 200)


# ---------------------------------------------------------------------------
# Lifecycle: cancel
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/cancel")
def cancel_job(jid):
    require(["Customer", "ServiceManager"])
    job = get_job(jid)

    _check_job_owner(job)

    # Cancellation is permitted from DRAFT, QUOTED, or BOOKED (PRD §3.3). The
    # billing-eligibility guard requires billing_status == UNBILLED; a job whose
    # billing has started is rejected with ERR_JOB_ALREADY_BILLED. Because a job
    # only reaches INVOICED/PAID after COMPLETED, the billing guard is the
    # operative rejection for already-billed jobs; an IN_PROGRESS or already
    # CANCELLED/COMPLETED-unbilled job is not a state from which CANCELLED is
    # defined and is a 409 state conflict.
    if job["lifecycle_status"] not in ("DRAFT", "QUOTED", "BOOKED"):
        # billing already started (COMPLETED job that got invoiced) -> already-billed
        if job["billing_status"] != "UNBILLED":
            raise APIError(ERR_JOB_ALREADY_BILLED, 409, "Job billing has already started")
        raise APIError(ERR_JOB_ALREADY_BILLED, 409, "Job cannot be cancelled from its current state")

    # billing must still be UNBILLED -> ERR_JOB_ALREADY_BILLED
    if job["billing_status"] != "UNBILLED":
        raise APIError(ERR_JOB_ALREADY_BILLED, 409, "Job billing has already started")

    # release any RESERVED slot (cancel cascade hop 1) and clear scheduled_slot_id
    slot = db.scheduled_slots.get(job.get("scheduled_slot_id"))
    if slot is not None and slot["status"] == "RESERVED":
        slot["status"] = "RELEASED"
        touch(slot)
    if job.get("scheduled_slot_id") is not None:
        job["scheduled_slot_id"] = None

    job["lifecycle_status"] = "CANCELLED"
    touch(job)
    return ok_object(public(job), 200)
