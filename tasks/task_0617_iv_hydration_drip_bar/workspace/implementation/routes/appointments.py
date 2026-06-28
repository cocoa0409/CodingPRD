"""Appointment lifecycle: request, read, list, intake, schedule, md-approve,
md-decline, dispatch, start, complete, cancel.
"""
from flask import Blueprint, request

import clock
import db
import serialize
import validate as v
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SLOT_CONFLICT,
    ERR_ROUTE_LOCKED,
    ERR_NOT_FOUND,
)
from helpers import get_or_404, sort_paginate, recompute_open_adverse_event_count
from middleware import authenticate, require_role
from response import success, success_list
from services import booking, scoring, slots, supply

bp = Blueprint("appointments", __name__)

LOCATION_TYPES = {"LOUNGE", "MOBILE"}
APPT_STATUSES = {
    "REQUESTED", "SCREEN_PENDING", "REQUIRES_MD_REVIEW", "SCHEDULED",
    "DISPATCHED", "IN_PROGRESS", "COMPLETED", "DECLINED", "CANCELLED",
}


# --------------------------------------------------------------------------
# Create / read / list
# --------------------------------------------------------------------------
@bp.route("/appointments", methods=["POST"])
def create_appointment():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse"})
    body = v.body_obj()

    patient_id = v.as_string(v.require(body, "patient_id"), "patient_id")
    menu_item_id = v.as_string(v.require(body, "menu_item_id"), "menu_item_id")
    location_type = v.as_enum(v.require(body, "location_type"), "location_type", LOCATION_TYPES)

    addon_ids = v.opt(body, "addon_ids", [])
    if not isinstance(addon_ids, list):
        raise err(ERR_INVALID_REQUEST, "addon_ids must be an array.")
    for aid in addon_ids:
        if not isinstance(aid, str) or aid.strip() == "":
            raise err(ERR_INVALID_REQUEST, "addon_ids contains an empty element.")

    lounge_id = v.opt(body, "lounge_id", None)
    # lounge_id present iff LOUNGE, absent iff MOBILE.
    if location_type == "LOUNGE":
        if lounge_id is None:
            raise err(ERR_INVALID_REQUEST, "lounge_id required for LOUNGE appointment.")
        lounge_id = v.as_string(lounge_id, "lounge_id")
    else:  # MOBILE
        if lounge_id is not None:
            raise err(ERR_INVALID_REQUEST, "lounge_id must be absent for MOBILE appointment.")

    start_at = v.parse_dt(v.require(body, "start_at"), "start_at")
    duration = v.as_int(v.opt(body, "duration_minutes", 60), "duration_minutes", minimum=15)

    membership_id = v.opt(body, "membership_id", None)
    if membership_id is not None:
        membership_id = v.as_string(membership_id, "membership_id")

    # Existence checks (left-to-right): patient, menu item, add-ons, lounge,
    # membership.
    get_or_404(db.patients, patient_id, "patient")
    get_or_404(db.menu_items, menu_item_id, "menu item")
    for aid in addon_ids:
        get_or_404(db.add_ons, aid, "add-on")
    if location_type == "LOUNGE":
        get_or_404(db.lounges, lounge_id, "lounge")
    if membership_id is not None:
        get_or_404(db.memberships, membership_id, "membership")

    rec = {
        "patient_id": patient_id, "menu_item_id": menu_item_id,
        "addon_ids": list(addon_ids), "location_type": location_type,
        "lounge_id": lounge_id, "route_id": None, "nurse_id": None,
        "standing_order_id": None, "start_at": start_at,
        "duration_minutes": duration, "membership_id": membership_id,
        "status": "REQUESTED", "amount_charged_cents": None,
        "drip_credit_used": 0, "addon_credits_used": 0,
    }
    db.stamp_create(rec)
    db.appointments[rec["id"]] = rec
    return success(serialize.appointment(rec), status=201)


