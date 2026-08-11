"""Lay-down areas & staging reservations (PRD 3.7).

Aggregate-capacity semantics: windows may overlap freely; the sole check is
occupied_sqm + area_sqm <= capacity_sqm (equality admitted). Creation is
OCC-guarded on expected_laydown_area_version.
"""
from flask import Blueprint, request

import db
from errors import bad_request, conflict, invalid_state, stale
from helpers import (actor, as_dt, as_int, as_str, body, get_or_404, paged,
                     pagination_params, req_field, require_roles,
                     sorted_by_created)
from response import ok
from serialize import laydown_area_out, reservation_out
from services import computed
from util import fmt_iso

bp = Blueprint("laydown", __name__)

TM = ("TurnaroundManager",)
RESERVE_ROLES = ("ContractorSupervisor", "Planner")
SUPERVISOR = ("ContractorSupervisor",)


@bp.post("/turnarounds/<tid>/laydown-areas")
def create_area(tid):
    _uid, role = actor()
    require_roles(role, TM)
    get_or_404(db.turnarounds, tid, "Turnaround")
    b = body()
    name = as_str(req_field(b, "name"), "name")
    capacity = as_int(req_field(b, "capacity_sqm"), "capacity_sqm", minimum=1)
    now = db.now_iso()
    a = db.create(db.laydown_areas, {
        "id": db.mint_id(),
        "turnaround_id": tid,
        "name": name,
        "capacity_sqm": capacity,
        "status": "OPEN",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    return ok(laydown_area_out(a), status=201)


@bp.get("/turnarounds/<tid>/laydown-areas")
def list_areas(tid):
    actor()
    get_or_404(db.turnarounds, tid, "Turnaround")
    items = [a for a in db.laydown_areas.values() if a["turnaround_id"] == tid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([laydown_area_out(a) for a in page], pagination=meta)


@bp.get("/laydown-areas/<aid>")
def get_area(aid):
    actor()
    a = get_or_404(db.laydown_areas, aid, "LayDownArea")
    return ok(laydown_area_out(a))


@bp.post("/laydown-areas/<aid>/reservations")
def create_reservation(aid):
    _uid, role = actor()
    require_roles(role, RESERVE_ROLES)
    a = get_or_404(db.laydown_areas, aid, "LayDownArea")
    b = body()
    # OCC (priority 4) precedes request-shape checks (priority 5).
    occ = b.get("expected_laydown_area_version")
    if isinstance(occ, int) and not isinstance(occ, bool):
        if occ != a["version"]:
            stale("expected_laydown_area_version does not match the area version")
    as_int(req_field(b, "expected_laydown_area_version"),
           "expected_laydown_area_version")
    material = as_str(req_field(b, "material_description"),
                      "material_description")
    area_sqm = as_int(req_field(b, "area_sqm"), "area_sqm", minimum=1)
    window_from = as_dt(req_field(b, "window_from"), "window_from")
    window_until = as_dt(req_field(b, "window_until"), "window_until")
    if window_until <= window_from:
        bad_request("window_until must be strictly after window_from")
    if computed.occupied_sqm(aid) + area_sqm > a["capacity_sqm"]:
        conflict("ERR_LAYDOWN_CAPACITY_EXCEEDED",
                 "The reservation would exceed the area's capacity")
    now = db.now_iso()
    r = db.create(db.reservations, {
        "id": db.mint_id(),
        "laydown_area_id": aid,
        "material_description": material,
        "area_sqm": area_sqm,
        "window_from": fmt_iso(window_from),
        "window_until": fmt_iso(window_until),
        "status": "RESERVED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "_window_from": window_from,
        "_window_until": window_until,
    })
    db.touch(a)  # occupancy moved; the area's version increments
    return ok(reservation_out(r), status=201)


@bp.get("/laydown-areas/<aid>/reservations")
def list_reservations(aid):
    actor()
    get_or_404(db.laydown_areas, aid, "LayDownArea")
    items = [r for r in db.reservations.values() if r["laydown_area_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([reservation_out(r) for r in page], pagination=meta)


@bp.post("/reservations/<rid>/stage")
def stage_reservation(rid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    r = get_or_404(db.reservations, rid, "StagingReservation")
    if r["status"] != "RESERVED":
        invalid_state("Only a RESERVED reservation can be staged")
    r["status"] = "STAGED"
    db.touch(r)
    return ok(reservation_out(r))


@bp.post("/reservations/<rid>/release")
def release_reservation(rid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    r = get_or_404(db.reservations, rid, "StagingReservation")
    if r["status"] == "RESERVED":
        r["status"] = "CANCELLED"
    elif r["status"] == "STAGED":
        r["status"] = "RELEASED"
    else:
        invalid_state("Only a RESERVED or STAGED reservation can be released")
    db.touch(r)
    area = db.laydown_areas.get(r["laydown_area_id"])
    if area is not None:
        db.touch(area)  # occupancy moved; the area's version increments
    return ok(reservation_out(r))
