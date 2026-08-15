"""Tour coordination (PRD §3.2): buffered site schedule guard runs before the
plain representative-calendar guard; completion is gated on the logical clock.
"""
from datetime import timedelta

from flask import Blueprint

from db import store, new_entity, public, touch
from errors import (
    ApiError, ERR_FORBIDDEN, ERR_INVALID_TIME_RANGE, ERR_INVALID_STATE,
    ERR_SITE_NOT_LISTED, ERR_TOUR_SITE_CONFLICT, ERR_REP_CALENDAR_CONFLICT,
    ERR_TOUR_NOT_CONCLUDED,
)
from middleware import (
    authenticate, body, require_fields, get_fk, get_path, ALL_ROLES,
)
from response import success_object
from routes import list_response
from timeutil import parse_iso

bp = Blueprint("tours", __name__)

BUFFER = timedelta(minutes=30)


@bp.post("/api/tours")
def create_tour():
    uid, _ = authenticate(["TenantRep"])
    b = body()
    # Priority 4 (existence), input-list order: site_id then requirement_id.
    site = get_fk(b, "site_id", store.sites)
    req = get_fk(b, "requirement_id", store.requirements)
    require_fields(b, [
        ("site_id", "string", True),
        ("requirement_id", "string", True),
        ("start_at", "datetime", True),
        ("end_at", "datetime", True),
    ])
    if site is None:
        site = store.sites[b["site_id"]]
    if req is None:
        req = store.requirements[b["requirement_id"]]
    start_dt = parse_iso(b["start_at"])
    end_dt = parse_iso(b["end_at"])
    # Priority 7: end strictly after start.
    if end_dt <= start_dt:
        raise ApiError(ERR_INVALID_TIME_RANGE,
                       "end_at must be strictly after start_at", 422)
    # Priority 13: buffered site schedule first, then representative calendar.
    for t in store.tours.values():
        if t["status"] == "CANCELLED" or t["site_id"] != site["id"]:
            continue
        buf_start = parse_iso(t["start_at"]) - BUFFER
        buf_end = parse_iso(t["end_at"]) + BUFFER
        if buf_start < end_dt and start_dt < buf_end:
            raise ApiError(ERR_TOUR_SITE_CONFLICT,
                           "Tour intersects a non-CANCELLED tour at the same site "
                           "under 30-minute buffered interval semantics", 409)
    for t in store.tours.values():
        if t["status"] == "CANCELLED" or t["tenant_rep_id"] != uid:
            continue
        t_start = parse_iso(t["start_at"])
        t_end = parse_iso(t["end_at"])
        if t_start < end_dt and start_dt < t_end:
            raise ApiError(ERR_REP_CALENDAR_CONFLICT,
                           "Tour intersects a non-CANCELLED tour of the same "
                           "tenant representative", 409)
    ent = new_entity({
        "site_id": site["id"],
        "requirement_id": req["id"],
        "tenant_rep_id": uid,
        "start_at": b["start_at"],
        "end_at": b["end_at"],
        "status": "REQUESTED",
    })
    store.tours[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/tours")
def list_tours():
    authenticate(ALL_ROLES)
    return list_response(store.tours.values(), [
        ("site_id", lambda e: e["site_id"]),
        ("requirement_id", lambda e: e["requirement_id"]),
        ("tenant_rep_id", lambda e: e["tenant_rep_id"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/tours/<tid>")
def get_tour(tid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.tours, tid, "tour")))


@bp.post("/api/tours/<tid>/confirm")
def confirm_tour(tid):
    authenticate(["LeasingManager"])
    tour = get_path(store.tours, tid, "tour")
    if tour["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot confirm a tour in status {tour['status']}", 409)
    # Cross-entity gate: the toured site must be LISTED or RESERVED.
    site = store.sites[tour["site_id"]]
    if site["status"] not in ("LISTED", "RESERVED"):
        raise ApiError(ERR_SITE_NOT_LISTED,
                       f"Tour site is in status {site['status']}", 409)
    tour["status"] = "CONFIRMED"
    touch(tour)
    return success_object(public(tour))


@bp.post("/api/tours/<tid>/complete")
def complete_tour(tid):
    uid, _ = authenticate(["TenantRep"])
    tour = get_path(store.tours, tid, "tour")
    # Priority 3: representative ownership.
    if tour["tenant_rep_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, "X-User-ID does not own this tour", 403)
    if tour["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot complete a tour in status {tour['status']}", 409)
    # Priority 15/22: the logical clock must have reached the tour's end.
    if store.clock < parse_iso(tour["end_at"]):
        raise ApiError(ERR_TOUR_NOT_CONCLUDED,
                       "The tour window has not concluded on the logical clock", 409)
    tour["status"] = "COMPLETED"
    touch(tour)
    return success_object(public(tour))


@bp.post("/api/tours/<tid>/cancel")
def cancel_tour(tid):
    uid, role = authenticate(["TenantRep", "LeasingManager"])
    tour = get_path(store.tours, tid, "tour")
    # Priority 3: a TenantRep may only cancel their own tours.
    if role == "TenantRep" and tour["tenant_rep_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, "X-User-ID does not own this tour", 403)
    if tour["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot cancel a tour in status {tour['status']}", 409)
    tour["status"] = "CANCELLED"
    touch(tour)
    return success_object(public(tour))
