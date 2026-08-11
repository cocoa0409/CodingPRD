"""Booking child resources: roster attachments, staff assignments, add-on
requests, permits (booking-scoped), waivers, weather assessments, ledger."""
from flask import Blueprint

from db import store
from errors import (
    raise_err,
    ERR_BOOKING_NOT_FOUND, ERR_ANIMAL_NOT_FOUND, ERR_HANDLER_NOT_FOUND,
    ERR_ADDON_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_INVALID_STATE, ERR_STALE_BOOKING_VERSION,
    ERR_ANIMAL_QUARANTINED, ERR_HEALTH_CERT_EXPIRED,
    ERR_ANIMAL_SCHEDULE_CONFLICT, ERR_HANDLER_OVERBOOKED,
    ERR_NO_CERTIFIED_HANDLER, ERR_ADDON_VENUE_INCOMPATIBLE,
    ERR_WAIVER_SIGNATURE_OVERFLOW, ERR_ADDON_ALREADY_REQUESTED,
    ERR_ANIMAL_ALREADY_ON_BOOKING,
)
from middleware import require, check_customer_ownership
from response import ok
from serializers import (
    ser_addon, ser_booking_animal, ser_ledger_entry, ser_permit,
    ser_staff_assignment, ser_waiver, ser_weather_assessment,
)
from services.cascade import (
    animal_buffered_conflict, handler_overbooked, recompute_handler_minutes,
)
from services.pricing import TERMINAL_BOOKING_STATES
from util import (
    body_json, bump, new_common, new_immutable, paginate,
    v_dt, v_enum, v_int, v_str,
)

bp = Blueprint("booking_children", __name__)

BOOKING_ANIMAL_ROLES = {"PETTING_ZOO", "PONY_RIDE", "REPTILE_SHOW"}
ASSIGNMENT_ROLES = {"LEAD", "ASSISTANT"}
ADDON_TYPES = {"PONY_RIDE", "REPTILE_SHOW"}
PERMIT_TYPES = {"ANIMAL_EXHIBITION", "HEALTH_DEPT", "FIRE_SAFETY"}
WEATHER_VERDICTS = {"PROCEED", "HOLD_RECOMMENDED", "MANDATORY_HOLD"}


def get_booking_or_404(booking_id):
    booking = store.bookings.get(booking_id)
    if booking is None:
        raise_err(ERR_BOOKING_NOT_FOUND, "Booking not found")
    return booking


def get_ba_or_404(booking_id, booking_animal_id):
    ba = store.booking_animals.get(booking_animal_id)
    if ba is None or ba["booking_id"] != booking_id:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Booking animal attachment not found")
    return ba


def get_sa_or_404(booking_id, staff_assignment_id):
    sa = store.staff_assignments.get(staff_assignment_id)
    if sa is None or sa["booking_id"] != booking_id:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "Staff assignment not found")
    return sa


def get_addon_or_404(booking_id, addon_id):
    addon = store.addon_requests.get(addon_id)
    if addon is None or addon["booking_id"] != booking_id:
        raise_err(ERR_ADDON_NOT_FOUND, "Add-on request not found")
    return addon


# ---------------------------------------------------------------------------
# Booking animals (roster attachments)
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/animals")
def attach_animal(booking_id):
    require({"Coordinator"})
    body = body_json()
    animal_id = v_str(body, "animal_id")
    role = v_enum(body, "role", BOOKING_ANIMAL_ROLES)
    booking = get_booking_or_404(booking_id)
    animal = store.animals.get(animal_id)
    if animal is None:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    if booking["status"] in TERMINAL_BOOKING_STATES:
        raise_err(ERR_INVALID_STATE, "Booking is terminal")
    if any(
        ba["booking_id"] == booking["id"] and ba["animal_id"] == animal_id
        and ba["status"] in ("PROPOSED", "CONFIRMED")
        for ba in store.booking_animals.values()
    ):
        raise_err(ERR_ANIMAL_ALREADY_ON_BOOKING, "Animal already attached to this booking")

    ba = new_common()
    ba.update({
        "booking_id": booking["id"],
        "animal_id": animal_id,
        "role": role,
        "status": "PROPOSED",
        "removal_reason": None,
    })
    store.booking_animals[ba["id"]] = ba
    booking["quote_fresh"] = False
    bump(booking)
    return ok(ser_booking_animal(ba), status=201)


