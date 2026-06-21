"""Nightclub & Bar Service API — entry point, error handlers, and all routes.

In-memory storage only; the store starts EMPTY on every process boot. No
seeding, no preload. Every entity any test needs is constructed via the
declared API surface.

Validation priority order (PRD §3.10), applied per request:
  1 auth (401)  2 role (403)  3 path existence (404 NOT_FOUND)
  4 body FK (404 FK_NOT_FOUND)  5 request shape (400)  6 OCC (412)
  7 venue-closed (409)  8 invalid state (409)  9+ business gates
"""
import os

from flask import Flask, request

import errors
import validators as V
from errors import ApiError
from response import success_object, success_array, error_response
from middleware import get_auth, require_roles
from clock import clock
from db import db
import domain as D


app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Lookup helpers (priority 3 path existence -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_venue_or_404(vid):
    v = db.venues.get(vid)
    if v is None:
        raise errors.not_found("Venue not found")
    return v


def get_or_404(collection, rid, label):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found(f"{label} not found")
    return rec


def sorted_by_creation(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def venue_not_closed(venue):
    """Priority 7: venue-closed gate -> ERR_VENUE_CLOSED."""
    if venue["posture"] == "CLOSED":
        raise errors.venue_closed()


# ===========================================================================
# VENUE
# ===========================================================================
@app.route("/nightclub/venues", methods=["POST"])
def create_venue():
    role, _ = get_auth()
    require_roles(role, {"PlatformAdmin"})
    body = V.get_body(request)

    name = V.as_string(V.require(body, "name"), "name")
    fire_code_capacity = V.as_int(V.require(body, "fire_code_capacity"), "fire_code_capacity", minimum=1)
    closing_time_utc = V.parse_iso_field(V.require(body, "closing_time_utc"), "closing_time_utc")
    last_call_offset_minutes = V.opt_int(body, "last_call_offset_minutes", default=30, minimum=0)
    cover_base_cents = V.opt_int(body, "cover_base_cents", default=2000, minimum=0)
    cover_surge_pct = V.opt_number(body, "cover_surge_pct", default=0.5, lo=0, hi=2)
    max_alcohol_strikes = V.opt_int(body, "max_alcohol_strikes", default=4, minimum=1)

    v = {
        "id": db.new_id(),
        "name": name,
        "fire_code_capacity": fire_code_capacity,
        "last_call_offset_minutes": last_call_offset_minutes,
        "closing_time_utc": closing_time_utc,
        "cover_base_cents": cover_base_cents,
        "cover_surge_pct": cover_surge_pct,
        "max_alcohol_strikes": max_alcohol_strikes,
        "posture": "OPEN",
    }
    D._stamp_create(v)
    # A freshly created venue's posture is OPEN unless the clock already places
    # it past last-call/closing (defensive; default clock is well before any
    # realistic closing time).
    D.recompute_posture(v)
    db.venues[v["id"]] = v
    return success_object(D.serialize_venue(v), status=201)


@app.route("/nightclub/venues/<vid>", methods=["GET"])
def read_venue(vid):
    role, _ = get_auth()
    require_roles(role, {"PlatformAdmin", "FloorManager", "DoorHost", "Bartender", "SecurityOfficer"})
    v = get_venue_or_404(vid)
    return success_object(D.serialize_venue(v))


@app.route("/nightclub/venues", methods=["GET"])
def list_venues():
    role, _ = get_auth()
    require_roles(role, {"PlatformAdmin", "FloorManager", "DoorHost", "Bartender", "SecurityOfficer"})
    rows = sorted_by_creation(db.venues.values())
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_venue(v) for v in page], limit, offset, total)


