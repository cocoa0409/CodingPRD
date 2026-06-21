"""Visitor Management & Lobby Check-In API — Flask entry point.

Storage is in-memory only (db.py dicts). The store starts EMPTY on every boot;
nothing is seeded. All state is built by clients through the declared endpoints.
"""
import os

from flask import Flask, request

import calculations as calc
import clock
import db
import errors
import middleware
import response
import serializers
import validation as V

app = Flask(__name__)
app.url_map.strict_slashes = False

# Enums
DEPARTMENTS = {"ENGINEERING", "SALES", "FACILITIES", "EXECUTIVE"}
MATCH_TYPES = {"NAME", "COMPANY"}
SEVERITIES = {"REVIEW", "DENY"}
DOCUMENT_KINDS = {"NDA", "SAFETY_WAIVER", "DATA_POLICY"}
CARRIERS = {"FEDEX", "UPS", "USPS", "DHL", "COURIER"}
EVAC_REASONS = {"FIRE_DRILL", "FIRE_ALARM", "GAS_LEAK", "OTHER"}
CLEARANCE_DECISIONS = {"CLEAR", "DENY"}

CLEANING_BUFFER_MINUTES = 15


# -----------------------------------------------------------------------------
# Error handling
# -----------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return response.error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return response.error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return response.error_response(exc.error_id, exc.message, exc.http_status)
    return response.error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)


# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------
def auth():
    return middleware.authenticate()


def fk_get(collection, key, label):
    """Resolve an FK / path id; raise ERR_NOT_FOUND (404) if missing."""
    if key is None:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "%s not found" % label)
    rec = collection.get(key)
    if rec is None:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "%s not found" % label)
    return rec


def require_version_field(body, field):
    """OCC field: required, integer, non-negative (422 if malformed)."""
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise V.invalid("Field '%s' is required and must be a non-negative integer" % field)
    return val


def list_response(rows, serializer):
    limit, offset = V.parse_pagination()
    page, total = V.paginate(rows, limit, offset)
    return response.array_response([serializer(r) for r in page], limit, offset, total)


def filtered(collection, filters):
    """Return rows matching every provided (field == value) filter."""
    out = []
    for r in collection.values():
        ok = True
        for field, value in filters.items():
            if value is not None and r.get(field) != value:
                ok = False
                break
        if ok:
            out.append(r)
    return out


def arg(name):
    return request.args.get(name)


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
def root():
    return response.object_response({"service": "visitor-management-lobby-checkin"}, 200)


# =============================================================================
# Clock (test-driving)  — SecurityOfficer
# =============================================================================
@app.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    now_dt = V.require_datetime(body, "now_utc")
    clock.set_now(now_dt)
    return response.object_response({"now_utc": clock.iso(now_dt)}, 200)


# =============================================================================
# Site
# =============================================================================
@app.route("/sites", methods=["POST"])
def create_site():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    name = V.require_str(body, "name")
    timezone = V.optional_str(body, "timezone", default="UTC")
    badge_total = V.require_int(body, "badge_total", minimum=0)
    rec = db.stamp_create({
        "name": name,
        "timezone": timezone,
        "badge_total": badge_total,
    })
    db.sites[rec["id"]] = rec
    return response.object_response(serializers.site(rec), 201)


@app.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.sites, site_id, "Site")
    return response.object_response(serializers.site(rec), 200)


# =============================================================================
# Floor
# =============================================================================
@app.route("/floors", methods=["POST"])
def create_floor():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    site_id = V.require_str(body, "site_id")
    label = V.require_str(body, "label")
    capacity = V.require_int(body, "capacity", minimum=1)
    fk_get(db.sites, site_id, "Site")
    rec = db.stamp_create({
        "site_id": site_id,
        "label": label,
        "capacity": capacity,
    })
    db.floors[rec["id"]] = rec
    return response.object_response(serializers.floor(rec), 201)


@app.route("/floors/<floor_id>", methods=["GET"])
def get_floor(floor_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.floors, floor_id, "Floor")
    return response.object_response(serializers.floor(rec), 200)


