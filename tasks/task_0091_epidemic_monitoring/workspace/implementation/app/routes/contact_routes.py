"""ContactEvent endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import ENTITY_BACKED_ROLES, EVENT_TYPES, INGEST_SOURCES
from ..errors import ApiError
from ..services.calculations import classify_tier
from ..store import common_fields_append_only, get_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/contact-events",
        view_func=require_auth("CDCTracer", "HospitalReporter")(with_lock(create_contact_event)),
        methods=["POST"],
    )


def create_contact_event():
    body = get_json_body()
    store = get_store()
    user_id, role = current_actor()

    src = body.get("source_person_id")
    tgt = body.get("target_person_id")
    et = body.get("event_type")
    event_time = body.get("event_time")
    duration = body.get("duration_minutes")
    distance = body.get("distance_meters")
    ingested_from = body.get("ingested_from")

    required = [src, tgt, et, event_time, duration, distance, ingested_from]
    if any(v is None for v in required):
        raise ApiError("ERR_INVALID_INPUT", "Missing required ContactEvent fields.")
    if et not in EVENT_TYPES:
        raise ApiError("ERR_INVALID_INPUT", f"event_type must be one of {sorted(EVENT_TYPES)}.")
    if ingested_from not in INGEST_SOURCES:
        raise ApiError(
            "ERR_INVALID_INPUT", f"ingested_from must be one of {sorted(INGEST_SOURCES)}."
        )

    # FK existence
    if src not in store.persons:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"source_person_id {src} not found.")
    if tgt not in store.persons:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"target_person_id {tgt} not found.")

    # Acting institution must be ACTIVE if entity-backed
    if role in ENTITY_BACKED_ROLES:
        inst = store.institutions.get(user_id)
        if not inst:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Acting institution not found.")
        if inst.get("status") != "ACTIVE":
            raise ApiError("ERR_INSTITUTION_INACTIVE", "Acting institution is not ACTIVE.")

    # Self contact
    if src == tgt:
        raise ApiError("ERR_SELF_CONTACT", "source_person_id and target_person_id must differ.")

    try:
        ev_dt = parse_iso(event_time)
    except Exception as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid event_time: {exc}")
    if ev_dt > now_dt():
        raise ApiError("ERR_EVENT_TIME_INVALID", "event_time cannot be in the future.")

    try:
        dur_int = int(duration)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "duration_minutes must be integer.")
    if dur_int < 0:
        raise ApiError("ERR_INVALID_INPUT", "duration_minutes must be >= 0.")
    try:
        dist_f = float(distance)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "distance_meters must be a number.")
    if dist_f < 0:
        raise ApiError("ERR_INVALID_INPUT", "distance_meters must be >= 0.")

    raw_event = {
        "event_type": et,
        "duration_minutes": dur_int,
        "distance_meters": dist_f,
    }
    tier = classify_tier(raw_event)

    base = common_fields_append_only()
    row = {
        **base,
        "source_person_id": src,
        "target_person_id": tgt,
        "event_type": et,
        "event_time": event_time,
        "duration_minutes": dur_int,
        "distance_meters": dist_f,
        "tier": tier,
        "ingested_from": ingested_from,
    }
    store.contact_events[row["id"]] = row

    # If a tracing task is in IN_PROGRESS for the source person's case, attribute this event
    for task in store.tracing_tasks.values():
        if task.get("status") != "IN_PROGRESS":
            continue
        case = store.cases.get(task.get("case_id"))
        if not case:
            continue
        if case.get("person_id") == src:
            store.task_to_events.setdefault(task["id"], []).append(row["id"])
            task["discovered_contact_count"] = int(task.get("discovered_contact_count", 0)) + 1
            # bump version (TracingTask has common fields)
            from ..store import bump_version as _bv
            _bv(task)
            break

    return ok(row, status=201)
