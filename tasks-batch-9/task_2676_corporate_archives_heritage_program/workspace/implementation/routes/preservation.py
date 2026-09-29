"""Preservation plans, migration jobs, the cost waterfall and zone capacity."""

from flask import Blueprint, g

from core import clock, register, sorted_rows, store, touch
from errors import ApiError
from middleware import endpoint
from response import apply_filters, collection_response, object_response
from services import calc
from services.lookup import fetch
from validation import TARGET_FORMATS, body, venum, vid, vinstant, vint, vstr

bp = Blueprint("preservation", __name__)

PLAN_READERS = ("ArchivesDirector", "PreservationOfficer")
OPEN_JOB_STATUSES = ("PENDING_APPROVAL", "APPROVED", "IN_PROGRESS")


# --- preservation plans ----------------------------------------------------


@bp.post("/preservation-plans")
@endpoint(("PreservationOfficer",))
def create_preservation_plan():
    payload = body()
    storage_zone_id = vid(payload, "storage_zone_id")
    plan_name = vstr(payload, "plan_name", 1, 120)
    budget_cents = vint(payload, "budget_cents", 0, None)
    zone = fetch("storage_zones", storage_zone_id)
    row = register(
        store.preservation_plans,
        {
            "storage_zone_id": zone["id"],
            "plan_name": plan_name,
            "budget_cents": budget_cents,
            "status": "DRAFT",
            "budget_committed_cents": 0,
            "budget_spent_cents": 0,
            "at_risk_unit_count": 0,
            "satisfied_at": None,
        },
    )
    return object_response(row, 201)