@app.route("/nightclub/venues/<vid>/close", methods=["POST"])
def close_venue_route(vid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    v = get_venue_or_404(vid)
    venue_not_closed(v)
    D.close_venue(v)
    return success_object(D.serialize_venue(v))


# ===========================================================================
# PROMOTER
# ===========================================================================
@app.route("/nightclub/promoters", methods=["POST"])
def create_promoter():
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    body = V.get_body(request)

    # FK existence (priority 4) before shape of the remaining fields.
    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    name = V.as_string(V.require(body, "name"), "name")
    comp_budget_cents = V.as_int(V.require(body, "comp_budget_cents"), "comp_budget_cents", minimum=0)
    guest_discount_pct = V.opt_number(body, "guest_discount_pct", default=0.5, lo=0, hi=1)

    venue_not_closed(venue)

    p = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "name": name,
        "comp_budget_cents": comp_budget_cents,
        "guest_discount_pct": guest_discount_pct,
    }
    D._stamp_create(p)
    db.promoters[p["id"]] = p
    return success_object(D.serialize_promoter(p), status=201)


@app.route("/nightclub/promoters", methods=["GET"])
def list_promoters():
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin", "DoorHost"})
    rows = list(db.promoters.values())
    vid = request.args.get("venue_id")
    if vid is not None:
        rows = [p for p in rows if p["venue_id"] == vid]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_promoter(p) for p in page], limit, offset, total)


@app.route("/nightclub/promoters/<pid>", methods=["GET"])
def read_promoter(pid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin", "DoorHost"})
    p = get_or_404(db.promoters, pid, "Promoter")
    return success_object(D.serialize_promoter(p))


# ===========================================================================
# GUEST LIST
# ===========================================================================
@app.route("/nightclub/guest-list", methods=["POST"])
def create_guest_list():
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "FloorManager", "PlatformAdmin"})
    body = V.get_body(request)

    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    promoter_id = V.opt_string(body, "promoter_id")
    promoter = None
    if promoter_id is not None:
        promoter = db.promoters.get(promoter_id)
        if promoter is None or promoter["venue_id"] != venue_id:
            raise errors.fk_not_found("promoter_id does not reference a promoter in this venue")

    guest_name = V.as_string(V.require(body, "guest_name"), "guest_name")
    party_size = V.as_int(V.require(body, "party_size"), "party_size", minimum=1)
    comp_value_cents = V.opt_int(body, "comp_value_cents", default=0, minimum=0)

    venue_not_closed(venue)

    # Comp budget gate (priority 16) — only for promoter-backed entries.
    if promoter is not None:
        committed = D.promoter_comp_committed(promoter)
        if committed + comp_value_cents > promoter["comp_budget_cents"]:
            raise errors.comp_budget_exceeded()

    g = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "promoter_id": promoter_id,
        "guest_name": guest_name,
        "party_size": party_size,
        "comp_value_cents": comp_value_cents,
        "status": "CONFIRMED",
        "redeemed_entry_id": None,
    }
    D._stamp_create(g)
    db.guest_list[g["id"]] = g
    return success_object(D.serialize_guest_list(g), status=201)


@app.route("/nightclub/guest-list", methods=["GET"])
def list_guest_list():
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "FloorManager", "PlatformAdmin"})
    rows = list(db.guest_list.values())
    vid = request.args.get("venue_id")
    pid = request.args.get("promoter_id")
    rid = request.args.get("redeemed_entry_id")
    if vid is not None:
        rows = [g for g in rows if g["venue_id"] == vid]
    if pid is not None:
        rows = [g for g in rows if g.get("promoter_id") == pid]
    if rid is not None:
        rows = [g for g in rows if g.get("redeemed_entry_id") == rid]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_guest_list(g) for g in page], limit, offset, total)


@app.route("/nightclub/guest-list/<gid>", methods=["GET"])
def read_guest_list(gid):
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "FloorManager", "PlatformAdmin"})
    g = get_or_404(db.guest_list, gid, "Guest-list entry")
    return success_object(D.serialize_guest_list(g))


