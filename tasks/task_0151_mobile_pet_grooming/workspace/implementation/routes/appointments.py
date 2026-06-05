"""Appointment routes: CRUD, add-ons, and lifecycle transitions."""
from flask import Blueprint, request

import db
import models
import validate as V
from middleware import get_identity, require_role
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ADDON_NOT_ALLOWED
import lookup
from util import parse_dt
from response import object_response, array_response
from services import appointment as appt_svc

bp = Blueprint("appointments", __name__)


# ---- Create / read / list ----
@bp.route("/appointments", methods=["POST"])
def create_appointment():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    body = V.require_body(request.get_json(silent=True))
    pet_id = V.require_str(body, "pet_id")
    service_tier_id = V.require_str(body, "service_tier_id")
    recurring_plan_id = V.opt_field(body, "recurring_plan_id")
    pet = lookup.get_pet(pet_id)
    lookup.get_service_tier(service_tier_id)
    if recurring_plan_id is not None:
        lookup.get_recurring_plan(recurring_plan_id)
    if role == "Customer":
        lookup.forbid_unless(uid == pet["customer_id"])
    rec = models.base_versioned()
    rec.update({
        "pet_id": pet_id, "service_tier_id": service_tier_id,
        "route_stop_id": None, "groomer_id": None,
        "recurring_plan_id": recurring_plan_id,
        "estimated_minutes": 0, "quoted_price_cents": 0, "final_price_cents": 0,
        "quote_round": 0, "status": "REQUESTED",
    })
    db.appointments[rec["id"]] = rec
    return object_response(models.ser_appointment(rec), 201)


@bp.route("/appointments/<rid>", methods=["GET"])
def get_appointment(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"})
    rec = lookup.get_appointment(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == lookup.customer_of_appointment(rec))
    elif role == "Groomer":
        lookup.forbid_unless(uid == rec.get("groomer_id"))
    return object_response(models.ser_appointment(rec), 200)


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"})
    limit, offset = V.parse_pagination(request.args)
    items = list(db.appointments.values())
    for field in ("pet_id", "service_tier_id", "route_stop_id", "groomer_id", "recurring_plan_id"):
        val = request.args.get(field)
        if val:
            items = [a for a in items if a.get(field) == val]
    if role == "Customer":
        items = [a for a in items if lookup.customer_of_appointment(a) == uid]
    elif role == "Groomer":
        items = [a for a in items if a.get("groomer_id") == uid]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_appointment(a) for a in page], limit, offset, total, 200)


# ---- Add-ons ----
@bp.route("/appointments/<rid>/add-ons", methods=["POST"])
def attach_add_on(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    appt = lookup.get_appointment(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == lookup.customer_of_appointment(appt))
    body = V.require_body(request.get_json(silent=True))
    add_on_id = V.require_str(body, "add_on_id")
    ao = lookup.get_add_on(add_on_id)
    # not-yet-scheduled: must not already be on a route
    if appt["route_stop_id"] is not None or appt["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"):
        raise err(ERR_INVALID_STATE, "Add-ons can only be attached to a not-yet-scheduled appointment")
    # calm requirement
    pet = db.pets[appt["pet_id"]]
    if ao["requires_calm"] and pet["behavioral_flag"] == "AGGRESSIVE":
        raise err(ERR_ADDON_NOT_ALLOWED, "Add-on requires a calm pet")
    link = models.base_immutable()
    link.update({
        "appointment_id": appt["id"], "add_on_id": add_on_id,
        "price_cents_snapshot": ao["price_cents"],
    })
    db.appointment_add_ons[link["id"]] = link
    models.touch(appt)
    return object_response(models.ser_appointment_add_on(link), 201)


@bp.route("/appointments/<rid>/add-ons", methods=["GET"])
def list_appointment_add_ons(rid):
    uid, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"})
    appt = lookup.get_appointment(rid)
    if role == "Customer":
        lookup.forbid_unless(uid == lookup.customer_of_appointment(appt))
    elif role == "Groomer":
        lookup.forbid_unless(uid == appt.get("groomer_id"))
    limit, offset = V.parse_pagination(request.args)
    items = [l for l in db.appointment_add_ons.values() if l["appointment_id"] == appt["id"]]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_appointment_add_on(l) for l in page], limit, offset, total, 200)


@bp.route("/add-on-links/<rid>", methods=["GET"])
def get_add_on_link(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"})
    link = lookup.get_appointment_add_on(rid)
    return object_response(models.ser_appointment_add_on(link), 200)


@bp.route("/add-on-links", methods=["GET"])
def list_add_on_links():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    limit, offset = V.parse_pagination(request.args)
    items = list(db.appointment_add_ons.values())
    add_on_id = request.args.get("add_on_id")
    appointment_id = request.args.get("appointment_id")
    if add_on_id:
        items = [l for l in items if l["add_on_id"] == add_on_id]
    if appointment_id:
        items = [l for l in items if l["appointment_id"] == appointment_id]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_appointment_add_on(l) for l in page], limit, offset, total, 200)


# ---- Lifecycle transitions ----
@bp.route("/appointments/<rid>/quote", methods=["POST"])
def quote_appointment(rid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    appt = lookup.get_appointment(rid)
    appt_svc.issue_quote(appt)
    return object_response(models.ser_appointment(appt), 200)


@bp.route("/appointments/<rid>/schedule", methods=["POST"])
def schedule_appointment(rid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    appt = lookup.get_appointment(rid)
    body = V.require_body(request.get_json(silent=True))
    route_day_id = V.require_str(body, "route_day_id")
    slot_start = parse_dt(V.require_field(body, "slot_start"), "slot_start")
    expected_route_day_version = V.require_int(body, "expected_route_day_version")
    lookup.get_route_day(route_day_id)
    appt_svc.schedule(appt, route_day_id, slot_start, expected_route_day_version)
    return object_response(models.ser_appointment(appt), 200)


@bp.route("/appointments/<rid>/complete", methods=["POST"])
def complete_appointment(rid):
    uid, role = get_identity()
    require_role(role, {"Groomer"})
    appt = lookup.get_appointment(rid)
    # ownership: only the assigned groomer may complete
    lookup.forbid_unless(appt.get("groomer_id") == uid)
    body = request.get_json(silent=True) or {}
    skipped = V.opt_field(body, "skipped_add_on_ids", [])
    if skipped is None:
        skipped = []
    if not isinstance(skipped, list):
        raise err(ERR_INVALID_REQUEST, "skipped_add_on_ids must be a list")
    appt_svc.complete(appt, skipped)
    return object_response(models.ser_appointment(appt), 200)


@bp.route("/appointments/<rid>/no-show", methods=["POST"])
def no_show_appointment(rid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    appt = lookup.get_appointment(rid)
    appt_svc.no_show(appt)
    return object_response(models.ser_appointment(appt), 200)


@bp.route("/appointments/<rid>/cancel", methods=["POST"])
def cancel_appointment(rid):
    uid, role = get_identity()
    require_role(role, {"Customer"})
    appt = lookup.get_appointment(rid)
    # only the owning customer may cancel
    lookup.forbid_unless(uid == lookup.customer_of_appointment(appt))
    appt_svc.cancel(appt)
    return object_response(models.ser_appointment(appt), 200)