@app.route("/floors", methods=["GET"])
def list_floors():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.floors, {"site_id": arg("site_id")})
    return list_response(rows, serializers.floor)


# =============================================================================
# Host
# =============================================================================
@app.route("/hosts", methods=["POST"])
def create_host():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    site_id = V.require_str(body, "site_id")
    full_name = V.require_str(body, "full_name")
    email = V.require_str(body, "email")
    department = V.optional_enum(body, "department", DEPARTMENTS, default="FACILITIES")
    fk_get(db.sites, site_id, "Site")
    rec = db.stamp_create({
        "site_id": site_id,
        "full_name": full_name,
        "email": email,
        "department": department,
        "notify_count": 0,
    })
    db.hosts[rec["id"]] = rec
    return response.object_response(serializers.host(rec), 201)


@app.route("/hosts/<host_id>", methods=["GET"])
def get_host(host_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.hosts, host_id, "Host")
    return response.object_response(serializers.host(rec), 200)


@app.route("/hosts", methods=["GET"])
def list_hosts():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.hosts, {"site_id": arg("site_id")})
    return list_response(rows, serializers.host)


# =============================================================================
# WatchlistEntry  (SecurityOfficer only, all operations)
# =============================================================================
@app.route("/watchlist-entries", methods=["POST"])
def create_watchlist_entry():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    site_id = V.require_str(body, "site_id")
    match_type = V.require_enum(body, "match_type", MATCH_TYPES)
    match_value = V.require_str(body, "match_value_normalized")
    severity = V.optional_enum(body, "severity", SEVERITIES, default="REVIEW")
    active = V.optional_bool(body, "active", default=True)
    fk_get(db.sites, site_id, "Site")
    rec = db.stamp_create({
        "site_id": site_id,
        "match_type": match_type,
        "match_value_normalized": match_value,
        "severity": severity,
        "active": active,
    })
    db.watchlist_entries[rec["id"]] = rec
    return response.object_response(serializers.watchlist_entry(rec), 201)


@app.route("/watchlist-entries/<entry_id>", methods=["GET"])
def get_watchlist_entry(entry_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    rec = fk_get(db.watchlist_entries, entry_id, "WatchlistEntry")
    return response.object_response(serializers.watchlist_entry(rec), 200)


@app.route("/watchlist-entries", methods=["GET"])
def list_watchlist_entries():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    rows = filtered(db.watchlist_entries, {"site_id": arg("site_id")})
    return list_response(rows, serializers.watchlist_entry)


# =============================================================================
# MeetingRoom
# =============================================================================
@app.route("/meeting-rooms", methods=["POST"])
def create_meeting_room():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    floor_id = V.require_str(body, "floor_id")
    name = V.require_str(body, "name")
    seats = V.require_int(body, "seats", minimum=1)
    fk_get(db.floors, floor_id, "Floor")
    rec = db.stamp_create({
        "floor_id": floor_id,
        "name": name,
        "seats": seats,
    })
    db.meeting_rooms[rec["id"]] = rec
    return response.object_response(serializers.meeting_room(rec), 201)


@app.route("/meeting-rooms/<room_id>", methods=["GET"])
def get_meeting_room(room_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.meeting_rooms, room_id, "MeetingRoom")
    return response.object_response(serializers.meeting_room(rec), 200)


@app.route("/meeting-rooms", methods=["GET"])
def list_meeting_rooms():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.meeting_rooms, {"floor_id": arg("floor_id")})
    return list_response(rows, serializers.meeting_room)


# =============================================================================
# ParkingSpace
# =============================================================================
@app.route("/parking-spaces", methods=["POST"])
def create_parking_space():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    site_id = V.require_str(body, "site_id")
    bay_label = V.require_str(body, "bay_label")
    fk_get(db.sites, site_id, "Site")
    rec = db.stamp_create({
        "site_id": site_id,
        "bay_label": bay_label,
    })
    db.parking_spaces[rec["id"]] = rec
    return response.object_response(serializers.parking_space(rec), 201)


@app.route("/parking-spaces/<space_id>", methods=["GET"])
def get_parking_space(space_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.parking_spaces, space_id, "ParkingSpace")
    return response.object_response(serializers.parking_space(rec), 200)


