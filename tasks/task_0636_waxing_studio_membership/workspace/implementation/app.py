"""Waxing Studio Membership API — entry point and route registration.

Storage is in-memory only (db.py). No seeding at startup. start.sh re-invocation
wipes every byte of state because a fresh process re-imports db with empty dicts.
"""
import os

from flask import Flask, request

from db import db
from clock import clock
from errors import ApiError, err
from auth import authenticate, require_roles
from response import ok, created, list_response, error_response
from mutate import touch
from util import new_id, parse_dt
import helpers as H

import serializers as S
import membership_service as MS
import reservation_service as RS
import retail_service as RT
import sweeps
from credits import ledger_entries_for, membership_credit_balance
from strikes import member_active_strike_count

app = Flask(__name__)

ALL_ROLES = ("StudioAdmin", "FrontDesk", "Technician", "Member")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 422, "unexpected error: %s" % e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_or_404(table, rid):
    obj = table.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return obj


def _list_filtered(table, filters, principal=None, post_filter=None):
    items = list(table.values())
    for f, val in filters:
        if val is not None:
            items = [x for x in items if x.get(f) == val]
    if post_filter is not None:
        items = [x for x in items if post_filter(x)]
    items.sort(key=lambda x: (x["created_at"], x.get("_seq", 0)))
    limit, offset = H.parse_pagination()
    window, total = H.paginate(items, limit, offset)
    return window, total, limit, offset


# ===========================================================================
# Locations
# ===========================================================================
@app.route("/studio/locations", methods=["POST"])
def create_location():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    body = H.get_json()
    H.require_fields(body, ["name", "state_code"])
    name = H.require_str(body, "name")
    state_code = H.require_str(body, "state_code")
    open_mod = H.opt_int(body, "open_minute_of_day", 540)
    close_mod = H.opt_int(body, "close_minute_of_day", 1200)
    deposit = H.opt_int(body, "deposit_required_cents", 1000)
    no_show_fee = H.opt_int(body, "no_show_fee_cents", 2500)
    lid = new_id()
    now = clock.get()
    loc = {
        "id": lid, "created_at": now, "updated_at": now, "version": 1,
        "name": name, "state_code": state_code,
        "open_minute_of_day": open_mod, "close_minute_of_day": close_mod,
        "deposit_required_cents": deposit, "no_show_fee_cents": no_show_fee,
    }
    db.locations[lid] = loc
    return created(S.ser_location(loc))


