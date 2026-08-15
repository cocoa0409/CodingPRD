"""Flat canonical lookups and filtered lists (PRD §2.5)."""

from flask import Blueprint

import db
import errors
import helpers as h
import response

bp = Blueprint("flat", __name__)

ALL_ROLES = ("TrackOps", "SafetyOfficer", "Coach", "Organizer")
INCIDENT_ROLES = ("TrackOps", "SafetyOfficer")


def _lookup(store, rid, label):
    record = store.get(rid)
    if record is None:
        raise errors.not_found("%s %s not found" % (label, rid))
    return record


def _list(items, serializer):
    limit, offset = h.pagination()
    items = list(items)
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializer(r) for r in page], total, limit, offset)


# --- Coaches ---
@bp.route("/tracks/coaches/<cid>", methods=["GET"])
def flat_get_coach(cid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_coach(_lookup(db.coaches, cid, "coach")), 200)


@bp.route("/tracks/coaches", methods=["GET"])
def flat_list_coaches():
    h.require_roles(*ALL_ROLES)
    track_id = h.query_string("track_id")
    cert = h.query_enum("cert_level", h.CERT_LEVELS)
    active = h.parse_bool_param("active")
    items = db.coaches.values()
    if track_id is not None:
        items = [c for c in items if c["track_id"] == track_id]
    if cert is not None:
        items = [c for c in items if c["cert_level"] == cert]
    if active is not None:
        items = [c for c in items if c["active"] == active]
    return _list(items, h.serialize_coach)


# --- TrackDays ---
@bp.route("/tracks/track-days/<tdid>", methods=["GET"])
def flat_get_track_day(tdid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_track_day(_lookup(db.track_days, tdid, "track day")), 200)


@bp.route("/tracks/track-days", methods=["GET"])
def flat_list_track_days():
    h.require_roles(*ALL_ROLES)
    track_id = h.query_string("track_id")
    date = h.query_string("date")
    status = h.query_enum("status", h.TRACK_DAY_STATUSES)
    items = db.track_days.values()
    if track_id is not None:
        items = [d for d in items if d["track_id"] == track_id]
    if date is not None:
        items = [d for d in items if d["date"] == date]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return _list(items, h.serialize_track_day)


# --- RentalBlocks ---
@bp.route("/tracks/rental-blocks/<rbid>", methods=["GET"])
def flat_get_rental_block(rbid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_rental_block(_lookup(db.rental_blocks, rbid, "rental block")), 200)


@bp.route("/tracks/rental-blocks", methods=["GET"])
def flat_list_rental_blocks():
    h.require_roles(*ALL_ROLES)
    track_day_id = h.query_string("track_day_id")
    items = db.rental_blocks.values()
    if track_day_id is not None:
        items = [b for b in items if b["track_day_id"] == track_day_id]
    return _list(items, h.serialize_rental_block)


# --- Bookings ---
@bp.route("/tracks/bookings/<bid>", methods=["GET"])
def flat_get_booking(bid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_booking(_lookup(db.bookings, bid, "booking")), 200)


@bp.route("/tracks/bookings", methods=["GET"])
def flat_list_bookings():
    h.require_roles(*ALL_ROLES)
    rental_block_id = h.query_string("rental_block_id")
    coach_id = h.query_string("coach_id")
    approval_status = h.query_enum("approval_status", h.BOOKING_APPROVAL_STATUSES)
    items = db.bookings.values()
    if rental_block_id is not None:
        items = [b for b in items if b["rental_block_id"] == rental_block_id]
    if coach_id is not None:
        items = [b for b in items if b["coach_id"] == coach_id]
    if approval_status is not None:
        items = [b for b in items if b["approval_status"] == approval_status]
    return _list(items, h.serialize_booking)


# --- Drivers ---
@bp.route("/tracks/drivers/<did>", methods=["GET"])
def flat_get_driver(did):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_driver(_lookup(db.drivers, did, "driver")), 200)


@bp.route("/tracks/drivers", methods=["GET"])
def flat_list_drivers():
    h.require_roles(*ALL_ROLES)
    booking_id = h.query_string("booking_id")
    items = db.drivers.values()
    if booking_id is not None:
        items = [d for d in items if d["booking_id"] == booking_id]
    return _list(items, h.serialize_driver)


# --- Waivers ---
@bp.route("/tracks/waivers/<wid>", methods=["GET"])
def flat_get_waiver(wid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_waiver(_lookup(db.waivers, wid, "waiver")), 200)


@bp.route("/tracks/waivers", methods=["GET"])
def flat_list_waivers():
    h.require_roles(*ALL_ROLES)
    driver_id = h.query_string("driver_id")
    items = db.waivers.values()
    if driver_id is not None:
        items = [w for w in items if w["driver_id"] == driver_id]
    return _list(items, h.serialize_waiver)