@app.route("/parking-spaces", methods=["GET"])
def list_parking_spaces():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.parking_spaces, {"site_id": arg("site_id")})
    return list_response(rows, serializers.parking_space)


# =============================================================================
# ContractorPass
# =============================================================================
@app.route("/contractor-passes", methods=["POST"])
def create_contractor_pass():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    host_id = V.require_str(body, "host_id")
    contractor_name = V.require_str(body, "contractor_name")
    contractor_company = V.require_str(body, "contractor_company")
    valid_from = V.require_datetime(body, "access_valid_from")
    valid_until = V.require_datetime(body, "access_valid_until")
    fk_get(db.hosts, host_id, "Host")
    rec = db.stamp_create({
        "host_id": host_id,
        "contractor_name": contractor_name,
        "contractor_company": contractor_company,
        "access_valid_from": clock.iso(valid_from),
        "access_valid_until": clock.iso(valid_until),
        "status": "ACTIVE",
        "covered_visit_count": 0,
    })
    db.contractor_passes[rec["id"]] = rec
    return response.object_response(serializers.contractor_pass(rec), 201)


@app.route("/contractor-passes/<pass_id>", methods=["GET"])
def get_contractor_pass(pass_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.contractor_passes, pass_id, "ContractorPass")
    return response.object_response(serializers.contractor_pass(rec), 200)


@app.route("/contractor-passes", methods=["GET"])
def list_contractor_passes():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.contractor_passes, {"host_id": arg("host_id")})
    return list_response(rows, serializers.contractor_pass)


def _pass_transition(pass_id, allowed_from, target):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    rec = fk_get(db.contractor_passes, pass_id, "ContractorPass")
    if rec["status"] not in allowed_from:
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "ContractorPass is %s; cannot transition to %s" % (rec["status"], target),
        )
    rec["status"] = target
    db.touch(rec)
    return response.object_response(serializers.contractor_pass(rec), 200)


@app.route("/contractor-passes/<pass_id>/suspend", methods=["POST"])
def suspend_pass(pass_id):
    return _pass_transition(pass_id, {"ACTIVE"}, "SUSPENDED")


@app.route("/contractor-passes/<pass_id>/reactivate", methods=["POST"])
def reactivate_pass(pass_id):
    return _pass_transition(pass_id, {"SUSPENDED"}, "ACTIVE")


@app.route("/contractor-passes/<pass_id>/revoke", methods=["POST"])
def revoke_pass(pass_id):
    return _pass_transition(pass_id, {"ACTIVE", "SUSPENDED"}, "REVOKED")


@app.route("/contractor-passes/<pass_id>/billing", methods=["GET"])
def pass_billing(pass_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "Host"])
    rec = fk_get(db.contractor_passes, pass_id, "ContractorPass")
    covered = [v for v in db.visits.values()
               if v.get("contractor_pass_id") == pass_id and v.get("status") == "SIGNED_OUT"]
    total, count = calc.contractor_billing_total(covered)
    return response.object_response({
        "pass_id": pass_id,
        "billing_total_cents": total,
        "covered_signed_out_count": count,
    }, 200)


# =============================================================================
# Visit
# =============================================================================
def _intervals_overlap_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start,end): overlap iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


def _check_room_conflict(room_id, scheduled_start, scheduled_end, exclude_visit_id):
    """ERR_ROOM_CONFLICT (409) if half-open [start,end) overlaps an existing booking."""
    for v in db.visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v.get("room_id") != room_id:
            continue
        # terminal/denied visits still hold their booking? Booking interval is about the
        # schedule; we consider any visit referencing the same room as occupying it.
        other_start = clock.parse_iso(v["scheduled_start"])
        other_end = clock.parse_iso(v["scheduled_end"])
        if _intervals_overlap_half_open(scheduled_start, scheduled_end, other_start, other_end):
            raise errors.ApiError(
                errors.ERR_ROOM_CONFLICT, 409,
                "Meeting room booking overlaps an existing booking",
            )