@bp.route("/appointments/<id>", methods=["GET"])
def get_appointment(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.appointments, id, "appointment")
    return success(serialize.appointment(rec), status=200)


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    limit, offset = v.parse_pagination()
    status = v.filter_enum("status", request.args.get("status"), APPT_STATUSES)
    filters = {
        "patient_id": request.args.get("patient_id"),
        "menu_item_id": request.args.get("menu_item_id"),
        "membership_id": request.args.get("membership_id"),
        "lounge_id": request.args.get("lounge_id"),
        "route_id": request.args.get("route_id"),
        "nurse_id": request.args.get("nurse_id"),
        "standing_order_id": request.args.get("standing_order_id"),
    }
    items = []
    for r in db.appointments.values():
        if status is not None and r["status"] != status:
            continue
        ok = True
        for key, val in filters.items():
            if val is not None and r[key] != val:
                ok = False
                break
        if ok:
            items.append(r)
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.appointment(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Intake screening
# --------------------------------------------------------------------------
@bp.route("/appointments/<id>/intake", methods=["POST"])
def intake(id):
    user_id, role = authenticate()
    require_role(role, {"IntakeNurse"})
    appt = get_or_404(db.appointments, id, "appointment")
    body = v.body_obj()
    author = v.as_string(v.require(body, "author_user_id"), "author_user_id")
    flags = {}
    for f in ("pregnancy", "renal_impairment", "cardiac_history",
              "g6pd_deficiency", "recent_adverse_event"):
        flags[f] = v.as_bool(v.opt(body, f, False), f)

    # State: intake allowed from REQUESTED, SCREEN_PENDING, REQUIRES_MD_REVIEW.
    if appt["status"] not in ("REQUESTED", "SCREEN_PENDING", "REQUIRES_MD_REVIEW"):
        raise err(ERR_INVALID_STATE, "Intake not allowed from current status.")

    # Supersede any prior SUBMITTED screening for this appointment.
    for s in db.intake_screenings.values():
        if s["appointment_id"] == id and s["status"] == "SUBMITTED":
            s["status"] = "SUPERSEDED"

    menu_item = db.menu_items[appt["menu_item_id"]]
    patient = db.patients[appt["patient_id"]]

    screening = {
        "appointment_id": id, "author_user_id": author,
        "pregnancy": flags["pregnancy"], "renal_impairment": flags["renal_impairment"],
        "cardiac_history": flags["cardiac_history"], "g6pd_deficiency": flags["g6pd_deficiency"],
        "recent_adverse_event": flags["recent_adverse_event"],
        "contraindication_score": 0, "outcome": None, "status": "SUBMITTED",
    }
    score = scoring.compute_score(screening, menu_item, patient, appt["start_at"])
    screening["contraindication_score"] = score
    screening["outcome"] = scoring.outcome_for(score)
    db.stamp_create(screening)
    db.intake_screenings[screening["id"]] = screening

    appt["status"] = "SCREEN_PENDING"
    db.touch(appt)

    return success(serialize.intake_screening(screening), status=201)


# --------------------------------------------------------------------------
# Schedule (clearance fork)
# --------------------------------------------------------------------------
@bp.route("/appointments/<id>/schedule", methods=["POST"])
def schedule(id):
    user_id, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    appt = get_or_404(db.appointments, id, "appointment")
    body = v.body_obj()
    expected_version = v.as_int(v.require(body, "expected_appointment_version"),
                                "expected_appointment_version")

    # State: schedule defined only from SCREEN_PENDING.
    if appt["status"] != "SCREEN_PENDING":
        raise err(ERR_INVALID_STATE, "Appointment is not SCREEN_PENDING.")

    # OCC (after state, before business rules) — PRD §2.6.
    if expected_version != appt["version"]:
        raise err(ERR_STALE_VERSION, "expected_appointment_version is stale.")

    screening = booking.latest_submitted_screening(id)

    # Fork on outcome. BLOCKED is rejected (ERR_SCREENING_BLOCKED) — handled
    # inside the booking battery for the CLEARED path; here, an explicit fork:
    if screening is not None and screening["outcome"] == "REQUIRES_MD_REVIEW":
        appt["status"] = "REQUIRES_MD_REVIEW"
        db.touch(appt)
        return success(serialize.appointment(appt), status=200)

    # CLEARED path (or BLOCKED -> rejected inside the battery).
    booking.perform_booking(appt, caller_user_id=user_id, is_md_approve=False)
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


# --------------------------------------------------------------------------
# MD approve / decline
# --------------------------------------------------------------------------
@bp.route("/appointments/<id>/md-approve", methods=["POST"])
def md_approve(id):
    user_id, role = authenticate()
    require_role(role, {"MedicalDirector"})
    appt = get_or_404(db.appointments, id, "appointment")
    body = v.body_obj()
    expected_appt_version = v.as_int(v.require(body, "expected_appointment_version"),
                                     "expected_appointment_version")
    expected_membership_version = v.opt(body, "expected_membership_version", None)
    if expected_membership_version is not None:
        expected_membership_version = v.as_int(expected_membership_version,
                                               "expected_membership_version")

    if appt["status"] != "REQUIRES_MD_REVIEW":
        raise err(ERR_INVALID_STATE, "Appointment is not REQUIRES_MD_REVIEW.")

    # OCC: appointment version, then membership version (when a membership is
    # in play against which credits will be redeemed).
    if expected_appt_version != appt["version"]:
        raise err(ERR_STALE_VERSION, "expected_appointment_version is stale.")
    if appt["membership_id"] is not None:
        membership = db.memberships.get(appt["membership_id"])
        if (membership is not None and expected_membership_version is not None
                and expected_membership_version != membership["version"]):
            raise err(ERR_STALE_VERSION, "expected_membership_version is stale.")

    booking.perform_booking(appt, caller_user_id=user_id, is_md_approve=True)
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


@bp.route("/appointments/<id>/md-decline", methods=["POST"])
def md_decline(id):
    user_id, role = authenticate()
    require_role(role, {"MedicalDirector"})
    appt = get_or_404(db.appointments, id, "appointment")
    if appt["status"] != "REQUIRES_MD_REVIEW":
        raise err(ERR_INVALID_STATE, "Appointment is not REQUIRES_MD_REVIEW.")
    screening = booking.latest_submitted_screening(id)
    if screening is not None and user_id == screening["author_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "MD must not be the screening author.")
    appt["status"] = "DECLINED"
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
@bp.route("/appointments/<id>/dispatch", methods=["POST"])
def dispatch(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    appt = get_or_404(db.appointments, id, "appointment")
    body = v.body_obj()
    nurse_id = v.as_string(v.require(body, "nurse_id"), "nurse_id")
    route_id = v.opt(body, "route_id", None)
    if route_id is not None:
        route_id = v.as_string(route_id, "route_id")

    # Existence (FK): nurse, route.
    nurse = get_or_404(db.nurses, nurse_id, "nurse")
    route = None
    if route_id is not None:
        route = get_or_404(db.dispatch_routes, route_id, "dispatch route")

    if appt["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Appointment is not SCHEDULED.")

    # Nurse must be AVAILABLE.
    if nurse["status"] != "AVAILABLE":
        raise err(ERR_INVALID_STATE, "Nurse is not AVAILABLE.")

    # SoD: dispatched nurse X-User-ID != standing order's medical_director_user_id.
    # (X-User-ID for a Nurse is the Nurse entity id; here the dispatched nurse's
    #  id is compared to the pinned standing order's signing director.)
    if appt["standing_order_id"] is not None:
        order = db.standing_orders.get(appt["standing_order_id"])
        if order is not None and nurse_id == order["medical_director_user_id"]:
            raise err(ERR_SEGREGATION_OF_DUTIES,
                      "Dispatched nurse must not be the standing-order medical director.")

    if appt["location_type"] == "MOBILE":
        # Mobile dispatch needs a PLANNING route for this nurse on start_at's
        # date, with the turnaround buffer satisfied.
        if route is None:
            raise err(ERR_SLOT_CONFLICT, "Mobile dispatch requires a route.")
        if route["nurse_id"] != nurse_id:
            raise err(ERR_SLOT_CONFLICT, "Route belongs to a different nurse.")
        if not _same_utc_date(route["service_date"], appt["start_at"]):
            raise err(ERR_SLOT_CONFLICT, "Route service_date does not match start_at date.")
        if route["status"] != "PLANNING":
            raise err(ERR_ROUTE_LOCKED, "Route is not PLANNING.")
        if not slots.route_buffer_ok(appt, route):
            raise err(ERR_SLOT_CONFLICT, "Turnaround buffer violated on the route.")
        appt["route_id"] = route_id
        route["stop_count"] += 1

    appt["nurse_id"] = nurse_id
    appt["status"] = "DISPATCHED"
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


def _same_utc_date(a, b):
    return (a.year, a.month, a.day) == (b.year, b.month, b.day)


# --------------------------------------------------------------------------
# Start / complete
# --------------------------------------------------------------------------
@bp.route("/appointments/<id>/start", methods=["POST"])
def start(id):
    user_id, role = authenticate()
    require_role(role, {"Nurse"})
    appt = get_or_404(db.appointments, id, "appointment")
    if appt["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Appointment is not DISPATCHED.")
    if user_id != appt["nurse_id"]:
        raise err(ERR_INVALID_STATE, "Caller is not the dispatched nurse.")
    if not (clock.now() >= appt["start_at"]):
        raise err(ERR_INVALID_STATE, "Infusion cannot start before start_at.")
    appt["status"] = "IN_PROGRESS"
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


@bp.route("/appointments/<id>/complete", methods=["POST"])
def complete(id):
    user_id, role = authenticate()
    require_role(role, {"Nurse"})
    appt = get_or_404(db.appointments, id, "appointment")
    if appt["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE, "Appointment is not IN_PROGRESS.")
    if user_id != appt["nurse_id"]:
        raise err(ERR_INVALID_STATE, "Caller is not the dispatched nurse.")

    # Consume reserved units for each line via the same FEFO ordering that was
    # used to reserve: drip first, then add-ons in order. We move each
    # already-reserved unit to consumed on a lot that currently has a reserved
    # unit for the line key.
    _consume_supply(appt)

    # Membership credits already decremented at schedule/approve; completion
    # finalizes consumption (no restore). Nothing further to do.
    appt["status"] = "COMPLETED"
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


def _consume_supply(appt):
    menu_item = db.menu_items[appt["menu_item_id"]]
    addon_records = [db.add_ons[aid] for aid in appt["addon_ids"]]
    lines = supply.build_lines(menu_item, addon_records)
    consumed_per_lot = {}
    for item_kind, key in lines:
        lot = _pick_reserved_lot(item_kind, key, consumed_per_lot)
        if lot is None:
            continue
        lot["units_reserved"] -= 1
        lot["units_consumed"] += 1
        consumed_per_lot[lot["id"]] = consumed_per_lot.get(lot["id"], 0) + 1
        if lot["units_consumed"] + lot["units_reserved"] == lot["units_total"]:
            lot["status"] = "EXHAUSTED"


def _pick_reserved_lot(item_kind, key, consumed_per_lot):
    """Pick a lot holding a reserved unit for the line key, FEFO order."""
    cands = []
    for lot in db.supply_lots.values():
        if lot["item_kind"] != item_kind:
            continue
        if lot["tier_or_code"] != key:
            continue
        if lot["units_reserved"] - consumed_per_lot.get(lot["id"], 0) >= 1:
            cands.append(lot)
    cands.sort(key=lambda l: (l["expires_at"], l["created_at"], l["_seq"]))
    return cands[0] if cands else None


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------
@bp.route("/appointments/<id>/cancel", methods=["POST"])
def cancel(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    appt = get_or_404(db.appointments, id, "appointment")
    if appt["status"] not in ("REQUESTED", "SCREEN_PENDING", "REQUIRES_MD_REVIEW",
                              "SCHEDULED", "DISPATCHED"):
        raise err(ERR_INVALID_STATE, "Appointment is terminal; cannot cancel.")

    # Release reserved supply units (only when the appointment had reserved —
    # i.e. it had reached SCHEDULED/DISPATCHED). Reservation happens at
    # schedule/approve, so amount_charged_cents being set indicates a booking.
    if appt["status"] in ("SCHEDULED", "DISPATCHED"):
        _release_supply(appt)

    # Restore membership credits the appointment had consumed (PRD §3.13).
    if appt["membership_id"] is not None and (appt["drip_credit_used"] or appt["addon_credits_used"]):
        membership = db.memberships.get(appt["membership_id"])
        if membership is not None:
            membership["drip_credits_remaining"] += appt["drip_credit_used"]
            membership["addon_credits_remaining"] += appt["addon_credits_used"]

    # Decrement route stop_count if routed.
    if appt["route_id"] is not None:
        route = db.dispatch_routes.get(appt["route_id"])
        if route is not None and route["stop_count"] > 0:
            route["stop_count"] -= 1

    appt["status"] = "CANCELLED"
    db.touch(appt)
    return success(serialize.appointment(appt), status=200)


def _release_supply(appt):
    menu_item = db.menu_items[appt["menu_item_id"]]
    addon_records = [db.add_ons[aid] for aid in appt["addon_ids"]]
    lines = supply.build_lines(menu_item, addon_records)
    released_per_lot = {}
    for item_kind, key in lines:
        lot = _pick_reserved_lot(item_kind, key, released_per_lot)
        if lot is None:
            continue
        lot["units_reserved"] -= 1
        released_per_lot[lot["id"]] = released_per_lot.get(lot["id"], 0) + 1
