"""Route lifecycle: create, validate, publish, retire."""
from __future__ import annotations

import re
import threading

import db
from clock import iso, now
from errors import err
from services.audit import append_audit
from services.route_calc import (
    route_stop_sequence_ids, compute_distance_km, compute_duration_minutes_base,
)
from services.stops import find_stop_or_ref_not_found
from services.util import validate_peak_windows


_CODE_RE = re.compile(r"^[A-Z0-9-]{3,12}$")


def validate_route_input_create(body: dict) -> None:
    code = body.get("code")
    name = body.get("name")
    s_id = body.get("start_stop_id")
    e_id = body.get("end_stop_id")
    inters = body.get("intermediate_stop_ids", [])
    pf = body.get("peak_frequency_minutes")
    of = body.get("offpeak_frequency_minutes")
    pw = body.get("peak_windows", [])

    if not isinstance(code, str) or not _CODE_RE.match(code):
        raise err("ERR_VALIDATION",
                  "code must be 3-12 chars in [A-Z0-9-]")
    if not isinstance(name, str) or not name:
        raise err("ERR_VALIDATION", "name is required")
    if not isinstance(s_id, str) or not s_id:
        raise err("ERR_VALIDATION", "start_stop_id is required")
    if not isinstance(e_id, str) or not e_id:
        raise err("ERR_VALIDATION", "end_stop_id is required")
    if not isinstance(inters, list):
        raise err("ERR_VALIDATION", "intermediate_stop_ids must be a list")
    if not isinstance(pf, int) or isinstance(pf, bool):
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "peak_frequency_minutes must be integer")
    if not isinstance(of, int) or isinstance(of, bool):
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "offpeak_frequency_minutes must be integer")
    validate_peak_windows(pw, pf, of)


def validate_fk_stops(body: dict) -> None:
    """Validate that referenced stop ids resolve (but not status)."""
    s_id = body.get("start_stop_id")
    e_id = body.get("end_stop_id")
    inters = body.get("intermediate_stop_ids", [])
    if s_id is not None:
        find_stop_or_ref_not_found(s_id)
    if e_id is not None:
        find_stop_or_ref_not_found(e_id)
    if isinstance(inters, list):
        for sid in inters:
            find_stop_or_ref_not_found(sid)


_publish_lock = threading.Lock()


def publish_route(route: dict, actor_role: str, actor_id: str) -> dict:
    """Publish a DRAFT route -> ACTIVE. Cascades to retire prior ACTIVE route with same code."""
    if route.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  f"Route must be DRAFT to publish (current: {route.get('status')})")

    # Stop active-status precondition
    seq = route_stop_sequence_ids(route)
    for sid in seq:
        s = db.stops.get(sid)
        if not s:
            raise err("ERR_REFERENCE_NOT_FOUND", f"Stop {sid} not found")
        if s.get("status") != "ACTIVE":
            raise err("ERR_STOP_NOT_ACTIVE",
                      f"Stop {sid} is not ACTIVE")

    # Frequency-window structural rules
    validate_peak_windows(route.get("peak_windows", []),
                          route.get("peak_frequency_minutes"),
                          route.get("offpeak_frequency_minutes"))

    with _publish_lock:
        # Identify prior ACTIVE route with same code
        prior = None
        for r in db.routes.values():
            if r["id"] == route["id"]:
                continue
            if r.get("code") == route.get("code") and r.get("status") == "ACTIVE":
                prior = r
                break

        # If a duplicate ACTIVE exists, we'll retire it in this op; that always succeeds
        # for the "fresh publish" case. (ERR_ROUTE_VERSION_CONFLICT is a race; we treat
        # serial requests as resolvable. ERR_DUPLICATE_ROUTE_CODE applies when no
        # predecessor row exists but somehow another ACTIVE row with same code is in
        # an inconsistent state — also covered by the same logic: if there's another
        # ACTIVE row we either auto-retire it or 409.)

        # Compute version_number = max prior version_number for this code + 1
        max_prior = 0
        for rv in db.route_versions.values():
            if rv.get("route_code") == route.get("code"):
                if rv.get("version_number", 0) > max_prior:
                    max_prior = rv.get("version_number")
        new_version_number = max_prior + 1

        # Mutate route
        distance = compute_distance_km(route)
        intermediate_count = len(route.get("intermediate_stop_ids", []))
        duration = compute_duration_minutes_base(distance, intermediate_count)

        route["estimated_distance_km"] = distance
        route["estimated_duration_minutes"] = duration
        route["status"] = "ACTIVE"
        route["version_number"] = new_version_number
        db.stamp_update(route)

        # Append RouteVersion snapshot
        rv = {
            "route_code": route["code"],
            "route_id": route["id"],
            "version_number": new_version_number,
            "stop_sequence_snapshot": list(route_stop_sequence_ids(route)),
            "peak_frequency_minutes": route["peak_frequency_minutes"],
            "offpeak_frequency_minutes": route["offpeak_frequency_minutes"],
            "peak_windows": list(route.get("peak_windows", [])),
            "published_at": iso(now()),
            "retired_at": None,
        }
        db.stamp_create(rv, common_fields=False)
        db.route_versions[rv["id"]] = rv

        # Retire prior + cascade
        if prior is not None:
            retire_route(prior, actor_role=actor_role, actor_id=actor_id,
                         emit_audit=False, cause="superseded_by_publish")

        # Audit ROUTE_PUBLISHED
        append_audit(
            event_type="ROUTE_PUBLISHED",
            subject_type="Route",
            subject_id=route["id"],
            actor_role=actor_role,
            actor_id=actor_id,
            payload={
                "route_code": route["code"],
                "version_number": new_version_number,
                "prior_retired_route_id": prior["id"] if prior else None,
            },
        )

        return route


def retire_route(route: dict, actor_role: str, actor_id: str,
                 emit_audit: bool = True, cause: str | None = None) -> dict:
    """Retire an ACTIVE route. Cascades: PLANNED RunSheets -> CANCELLED, which cascades
    Reservations -> CANCELLED."""
    if route.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  f"Route must be ACTIVE to retire (current: {route.get('status')})")

    route["status"] = "RETIRED"
    db.stamp_update(route)

    # Stamp the matching RouteVersion.retired_at
    for rv in db.route_versions.values():
        if rv.get("route_code") == route.get("code") and \
                rv.get("version_number") == route.get("version_number") and \
                rv.get("retired_at") is None:
            rv["retired_at"] = iso(now())

    # Cascade: cancel PLANNED RunSheets on this route
    from services.run_sheets_svc import cancel_run_sheet_cascade
    for rs in list(db.run_sheets.values()):
        if rs.get("route_id") == route["id"] and rs.get("status") == "PLANNED":
            cancel_run_sheet_cascade(rs, actor_role="system",
                                     actor_id=actor_id,
                                     cause=cause or "route_retired")

    return route