def _check_parking_conflict(space_id, scheduled_start, scheduled_end, exclude_visit_id):
    """ERR_PARKING_CONFLICT (409) when within 15-min cleaning buffer of an existing reservation.

    Closed interval extended by buffer on each side; adjacency NOT allowed.
    Conflict iff a_start <= b_end + buffer AND b_start <= a_end + buffer.
    """
    buffer_seconds = CLEANING_BUFFER_MINUTES * 60
    for v in db.visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v.get("parking_space_id") != space_id:
            continue
        other_start = clock.parse_iso(v["scheduled_start"])
        other_end = clock.parse_iso(v["scheduled_end"])
        gap_ok_after = (other_start - scheduled_end).total_seconds() >= buffer_seconds
        gap_ok_before = (scheduled_start - other_end).total_seconds() >= buffer_seconds
        if not (gap_ok_after or gap_ok_before):
            raise errors.ApiError(
                errors.ERR_PARKING_CONFLICT, 409,
                "Parking reservation within the %d-minute cleaning buffer of an existing reservation"
                % CLEANING_BUFFER_MINUTES,
            )


@app.route("/visits", methods=["POST"])
def create_visit():
    _, role = auth()
    middleware.require_role(role, ["Host", "LobbyAttendant"])
    body = V.get_json_body()

    site_id = V.require_str(body, "site_id")
    host_id = V.require_str(body, "host_id")
    floor_id = V.require_str(body, "floor_id")
    room_id = V.optional_str(body, "room_id", default=None)
    parking_space_id = V.optional_str(body, "parking_space_id", default=None)
    contractor_pass_id = V.optional_str(body, "contractor_pass_id", default=None)
    visitor_full_name = V.require_str(body, "visitor_full_name")
    visitor_company = V.require_str(body, "visitor_company")
    scheduled_start = V.require_datetime(body, "scheduled_start")
    scheduled_end = V.require_datetime(body, "scheduled_end")
    id_scanned = V.optional_bool(body, "id_scanned", default=False)

    # Existence checks (404) — FK bodies reference existing rows.
    fk_get(db.sites, site_id, "Site")
    host = fk_get(db.hosts, host_id, "Host")
    fk_get(db.floors, floor_id, "Floor")
    if room_id is not None:
        fk_get(db.meeting_rooms, room_id, "MeetingRoom")
    if parking_space_id is not None:
        fk_get(db.parking_spaces, parking_space_id, "ParkingSpace")
    if contractor_pass_id is not None:
        fk_get(db.contractor_passes, contractor_pass_id, "ContractorPass")

    # Booking conflict checks (priority 12 then 13).
    if room_id is not None:
        _check_room_conflict(room_id, scheduled_start, scheduled_end, exclude_visit_id=None)
    if parking_space_id is not None:
        _check_parking_conflict(parking_space_id, scheduled_start, scheduled_end, exclude_visit_id=None)

    rec = db.stamp_create({
        "site_id": site_id,
        "host_id": host_id,
        "floor_id": floor_id,
        "room_id": room_id,
        "parking_space_id": parking_space_id,
        "contractor_pass_id": contractor_pass_id,
        "visitor_full_name": visitor_full_name,
        "visitor_company": visitor_company,
        "scheduled_start": clock.iso(scheduled_start),
        "scheduled_end": clock.iso(scheduled_end),
        "id_scanned": id_scanned,
        "status": "PREREGISTERED",
        "risk_score": 0,
        "sign_in_at": None,
        "sign_out_at": None,
        "visit_duration_minutes": None,
        "badge_number": None,
        "_ever_signed_in": False,
    })
    db.visits[rec["id"]] = rec

    # Side effect: pre-registration host notification.
    host["notify_count"] += 1
    db.touch(host)

    return response.object_response(serializers.visit(rec), 201)


@app.route("/visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.visits, visit_id, "Visit")
    return response.object_response(serializers.visit(rec), 200)


@app.route("/visits", methods=["GET"])
def list_visits():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.visits, {
        "host_id": arg("host_id"),
        "floor_id": arg("floor_id"),
        "contractor_pass_id": arg("contractor_pass_id"),
        "room_id": arg("room_id"),
        "parking_space_id": arg("parking_space_id"),
        "site_id": arg("site_id"),
        "status": arg("status"),
    })
    return list_response(rows, serializers.visit)


