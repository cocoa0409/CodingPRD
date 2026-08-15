"""Crew assignments, the two dispatch channels, travel logistics (PRD 3.7, 3.8)."""

from flask import Blueprint, g, request

from db import store
from errors import err
from helpers import (
    get_body,
    opt_bool,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_list,
    req_str,
    require_roles,
    scope_mariner_resource,
    sorted_items,
)
from response import success
from serialize import ser_assignment, ser_travel_booking
from services import (
    active_rotation_plan,
    cancel_travel_bookings,
    compute_cancellation_fee,
    compute_total_fare,
    credential_is_valid,
    find_handover_violation,
    find_mariner_overlap,
    recompute_vessel,
)

bp = Blueprint("assignments", __name__)

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)

PAYERS = ("VESSEL_OWNER", "UNION_HALL", "MARINER")
DIRECTIONS = ("JOIN", "REPATRIATION")


def _get_assignment(assignment_id):
    a = store.assignments.get(assignment_id)
    if a is None:
        raise err("ERR_ASSIGNMENT_NOT_FOUND", "Assignment %s not found" % assignment_id)
    return a


def _get_booking_under_assignment(assignment_id, booking_id):
    b = store.travel_bookings.get(booking_id)
    if b is None or b["assignment_id"] != assignment_id:
        raise err(
            "ERR_TRAVEL_BOOKING_NOT_FOUND",
            "Travel booking %s not found" % booking_id,
        )
    return b


def _validate_legs(legs):
    """Schema-check a legs array; returns the normalized list."""
    if not isinstance(legs, list):
        raise err("ERR_INVALID_REQUEST", "Field 'legs' must be an array")
    normalized = []
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise err("ERR_INVALID_REQUEST", "legs[%d] must be an object" % i)
        normalized.append(
            {
                "carrier": req_str(leg, "carrier"),
                "from_port": req_str(leg, "from_port"),
                "to_port": req_str(leg, "to_port"),
                "depart_at": req_dt(leg, "depart_at"),
                "arrive_at": req_dt(leg, "arrive_at"),
                "base_fare_cents": req_int(leg, "base_fare_cents"),
                "markup_bps": req_int(leg, "markup_bps"),
            }
        )
    return normalized


def _channel_rules(a, m):
    """Pipeline step 12: channel / registration / dues rules for an assignment."""
    if a["assignment_channel"] == "DIRECT_HIRE":
        if g.role != "CrewingManager" or m["hire_channel"] != "DIRECT":
            raise err(
                "ERR_CHANNEL_NOT_PERMITTED",
                "DIRECT_HIRE assignments require a CrewingManager and a DIRECT mariner",
            )
    else:  # UNION_DISPATCH
        if g.role != "UnionDispatcher" or m["hire_channel"] != "UNION_HALL":
            raise err(
                "ERR_CHANNEL_NOT_PERMITTED",
                "UNION_DISPATCH assignments require a UnionDispatcher and a UNION_HALL mariner",
            )
        reg = store.union_registrations.get(a["union_registration_id"] or "")
        if reg is None or reg["mariner_id"] != m["id"]:
            raise err(
                "ERR_UNION_REGISTRATION_INVALID",
                "UNION_DISPATCH requires a valid union registration",
            )
        if reg["status"] != "REGISTERED":
            raise err(
                "ERR_UNION_REGISTRATION_INVALID",
                "Union registration must be REGISTERED",
            )
        if reg["dues_current_until"] is None or reg["dues_current_until"] < a[
            "sign_on_date"
        ]:
            raise err(
                "ERR_DUES_NOT_CURRENT",
                "Union dues must be current through the sign-on date",
            )


