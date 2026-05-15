"""Person endpoints + exposure-score + contact-graph."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask, request

from ..auth import require_auth
from ..clock import now_dt, parse_iso
from ..constants import EXPOSURE_WINDOW_DAYS
from ..errors import ApiError
from ..services.calculations import compute_exposure_score
from ..store import common_fields_create, get_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/persons",
        view_func=require_auth("CDCSupervisor", "HospitalReporter")(with_lock(create_person)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/persons/<person_id>",
        view_func=require_auth(
            "CDCSupervisor", "CDCDispatcher", "CDCTracer", "HospitalReporter", "LabTechnician"
        )(with_lock(get_person)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/persons/<person_id>/exposure-score",
        view_func=require_auth("CDCSupervisor", "CDCTracer")(with_lock(get_exposure)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/persons/<person_id>/contact-graph",
        view_func=require_auth("CDCSupervisor", "CDCTracer")(with_lock(get_contact_graph)),
        methods=["GET"],
    )


def _validate_person_hash(h: str) -> None:
    if not isinstance(h, str) or len(h) != 16:
        raise ApiError("ERR_INVALID_INPUT", "person_hash must be 16 lowercase hex chars.")
    try:
        int(h, 16)
    except ValueError:
        raise ApiError("ERR_INVALID_INPUT", "person_hash must be hex.")
    if h.lower() != h:
        raise ApiError("ERR_INVALID_INPUT", "person_hash must be lowercase.")


def create_person():
    body = get_json_body()
    store = get_store()
    p_hash = body.get("person_hash")
    demographics = body.get("demographics")
    district = body.get("district_code")
    if not p_hash or demographics is None or not district:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    _validate_person_hash(p_hash)
    if not isinstance(demographics, dict):
        raise ApiError("ERR_INVALID_INPUT", "demographics must be an object.")
    for p in store.persons.values():
        if p.get("person_hash") == p_hash:
            raise ApiError("ERR_INVALID_INPUT", f"person_hash {p_hash!r} already exists.")
    row = {
        **common_fields_create(),
        "person_hash": p_hash,
        "demographics": demographics,
        "district_code": district,
        "isolation_status": "NONE",
        "latest_case_id": None,
    }
    store.persons[row["id"]] = row
    return ok(row, status=201)


def get_person(person_id: str):
    store = get_store()
    p = store.persons.get(person_id)
    if not p:
        raise ApiError("ERR_NOT_FOUND", f"Person {person_id} not found.")
    return ok(p)


def get_exposure(person_id: str):
    store = get_store()
    p = store.persons.get(person_id)
    if not p:
        raise ApiError("ERR_NOT_FOUND", f"Person {person_id} not found.")
    projection_raw = request.args.get("projection", "false")
    projection = str(projection_raw).lower() in ("1", "true", "yes")
    score = compute_exposure_score(person_id, projection=projection)
    return ok({
        "person_id": person_id,
        "contact_exposure_score": score,
        "projection": projection,
    })


def get_contact_graph(person_id: str):
    store = get_store()
    p = store.persons.get(person_id)
    if not p:
        raise ApiError("ERR_NOT_FOUND", f"Person {person_id} not found.")
    depth_raw = request.args.get("depth", "1")
    try:
        depth = int(depth_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", f"Invalid depth: {depth_raw!r}")
    if depth < 1:
        depth = 1

    now = now_dt()
    start_ts = now - timedelta(days=EXPOSURE_WINDOW_DAYS)

    # BFS from person_id outward
    visited = {person_id}
    frontier = {person_id}
    edges: list[dict] = []
    for _ in range(depth):
        next_frontier: set[str] = set()
        for ev in store.contact_events.values():
            try:
                et = parse_iso(ev.get("event_time"))
            except Exception:
                continue
            if not (start_ts < et <= now):
                continue
            s = ev.get("source_person_id")
            t = ev.get("target_person_id")
            if s in frontier and t not in visited:
                next_frontier.add(t)
                edges.append({"event_id": ev["id"], "source_person_id": s, "target_person_id": t,
                              "tier": ev.get("tier")})
            elif t in frontier and s not in visited:
                next_frontier.add(s)
                edges.append({"event_id": ev["id"], "source_person_id": s, "target_person_id": t,
                              "tier": ev.get("tier")})
            elif s in frontier and t in frontier:
                # internal edge already in graph; add once
                edges.append({"event_id": ev["id"], "source_person_id": s, "target_person_id": t,
                              "tier": ev.get("tier")})
        visited |= next_frontier
        frontier = next_frontier
        if not frontier:
            break

    nodes = [{"person_id": pid} for pid in sorted(visited)]
    # Dedup edges
    seen: set[str] = set()
    deduped: list[dict] = []
    for e in edges:
        if e["event_id"] in seen:
            continue
        seen.add(e["event_id"])
        deduped.append(e)
    return ok({"person_id": person_id, "depth": depth, "nodes": nodes, "edges": deduped})