@app.route("/visits/<visit_id>", methods=["PATCH"])
def patch_visit(visit_id):
    _, role = auth()
    middleware.require_role(role, ["Host", "LobbyAttendant"])
    rec = fk_get(db.visits, visit_id, "Visit")
    body = V.get_json_body()

    # Determine effective values (well-formedness 422 before state checks per precedence).
    new_room_id = rec.get("room_id")
    room_provided = "room_id" in body
    if room_provided:
        new_room_id = V.optional_str(body, "room_id", default=None)

    new_parking_id = rec.get("parking_space_id")
    parking_provided = "parking_space_id" in body
    if parking_provided:
        new_parking_id = V.optional_str(body, "parking_space_id", default=None)

    schedule_changed = False
    new_start = clock.parse_iso(rec["scheduled_start"])
    new_end = clock.parse_iso(rec["scheduled_end"])
    if "scheduled_start" in body and body.get("scheduled_start") is not None:
        new_start = V.require_datetime(body, "scheduled_start")
        schedule_changed = True
    if "scheduled_end" in body and body.get("scheduled_end") is not None:
        new_end = V.require_datetime(body, "scheduled_end")
        schedule_changed = True

    new_id_scanned = rec["id_scanned"]
    if "id_scanned" in body and body.get("id_scanned") is not None:
        new_id_scanned = V.optional_bool(body, "id_scanned", default=rec["id_scanned"])

    # Existence of new FK targets (404).
    if room_provided and new_room_id is not None:
        fk_get(db.meeting_rooms, new_room_id, "MeetingRoom")
    if parking_provided and new_parking_id is not None:
        fk_get(db.parking_spaces, new_parking_id, "ParkingSpace")

    # Re-run conflict checks when room/parking/schedule changed (priority 12/13).
    room_changed = room_provided or schedule_changed
    if new_room_id is not None and room_changed:
        _check_room_conflict(new_room_id, new_start, new_end, exclude_visit_id=visit_id)
    parking_changed = parking_provided or schedule_changed
    if new_parking_id is not None and parking_changed:
        _check_parking_conflict(new_parking_id, new_start, new_end, exclude_visit_id=visit_id)

    rec["room_id"] = new_room_id
    rec["parking_space_id"] = new_parking_id
    rec["scheduled_start"] = clock.iso(new_start)
    rec["scheduled_end"] = clock.iso(new_end)
    rec["id_scanned"] = new_id_scanned
    db.touch(rec)
    return response.object_response(serializers.visit(rec), 200)


def _void_pending_agreements(visit_id):
    """Cascade: every PENDING agreement on this visit -> VOID (each bumps its own version)."""
    for ag in db.agreements.values():
        if ag.get("visit_id") == visit_id and ag.get("status") == "PENDING":
            ag["status"] = "VOID"
            db.touch(ag)


@app.route("/visits/<visit_id>/screen", methods=["POST"])
def screen_visit(visit_id):
    _, role = auth()
    middleware.require_role(role, ["LobbyAttendant", "SecurityOfficer"])
    rec = fk_get(db.visits, visit_id, "Visit")

    if rec["status"] != "PREREGISTERED":
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "Visit is %s; screening requires PREREGISTERED" % rec["status"],
        )

    entries = list(db.watchlist_entries.values())
    rec["risk_score"] = calc.risk_score(rec, entries)
    decision = calc.screening_decision(rec, entries)

    if decision == "DENY":
        rec["status"] = "DENIED"
        db.touch(rec)
        _void_pending_agreements(visit_id)
    elif decision == "REVIEW":
        rec["status"] = "FLAGGED"
        db.touch(rec)
    else:  # CLEAR
        rec["status"] = "CLEARED"
        db.touch(rec)

    return response.object_response(serializers.visit(rec), 200)