@app.route("/nightclub/guest-list/<gid>/cancel", methods=["POST"])
def cancel_guest_list(gid):
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "FloorManager", "PlatformAdmin"})
    g = get_or_404(db.guest_list, gid, "Guest-list entry")
    venue = db.venues.get(g["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if g["status"] != "CONFIRMED":
        raise errors.invalid_state("Only a CONFIRMED guest-list entry can be cancelled")
    g["status"] = "CANCELLED"
    D.touch(g)
    return success_object(D.serialize_guest_list(g))


# ===========================================================================
# ID CHECKS
# ===========================================================================
@app.route("/nightclub/id-checks", methods=["POST"])
def create_id_check():
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "SecurityOfficer", "PlatformAdmin"})
    body = V.get_body(request)

    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    patron_name = V.as_string(V.require(body, "patron_name"), "patron_name")
    date_of_birth = V.parse_date_field(V.require(body, "date_of_birth"), "date_of_birth")
    id_expiry = V.parse_date_field(V.require(body, "id_expiry"), "id_expiry")

    venue_not_closed(venue)

    age = D.compute_age_years(date_of_birth)
    outcome, reason = D.compute_id_check_outcome(id_expiry, age)

    c = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "patron_name": patron_name,
        "date_of_birth": date_of_birth,
        "id_expiry": id_expiry,
        "computed_age_years": age,
        "outcome": outcome,
        "refusal_reason": reason,
    }
    D._stamp_create(c)
    db.id_checks[c["id"]] = c
    return success_object(D.serialize_id_check(c), status=201)


@app.route("/nightclub/id-checks", methods=["GET"])
def list_id_checks():
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "SecurityOfficer", "FloorManager", "PlatformAdmin"})
    rows = list(db.id_checks.values())
    vid = request.args.get("venue_id")
    outcome = request.args.get("outcome")
    if vid is not None:
        rows = [c for c in rows if c["venue_id"] == vid]
    if outcome is not None:
        rows = [c for c in rows if c["outcome"] == outcome]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_id_check(c) for c in page], limit, offset, total)


@app.route("/nightclub/id-checks/<cid>", methods=["GET"])
def read_id_check(cid):
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "SecurityOfficer", "FloorManager", "PlatformAdmin"})
    c = get_or_404(db.id_checks, cid, "ID check")
    return success_object(D.serialize_id_check(c))


# ===========================================================================
# ENTRIES (admission / occupancy)
# ===========================================================================
@app.route("/nightclub/entries", methods=["POST"])
def create_entry():
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "PlatformAdmin"})
    body = V.get_body(request)

    # Priority 4: body FK existence (venue_id, id_check_id, optional guest_list_entry_id).
    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    id_check_id = V.as_string(V.require(body, "id_check_id"), "id_check_id")
    id_check = db.id_checks.get(id_check_id)
    if id_check is None or id_check["venue_id"] != venue_id:
        raise errors.fk_not_found("id_check_id does not reference an ID check in this venue")

    guest_list_entry_id = V.opt_string(body, "guest_list_entry_id")
    gle = None
    if guest_list_entry_id is not None:
        gle = db.guest_list.get(guest_list_entry_id)
        if gle is None or gle["venue_id"] != venue_id:
            raise errors.fk_not_found("guest_list_entry_id does not reference a guest-list entry in this venue")

    # Priority 5: request shape — expected_venue_version required and well-typed.
    expected_version = V.as_int(V.require(body, "expected_venue_version"), "expected_venue_version", minimum=0)

    # Priority 6: OCC.
    if expected_version != venue["version"]:
        raise errors.stale_venue_version()

    # Priority 7: venue-closed gate.
    venue_not_closed(venue)

    # Priority 9: ID-check gate.
    if id_check["outcome"] != "PASS":
        raise errors.id_check_not_passed()

    # Priority 14: re-entry gate — this id_check must not back a live INSIDE entry.
    for e in db.entries.values():
        if e["id_check_id"] == id_check_id and e["status"] == "INSIDE":
            raise errors.patron_already_inside()

    # Priority 15: capacity gate.
    if D.occupancy_count(venue) >= venue["fire_code_capacity"]:
        raise errors.at_capacity()

    cover_paid = D.compute_cover(venue, gle)

    e = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "guest_list_entry_id": guest_list_entry_id,
        "id_check_id": id_check_id,
        "cover_paid_cents": cover_paid,
        "admitted_at_utc": clock.now_iso(),
        "exited_at_utc": None,
        "status": "INSIDE",
    }
    D._stamp_create(e)
    db.entries[e["id"]] = e

    # Redeem the guest-list entry.
    if gle is not None:
        gle["status"] = "REDEEMED"
        gle["redeemed_entry_id"] = e["id"]
        D.touch(gle)

    # Recompute posture and bump venue version (this admission is a mutation).
    D.recompute_posture(venue)
    D.touch(venue)

    return success_object(D.serialize_entry(e), status=201)