@bp.get("/preservation-plans")
@endpoint(PLAN_READERS)
def list_preservation_plans():
    rows = apply_filters(
        sorted_rows(store.preservation_plans),
        {"storage_zone_id": "storage_zone_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/preservation-plans/<resource_id>")
@endpoint(PLAN_READERS)
def get_preservation_plan(resource_id):
    return object_response(fetch("preservation_plans", resource_id))


@bp.post("/preservation-plans/<resource_id>/activate")
@endpoint(("PreservationOfficer",))
def activate_preservation_plan(resource_id):
    plan = fetch("preservation_plans", resource_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if plan["budget_cents"] < 1:
        raise ApiError(
            "ERR_PLAN_STATE_INVALID", "A zero-budget preservation plan cannot be activated."
        )
    census = calc.at_risk_unit_count(plan["storage_zone_id"])
    plan["at_risk_unit_count"] = census
    if census == 0:
        plan["status"] = "SATISFIED"
        plan["satisfied_at"] = clock.now()
    else:
        plan["status"] = "ACTIVE"
    touch(plan)
    return object_response(plan)


@bp.post("/preservation-plans/<resource_id>/close")
@endpoint(("PreservationOfficer",))
def close_preservation_plan(resource_id):
    plan = fetch("preservation_plans", resource_id)
    if plan["status"] not in ("ACTIVE", "SATISFIED"):
        raise ApiError("ERR_PLAN_STATE_INVALID")
    for job in store.migration_jobs.values():
        if job["preservation_plan_id"] == plan["id"] and job["status"] in OPEN_JOB_STATUSES:
            raise ApiError(
                "ERR_PLAN_STATE_INVALID", "A migration job on this plan is still open."
            )
    plan["status"] = "CLOSED"
    touch(plan)
    return object_response(plan)


# --- migration jobs --------------------------------------------------------


@bp.post("/migration-jobs")
@endpoint(("PreservationOfficer",))
def create_migration_job():
    payload = body()
    preservation_plan_id = vid(payload, "preservation_plan_id")
    archival_item_id = vid(payload, "archival_item_id")
    target_format = venum(payload, "target_format", TARGET_FORMATS)
    units = vint(payload, "units", 1, None)
    window_start = vinstant(payload, "window_start")
    window_end = vinstant(payload, "window_end")
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'window_end' must be strictly later than 'window_start'."
        )
    plan = fetch("preservation_plans", preservation_plan_id)
    item = fetch("archival_items", archival_item_id)
    cost = calc.migration_job_cost(item, units)
    fields = {
        "preservation_plan_id": plan["id"],
        "archival_item_id": item["id"],
        "target_format": target_format,
        "units": units,
        "window_start": window_start,
        "window_end": window_end,
        "status": "PENDING_APPROVAL",
        "requested_by": g.user_id,
        "approved_by": None,
        "cancel_reason": None,
    }
    fields.update(cost)
    row = register(store.migration_jobs, fields)
    return object_response(row, 201)


@bp.get("/migration-jobs")
@endpoint(PLAN_READERS)
def list_migration_jobs():
    rows = apply_filters(
        sorted_rows(store.migration_jobs),
        {
            "preservation_plan_id": "preservation_plan_id",
            "archival_item_id": "archival_item_id",
            "status": "status",
        },
    )
    return collection_response(rows)


@bp.get("/migration-jobs/<resource_id>")
@endpoint(PLAN_READERS)
def get_migration_job(resource_id):
    return object_response(fetch("migration_jobs", resource_id))


@bp.post("/migration-jobs/<resource_id>/approve")
@endpoint(("PreservationOfficer",))
def approve_migration_job(resource_id):
    job = fetch("migration_jobs", resource_id)
    if job["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_JOB_STATE_INVALID")
    plan = store.preservation_plans[job["preservation_plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_STATE_INVALID", "The funding plan is not ACTIVE.")
    if g.user_id == job["requested_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    item = store.archival_items[job["archival_item_id"]]
    zone = store.storage_zones[item["storage_zone_id"]]
    peak = calc.zone_migration_peak(job, zone["id"])
    if peak > zone["max_overlapping_migration_jobs"]:
        raise ApiError("ERR_ZONE_MIGRATION_CAPACITY_EXCEEDED")
    if plan["budget_committed_cents"] + job["committed_cost_cents"] > plan["budget_cents"]:
        raise ApiError("ERR_PRESERVATION_BUDGET_EXCEEDED")
    job["approved_by"] = g.user_id
    job["status"] = "APPROVED"
    touch(job)
    plan["budget_committed_cents"] += job["committed_cost_cents"]
    touch(plan)
    return object_response(job)


@bp.post("/migration-jobs/<resource_id>/start")
@endpoint(("PreservationOfficer",))
def start_migration_job(resource_id):
    job = fetch("migration_jobs", resource_id)
    if job["status"] != "APPROVED":
        raise ApiError("ERR_JOB_STATE_INVALID")
    item = store.archival_items[job["archival_item_id"]]
    if item["status"] != "ACCESSIONED":
        raise ApiError("ERR_ITEM_STATE_INVALID")
    zone = store.storage_zones[item["storage_zone_id"]]
    if zone["environmental_status"] != "COMPLIANT":
        raise ApiError("ERR_ZONE_NOT_COMPLIANT")
    job["status"] = "IN_PROGRESS"
    touch(job)
    item["status"] = "IN_TREATMENT"
    touch(item)
    return object_response(job)


@bp.post("/migration-jobs/<resource_id>/complete")
@endpoint(("PreservationOfficer",))
def complete_migration_job(resource_id):
    job = fetch("migration_jobs", resource_id)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_JOB_STATE_INVALID")
    job["status"] = "COMPLETED"
    touch(job)
    # hop one: the treated item returns to the shelf with its surrogate.
    item = store.archival_items[job["archival_item_id"]]
    item["status"] = "ACCESSIONED"
    item["preservation_format"] = job["target_format"]
    item["digital_surrogate_available"] = True
    touch(item)
    # hop two: re-census the funding plan, which may retire it.
    plan = store.preservation_plans[job["preservation_plan_id"]]
    plan["budget_committed_cents"] -= job["committed_cost_cents"]
    plan["budget_spent_cents"] += job["committed_cost_cents"]
    plan["at_risk_unit_count"] = calc.at_risk_unit_count(plan["storage_zone_id"])
    if plan["at_risk_unit_count"] == 0 and plan["status"] == "ACTIVE":
        plan["status"] = "SATISFIED"
        plan["satisfied_at"] = clock.now()
    touch(plan)
    return object_response(job)


@bp.post("/migration-jobs/<resource_id>/cancel")
@endpoint(("PreservationOfficer",))
def cancel_migration_job(resource_id):
    payload = body()
    cancel_reason = vstr(payload, "cancel_reason", 1, None)
    job = fetch("migration_jobs", resource_id)
    origin = job["status"]
    if origin not in OPEN_JOB_STATUSES:
        raise ApiError("ERR_JOB_STATE_INVALID")
    job["cancel_reason"] = cancel_reason
    if origin == "PENDING_APPROVAL":
        job["status"] = "REJECTED"
        touch(job)
        return object_response(job)
    job["status"] = "CANCELLED"
    touch(job)
    plan = store.preservation_plans[job["preservation_plan_id"]]
    plan["budget_committed_cents"] -= job["committed_cost_cents"]
    touch(plan)
    if origin == "IN_PROGRESS":
        item = store.archival_items[job["archival_item_id"]]
        if item["status"] == "IN_TREATMENT":
            item["status"] = "ACCESSIONED"
            touch(item)
    return object_response(job)