@app.route("/visits/<visit_id>/clearance", methods=["POST"])
def clearance_visit(visit_id):
    user_id, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    rec = fk_get(db.visits, visit_id, "Visit")
    body = V.get_json_body()

    # 4. well-formedness (422)
    decision = V.require_enum(body, "decision", CLEARANCE_DECISIONS)
    expected_version = require_version_field(body, "expected_visit_version")

    # 5. OCC (412)
    if expected_version != rec["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_VISIT_VERSION, 412,
            "expected_visit_version does not match current Visit.version",
        )

    # 6. state (409)
    if rec["status"] != "FLAGGED":
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "Visit is %s; clearance requires FLAGGED" % rec["status"],
        )

    # 7. segregation of duties (409)
    if user_id == rec["host_id"]:
        raise errors.ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES, 409,
            "A host may not adjudicate a flag on their own guest",
        )

    if decision == "CLEAR":
        rec["status"] = "CLEARED"
        db.touch(rec)
    else:  # DENY
        rec["status"] = "DENIED"
        db.touch(rec)
        _void_pending_agreements(visit_id)

    return response.object_response(serializers.visit(rec), 200)


@app.route("/visits/<visit_id>/sign-in", methods=["POST"])
def sign_in_visit(visit_id):
    _, role = auth()
    middleware.require_role(role, ["LobbyAttendant"])
    rec = fk_get(db.visits, visit_id, "Visit")
    body = V.get_json_body()

    # 4. well-formedness (422)
    expected_floor_version = require_version_field(body, "expected_floor_version")

    floor = db.floors.get(rec["floor_id"])
    site = db.sites.get(rec["site_id"])

    # 5. OCC (412) — guard on Floor.version.
    if floor is None or expected_floor_version != floor["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_FLOOR_VERSION, 412,
            "expected_floor_version does not match current Floor.version",
        )

    # 6. state (409)
    if rec["status"] != "CLEARED":
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "Visit is %s; sign-in requires CLEARED" % rec["status"],
        )

    # 8. id scanned (409)
    if not rec["id_scanned"]:
        raise errors.ApiError(errors.ERR_ID_NOT_SCANNED, 409, "Government photo ID was not scanned")

    # 9. all agreements SIGNED (none PENDING) (409)
    for ag in db.agreements.values():
        if ag.get("visit_id") == visit_id and ag.get("status") == "PENDING":
            raise errors.ApiError(
                errors.ERR_AGREEMENT_NOT_SIGNED, 409,
                "At least one agreement on this visit is still PENDING",
            )

    # 10/11. contractor pass active + window (409)
    pass_rec = None
    if rec.get("contractor_pass_id") is not None:
        pass_rec = db.contractor_passes.get(rec["contractor_pass_id"])
        if pass_rec is None or pass_rec["status"] != "ACTIVE":
            raise errors.ApiError(
                errors.ERR_PASS_NOT_ACTIVE, 409,
                "Contractor pass is not ACTIVE",
            )
        sched_start = clock.parse_iso(rec["scheduled_start"])
        valid_from = clock.parse_iso(pass_rec["access_valid_from"])
        valid_until = clock.parse_iso(pass_rec["access_valid_until"])
        if not (valid_from <= sched_start <= valid_until):
            raise errors.ApiError(
                errors.ERR_PASS_WINDOW, 409,
                "scheduled_start is outside the contractor access window",
            )

    # 14. floor capacity (409) — available_slots >= 1.
    current_occupancy = sum(
        1 for v in db.visits.values()
        if v.get("floor_id") == floor["id"] and v.get("status") == "SIGNED_IN"
    )
    if floor["capacity"] - current_occupancy < 1:
        raise errors.ApiError(errors.ERR_FLOOR_AT_CAPACITY, 409, "Floor is at capacity")

    # 15. badge availability (409) — badge_available >= 1.
    badge_in_use = sum(
        1 for v in db.visits.values()
        if v.get("site_id") == site["id"] and v.get("status") == "SIGNED_IN"
    ) if site is not None else 0
    badge_total = site["badge_total"] if site is not None else 0
    if site is None or (badge_total - badge_in_use) < 1:
        raise errors.ApiError(errors.ERR_NO_BADGE_AVAILABLE, 409, "No physical badge available")

    # --- commit: all guards passed ---
    rec["status"] = "SIGNED_IN"
    rec["sign_in_at"] = clock.now_iso()
    rec["badge_number"] = "BADGE-" + rec["id"][:8].upper()
    first_sign_in = not rec.get("_ever_signed_in", False)
    rec["_ever_signed_in"] = True
    db.touch(rec)

    # Floor mutation (occupancy is recomputed at read; version advances — same field OCC reads).
    db.touch(floor)
    # Site mutation (badge counters recomputed at read; version advances).
    db.touch(site)

    # Host arrival notification.
    host = db.hosts.get(rec["host_id"])
    if host is not None:
        host["notify_count"] += 1
        db.touch(host)

    # First SIGNED_IN of a contractor-covered visit bumps covered_visit_count (cross-aggregate).
    if pass_rec is not None and first_sign_in:
        pass_rec["covered_visit_count"] += 1
        db.touch(pass_rec)

    return response.object_response(serializers.visit(rec), 200)