# --- SafetyInspections ---
@bp.route("/tracks/safety-inspections/<siid>", methods=["GET"])
def flat_get_inspection(siid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_inspection(_lookup(db.inspections, siid, "safety inspection")), 200)


@bp.route("/tracks/safety-inspections", methods=["GET"])
def flat_list_inspections():
    h.require_roles(*ALL_ROLES)
    driver_id = h.query_string("driver_id")
    items = db.inspections.values()
    if driver_id is not None:
        items = [i for i in items if i["driver_id"] == driver_id]
    return _list(items, h.serialize_inspection)


# --- Sessions ---
@bp.route("/tracks/sessions/<sid>", methods=["GET"])
def flat_get_session(sid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_session(_lookup(db.sessions, sid, "session")), 200)


@bp.route("/tracks/sessions", methods=["GET"])
def flat_list_sessions():
    h.require_roles(*ALL_ROLES)
    track_day_id = h.query_string("track_day_id")
    rental_block_id = h.query_string("rental_block_id")
    status = h.query_enum("status", h.SESSION_STATUSES)
    items = db.sessions.values()
    if track_day_id is not None:
        items = [s for s in items if s["track_day_id"] == track_day_id]
    if rental_block_id is not None:
        items = [s for s in items if s["rental_block_id"] == rental_block_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return _list(items, h.serialize_session)


# --- Incidents ---
@bp.route("/tracks/incidents/<iid>", methods=["GET"])
def flat_get_incident(iid):
    h.require_roles(*INCIDENT_ROLES)
    return response.success(h.serialize_incident(_lookup(db.incidents, iid, "incident")), 200)


@bp.route("/tracks/incidents", methods=["GET"])
def flat_list_incidents():
    h.require_roles(*INCIDENT_ROLES)
    track_day_id = h.query_string("track_day_id")
    session_id = h.query_string("session_id")
    status = h.query_enum("status", h.INCIDENT_STATUSES)
    severity = h.query_enum("severity", h.SEVERITIES)
    items = db.incidents.values()
    if track_day_id is not None:
        items = [i for i in items if i["track_day_id"] == track_day_id]
    if session_id is not None:
        items = [i for i in items if i["session_id"] == session_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if severity is not None:
        items = [i for i in items if i["severity"] == severity]
    return _list(items, h.serialize_incident)


# --- NoiseReadings ---
@bp.route("/tracks/noise-readings/<nrid>", methods=["GET"])
def flat_get_noise_reading(nrid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_noise_reading(_lookup(db.noise_readings, nrid, "noise reading")), 200)


@bp.route("/tracks/noise-readings", methods=["GET"])
def flat_list_noise_readings():
    h.require_roles(*ALL_ROLES)
    track_day_id = h.query_string("track_day_id")
    session_id = h.query_string("session_id")
    breach = h.parse_bool_param("breach")
    items = db.noise_readings.values()
    if track_day_id is not None:
        items = [n for n in items if n["track_day_id"] == track_day_id]
    if session_id is not None:
        items = [n for n in items if n["session_id"] == session_id]
    if breach is not None:
        items = [n for n in items if n["breach"] == breach]
    return _list(items, h.serialize_noise_reading)


# --- GarageAssignments ---
@bp.route("/tracks/garage-assignments/<gid>", methods=["GET"])
def flat_get_garage_assignment(gid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_garage_assignment(_lookup(db.garage_assignments, gid, "garage assignment")), 200)


@bp.route("/tracks/garage-assignments", methods=["GET"])
def flat_list_garage_assignments():
    h.require_roles(*ALL_ROLES)
    track_day_id = h.query_string("track_day_id")
    booking_id = h.query_string("booking_id")
    status = h.query_enum("status", h.ASSIGNMENT_STATUSES)
    items = db.garage_assignments.values()
    if track_day_id is not None:
        items = [g for g in items if g["track_day_id"] == track_day_id]
    if booking_id is not None:
        items = [g for g in items if g["booking_id"] == booking_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return _list(items, h.serialize_garage_assignment)


# --- PaddockAssignments ---
@bp.route("/tracks/paddock-assignments/<pid>", methods=["GET"])
def flat_get_paddock_assignment(pid):
    h.require_roles(*ALL_ROLES)
    return response.success(h.serialize_paddock_assignment(_lookup(db.paddock_assignments, pid, "paddock assignment")), 200)


@bp.route("/tracks/paddock-assignments", methods=["GET"])
def flat_list_paddock_assignments():
    h.require_roles(*ALL_ROLES)
    track_day_id = h.query_string("track_day_id")
    booking_id = h.query_string("booking_id")
    status = h.query_enum("status", h.ASSIGNMENT_STATUSES)
    items = db.paddock_assignments.values()
    if track_day_id is not None:
        items = [p for p in items if p["track_day_id"] == track_day_id]
    if booking_id is not None:
        items = [p for p in items if p["booking_id"] == booking_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return _list(items, h.serialize_paddock_assignment)
