"""Barbershop & Booth Rental API — Flask app, entry point + all routes.

In-memory only; store starts empty on every boot (no seeding). The logical clock
defaults to 2026-01-01T00:00:00Z.
"""
import os

from flask import Flask

import auth
import clock
import db
import errors
import money
import response as resp
import validate as v

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return resp.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return resp.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return resp.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return resp.error_response(e.error_id, e.message, e.http_status)
    return resp.error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Lookup helpers (existence checks, ordered left-to-right)
# ---------------------------------------------------------------------------
def get_shop(shop_id):
    obj = db.shops.get(shop_id)
    if obj is None:
        errors.fail(errors.ERR_SHOP_NOT_FOUND, "Shop not found.")
    return obj


def get_barber(barber_id):
    obj = db.barbers.get(barber_id)
    if obj is None:
        errors.fail(errors.ERR_BARBER_NOT_FOUND, "Barber not found.")
    return obj


def get_chair(chair_id):
    obj = db.chairs.get(chair_id)
    if obj is None:
        errors.fail(errors.ERR_CHAIR_NOT_FOUND, "Chair not found.")
    return obj


def get_shift(shift_id):
    obj = db.shifts.get(shift_id)
    if obj is None:
        errors.fail(errors.ERR_SHIFT_NOT_FOUND, "Shift not found.")
    return obj