@app.route("/nightclub/entries", methods=["GET"])
def list_entries():
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "FloorManager", "SecurityOfficer", "PlatformAdmin"})
    rows = list(db.entries.values())
    vid = request.args.get("venue_id")
    status = request.args.get("status")
    gle_id = request.args.get("guest_list_entry_id")
    idc = request.args.get("id_check_id")
    if vid is not None:
        rows = [e for e in rows if e["venue_id"] == vid]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    if gle_id is not None:
        rows = [e for e in rows if e.get("guest_list_entry_id") == gle_id]
    if idc is not None:
        rows = [e for e in rows if e["id_check_id"] == idc]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_entry(e) for e in page], limit, offset, total)


@app.route("/nightclub/entries/<eid>", methods=["GET"])
def read_entry(eid):
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "FloorManager", "SecurityOfficer", "PlatformAdmin"})
    e = get_or_404(db.entries, eid, "Entry")
    return success_object(D.serialize_entry(e))


@app.route("/nightclub/entries/<eid>/exit", methods=["POST"])
def exit_entry_route(eid):
    role, _ = get_auth()
    require_roles(role, {"DoorHost", "SecurityOfficer", "PlatformAdmin"})
    e = get_or_404(db.entries, eid, "Entry")
    venue = db.venues.get(e["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if e["status"] != "INSIDE":
        raise errors.invalid_state("Only an INSIDE entry can be exited")
    D.exit_entry(e, new_status="EXITED")
    return success_object(D.serialize_entry(e))


# ===========================================================================
# RESERVATIONS
# ===========================================================================
@app.route("/nightclub/reservations", methods=["POST"])
def create_reservation():
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    body = V.get_body(request)

    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    table_label = V.as_string(V.require(body, "table_label"), "table_label")
    party_size = V.as_int(V.require(body, "party_size"), "party_size", minimum=1)
    window_start_utc = V.parse_iso_field(V.require(body, "window_start_utc"), "window_start_utc")
    window_end_utc = V.parse_iso_field(V.require(body, "window_end_utc"), "window_end_utc")
    spend_minimum_cents = V.as_int(V.require(body, "spend_minimum_cents"), "spend_minimum_cents", minimum=0)
    expected_version = V.as_int(V.require(body, "expected_venue_version"), "expected_venue_version", minimum=0)
    deposit_cents = V.opt_int(body, "deposit_cents", default=0, minimum=0)

    # Priority 6: OCC.
    if expected_version != venue["version"]:
        raise errors.stale_venue_version()

    # Priority 7: venue-closed gate.
    venue_not_closed(venue)

    # Priority 12: window_end must be strictly after window_start at booking.
    from clock import parse_iso
    ws = parse_iso(window_start_utc)
    we = parse_iso(window_end_utc)
    if not (we > ws):
        raise errors.reservation_window("window_end_utc must be strictly after window_start_utc")

    # Priority 13: table double-book — overlap with a non-terminal reservation on
    # the same table_label (half-open intervals; touching endpoints do not conflict).
    for r in db.reservations.values():
        if r["venue_id"] != venue_id or r["table_label"] != table_label:
            continue
        if r["status"] not in ("BOOKED", "SEATED"):
            continue
        rs = parse_iso(r["window_start_utc"])
        re_ = parse_iso(r["window_end_utc"])
        if ws < re_ and rs < we:  # half-open overlap
            raise errors.table_double_booked()

    r = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "table_label": table_label,
        "party_size": party_size,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "spend_minimum_cents": spend_minimum_cents,
        "deposit_cents": deposit_cents,
        "status": "BOOKED",
        "minimum_shortfall_cents": None,
    }
    D._stamp_create(r)
    db.reservations[r["id"]] = r

    # The booking is a venue mutation: bump venue version.
    D.touch(venue)

    return success_object(D.serialize_reservation(r), status=201)


@app.route("/nightclub/reservations", methods=["GET"])
def list_reservations():
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "DoorHost", "PlatformAdmin"})
    rows = list(db.reservations.values())
    vid = request.args.get("venue_id")
    status = request.args.get("status")
    table_label = request.args.get("table_label")
    if vid is not None:
        rows = [r for r in rows if r["venue_id"] == vid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if table_label is not None:
        rows = [r for r in rows if r["table_label"] == table_label]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_reservation(r) for r in page], limit, offset, total)