def _temporal_checks(a, exclude_id=None):
    """Pipeline step 13: rotation window, mariner overlap, slot handover."""
    slot = store.manning_slots.get(a["manning_slot_id"])
    vessel_id = slot["vessel_id"] if slot is not None else a["vessel_id"]
    plan = active_rotation_plan(vessel_id)
    if (
        plan is None
        or not (plan["effective_from"] <= a["sign_on_date"] < plan["effective_to"])
    ):
        raise err(
            "ERR_NO_ACTIVE_ROTATION_WINDOW",
            "No ACTIVE rotation plan covers the sign-on date",
        )
    if find_mariner_overlap(
        a["mariner_id"], a["sign_on_date"], a["planned_relief_date"], exclude_id
    ):
        raise err(
            "ERR_MARINER_ASSIGNMENT_OVERLAP",
            "Mariner already has an overlapping assignment",
        )
    if find_handover_violation(
        a["manning_slot_id"],
        a["sign_on_date"],
        a["planned_relief_date"],
        plan["max_handover_overlap_days"],
        exclude_id,
    ):
        raise err(
            "ERR_HANDOVER_WINDOW_EXCEEDED",
            "Slot handover overlap exceeds the rotation plan maximum",
        )


def _endorsement_and_rank_checks(a, m, slot):
    """Pipeline step 11: endorsement match then rank minimums."""
    now = store.clock
    if not any(
        c["mariner_id"] == m["id"]
        and c["endorsement_code"] == slot["required_endorsement_code"]
        and credential_is_valid(c, now)
        for c in store.credentials.values()
    ):
        raise err(
            "ERR_ENDORSEMENT_MISMATCH",
            "Mariner lacks a VALID credential with the slot's required endorsement",
        )
    if m["rank_track"] != slot["rank_track"] or m["rank_grade"] < slot["min_rank_grade"]:
        raise err(
            "ERR_RANK_BELOW_MINIMUM",
            "Mariner rank track/grade does not satisfy the slot minimums",
        )


# ---------------------------------------------------------------------------
# Assignment lifecycle
# ---------------------------------------------------------------------------


@bp.route("/assignments", methods=["POST"])
@require_roles("CrewingManager", "UnionDispatcher")
def create_assignment():
    body = get_body()
    # Body FK existence (pipeline step 5).
    mariner_id = body.get("mariner_id")
    if not isinstance(mariner_id, str) or mariner_id == "":
        raise err("ERR_INVALID_REQUEST", "Field 'mariner_id' is required")
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    slot_id = body.get("manning_slot_id")
    if not isinstance(slot_id, str) or slot_id == "":
        raise err("ERR_INVALID_REQUEST", "Field 'manning_slot_id' is required")
    slot = store.manning_slots.get(slot_id)
    if slot is None:
        raise err("ERR_MANNING_SLOT_NOT_FOUND", "Manning slot %s not found" % slot_id)
    channel = req_enum(body, "assignment_channel", ("DIRECT_HIRE", "UNION_DISPATCH"))
    registration = None
    registration_id = body.get("union_registration_id")
    if registration_id is not None:
        registration = store.union_registrations.get(registration_id)
        if registration is None:
            raise err(
                "ERR_UNION_REGISTRATION_NOT_FOUND",
                "Union registration %s not found" % registration_id,
            )
    relief_of = body.get("relief_of_assignment_id")
    if relief_of is not None:
        if relief_of not in store.assignments:
            raise err(
                "ERR_ASSIGNMENT_NOT_FOUND",
                "Assignment %s not found" % relief_of,
            )
    # Resource scoping (pipeline step 3): dispatchers act on their own hall.
    if g.role == "UnionDispatcher" and channel == "UNION_DISPATCH":
        if registration is None or registration["hall_id"] != g.user_id:
            raise err(
                "ERR_FORBIDDEN_RESOURCE_ACCESS",
                "UnionDispatcher may only dispatch from their own hall",
            )
    # Schema (pipeline step 6).
    sign_on = req_dt(body, "sign_on_date")
    relief = req_dt(body, "planned_relief_date")
    local_join = opt_bool(body, "local_join", default=False)
    if sign_on < store.clock:
        raise err(
            "ERR_INVALID_REQUEST",
            "sign_on_date must not be earlier than the current time",
        )
    if not relief > sign_on:
        raise err(
            "ERR_INVALID_REQUEST",
            "planned_relief_date must be strictly later than sign_on_date",
        )
    if channel == "UNION_DISPATCH" and registration is None:
        raise err(
            "ERR_INVALID_REQUEST",
            "union_registration_id is required for UNION_DISPATCH assignments",
        )
    a = {
        "mariner_id": m["id"],
        "manning_slot_id": slot["id"],
        "vessel_id": slot["vessel_id"],
        "union_registration_id": registration_id,
        "assignment_channel": channel,
        "relief_of_assignment_id": relief_of,
        "sign_on_date": sign_on,
        "planned_relief_date": relief,
        "local_join": local_join,
        "actual_sign_on_at": None,
        "actual_relieved_at": None,
        "assignment_status": "PROPOSED",
        "travel_status": "PENDING",
        "repatriation_status": "NOT_DUE",
    }
    # State preconditions (pipeline step 9).
    vessel = store.vessels.get(slot["vessel_id"])
    if vessel is None or vessel["status"] not in ("ACTIVE", "UNDERWAY"):
        raise err(
            "ERR_VESSEL_NOT_ACTIVE",
            "Assignments require the vessel to be ACTIVE or UNDERWAY",
        )
    if slot["status"] != "ACTIVE":
        raise err("ERR_SLOT_NOT_ACTIVE", "Manning slot must be ACTIVE")
    # Readiness gate (pipeline step 10): creation rejects BLOCKED mariners.
    if m["readiness_posture"] == "BLOCKED":
        raise err(
            "ERR_MARINER_NOT_CLEAR",
            "Mariner readiness posture is BLOCKED",
        )
    # Endorsement and rank chain (pipeline step 11).
    _endorsement_and_rank_checks(a, m, slot)
    # Channel rules (pipeline step 12).
    _channel_rules(a, m)
    # Temporal windowing (pipeline step 13).
    _temporal_checks(a)
    # Aggregate constraints (pipeline step 14).
    if m["status"] != "ACTIVE":
        raise err("ERR_MARINER_NOT_ACTIVE", "Mariner must be ACTIVE")
    store.stamp(a)
    store.assignments[a["id"]] = a
    return success(ser_assignment(a), code=201)


