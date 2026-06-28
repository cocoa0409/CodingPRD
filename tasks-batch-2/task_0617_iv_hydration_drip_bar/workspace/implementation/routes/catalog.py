"""Clock, catalog, people, places, memberships, standing orders, supply lots,
dispatch routes — creation, read, list, and their lifecycle transitions.
"""
from flask import Blueprint

import clock
import db
import serialize
import validate as v
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_LOT_HAS_RESERVATIONS,
)
from helpers import get_or_404, sort_paginate, refresh_standing_order, refresh_supply_lot
from middleware import authenticate, require_role
from response import success, success_list

bp = Blueprint("catalog", __name__)

TIERS = {"MYERS", "NAD", "IMMUNITY"}
ADDON_CODES = {"GLUTATHIONE", "B12", "ZOFRAN", "TORADOL", "VITC_HIGH"}
MEMBERSHIP_TIERS = {"NONE", "GOLD", "PLATINUM"}


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    to_iso = v.require(body, "to_iso8601")
    dt = v.parse_dt(to_iso, "to_iso8601")
    clock.set_now(dt)
    return success({}, status=200)


# --------------------------------------------------------------------------
# InfusionMenuItem
# --------------------------------------------------------------------------
@bp.route("/menu-items", methods=["POST"])
def create_menu_item():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    name = v.as_string(v.require(body, "name"), "name")
    tier = v.as_enum(v.require(body, "tier"), "tier", TIERS)
    base_price = v.as_int(v.require(body, "base_price_cents"), "base_price_cents", minimum=0)
    requires_so = v.opt(body, "requires_standing_order", True)
    requires_so = v.as_bool(requires_so, "requires_standing_order")
    g6pd = v.as_bool(v.opt(body, "g6pd_sensitive", False), "g6pd_sensitive")
    active = v.as_bool(v.opt(body, "active", True), "active")
    rec = {
        "name": name, "tier": tier, "base_price_cents": base_price,
        "requires_standing_order": requires_so, "g6pd_sensitive": g6pd,
        "active": active,
    }
    db.stamp_create(rec)
    db.menu_items[rec["id"]] = rec
    return success(serialize.menu_item(rec), status=201)


@bp.route("/menu-items/<id>", methods=["GET"])
def get_menu_item(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.menu_items, id, "menu item")
    return success(serialize.menu_item(rec), status=200)


@bp.route("/menu-items", methods=["GET"])
def list_menu_items():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    from flask import request
    limit, offset = v.parse_pagination()
    tier = v.filter_enum("tier", request.args.get("tier"), TIERS)
    items = [r for r in db.menu_items.values() if tier is None or r["tier"] == tier]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.menu_item(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# AddOn
# --------------------------------------------------------------------------
@bp.route("/add-ons", methods=["POST"])
def create_add_on():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    name = v.as_string(v.require(body, "name"), "name")
    code = v.as_enum(v.require(body, "code"), "code", ADDON_CODES)
    price = v.as_int(v.require(body, "price_cents"), "price_cents", minimum=0)
    active = v.as_bool(v.opt(body, "active", True), "active")
    rec = {"name": name, "code": code, "price_cents": price, "active": active}
    db.stamp_create(rec)
    db.add_ons[rec["id"]] = rec
    return success(serialize.add_on(rec), status=201)


@bp.route("/add-ons", methods=["GET"])
def list_add_ons():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    from flask import request
    limit, offset = v.parse_pagination()
    code = v.filter_enum("code", request.args.get("code"), ADDON_CODES)
    items = [r for r in db.add_ons.values() if code is None or r["code"] == code]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.add_on(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Patient
# --------------------------------------------------------------------------
@bp.route("/patients", methods=["POST"])
def create_patient():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse"})
    body = v.body_obj()
    full_name = v.as_string(v.require(body, "full_name"), "full_name")
    dob = v.parse_dt(v.require(body, "date_of_birth"), "date_of_birth")
    membership_id = v.opt(body, "membership_id", None)
    if membership_id is not None:
        membership_id = v.as_string(membership_id, "membership_id")
        get_or_404(db.memberships, membership_id, "membership")
    rec = {
        "full_name": full_name, "date_of_birth": dob,
        "membership_id": membership_id, "open_adverse_event_count": 0,
    }
    db.stamp_create(rec)
    db.patients[rec["id"]] = rec
    return success(serialize.patient(rec), status=201)


@bp.route("/patients/<id>", methods=["GET"])
def get_patient(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.patients, id, "patient")
    return success(serialize.patient(rec), status=200)


@bp.route("/patients", methods=["GET"])
def list_patients():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    from flask import request
    limit, offset = v.parse_pagination()
    membership_id = request.args.get("membership_id")
    items = [r for r in db.patients.values()
             if membership_id is None or r["membership_id"] == membership_id]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.patient(r) for r in page], limit, offset, total)


