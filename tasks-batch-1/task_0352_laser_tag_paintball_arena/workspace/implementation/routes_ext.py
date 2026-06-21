"""Remaining routes: bookings, waivers, equipment, rentals, add-ons,
referees, assignments, leagues, matches. Registered onto the shared app."""

from flask import request

import calc
import db
import domain
from errors import err
from middleware import require_auth, require_role, ALL_ROLES
from response import success, list_success
from serialize import serialize
from timeutil import parse_iso
from validation import (
    get_json_body,
    parse_pagination,
    require_string,
    require_int,
    optional_int,
    require_enum,
)


def _paginate(kind, collection, predicate=None):
    limit, offset = parse_pagination()
    rows = [r for r in collection.values() if (predicate is None or predicate(r))]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_success([serialize(kind, r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Cascade primitives (shared by cancel / no-show)
# ---------------------------------------------------------------------------

def _release_rental(rental, arena):
    """HELD/CHECKED_OUT -> RELEASED; unit back to AVAILABLE; held deposit leaves."""
    rental["status"] = "RELEASED"
    db.touch(rental)
    unit = db.equipment_units.get(rental["equipment_unit_id"])
    if unit is not None:
        unit["status"] = "AVAILABLE"
        db.touch(unit)
    domain.reconcile_arena(arena)


def _release_referee_for_booking(booking):
    for asg in db.referee_assignments.values():
        if asg["booking_id"] != booking["id"]:
            continue
        if asg["status"] == "ASSIGNED":
            asg["status"] = "RELEASED"
            db.touch(asg)
            ref = db.referees.get(asg["referee_id"])
            if ref is not None:
                ref["status"] = "AVAILABLE"
                db.touch(ref)


def _void_quoted_addons(booking):
    for o in db.add_on_orders.values():
        if o["booking_id"] == booking["id"] and o["status"] == "QUOTED":
            o["status"] = "VOID"
            db.touch(o)


def _cancel_cascade(booking, arena):
    """Full cancel/no-show-style cascade (PRD §3.8) for HELD/CHECKED_OUT rentals."""
    for rental in db.rentals.values():
        if rental["booking_id"] != booking["id"]:
            continue
        if rental["status"] in ("HELD", "CHECKED_OUT"):
            _release_rental(rental, arena)
    _void_quoted_addons(booking)
    _release_referee_for_booking(booking)


# ===========================================================================
# BOOKING
# ===========================================================================

def register(app):

    def _lookup_arena(arena_id):
        a = db.arenas.get(arena_id)
        if a is None:
            raise err("ERR_ARENA_NOT_FOUND", "Arena not found")
        return a

    def _lookup_field(field_id):
        f = db.fields.get(field_id)
        if f is None:
            raise err("ERR_FIELD_NOT_FOUND", "Field not found")
        return f

    def _lookup_package(package_id):
        p = db.party_packages.get(package_id)
        if p is None:
            raise err("ERR_PACKAGE_NOT_FOUND", "Package not found")
        return p

    def _lookup_booking(booking_id):
        b = db.bookings.get(booking_id)
        if b is None:
            raise err("ERR_BOOKING_NOT_FOUND", "Booking not found")
        return b

    def _lookup_equipment(unit_id):
        u = db.equipment_units.get(unit_id)
        if u is None:
            raise err("ERR_EQUIPMENT_NOT_FOUND", "Equipment unit not found")
        return u

    def _lookup_rental(rental_id):
        r = db.rentals.get(rental_id)
        if r is None:
            raise err("ERR_RENTAL_NOT_FOUND", "Rental not found")
        return r

    def _lookup_waiver(waiver_id):
        w = db.waiver_profiles.get(waiver_id)
        if w is None:
            raise err("ERR_WAIVER_NOT_FOUND", "Waiver profile not found")
        return w

    def _lookup_referee(referee_id):
        r = db.referees.get(referee_id)
        if r is None:
            raise err("ERR_REFEREE_NOT_FOUND", "Referee not found")
        return r

    def _lookup_assignment(assignment_id):
        a = db.referee_assignments.get(assignment_id)
        if a is None:
            raise err("ERR_ASSIGNMENT_NOT_FOUND", "Referee assignment not found")
        return a

    def _lookup_league(league_id):
        lg = db.leagues.get(league_id)
        if lg is None:
            raise err("ERR_LEAGUE_NOT_FOUND", "League not found")
        return lg

    def _lookup_match(match_id):
        m = db.league_matches.get(match_id)
        if m is None:
            raise err("ERR_MATCH_NOT_FOUND", "League match not found")
        return m

    def _lookup_addon(order_id):
        o = db.add_on_orders.get(order_id)
        if o is None:
            raise err("ERR_VALIDATION", "Add-on order not found")
        return o

    # --- field slot conflict check ---------------------------------------
    def _field_slot_conflict(field, new_start, new_end, exclude_booking_id=None):
        buffer_secs = field["turnaround_minutes"] * 60
        for b in db.bookings.values():
            if b["field_id"] != field["id"]:
                continue
            if exclude_booking_id is not None and b["id"] == exclude_booking_id:
                continue
            if b["status"] not in ("HELD", "CONFIRMED", "CHECKED_IN"):
                continue
            ex_start = parse_iso(b["window_start"])
            ex_end = parse_iso(b["window_end"])
            if ex_start is None or ex_end is None:
                continue
            # Two sessions must be separated by at least turnaround_minutes of
            # clear time between the end of one and the start of the next.
            # Extend each existing window by the buffer on both ends and test
            # for overlap against the new window.
            from datetime import timedelta
            buf = timedelta(seconds=buffer_secs)
            if new_start < ex_end + buf and ex_start < new_end + buf:
                return True
        return False

    # =====================================================================
    # BOOKING
    # =====================================================================

    @app.route("/bookings", methods=["POST"])
    def create_booking():
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            arena = _lookup_arena(arena_id)
            field_id = require_string(body, "field_id")
            field = _lookup_field(field_id)
            package_id = body.get("package_id")
            package = None
            if package_id is not None:
                if not isinstance(package_id, str):
                    raise err("ERR_VALIDATION", "package_id must be a string")
                package = _lookup_package(package_id)
            # shape validation (priority 4)
            booking_type = require_enum(body, "booking_type", {"RESERVATION", "WALK_IN"})
            party_size = require_int(body, "party_size", minimum=1)
            window_start_raw = require_string(body, "window_start")
            window_end_raw = require_string(body, "window_end")
            ws = parse_iso(window_start_raw)
            we = parse_iso(window_end_raw)
            if ws is None:
                raise err("ERR_VALIDATION", "window_start must be ISO 8601")
            if we is None:
                raise err("ERR_VALIDATION", "window_end must be ISO 8601")

            # state: arena/field closed (priority 5)
            if arena["status"] == "CLOSED":
                raise err("ERR_ARENA_CLOSED", "Arena is closed")
            if field["status"] == "CLOSED":
                raise err("ERR_FIELD_CLOSED", "Field is closed")

            now = parse_iso(arena["current_utc"])

            # business rules, in §1.4 priority order for POST /bookings:
            # 12 lead-time, 13 window sanity, 14 capacity, 16 package-active,
            # 10 field-slot-conflict.
            # PRD §3.2 narrates window sanity FIRST, then lead time. Follow PRD.
            if not (we > ws):
                raise err("ERR_INVALID_WINDOW", "window_end must be after window_start")

            if booking_type == "WALK_IN":
                if now is None or ws != now:
                    raise err("ERR_LEAD_TIME_VIOLATION",
                              "WALK_IN window_start must equal arena current_utc")
            else:  # RESERVATION
                from datetime import timedelta
                if now is None or ws < now + timedelta(minutes=calc.MIN_LEAD_MINUTES):
                    raise err("ERR_LEAD_TIME_VIOLATION",
                              "RESERVATION window_start must be >= current_utc + 60min")

            if party_size > field["capacity_max"]:
                raise err("ERR_CAPACITY_EXCEEDED",
                          "party_size exceeds field capacity_max")

            if package is not None:
                if not package["active"] or package["arena_id"] != arena_id:
                    raise err("ERR_PACKAGE_INACTIVE",
                              "Package inactive or belongs to a different arena")

            if _field_slot_conflict(field, ws, we):
                raise err("ERR_FIELD_SLOT_CONFLICT",
                          "Booking window conflicts with an existing booking")

            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "field_id": field_id,
                "package_id": package_id,
                "booking_type": booking_type,
                "party_size": party_size,
                "window_start": window_start_raw,
                "window_end": window_end_raw,
                "status": "HELD",
                "field_fee_cents": 0,
                "invoice_total_cents": None,
                "checked_in_count": 0,
                "minors_present": False,
                "referee_required": False,
            })
            db.bookings[rec["id"]] = rec
            domain.recompute_booking_flags(rec)
            domain.reconcile_field_headcount(field)
            db.touch(field)
            return success(serialize("booking", rec), 201)

    @app.route("/bookings/<booking_id>", methods=["GET"])
    def get_booking_route(booking_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        b = _lookup_booking(booking_id)
        return success(serialize("booking", b), 200)

    @app.route("/bookings", methods=["GET"])
    def list_bookings():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        field_id = request.args.get("field_id")
        package_id = request.args.get("package_id")

        def pred(r):
            if arena_id and r["arena_id"] != arena_id:
                return False
            if field_id and r["field_id"] != field_id:
                return False
            if package_id and r["package_id"] != package_id:
                return False
            return True

        return _paginate("booking", db.bookings, pred)

    @app.route("/bookings/<booking_id>/confirm", methods=["POST"])
    def confirm_booking(booking_id):
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        body = get_json_body()
        with db.LOCK:
            booking = _lookup_booking(booking_id)
            # shape: expected_field_version required
            expected = require_int(body, "expected_field_version")
            # state legality (priority 5)
            if booking["status"] != "HELD":
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Booking must be HELD to confirm")
            field = db.fields.get(booking["field_id"])
            arena = db.arenas.get(booking["arena_id"])
            if field["status"] != "ACTIVE":
                raise err("ERR_FIELD_CLOSED", "Field is not ACTIVE")
            if arena["status"] != "OPEN":
                raise err("ERR_ARENA_CLOSED", "Arena is not OPEN")
            # OCC (priority 6)
            if expected != field["version"]:
                raise err("ERR_STALE_FIELD_VERSION",
                          "expected_field_version does not match the field version")
            # field-slot conflict re-check at confirm (priority 10)
            ws = parse_iso(booking["window_start"])
            we = parse_iso(booking["window_end"])
            if _field_slot_conflict(field, ws, we, exclude_booking_id=booking["id"]):
                raise err("ERR_FIELD_SLOT_CONFLICT",
                          "Booking window conflicts with an existing booking")

            package = db.party_packages.get(booking["package_id"]) if booking["package_id"] else None
            booking["field_fee_cents"] = calc.field_fee_cents(booking["party_size"], package)
            booking["status"] = "CONFIRMED"
            db.touch(booking)
            # field: reserved_headcount recomputed + version incremented by 1
            domain.reconcile_field_headcount(field)
            db.touch(field)
            return success(serialize("booking", booking), 200)

    @app.route("/bookings/<booking_id>/check-in", methods=["POST"])
    def check_in_booking(booking_id):
        _, role = require_auth()
        require_role(role, {"FieldMarshal"})
        body = get_json_body()
        with db.LOCK:
            booking = _lookup_booking(booking_id)
            checked_in_count = require_int(body, "checked_in_count")
            # state legality
            if booking["status"] != "CONFIRMED":
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Booking must be CONFIRMED to check in")
            arena = db.arenas.get(booking["arena_id"])
            field = db.fields.get(booking["field_id"])
            now = parse_iso(arena["current_utc"])
            ws = parse_iso(booking["window_start"])
            we = parse_iso(booking["window_end"])
            # minor-waiver safety gate (priority 7)
            for w in db.waiver_profiles.values():
                if w["booking_id"] != booking["id"]:
                    continue
                if w["status"] == "VOID":
                    continue
                if w["is_minor"]:
                    if w["status"] != "SIGNED" or not (w.get("guardian_name") or "").strip():
                        raise err("ERR_MINOR_WAIVER_REQUIRED",
                                  "Every minor waiver must be SIGNED with a guardian")
            # referee gate (priority 8)
            if booking["referee_required"]:
                has_assigned = any(
                    a["booking_id"] == booking["id"] and a["status"] == "ASSIGNED"
                    for a in db.referee_assignments.values()
                )
                if not has_assigned:
                    raise err("ERR_REFEREE_REQUIRED",
                              "Booking requires a referee but none is assigned")
            # capacity (priority 14): 1 <= checked_in_count <= party_size
            if checked_in_count < 1 or checked_in_count > booking["party_size"]:
                raise err("ERR_CAPACITY_EXCEEDED",
                          "checked_in_count must be between 1 and party_size")
            # window check (within [start,end)). PRD §3.3 lists this as a check-in
            # precondition. Treated as a state precondition -> invalid state.
            if now is None or ws is None or we is None or not (ws <= now < we):
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Current time is not within the booking window")

            booking["checked_in_count"] = checked_in_count
            booking["status"] = "CHECKED_IN"
            db.touch(booking)
            # each HELD rental -> CHECKED_OUT; its unit -> CHECKED_OUT
            for rental in db.rentals.values():
                if rental["booking_id"] == booking["id"] and rental["status"] == "HELD":
                    rental["status"] = "CHECKED_OUT"
                    db.touch(rental)
                    unit = db.equipment_units.get(rental["equipment_unit_id"])
                    if unit is not None:
                        unit["status"] = "CHECKED_OUT"
                        db.touch(unit)
            domain.reconcile_field_headcount(field)
            db.touch(field)
            return success(serialize("booking", booking), 200)

    @app.route("/bookings/<booking_id>/complete", methods=["POST"])
    def complete_booking(booking_id):
        _, role = require_auth()
        require_role(role, {"FieldMarshal"})
        with db.LOCK:
            booking = _lookup_booking(booking_id)
            if booking["status"] != "CHECKED_IN":
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Booking must be CHECKED_IN to complete")
            # no rental still CHECKED_OUT
            for rental in db.rentals.values():
                if rental["booking_id"] == booking["id"] and rental["status"] == "CHECKED_OUT":
                    raise err("ERR_BOOKING_INVALID_STATE",
                              "All rentals must be returned before completion")
            field = db.fields.get(booking["field_id"])
            package = db.party_packages.get(booking["package_id"]) if booking["package_id"] else None
            included_ammo = package["included_ammo_balls"] if package else 0
            discount_pct = package["discount_pct"] if package else 0

            # settle each QUOTED add-on
            addon_line = 0
            for o in db.add_on_orders.values():
                if o["booking_id"] != booking["id"]:
                    continue
                if o["status"] == "QUOTED":
                    settled = calc.add_on_settled_cents(
                        o["ammo_balls"], o["co2_tanks"], o["misc_cents"],
                        included_ammo, discount_pct)
                    o["settled_total_cents"] = settled
                    o["status"] = "SETTLED"
                    db.touch(o)
                if o["status"] == "SETTLED":
                    addon_line += o["settled_total_cents"]

            # forfeit line from rentals
            forfeit_line = 0
            for rental in db.rentals.values():
                if rental["booking_id"] == booking["id"] and rental["status"] == "RETURNED":
                    forfeit_line += rental.get("deposit_forfeit_cents") or 0

            field_line = booking["field_fee_cents"]
            booking["invoice_total_cents"] = calc.booking_invoice_cents(
                field_line, addon_line, forfeit_line)
            booking["status"] = "COMPLETED"
            db.touch(booking)
            _release_referee_for_booking(booking)
            domain.reconcile_field_headcount(field)
            db.touch(field)
            return success(serialize("booking", booking), 200)

    @app.route("/bookings/<booking_id>/no-show", methods=["POST"])
    def no_show_booking(booking_id):
        _, role = require_auth()
        require_role(role, {"FieldMarshal"})
        with db.LOCK:
            booking = _lookup_booking(booking_id)
            if booking["status"] != "CONFIRMED":
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Booking must be CONFIRMED to mark no-show")
            arena = db.arenas.get(booking["arena_id"])
            field = db.fields.get(booking["field_id"])
            now = parse_iso(arena["current_utc"])
            we = parse_iso(booking["window_end"])
            if now is None or we is None or now < we:
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Current time must be at or after window_end")
            # cascade: HELD rentals released, quoted add-ons voided, referee freed
            for rental in db.rentals.values():
                if rental["booking_id"] == booking["id"] and rental["status"] == "HELD":
                    _release_rental(rental, arena)
            _void_quoted_addons(booking)
            _release_referee_for_booking(booking)
            booking["status"] = "NO_SHOW"
            db.touch(booking)
            domain.reconcile_field_headcount(field)
            db.touch(field)
            return success(serialize("booking", booking), 200)

    @app.route("/bookings/<booking_id>/cancel", methods=["POST"])
    def cancel_booking(booking_id):
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        with db.LOCK:
            booking = _lookup_booking(booking_id)
            if booking["status"] not in ("HELD", "CONFIRMED"):
                raise err("ERR_BOOKING_INVALID_STATE",
                          "Only HELD or CONFIRMED bookings can be cancelled")
            arena = db.arenas.get(booking["arena_id"])
            field = db.fields.get(booking["field_id"])
            _cancel_cascade(booking, arena)
            booking["status"] = "CANCELLED"
            db.touch(booking)
            domain.reconcile_field_headcount(field)
            db.touch(field)
            return success(serialize("booking", booking), 200)

    # =====================================================================
    # WAIVER PROFILE
    # =====================================================================

    @app.route("/waiver-profiles", methods=["POST"])
    def create_waiver():
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            arena = _lookup_arena(arena_id)
            booking_id = require_string(body, "booking_id")
            booking = _lookup_booking(booking_id)
            participant_name = require_string(body, "participant_name")
            dob_raw = require_string(body, "date_of_birth")
            if parse_iso(dob_raw) is None:
                raise err("ERR_VALIDATION", "date_of_birth must be ISO 8601")
            guardian_name = body.get("guardian_name")
            if guardian_name is not None and not isinstance(guardian_name, str):
                raise err("ERR_VALIDATION", "guardian_name must be a string")
            age_years, is_minor = domain.compute_age(dob_raw, arena["current_utc"])
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "booking_id": booking_id,
                "participant_name": participant_name,
                "date_of_birth": dob_raw,
                "age_years": age_years,
                "is_minor": is_minor,
                "guardian_name": guardian_name,
                "status": "DRAFT",
            })
            db.waiver_profiles[rec["id"]] = rec
            return success(serialize("waiver_profile", rec), 201)

    @app.route("/waiver-profiles/<waiver_id>", methods=["GET"])
    def get_waiver_route(waiver_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        w = _lookup_waiver(waiver_id)
        return success(serialize("waiver_profile", w), 200)

    @app.route("/waiver-profiles", methods=["GET"])
    def list_waivers():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        booking_id = request.args.get("booking_id")

        def pred(r):
            if arena_id and r["arena_id"] != arena_id:
                return False
            if booking_id and r["booking_id"] != booking_id:
                return False
            return True

        return _paginate("waiver_profile", db.waiver_profiles, pred)

    @app.route("/waiver-profiles/<waiver_id>/sign", methods=["POST"])
    def sign_waiver(waiver_id):
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        with db.LOCK:
            w = _lookup_waiver(waiver_id)
            if w["status"] != "DRAFT":
                raise err("ERR_WAIVER_INVALID_STATE", "Waiver must be DRAFT to sign")
            booking = db.bookings.get(w["booking_id"])
            if booking is None or booking["status"] not in ("HELD", "CONFIRMED"):
                raise err("ERR_WAIVER_INVALID_STATE",
                          "Parent booking must be HELD or CONFIRMED")
            # minor-guardian rule (priority 7)
            if w["is_minor"] and not (w.get("guardian_name") or "").strip():
                raise err("ERR_MINOR_WAIVER_REQUIRED",
                          "A minor's waiver requires a guardian_name")
            w["status"] = "SIGNED"
            db.touch(w)
            domain.recompute_booking_flags(booking)
            return success(serialize("waiver_profile", w), 200)

    @app.route("/waiver-profiles/<waiver_id>/void", methods=["POST"])
    def void_waiver(waiver_id):
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        with db.LOCK:
            w = _lookup_waiver(waiver_id)
            if w["status"] not in ("DRAFT", "SIGNED"):
                raise err("ERR_WAIVER_INVALID_STATE",
                          "Waiver must be DRAFT or SIGNED to void")
            w["status"] = "VOID"
            db.touch(w)
            booking = db.bookings.get(w["booking_id"])
            if booking is not None:
                domain.recompute_booking_flags(booking)
            return success(serialize("waiver_profile", w), 200)

    # =====================================================================
    # EQUIPMENT UNIT
    # =====================================================================

    @app.route("/equipment-units", methods=["POST"])
    def create_equipment():
        _, role = require_auth()
        require_role(role, {"ArenaManager"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            arena = _lookup_arena(arena_id)
            unit_type = require_enum(body, "unit_type", {"MARKER", "VEST"})
            asset_tag = require_string(body, "asset_tag")
            deposit_cents = require_int(body, "deposit_cents", minimum=0)
            condition_grade = body.get("condition_grade")
            if condition_grade is None:
                condition_grade = "A"
            else:
                condition_grade = require_enum(body, "condition_grade", {"A", "B", "C"})
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "unit_type": unit_type,
                "asset_tag": asset_tag,
                "deposit_cents": deposit_cents,
                "condition_grade": condition_grade,
                "status": "AVAILABLE",
            })
            db.equipment_units[rec["id"]] = rec
            domain.reconcile_arena(arena)
            return success(serialize("equipment_unit", rec), 201)

    @app.route("/equipment-units/<unit_id>", methods=["GET"])
    def get_equipment_route(unit_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        u = _lookup_equipment(unit_id)
        return success(serialize("equipment_unit", u), 200)

    @app.route("/equipment-units", methods=["GET"])
    def list_equipment():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        pred = (lambda r: r["arena_id"] == arena_id) if arena_id else None
        return _paginate("equipment_unit", db.equipment_units, pred)

    @app.route("/equipment-units/<unit_id>/restore", methods=["POST"])
    def restore_equipment(unit_id):
        _, role = require_auth()
        require_role(role, {"ArenaManager"})
        with db.LOCK:
            u = _lookup_equipment(unit_id)
            if u["status"] != "MAINTENANCE":
                raise err("ERR_EQUIPMENT_INVALID_STATE",
                          "Unit must be in MAINTENANCE to restore")
            u["status"] = "AVAILABLE"
            db.touch(u)
            arena = db.arenas.get(u["arena_id"])
            domain.reconcile_arena(arena)
            return success(serialize("equipment_unit", u), 200)

    # =====================================================================
    # RENTAL
    # =====================================================================

    @app.route("/rentals", methods=["POST"])
    def create_rental():
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            arena = _lookup_arena(arena_id)
            booking_id = require_string(body, "booking_id")
            booking = _lookup_booking(booking_id)
            unit_id = require_string(body, "equipment_unit_id")
            unit = _lookup_equipment(unit_id)
            # arena closed (state)
            if arena["status"] == "CLOSED":
                raise err("ERR_ARENA_CLOSED", "Arena is closed")
            # equipment time conflict (priority 11) — closed interval, no buffer
            new_ws = parse_iso(booking["window_start"])
            new_we = parse_iso(booking["window_end"])
            for r in db.rentals.values():
                if r["equipment_unit_id"] != unit_id:
                    continue
                if r["status"] not in ("HELD", "CHECKED_OUT"):
                    continue
                ob = db.bookings.get(r["booking_id"])
                if ob is None:
                    continue
                o_ws = parse_iso(ob["window_start"])
                o_we = parse_iso(ob["window_end"])
                if o_ws is None or o_we is None or new_ws is None or new_we is None:
                    continue
                # closed-interval overlap: collide whenever windows touch at all
                if new_ws <= o_we and o_ws <= new_we:
                    raise err("ERR_EQUIPMENT_TIME_CONFLICT",
                              "Equipment unit already reserved for an overlapping window")
            # equipment availability (priority 15)
            if unit["status"] != "AVAILABLE" or unit["condition_grade"] not in ("A", "B"):
                raise err("ERR_EQUIPMENT_UNAVAILABLE",
                          "Unit must be AVAILABLE with condition A or B")
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "booking_id": booking_id,
                "equipment_unit_id": unit_id,
                "deposit_hold_cents": unit["deposit_cents"],
                "damage_fee_cents": 0,
                "deposit_refund_cents": None,
                "deposit_forfeit_cents": None,
                "status": "HELD",
            })
            db.rentals[rec["id"]] = rec
            unit["status"] = "RESERVED"
            db.touch(unit)
            domain.reconcile_arena(arena)
            return success(serialize("rental", rec), 201)

    @app.route("/rentals/<rental_id>", methods=["GET"])
    def get_rental_route(rental_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        r = _lookup_rental(rental_id)
        return success(serialize("rental", r), 200)

    @app.route("/rentals", methods=["GET"])
    def list_rentals():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        booking_id = request.args.get("booking_id")
        unit_id = request.args.get("equipment_unit_id")

        def pred(r):
            if arena_id and r["arena_id"] != arena_id:
                return False
            if booking_id and r["booking_id"] != booking_id:
                return False
            if unit_id and r["equipment_unit_id"] != unit_id:
                return False
            return True

        return _paginate("rental", db.rentals, pred)

    @app.route("/rentals/<rental_id>/return", methods=["POST"])
    def return_rental(rental_id):
        _, role = require_auth()
        require_role(role, {"FieldMarshal"})
        body = get_json_body()
        with db.LOCK:
            rental = _lookup_rental(rental_id)
            damage_fee = optional_int(body, "damage_fee_cents", default=0, minimum=0)
            if rental["status"] != "CHECKED_OUT":
                raise err("ERR_RENTAL_INVALID_STATE",
                          "Rental must be CHECKED_OUT to return")
            if damage_fee > rental["deposit_hold_cents"]:
                raise err("ERR_DAMAGE_FEE_EXCEEDS_DEPOSIT",
                          "damage_fee_cents exceeds the held deposit")
            refund, forfeit = calc.deposit_settlement(rental["deposit_hold_cents"], damage_fee)
            rental["damage_fee_cents"] = damage_fee
            rental["deposit_refund_cents"] = refund
            rental["deposit_forfeit_cents"] = forfeit
            rental["status"] = "RETURNED"
            db.touch(rental)
            unit = db.equipment_units.get(rental["equipment_unit_id"])
            if unit is not None:
                if damage_fee == 0:
                    unit["status"] = "AVAILABLE"
                else:
                    unit["status"] = "MAINTENANCE"
                    # downgrade condition one notch
                    grade = unit["condition_grade"]
                    unit["condition_grade"] = {"A": "B", "B": "C", "C": "C"}.get(grade, grade)
                db.touch(unit)
            arena = db.arenas.get(rental["arena_id"])
            domain.reconcile_arena(arena)
            domain.add_refund(arena, refund, forfeit)
            return success(serialize("rental", rental), 200)

    @app.route("/rentals/<rental_id>/release", methods=["POST"])
    def release_rental(rental_id):
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        with db.LOCK:
            rental = _lookup_rental(rental_id)
            if rental["status"] != "HELD":
                raise err("ERR_RENTAL_INVALID_STATE",
                          "Only a HELD rental can be released")
            arena = db.arenas.get(rental["arena_id"])
            rental["status"] = "RELEASED"
            db.touch(rental)
            unit = db.equipment_units.get(rental["equipment_unit_id"])
            if unit is not None:
                unit["status"] = "AVAILABLE"
                db.touch(unit)
            domain.reconcile_arena(arena)
            return success(serialize("rental", rental), 200)

    # =====================================================================
    # ADD-ON ORDER
    # =====================================================================

    @app.route("/add-on-orders", methods=["POST"])
    def create_addon():
        _, role = require_auth()
        require_role(role, {"FrontDesk"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            _lookup_arena(arena_id)
            booking_id = require_string(body, "booking_id")
            _lookup_booking(booking_id)
            ammo = optional_int(body, "ammo_balls", default=0, minimum=0)
            co2 = optional_int(body, "co2_tanks", default=0, minimum=0)
            misc = optional_int(body, "misc_cents", default=0, minimum=0)
            quote = calc.add_on_quote_cents(ammo, co2, misc)
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "booking_id": booking_id,
                "ammo_balls": ammo,
                "co2_tanks": co2,
                "misc_cents": misc,
                "quote_total_cents": quote,
                "settled_total_cents": None,
                "status": "QUOTED",
            })
            db.add_on_orders[rec["id"]] = rec
            return success(serialize("add_on_order", rec), 201)

    @app.route("/add-on-orders/<order_id>", methods=["GET"])
    def get_addon_route(order_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        o = _lookup_addon(order_id)
        return success(serialize("add_on_order", o), 200)

    @app.route("/add-on-orders", methods=["GET"])
    def list_addons():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        booking_id = request.args.get("booking_id")

        def pred(r):
            if arena_id and r["arena_id"] != arena_id:
                return False
            if booking_id and r["booking_id"] != booking_id:
                return False
            return True

        return _paginate("add_on_order", db.add_on_orders, pred)

    # =====================================================================
    # REFEREE
    # =====================================================================

    @app.route("/referees", methods=["POST"])
    def create_referee():
        _, role = require_auth()
        require_role(role, {"ArenaManager"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            _lookup_arena(arena_id)
            name = require_string(body, "name")
            certified = body.get("certified_paintball")
            if certified is None:
                certified = False
            elif not isinstance(certified, bool):
                raise err("ERR_VALIDATION", "certified_paintball must be a boolean")
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "name": name,
                "certified_paintball": certified,
                "status": "AVAILABLE",
            })
            db.referees[rec["id"]] = rec
            return success(serialize("referee", rec), 201)

    @app.route("/referees/<referee_id>", methods=["GET"])
    def get_referee_route(referee_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        r = _lookup_referee(referee_id)
        return success(serialize("referee", r), 200)

    @app.route("/referees", methods=["GET"])
    def list_referees():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        pred = (lambda r: r["arena_id"] == arena_id) if arena_id else None
        return _paginate("referee", db.referees, pred)

    # =====================================================================
    # REFEREE ASSIGNMENT
    # =====================================================================

    @app.route("/referee-assignments", methods=["POST"])
    def create_assignment():
        _, role = require_auth()
        require_role(role, {"FieldMarshal"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            _lookup_arena(arena_id)
            booking_id = require_string(body, "booking_id")
            booking = _lookup_booking(booking_id)
            referee_id = require_string(body, "referee_id")
            referee = _lookup_referee(referee_id)
            field = db.fields.get(booking["field_id"])
            # eligibility (priority 9)
            if referee["status"] != "AVAILABLE":
                raise err("ERR_REFEREE_NOT_ELIGIBLE", "Referee is not AVAILABLE")
            if field is not None and field["game_mode"] == "PAINTBALL" and not referee["certified_paintball"]:
                raise err("ERR_REFEREE_NOT_ELIGIBLE",
                          "Referee not certified for PAINTBALL")
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "booking_id": booking_id,
                "referee_id": referee_id,
                "status": "ASSIGNED",
            })
            db.referee_assignments[rec["id"]] = rec
            referee["status"] = "ON_DUTY"
            db.touch(referee)
            return success(serialize("referee_assignment", rec), 201)

    @app.route("/referee-assignments/<assignment_id>", methods=["GET"])
    def get_assignment_route(assignment_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        a = _lookup_assignment(assignment_id)
        return success(serialize("referee_assignment", a), 200)

    @app.route("/referee-assignments", methods=["GET"])
    def list_assignments():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        booking_id = request.args.get("booking_id")
        referee_id = request.args.get("referee_id")

        def pred(r):
            if arena_id and r["arena_id"] != arena_id:
                return False
            if booking_id and r["booking_id"] != booking_id:
                return False
            if referee_id and r["referee_id"] != referee_id:
                return False
            return True

        return _paginate("referee_assignment", db.referee_assignments, pred)

    # =====================================================================
    # LEAGUE
    # =====================================================================

    @app.route("/leagues", methods=["POST"])
    def create_league():
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            _lookup_arena(arena_id)
            name = require_string(body, "name")
            total_rounds = require_int(body, "total_rounds", minimum=1)
            win_points = optional_int(body, "win_points", default=3, minimum=0)
            draw_points = optional_int(body, "draw_points", default=1, minimum=0)
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "name": name,
                "total_rounds": total_rounds,
                "current_round": 0,
                "win_points": win_points,
                "draw_points": draw_points,
                "status": "DRAFT",
            })
            db.leagues[rec["id"]] = rec
            return success(serialize("league", rec), 201)

    @app.route("/leagues/<league_id>", methods=["GET"])
    def get_league_route(league_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        lg = _lookup_league(league_id)
        return success(serialize("league", lg), 200)

    @app.route("/leagues", methods=["GET"])
    def list_leagues():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        pred = (lambda r: r["arena_id"] == arena_id) if arena_id else None
        return _paginate("league", db.leagues, pred)

    def _compute_standings(league):
        win = league["win_points"]
        draw = league["draw_points"]
        matches = [
            m for m in db.league_matches.values()
            if m["league_id"] == league["id"]
            and m["status"] == "RESULT_RECORDED"
            and m["round_index"] <= league["current_round"]
        ]
        matches.sort(key=lambda m: (m["created_at"], m["_seq"]))
        points = {}

        def ensure(team):
            if team not in points:
                points[team] = 0

        for m in matches:
            ensure(m["home_team"])
            ensure(m["away_team"])
            if m["outcome"] == "DRAW":
                points[m["home_team"]] += draw
                points[m["away_team"]] += draw
            elif m["outcome"] == "HOME":
                points[m["home_team"]] += win
            elif m["outcome"] == "AWAY":
                points[m["away_team"]] += win
        standings = sorted(points.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"team": t, "points": p} for t, p in standings]

    @app.route("/leagues/<league_id>/standings", methods=["GET"])
    def league_standings(league_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        lg = _lookup_league(league_id)
        standings = _compute_standings(lg)
        data = {
            "standings": standings,
            "current_round": lg["current_round"],
            "league_version": lg["version"],
        }
        return success(data, 200)

    @app.route("/leagues/<league_id>/open", methods=["POST"])
    def open_league(league_id):
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        with db.LOCK:
            lg = _lookup_league(league_id)
            if lg["status"] != "DRAFT":
                raise err("ERR_LEAGUE_INVALID_STATE", "League must be DRAFT to open")
            lg["status"] = "OPEN"
            lg["current_round"] = 1
            db.touch(lg)
            return success(serialize("league", lg), 200)

    @app.route("/leagues/<league_id>/lock-round", methods=["POST"])
    def lock_round(league_id):
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        body = get_json_body()
        with db.LOCK:
            lg = _lookup_league(league_id)
            expected = require_int(body, "expected_league_version")
            if lg["status"] != "OPEN":
                raise err("ERR_LEAGUE_INVALID_STATE", "League must be OPEN to lock round")
            # OCC (priority 6)
            if expected != lg["version"]:
                raise err("ERR_STALE_LEAGUE_VERSION",
                          "expected_league_version does not match the league version")
            # round complete?
            for m in db.league_matches.values():
                if (m["league_id"] == lg["id"]
                        and m["round_index"] == lg["current_round"]
                        and m["status"] == "SCHEDULED"):
                    raise err("ERR_ROUND_NOT_COMPLETE",
                              "A match in the current round is still SCHEDULED")
            lg["status"] = "ROUND_LOCKED"
            db.touch(lg)
            return success(serialize("league", lg), 200)

    @app.route("/leagues/<league_id>/advance-round", methods=["POST"])
    def advance_round(league_id):
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        body = get_json_body()
        with db.LOCK:
            lg = _lookup_league(league_id)
            expected = require_int(body, "expected_league_version")
            if lg["status"] != "ROUND_LOCKED":
                raise err("ERR_LEAGUE_INVALID_STATE",
                          "League must be ROUND_LOCKED to advance")
            # OCC (priority 6)
            if expected != lg["version"]:
                raise err("ERR_STALE_LEAGUE_VERSION",
                          "expected_league_version does not match the league version")
            if not (lg["current_round"] < lg["total_rounds"]):
                raise err("ERR_ROUND_LIMIT_REACHED",
                          "Already at the final round")
            lg["current_round"] += 1
            lg["status"] = "OPEN"
            db.touch(lg)
            return success(serialize("league", lg), 200)

    @app.route("/leagues/<league_id>/finalize", methods=["POST"])
    def finalize_league(league_id):
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        with db.LOCK:
            lg = _lookup_league(league_id)
            if lg["status"] != "ROUND_LOCKED":
                raise err("ERR_LEAGUE_INVALID_STATE",
                          "League must be ROUND_LOCKED to finalize")
            if lg["current_round"] != lg["total_rounds"]:
                raise err("ERR_LEAGUE_NOT_AT_FINAL_ROUND",
                          "Finalize requires current_round == total_rounds")
            lg["status"] = "FINALIZED"
            db.touch(lg)
            return success(serialize("league", lg), 200)

    # =====================================================================
    # LEAGUE MATCH
    # =====================================================================

    @app.route("/league-matches", methods=["POST"])
    def create_match():
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        body = get_json_body()
        arena_id = require_string(body, "arena_id")
        with db.LOCK:
            _lookup_arena(arena_id)
            league_id = require_string(body, "league_id")
            lg = _lookup_league(league_id)
            booking_id = require_string(body, "booking_id")
            _lookup_booking(booking_id)
            home_team = require_string(body, "home_team")
            away_team = require_string(body, "away_team")
            rec = db.base_record()
            rec.update({
                "arena_id": arena_id,
                "league_id": league_id,
                "booking_id": booking_id,
                "round_index": lg["current_round"],
                "home_team": home_team,
                "away_team": away_team,
                "home_score": 0,
                "away_score": 0,
                "outcome": None,
                "status": "SCHEDULED",
            })
            db.league_matches[rec["id"]] = rec
            return success(serialize("league_match", rec), 201)

    @app.route("/league-matches/<match_id>", methods=["GET"])
    def get_match_route(match_id):
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        m = _lookup_match(match_id)
        return success(serialize("league_match", m), 200)

    @app.route("/league-matches", methods=["GET"])
    def list_matches():
        _, role = require_auth()
        require_role(role, ALL_ROLES)
        arena_id = request.args.get("arena_id")
        league_id = request.args.get("league_id")
        booking_id = request.args.get("booking_id")

        def pred(r):
            if arena_id and r["arena_id"] != arena_id:
                return False
            if league_id and r["league_id"] != league_id:
                return False
            if booking_id and r["booking_id"] != booking_id:
                return False
            return True

        return _paginate("league_match", db.league_matches, pred)

    @app.route("/league-matches/<match_id>/record-result", methods=["POST"])
    def record_result(match_id):
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        body = get_json_body()
        with db.LOCK:
            m = _lookup_match(match_id)
            home_score = require_int(body, "home_score", minimum=0)
            away_score = require_int(body, "away_score", minimum=0)
            if m["status"] != "SCHEDULED":
                raise err("ERR_MATCH_INVALID_STATE",
                          "Match must be SCHEDULED to record a result")
            lg = db.leagues.get(m["league_id"])
            if lg is None or lg["status"] != "OPEN":
                raise err("ERR_MATCH_INVALID_STATE", "League must be OPEN")
            if m["round_index"] != lg["current_round"]:
                raise err("ERR_MATCH_INVALID_STATE",
                          "Match round_index must equal current_round")
            booking = db.bookings.get(m["booking_id"])
            if booking is None or booking["status"] != "COMPLETED":
                raise err("ERR_MATCH_INVALID_STATE",
                          "Linked booking must be COMPLETED")
            m["home_score"] = home_score
            m["away_score"] = away_score
            if home_score > away_score:
                m["outcome"] = "HOME"
            elif away_score > home_score:
                m["outcome"] = "AWAY"
            else:
                m["outcome"] = "DRAW"
            m["status"] = "RESULT_RECORDED"
            db.touch(m)
            return success(serialize("league_match", m), 200)

    @app.route("/league-matches/<match_id>/void", methods=["POST"])
    def void_match(match_id):
        _, role = require_auth()
        require_role(role, {"LeagueDirector"})
        with db.LOCK:
            m = _lookup_match(match_id)
            if m["status"] != "SCHEDULED":
                raise err("ERR_MATCH_INVALID_STATE", "Match must be SCHEDULED to void")
            m["status"] = "VOID"
            db.touch(m)
            return success(serialize("league_match", m), 200)