@bp.route("/assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_assignments():
    items = list(store.assignments.values())
    for param, field in (
        ("mariner_id", "mariner_id"),
        ("manning_slot_id", "manning_slot_id"),
        ("vessel_id", "vessel_id"),
        ("assignment_status", "assignment_status"),
        ("relief_of_assignment_id", "relief_of_assignment_id"),
        ("union_registration_id", "union_registration_id"),
    ):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a[field] == val]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_assignment(a) for a in page], response_type="array", pagination=meta
    )


@bp.route("/assignments/<assignment_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_assignment(assignment_id):
    a = _get_assignment(assignment_id)
    scope_mariner_resource(a["mariner_id"])
    return success(ser_assignment(a))


def _dispatcher_cancel_scope(a):
    """Dispatchers may only cancel own-hall UNION_DISPATCH assignments."""
    if g.role != "UnionDispatcher":
        return
    if a["assignment_channel"] != "UNION_DISPATCH":
        raise err(
            "ERR_FORBIDDEN_RESOURCE_ACCESS",
            "UnionDispatcher may only act on UNION_DISPATCH assignments",
        )
    reg = store.union_registrations.get(a["union_registration_id"] or "")
    if reg is None or reg["hall_id"] != g.user_id:
        raise err(
            "ERR_FORBIDDEN_RESOURCE_ACCESS",
            "UnionDispatcher may only act on their own hall",
        )


@bp.route("/assignments/<assignment_id>/confirm", methods=["POST"])
@require_roles("CrewingManager", "UnionDispatcher")
def confirm_assignment(assignment_id):
    a = _get_assignment(assignment_id)
    # Scoping: own-hall check for union dispatch (pipeline step 3).
    if g.role == "UnionDispatcher" and a["assignment_channel"] == "UNION_DISPATCH":
        reg = store.union_registrations.get(a["union_registration_id"] or "")
        if reg is None or reg["hall_id"] != g.user_id:
            raise err(
                "ERR_FORBIDDEN_RESOURCE_ACCESS",
                "UnionDispatcher may only confirm their own hall's assignments",
            )
    # State (pipeline step 9).
    if a["assignment_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Only PROPOSED assignments can be confirmed")
    m = store.mariners.get(a["mariner_id"])
    slot = store.manning_slots.get(a["manning_slot_id"])
    # Readiness gate (pipeline step 10): CLEAR, or RESTRICTED within the window.
    if m["readiness_posture"] == "BLOCKED":
        raise err("ERR_MARINER_NOT_CLEAR", "Mariner readiness posture is BLOCKED")
    if m["readiness_posture"] == "RESTRICTED":
        earliest = m.get("_earliest_expiry")
        if earliest is None or a["planned_relief_date"] > earliest:
            raise err(
                "ERR_RESTRICTED_WINDOW_EXCEEDED",
                "Planned relief exceeds the restricting expiry window",
            )
    # Endorsement/rank (step 11), channel (step 12), temporal (step 13).
    _endorsement_and_rank_checks(a, m, slot)
    _channel_rules(a, m)
    _temporal_checks(a, exclude_id=a["id"])
    a["assignment_status"] = "CONFIRMED"
    a["travel_status"] = "WAIVED" if a["local_join"] else "PENDING"
    store.bump(a)
    return success(ser_assignment(a))


@bp.route("/assignments/<assignment_id>/sign-on", methods=["POST"])
@require_roles("CrewingManager", "PortCaptain")
def sign_on(assignment_id):
    a = _get_assignment(assignment_id)
    if a["assignment_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only CONFIRMED assignments can sign on")
    if store.clock < a["sign_on_date"]:
        raise err("ERR_SIGN_ON_TOO_EARLY", "Sign-on is before the sign-on date")
    if a["travel_status"] not in ("READY", "WAIVED"):
        raise err("ERR_TRAVEL_NOT_READY", "Travel must be READY or WAIVED")
    m = store.mariners.get(a["mariner_id"])
    if m["readiness_posture"] == "BLOCKED":
        raise err("ERR_MARINER_NOT_CLEAR", "Mariner readiness posture is BLOCKED")
    a["assignment_status"] = "ONBOARD"
    a["actual_sign_on_at"] = store.clock
    store.bump(a)
    v = store.vessels.get(a["vessel_id"])
    if v is not None:
        recompute_vessel(v)
    return success(ser_assignment(a))


@bp.route("/assignments/<assignment_id>/relieve", methods=["POST"])
@require_roles("CrewingManager")
def relieve_assignment(assignment_id):
    a = _get_assignment(assignment_id)
    if a["assignment_status"] != "ONBOARD":
        raise err("ERR_INVALID_STATE", "Only ONBOARD assignments can be relieved")
    relief_aboard = any(
        o["manning_slot_id"] == a["manning_slot_id"]
        and o["id"] != a["id"]
        and o["assignment_status"] == "ONBOARD"
        for o in store.assignments.values()
    )
    if not relief_aboard:
        raise err(
            "ERR_RELIEF_NOT_ONBOARD",
            "Relief requires another ONBOARD assignment on the same slot",
        )
    a["assignment_status"] = "RELIEVED"
    a["actual_relieved_at"] = store.clock
    a["repatriation_status"] = "DUE"
    store.bump(a)
    # System-created repatriation booking (QUOTED, empty legs, vessel owner pays).
    b = {
        "assignment_id": a["id"],
        "direction": "REPATRIATION",
        "legs": [],
        "payer": "VESSEL_OWNER",
        "total_fare_cents": None,
        "cancellation_fee_cents": None,
        "status": "QUOTED",
    }
    store.stamp(b)
    store.travel_bookings[b["id"]] = b
    v = store.vessels.get(a["vessel_id"])
    if v is not None:
        recompute_vessel(v)
    return success(ser_assignment(a))


@bp.route("/assignments/<assignment_id>/close", methods=["POST"])
@require_roles("CrewingManager")
def close_assignment(assignment_id):
    a = _get_assignment(assignment_id)
    if a["assignment_status"] != "RELIEVED":
        raise err("ERR_INVALID_STATE", "Only RELIEVED assignments can be closed")
    if a["repatriation_status"] != "COMPLETED":
        raise err(
            "ERR_REPATRIATION_INCOMPLETE",
            "Repatriation must be COMPLETED before closing",
        )
    a["assignment_status"] = "CLOSED"
    store.bump(a)
    return success(ser_assignment(a))


@bp.route("/assignments/<assignment_id>/cancel", methods=["POST"])
@require_roles("CrewingManager", "UnionDispatcher")
def cancel_assignment(assignment_id):
    a = _get_assignment(assignment_id)
    _dispatcher_cancel_scope(a)
    if a["assignment_status"] not in ("PROPOSED", "CONFIRMED", "SUSPENDED"):
        raise err(
            "ERR_INVALID_STATE",
            "Only PROPOSED, CONFIRMED, or SUSPENDED assignments can be cancelled",
        )
    a["assignment_status"] = "CANCELLED"
    store.bump(a)
    cancel_travel_bookings(a)
    v = store.vessels.get(a["vessel_id"])
    if v is not None:
        recompute_vessel(v)
    return success(ser_assignment(a))


@bp.route("/assignments/<assignment_id>/resume", methods=["POST"])
@require_roles("CrewingManager")
def resume_assignment(assignment_id):
    a = _get_assignment(assignment_id)
    if a["assignment_status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Only SUSPENDED assignments can be resumed")
    m = store.mariners.get(a["mariner_id"])
    if a["actual_sign_on_at"] is None:
        # Never signed on: back to CONFIRMED under the confirm readiness rule.
        if m["readiness_posture"] == "BLOCKED":
            raise err(
                "ERR_MARINER_NOT_CLEAR", "Mariner readiness posture is BLOCKED"
            )
        if m["readiness_posture"] == "RESTRICTED":
            earliest = m.get("_earliest_expiry")
            if earliest is None or a["planned_relief_date"] > earliest:
                raise err(
                    "ERR_RESTRICTED_WINDOW_EXCEEDED",
                    "Planned relief exceeds the restricting expiry window",
                )
        a["assignment_status"] = "CONFIRMED"
    else:
        # Mid-tour resume: straight back ONBOARD, posture CLEAR or RESTRICTED.
        if m["readiness_posture"] == "BLOCKED":
            raise err(
                "ERR_MARINER_NOT_CLEAR", "Mariner readiness posture is BLOCKED"
            )
        a["assignment_status"] = "ONBOARD"
    store.bump(a)
    v = store.vessels.get(a["vessel_id"])
    if v is not None:
        recompute_vessel(v)
    return success(ser_assignment(a))


# ---------------------------------------------------------------------------
# Travel bookings
# ---------------------------------------------------------------------------


@bp.route("/assignments/<assignment_id>/travel-bookings", methods=["POST"])
@require_roles("CrewingManager")
def create_travel_booking(assignment_id):
    a = _get_assignment(assignment_id)
    body = get_body()
    # Schema (pipeline step 6): direction enum + manual REPATRIATION ban.
    direction = req_enum(body, "direction", DIRECTIONS)
    if direction == "REPATRIATION":
        raise err(
            "ERR_INVALID_REQUEST",
            "REPATRIATION bookings are system-created at relieve",
        )
    legs = _validate_legs(body.get("legs"))
    payer = req_enum(body, "payer", PAYERS)
    # State (pipeline step 9).
    if a["assignment_status"] not in ("CONFIRMED", "ONBOARD", "RELIEVED"):
        raise err(
            "ERR_INVALID_STATE",
            "Travel bookings require a CONFIRMED, ONBOARD, or RELIEVED assignment",
        )
    if not legs:
        raise err("ERR_NO_TRAVEL_LEGS", "JOIN bookings require at least one leg")
    b = {
        "assignment_id": a["id"],
        "direction": "JOIN",
        "legs": legs,
        "payer": payer,
        "total_fare_cents": None,
        "cancellation_fee_cents": None,
        "status": "QUOTED",
    }
    store.stamp(b)
    store.travel_bookings[b["id"]] = b
    return success(ser_travel_booking(b), code=201)


@bp.route("/assignments/<assignment_id>/travel-bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_travel_bookings(assignment_id):
    a = _get_assignment(assignment_id)
    scope_mariner_resource(a["mariner_id"])
    items = [
        b for b in store.travel_bookings.values() if b["assignment_id"] == a["id"]
    ]
    direction = request.args.get("direction")
    status = request.args.get("status")
    if direction is not None:
        items = [b for b in items if b["direction"] == direction]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_travel_booking(b) for b in page], response_type="array", pagination=meta
    )