@app.route("/nightclub/reservations/<rid>", methods=["GET"])
def read_reservation(rid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "DoorHost", "PlatformAdmin"})
    r = get_or_404(db.reservations, rid, "Reservation")
    return success_object(D.serialize_reservation(r))


@app.route("/nightclub/reservations/<rid>/seat", methods=["POST"])
def seat_reservation(rid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    r = get_or_404(db.reservations, rid, "Reservation")
    venue = db.venues.get(r["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if r["status"] != "BOOKED":
        raise errors.invalid_state("Only a BOOKED reservation can be seated")
    # Posture must be OPEN or AT_CAPACITY (not LAST_CALL, not CLOSED).
    if venue is None or venue["posture"] not in ("OPEN", "AT_CAPACITY"):
        # CLOSED is already caught above; LAST_CALL falls through to window/state.
        raise errors.invalid_state("Seating not permitted in current venue posture")
    # Clock must fall within [window_start, window_end).
    from clock import parse_iso
    now = clock.now()
    ws = parse_iso(r["window_start_utc"])
    we = parse_iso(r["window_end_utc"])
    if not (ws <= now < we):
        raise errors.reservation_window("Seating only permitted within the reservation window")
    r["status"] = "SEATED"
    D.touch(r)
    return success_object(D.serialize_reservation(r))


@app.route("/nightclub/reservations/<rid>/no-show", methods=["POST"])
def no_show_reservation(rid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    r = get_or_404(db.reservations, rid, "Reservation")
    venue = db.venues.get(r["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if r["status"] != "BOOKED":
        raise errors.invalid_state("Only a BOOKED reservation can be marked no-show")
    from clock import parse_iso
    if clock.now() < parse_iso(r["window_end_utc"]):
        raise errors.reservation_window("No-show only permitted once the window has lapsed")
    # Deposit forfeited (retained as revenue, not refunded). No field mutated
    # beyond status; the deposit simply is not returned.
    r["status"] = "NO_SHOW"
    D.touch(r)
    return success_object(D.serialize_reservation(r))


@app.route("/nightclub/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    r = get_or_404(db.reservations, rid, "Reservation")
    venue = db.venues.get(r["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if r["status"] != "BOOKED":
        raise errors.invalid_state("Only a BOOKED reservation can be cancelled")
    from clock import parse_iso
    if clock.now() >= parse_iso(r["window_start_utc"]):
        raise errors.reservation_window("Cancel only permitted strictly before the window opens")
    # Deposit refunded in full — no retained forfeiture.
    r["status"] = "CANCELLED"
    D.touch(r)
    return success_object(D.serialize_reservation(r))


@app.route("/nightclub/reservations/<rid>/settle", methods=["POST"])
def settle_reservation_route(rid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    r = get_or_404(db.reservations, rid, "Reservation")
    venue = db.venues.get(r["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if r["status"] != "SEATED":
        raise errors.invalid_state("Only a SEATED reservation can be settled")
    D.settle_reservation(r, forced=False)
    return success_object(D.serialize_reservation(r))


# ===========================================================================
# TABS (bar POS)
# ===========================================================================
@app.route("/nightclub/tabs", methods=["POST"])
def create_tab():
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    body = V.get_body(request)

    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    reservation_id = V.opt_string(body, "reservation_id")
    if reservation_id is not None:
        res = db.reservations.get(reservation_id)
        if res is None or res["venue_id"] != venue_id:
            raise errors.fk_not_found("reservation_id does not reference a reservation in this venue")

    patron_name = V.as_string(V.require(body, "patron_name"), "patron_name")
    preauth_cents = V.as_int(V.require(body, "preauth_cents"), "preauth_cents", minimum=0)
    gratuity_pct = V.opt_number(body, "gratuity_pct", default=0.2, lo=0, hi=1)

    # Priority 7: venue-closed gate.
    venue_not_closed(venue)
    # A new tab may not be opened while posture == LAST_CALL (PRD §3.7).
    if venue["posture"] == "LAST_CALL":
        raise errors.invalid_state("Cannot open a new tab during LAST_CALL")

    t = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "reservation_id": reservation_id,
        "patron_name": patron_name,
        "preauth_cents": preauth_cents,
        "gratuity_pct": gratuity_pct,
        "final_total_cents": 0,
        "bac_strikes": 0,
        "status": "OPEN",
    }
    D._stamp_create(t)
    db.tabs[t["id"]] = t
    # Opening a tab recomputes the venue's tabs_open_count (computed at read).
    return success_object(D.serialize_tab(t), status=201)


@app.route("/nightclub/tabs", methods=["GET"])
def list_tabs():
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    rows = list(db.tabs.values())
    vid = request.args.get("venue_id")
    status = request.args.get("status")
    res_id = request.args.get("reservation_id")
    if vid is not None:
        rows = [t for t in rows if t["venue_id"] == vid]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if res_id is not None:
        rows = [t for t in rows if t.get("reservation_id") == res_id]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_tab(t) for t in page], limit, offset, total)


@app.route("/nightclub/tabs/<tid>", methods=["GET"])
def read_tab(tid):
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    t = get_or_404(db.tabs, tid, "Tab")
    return success_object(D.serialize_tab(t))


@app.route("/nightclub/tabs/<tid>/items", methods=["POST"])
def add_tab_item(tid):
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    t = get_or_404(db.tabs, tid, "Tab")
    body = V.get_body(request)

    name = V.as_string(V.require(body, "name"), "name")
    category = V.as_enum(V.require(body, "category"), "category", {"ALCOHOL", "FOOD", "NA_BEVERAGE", "SERVICE"})
    qty = V.as_int(V.require(body, "qty"), "qty", minimum=1)
    unit_price_cents = V.as_int(V.require(body, "unit_price_cents"), "unit_price_cents", minimum=0)

    venue = db.venues.get(t["venue_id"])
    if venue is not None:
        venue_not_closed(venue)

    # Priority 8: tab state must admit item adds.
    if t["status"] not in ("OPEN", "RUNNING"):
        raise errors.invalid_state("Items can only be added to an OPEN or RUNNING tab")

    if category == "ALCOHOL":
        # Priority 10: last-call gate.
        if venue is not None and venue["posture"] == "LAST_CALL":
            raise errors.last_call_no_alcohol()
        # Priority 11: over-service gate.
        if venue is not None and t["bac_strikes"] >= venue["max_alcohol_strikes"]:
            raise errors.over_service_refused()

    item = D.create_tab_item(t, name, category, qty, unit_price_cents)
    return success_object(D.serialize_tab_item(item), status=201)


@app.route("/nightclub/tabs/<tid>/items", methods=["GET"])
def list_tab_items(tid):
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    get_or_404(db.tabs, tid, "Tab")
    rows = [it for it in db.tab_items.values() if it["tab_id"] == tid]
    rows = sorted(rows, key=lambda it: (it["created_at"], it["_seq"]))
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_tab_item(it) for it in page], limit, offset, total)


@app.route("/nightclub/tabs/<tid>/items/<itemid>/void", methods=["POST"])
def void_tab_item(tid, itemid):
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    # Path resolution left-to-right: tab first, then item.
    t = get_or_404(db.tabs, tid, "Tab")
    item = db.tab_items.get(itemid)
    if item is None or item["tab_id"] != tid:
        raise errors.not_found("Tab item not found")

    venue = db.venues.get(t["venue_id"])
    if venue is not None:
        venue_not_closed(venue)

    if t["status"] not in ("OPEN", "RUNNING"):
        raise errors.invalid_state("Items can only be voided on an OPEN or RUNNING tab")
    if item["voided"]:
        raise errors.invalid_state("Item is already voided")

    item["voided"] = True
    if item["category"] == "ALCOHOL" and t["bac_strikes"] > 0:
        t["bac_strikes"] -= 1

    # If zero non-voided items remain, revert RUNNING -> OPEN and reset strikes.
    remaining = [
        it for it in db.tab_items.values()
        if it["tab_id"] == tid and not it["voided"]
    ]
    if not remaining:
        t["status"] = "OPEN"
        t["bac_strikes"] = 0

    D.touch(t)
    return success_object(D.serialize_tab_item(item))


@app.route("/nightclub/tabs/<tid>/settle", methods=["POST"])
def settle_tab_route(tid):
    role, _ = get_auth()
    require_roles(role, {"Bartender", "FloorManager", "PlatformAdmin"})
    t = get_or_404(db.tabs, tid, "Tab")
    venue = db.venues.get(t["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if t["status"] not in ("OPEN", "RUNNING"):
        raise errors.invalid_state("Only an OPEN or RUNNING tab can be settled")
    D.settle_tab(t, forced=False)
    return success_object(D.serialize_tab(t))


@app.route("/nightclub/tabs/<tid>/void", methods=["POST"])
def void_tab_route(tid):
    role, _ = get_auth()
    require_roles(role, {"FloorManager", "PlatformAdmin"})
    t = get_or_404(db.tabs, tid, "Tab")
    venue = db.venues.get(t["venue_id"])
    if venue is not None:
        venue_not_closed(venue)
    if t["status"] not in ("OPEN", "RUNNING"):
        raise errors.invalid_state("Only an OPEN or RUNNING tab can be voided")
    if D.running_subtotal(t) != 0:
        raise errors.tab_not_empty()
    t["status"] = "VOIDED"
    D.touch(t)
    return success_object(D.serialize_tab(t))


# ===========================================================================
# SECURITY INCIDENTS
# ===========================================================================
@app.route("/nightclub/incidents", methods=["POST"])
def create_incident():
    role, _ = get_auth()
    require_roles(role, {"SecurityOfficer", "FloorManager", "PlatformAdmin"})
    body = V.get_body(request)

    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")

    subject_entry_id = V.opt_string(body, "subject_entry_id")
    subject = None
    if subject_entry_id is not None:
        subject = db.entries.get(subject_entry_id)
        if subject is None or subject["venue_id"] != venue_id:
            raise errors.fk_not_found("subject_entry_id does not reference an entry in this venue")

    severity = V.as_enum(V.require(body, "severity"), "severity", {"MINOR", "SERIOUS", "CRITICAL"})
    action = V.as_enum(V.require(body, "action"), "action", {"WARNING", "EJECTION", "REFUSAL_SERVICE"})
    narrative = V.as_string(V.require(body, "narrative"), "narrative")

    venue_not_closed(venue)

    i = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "subject_entry_id": subject_entry_id,
        "severity": severity,
        "action": action,
        "narrative": narrative,
        "logged_at_utc": clock.now_iso(),
    }
    D._stamp_create(i)
    db.incidents[i["id"]] = i

    # EJECTION cascade: if action is EJECTION and the subject entry is INSIDE,
    # move it INSIDE -> EJECTED (stamp exit, decrement occupancy, recompute posture).
    if action == "EJECTION" and subject is not None and subject["status"] == "INSIDE":
        D.exit_entry(subject, new_status="EJECTED")

    return success_object(D.serialize_incident(i), status=201)


@app.route("/nightclub/incidents", methods=["GET"])
def list_incidents():
    role, _ = get_auth()
    require_roles(role, {"SecurityOfficer", "FloorManager", "PlatformAdmin"})
    rows = list(db.incidents.values())
    vid = request.args.get("venue_id")
    subj = request.args.get("subject_entry_id")
    severity = request.args.get("severity")
    if vid is not None:
        rows = [i for i in rows if i["venue_id"] == vid]
    if subj is not None:
        rows = [i for i in rows if i.get("subject_entry_id") == subj]
    if severity is not None:
        rows = [i for i in rows if i["severity"] == severity]
    rows = sorted_by_creation(rows)
    page, limit, offset, total = V.paginate(request, rows)
    return success_array([D.serialize_incident(i) for i in page], limit, offset, total)


@app.route("/nightclub/incidents/<iid>", methods=["GET"])
def read_incident(iid):
    role, _ = get_auth()
    require_roles(role, {"SecurityOfficer", "FloorManager", "PlatformAdmin"})
    i = get_or_404(db.incidents, iid, "Security incident")
    return success_object(D.serialize_incident(i))


# ===========================================================================
# TEST-DRIVING: logical clock & occupancy injection
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = get_auth()
    require_roles(role, {"PlatformAdmin"})
    body = V.get_body(request)
    to_iso = V.parse_iso_field(V.require(body, "to_iso8601"), "to_iso8601")
    clock.set(to_iso)
    # Recompute every venue's posture and run any due close cascade.
    D.advance_clock_recompute()
    return success_object({})


@app.route("/_inject/occupancy", methods=["POST"])
def inject_occupancy():
    role, _ = get_auth()
    require_roles(role, {"PlatformAdmin"})
    body = V.get_body(request)

    venue_id = V.as_string(V.require(body, "venue_id"), "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.fk_not_found("venue_id does not reference an existing venue")
    target_inside = V.as_int(V.require(body, "target_inside"), "target_inside", minimum=0)

    venue_not_closed(venue)

    current = D.occupancy_count(venue)
    if target_inside > current:
        for _ in range(target_inside - current):
            # Auto-generate a PASS IdCheck.
            c = {
                "id": db.new_id(),
                "venue_id": venue_id,
                "patron_name": "synthetic",
                "date_of_birth": "1990-01-01",
                "id_expiry": "2099-01-01",
                "computed_age_years": D.compute_age_years("1990-01-01"),
                "outcome": "PASS",
                "refusal_reason": None,
            }
            D._stamp_create(c)
            db.id_checks[c["id"]] = c
            # Auto-generate an INSIDE Entry.
            e = {
                "id": db.new_id(),
                "venue_id": venue_id,
                "guest_list_entry_id": None,
                "id_check_id": c["id"],
                "cover_paid_cents": 0,
                "admitted_at_utc": clock.now_iso(),
                "exited_at_utc": None,
                "status": "INSIDE",
            }
            D._stamp_create(e)
            db.entries[e["id"]] = e
    elif target_inside < current:
        # Exit synthetic/most-recent INSIDE entries down to the target.
        inside = [e for e in db.entries.values() if e["venue_id"] == venue_id and e["status"] == "INSIDE"]
        inside = sorted(inside, key=lambda e: (e["created_at"], e["_seq"]), reverse=True)
        for e in inside[: current - target_inside]:
            e["status"] = "EXITED"
            e["exited_at_utc"] = clock.now_iso()
            D.touch(e)

    D.recompute_posture(venue)
    D.touch(venue)
    return success_object(D.serialize_venue(venue))


# ===========================================================================
# ERROR HANDLERS
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(400)
def handle_400(err):
    return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