@app.route("/visits/<visit_id>/sign-out", methods=["POST"])
def sign_out_visit(visit_id):
    _, role = auth()
    middleware.require_role(role, ["LobbyAttendant"])
    rec = fk_get(db.visits, visit_id, "Visit")

    if rec["status"] != "SIGNED_IN":
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "Visit is %s; sign-out requires SIGNED_IN" % rec["status"],
        )

    rec["status"] = "SIGNED_OUT"
    rec["sign_out_at"] = clock.now_iso()
    rec["visit_duration_minutes"] = calc.visit_duration_minutes(
        rec["sign_in_at"], rec["sign_out_at"]
    )
    db.touch(rec)

    # Compensating actions: floor + site counters recomputed at read; bump versions.
    floor = db.floors.get(rec["floor_id"])
    if floor is not None:
        db.touch(floor)
    site = db.sites.get(rec["site_id"])
    if site is not None:
        db.touch(site)

    return response.object_response(serializers.visit(rec), 200)


# =============================================================================
# Agreement
# =============================================================================
@app.route("/agreements", methods=["POST"])
def create_agreement():
    _, role = auth()
    middleware.require_role(role, ["Host", "LobbyAttendant"])
    body = V.get_json_body()
    visit_id = V.require_str(body, "visit_id")
    document_kind = V.require_enum(body, "document_kind", DOCUMENT_KINDS)
    document_version = V.require_str(body, "document_version")
    fk_get(db.visits, visit_id, "Visit")
    rec = db.stamp_create({
        "visit_id": visit_id,
        "document_kind": document_kind,
        "document_version": document_version,
        "status": "PENDING",
        "signed_at": None,
        "signer_name": None,
    })
    db.agreements[rec["id"]] = rec
    return response.object_response(serializers.agreement(rec), 201)


@app.route("/agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.agreements, agreement_id, "Agreement")
    return response.object_response(serializers.agreement(rec), 200)


@app.route("/agreements", methods=["GET"])
def list_agreements():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.agreements, {"visit_id": arg("visit_id")})
    return list_response(rows, serializers.agreement)


SIGNABLE_VISIT_STATES = {"PREREGISTERED", "SCREENING", "FLAGGED", "CLEARED"}


@app.route("/agreements/<agreement_id>/sign", methods=["POST"])
def sign_agreement(agreement_id):
    _, role = auth()
    middleware.require_role(role, ["LobbyAttendant", "Host"])
    rec = fk_get(db.agreements, agreement_id, "Agreement")
    body = V.get_json_body()

    # 4. well-formedness (422)
    signer_name = V.require_str(body, "signer_name")

    # 6. state (409): agreement must be PENDING.
    if rec["status"] != "PENDING":
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "Agreement is %s; signing requires PENDING" % rec["status"],
        )

    # Parent visit must be in a pre-entry state.
    visit = db.visits.get(rec["visit_id"])
    if visit is None or visit["status"] not in SIGNABLE_VISIT_STATES:
        raise errors.ApiError(
            errors.ERR_VISIT_NOT_SIGNABLE, 409,
            "Parent visit is not in a signable state",
        )

    rec["status"] = "SIGNED"
    rec["signed_at"] = clock.now_iso()
    rec["signer_name"] = signer_name
    db.touch(rec)
    return response.object_response(serializers.agreement(rec), 200)