@bp.route(
    "/assignments/<assignment_id>/travel-bookings/<booking_id>", methods=["PUT"]
)
@require_roles("CrewingManager")
def replace_legs(assignment_id, booking_id):
    _get_assignment(assignment_id)
    b = _get_booking_under_assignment(assignment_id, booking_id)
    body = get_body()
    legs = _validate_legs(body.get("legs"))
    if b["status"] != "QUOTED":
        raise err(
            "ERR_INVALID_STATE", "Legs can only be replaced while QUOTED"
        )
    b["legs"] = legs
    store.bump(b)
    return success(ser_travel_booking(b))


@bp.route(
    "/assignments/<assignment_id>/travel-bookings/<booking_id>/book", methods=["POST"]
)
@require_roles("CrewingManager")
def book_booking(assignment_id, booking_id):
    _get_assignment(assignment_id)
    b = _get_booking_under_assignment(assignment_id, booking_id)
    if b["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Only QUOTED bookings can be booked")
    if not b["legs"]:
        raise err("ERR_NO_TRAVEL_LEGS", "Booking requires at least one leg")
    b["status"] = "BOOKED"
    store.bump(b)
    return success(ser_travel_booking(b))


@bp.route(
    "/assignments/<assignment_id>/travel-bookings/<booking_id>/ticket",
    methods=["POST"],
)
@require_roles("CrewingManager")
def ticket_booking(assignment_id, booking_id):
    a = _get_assignment(assignment_id)
    b = _get_booking_under_assignment(assignment_id, booking_id)
    if b["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Only BOOKED bookings can be ticketed")
    b["total_fare_cents"] = compute_total_fare(b["legs"])
    b["status"] = "TICKETED"
    store.bump(b)
    # Bubble into the assignment's parallel travel dimensions.
    if b["direction"] == "JOIN":
        if a["travel_status"] == "PENDING":
            a["travel_status"] = "READY"
            store.bump(a)
    else:
        if a["repatriation_status"] == "DUE":
            a["repatriation_status"] = "ARRANGED"
            store.bump(a)
    return success(ser_travel_booking(b))