@bp.post("/petting-zoo/bookings/<booking_id>/animals/<booking_animal_id>/confirm")
def confirm_booking_animal(booking_id, booking_animal_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    ba = get_ba_or_404(booking["id"], booking_animal_id)
    # 1. from-state: attachment PROPOSED and parent booking DRAFT/QUOTED.
    if ba["status"] != "PROPOSED" or booking["status"] not in ("DRAFT", "QUOTED"):
        raise_err(ERR_INVALID_STATE, "Attachment cannot be confirmed in its current state")
    animal = store.animals[ba["animal_id"]]
    # 2. animal must be AVAILABLE
    if animal["status"] != "AVAILABLE":
        raise_err(ERR_ANIMAL_QUARANTINED, "Animal is not AVAILABLE")
    # 3. health certificate valid strictly beyond the event end
    cert = animal["current_health_cert_expires_at"]
    if cert is None or not cert > booking["end_time"]:
        raise_err(ERR_HEALTH_CERT_EXPIRED, "Animal health certificate does not extend past event end")
    # 4. buffered rest-window conflict
    if animal_buffered_conflict(animal, booking):
        raise_err(ERR_ANIMAL_SCHEDULE_CONFLICT, "Animal buffered rest-window conflict")

    ba["status"] = "CONFIRMED"
    bump(ba)
    booking["quote_fresh"] = False
    bump(booking)
    return ok(ser_booking_animal(ba))


@bp.delete("/petting-zoo/bookings/<booking_id>/animals/<booking_animal_id>")
def remove_booking_animal(booking_id, booking_animal_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    ba = get_ba_or_404(booking["id"], booking_animal_id)
    if ba["status"] == "REMOVED":
        raise_err(ERR_INVALID_STATE, "Attachment is already REMOVED")
    if ba["status"] == "CONFIRMED" and booking["status"] not in ("DRAFT", "QUOTED"):
        raise_err(ERR_INVALID_STATE,
                  "A CONFIRMED attachment may be manually removed only from DRAFT/QUOTED bookings")
    ba["status"] = "REMOVED"
    ba["removal_reason"] = "MANUAL"
    bump(ba)
    booking["quote_fresh"] = False
    bump(booking)
    return ok(ser_booking_animal(ba))


@bp.get("/petting-zoo/bookings/<booking_id>/animals")
def list_booking_animals(booking_id):
    role, uid = require({"Customer", "Coordinator", "Operator"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    bas = [ba for ba in store.booking_animals.values() if ba["booking_id"] == booking["id"]]
    data, meta = paginate(bas, ser_booking_animal)
    return ok(data, pagination=meta)


# ---------------------------------------------------------------------------
# Staff assignments
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/staff-assignments")
def create_staff_assignment(booking_id):
    require({"Coordinator"})
    body = body_json()
    handler_id = v_str(body, "handler_id")
    role = v_enum(body, "role", ASSIGNMENT_ROLES)
    booking = get_booking_or_404(booking_id)
    handler = store.handlers.get(handler_id)
    if handler is None:
        raise_err(ERR_HANDLER_NOT_FOUND, "Handler not found")
    if booking["status"] in TERMINAL_BOOKING_STATES:
        raise_err(ERR_INVALID_STATE, "Booking is terminal")
    if handler_overbooked(handler_id, booking):
        raise_err(ERR_HANDLER_OVERBOOKED,
                  "Handler window overlap or daily capacity exceeded")

    sa = new_common()
    sa.update({
        "booking_id": booking["id"],
        "handler_id": handler_id,
        "role": role,
        "status": "ASSIGNED",
        "release_reason": None,
    })
    store.staff_assignments[sa["id"]] = sa
    recompute_handler_minutes(handler_id)
    return ok(ser_staff_assignment(sa), status=201)


@bp.delete("/petting-zoo/bookings/<booking_id>/staff-assignments/<staff_assignment_id>")
def release_staff_assignment(booking_id, staff_assignment_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    sa = get_sa_or_404(booking["id"], staff_assignment_id)
    if sa["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Assignment is not ASSIGNED")
    if booking["status"] not in ("DRAFT", "QUOTED", "CONFIRMED", "WEATHER_HOLD"):
        raise_err(ERR_INVALID_STATE,
                  "Manual release is allowed only while the booking is DRAFT/QUOTED/CONFIRMED/WEATHER_HOLD")
    sa["status"] = "RELEASED"
    sa["release_reason"] = "MANUAL"
    bump(sa)
    recompute_handler_minutes(sa["handler_id"])
    return ok(ser_staff_assignment(sa))


@bp.get("/petting-zoo/bookings/<booking_id>/staff-assignments")
def list_staff_assignments(booking_id):
    role, uid = require({"Customer", "Coordinator", "Operator"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    sas = [s for s in store.staff_assignments.values() if s["booking_id"] == booking["id"]]
    data, meta = paginate(sas, ser_staff_assignment)
    return ok(data, pagination=meta)


# ---------------------------------------------------------------------------
# Add-on requests
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/add-ons")
def create_addon(booking_id):
    role, uid = require({"Customer"})
    body = body_json()
    addon_type = v_enum(body, "addon_type", ADDON_TYPES)
    duration_minutes = v_int(body, "duration_minutes", minimum=1)
    expected_version = v_int(body, "expected_booking_version")
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    if booking["status"] in TERMINAL_BOOKING_STATES:
        raise_err(ERR_INVALID_STATE, "Booking is terminal")
    if expected_version != booking["version"]:
        raise_err(ERR_STALE_BOOKING_VERSION, "expected_booking_version does not match")
    if any(
        a["booking_id"] == booking["id"] and a["addon_type"] == addon_type
        and a["status"] in ("REQUESTED", "APPROVED")
        for a in store.addon_requests.values()
    ):
        raise_err(ERR_ADDON_ALREADY_REQUESTED, "Duplicate add-on type on this booking")

    addon = new_common()
    addon.update({
        "booking_id": booking["id"],
        "addon_type": addon_type,
        "duration_minutes": duration_minutes,
        "status": "REQUESTED",
        "denial_reason": None,
    })
    store.addon_requests[addon["id"]] = addon
    booking["quote_fresh"] = False
    bump(booking)
    return ok(ser_addon(addon), status=201)


@bp.post("/petting-zoo/bookings/<booking_id>/add-ons/<addon_id>/decide")
def decide_addon(booking_id, addon_id):
    require({"Coordinator"})
    body = body_json()
    decision = v_enum(body, "decision", {"APPROVED", "DENIED"})
    denial_reason = v_str(body, "denial_reason", required=False, default=None)
    booking = get_booking_or_404(booking_id)
    addon = get_addon_or_404(booking["id"], addon_id)
    if addon["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Add-on request is not REQUESTED")

    if decision == "APPROVED":
        if addon["addon_type"] == "REPTILE_SHOW":
            certified = any(
                sa["booking_id"] == booking["id"] and sa["status"] == "ASSIGNED"
                and "REPTILE_CERTIFIED" in store.handlers[sa["handler_id"]]["certifications"]
                for sa in store.staff_assignments.values()
            )
            if not certified:
                raise_err(ERR_NO_CERTIFIED_HANDLER,
                          "REPTILE_SHOW requires an ASSIGNED REPTILE_CERTIFIED handler")
        if addon["addon_type"] == "PONY_RIDE":
            venue = store.venues[booking["venue_id"]]
            if venue["venue_type"] not in ("OUTDOOR", "MIXED"):
                raise_err(ERR_ADDON_VENUE_INCOMPATIBLE,
                          "PONY_RIDE requires an OUTDOOR or MIXED venue")
        addon["status"] = "APPROVED"
        bump(addon)
        # Approval invalidates the quote (PRD §2.4).
        booking["quote_fresh"] = False
        bump(booking)
    else:
        addon["status"] = "DENIED"
        addon["denial_reason"] = denial_reason
        bump(addon)
    return ok(ser_addon(addon))


@bp.get("/petting-zoo/bookings/<booking_id>/add-ons")
def list_addons(booking_id):
    role, uid = require({"Customer", "Coordinator"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    addons = [a for a in store.addon_requests.values() if a["booking_id"] == booking["id"]]
    data, meta = paginate(addons, ser_addon)
    return ok(data, pagination=meta)


# ---------------------------------------------------------------------------
# Permits (booking-scoped creation and listing)
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/permits")
def create_permit(booking_id):
    require({"Coordinator"})
    body = body_json()
    permit_type = v_enum(body, "permit_type", PERMIT_TYPES)
    jurisdiction = v_str(body, "jurisdiction")
    booking = get_booking_or_404(booking_id)

    permit = new_common()
    permit.update({
        "booking_id": booking["id"],
        "permit_type": permit_type,
        "jurisdiction": jurisdiction,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "denial_reason": None,
    })
    store.permits[permit["id"]] = permit
    return ok(ser_permit(permit), status=201)


@bp.get("/petting-zoo/bookings/<booking_id>/permits")
def list_permits(booking_id):
    role, uid = require({"Customer", "Coordinator", "ComplianceOfficer"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    permits = [p for p in store.permits.values() if p["booking_id"] == booking["id"]]
    data, meta = paginate(permits, ser_permit)
    return ok(data, pagination=meta)


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/waiver-signatures")
def record_waiver_signatures(booking_id):
    role, uid = require({"Customer"})
    body = body_json()
    count = v_int(body, "count", minimum=1)
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    waiver = next((w for w in store.waivers.values() if w["booking_id"] == booking["id"]), None)
    if waiver is None:
        raise_err(ERR_BOOKING_NOT_FOUND, "Booking has no waiver")
    if waiver["signed_count"] + count > waiver["required_signatures"]:
        raise_err(ERR_WAIVER_SIGNATURE_OVERFLOW, "Signatures would exceed required_signatures")
    waiver["signed_count"] += count
    if waiver["signed_count"] >= waiver["required_signatures"]:
        waiver["status"] = "COMPLETE"
    elif waiver["signed_count"] > 0:
        waiver["status"] = "PARTIAL"
    else:
        waiver["status"] = "PENDING"
    bump(waiver)
    return ok(ser_waiver(waiver))


@bp.get("/petting-zoo/bookings/<booking_id>/waivers")
def list_waivers(booking_id):
    role, uid = require({"Customer", "Coordinator"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    waivers = [w for w in store.waivers.values() if w["booking_id"] == booking["id"]]
    data, meta = paginate(waivers, ser_waiver)
    return ok(data, pagination=meta)


# ---------------------------------------------------------------------------
# Weather assessments
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/weather-assessments")
def create_weather_assessment(booking_id):
    require({"Coordinator"})
    body = body_json()
    assessed_at = v_dt(body, "assessed_at")
    forecast_temp_f = v_int(body, "forecast_temp_f")
    forecast_precip_pct = v_int(body, "forecast_precip_pct", minimum=0, maximum=100)
    wind_mph = v_int(body, "wind_mph")
    verdict = v_enum(body, "verdict", WEATHER_VERDICTS)
    booking = get_booking_or_404(booking_id)

    assessment = new_immutable()
    assessment.update({
        "booking_id": booking["id"],
        "assessed_at": assessed_at,
        "forecast_temp_f": forecast_temp_f,
        "forecast_precip_pct": forecast_precip_pct,
        "wind_mph": wind_mph,
        "verdict": verdict,
    })
    store.weather_assessments[assessment["id"]] = assessment
    return ok(ser_weather_assessment(assessment), status=201)


@bp.get("/petting-zoo/bookings/<booking_id>/weather-assessments")
def list_weather_assessments(booking_id):
    role, uid = require({"Customer", "Coordinator"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    items = [w for w in store.weather_assessments.values() if w["booking_id"] == booking["id"]]
    data, meta = paginate(items, ser_weather_assessment)
    return ok(data, pagination=meta)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

@bp.get("/petting-zoo/bookings/<booking_id>/ledger-entries")
def list_ledger_entries(booking_id):
    role, uid = require({"Customer", "Coordinator", "Operator"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    entries = [e for e in store.ledger_entries.values() if e["booking_id"] == booking["id"]]
    data, meta = paginate(entries, ser_ledger_entry)
    return ok(data, pagination=meta)