def get_service(service_id):
    obj = db.services.get(service_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Service not found.")
    return obj


def get_addon(addon_id):
    obj = db.addons.get(addon_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Add-on not found.")
    return obj


def get_product(product_id):
    obj = db.products.get(product_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Product not found.")
    return obj


def get_membership(membership_id):
    obj = db.memberships.get(membership_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Membership not found.")
    return obj


def get_customer(customer_id):
    obj = db.customers.get(customer_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Customer not found.")
    return obj


def get_appointment(appointment_id):
    obj = db.appointments.get(appointment_id)
    if obj is None:
        errors.fail(errors.ERR_APPOINTMENT_NOT_FOUND, "Appointment not found.")
    return obj


def get_queue_ticket(queue_ticket_id):
    obj = db.queue_tickets.get(queue_ticket_id)
    if obj is None:
        errors.fail(errors.ERR_QUEUE_TICKET_NOT_FOUND, "Queue ticket not found.")
    return obj


def get_ticket(ticket_id):
    obj = db.tickets.get(ticket_id)
    if obj is None:
        errors.fail(errors.ERR_TICKET_NOT_FOUND, "Ticket not found.")
    return obj


def get_settlement(settlement_id):
    obj = db.settlements.get(settlement_id)
    if obj is None:
        errors.fail(errors.ERR_SETTLEMENT_NOT_FOUND, "Settlement not found.")
    return obj


# Body-FK resolution within a shop (priority-4 existence => ERR_REFERENCED_ENTITY_NOT_FOUND)
def ref_in_shop(collection, ent_id, shop_id):
    obj = collection.get(ent_id)
    if obj is None or obj.get("shop_id") != shop_id:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Referenced entity not found in shop.")
    return obj


# ---------------------------------------------------------------------------
# Ownership enforcement for entity-backed roles (Barber / Customer)
# ---------------------------------------------------------------------------
def enforce_customer_owns(role, uid, customer_id):
    if role == "Customer" and uid != customer_id:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Customer may act only on their own records.")


def enforce_barber_owns(role, uid, barber_id):
    if role == "Barber" and uid != barber_id:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Barber may read only their own records.")


# ===========================================================================
# Generic list helper
# ===========================================================================
def list_collection(collection, filters=None):
    items = list(collection.values())
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [o for o in items if o.get(key) == val]
    return items


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    iso = v.as_str(data, "to_iso8601", required=True)
    try:
        clock.set_current(iso)
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant.")
    return resp.success_object({}, 200)


# ===========================================================================
# Shop
# ===========================================================================
@app.route("/shops", methods=["POST"])
def create_shop():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    name = v.as_str(data, "name", required=True)
    tax_rate_pct = v.as_number(data, "tax_rate_pct", required=True, min_v=0, max_v=30)
    default_booth_rent_cents = v.as_int(data, "default_booth_rent_cents", required=True, min_v=0)
    default_commission_pct = v.as_number(data, "default_commission_pct", required=True, min_v=0, max_v=100)
    product_commission_pct = v.as_number(data, "product_commission_pct", required=False, default=0, min_v=0, max_v=100)
    no_show_fee_cents = v.as_int(data, "no_show_fee_cents", required=False, default=0, min_v=0)
    no_show_strike_limit = v.as_int(data, "no_show_strike_limit", required=False, default=3, min_v=1)
    late_grace_minutes = v.as_int(data, "late_grace_minutes", required=False, default=10, min_v=0)
    punch_reward_threshold = v.as_int(data, "punch_reward_threshold", required=False, default=10, min_v=1)
    punch_reward_value_cents = v.as_int(data, "punch_reward_value_cents", required=False, default=0, min_v=0)

    obj = {
        "id": db.new_id(),
        "name": name,
        "tax_rate_pct": tax_rate_pct,
        "default_booth_rent_cents": default_booth_rent_cents,
        "default_commission_pct": default_commission_pct,
        "product_commission_pct": product_commission_pct,
        "no_show_fee_cents": no_show_fee_cents,
        "no_show_strike_limit": no_show_strike_limit,
        "late_grace_minutes": late_grace_minutes,
        "punch_reward_threshold": punch_reward_threshold,
        "punch_reward_value_cents": punch_reward_value_cents,
        "status": "OPEN",
        "gross_service_revenue_cents": 0,
        "gross_product_revenue_cents": 0,
    }
    db.stamp_create(obj)
    db.shops[obj["id"]] = obj
    return resp.success_object(db.public(obj), 201)


@app.route("/shops", methods=["GET"])
def list_shops():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    items, meta = v.paginate(list_collection(db.shops))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/shops/<shop_id>", methods=["GET"])
def read_shop(shop_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = get_shop(shop_id)
    return resp.success_object(db.public(obj))


@app.route("/shops/<shop_id>/close", methods=["POST"])
def close_shop(shop_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    shop = get_shop(shop_id)
    # Precondition: no CHECKED_IN appointment and no OPEN ticket in this shop.
    for appt in db.appointments.values():
        if appt["shop_id"] == shop_id and appt["status"] == "CHECKED_IN":
            errors.fail(errors.ERR_OPEN_TICKETS_EXIST, "Open tickets / checked-in appointments exist.")
    for tk in db.tickets.values():
        if tk["shop_id"] == shop_id and tk["status"] == "OPEN":
            errors.fail(errors.ERR_OPEN_TICKETS_EXIST, "Open tickets exist.")
    shop["status"] = "CLOSED"
    db.touch(shop)
    return resp.success_object(db.public(shop))


@app.route("/shops/<shop_id>/reopen", methods=["POST"])
def reopen_shop(shop_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    shop = get_shop(shop_id)
    shop["status"] = "OPEN"
    db.touch(shop)
    return resp.success_object(db.public(shop))


# ===========================================================================
# Barber
# ===========================================================================
@app.route("/barbers", methods=["POST"])
def create_barber():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    full_name = v.as_str(data, "full_name", required=True)
    license_number = v.as_str(data, "license_number", required=True)
    license_expires_on = v.as_str(data, "license_expires_on", required=True)
    # Validate it is a real date.
    v.parse_iso_date(license_expires_on, "license_expires_on")
    comp_model = v.as_enum(data, "comp_model", {"BOOTH_RENT", "COMMISSION"}, required=True)
    booth_rent_cents = v.as_int(data, "booth_rent_cents", required=False, default=None, min_v=0)
    commission_pct = v.as_number(data, "commission_pct", required=False, default=None, min_v=0, max_v=100)

    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    shop = db.shops[shop_id]

    if booth_rent_cents is None:
        booth_rent_cents = shop["default_booth_rent_cents"]
    if commission_pct is None:
        commission_pct = shop["default_commission_pct"]

    obj = {
        "id": db.new_id(),
        "shop_id": shop_id,
        "full_name": full_name,
        "license_number": license_number,
        "license_expires_on": license_expires_on,
        "comp_model": comp_model,
        "booth_rent_cents": booth_rent_cents,
        "commission_pct": commission_pct,
        "license_status": "PENDING",
        "unsettled_revenue_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(obj)
    db.barbers[obj["id"]] = obj
    return resp.success_object(db.public(obj), 201)


@app.route("/barbers", methods=["GET"])
def list_barbers():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    shop_id = request.args.get("shop_id")
    items, meta = v.paginate(list_collection(db.barbers, {"shop_id": shop_id}))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/barbers/<barber_id>", methods=["GET"])
def read_barber(barber_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = get_barber(barber_id)
    enforce_barber_owns(role, _uid(), barber_id)
    return resp.success_object(db.public(obj))


def _uid():
    from flask import request
    return request.headers.get("X-User-ID")


def _activate(barber):
    # license_expires_on >= clock date else ERR_LICENSE_EXPIRED
    exp = v.parse_iso_date(barber["license_expires_on"], "license_expires_on")
    if exp < clock.now().date():
        errors.fail(errors.ERR_LICENSE_EXPIRED, "License is expired.")
    barber["license_status"] = "ACTIVE"
    db.touch(barber)


@app.route("/barbers/<barber_id>/license/activate", methods=["POST"])
def activate_license(barber_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    barber = get_barber(barber_id)
    if barber["license_status"] not in ("PENDING", "SUSPENDED"):
        errors.fail(errors.ERR_INVALID_STATE, "License cannot be activated from current state.")
    _activate(barber)
    return resp.success_object(db.public(barber))


@app.route("/barbers/<barber_id>/license/suspend", methods=["POST"])
def suspend_license(barber_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    barber = get_barber(barber_id)
    if barber["license_status"] != "ACTIVE":
        errors.fail(errors.ERR_INVALID_STATE, "Only an ACTIVE license can be suspended.")
    barber["license_status"] = "SUSPENDED"
    db.touch(barber)
    # Cascade: cancel future BOOKED appointments (start_utc > clock), no fee.
    now = clock.now()
    for appt in db.appointments.values():
        if appt["barber_id"] == barber_id and appt["status"] == "BOOKED":
            if v.parse_iso_dt(appt["start_utc"]) > now:
                appt["status"] = "CANCELLED"
                db.touch(appt)
    return resp.success_object(db.public(barber))


@app.route("/barbers/<barber_id>/license/revoke", methods=["POST"])
def revoke_license(barber_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    barber = get_barber(barber_id)
    if barber["license_status"] == "REVOKED":
        errors.fail(errors.ERR_INVALID_STATE, "License already revoked.")
    barber["license_status"] = "REVOKED"
    db.touch(barber)
    now = clock.now()
    # Cascade 1: future SCHEDULED shifts (end_utc > clock) -> CANCELLED.
    for shift in db.shifts.values():
        if shift["barber_id"] == barber_id and shift["status"] == "SCHEDULED":
            if v.parse_iso_dt(shift["end_utc"]) > now:
                shift["status"] = "CANCELLED"
                db.touch(shift)
    # Cascade 2: every BOOKED appointment -> CANCELLED, no fee.
    for appt in db.appointments.values():
        if appt["barber_id"] == barber_id and appt["status"] == "BOOKED":
            appt["status"] = "CANCELLED"
            db.touch(appt)
    return resp.success_object(db.public(barber))


# ===========================================================================
# Chair
# ===========================================================================
@app.route("/chairs", methods=["POST"])
def create_chair():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    label = v.as_str(data, "label", required=True)
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    obj = {"id": db.new_id(), "shop_id": shop_id, "label": label, "status": "AVAILABLE"}
    db.stamp_create(obj)
    db.chairs[obj["id"]] = obj
    return resp.success_object(db.public(obj), 201)


@app.route("/chairs", methods=["GET"])
def list_chairs():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    items, meta = v.paginate(list_collection(db.chairs, {"shop_id": request.args.get("shop_id")}))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/chairs/<chair_id>", methods=["GET"])
def read_chair(chair_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    return resp.success_object(db.public(get_chair(chair_id)))


# ===========================================================================
# BarberShift
# ===========================================================================
@app.route("/shifts", methods=["POST"])
def create_shift():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    barber_id = v.as_str(data, "barber_id", required=True)
    chair_id = v.as_str(data, "chair_id", required=True)
    start_dt = v.parse_dt(data, "start_utc", required=True)
    end_dt = v.parse_dt(data, "end_utc", required=True)
    expected_shop_version = v.as_int(data, "expected_shop_version", required=True)

    # Body FK existence within shop.
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    ref_in_shop(db.barbers, barber_id, shop_id)
    ref_in_shop(db.chairs, chair_id, shop_id)

    # Body well-formed: end_utc > start_utc.
    if not (end_dt > start_dt):
        errors.fail(errors.ERR_INVALID_REQUEST, "end_utc must be strictly later than start_utc.")

    shop = db.shops[shop_id]
    # OCC on shop version.
    if expected_shop_version != shop["version"]:
        errors.fail(errors.ERR_STALE_SHOP_VERSION, "Stale shop version.")

    # Closed-buffer overlap on same chair among SCHEDULED shifts:
    #   earlier.end + grace <= later.start
    grace = shop["late_grace_minutes"]
    from datetime import timedelta
    buf = timedelta(minutes=grace)
    for s in db.shifts.values():
        if s["chair_id"] != chair_id or s["status"] != "SCHEDULED":
            continue
        s_start = v.parse_iso_dt(s["start_utc"])
        s_end = v.parse_iso_dt(s["end_utc"])
        # OK only if new is fully before s with buffer, or fully after s with buffer.
        before = end_dt + buf <= s_start
        after = s_end + buf <= start_dt
        if not (before or after):
            errors.fail(errors.ERR_SHIFT_OVERLAP, "Shift violates the closed-buffer gap on this chair.")

    obj = {
        "id": db.new_id(),
        "shop_id": shop_id,
        "barber_id": barber_id,
        "chair_id": chair_id,
        "start_utc": data["start_utc"],
        "end_utc": data["end_utc"],
        "status": "SCHEDULED",
    }
    db.stamp_create(obj)
    db.shifts[obj["id"]] = obj
    # Side effect: bump shop version.
    db.touch(shop)
    return resp.success_object(db.public(obj), 201)


@app.route("/shifts", methods=["GET"])
def list_shifts():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    filters = {
        "shop_id": request.args.get("shop_id"),
        "barber_id": request.args.get("barber_id"),
        "chair_id": request.args.get("chair_id"),
    }
    items, meta = v.paginate(list_collection(db.shifts, filters))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/shifts/<shift_id>", methods=["GET"])
def read_shift(shift_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    return resp.success_object(db.public(get_shift(shift_id)))


@app.route("/shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift(shift_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    shift = get_shift(shift_id)
    if shift["status"] != "SCHEDULED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a SCHEDULED shift can be cancelled.")
    # Precondition: no BOOKED/CHECKED_IN appt within window on same chair.
    s_start = v.parse_iso_dt(shift["start_utc"])
    s_end = v.parse_iso_dt(shift["end_utc"])
    for appt in db.appointments.values():
        if appt["chair_id"] != shift["chair_id"]:
            continue
        if appt["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        a_start = v.parse_iso_dt(appt["start_utc"])
        a_end = v.parse_iso_dt(appt["end_utc"])
        # Slot lies within shift window [s_start, s_end).
        if s_start <= a_start and a_end <= s_end:
            errors.fail(errors.ERR_SHIFT_HAS_APPOINTMENTS, "Shift still contains an appointment.")
    shift["status"] = "CANCELLED"
    db.touch(shift)
    return resp.success_object(db.public(shift))


# ===========================================================================
# Catalog: Services, AddOns, Products, Memberships
# ===========================================================================
def _create_catalog_item(collection, builder):
    obj = builder()
    db.stamp_create(obj)
    collection[obj["id"]] = obj
    return resp.success_object(db.public(obj), 201)


@app.route("/services", methods=["POST"])
def create_service():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    name = v.as_str(data, "name", required=True)
    price_cents = v.as_int(data, "price_cents", required=True, min_v=0)
    duration_minutes = v.as_int(data, "duration_minutes", required=True, min_v=1)
    membership_included = v.as_bool(data, "membership_included", required=False, default=False)
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    return _create_catalog_item(db.services, lambda: {
        "id": db.new_id(), "shop_id": shop_id, "name": name, "price_cents": price_cents,
        "duration_minutes": duration_minutes, "membership_included": membership_included,
        "status": "LISTED",
    })


@app.route("/services", methods=["GET"])
def list_services():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    items, meta = v.paginate(list_collection(db.services, {"shop_id": request.args.get("shop_id")}))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/services/<service_id>", methods=["GET"])
def read_service(service_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = db.services.get(service_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Service not found.")
    return resp.success_object(db.public(obj))


@app.route("/services/<service_id>/delist", methods=["POST"])
def delist_service(service_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    obj = db.services.get(service_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Service not found.")
    obj["status"] = "DELISTED"
    db.touch(obj)
    return resp.success_object(db.public(obj))


@app.route("/addons", methods=["POST"])
def create_addon():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    name = v.as_str(data, "name", required=True)
    price_cents = v.as_int(data, "price_cents", required=True, min_v=0)
    extra_minutes = v.as_int(data, "extra_minutes", required=False, default=0, min_v=0)
    membership_discount_pct = v.as_number(data, "membership_discount_pct", required=False, default=0, min_v=0, max_v=100)
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    return _create_catalog_item(db.addons, lambda: {
        "id": db.new_id(), "shop_id": shop_id, "name": name, "price_cents": price_cents,
        "extra_minutes": extra_minutes, "membership_discount_pct": membership_discount_pct,
        "status": "LISTED",
    })


@app.route("/addons", methods=["GET"])
def list_addons():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    items, meta = v.paginate(list_collection(db.addons, {"shop_id": request.args.get("shop_id")}))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/addons/<addon_id>", methods=["GET"])
def read_addon(addon_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = db.addons.get(addon_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Add-on not found.")
    return resp.success_object(db.public(obj))


@app.route("/addons/<addon_id>/delist", methods=["POST"])
def delist_addon(addon_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    obj = db.addons.get(addon_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Add-on not found.")
    obj["status"] = "DELISTED"
    db.touch(obj)
    return resp.success_object(db.public(obj))


@app.route("/products", methods=["POST"])
def create_product():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    name = v.as_str(data, "name", required=True)
    price_cents = v.as_int(data, "price_cents", required=True, min_v=0)
    stock_qty = v.as_int(data, "stock_qty", required=False, default=0, min_v=0)
    commission_eligible = v.as_bool(data, "commission_eligible", required=False, default=False)
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    return _create_catalog_item(db.products, lambda: {
        "id": db.new_id(), "shop_id": shop_id, "name": name, "price_cents": price_cents,
        "stock_qty": stock_qty, "commission_eligible": commission_eligible, "status": "LISTED",
    })


@app.route("/products", methods=["GET"])
def list_products():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    items, meta = v.paginate(list_collection(db.products, {"shop_id": request.args.get("shop_id")}))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/products/<product_id>", methods=["GET"])
def read_product(product_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = db.products.get(product_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Product not found.")
    return resp.success_object(db.public(obj))


@app.route("/products/<product_id>/delist", methods=["POST"])
def delist_product(product_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    obj = db.products.get(product_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Product not found.")
    obj["status"] = "DELISTED"
    db.touch(obj)
    return resp.success_object(db.public(obj))


@app.route("/memberships", methods=["POST"])
def create_membership():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    name = v.as_str(data, "name", required=True)
    monthly_fee_cents = v.as_int(data, "monthly_fee_cents", required=True, min_v=0)
    addon_discount_pct = v.as_number(data, "addon_discount_pct", required=False, default=0, min_v=0, max_v=100)
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    return _create_catalog_item(db.memberships, lambda: {
        "id": db.new_id(), "shop_id": shop_id, "name": name, "monthly_fee_cents": monthly_fee_cents,
        "addon_discount_pct": addon_discount_pct, "status": "OFFERED",
    })


@app.route("/memberships", methods=["GET"])
def list_memberships():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    items, meta = v.paginate(list_collection(db.memberships, {"shop_id": request.args.get("shop_id")}))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/memberships/<membership_id>", methods=["GET"])
def read_membership(membership_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = db.memberships.get(membership_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Membership not found.")
    return resp.success_object(db.public(obj))


@app.route("/memberships/<membership_id>/retire", methods=["POST"])
def retire_membership(membership_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    obj = db.memberships.get(membership_id)
    if obj is None:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Membership not found.")
    obj["status"] = "RETIRED"
    db.touch(obj)
    return resp.success_object(db.public(obj))


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    full_name = v.as_str(data, "full_name", required=True)
    email = v.as_str(data, "email", required=True)
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    # Email unique within the shop.
    for c in db.customers.values():
        if c["shop_id"] == shop_id and c["email"] == email:
            errors.fail(errors.ERR_INVALID_REQUEST, "Email already used in this shop.")
    obj = {
        "id": db.new_id(), "shop_id": shop_id, "full_name": full_name, "email": email,
        "membership_id": None, "membership_status": "NONE", "punch_count": 0,
        "reward_credits": 0, "no_show_strikes": 0, "status": "ACTIVE",
    }
    db.stamp_create(obj)
    db.customers[obj["id"]] = obj
    return resp.success_object(db.public(obj), 201)


@app.route("/customers", methods=["GET"])
def list_customers():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    from flask import request
    filters = {
        "shop_id": request.args.get("shop_id"),
        "membership_id": request.args.get("membership_id"),
    }
    items, meta = v.paginate(list_collection(db.customers, filters))
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/customers/<customer_id>", methods=["GET"])
def read_customer(customer_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Customer"})
    obj = get_customer_path(customer_id)
    enforce_customer_owns(role, _uid(), customer_id)
    return resp.success_object(db.public(obj))


def get_customer_path(customer_id):
    obj = db.customers.get(customer_id)
    if obj is None:
        # Customer is a path resource here; but there is no dedicated not-found in path
        # set for customer. Use referenced-entity per scaffold existence ordering.
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "Customer not found.")
    return obj


@app.route("/customers/<customer_id>/subscribe", methods=["POST"])
def subscribe_customer(customer_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Customer"})
    customer = get_customer_path(customer_id)
    enforce_customer_owns(role, _uid(), customer_id)
    data = v.body()
    membership_id = v.as_str(data, "membership_id", required=True)
    plan = db.memberships.get(membership_id)
    if plan is None or plan["shop_id"] != customer["shop_id"]:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "membership_id not found in shop.")
    if plan["status"] != "OFFERED":
        errors.fail(errors.ERR_ITEM_DELISTED, "Membership plan is retired.")
    customer["membership_id"] = membership_id
    customer["membership_status"] = "ACTIVE"
    db.touch(customer)
    return resp.success_object(db.public(customer))


# ===========================================================================
# Appointment
# ===========================================================================
def _slot_end(start_dt, service, addon_objs):
    from datetime import timedelta
    minutes = service["duration_minutes"] + sum(a["extra_minutes"] for a in addon_objs)
    return start_dt + timedelta(minutes=minutes)


def _to_iso_z(dt):
    # Emit ISO 8601 UTC with Z suffix; drop microseconds when zero for cleanliness.
    dt = dt.astimezone(__import__("datetime").timezone.utc)
    if dt.microsecond:
        s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    else:
        s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + "Z"


@app.route("/appointments", methods=["POST"])
def create_appointment():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Customer"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    customer_id = v.as_str(data, "customer_id", required=True)
    barber_id = v.as_str(data, "barber_id", required=True)
    chair_id = v.as_str(data, "chair_id", required=True)
    service_item_id = v.as_str(data, "service_item_id", required=True)
    addon_ids = v.as_str_list(data, "addon_ids", default=[])
    start_dt = v.parse_dt(data, "start_utc", required=True)

    # Body FK existence within shop.
    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    shop = db.shops[shop_id]
    customer = ref_in_shop(db.customers, customer_id, shop_id)
    # Customer role ownership: may only book for self.
    enforce_customer_owns(role, _uid(), customer_id)
    barber = ref_in_shop(db.barbers, barber_id, shop_id)
    ref_in_shop(db.chairs, chair_id, shop_id)
    service = ref_in_shop(db.services, service_item_id, shop_id)
    addon_objs = [ref_in_shop(db.addons, aid, shop_id) for aid in addon_ids]

    # State / business checks (after structural).
    # Shop OPEN.
    if shop["status"] != "OPEN":
        errors.fail(errors.ERR_SHOP_CLOSED, "Shop is closed.")
    # Catalog LISTED.
    if service["status"] != "LISTED":
        errors.fail(errors.ERR_ITEM_DELISTED, "Service is delisted.")
    for a in addon_objs:
        if a["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "Add-on is delisted.")
    # Barber ACTIVE.
    if barber["license_status"] != "ACTIVE":
        errors.fail(errors.ERR_BARBER_NOT_ACTIVE, "Barber license is not active.")
    # Customer ACTIVE.
    if customer["status"] != "ACTIVE":
        errors.fail(errors.ERR_CUSTOMER_SUSPENDED, "Customer is suspended.")

    end_dt = _slot_end(start_dt, service, addon_objs)

    # Temporal: slot fully within one SCHEDULED shift of same barber on same chair.
    contained = False
    for shift in db.shifts.values():
        if shift["status"] != "SCHEDULED":
            continue
        if shift["barber_id"] != barber_id or shift["chair_id"] != chair_id:
            continue
        s_start = v.parse_iso_dt(shift["start_utc"])
        s_end = v.parse_iso_dt(shift["end_utc"])
        if s_start <= start_dt and end_dt <= s_end:
            contained = True
            break
    if not contained:
        errors.fail(errors.ERR_OUTSIDE_SHIFT, "Slot not within a scheduled shift.")

    # Temporal: no overlap with non-terminal appt on same chair (half-open).
    for appt in db.appointments.values():
        if appt["chair_id"] != chair_id:
            continue
        if appt["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        a_start = v.parse_iso_dt(appt["start_utc"])
        a_end = v.parse_iso_dt(appt["end_utc"])
        # Half-open overlap: start < a_end and a_start < end.
        if start_dt < a_end and a_start < end_dt:
            errors.fail(errors.ERR_CHAIR_DOUBLE_BOOKED, "Chair is double-booked.")

    obj = {
        "id": db.new_id(),
        "shop_id": shop_id,
        "customer_id": customer_id,
        "barber_id": barber_id,
        "chair_id": chair_id,
        "service_item_id": service_item_id,
        "addon_ids": list(addon_ids),
        "start_utc": data["start_utc"],
        "end_utc": _to_iso_z(end_dt),
        "check_in_punctuality": "UNSET",
        "ticket_id": None,
        "status": "BOOKED",
    }
    db.stamp_create(obj)
    db.appointments[obj["id"]] = obj
    return resp.success_object(db.public(obj), 201)


@app.route("/appointments", methods=["GET"])
def list_appointments():
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    filters = {
        "shop_id": request.args.get("shop_id"),
        "customer_id": request.args.get("customer_id"),
        "barber_id": request.args.get("barber_id"),
        "chair_id": request.args.get("chair_id"),
        "service_item_id": request.args.get("service_item_id"),
        "ticket_id": request.args.get("ticket_id"),
    }
    items = list_collection(db.appointments, filters)
    # Entity-backed scoping: Customer -> own; Barber -> own.
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
    elif role == "Barber":
        items = [o for o in items if o["barber_id"] == uid]
    items, meta = v.paginate(items)
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/appointments/<appointment_id>", methods=["GET"])
def read_appointment(appointment_id):
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = get_appointment(appointment_id)
    if role == "Customer" and obj["customer_id"] != uid:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your appointment.")
    if role == "Barber" and obj["barber_id"] != uid:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your appointment.")
    return resp.success_object(db.public(obj))


@app.route("/appointments/<appointment_id>/check-in", methods=["POST"])
def check_in_appointment(appointment_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    appt = get_appointment(appointment_id)
    shop = db.shops[appt["shop_id"]]
    if shop["status"] != "OPEN":
        errors.fail(errors.ERR_SHOP_CLOSED, "Shop is closed.")
    if appt["status"] != "BOOKED":
        errors.fail(errors.ERR_INVALID_STATE, "Appointment is not BOOKED.")
    barber = db.barbers[appt["barber_id"]]
    if barber["license_status"] != "ACTIVE":
        errors.fail(errors.ERR_BARBER_NOT_ACTIVE, "Barber license is not active.")
    customer = db.customers[appt["customer_id"]]
    if customer["status"] != "ACTIVE":
        errors.fail(errors.ERR_CUSTOMER_SUSPENDED, "Customer is suspended.")

    from datetime import timedelta
    now = clock.now()
    start_dt = v.parse_iso_dt(appt["start_utc"])
    grace = shop["late_grace_minutes"]
    punctuality = "ON_TIME" if now <= start_dt + timedelta(minutes=grace) else "LATE"

    # Open the ticket seeded with service + addons.
    business_date = clock.now_date()
    ticket = {
        "id": db.new_id(),
        "shop_id": appt["shop_id"],
        "customer_id": appt["customer_id"],
        "barber_id": appt["barber_id"],
        "appointment_id": appt["id"],
        "queue_ticket_id": None,
        "business_date": business_date,
        "service_line_ids": [appt["service_item_id"]] if appt["service_item_id"] else [],
        "addon_line_ids": list(appt["addon_ids"]),
        "product_lines": [],
        "redeem_reward": False,
        "tip_cents": 0,
        "service_net_cents": 0,
        "product_net_cents": 0,
        "tax_cents": 0,
        "total_due_cents": 0,
        "status": "OPEN",
    }
    db.stamp_create(ticket)
    db.tickets[ticket["id"]] = ticket

    appt["status"] = "CHECKED_IN"
    appt["ticket_id"] = ticket["id"]
    appt["check_in_punctuality"] = punctuality
    db.touch(appt)
    return resp.success_object(db.public(appt))


@app.route("/appointments/<appointment_id>/no-show", methods=["POST"])
def no_show_appointment(appointment_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    appt = get_appointment(appointment_id)
    shop = db.shops[appt["shop_id"]]
    if shop["status"] != "OPEN":
        errors.fail(errors.ERR_SHOP_CLOSED, "Shop is closed.")
    if appt["status"] != "BOOKED":
        errors.fail(errors.ERR_INVALID_STATE, "Appointment is not BOOKED.")

    from datetime import timedelta
    now = clock.now()
    start_dt = v.parse_iso_dt(appt["start_utc"])
    grace = shop["late_grace_minutes"]
    if now < start_dt + timedelta(minutes=grace):
        errors.fail(errors.ERR_NO_SHOW_TOO_EARLY, "Too early to mark no-show.")

    appt["status"] = "NO_SHOW"
    db.touch(appt)

    customer = db.customers[appt["customer_id"]]
    customer["no_show_strikes"] = customer["no_show_strikes"] + 1
    if customer["no_show_strikes"] >= shop["no_show_strike_limit"]:
        customer["status"] = "SUSPENDED"
    db.touch(customer)

    # No-show fee ticket if configured.
    if shop["no_show_fee_cents"] > 0:
        fee = shop["no_show_fee_cents"]
        ticket = {
            "id": db.new_id(),
            "shop_id": appt["shop_id"],
            "customer_id": appt["customer_id"],
            "barber_id": appt["barber_id"],
            "appointment_id": appt["id"],
            "queue_ticket_id": None,
            "business_date": clock.now_date(),
            "service_line_ids": [],
            "addon_line_ids": [],
            "product_lines": [],
            "redeem_reward": False,
            "tip_cents": 0,
            "service_net_cents": 0,
            "product_net_cents": 0,
            "tax_cents": 0,
            "total_due_cents": fee,
            "status": "PAID",
        }
        db.stamp_create(ticket)
        db.tickets[ticket["id"]] = ticket
    return resp.success_object(db.public(appt))


@app.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Customer"})
    appt = get_appointment(appointment_id)
    if role == "Customer" and appt["customer_id"] != uid:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your appointment.")
    if appt["status"] != "BOOKED":
        errors.fail(errors.ERR_INVALID_STATE, "Appointment is not BOOKED.")
    now = clock.now()
    start_dt = v.parse_iso_dt(appt["start_utc"])
    if now >= start_dt:
        errors.fail(errors.ERR_CANCEL_TOO_LATE, "Too late to cancel.")
    appt["status"] = "CANCELLED"
    db.touch(appt)
    return resp.success_object(db.public(appt))


# ===========================================================================
# QueueTicket
# ===========================================================================
def _recompute_queue_positions(shop_id):
    waiting = [q for q in db.queue_tickets.values()
               if q["shop_id"] == shop_id and q["status"] == "WAITING"]
    waiting.sort(key=lambda q: q.get("_seq", 0))
    for i, q in enumerate(waiting, start=1):
        if q["queue_position"] != i:
            q["queue_position"] = i
            # position recompute is a denormalized derived field refresh
            db.touch(q)
        else:
            q["queue_position"] = i


@app.route("/queue", methods=["POST"])
def enqueue():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Customer"})
    data = v.body()
    shop_id = v.as_str(data, "shop_id", required=True)
    customer_id = v.as_str(data, "customer_id", required=True)
    requested_barber_id = v.as_str(data, "requested_barber_id", required=False, default=None)

    if shop_id not in db.shops:
        errors.fail(errors.ERR_REFERENCED_ENTITY_NOT_FOUND, "shop_id not found.")
    shop = db.shops[shop_id]
    customer = ref_in_shop(db.customers, customer_id, shop_id)
    enforce_customer_owns(role, _uid(), customer_id)
    if requested_barber_id is not None:
        ref_in_shop(db.barbers, requested_barber_id, shop_id)

    if shop["status"] != "OPEN":
        errors.fail(errors.ERR_SHOP_CLOSED, "Shop is closed.")
    if customer["status"] != "ACTIVE":
        errors.fail(errors.ERR_CUSTOMER_SUSPENDED, "Customer is suspended.")

    obj = {
        "id": db.new_id(),
        "shop_id": shop_id,
        "customer_id": customer_id,
        "requested_barber_id": requested_barber_id,
        "queue_position": 0,
        "assigned_barber_id": None,
        "ticket_id": None,
        "status": "WAITING",
    }
    db.stamp_create(obj)
    db.queue_tickets[obj["id"]] = obj
    _recompute_queue_positions(shop_id)
    return resp.success_object(db.public(obj), 201)


@app.route("/queue", methods=["GET"])
def list_queue():
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    from flask import request
    filters = {
        "shop_id": request.args.get("shop_id"),
        "customer_id": request.args.get("customer_id"),
        "requested_barber_id": request.args.get("requested_barber_id"),
        "assigned_barber_id": request.args.get("assigned_barber_id"),
        "ticket_id": request.args.get("ticket_id"),
    }
    items = list_collection(db.queue_tickets, filters)
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
    elif role == "Barber":
        items = [o for o in items if o.get("assigned_barber_id") == uid or o.get("requested_barber_id") == uid]
    items, meta = v.paginate(items)
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/queue/<queue_ticket_id>", methods=["GET"])
def read_queue(queue_ticket_id):
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber", "Customer"})
    obj = get_queue_ticket(queue_ticket_id)
    if role == "Customer" and obj["customer_id"] != uid:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your queue ticket.")
    return resp.success_object(db.public(obj))


@app.route("/queue/<queue_ticket_id>/serve", methods=["POST"])
def serve_queue(queue_ticket_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    q = get_queue_ticket(queue_ticket_id)
    shop = db.shops[q["shop_id"]]
    if shop["status"] != "OPEN":
        errors.fail(errors.ERR_SHOP_CLOSED, "Shop is closed.")
    if q["status"] != "WAITING":
        errors.fail(errors.ERR_INVALID_STATE, "Queue ticket is not WAITING.")

    # Front-of-line check.
    waiting = [x for x in db.queue_tickets.values()
               if x["shop_id"] == q["shop_id"] and x["status"] == "WAITING"]
    waiting.sort(key=lambda x: x.get("_seq", 0))
    if q["requested_barber_id"] is not None:
        scoped = [x for x in waiting if x["requested_barber_id"] == q["requested_barber_id"]]
        front = scoped[0] if scoped else None
        if front is None or front["id"] != q["id"]:
            errors.fail(errors.ERR_NOT_QUEUE_FRONT, "Not the front of the queue.")
    else:
        if not waiting or waiting[0]["id"] != q["id"]:
            errors.fail(errors.ERR_NOT_QUEUE_FRONT, "Not the front of the queue.")

    # Resolve assigned barber.
    if q["requested_barber_id"] is not None:
        barber = db.barbers[q["requested_barber_id"]]
    else:
        # ACTIVE barber in the shop with fewest SERVING tickets, tie-break created_at ASC.
        candidates = [b for b in db.barbers.values()
                      if b["shop_id"] == q["shop_id"] and b["license_status"] == "ACTIVE"]
        if not candidates:
            errors.fail(errors.ERR_BARBER_NOT_ACTIVE, "No active barber available.")

        def serving_count(b):
            return sum(1 for qt in db.queue_tickets.values()
                       if qt["status"] == "SERVING" and qt.get("assigned_barber_id") == b["id"])

        candidates.sort(key=lambda b: (serving_count(b), b.get("_seq", 0)))
        barber = candidates[0]

    if barber["license_status"] != "ACTIVE":
        errors.fail(errors.ERR_BARBER_NOT_ACTIVE, "Resolved barber is not active.")

    # Open a sales ticket.
    ticket = {
        "id": db.new_id(),
        "shop_id": q["shop_id"],
        "customer_id": q["customer_id"],
        "barber_id": barber["id"],
        "appointment_id": None,
        "queue_ticket_id": q["id"],
        "business_date": clock.now_date(),
        "service_line_ids": [],
        "addon_line_ids": [],
        "product_lines": [],
        "redeem_reward": False,
        "tip_cents": 0,
        "service_net_cents": 0,
        "product_net_cents": 0,
        "tax_cents": 0,
        "total_due_cents": 0,
        "status": "OPEN",
    }
    db.stamp_create(ticket)
    db.tickets[ticket["id"]] = ticket

    q["status"] = "SERVING"
    q["assigned_barber_id"] = barber["id"]
    q["ticket_id"] = ticket["id"]
    db.touch(q)
    _recompute_queue_positions(q["shop_id"])
    return resp.success_object(db.public(q))


@app.route("/queue/<queue_ticket_id>/abandon", methods=["POST"])
def abandon_queue(queue_ticket_id):
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Customer"})
    q = get_queue_ticket(queue_ticket_id)
    if role == "Customer" and q["customer_id"] != uid:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your queue ticket.")
    if q["status"] != "WAITING":
        errors.fail(errors.ERR_INVALID_STATE, "Queue ticket is not WAITING.")
    q["status"] = "ABANDONED"
    db.touch(q)
    _recompute_queue_positions(q["shop_id"])
    return resp.success_object(db.public(q))


# ===========================================================================
# Ticket: lines edit, checkout, void
# ===========================================================================
@app.route("/tickets", methods=["GET"])
def list_tickets():
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber"})
    from flask import request
    filters = {
        "shop_id": request.args.get("shop_id"),
        "customer_id": request.args.get("customer_id"),
        "barber_id": request.args.get("barber_id"),
        "appointment_id": request.args.get("appointment_id"),
        "queue_ticket_id": request.args.get("queue_ticket_id"),
        "business_date": request.args.get("business_date"),
    }
    items = list_collection(db.tickets, filters)
    if role == "Barber":
        items = [o for o in items if o["barber_id"] == uid]
    items, meta = v.paginate(items)
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/tickets/<ticket_id>", methods=["GET"])
def read_ticket(ticket_id):
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist", "Barber"})
    obj = get_ticket(ticket_id)
    if role == "Barber" and obj["barber_id"] != uid:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your ticket.")
    return resp.success_object(db.public(obj))


@app.route("/tickets/<ticket_id>/lines", methods=["PUT"])
def edit_ticket_lines(ticket_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    ticket = get_ticket(ticket_id)
    data = v.body()
    shop_id = ticket["shop_id"]

    if ticket["status"] != "OPEN":
        errors.fail(errors.ERR_INVALID_STATE, "Ticket is not OPEN.")

    # Parse new line fields (only those present replace existing wholesale).
    if "service_line_ids" in data and data["service_line_ids"] is not None:
        service_line_ids = v.as_str_list(data, "service_line_ids", default=[])
    else:
        service_line_ids = ticket["service_line_ids"]
    if "addon_line_ids" in data and data["addon_line_ids"] is not None:
        addon_line_ids = v.as_str_list(data, "addon_line_ids", default=[])
    else:
        addon_line_ids = ticket["addon_line_ids"]
    product_lines = ticket["product_lines"]
    if "product_lines" in data and data["product_lines"] is not None:
        product_lines = _parse_product_lines(data["product_lines"])
    tip_cents = ticket["tip_cents"]
    if "tip_cents" in data and data["tip_cents"] is not None:
        tip_cents = v.as_int(data, "tip_cents", required=False, default=0, min_v=0)
    redeem_reward = ticket["redeem_reward"]
    if "redeem_reward" in data and data["redeem_reward"] is not None:
        redeem_reward = v.as_bool(data, "redeem_reward", required=False, default=False)

    # Body FK existence within shop.
    for sid in service_line_ids:
        ref_in_shop(db.services, sid, shop_id)
    for aid in addon_line_ids:
        ref_in_shop(db.addons, aid, shop_id)
    for pl in product_lines:
        ref_in_shop(db.products, pl["product_sku_id"], shop_id)

    # LISTED checks.
    for sid in service_line_ids:
        if db.services[sid]["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "A service line is delisted.")
    for aid in addon_line_ids:
        if db.addons[aid]["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "An add-on line is delisted.")
    for pl in product_lines:
        if db.products[pl["product_sku_id"]]["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "A product line is delisted.")

    ticket["service_line_ids"] = service_line_ids
    ticket["addon_line_ids"] = addon_line_ids
    ticket["product_lines"] = product_lines
    ticket["tip_cents"] = tip_cents
    ticket["redeem_reward"] = redeem_reward
    db.touch(ticket)
    return resp.success_object(db.public(ticket))


def _parse_product_lines(raw):
    if not isinstance(raw, list):
        errors.fail(errors.ERR_INVALID_REQUEST, "product_lines must be an array.")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "Each product line must be an object.")
        sku = item.get("product_sku_id")
        qty = item.get("qty")
        if not isinstance(sku, str) or not sku:
            errors.fail(errors.ERR_INVALID_REQUEST, "product_sku_id required on product line.")
        if isinstance(qty, bool) or not isinstance(qty, int):
            errors.fail(errors.ERR_INVALID_REQUEST, "qty must be an integer.")
        if qty < 1:
            errors.fail(errors.ERR_INVALID_REQUEST, "qty must be >= 1.")
        out.append({"product_sku_id": sku, "qty": qty})
    return out


@app.route("/tickets/<ticket_id>/checkout", methods=["POST"])
def checkout_ticket(ticket_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Receptionist"})
    ticket = get_ticket(ticket_id)
    shop = db.shops[ticket["shop_id"]]
    barber = db.barbers[ticket["barber_id"]]
    customer = db.customers[ticket["customer_id"]]

    # Preconditions.
    if shop["status"] != "OPEN":
        errors.fail(errors.ERR_SHOP_CLOSED, "Shop is closed.")
    if ticket["status"] != "OPEN":
        errors.fail(errors.ERR_INVALID_STATE, "Ticket is not OPEN.")
    if barber["license_status"] != "ACTIVE":
        errors.fail(errors.ERR_BARBER_NOT_ACTIVE, "Barber license is not active.")

    # Catalog LISTED.
    for sid in ticket["service_line_ids"]:
        svc = db.services.get(sid)
        if svc is None or svc["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "A service line is delisted.")
    for aid in ticket["addon_line_ids"]:
        ad = db.addons.get(aid)
        if ad is None or ad["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "An add-on line is delisted.")
    for pl in ticket["product_lines"]:
        pr = db.products.get(pl["product_sku_id"])
        if pr is None or pr["status"] != "LISTED":
            errors.fail(errors.ERR_ITEM_DELISTED, "A product line is delisted.")

    # Stock.
    for pl in ticket["product_lines"]:
        pr = db.products[pl["product_sku_id"]]
        if pr["stock_qty"] < pl["qty"]:
            errors.fail(errors.ERR_INSUFFICIENT_STOCK, "Insufficient stock.")

    # Reward credits precondition (credit existing before accrual).
    if ticket["redeem_reward"] and customer["reward_credits"] < 1:
        errors.fail(errors.ERR_NO_REWARD_CREDITS, "No reward credits.")

    # Already-settled (barber, business_date).
    for st in db.settlements.values():
        if st["barber_id"] == barber["id"] and st["business_date"] == ticket["business_date"]:
            errors.fail(errors.ERR_DATE_ALREADY_SETTLED, "Date already settled.")

    # ---------------- Pricing (pinned order) ----------------
    member_active = customer["membership_status"] == "ACTIVE"
    plan = db.memberships.get(customer["membership_id"]) if customer.get("membership_id") else None

    # 1. service_gross
    service_gross = 0
    for sid in ticket["service_line_ids"]:
        svc = db.services[sid]
        if svc["membership_included"] and member_active:
            service_gross += 0
        else:
            service_gross += svc["price_cents"]

    # 2. addon_gross (round per-line half-up then sum)
    addon_gross = 0
    for aid in ticket["addon_line_ids"]:
        ad = db.addons[aid]
        if not member_active:
            addon_gross += ad["price_cents"]
        else:
            if ad["membership_discount_pct"] > 0:
                pct = ad["membership_discount_pct"]
            else:
                pct = plan["addon_discount_pct"] if plan else 0
            from decimal import Decimal
            line_val = money.round_half_up_cents(
                Decimal(str(ad["price_cents"])) * (Decimal("1") - Decimal(str(pct)) / Decimal("100"))
            )
            addon_gross += line_val

    # 3. reward waiver
    reward_waiver = 0
    if ticket["redeem_reward"] and customer["reward_credits"] >= 1 and ticket["service_line_ids"]:
        listed_services = [db.services[sid] for sid in ticket["service_line_ids"]
                           if db.services[sid]["status"] == "LISTED"]
        if listed_services:
            cheapest = min(listed_services, key=lambda s: (s["price_cents"], s.get("_seq", 0)))
            reward_waiver = min(cheapest["price_cents"], shop["punch_reward_value_cents"])

    # 4. service_net
    service_net = max(0, service_gross + addon_gross - reward_waiver)

    # product_net
    product_net = 0
    for pl in ticket["product_lines"]:
        pr = db.products[pl["product_sku_id"]]
        product_net += pr["price_cents"] * pl["qty"]

    # tax (sum-then-round)
    taxable_base = service_net + product_net
    tax_cents = money.pct_of(taxable_base, shop["tax_rate_pct"])

    total_due = service_net + product_net + tax_cents + ticket["tip_cents"]

    # Commit pricing.
    ticket["service_net_cents"] = service_net
    ticket["product_net_cents"] = product_net
    ticket["tax_cents"] = tax_cents
    ticket["total_due_cents"] = total_due
    ticket["status"] = "PAID"
    db.touch(ticket)

    # ---------------- Cascade reconciliation ----------------
    # Decrement stock.
    for pl in ticket["product_lines"]:
        pr = db.products[pl["product_sku_id"]]
        pr["stock_qty"] -= pl["qty"]
        db.touch(pr)

    # Barber unsettled revenue + version bump.
    barber["unsettled_revenue_cents"] = barber["unsettled_revenue_cents"] + service_net
    db.touch(barber)

    # Shop ledgers.
    shop["gross_service_revenue_cents"] = shop["gross_service_revenue_cents"] + service_net
    shop["gross_product_revenue_cents"] = shop["gross_product_revenue_cents"] + product_net
    db.touch(shop)

    # Reward redemption consumes a pre-existing credit (before accrual).
    if ticket["redeem_reward"]:
        customer["reward_credits"] = customer["reward_credits"] - 1

    # Punch accrual.
    new_count = customer["punch_count"] + 1
    if new_count >= shop["punch_reward_threshold"]:
        customer["reward_credits"] = customer["reward_credits"] + 1
        customer["punch_count"] = new_count - shop["punch_reward_threshold"]
    else:
        customer["punch_count"] = new_count
    db.touch(customer)

    # Source appointment / queue completion.
    if ticket["appointment_id"]:
        appt = db.appointments.get(ticket["appointment_id"])
        if appt and appt["status"] == "CHECKED_IN":
            appt["status"] = "COMPLETED"
            db.touch(appt)
    if ticket["queue_ticket_id"]:
        q = db.queue_tickets.get(ticket["queue_ticket_id"])
        if q and q["status"] == "SERVING":
            q["status"] = "DONE"
            db.touch(q)
            _recompute_queue_positions(q["shop_id"])

    return resp.success_object(db.public(ticket))


@app.route("/tickets/<ticket_id>/void", methods=["POST"])
def void_ticket(ticket_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    ticket = get_ticket(ticket_id)
    if ticket["status"] != "OPEN":
        errors.fail(errors.ERR_INVALID_STATE, "Only an OPEN ticket may be voided.")
    ticket["status"] = "VOIDED"
    db.touch(ticket)
    # Revert source.
    if ticket["appointment_id"]:
        appt = db.appointments.get(ticket["appointment_id"])
        if appt and appt["status"] == "CHECKED_IN":
            appt["status"] = "BOOKED"
            appt["ticket_id"] = None
            db.touch(appt)
    if ticket["queue_ticket_id"]:
        q = db.queue_tickets.get(ticket["queue_ticket_id"])
        if q and q["status"] == "SERVING":
            q["status"] = "WAITING"
            q["assigned_barber_id"] = None
            q["ticket_id"] = None
            # Re-queue at the back: assign a fresh sequence so it sorts last.
            q["_seq"] = next(db._seq)
            db.touch(q)
            _recompute_queue_positions(q["shop_id"])
    return resp.success_object(db.public(ticket))


# ===========================================================================
# DailySettlement
# ===========================================================================
@app.route("/barbers/<barber_id>/settlements", methods=["GET"])
def list_barber_settlements(barber_id):
    uid, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Barber"})
    barber = get_barber(barber_id)
    enforce_barber_owns(role, uid, barber_id)
    from flask import request
    bd = request.args.get("business_date")
    items = [s for s in db.settlements.values() if s["barber_id"] == barber_id]
    if bd is not None:
        items = [s for s in items if s["business_date"] == bd]
    items, meta = v.paginate(items)
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/barbers/<barber_id>/settlements", methods=["POST"])
def create_settlement(barber_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner"})
    barber = get_barber(barber_id)
    data = v.body()
    business_date = v.as_str(data, "business_date", required=True)
    v.parse_iso_date(business_date, "business_date")
    expected_barber_version = v.as_int(data, "expected_barber_version", required=True)

    # Uniqueness: no settlement for (barber, date) yet.
    for s in db.settlements.values():
        if s["barber_id"] == barber_id and s["business_date"] == business_date:
            errors.fail(errors.ERR_DATE_ALREADY_SETTLED, "Date already settled.")

    # OCC on barber version.
    if expected_barber_version != barber["version"]:
        errors.fail(errors.ERR_STALE_BARBER_VERSION, "Stale barber version.")

    # Aggregate barber's PAID tickets on business_date (VOIDED excluded).
    paid = [t for t in db.tickets.values()
            if t["barber_id"] == barber_id and t["status"] == "PAID"
            and t["business_date"] == business_date]

    svc = sum(t["service_net_cents"] for t in paid)
    prod = sum(t["product_net_cents"] for t in paid)
    tips = sum(t["tip_cents"] for t in paid)

    prod_eligible = 0
    for t in paid:
        for pl in t["product_lines"]:
            pr = db.products.get(pl["product_sku_id"])
            if pr and pr["commission_eligible"]:
                prod_eligible += pr["price_cents"] * pl["qty"]

    comp_model = barber["comp_model"]
    if comp_model == "BOOTH_RENT":
        booth_rent_charged = barber["booth_rent_cents"]
        shop_commission = 0
        barber_payout = tips + svc + prod - barber["booth_rent_cents"]
    else:  # COMMISSION
        shop = db.shops[barber["shop_id"]]
        booth_rent_charged = 0
        service_commission = money.pct_of(svc, barber["commission_pct"])
        product_commission = money.pct_of(prod_eligible, shop["product_commission_pct"])
        shop_commission = service_commission + (prod - product_commission)
        barber_payout = tips + (svc - service_commission) + product_commission

    obj = {
        "id": db.new_id(),
        "shop_id": barber["shop_id"],
        "barber_id": barber_id,
        "business_date": business_date,
        "comp_model": comp_model,
        "service_revenue_cents": svc,
        "product_revenue_cents": prod,
        "tip_total_cents": tips,
        "booth_rent_charged_cents": booth_rent_charged,
        "shop_commission_cents": shop_commission,
        "barber_payout_cents": barber_payout,
        "status": "FINALIZED",
    }
    db.stamp_create(obj)
    db.settlements[obj["id"]] = obj

    # Reconcile barber unsettled revenue toward 0 for the date; bump version.
    barber["unsettled_revenue_cents"] = barber["unsettled_revenue_cents"] - svc
    db.touch(barber)

    return resp.success_object(db.public(obj), 201)


@app.route("/settlements", methods=["GET"])
def list_settlements():
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Barber"})
    from flask import request
    filters = {
        "shop_id": request.args.get("shop_id"),
        "barber_id": request.args.get("barber_id"),
        "business_date": request.args.get("business_date"),
    }
    items = list_collection(db.settlements, filters)
    if role == "Barber":
        items = [o for o in items if o["barber_id"] == _uid()]
    items, meta = v.paginate(items)
    return resp.success_array([db.public(o) for o in items], meta)


@app.route("/settlements/<settlement_id>", methods=["GET"])
def read_settlement(settlement_id):
    _, role = auth.get_context()
    auth.require_role(role, {"ShopOwner", "Barber"})
    obj = get_settlement(settlement_id)
    if role == "Barber" and obj["barber_id"] != _uid():
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Not your settlement.")
    return resp.success_object(db.public(obj))


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