@bp.route(
    "/assignments/<assignment_id>/travel-bookings/<booking_id>/complete",
    methods=["POST"],
)
@require_roles("CrewingManager")
def complete_booking(assignment_id, booking_id):
    a = _get_assignment(assignment_id)
    b = _get_booking_under_assignment(assignment_id, booking_id)
    if b["status"] != "TICKETED":
        raise err("ERR_INVALID_STATE", "Only TICKETED bookings can be completed")
    b["status"] = "COMPLETED"
    store.bump(b)
    if b["direction"] == "REPATRIATION" and a["repatriation_status"] == "ARRANGED":
        a["repatriation_status"] = "COMPLETED"
        store.bump(a)
    return success(ser_travel_booking(b))


@bp.route(
    "/assignments/<assignment_id>/travel-bookings/<booking_id>/cancel",
    methods=["POST"],
)
@require_roles("CrewingManager")
def cancel_booking(assignment_id, booking_id):
    a = _get_assignment(assignment_id)
    b = _get_booking_under_assignment(assignment_id, booking_id)
    if b["status"] not in ("QUOTED", "BOOKED", "TICKETED"):
        raise err(
            "ERR_INVALID_STATE",
            "Only QUOTED, BOOKED, or TICKETED bookings can be cancelled",
        )
    was_ticketed = b["status"] == "TICKETED"
    if was_ticketed:
        b["cancellation_fee_cents"] = compute_cancellation_fee(
            b["total_fare_cents"] or 0
        )
    else:
        b["cancellation_fee_cents"] = 0
    b["status"] = "CANCELLED"
    store.bump(b)
    # Demote travel readiness when the last ticketed/completed JOIN booking goes.
    if was_ticketed and b["direction"] == "JOIN" and a["travel_status"] == "READY":
        remaining = any(
            o["assignment_id"] == a["id"]
            and o["id"] != b["id"]
            and o["direction"] == "JOIN"
            and o["status"] in ("TICKETED", "COMPLETED")
            for o in store.travel_bookings.values()
        )
        if not remaining:
            a["travel_status"] = "PENDING"
            store.bump(a)
    return success(ser_travel_booking(b))