@app.route("/studio/locations/<lid>", methods=["GET"])
def get_location(lid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    loc = _get_or_404(db.locations, lid)
    return ok(S.ser_location(loc))


@app.route("/studio/locations", methods=["GET"])
def list_locations():
    p = authenticate()
    require_roles(p, ALL_ROLES)
    state_code = request.args.get("state_code")
    items, total, limit, offset = _list_filtered(
        db.locations, [("state_code", state_code)])
    return list_response([S.ser_location(x) for x in items], limit, offset, total)


# ===========================================================================
# ServiceTypes
# ===========================================================================
@app.route("/studio/service-types", methods=["POST"])
def create_service_type():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    body = H.get_json()
    H.require_fields(body, ["name", "duration_minutes", "list_price_cents"])
    name = H.require_str(body, "name")
    duration = H.require_int(body, "duration_minutes")
    if duration <= 0:
        raise err("ERR_INVALID_REQUEST", "duration_minutes must be > 0")
    list_price = H.require_int(body, "list_price_cents")
    buffer_min = H.opt_int(body, "buffer_minutes", 5)
    credit_cost = H.opt_int(body, "credit_cost", 1)
    intro_eligible = H.opt_bool(body, "intro_eligible", False)
    active = H.opt_bool(body, "active", True)
    sid = new_id()
    now = clock.get()
    s = {
        "id": sid, "created_at": now, "updated_at": now, "version": 1,
        "name": name, "duration_minutes": duration, "buffer_minutes": buffer_min,
        "list_price_cents": list_price, "credit_cost": credit_cost,
        "intro_eligible": intro_eligible, "active": active,
    }
    db.service_types[sid] = s
    return created(S.ser_service_type(s))


@app.route("/studio/service-types/<sid>", methods=["GET"])
def get_service_type(sid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    s = _get_or_404(db.service_types, sid)
    return ok(S.ser_service_type(s))


@app.route("/studio/service-types", methods=["GET"])
def list_service_types():
    p = authenticate()
    require_roles(p, ALL_ROLES)
    active = request.args.get("active")
    active_val = None
    if active is not None:
        active_val = active.lower() == "true"
    items, total, limit, offset = _list_filtered(
        db.service_types, [("active", active_val)])
    return list_response([S.ser_service_type(x) for x in items], limit, offset, total)


@app.route("/studio/service-types/<sid>", methods=["PATCH"])
def update_service_type(sid):
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    s = _get_or_404(db.service_types, sid)
    body = H.get_json()
    H.require_fields(body, ["expected_servicetype_version"])
    expected = H.require_int(body, "expected_servicetype_version")
    if expected != s["version"]:
        raise err("ERR_STALE_VERSION", "stale service type version")
    if "list_price_cents" in body and body["list_price_cents"] is not None:
        s["list_price_cents"] = H.require_int(body, "list_price_cents")
    if "duration_minutes" in body and body["duration_minutes"] is not None:
        d = H.require_int(body, "duration_minutes")
        if d <= 0:
            raise err("ERR_INVALID_REQUEST", "duration_minutes must be > 0")
        s["duration_minutes"] = d
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        s["buffer_minutes"] = H.require_int(body, "buffer_minutes")
    if "credit_cost" in body and body["credit_cost"] is not None:
        s["credit_cost"] = H.require_int(body, "credit_cost")
    if "intro_eligible" in body and body["intro_eligible"] is not None:
        s["intro_eligible"] = H.opt_bool(body, "intro_eligible", s["intro_eligible"])
    if "active" in body and body["active"] is not None:
        s["active"] = H.opt_bool(body, "active", s["active"])
    touch(s)
    return ok(S.ser_service_type(s))


# ===========================================================================
# Products
# ===========================================================================
@app.route("/studio/products", methods=["POST"])
def create_product():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    body = H.get_json()
    H.require_fields(body, ["name", "unit_price_cents"])
    name = H.require_str(body, "name")
    unit_price = H.require_int(body, "unit_price_cents")
    discount_pct = H.opt_number(body, "member_discount_pct", 0.10)
    stock = H.opt_int(body, "stock_qty", 100)
    if stock < 0:
        raise err("ERR_INVALID_REQUEST", "stock_qty must be >= 0")
    pid = new_id()
    now = clock.get()
    prod = {
        "id": pid, "created_at": now, "updated_at": now, "version": 1,
        "name": name, "unit_price_cents": unit_price,
        "member_discount_pct": discount_pct, "stock_qty": stock,
    }
    db.products[pid] = prod
    return created(S.ser_product(prod))


@app.route("/studio/products/<pid>", methods=["GET"])
def get_product(pid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    prod = _get_or_404(db.products, pid)
    return ok(S.ser_product(prod))


@app.route("/studio/products", methods=["GET"])
def list_products():
    p = authenticate()
    require_roles(p, ALL_ROLES)
    items, total, limit, offset = _list_filtered(db.products, [])
    return list_response([S.ser_product(x) for x in items], limit, offset, total)


# ===========================================================================
# Rooms
# ===========================================================================
@app.route("/studio/rooms", methods=["POST"])
def create_room():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    body = H.get_json()
    H.require_fields(body, ["location_id", "label"])
    location_id = H.require_str(body, "location_id")
    label = H.require_str(body, "label")
    active = H.opt_bool(body, "active", True)
    _get_or_404(db.locations, location_id)
    rid = new_id()
    now = clock.get()
    room = {
        "id": rid, "created_at": now, "updated_at": now, "version": 1,
        "location_id": location_id, "label": label, "active": active,
    }
    db.rooms[rid] = room
    return created(S.ser_room(room))


@app.route("/studio/rooms/<rid>", methods=["GET"])
def get_room(rid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    room = _get_or_404(db.rooms, rid)
    return ok(S.ser_room(room))


@app.route("/studio/rooms", methods=["GET"])
def list_rooms():
    p = authenticate()
    require_roles(p, ALL_ROLES)
    location_id = request.args.get("location_id")
    active = request.args.get("active")
    active_val = None if active is None else active.lower() == "true"
    items, total, limit, offset = _list_filtered(
        db.rooms, [("location_id", location_id), ("active", active_val)])
    return list_response([S.ser_room(x) for x in items], limit, offset, total)


# ===========================================================================
# Technicians
# ===========================================================================
@app.route("/studio/technicians", methods=["POST"])
def create_technician():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    body = H.get_json()
    H.require_fields(body, ["location_id", "full_name"])
    location_id = H.require_str(body, "location_id")
    full_name = H.require_str(body, "full_name")
    certified = body.get("certified_service_ids")
    if certified is None:
        certified = []
    if not isinstance(certified, list) or not all(isinstance(x, str) for x in certified):
        raise err("ERR_INVALID_REQUEST", "certified_service_ids must be an array of strings")
    active = H.opt_bool(body, "active", True)
    _get_or_404(db.locations, location_id)
    tid = new_id()
    now = clock.get()
    tech = {
        "id": tid, "created_at": now, "updated_at": now, "version": 1,
        "location_id": location_id, "full_name": full_name,
        "certified_service_ids": list(certified), "active": active,
    }
    db.technicians[tid] = tech
    return created(S.ser_technician(tech))


@app.route("/studio/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    tech = _get_or_404(db.technicians, tid)
    return ok(S.ser_technician(tech))


@app.route("/studio/technicians", methods=["GET"])
def list_technicians():
    p = authenticate()
    require_roles(p, ALL_ROLES)
    location_id = request.args.get("location_id")
    active = request.args.get("active")
    active_val = None if active is None else active.lower() == "true"
    items, total, limit, offset = _list_filtered(
        db.technicians, [("location_id", location_id), ("active", active_val)])
    return list_response([S.ser_technician(x) for x in items], limit, offset, total)


# ===========================================================================
# Members
# ===========================================================================
@app.route("/studio/members", methods=["POST"])
def create_member():
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk"))
    body = H.get_json()
    H.require_fields(body, ["home_location_id", "full_name", "email"])
    home_location_id = H.require_str(body, "home_location_id")
    full_name = H.require_str(body, "full_name")
    email = H.require_str(body, "email")
    _get_or_404(db.locations, home_location_id)
    # Email uniqueness across all members (ERR_DUPLICATE_EMAIL).
    for m in db.members.values():
        if m["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "email already registered")
    mid = new_id()
    now = clock.get()
    member = {
        "id": mid, "created_at": now, "updated_at": now, "version": 1,
        "home_location_id": home_location_id, "full_name": full_name,
        "email": email, "intro_used": False, "wallet_credit_cents": 0,
    }
    db.members[mid] = member
    return created(S.ser_member(member))


@app.route("/studio/members/<mid>", methods=["GET"])
def get_member(mid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    member = _get_or_404(db.members, mid)
    return ok(S.ser_member(member))


@app.route("/studio/members", methods=["GET"])
def list_members():
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk"))
    home_location_id = request.args.get("home_location_id")
    email = request.args.get("email")
    items, total, limit, offset = _list_filtered(
        db.members, [("home_location_id", home_location_id), ("email", email)])
    return list_response([S.ser_member(x) for x in items], limit, offset, total)


# ===========================================================================
# Memberships
# ===========================================================================
@app.route("/studio/memberships", methods=["POST"])
def create_membership():
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk"))
    body = H.get_json()
    H.require_fields(body, ["member_id", "tier", "monthly_credit_grant", "monthly_fee_cents"])
    member_id = H.require_str(body, "member_id")
    tier = H.require_enum(body, "tier", ("BASIC", "PLUS", "UNLIMITED"))
    monthly_credit_grant = H.require_int(body, "monthly_credit_grant")
    monthly_fee_cents = H.require_int(body, "monthly_fee_cents")
    max_rollover = H.opt_int(body, "max_rollover_credits", 0)
    _get_or_404(db.members, member_id)
    mbid = new_id()
    now = clock.get()
    mb = {
        "id": mbid, "created_at": now, "updated_at": now, "version": 1,
        "member_id": member_id, "tier": tier,
        "monthly_credit_grant": monthly_credit_grant,
        "monthly_fee_cents": monthly_fee_cents,
        "max_rollover_credits": max_rollover,
        "status": "PENDING", "cycle_anchor_utc": None, "cycle_index": 0,
        "freeze_until_utc": None, "frozen_cycle_credits": 0,
    }
    db.memberships[mbid] = mb
    return created(S.ser_membership(mb))


@app.route("/studio/memberships/<mbid>", methods=["GET"])
def get_membership(mbid):
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    mb = _get_or_404(db.memberships, mbid)
    _membership_owner_check(p, mb)
    return ok(S.ser_membership(mb))


@app.route("/studio/memberships", methods=["GET"])
def list_memberships():
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    post = None
    if p.role == "Member":
        post = lambda x: x["member_id"] == p.user_id
    items, total, limit, offset = _list_filtered(
        db.memberships, [("member_id", member_id), ("status", status)],
        post_filter=post)
    return list_response([S.ser_membership(x) for x in items], limit, offset, total)


def _membership_owner_check(p, mb):
    if p.role == "Member" and mb["member_id"] != p.user_id:
        raise err("ERR_UNAUTHORIZED", "not your membership")


@app.route("/studio/memberships/<mbid>/activate", methods=["POST"])
def activate_membership(mbid):
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk"))
    mb = _get_or_404(db.memberships, mbid)
    MS.activate(mb)
    return ok(S.ser_membership(mb))


@app.route("/studio/memberships/<mbid>/freeze", methods=["POST"])
def freeze_membership(mbid):
    p = authenticate()
    require_roles(p, ("Member", "FrontDesk", "StudioAdmin"))
    mb = _get_or_404(db.memberships, mbid)
    _membership_owner_check(p, mb)
    body = H.get_json()
    H.require_fields(body, ["freeze_days"])
    freeze_days = H.require_int(body, "freeze_days")
    if freeze_days < 1 or freeze_days > 90:
        raise err("ERR_INVALID_REQUEST", "freeze_days must be in [1,90]")
    MS.freeze(mb, freeze_days)
    return ok(S.ser_membership(mb))


@app.route("/studio/memberships/<mbid>/unfreeze", methods=["POST"])
def unfreeze_membership(mbid):
    p = authenticate()
    require_roles(p, ("Member", "FrontDesk", "StudioAdmin"))
    mb = _get_or_404(db.memberships, mbid)
    _membership_owner_check(p, mb)
    MS.unfreeze(mb)
    return ok(S.ser_membership(mb))


@app.route("/studio/memberships/<mbid>/renew", methods=["POST"])
def renew_membership(mbid):
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk"))
    mb = _get_or_404(db.memberships, mbid)
    body = H.get_json()
    H.require_fields(body, ["payment_outcome"])
    payment_outcome = H.require_enum(body, "payment_outcome", ("SUCCEEDED", "FAILED"))
    MS.renew(mb, payment_outcome)
    return ok(S.ser_membership(mb))


@app.route("/studio/memberships/<mbid>/cancel", methods=["POST"])
def cancel_membership(mbid):
    p = authenticate()
    require_roles(p, ("Member", "FrontDesk", "StudioAdmin"))
    mb = _get_or_404(db.memberships, mbid)
    _membership_owner_check(p, mb)
    MS.cancel(mb)
    return ok(S.ser_membership(mb))


@app.route("/studio/memberships/<mbid>/ledger", methods=["GET"])
def list_ledger(mbid):
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    mb = _get_or_404(db.memberships, mbid)
    _membership_owner_check(p, mb)
    entry_type = request.args.get("entry_type")
    entries = ledger_entries_for(mbid)
    if entry_type is not None:
        entries = [e for e in entries if e["entry_type"] == entry_type]
    limit, offset = H.parse_pagination()
    window, total = H.paginate(entries, limit, offset)
    return list_response([S.ser_ledger_entry(e) for e in window], limit, offset, total)


# ===========================================================================
# Reservations
# ===========================================================================
@app.route("/studio/reservations", methods=["POST"])
def create_reservation():
    p = authenticate()
    require_roles(p, ("Member", "FrontDesk"))
    body = H.get_json()
    res = RS.create_reservation(p, body)
    return created(S.ser_reservation(res))


@app.route("/studio/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    res = _get_or_404(db.reservations, rid)
    return ok(S.ser_reservation(res))


@app.route("/studio/reservations", methods=["GET"])
def list_reservations():
    p = authenticate()
    require_roles(p, ALL_ROLES)
    filters = [
        ("member_id", request.args.get("member_id")),
        ("location_id", request.args.get("location_id")),
        ("room_id", request.args.get("room_id")),
        ("technician_id", request.args.get("technician_id")),
        ("service_type_id", request.args.get("service_type_id")),
        ("membership_id", request.args.get("membership_id")),
        ("booking_status", request.args.get("booking_status")),
    ]
    items, total, limit, offset = _list_filtered(db.reservations, filters)
    return list_response([S.ser_reservation(x) for x in items], limit, offset, total)


@app.route("/studio/reservations/<rid>/check-in", methods=["POST"])
def reservation_check_in(rid):
    p = authenticate()
    require_roles(p, ("FrontDesk",))
    res = _get_or_404(db.reservations, rid)
    RS.check_in(res)
    return ok(S.ser_reservation(res))


@app.route("/studio/reservations/<rid>/complete", methods=["POST"])
def reservation_complete(rid):
    p = authenticate()
    require_roles(p, ("FrontDesk", "Technician"))
    res = _get_or_404(db.reservations, rid)
    # Technician may complete only reservations where technician_id == X-User-ID.
    if p.role == "Technician" and res["technician_id"] != p.user_id:
        raise err("ERR_UNAUTHORIZED", "not your reservation")
    RS.complete(res)
    return ok(S.ser_reservation(res))


@app.route("/studio/reservations/<rid>/cancel", methods=["POST"])
def reservation_cancel(rid):
    p = authenticate()
    require_roles(p, ("Member", "FrontDesk"))
    res = _get_or_404(db.reservations, rid)
    if p.role == "Member" and res["member_id"] != p.user_id:
        raise err("ERR_UNAUTHORIZED", "not your reservation")
    RS.cancel(res)
    return ok(S.ser_reservation(res))


@app.route("/studio/reservations/<rid>/mark-no-show", methods=["POST"])
def reservation_mark_no_show(rid):
    p = authenticate()
    require_roles(p, ("FrontDesk",))
    res = _get_or_404(db.reservations, rid)
    RS.mark_no_show(res)
    return ok(S.ser_reservation(res))


# ===========================================================================
# Retail sales
# ===========================================================================
@app.route("/studio/retail-sales", methods=["POST"])
def create_retail_sale():
    p = authenticate()
    require_roles(p, ("Member", "FrontDesk"))
    body = H.get_json()
    H.require_fields(body, ["member_id", "reservation_id", "product_id", "quantity"])
    member_id = H.require_str(body, "member_id")
    reservation_id = H.require_str(body, "reservation_id")
    product_id = H.require_str(body, "product_id")
    quantity = H.require_int(body, "quantity")
    if quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity must be > 0")
    # Existence left-to-right: Member, then Reservation, then Product (the FK set
    # this request touches; ordering per PRD 2.9 across the resources present).
    member = db.members.get(member_id)
    if member is None:
        raise err("ERR_NOT_FOUND", "member not found")
    reservation = db.reservations.get(reservation_id)
    if reservation is None:
        raise err("ERR_NOT_FOUND", "reservation not found")
    product = db.products.get(product_id)
    if product is None:
        raise err("ERR_NOT_FOUND", "product not found")
    # Ownership: a Member may attach retail only against their own member_id.
    if p.role == "Member" and member_id != p.user_id:
        raise err("ERR_UNAUTHORIZED", "member may only attach own retail")
    rs = RT.create_retail_sale(member, reservation, product, quantity)
    return created(S.ser_retail_sale(rs))


@app.route("/studio/retail-sales/<rid>", methods=["GET"])
def get_retail_sale(rid):
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    rs = _get_or_404(db.retail_sales, rid)
    if p.role == "Member" and rs["member_id"] != p.user_id:
        raise err("ERR_UNAUTHORIZED", "not your retail sale")
    return ok(S.ser_retail_sale(rs))


@app.route("/studio/retail-sales", methods=["GET"])
def list_retail_sales():
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    filters = [
        ("member_id", request.args.get("member_id")),
        ("reservation_id", request.args.get("reservation_id")),
        ("product_id", request.args.get("product_id")),
        ("status", request.args.get("status")),
    ]
    post = None
    if p.role == "Member":
        post = lambda x: x["member_id"] == p.user_id
    items, total, limit, offset = _list_filtered(
        db.retail_sales, filters, post_filter=post)
    return list_response([S.ser_retail_sale(x) for x in items], limit, offset, total)


@app.route("/studio/retail-sales/<rid>/confirm", methods=["POST"])
def confirm_retail_sale(rid):
    p = authenticate()
    require_roles(p, ("FrontDesk",))
    rs = _get_or_404(db.retail_sales, rid)
    body = H.get_json()
    H.require_fields(body, ["expected_product_version"])
    expected = H.require_int(body, "expected_product_version")
    product = db.products[rs["product_id"]]
    if expected != product["version"]:
        raise err("ERR_STALE_VERSION", "stale product version")
    RT.confirm(rs)
    return ok(S.ser_retail_sale(rs))


@app.route("/studio/retail-sales/<rid>/void", methods=["POST"])
def void_retail_sale(rid):
    p = authenticate()
    require_roles(p, ("FrontDesk",))
    rs = _get_or_404(db.retail_sales, rid)
    RT.void(rs)
    return ok(S.ser_retail_sale(rs))


# ===========================================================================
# No-show strikes
# ===========================================================================
@app.route("/studio/no-show-strikes/<sid>", methods=["GET"])
def get_no_show_strike(sid):
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    s = _get_or_404(db.no_show_strikes, sid)
    if p.role == "Member" and s["member_id"] != p.user_id:
        raise err("ERR_UNAUTHORIZED", "not your strike")
    return ok(S.ser_no_show_strike(s))


@app.route("/studio/no-show-strikes", methods=["GET"])
def list_no_show_strikes():
    p = authenticate()
    require_roles(p, ("StudioAdmin", "FrontDesk", "Member"))
    filters = [
        ("member_id", request.args.get("member_id")),
        ("reservation_id", request.args.get("reservation_id")),
        ("status", request.args.get("status")),
    ]
    post = None
    if p.role == "Member":
        post = lambda x: x["member_id"] == p.user_id
    items, total, limit, offset = _list_filtered(
        db.no_show_strikes, filters, post_filter=post)
    return list_response([S.ser_no_show_strike(x) for x in items], limit, offset, total)


@app.route("/studio/no-show-strikes/<sid>/waive", methods=["POST"])
def waive_no_show_strike(sid):
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    s = _get_or_404(db.no_show_strikes, sid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "strike not ACTIVE")
    member = db.members[s["member_id"]]
    member["wallet_credit_cents"] += s["fee_charged_cents"]
    touch(member)
    s["status"] = "WAIVED"
    return ok(S.ser_no_show_strike(s))


# ===========================================================================
# Clock + sweeps
# ===========================================================================
@app.route("/studio/_clock/set_current_utc", methods=["POST"])
def set_clock():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    body = H.get_json()
    H.require_fields(body, ["to_iso8601"])
    new_time = parse_dt(body.get("to_iso8601"))
    clock.set(new_time)
    sweeps.run_sweeps()
    return ok({})


@app.route("/studio/_clock/run_sweeps", methods=["POST"])
def run_sweeps_endpoint():
    p = authenticate()
    require_roles(p, ("StudioAdmin",))
    sweeps.run_sweeps()
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
