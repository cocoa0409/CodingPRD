"""Family navigation tasks, interpreter support and the support budget."""
from flask import Blueprint, request

import calc
import db
import resolve
import response
import serialize
import services
import validate
from db import store
from errors import ApiError
from middleware import (AUDIOLOGIST, EI_COORDINATOR, FACILITY_ADMIN,
                        FACILITY_SCREENER, NAVIGATOR, PROGRAM_ADMIN,
                        PROGRAM_AUDITOR, endpoint, identity)

bp = Blueprint("navigation", __name__)

READ_ROLES = [PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN, FACILITY_SCREENER,
              AUDIOLOGIST, NAVIGATOR, EI_COORDINATOR]


def _check_navigator(provider):
    """Priorities 20 and 21 for an explicitly named navigator."""
    if provider["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if provider["provider_type"] != "NAVIGATOR":
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH")


def _check_capacity(provider):
    """Priority 42: an explicitly named navigator must be below its ceiling."""
    if calc.provider_open_task_count(provider["id"]) >= provider["max_open_tasks"]:
        raise ApiError("ERR_NAVIGATOR_AT_CAPACITY")


@bp.post("/navigation-tasks")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, NAVIGATOR])
def create_task():
    body = validate.body()
    infant_id = validate.id_field(body, "infant_id")
    task_type = validate.enum_field(body, "task_type", validate.TASK_TYPES)
    episode_id = validate.id_field(body, "episode_id", required=False)
    visit_starts_at = validate.datetime_field(body, "visit_starts_at", required=False)
    visit_ends_at = validate.datetime_field(body, "visit_ends_at", required=False)
    assigned_provider_id = validate.id_field(body, "assigned_provider_id",
                                             required=False)
    auto_assign = validate.bool_field(body, "auto_assign", required=False,
                                      default=False)
    # The visit window is present if and only if the task is a home visit.
    if task_type == "HOME_VISIT":
        if visit_starts_at is None or visit_ends_at is None:
            validate.bad("A HOME_VISIT task requires visit_starts_at and visit_ends_at.")
    elif visit_starts_at is not None or visit_ends_at is not None:
        validate.bad("visit_starts_at/visit_ends_at are only valid on a HOME_VISIT.")

    linked = resolve.fks({
        "infant_id": infant_id,
        "episode_id": episode_id,
        "assigned_provider_id": assigned_provider_id,
    })
    infant = linked["infant_id"]
    episode = linked.get("episode_id")
    provider = linked.get("assigned_provider_id")
    identity(facility_id=infant["birth_facility_id"])

    if provider is not None:
        _check_navigator(provider)
    if task_type == "HOME_VISIT" and visit_ends_at <= visit_starts_at:
        raise ApiError("ERR_INVALID_WINDOW")
    if provider is not None and task_type == "HOME_VISIT":
        if services.travel_buffer_conflict(provider["id"], visit_starts_at,
                                           visit_ends_at):
            raise ApiError("ERR_NAVIGATOR_TRAVEL_BUFFER")
    units = services.reserve_units_or_reject(infant, task_type)

    chosen = provider
    if provider is not None:
        _check_capacity(provider)
    elif auto_assign:
        pool = calc.navigator_candidates(infant)
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_NAVIGATOR")
        chosen = pool[0]
        if task_type == "HOME_VISIT" and services.travel_buffer_conflict(
                chosen["id"], visit_starts_at, visit_ends_at):
            raise ApiError("ERR_NAVIGATOR_TRAVEL_BUFFER")

    task = services._new_task_row(infant, task_type,
                                  episode["id"] if episode else None,
                                  visit_starts_at, visit_ends_at, units, False)
    if chosen is not None:
        services.assign_task(task, chosen)
    services.recompute_risk(infant)
    return response.single(task, serialize.task, 201)


@bp.post("/navigation-tasks/<task_id>/assign")
@endpoint([PROGRAM_ADMIN, NAVIGATOR])
def assign(task_id):
    body = validate.body()
    assigned_provider_id = validate.id_field(body, "assigned_provider_id",
                                             required=False)
    task = resolve.one("task", task_id)
    linked = resolve.fks({"assigned_provider_id": assigned_provider_id})
    provider = linked.get("assigned_provider_id")
    infant = store.infants.get(task["infant_id"])
    identity(facility_id=task["funding_facility_id"])

    if task["status"] != "UNASSIGNED":
        raise ApiError("ERR_TASK_INVALID_STATE")
    if provider is not None:
        _check_navigator(provider)
        if task["task_type"] == "HOME_VISIT" and services.travel_buffer_conflict(
                provider["id"], task["visit_starts_at"], task["visit_ends_at"],
                ignore_task_id=task["id"]):
            raise ApiError("ERR_NAVIGATOR_TRAVEL_BUFFER")
        _check_capacity(provider)
        chosen = provider
    else:
        pool = calc.navigator_candidates(infant)
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_NAVIGATOR")
        chosen = pool[0]
        if task["task_type"] == "HOME_VISIT" and services.travel_buffer_conflict(
                chosen["id"], task["visit_starts_at"], task["visit_ends_at"],
                ignore_task_id=task["id"]):
            raise ApiError("ERR_NAVIGATOR_TRAVEL_BUFFER")

    services.assign_task(task, chosen)
    if infant is not None:
        services.recompute_risk(infant)
    return response.single(task, serialize.task)


@bp.post("/navigation-tasks/<task_id>/close")
@endpoint([PROGRAM_ADMIN, NAVIGATOR])
def close_task(task_id):
    body = validate.body()
    disposition = validate.enum_field(body, "disposition",
                                      validate.TASK_DISPOSITIONS)
    outcome = validate.enum_field(body, "outcome", validate.TASK_OUTCOMES,
                                  required=(disposition == "COMPLETED"))
    contacted_language = validate.enum_field(
        body, "contacted_language", validate.LANGUAGES,
        required=(outcome in validate.LANGUAGE_OUTCOMES))
    reason = validate.string_field(body, "reason", required=False)
    task = resolve.one("task", task_id)
    infant = store.infants.get(task["infant_id"])
    identity(facility_id=task["funding_facility_id"])

    if task["status"] not in ("UNASSIGNED", "OPEN"):
        raise ApiError("ERR_TASK_INVALID_STATE")

    if disposition == "COMPLETED":
        task["status"] = "COMPLETED"
        task["outcome"] = outcome
        task["contacted_language"] = contacted_language
        if reason is not None:
            task["closure_note"] = reason
    else:
        # A cancelled task credits its reserved units back (derived on read).
        task["status"] = "CANCELLED"
        task["closure_note"] = reason
    db.touch(task)

    if disposition == "COMPLETED" and outcome == "FAMILY_REENGAGED":
        if infant is not None:
            services.reengagement_cascade(infant)
    elif infant is not None:
        services.recompute_risk(infant)
    return response.single(task, serialize.task)


@bp.get("/navigation-tasks/<task_id>")
@endpoint([PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN, AUDIOLOGIST, NAVIGATOR,
           EI_COORDINATOR])
def get_task(task_id):
    row = resolve.one("task", task_id)
    identity()
    return response.single(row, serialize.task)


@bp.get("/navigation-tasks")
@endpoint(READ_ROLES)
def list_tasks():
    limit, offset = response.pagination()
    identity()
    rows = list(store.tasks.values())
    for field in ("infant_id", "episode_id", "funding_facility_id",
                  "assigned_provider_id", "status", "task_type"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.task, limit, offset)
