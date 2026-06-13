"""Personal Chef & In-Home Dining API — entry point and all routes.

Storage is in-memory only (db.DB). NO seeding/preload at startup. Every entity is
constructed by tests via the declared API surface. Boots fresh on every process.
"""
import os

from flask import Flask, request

import calculations as calc
import lookups
import serialize
import services
from db import DB
from errors import ApiError, err
from middleware import get_auth, require_role
from models import stamp_create, touch
from response import success, error
from validators import (
    get_json_body, require_fields, as_int, as_str, as_array,
    validate_datetime_field, validate_allergen_tokens, parse_pagination, paginate,
    ALLERGEN_TOKENS, DIETARY_PATTERNS,
)

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unmapped URL path. No specific entity not-found applies; return a
    # well-formed envelope with a 404 status.
    return error("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 400)


# ===========================================================================
# Helpers
# ===========================================================================
def with_lock():
    return DB.lock


# ===========================================================================
# Chef endpoints
# ===========================================================================
@app.route("/chefs", methods=["POST"])
def create_chef():
    _, role = get_auth()
    require_role(role, {"Chef", "PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["display_name", "home_base_zip"])
    display_name = as_str(body, "display_name")
    home_base_zip = as_str(body, "home_base_zip")
    equipment = as_array(body, "equipment_inventory", required=False, default=[])
    prep_buffer = as_int(body, "prep_buffer_minutes", required=False, default=90, minimum=0)
    max_per_day = as_int(body, "max_bookings_per_day", required=False, default=2, minimum=1)
    with DB.lock:
        rec = {
            "display_name": display_name,
            "home_base_zip": home_base_zip,
            "equipment_inventory": list(equipment),
            "prep_buffer_minutes": prep_buffer,
            "max_bookings_per_day": max_per_day,
            "status": "DRAFT",
            "completed_bookings_count": 0,
            "settled_reliability_score": 50,
            "projected_reliability_score": 50,
            "captured_payments_cents": 0,
            "refunded_payments_cents": 0,
            "payout_accrued_cents": 0,
            "active_booking_count": 0,
        }
        stamp_create(rec)
        DB.chefs[rec["id"]] = rec
        return success(serialize.chef(rec), status=201)


@app.route("/chefs", methods=["GET"])
def list_chefs():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with DB.lock:
        records = list(DB.chefs.values())
        if status is not None:
            records = [r for r in records if r["status"] == status]
        page, meta = paginate(records, limit, offset)
        return success([serialize.chef(r) for r in page], status=200, pagination=meta)


@app.route("/chefs/<chef_id>", methods=["GET"])
def get_chef(chef_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_chef(chef_id)
        return success(serialize.chef(rec), status=200)


@app.route("/chefs/<chef_id>/activate", methods=["POST"])
def activate_chef(chef_id):
    user_id, role = get_auth()
    require_role(role, {"Chef", "PlatformAdmin"})
    with DB.lock:
        chef = lookups.get_chef(chef_id)
        # Ownership: a Chef activating must own this chef (PRD §3.1 — chef itself
        # may DRAFT->ACTIVE; admin handles SUSPENDED->ACTIVE). PlatformAdmin exempt.
        if role == "Chef" and user_id != chef_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this resource")
        cur = chef["status"]
        if cur == "DRAFT":
            # both conditions checked
            has_listed = any(m["chef_id"] == chef_id and m["is_listed"] for m in DB.menus.values())
            if not has_listed:
                raise err("ERR_NO_LISTED_MENU", "Activation requires at least one listed menu")
            has_zone = any(z["chef_id"] == chef_id for z in DB.travel_zones.values())
            if not has_zone:
                raise err("ERR_NO_TRAVEL_ZONE", "Activation requires at least one travel zone")
        elif cur == "SUSPENDED":
            has_listed = any(m["chef_id"] == chef_id and m["is_listed"] for m in DB.menus.values())
            if not has_listed:
                raise err("ERR_NO_LISTED_MENU", "Re-activation requires at least one listed menu")
        else:
            raise err("ERR_INVALID_STATE", "Chef cannot be activated from status %s" % cur)
        chef["status"] = "ACTIVE"
        touch(chef)
        return success(serialize.chef(chef), status=200)


@app.route("/chefs/<chef_id>/suspend", methods=["POST"])
def suspend_chef(chef_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    with DB.lock:
        chef = lookups.get_chef(chef_id)
        if chef["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Chef cannot be suspended from status %s" % chef["status"])
        chef["status"] = "SUSPENDED"
        touch(chef)
        return success(serialize.chef(chef), status=200)


# ===========================================================================
# MenuPackage endpoints
# ===========================================================================
@app.route("/menus", methods=["POST"])
def create_menu():
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    body = get_json_body()
    require_fields(body, ["chef_id", "title", "base_price_per_guest_cents",
                          "estimated_ingredient_per_guest_cents"])
    chef_id = as_str(body, "chef_id")
    title = as_str(body, "title")
    base_price = as_int(body, "base_price_per_guest_cents", minimum=0)
    est_ingredient = as_int(body, "estimated_ingredient_per_guest_cents", minimum=0)
    min_party = as_int(body, "min_party_size", required=False, default=2, minimum=1)
    max_party = as_int(body, "max_party_size", required=False, default=12, minimum=1)
    if max_party < min_party:
        raise err("ERR_INVALID_REQUEST", "max_party_size must be >= min_party_size")
    allergen_tags = as_array(body, "allergen_tags", required=False, default=[])
    validate_allergen_tokens(allergen_tags, "allergen_tags")
    required_equipment = as_array(body, "required_equipment", required=False, default=[])
    with DB.lock:
        chef = lookups.get_chef(chef_id)
        if user_id != chef_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this menu")
        rec = {
            "chef_id": chef_id,
            "title": title,
            "base_price_per_guest_cents": base_price,
            "estimated_ingredient_per_guest_cents": est_ingredient,
            "min_party_size": min_party,
            "max_party_size": max_party,
            "allergen_tags": list(allergen_tags),
            "required_equipment": list(required_equipment),
            "is_listed": False,
        }
        stamp_create(rec)
        DB.menus[rec["id"]] = rec
        return success(serialize.menu(rec), status=201)


@app.route("/menus", methods=["GET"])
def list_menus():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    chef_id = request.args.get("chef_id")
    is_listed = request.args.get("is_listed")
    with DB.lock:
        records = list(DB.menus.values())
        if chef_id is not None:
            records = [r for r in records if r["chef_id"] == chef_id]
        if is_listed is not None:
            want = is_listed.lower() == "true"
            records = [r for r in records if r["is_listed"] == want]
        page, meta = paginate(records, limit, offset)
        return success([serialize.menu(r) for r in page], status=200, pagination=meta)


@app.route("/menus/<menu_id>", methods=["GET"])
def get_menu(menu_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_menu(menu_id)
        return success(serialize.menu(rec), status=200)


@app.route("/menus/<menu_id>/publish", methods=["POST"])
def publish_menu(menu_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        menu = lookups.get_menu(menu_id)
        if user_id != menu["chef_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this menu")
        menu["is_listed"] = True
        touch(menu)
        return success(serialize.menu(menu), status=200)


# ===========================================================================
# TravelZone endpoints
# ===========================================================================
@app.route("/travel-zones", methods=["POST"])
def create_travel_zone():
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    body = get_json_body()
    require_fields(body, ["chef_id", "zone_code", "zip_prefixes", "travel_fee_cents"])
    chef_id = as_str(body, "chef_id")
    zone_code = as_str(body, "zone_code")
    zip_prefixes = as_array(body, "zip_prefixes")
    for p in zip_prefixes:
        if not isinstance(p, str):
            raise err("ERR_INVALID_REQUEST", "zip_prefixes entries must be strings")
    travel_fee = as_int(body, "travel_fee_cents", minimum=0)
    with DB.lock:
        chef = lookups.get_chef(chef_id)
        if user_id != chef_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this travel zone")
        # zone_code unique within (chef_id, zone_code)
        for z in DB.travel_zones.values():
            if z["chef_id"] == chef_id and z["zone_code"] == zone_code:
                raise err("ERR_INVALID_REQUEST", "zone_code must be unique for this chef")
        rec = {
            "chef_id": chef_id,
            "zone_code": zone_code,
            "zip_prefixes": list(zip_prefixes),
            "travel_fee_cents": travel_fee,
        }
        stamp_create(rec)
        DB.travel_zones[rec["id"]] = rec
        return success(serialize.travel_zone(rec), status=201)


@app.route("/travel-zones", methods=["GET"])
def list_travel_zones():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    chef_id = request.args.get("chef_id")
    with DB.lock:
        records = list(DB.travel_zones.values())
        if chef_id is not None:
            records = [r for r in records if r["chef_id"] == chef_id]
        page, meta = paginate(records, limit, offset)
        return success([serialize.travel_zone(r) for r in page], status=200, pagination=meta)


@app.route("/travel-zones/<zone_id>", methods=["GET"])
def get_travel_zone(zone_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_zone(zone_id)
        return success(serialize.travel_zone(rec), status=200)


# ===========================================================================
# AvailabilityBlock endpoints
# ===========================================================================
@app.route("/availability-blocks", methods=["POST"])
def create_availability_block():
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    body = get_json_body()
    require_fields(body, ["chef_id", "window_start_utc", "window_end_utc"])
    chef_id = as_str(body, "chef_id")
    start_dt = validate_datetime_field(body, "window_start_utc")
    end_dt = validate_datetime_field(body, "window_end_utc")
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_REQUEST", "window_end_utc must be after window_start_utc")
    with DB.lock:
        chef = lookups.get_chef(chef_id)
        if user_id != chef_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this availability block")
        rec = {
            "chef_id": chef_id,
            "kind": "BLACKOUT",
            "booking_id": None,
            "window_start_utc": as_str(body, "window_start_utc"),
            "window_end_utc": as_str(body, "window_end_utc"),
            "status": "HELD",
        }
        stamp_create(rec)
        DB.availability_blocks[rec["id"]] = rec
        return success(serialize.availability_block(rec), status=201)


@app.route("/availability-blocks", methods=["GET"])
def list_availability_blocks():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    chef_id = request.args.get("chef_id")
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    kind = request.args.get("kind")
    with DB.lock:
        records = list(DB.availability_blocks.values())
        if chef_id is not None:
            records = [r for r in records if r["chef_id"] == chef_id]
        if booking_id is not None:
            records = [r for r in records if r.get("booking_id") == booking_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        if kind is not None:
            records = [r for r in records if r["kind"] == kind]
        page, meta = paginate(records, limit, offset)
        return success([serialize.availability_block(r) for r in page], status=200, pagination=meta)


@app.route("/availability-blocks/<block_id>", methods=["GET"])
def get_availability_block(block_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_block(block_id)
        return success(serialize.availability_block(rec), status=200)


# ===========================================================================
# Client endpoints
# ===========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    _, role = get_auth()
    require_role(role, {"Client", "PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["full_name", "email"])
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    allergen_restrictions = as_array(body, "allergen_restrictions", required=False, default=[])
    validate_allergen_tokens(allergen_restrictions, "allergen_restrictions")
    dietary = as_str(body, "dietary_pattern", required=False, default="OMNIVORE")
    if dietary not in DIETARY_PATTERNS:
        raise err("ERR_INVALID_REQUEST", "Invalid dietary_pattern: %s" % dietary)
    with DB.lock:
        # email unique
        for c in DB.clients.values():
            if c["email"] == email:
                raise err("ERR_INVALID_REQUEST", "email must be unique")
        rec = {
            "full_name": full_name,
            "email": email,
            "allergen_restrictions": list(allergen_restrictions),
            "dietary_pattern": dietary,
        }
        stamp_create(rec)
        DB.clients[rec["id"]] = rec
        return success(serialize.client(rec), status=201)


@app.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    _, role = get_auth()
    require_role(role, {"Client", "Chef", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_client(client_id)
        return success(serialize.client(rec), status=200)


# ===========================================================================
# Booking endpoints
# ===========================================================================
@app.route("/bookings", methods=["POST"])
def create_booking():
    user_id, role = get_auth()
    require_role(role, {"Client"})
    body = get_json_body()
    require_fields(body, ["chef_id", "client_id", "menu_package_id", "party_size",
                          "service_zip", "event_start_utc", "event_end_utc"])
    chef_id = as_str(body, "chef_id")
    client_id = as_str(body, "client_id")
    menu_package_id = as_str(body, "menu_package_id")
    party_size = as_int(body, "party_size", minimum=1)
    service_zip = as_str(body, "service_zip")
    start_dt = validate_datetime_field(body, "event_start_utc")
    end_dt = validate_datetime_field(body, "event_end_utc")
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_REQUEST", "event_end_utc must be after event_start_utc")
    with DB.lock:
        # FK existence (PRD §2.8 priority 4): chef, client, menu
        lookups.get_chef(chef_id)
        lookups.get_client(client_id)
        lookups.get_menu(menu_package_id)
        # ownership: acting client must be the booking's client
        if user_id != client_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this booking")
        # resolve travel zone from service_zip
        zone = services.resolve_travel_zone(chef_id, service_zip)
        rec = {
            "chef_id": chef_id,
            "client_id": client_id,
            "menu_package_id": menu_package_id,
            "travel_zone_id": zone["id"],
            "recurring_plan_id": None,
            "party_size": party_size,
            "service_zip": service_zip,
            "event_start_utc": as_str(body, "event_start_utc"),
            "event_end_utc": as_str(body, "event_end_utc"),
            "event_date": services.event_date_from_start(start_dt),
            "locked_markup_rate": None,
            "labor_total_cents": 0,
            "estimated_grocery_total_cents": 0,
            "actual_grocery_total_cents": 0,
            "travel_fee_cents": zone["travel_fee_cents"],
            "quote_total_cents": 0,
            "deposit_due_cents": 0,
            "balance_due_cents": 0,
            "amount_captured_cents": 0,
            "amount_refunded_cents": 0,
            "lifecycle_status": "REQUESTED",
            "payment_status": "UNPAID",
            "cancellation_refund_rate": 0,
        }
        stamp_create(rec)
        DB.bookings[rec["id"]] = rec
        return success(serialize.booking(rec), status=201)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    filters = {
        "chef_id": request.args.get("chef_id"),
        "client_id": request.args.get("client_id"),
        "recurring_plan_id": request.args.get("recurring_plan_id"),
        "menu_package_id": request.args.get("menu_package_id"),
        "travel_zone_id": request.args.get("travel_zone_id"),
        "lifecycle_status": request.args.get("lifecycle_status"),
        "event_date": request.args.get("event_date"),
    }
    with DB.lock:
        records = list(DB.bookings.values())
        for field, val in filters.items():
            if val is not None:
                records = [r for r in records if r.get(field) == val]
        page, meta = paginate(records, limit, offset)
        return success([serialize.booking(r) for r in page], status=200, pagination=meta)


@app.route("/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_booking(booking_id)
        return success(serialize.booking(rec), status=200)


@app.route("/bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    body = get_json_body()
    # expected_chef_version is mandatory on confirm (PRD §2.5)
    if "expected_chef_version" not in body or body["expected_chef_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_chef_version is required")
    expected_version = as_int(body, "expected_chef_version")
    with DB.lock:
        booking = lookups.get_booking(booking_id)  # priority 3 existence
        chef = lookups.get_chef(booking["chef_id"])
        # Confirm-path order is pinned by PRD §2.5 and §3.3: after auth/existence,
        # "the version check precedes ownership, state, allergen, equipment, time,
        # and capacity checks on the confirm path" (§2.5). §3.3 lists: version guard
        # -> ownership -> chef-ACTIVE state gate -> allergen -> equipment -> party
        # size -> time -> capacity. The booking source-state (must be REQUESTED) is
        # a state check, so it follows the version guard and ownership.
        # 1) version guard (§2.5 — before ownership/state/business)
        if expected_version != chef["version"]:
            raise err("ERR_STALE_VERSION", "expected_chef_version does not match chef version")
        # 2) ownership
        if user_id != booking["chef_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this booking")
        # 3) booking source-state legality (must be REQUESTED)
        if booking["lifecycle_status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE",
                      "Booking must be REQUESTED to confirm (is %s)" % booking["lifecycle_status"])
        # 4) cross-entity state gate: chef ACTIVE
        if chef["status"] != "ACTIVE":
            raise err("ERR_CHEF_NOT_ACTIVE", "Chef must be ACTIVE to confirm")
        menu = DB.menus.get(booking["menu_package_id"])
        client = DB.clients.get(booking["client_id"])
        # allergen safety
        client_allergens = set(client["allergen_restrictions"]) if client else set()
        menu_allergens = set(menu["allergen_tags"]) if menu else set()
        if client_allergens & menu_allergens:
            raise err("ERR_ALLERGEN_CONFLICT", "Client allergen restriction intersects menu allergens")
        # equipment subset
        if not set(menu["required_equipment"]).issubset(set(chef["equipment_inventory"])):
            raise err("ERR_EQUIPMENT_UNAVAILABLE", "Menu required equipment not available")
        # party-size range
        if not (menu["min_party_size"] <= booking["party_size"] <= menu["max_party_size"]):
            raise err("ERR_PARTY_SIZE_OUT_OF_RANGE", "party_size outside menu range")
        # time conflict (buffer-widened, half-open)
        win_start, win_end = services.occupied_window(booking, chef)
        if services.window_conflicts(booking["chef_id"], win_start, win_end):
            raise err("ERR_CHEF_TIME_CONFLICT", "Occupied window overlaps a HELD availability block")
        # daily capacity
        same_date_count = sum(
            1 for b in DB.bookings.values()
            if b["chef_id"] == booking["chef_id"]
            and b["event_date"] == booking["event_date"]
            and b["lifecycle_status"] in ("CONFIRMED", "IN_PREP")
        )
        if same_date_count >= chef["max_bookings_per_day"]:
            raise err("ERR_DAILY_CAPACITY_EXCEEDED", "Chef at daily capacity for this event_date")

        # ---- all checks passed: freeze quote + reserve calendar atomically ----
        rate = calc.select_markup_rate(menu["estimated_ingredient_per_guest_cents"], booking["party_size"])
        booking["locked_markup_rate"] = float(rate)
        booking["labor_total_cents"] = calc.labor_total_cents(
            menu["base_price_per_guest_cents"], booking["party_size"])
        booking["estimated_grocery_total_cents"] = calc.estimated_grocery_total_cents(
            menu["estimated_ingredient_per_guest_cents"], booking["party_size"], rate)
        # travel_fee_cents already set at creation
        services.recompute_quote(booking)  # estimated basis (no finalized run)
        booking["deposit_due_cents"] = calc.deposit_due_cents(booking["quote_total_cents"])
        booking["lifecycle_status"] = "CONFIRMED"
        touch(booking)
        # mint BOOKING_HOLD over buffer-widened window
        hold = {
            "chef_id": booking["chef_id"],
            "kind": "BOOKING_HOLD",
            "booking_id": booking["id"],
            "window_start_utc": DB.iso_millis(win_start),
            "window_end_utc": DB.iso_millis(win_end),
            "status": "HELD",
        }
        stamp_create(hold)
        DB.availability_blocks[hold["id"]] = hold
        # chef counts/scores recompute + version bump
        services.recompute_chef_all(chef)  # touch() inside bumps version by 1
        return success(serialize.booking(booking), status=200)


@app.route("/bookings/<booking_id>/decline", methods=["POST"])
def decline_booking(booking_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        if booking["lifecycle_status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Booking must be REQUESTED to decline")
        if user_id != booking["chef_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this booking")
        booking["lifecycle_status"] = "DECLINED"
        touch(booking)
        chef = lookups.get_chef(booking["chef_id"])
        services.recompute_chef_all(chef)
        return success(serialize.booking(booking), status=200)


@app.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        if booking["lifecycle_status"] not in ("REQUESTED", "CONFIRMED", "IN_PREP"):
            raise err("ERR_INVALID_STATE", "Booking cannot be cancelled from %s" % booking["lifecycle_status"])
        if user_id != booking["client_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this booking")
        _do_cancel(booking, refund_enabled=True)
        chef = lookups.get_chef(booking["chef_id"])
        services.recompute_chef_all(chef)
        return success(serialize.booking(booking), status=200)


def _do_cancel(booking, refund_enabled):
    """Cancellation cascade (PRD §3.8). refund_enabled controls lead-time refund;
    plan-pause cancels REQUESTED children with rate 0 (handled by caller)."""
    prev_lifecycle = booking["lifecycle_status"]
    if refund_enabled:
        start_dt = services.parse_datetime(booking["event_start_utc"])
        ld = services.lead_days(start_dt)
        rate = calc.cancellation_refund_rate(ld)
    else:
        from decimal import Decimal
        rate = Decimal("0.00")
    booking["cancellation_refund_rate"] = float(rate)
    any_refund = False
    for p in DB.payments.values():
        if p["booking_id"] != booking["id"]:
            continue
        if p["status"] != "CAPTURED":
            continue
        refund = calc.refund_for_payment(p["amount_cents"], rate)
        if refund > 0:
            p["refunded_cents"] = refund
            if refund == p["amount_cents"]:
                p["status"] = "REFUNDED"
            touch(p)
            any_refund = True
    if any_refund:
        booking["payment_status"] = "REFUNDED"
    # void finalized grocery run -> re-pin to estimated basis
    for gr in DB.grocery_runs.values():
        if gr["booking_id"] == booking["id"] and gr["status"] == "FINALIZED":
            gr["status"] = "VOIDED"
            touch(gr)
            booking["actual_grocery_total_cents"] = 0
    # release the BOOKING_HOLD if the booking had been CONFIRMED/IN_PREP
    if prev_lifecycle in ("CONFIRMED", "IN_PREP"):
        for blk in DB.availability_blocks.values():
            if (blk.get("booking_id") == booking["id"]
                    and blk["kind"] == "BOOKING_HOLD" and blk["status"] == "HELD"):
                blk["status"] = "RELEASED"
                touch(blk)
    booking["lifecycle_status"] = "CANCELLED"
    services.recompute_booking_money_mirrors(booking)  # captured/refunded + quote/balance
    touch(booking)


@app.route("/bookings/<booking_id>/start-prep", methods=["POST"])
def start_prep_booking(booking_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        if booking["lifecycle_status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Booking must be CONFIRMED to start prep")
        if user_id != booking["chef_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this booking")
        if not services.has_finalized_grocery_run(booking["id"]):
            raise err("ERR_GROCERY_RUN_NOT_FINALIZED", "A finalized grocery run is required")
        booking["lifecycle_status"] = "IN_PREP"
        touch(booking)
        return success(serialize.booking(booking), status=200)


@app.route("/bookings/<booking_id>/complete", methods=["POST"])
def complete_booking(booking_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        if booking["lifecycle_status"] != "IN_PREP":
            raise err("ERR_INVALID_STATE", "Booking must be IN_PREP to complete")
        if user_id != booking["chef_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this booking")
        if booking["payment_status"] != "PAID_IN_FULL":
            raise err("ERR_BALANCE_OUTSTANDING", "Completion requires payment_status PAID_IN_FULL")
        booking["lifecycle_status"] = "COMPLETED"
        touch(booking)
        chef = lookups.get_chef(booking["chef_id"])
        services.recompute_chef_all(chef)
        return success(serialize.booking(booking), status=200)


# ===========================================================================
# Payment endpoints
# ===========================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    user_id, role = get_auth()
    require_role(role, {"Client"})
    body = get_json_body()
    require_fields(body, ["booking_id", "kind", "amount_cents"])
    booking_id = as_str(body, "booking_id")
    kind = as_str(body, "kind")
    if kind not in ("DEPOSIT", "BALANCE"):
        raise err("ERR_INVALID_REQUEST", "kind must be DEPOSIT or BALANCE")
    amount = as_int(body, "amount_cents", minimum=1)
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        if user_id != booking["client_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this booking")
        if kind == "DEPOSIT":
            if booking["lifecycle_status"] != "CONFIRMED":
                raise err("ERR_BOOKING_NOT_CONFIRMED", "Deposit requires a CONFIRMED booking")
            if booking["payment_status"] != "UNPAID":
                raise err("ERR_INVALID_STATE", "Deposit only valid from UNPAID")
            if amount != booking["deposit_due_cents"]:
                raise err("ERR_DEPOSIT_AMOUNT_MISMATCH", "Deposit amount must equal deposit_due_cents")
            new_payment_status = "DEPOSIT_PAID"
        else:  # BALANCE
            if booking["payment_status"] != "DEPOSIT_PAID":
                raise err("ERR_INVALID_STATE", "Balance only valid from DEPOSIT_PAID")
            if not services.has_finalized_grocery_run(booking["id"]):
                raise err("ERR_GROCERY_RUN_NOT_FINALIZED", "Balance requires a finalized grocery run")
            if amount != booking["balance_due_cents"]:
                raise err("ERR_BALANCE_AMOUNT_MISMATCH", "Balance amount must equal balance_due_cents")
            new_payment_status = "PAID_IN_FULL"
        rec = {
            "booking_id": booking_id,
            "kind": kind,
            "amount_cents": amount,
            "refunded_cents": 0,
            "status": "CAPTURED",
        }
        stamp_create(rec)
        DB.payments[rec["id"]] = rec
        # update booking money mirrors + payment_status
        booking["payment_status"] = new_payment_status
        services.recompute_booking_money_mirrors(booking)
        touch(booking)
        # chef captured/payout recompute
        chef = lookups.get_chef(booking["chef_id"])
        services.recompute_chef_all(chef)
        return success(serialize.payment(rec), status=201)


@app.route("/payments", methods=["GET"])
def list_payments():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    with DB.lock:
        records = list(DB.payments.values())
        if booking_id is not None:
            records = [r for r in records if r["booking_id"] == booking_id]
        page, meta = paginate(records, limit, offset)
        return success([serialize.payment(r) for r in page], status=200, pagination=meta)


@app.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_payment(payment_id)
        return success(serialize.payment(rec), status=200)


# ===========================================================================
# GroceryRun endpoints
# ===========================================================================
@app.route("/grocery-runs", methods=["POST"])
def create_grocery_run():
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    body = get_json_body()
    require_fields(body, ["booking_id", "line_items"])
    booking_id = as_str(body, "booking_id")
    line_items = as_array(body, "line_items")
    normalized = []
    for li in line_items:
        if not isinstance(li, dict):
            raise err("ERR_INVALID_REQUEST", "line_items entries must be objects")
        if "actual_cost_cents" not in li or li["actual_cost_cents"] is None:
            raise err("ERR_INVALID_REQUEST", "line_items entries require actual_cost_cents")
        cost = li["actual_cost_cents"]
        if isinstance(cost, bool) or not isinstance(cost, int):
            raise err("ERR_INVALID_REQUEST", "actual_cost_cents must be an integer")
        normalized.append({"label": li.get("label"), "actual_cost_cents": cost})
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        if user_id != booking["chef_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own the parent booking")
        if booking["lifecycle_status"] != "CONFIRMED":
            raise err("ERR_BOOKING_NOT_CONFIRMED", "Grocery run requires a CONFIRMED booking")
        raw_subtotal = sum(li["actual_cost_cents"] for li in normalized)
        rec = {
            "booking_id": booking_id,
            "raw_actual_subtotal_cents": raw_subtotal,
            "line_items": normalized,
            "status": "OPEN",
        }
        stamp_create(rec)
        DB.grocery_runs[rec["id"]] = rec
        return success(serialize.grocery_run(rec), status=201)


@app.route("/grocery-runs", methods=["GET"])
def list_grocery_runs():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    with DB.lock:
        records = list(DB.grocery_runs.values())
        if booking_id is not None:
            records = [r for r in records if r["booking_id"] == booking_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        page, meta = paginate(records, limit, offset)
        return success([serialize.grocery_run(r) for r in page], status=200, pagination=meta)


@app.route("/grocery-runs/<grocery_run_id>", methods=["GET"])
def get_grocery_run(grocery_run_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_grocery_run(grocery_run_id)
        return success(serialize.grocery_run(rec), status=200)


@app.route("/grocery-runs/<grocery_run_id>/finalize", methods=["POST"])
def finalize_grocery_run(grocery_run_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        gr = lookups.get_grocery_run(grocery_run_id)
        booking = DB.bookings.get(gr["booking_id"])
        # state legality
        if gr["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Grocery run must be OPEN to finalize")
        if user_id != (booking["chef_id"] if booking else None):
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own the parent booking")
        if booking["lifecycle_status"] != "CONFIRMED":
            raise err("ERR_BOOKING_NOT_CONFIRMED", "Finalize requires a CONFIRMED booking")
        if not gr["line_items"]:
            raise err("ERR_GROCERY_RUN_EMPTY", "Cannot finalize a grocery run with no line items")
        gr["raw_actual_subtotal_cents"] = sum(li["actual_cost_cents"] for li in gr["line_items"])
        booking["actual_grocery_total_cents"] = calc.actual_grocery_total_cents(
            gr["line_items"], booking["locked_markup_rate"])
        gr["status"] = "FINALIZED"
        touch(gr)
        services.recompute_quote(booking)  # actual basis now supersedes estimate
        touch(booking)
        return success(serialize.grocery_run(gr), status=200)


# ===========================================================================
# RescheduleRequest endpoints
# ===========================================================================
@app.route("/reschedule-requests", methods=["POST"])
def create_reschedule_request():
    user_id, role = get_auth()
    require_role(role, {"Client", "Chef"})
    body = get_json_body()
    require_fields(body, ["booking_id", "proposed_event_start_utc", "proposed_event_end_utc"])
    booking_id = as_str(body, "booking_id")
    start_dt = validate_datetime_field(body, "proposed_event_start_utc")
    end_dt = validate_datetime_field(body, "proposed_event_end_utc")
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_REQUEST", "proposed_event_end_utc must be after proposed_event_start_utc")
    with DB.lock:
        booking = lookups.get_booking(booking_id)
        # ownership: proposer (client or chef) must be a party to the booking
        if role == "Client":
            if user_id != booking["client_id"]:
                raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this booking")
            requested_by = "CLIENT"
        else:  # Chef
            if user_id != booking["chef_id"]:
                raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own this booking")
            requested_by = "CHEF"
        rec = {
            "booking_id": booking_id,
            "proposed_event_start_utc": as_str(body, "proposed_event_start_utc"),
            "proposed_event_end_utc": as_str(body, "proposed_event_end_utc"),
            "requested_by_role": requested_by,
            "status": "PROPOSED",
        }
        stamp_create(rec)
        DB.reschedule_requests[rec["id"]] = rec
        return success(serialize.reschedule_request(rec), status=201)


@app.route("/reschedule-requests", methods=["GET"])
def list_reschedule_requests():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    with DB.lock:
        records = list(DB.reschedule_requests.values())
        if booking_id is not None:
            records = [r for r in records if r["booking_id"] == booking_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        page, meta = paginate(records, limit, offset)
        return success([serialize.reschedule_request(r) for r in page], status=200, pagination=meta)


@app.route("/reschedule-requests/<request_id>", methods=["GET"])
def get_reschedule_request(request_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_reschedule(request_id)
        return success(serialize.reschedule_request(rec), status=200)


@app.route("/reschedule-requests/<request_id>/accept", methods=["POST"])
def accept_reschedule(request_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        rr = lookups.get_reschedule(request_id)
        booking = DB.bookings.get(rr["booking_id"])
        if rr["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Reschedule request must be PROPOSED")
        if user_id != (booking["chef_id"] if booking else None):
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own the parent booking")
        if booking["lifecycle_status"] != "CONFIRMED":
            raise err("ERR_BOOKING_NOT_CONFIRMED", "Parent booking must be CONFIRMED")
        chef = lookups.get_chef(booking["chef_id"])
        prop_start = services.parse_datetime(rr["proposed_event_start_utc"])
        prop_end = services.parse_datetime(rr["proposed_event_end_utc"])
        from datetime import timedelta
        win_start = prop_start - timedelta(minutes=chef["prep_buffer_minutes"])
        win_end = prop_end
        # overlap check excluding this booking's own current hold
        if services.window_conflicts(booking["chef_id"], win_start, win_end,
                                      exclude_booking_id=booking["id"]):
            raise err("ERR_CHEF_TIME_CONFLICT", "Proposed window overlaps a HELD availability block")
        # update booking window
        booking["event_start_utc"] = rr["proposed_event_start_utc"]
        booking["event_end_utc"] = rr["proposed_event_end_utc"]
        booking["event_date"] = services.event_date_from_start(prop_start)
        touch(booking)
        # release old hold, mint new HELD over proposed window
        for blk in DB.availability_blocks.values():
            if (blk.get("booking_id") == booking["id"]
                    and blk["kind"] == "BOOKING_HOLD" and blk["status"] == "HELD"):
                blk["status"] = "RELEASED"
                touch(blk)
        new_hold = {
            "chef_id": booking["chef_id"],
            "kind": "BOOKING_HOLD",
            "booking_id": booking["id"],
            "window_start_utc": DB.iso_millis(win_start),
            "window_end_utc": DB.iso_millis(win_end),
            "status": "HELD",
        }
        stamp_create(new_hold)
        DB.availability_blocks[new_hold["id"]] = new_hold
        rr["status"] = "ACCEPTED"
        touch(rr)
        # sibling PROPOSED requests on same booking -> WITHDRAWN
        for other in DB.reschedule_requests.values():
            if (other["id"] != rr["id"] and other["booking_id"] == booking["id"]
                    and other["status"] == "PROPOSED"):
                other["status"] = "WITHDRAWN"
                touch(other)
        return success(serialize.reschedule_request(rr), status=200)


@app.route("/reschedule-requests/<request_id>/reject", methods=["POST"])
def reject_reschedule(request_id):
    user_id, role = get_auth()
    require_role(role, {"Chef"})
    with DB.lock:
        rr = lookups.get_reschedule(request_id)
        booking = DB.bookings.get(rr["booking_id"])
        if rr["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Reschedule request must be PROPOSED")
        if user_id != (booking["chef_id"] if booking else None):
            raise err("ERR_NOT_RESOURCE_OWNER", "Chef does not own the parent booking")
        rr["status"] = "REJECTED"
        touch(rr)
        return success(serialize.reschedule_request(rr), status=200)


@app.route("/reschedule-requests/<request_id>/withdraw", methods=["POST"])
def withdraw_reschedule(request_id):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    with DB.lock:
        rr = lookups.get_reschedule(request_id)
        booking = DB.bookings.get(rr["booking_id"])
        if rr["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Reschedule request must be PROPOSED")
        if user_id != (booking["client_id"] if booking else None):
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own the parent booking")
        rr["status"] = "WITHDRAWN"
        touch(rr)
        return success(serialize.reschedule_request(rr), status=200)


# ===========================================================================
# RecurringPlan endpoints
# ===========================================================================
@app.route("/recurring-plans", methods=["POST"])
def create_recurring_plan():
    user_id, role = get_auth()
    require_role(role, {"Client"})
    body = get_json_body()
    require_fields(body, ["chef_id", "client_id", "menu_package_id", "party_size",
                          "service_zip", "weekday", "event_start_time_utc", "duration_minutes"])
    chef_id = as_str(body, "chef_id")
    client_id = as_str(body, "client_id")
    menu_package_id = as_str(body, "menu_package_id")
    party_size = as_int(body, "party_size", minimum=1)
    service_zip = as_str(body, "service_zip")
    weekday = as_int(body, "weekday")
    if weekday < 0 or weekday > 6:
        raise err("ERR_INVALID_REQUEST", "weekday must be between 0 and 6")
    event_start_time = as_str(body, "event_start_time_utc")
    duration = as_int(body, "duration_minutes", minimum=1)
    cadence = as_int(body, "cadence_weeks", required=False, default=1, minimum=1)
    with DB.lock:
        lookups.get_chef(chef_id)
        lookups.get_client(client_id)
        lookups.get_menu(menu_package_id)
        if user_id != client_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this plan")
        rec = {
            "chef_id": chef_id,
            "client_id": client_id,
            "menu_package_id": menu_package_id,
            "party_size": party_size,
            "service_zip": service_zip,
            "weekday": weekday,
            "event_start_time_utc": event_start_time,
            "duration_minutes": duration,
            "cadence_weeks": cadence,
            "occurrences_generated": 0,
            "status": "ACTIVE",
        }
        stamp_create(rec)
        DB.recurring_plans[rec["id"]] = rec
        return success(serialize.recurring_plan(rec), status=201)


@app.route("/recurring-plans", methods=["GET"])
def list_recurring_plans():
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    limit, offset = parse_pagination()
    chef_id = request.args.get("chef_id")
    client_id = request.args.get("client_id")
    menu_package_id = request.args.get("menu_package_id")
    status = request.args.get("status")
    with DB.lock:
        records = list(DB.recurring_plans.values())
        if chef_id is not None:
            records = [r for r in records if r["chef_id"] == chef_id]
        if client_id is not None:
            records = [r for r in records if r["client_id"] == client_id]
        if menu_package_id is not None:
            records = [r for r in records if r["menu_package_id"] == menu_package_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        page, meta = paginate(records, limit, offset)
        return success([serialize.recurring_plan(r) for r in page], status=200, pagination=meta)


@app.route("/recurring-plans/<plan_id>", methods=["GET"])
def get_recurring_plan(plan_id):
    _, role = get_auth()
    require_role(role, {"Chef", "Client", "PlatformAdmin"})
    with DB.lock:
        rec = lookups.get_plan(plan_id)
        return success(serialize.recurring_plan(rec), status=200)


@app.route("/recurring-plans/<plan_id>/generate-occurrence", methods=["POST"])
def generate_occurrence(plan_id):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    body = get_json_body()
    require_fields(body, ["occurrence_date"])
    occurrence_date = as_str(body, "occurrence_date")
    # occurrence_date YYYY-MM-DD
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    try:
        date_part = _dt.strptime(occurrence_date, "%Y-%m-%d").date()
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "occurrence_date must be YYYY-MM-DD")
    with DB.lock:
        plan = lookups.get_plan(plan_id)
        if user_id != plan["client_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this plan")
        if plan["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Plan must be ACTIVE to generate occurrences")
        # build event window from plan time-of-day + duration on occurrence_date
        try:
            t = _dt.strptime(plan["event_start_time_utc"], "%H:%M:%S").time()
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "plan event_start_time_utc must be HH:MM:SS")
        start_dt = _dt.combine(date_part, t).replace(tzinfo=_tz.utc)
        end_dt = start_dt + _td(minutes=plan["duration_minutes"])
        # resolve travel zone for the booking
        zone = services.resolve_travel_zone(plan["chef_id"], plan["service_zip"])
        rec = {
            "chef_id": plan["chef_id"],
            "client_id": plan["client_id"],
            "menu_package_id": plan["menu_package_id"],
            "travel_zone_id": zone["id"],
            "recurring_plan_id": plan["id"],
            "party_size": plan["party_size"],
            "service_zip": plan["service_zip"],
            "event_start_utc": DB.iso_millis(start_dt),
            "event_end_utc": DB.iso_millis(end_dt),
            "event_date": services.event_date_from_start(start_dt),
            "locked_markup_rate": None,
            "labor_total_cents": 0,
            "estimated_grocery_total_cents": 0,
            "actual_grocery_total_cents": 0,
            "travel_fee_cents": zone["travel_fee_cents"],
            "quote_total_cents": 0,
            "deposit_due_cents": 0,
            "balance_due_cents": 0,
            "amount_captured_cents": 0,
            "amount_refunded_cents": 0,
            "lifecycle_status": "REQUESTED",
            "payment_status": "UNPAID",
            "cancellation_refund_rate": 0,
        }
        stamp_create(rec)
        DB.bookings[rec["id"]] = rec
        plan["occurrences_generated"] += 1
        touch(plan)
        return success(serialize.booking(rec), status=201)


@app.route("/recurring-plans/<plan_id>/pause", methods=["POST"])
def pause_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    with DB.lock:
        plan = lookups.get_plan(plan_id)
        if plan["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Plan must be ACTIVE to pause")
        if user_id != plan["client_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this plan")
        plan["status"] = "PAUSED"
        touch(plan)
        # depth-2 cascade: REQUESTED children -> CANCELLED (refund rate 0)
        affected_chefs = set()
        for b in list(DB.bookings.values()):
            if b["recurring_plan_id"] == plan["id"] and b["lifecycle_status"] == "REQUESTED":
                _do_cancel(b, refund_enabled=False)
                affected_chefs.add(b["chef_id"])
        for cid in affected_chefs:
            chef = DB.chefs.get(cid)
            if chef:
                services.recompute_chef_all(chef)
        return success(serialize.recurring_plan(plan), status=200)


@app.route("/recurring-plans/<plan_id>/resume", methods=["POST"])
def resume_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    with DB.lock:
        plan = lookups.get_plan(plan_id)
        if plan["status"] != "PAUSED":
            raise err("ERR_INVALID_STATE", "Plan must be PAUSED to resume")
        if user_id != plan["client_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this plan")
        plan["status"] = "ACTIVE"
        touch(plan)
        return success(serialize.recurring_plan(plan), status=200)


@app.route("/recurring-plans/<plan_id>/cancel", methods=["POST"])
def cancel_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    with DB.lock:
        plan = lookups.get_plan(plan_id)
        if plan["status"] not in ("ACTIVE", "PAUSED"):
            raise err("ERR_INVALID_STATE", "Plan cannot be cancelled from %s" % plan["status"])
        if user_id != plan["client_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Client does not own this plan")
        plan["status"] = "CANCELLED"
        touch(plan)
        return success(serialize.recurring_plan(plan), status=200)


# ===========================================================================
# Test clock
# ===========================================================================
@app.route("/_clock/set", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["now_utc"])
    dt = validate_datetime_field(body, "now_utc")
    with DB.lock:
        DB.set_clock(dt)
        return success({}, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