# =============================================================================
# DeliveryLog
# =============================================================================
@app.route("/deliveries", methods=["POST"])
def create_delivery():
    _, role = auth()
    middleware.require_role(role, ["LobbyAttendant"])
    body = V.get_json_body()
    host_id = V.require_str(body, "host_id")
    carrier = V.require_enum(body, "carrier", CARRIERS)
    fees = body.get("parcel_fees_cents")
    if not isinstance(fees, list) or len(fees) == 0:
        raise V.invalid("parcel_fees_cents must be a non-empty array of non-negative integers")
    for f in fees:
        if isinstance(f, bool) or not isinstance(f, int) or f < 0:
            raise V.invalid("each parcel_fees_cents element must be a non-negative integer")
    fk_get(db.hosts, host_id, "Host")
    invoice = calc.delivery_handling_invoice(fees)
    rec = db.stamp_create({
        "host_id": host_id,
        "carrier": carrier,
        "parcel_fees_cents": list(fees),
        "status": "RECEIVED",
        "handling_invoice_cents": invoice,
        "picked_up_at": None,
    })
    db.deliveries[rec["id"]] = rec
    return response.object_response(serializers.delivery(rec), 201)


@app.route("/deliveries/<delivery_id>", methods=["GET"])
def get_delivery(delivery_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rec = fk_get(db.deliveries, delivery_id, "DeliveryLog")
    return response.object_response(serializers.delivery(rec), 200)


@app.route("/deliveries", methods=["GET"])
def list_deliveries():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant", "Host"])
    rows = filtered(db.deliveries, {"host_id": arg("host_id")})
    return list_response(rows, serializers.delivery)


@app.route("/deliveries/<delivery_id>/pickup", methods=["POST"])
def pickup_delivery(delivery_id):
    _, role = auth()
    middleware.require_role(role, ["LobbyAttendant", "Host"])
    rec = fk_get(db.deliveries, delivery_id, "DeliveryLog")
    if rec["status"] != "RECEIVED":
        raise errors.ApiError(
            errors.ERR_INVALID_STATE, 409,
            "Delivery is %s; pickup requires RECEIVED" % rec["status"],
        )
    rec["status"] = "PICKED_UP"
    rec["picked_up_at"] = clock.now_iso()
    db.touch(rec)
    return response.object_response(serializers.delivery(rec), 200)


# =============================================================================
# EvacuationEvent
# =============================================================================
@app.route("/evacuation-events", methods=["POST"])
def create_evacuation_event():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer"])
    body = V.get_json_body()
    floor_id = V.require_str(body, "floor_id")
    triggered_reason = V.require_enum(body, "triggered_reason", EVAC_REASONS)
    fk_get(db.floors, floor_id, "Floor")

    # Snapshot SIGNED_IN visits on this floor, ordered by sign_in_at ASC then created_at ASC.
    signed_in = [
        v for v in db.visits.values()
        if v.get("floor_id") == floor_id and v.get("status") == "SIGNED_IN"
    ]
    signed_in.sort(key=lambda v: (v.get("sign_in_at"), v.get("created_at")))
    roster_ids = [v["id"] for v in signed_in]

    rec = db.stamp_create({
        "floor_id": floor_id,
        "triggered_reason": triggered_reason,
        "roster_visit_ids": roster_ids,
        "roster_head_count": len(roster_ids),
    })
    db.evacuation_events[rec["id"]] = rec
    return response.object_response(serializers.evacuation_event(rec), 201)


@app.route("/evacuation-events/<event_id>", methods=["GET"])
def get_evacuation_event(event_id):
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant"])
    rec = fk_get(db.evacuation_events, event_id, "EvacuationEvent")
    return response.object_response(serializers.evacuation_event(rec), 200)


@app.route("/evacuation-events", methods=["GET"])
def list_evacuation_events():
    _, role = auth()
    middleware.require_role(role, ["SecurityOfficer", "LobbyAttendant"])
    rows = filtered(db.evacuation_events, {"floor_id": arg("floor_id")})
    return list_response(rows, serializers.evacuation_event)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