@bp.route("/patients/<id>/memberships", methods=["GET"])
def patient_memberships(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector"})
    patient = get_or_404(db.patients, id, "patient")
    items = []
    if patient["membership_id"] is not None and patient["membership_id"] in db.memberships:
        items.append(db.memberships[patient["membership_id"]])
    limit, offset = v.parse_pagination()
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.membership(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------
@bp.route("/memberships", methods=["POST"])
def create_membership():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    tier = v.as_enum(v.require(body, "tier"), "tier", MEMBERSHIP_TIERS)
    covered = v.as_enum(v.require(body, "covered_drip_tier"), "covered_drip_tier", TIERS)
    drip_total = v.as_int(v.opt(body, "drip_credits_total", 0), "drip_credits_total", minimum=0)
    addon_total = v.as_int(v.opt(body, "addon_credits_total", 0), "addon_credits_total", minimum=0)
    rec = {
        "tier": tier, "covered_drip_tier": covered,
        "drip_credits_total": drip_total, "drip_credits_remaining": drip_total,
        "addon_credits_total": addon_total, "addon_credits_remaining": addon_total,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.memberships[rec["id"]] = rec
    return success(serialize.membership(rec), status=201)


@bp.route("/memberships/<id>", methods=["GET"])
def get_membership(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector"})
    rec = get_or_404(db.memberships, id, "membership")
    return success(serialize.membership(rec), status=200)


@bp.route("/memberships/<id>/suspend", methods=["POST"])
def suspend_membership(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    rec = get_or_404(db.memberships, id, "membership")
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Membership is not ACTIVE.")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return success(serialize.membership(rec), status=200)


@bp.route("/memberships/<id>/reinstate", methods=["POST"])
def reinstate_membership(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    rec = get_or_404(db.memberships, id, "membership")
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Membership is not SUSPENDED.")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success(serialize.membership(rec), status=200)


# --------------------------------------------------------------------------
# StandingOrder
# --------------------------------------------------------------------------
@bp.route("/standing-orders", methods=["POST"])
def create_standing_order():
    _, role = authenticate()
    require_role(role, {"MedicalDirector"})
    body = v.body_obj()
    md_id = v.as_string(v.require(body, "medical_director_user_id"), "medical_director_user_id")
    covered = v.as_enum(v.require(body, "covered_tier"), "covered_tier", TIERS)
    eff = v.parse_dt(v.require(body, "effective_from"), "effective_from")
    exp = v.parse_dt(v.require(body, "expires_at"), "expires_at")
    rec = {
        "medical_director_user_id": md_id, "covered_tier": covered,
        "effective_from": eff, "expires_at": exp, "status": "DRAFT",
    }
    db.stamp_create(rec)
    db.standing_orders[rec["id"]] = rec
    return success(serialize.standing_order(rec), status=201)


@bp.route("/standing-orders/<id>", methods=["GET"])
def get_standing_order(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector"})
    rec = get_or_404(db.standing_orders, id, "standing order")
    refresh_standing_order(rec)
    return success(serialize.standing_order(rec), status=200)


@bp.route("/standing-orders", methods=["GET"])
def list_standing_orders():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector"})
    from flask import request
    limit, offset = v.parse_pagination()
    covered = v.filter_enum("covered_tier", request.args.get("covered_tier"), TIERS)
    status = v.filter_enum("status", request.args.get("status"),
                           {"DRAFT", "ACTIVE", "EXPIRED", "REVOKED"})
    items = []
    for r in db.standing_orders.values():
        refresh_standing_order(r)
        if covered is not None and r["covered_tier"] != covered:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.standing_order(r) for r in page], limit, offset, total)


@bp.route("/standing-orders/<id>/activate", methods=["POST"])
def activate_standing_order(id):
    user_id, role = authenticate()
    require_role(role, {"MedicalDirector"})
    rec = get_or_404(db.standing_orders, id, "standing order")
    refresh_standing_order(rec)
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Standing order is not DRAFT.")
    # Preconditions: caller is the signing director; clock < expires_at;
    # effective_from < expires_at.
    if user_id != rec["medical_director_user_id"]:
        raise err(ERR_INVALID_STATE, "Caller is not the signing medical director.")
    if not (clock.now() < rec["expires_at"]):
        raise err(ERR_INVALID_STATE, "Standing order has already expired.")
    if not (rec["effective_from"] < rec["expires_at"]):
        raise err(ERR_INVALID_STATE, "effective_from must be before expires_at.")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success(serialize.standing_order(rec), status=200)


@bp.route("/standing-orders/<id>/revoke", methods=["POST"])
def revoke_standing_order(id):
    user_id, role = authenticate()
    require_role(role, {"MedicalDirector"})
    rec = get_or_404(db.standing_orders, id, "standing order")
    refresh_standing_order(rec)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Standing order is not ACTIVE.")
    if user_id != rec["medical_director_user_id"]:
        raise err(ERR_INVALID_STATE, "Caller is not the signing medical director.")
    rec["status"] = "REVOKED"
    db.touch(rec)
    return success(serialize.standing_order(rec), status=200)


# --------------------------------------------------------------------------
# Nurse
# --------------------------------------------------------------------------
@bp.route("/nurses", methods=["POST"])
def create_nurse():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    full_name = v.as_string(v.require(body, "full_name"), "full_name")
    license_number = v.as_string(v.require(body, "license_number"), "license_number")
    home_lounge_id = v.opt(body, "home_lounge_id", None)
    if home_lounge_id is not None:
        home_lounge_id = v.as_string(home_lounge_id, "home_lounge_id")
        get_or_404(db.lounges, home_lounge_id, "lounge")
    status = v.as_enum(v.opt(body, "status", "AVAILABLE"), "status", {"AVAILABLE", "OFF_DUTY"})
    rec = {
        "full_name": full_name, "license_number": license_number,
        "home_lounge_id": home_lounge_id, "status": status,
    }
    db.stamp_create(rec)
    db.nurses[rec["id"]] = rec
    return success(serialize.nurse(rec), status=201)


@bp.route("/nurses/<id>", methods=["GET"])
def get_nurse(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.nurses, id, "nurse")
    return success(serialize.nurse(rec), status=200)


@bp.route("/lounges/<id>/nurses", methods=["GET"])
def lounge_nurses(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector"})
    get_or_404(db.lounges, id, "lounge")
    limit, offset = v.parse_pagination()
    items = [r for r in db.nurses.values() if r["home_lounge_id"] == id]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.nurse(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Lounge
# --------------------------------------------------------------------------
@bp.route("/lounges", methods=["POST"])
def create_lounge():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    name = v.as_string(v.require(body, "name"), "name")
    bay_count = v.as_int(v.require(body, "bay_count"), "bay_count", minimum=1)
    open_min = v.as_int(v.opt(body, "open_minute_of_day", 480), "open_minute_of_day",
                        minimum=0, maximum=1439)
    close_min = v.as_int(v.opt(body, "close_minute_of_day", 1200), "close_minute_of_day",
                         minimum=0, maximum=1440)
    rec = {
        "name": name, "bay_count": bay_count,
        "open_minute_of_day": open_min, "close_minute_of_day": close_min,
    }
    db.stamp_create(rec)
    db.lounges[rec["id"]] = rec
    return success(serialize.lounge(rec), status=201)


@bp.route("/lounges/<id>", methods=["GET"])
def get_lounge(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.lounges, id, "lounge")
    return success(serialize.lounge(rec), status=200)


# --------------------------------------------------------------------------
# SupplyLot
# --------------------------------------------------------------------------
@bp.route("/supply-lots", methods=["POST"])
def create_supply_lot():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    item_kind = v.as_enum(v.require(body, "item_kind"), "item_kind", {"DRIP_BASE", "ADDON"})
    tier_or_code = v.as_string(v.require(body, "tier_or_code"), "tier_or_code")
    lot_number = v.as_string(v.require(body, "lot_number"), "lot_number")
    units_total = v.as_int(v.require(body, "units_total"), "units_total", minimum=1)
    expires_at = v.parse_dt(v.require(body, "expires_at"), "expires_at")
    rec = {
        "item_kind": item_kind, "tier_or_code": tier_or_code,
        "lot_number": lot_number, "units_total": units_total,
        "units_reserved": 0, "units_consumed": 0,
        "expires_at": expires_at, "status": "AVAILABLE",
    }
    db.stamp_create(rec)
    db.supply_lots[rec["id"]] = rec
    return success(serialize.supply_lot(rec), status=201)


@bp.route("/supply-lots/<id>", methods=["GET"])
def get_supply_lot(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.supply_lots, id, "supply lot")
    refresh_supply_lot(rec)
    return success(serialize.supply_lot(rec), status=200)


@bp.route("/supply-lots", methods=["GET"])
def list_supply_lots():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    from flask import request
    limit, offset = v.parse_pagination()
    item_kind = v.filter_enum("item_kind", request.args.get("item_kind"), {"DRIP_BASE", "ADDON"})
    status = v.filter_enum("status", request.args.get("status"),
                           {"AVAILABLE", "EXHAUSTED", "EXPIRED", "QUARANTINED"})
    tier_or_code = request.args.get("tier_or_code")
    items = []
    for r in db.supply_lots.values():
        refresh_supply_lot(r)
        if item_kind is not None and r["item_kind"] != item_kind:
            continue
        if tier_or_code is not None and r["tier_or_code"] != tier_or_code:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.supply_lot(r) for r in page], limit, offset, total)


@bp.route("/supply-lots/<id>/quarantine", methods=["POST"])
def quarantine_supply_lot(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    rec = get_or_404(db.supply_lots, id, "supply lot")
    refresh_supply_lot(rec)
    if rec["status"] != "AVAILABLE":
        raise err(ERR_INVALID_STATE, "Supply lot is not AVAILABLE.")
    if rec["units_reserved"] > 0:
        raise err(ERR_LOT_HAS_RESERVATIONS, "Lot has reserved units; cannot quarantine.")
    rec["status"] = "QUARANTINED"
    db.touch(rec)
    return success(serialize.supply_lot(rec), status=200)


# --------------------------------------------------------------------------
# DispatchRoute
# --------------------------------------------------------------------------
@bp.route("/dispatch-routes", methods=["POST"])
def create_dispatch_route():
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    body = v.body_obj()
    nurse_id = v.as_string(v.require(body, "nurse_id"), "nurse_id")
    get_or_404(db.nurses, nurse_id, "nurse")
    service_date = v.parse_dt(v.require(body, "service_date"), "service_date")
    turnaround = v.as_int(v.opt(body, "turnaround_minutes", 30), "turnaround_minutes", minimum=0)
    rec = {
        "nurse_id": nurse_id, "service_date": service_date,
        "turnaround_minutes": turnaround, "stop_count": 0, "status": "PLANNING",
    }
    db.stamp_create(rec)
    db.dispatch_routes[rec["id"]] = rec
    return success(serialize.dispatch_route(rec), status=201)


@bp.route("/dispatch-routes/<id>", methods=["GET"])
def get_dispatch_route(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.dispatch_routes, id, "dispatch route")
    return success(serialize.dispatch_route(rec), status=200)


@bp.route("/nurses/<id>/dispatch-routes", methods=["GET"])
def nurse_dispatch_routes(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    get_or_404(db.nurses, id, "nurse")
    from flask import request
    limit, offset = v.parse_pagination()
    service_date_raw = request.args.get("service_date")
    service_date = None
    if service_date_raw is not None:
        service_date = v.parse_dt(service_date_raw, "service_date")
    items = []
    for r in db.dispatch_routes.values():
        if r["nurse_id"] != id:
            continue
        if service_date is not None and r["service_date"] != service_date:
            continue
        items.append(r)
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.dispatch_route(r) for r in page], limit, offset, total)


@bp.route("/dispatch-routes/<id>/lock", methods=["POST"])
def lock_dispatch_route(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    rec = get_or_404(db.dispatch_routes, id, "dispatch route")
    if rec["status"] != "PLANNING":
        raise err(ERR_INVALID_STATE, "Route is not PLANNING.")
    if rec["stop_count"] < 1:
        raise err(ERR_INVALID_STATE, "Route has no stops to lock.")
    rec["status"] = "LOCKED"
    db.touch(rec)
    return success(serialize.dispatch_route(rec), status=200)


@bp.route("/dispatch-routes/<id>/close", methods=["POST"])
def close_dispatch_route(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin"})
    rec = get_or_404(db.dispatch_routes, id, "dispatch route")
    if rec["status"] != "LOCKED":
        raise err(ERR_INVALID_STATE, "Route is not LOCKED.")
    for appt in db.appointments.values():
        if appt["route_id"] == id and appt["status"] not in ("COMPLETED", "CANCELLED"):
            raise err(ERR_INVALID_STATE, "Not all assigned appointments are terminal.")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return success(serialize.dispatch_route(rec), status=200)
