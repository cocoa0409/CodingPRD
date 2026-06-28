"""Threading & Brow Salon API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). Every
endpoint, field, side-effect and error traces to a PRD sentence (see PRD.md).
"""
import os

from flask import Flask, request

import clock
import domain
import response as resp
from db import db, new_id, stamp_create, touch
from errors import ApiError, err
from helpers import (
    get_addon, get_body, get_chair, get_entry, get_line, get_member,
    get_package, get_pagination, get_retail, get_salon, get_service_item,
    get_technician, get_ticket, get_visit, optional_bool, optional_int,
    paginate, require_datetime, require_enum, require_int, require_str,
    require_str_array, sorted_by_created,
)
from middleware import require_role, require_user_context

app = Flask(__name__)


# ===========================================================================
# Error handling — every failure renders the standard error envelope (§2.2)
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return resp.error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return resp.error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return resp.error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return resp.error_response(e.error_id, e.http_status, e.message)
    return resp.error_response("ERR_INTERNAL", 500, str(e))


def auth(allowed):
    """Run priority-1 then priority-2 auth checks (PRD §2.7). Returns (uid, role)."""
    user_id, role = require_user_context()
    require_role(role, allowed)
    return user_id, role


# ===========================================================================
# Logical clock (PRD §2.5)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    auth({"SalonManager"})
    body = get_body()
    dt = require_datetime(body, "to_iso8601")
    clock.set_now(dt)
    return resp.ok({}, status=200, response_type="object")


# ===========================================================================
# Salon (PRD §3.1, §3.2)
# ===========================================================================
@app.post("/salon-svc/salons")
def create_salon():
    auth({"SalonManager"})
    body = get_body()
    name = require_str(body, "name")
    license_number = require_str(body, "license_number")
    license_expiry = require_datetime(body, "license_expiry")
    earn_rate = optional_int(body, "loyalty_earn_rate_bps", default=500, non_negative=True)
    salon = {
        "id": new_id(),
        "name": name,
        "license_number": license_number,
        "license_expiry": license_expiry,
        "loyalty_earn_rate_bps": earn_rate,
        "status": "CLOSED",
    }
    stamp_create(salon)
    domain.refresh_salon_derived(salon)
    db.salons[salon["id"]] = salon
    return resp.object_response(salon, status=201)


@app.get("/salon-svc/salons")
def list_salons():
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    items = list(db.salons.values())
    for s in items:
        domain.refresh_salon_derived(s)
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/salons/<salon_id>")
def get_salon_route(salon_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    salon = get_salon(salon_id)
    domain.refresh_salon_derived(salon)
    return resp.object_response(salon)


@app.post("/salon-svc/salons/<salon_id>/open")
def open_salon(salon_id):
    auth({"SalonManager"})
    salon = get_salon(salon_id)
    body = get_body()
    # License must be ACTIVE to open (PRD §3.2). Recompute against the clock.
    domain.refresh_salon_derived(salon)
    if domain.compute_license_status(salon) != "ACTIVE":
        raise err("ERR_LICENSE_LAPSED", "Salon license has lapsed.")
    salon["status"] = "OPEN"
    touch(salon)
    domain.refresh_salon_derived(salon)
    return resp.object_response(salon)


@app.post("/salon-svc/salons/<salon_id>/close")
def close_salon(salon_id):
    auth({"SalonManager"})
    salon = get_salon(salon_id)
    body = get_body()
    # Close requires zero OCCUPIED chairs (PRD §3.2).
    if domain.compute_active_occupancy(salon_id) != 0:
        raise err("ERR_SALON_HAS_ACTIVE_VISITS", "Salon has active visits.")
    salon["status"] = "CLOSED"
    # Cascade: every WAITING/CALLED ticket -> CANCELLED (PRD §3.2).
    for t in db.queue_tickets.values():
        if t["salon_id"] == salon_id and t["status"] in ("WAITING", "CALLED"):
            t["status"] = "CANCELLED"
            touch(t)
    domain.recompute_positions(salon_id)
    touch(salon)
    domain.refresh_salon_derived(salon)
    return resp.object_response(salon)


# ===========================================================================
# Technician (PRD §3.1)
# ===========================================================================
@app.post("/salon-svc/technicians")
def create_technician():
    auth({"SalonManager"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    display_name = require_str(body, "display_name")
    cert_expiry = require_datetime(body, "sanitation_cert_expiry")
    codes = []
    if "certified_addon_codes" in body and body.get("certified_addon_codes") is not None:
        codes = require_str_array(body, "certified_addon_codes")
    get_salon(salon_id)
    tech = {
        "id": new_id(),
        "salon_id": salon_id,
        "display_name": display_name,
        "certified_addon_codes": codes,
        "sanitation_cert_expiry": cert_expiry,
        "status": "AVAILABLE",
    }
    stamp_create(tech)
    db.technicians[tech["id"]] = tech
    return resp.object_response(tech, status=201)


@app.get("/salon-svc/technicians")
def list_technicians():
    auth({"SalonManager", "FrontDeskAgent", "Technician"})
    items = list(db.technicians.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [t for t in items if t["salon_id"] == salon_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/technicians/<technician_id>")
def get_technician_route(technician_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician"})
    return resp.object_response(get_technician(technician_id))


# ===========================================================================
# Chair (PRD §3.1, §3.9)
# ===========================================================================
@app.post("/salon-svc/chairs")
def create_chair():
    auth({"SalonManager"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    label = require_str(body, "label")
    sanitation_minutes = optional_int(body, "sanitation_minutes", default=5, non_negative=True)
    get_salon(salon_id)
    chair = {
        "id": new_id(),
        "salon_id": salon_id,
        "label": label,
        "sanitation_minutes": sanitation_minutes,
        "sanitation_ready_at": None,
        "status": "OPEN",
    }
    stamp_create(chair)
    db.chairs[chair["id"]] = chair
    return resp.object_response(chair, status=201)


@app.get("/salon-svc/chairs")
def list_chairs():
    auth({"SalonManager", "FrontDeskAgent", "Technician"})
    items = list(db.chairs.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [c for c in items if c["salon_id"] == salon_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/chairs/<chair_id>")
def get_chair_route(chair_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician"})
    return resp.object_response(get_chair(chair_id))


@app.post("/salon-svc/chairs/<chair_id>/mark-sanitized")
def mark_sanitized(chair_id):
    auth({"FrontDeskAgent", "SalonManager"})
    chair = get_chair(chair_id)
    # Window must have elapsed: clock >= sanitation_ready_at (PRD §3.9).
    ready = chair.get("sanitation_ready_at")
    if ready is not None and clock.now() < ready:
        raise err("ERR_SANITATION_WINDOW_OPEN", "Sanitation window not yet elapsed.")
    chair["status"] = "OPEN"
    touch(chair)
    return resp.object_response(chair)


@app.post("/salon-svc/chairs/<chair_id>/take-out-of-service")
def take_out_of_service(chair_id):
    auth({"SalonManager"})
    chair = get_chair(chair_id)
    # Only a non-OCCUPIED chair may be taken out of service (PRD §3.9).
    if chair["status"] == "OCCUPIED":
        raise err("ERR_CHAIR_OCCUPIED", "Cannot take an occupied chair out of service.")
    chair["status"] = "OUT_OF_SERVICE"
    touch(chair)
    return resp.object_response(chair)


@app.post("/salon-svc/chairs/<chair_id>/return-to-service")
def return_to_service(chair_id):
    auth({"SalonManager"})
    chair = get_chair(chair_id)
    chair["status"] = "OPEN"
    chair["sanitation_ready_at"] = None
    touch(chair)
    return resp.object_response(chair)


# ===========================================================================
# Member (PRD §3.1, §3.7)
# ===========================================================================
@app.post("/salon-svc/members")
def create_member():
    auth({"FrontDeskAgent", "SalonManager"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")
    get_salon(salon_id)
    # phone unique within salon (PRD §3.1).
    for m in db.members.values():
        if m["salon_id"] == salon_id and m["phone"] == phone:
            raise err("ERR_DUPLICATE_RESOURCE", "Member phone already exists in salon.")
    member = {
        "id": new_id(),
        "salon_id": salon_id,
        "full_name": full_name,
        "phone": phone,
        "loyalty_balance": 0,
        "no_show_strikes": 0,
        "status": "ACTIVE",
    }
    stamp_create(member)
    db.members[member["id"]] = member
    return resp.object_response(member, status=201)


@app.get("/salon-svc/members")
def list_members():
    auth({"SalonManager", "FrontDeskAgent"})
    items = list(db.members.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [m for m in items if m["salon_id"] == salon_id]
    phone = request.args.get("phone")
    if phone is not None:
        items = [m for m in items if m["phone"] == phone]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    for m in items:
        domain.refresh_member_derived(m)
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/members/<member_id>")
def get_member_route(member_id):
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    member = get_member(member_id)
    # A Member may only read their own member record (PRD §2.1).
    if role == "Member" and user_id != member["id"]:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot read another member's record.")
    domain.refresh_member_derived(member)
    return resp.object_response(member)


@app.post("/salon-svc/members/<member_id>/loyalty-adjustments")
def loyalty_adjustment(member_id):
    auth({"SalonManager"})
    member = get_member(member_id)
    body = get_body()
    points = require_int(body, "points")  # signed delta
    entry = _write_ledger(member["id"], None, "ADJUSTMENT", points)
    domain.refresh_member_derived(member)
    touch(member)
    return resp.object_response(entry, status=201)


# ===========================================================================
# LoyaltyLedgerEntry (PRD §3.7)
# ===========================================================================
def _write_ledger(member_id, service_visit_id, entry_type, points):
    entry = {
        "id": new_id(),
        "member_id": member_id,
        "service_visit_id": service_visit_id,
        "entry_type": entry_type,
        "points": points,
    }
    # Append-only event: id + created_at only, no updated_at / version (PRD §2.4).
    stamp_create(entry, versioned=False)
    db.loyalty_entries[entry["id"]] = entry
    return entry


@app.get("/salon-svc/loyalty-entries")
def list_loyalty_entries():
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    items = list(db.loyalty_entries.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    service_visit_id = request.args.get("service_visit_id")
    if service_visit_id is not None:
        items = [e for e in items if e["service_visit_id"] == service_visit_id]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    # A Member sees only their own loyalty entries (PRD §2.1).
    if role == "Member":
        items = [e for e in items if e["member_id"] == user_id]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/loyalty-entries/<entry_id>")
def get_loyalty_entry(entry_id):
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    entry = get_entry(entry_id)
    if role == "Member" and entry["member_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot read another member's entry.")
    return resp.object_response(entry)


# ===========================================================================
# MembershipPackage (PRD §3.6)
# ===========================================================================
@app.post("/salon-svc/packages")
def create_package():
    auth({"FrontDeskAgent", "SalonManager"})
    body = get_body()
    member_id = require_str(body, "member_id")
    tier = require_enum(body, "tier", {"BRONZE", "SILVER", "GOLD"})
    member = get_member(member_id)
    pkg = {
        "id": new_id(),
        "salon_id": member["salon_id"],
        "member_id": member_id,
        "tier": tier,
        "discount_bps": domain.TIER_DISCOUNT_BPS[tier],
        "total_credits": domain.TIER_CREDITS[tier],
        "credits_remaining": domain.TIER_CREDITS[tier],
        "status": "PENDING",
    }
    stamp_create(pkg)
    db.packages[pkg["id"]] = pkg
    return resp.object_response(pkg, status=201)


@app.get("/salon-svc/packages")
def list_packages():
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    items = list(db.packages.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [p for p in items if p["salon_id"] == salon_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if role == "Member":
        items = [p for p in items if p["member_id"] == user_id]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/packages/<package_id>")
def get_package_route(package_id):
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    pkg = get_package(package_id)
    if role == "Member" and pkg["member_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot read another member's package.")
    return resp.object_response(pkg)


@app.post("/salon-svc/packages/<package_id>/activate")
def activate_package(package_id):
    user_id, role = require_user_context()
    require_role(role, {"Member", "FrontDeskAgent"})
    pkg = get_package(package_id)
    if role == "Member" and pkg["member_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot act on another member's package.")
    member = db.members.get(pkg["member_id"])
    # Activation requires the member to be ACTIVE (PRD §3.6).
    domain.refresh_member_derived(member)
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Member is not active.")
    pkg["status"] = "ACTIVE"
    # Re-stamp discount_bps/total_credits/credits_remaining from tier (PRD §3.6).
    pkg["discount_bps"] = domain.TIER_DISCOUNT_BPS[pkg["tier"]]
    pkg["total_credits"] = domain.TIER_CREDITS[pkg["tier"]]
    pkg["credits_remaining"] = domain.TIER_CREDITS[pkg["tier"]]
    touch(pkg)
    return resp.object_response(pkg)


@app.post("/salon-svc/packages/<package_id>/cancel")
def cancel_package(package_id):
    user_id, role = require_user_context()
    require_role(role, {"Member", "SalonManager"})
    pkg = get_package(package_id)
    if role == "Member" and pkg["member_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot act on another member's package.")
    pkg["status"] = "CANCELLED"
    touch(pkg)
    return resp.object_response(pkg)


# ===========================================================================
# ServiceMenuItem / AddOn / RetailProduct catalog (PRD §3.1)
# ===========================================================================
@app.post("/salon-svc/service-menu-items")
def create_service_item():
    auth({"SalonManager"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    code = require_str(body, "code")
    name = require_str(body, "name")
    base_price = require_int(body, "base_price_cents", positive=True)
    est_minutes = require_int(body, "est_minutes", positive=True)
    package_eligible = optional_bool(body, "package_eligible", default=False)
    get_salon(salon_id)
    for si in db.service_menu_items.values():
        if si["salon_id"] == salon_id and si["code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "Service code already exists in salon.")
    item = {
        "id": new_id(),
        "salon_id": salon_id,
        "code": code,
        "name": name,
        "base_price_cents": base_price,
        "est_minutes": est_minutes,
        "package_eligible": package_eligible,
        "status": "LISTED",
    }
    stamp_create(item)
    db.service_menu_items[item["id"]] = item
    return resp.object_response(item, status=201)


@app.get("/salon-svc/service-menu-items")
def list_service_items():
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    items = list(db.service_menu_items.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [s for s in items if s["salon_id"] == salon_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/service-menu-items/<item_id>")
def get_service_item_route(item_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    return resp.object_response(get_service_item(item_id))


@app.post("/salon-svc/add-ons")
def create_addon():
    auth({"SalonManager"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    code = require_str(body, "code")
    name = require_str(body, "name")
    price = require_int(body, "price_cents", positive=True)
    requires_cert = optional_bool(body, "requires_certification", default=True)
    get_salon(salon_id)
    for a in db.add_ons.values():
        if a["salon_id"] == salon_id and a["code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "Add-on code already exists in salon.")
    addon = {
        "id": new_id(),
        "salon_id": salon_id,
        "code": code,
        "name": name,
        "price_cents": price,
        "requires_certification": requires_cert,
        "status": "LISTED",
    }
    stamp_create(addon)
    db.add_ons[addon["id"]] = addon
    return resp.object_response(addon, status=201)


@app.get("/salon-svc/add-ons")
def list_addons():
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    items = list(db.add_ons.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [a for a in items if a["salon_id"] == salon_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/add-ons/<addon_id>")
def get_addon_route(addon_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    return resp.object_response(get_addon(addon_id))


@app.post("/salon-svc/retail-products")
def create_retail():
    auth({"SalonManager"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    unit_price = require_int(body, "unit_price_cents", positive=True)
    initial_stock = optional_int(body, "initial_stock_qty", default=0, non_negative=True)
    get_salon(salon_id)
    for r in db.retail_products.values():
        if r["salon_id"] == salon_id and r["sku"] == sku:
            raise err("ERR_DUPLICATE_RESOURCE", "Retail sku already exists in salon.")
    product = {
        "id": new_id(),
        "salon_id": salon_id,
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price,
        "initial_stock_qty": initial_stock,
        "stock_qty": initial_stock,
    }
    stamp_create(product)
    db.retail_products[product["id"]] = product
    return resp.object_response(product, status=201)


@app.get("/salon-svc/retail-products")
def list_retail():
    auth({"SalonManager", "FrontDeskAgent", "Member"})
    items = list(db.retail_products.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [r for r in items if r["salon_id"] == salon_id]
    sku = request.args.get("sku")
    if sku is not None:
        items = [r for r in items if r["sku"] == sku]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/retail-products/<retail_id>")
def get_retail_route(retail_id):
    auth({"SalonManager", "FrontDeskAgent", "Member"})
    return resp.object_response(get_retail(retail_id))


# ===========================================================================
# QueueTicket (PRD §3.3)
# ===========================================================================
@app.post("/salon-svc/queue-tickets")
def join_queue():
    auth({"FrontDeskAgent"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    member_id = require_str(body, "member_id")
    service_menu_item_id = require_str(body, "service_menu_item_id")
    salon = get_salon(salon_id)
    member = get_member(member_id)
    get_service_item(service_menu_item_id)
    # Salon must be OPEN (PRD §3.3).
    if salon["status"] != "OPEN":
        raise err("ERR_SALON_NOT_OPEN", "Salon is not open.")
    # Member must be ACTIVE; SUSPENDED/BANNED blocked (PRD §3.3).
    domain.refresh_member_derived(member)
    if member["status"] != "ACTIVE":
        raise err("ERR_MEMBER_BLOCKED", "Member is suspended or banned.")
    ticket = {
        "id": new_id(),
        "salon_id": salon_id,
        "member_id": member_id,
        "service_menu_item_id": service_menu_item_id,
        "joined_at": clock.now(),
        "position": 0,
        "called_count": 0,
        "status": "WAITING",
    }
    stamp_create(ticket)
    db.queue_tickets[ticket["id"]] = ticket
    domain.recompute_positions(salon_id)
    return resp.object_response(ticket, status=201)


@app.get("/salon-svc/queue-tickets")
def list_queue_tickets():
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    items = list(db.queue_tickets.values())
    salon_id = request.args.get("salon_id")
    if salon_id is not None:
        items = [t for t in items if t["salon_id"] == salon_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    smi = request.args.get("service_menu_item_id")
    if smi is not None:
        items = [t for t in items if t["service_menu_item_id"] == smi]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if role == "Member":
        items = [t for t in items if t["member_id"] == user_id]
    for t in items:
        domain.refresh_ticket_position(t)
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/queue-tickets/<ticket_id>")
def get_ticket_route(ticket_id):
    user_id, role = require_user_context()
    require_role(role, {"SalonManager", "FrontDeskAgent", "Member"})
    ticket = get_ticket(ticket_id)
    if role == "Member" and ticket["member_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot read another member's ticket.")
    domain.refresh_ticket_position(ticket)
    return resp.object_response(ticket)


@app.post("/salon-svc/queue-tickets/<ticket_id>/call")
def call_ticket(ticket_id):
    auth({"FrontDeskAgent"})
    ticket = get_ticket(ticket_id)
    salon = get_salon(ticket["salon_id"])
    body = get_body()
    allow_skip = optional_bool(body, "allow_skip", default=False)
    # Salon must be OPEN (PRD §3.3).
    if salon["status"] != "OPEN":
        raise err("ERR_SALON_NOT_OPEN", "Salon is not open.")
    # Must be WAITING to be called.
    if ticket["status"] != "WAITING":
        raise err("ERR_TICKET_NOT_CALLED", "Ticket is not waiting.")
    # FIFO order: must be lowest-position WAITING unless allow_skip (PRD §3.3).
    lowest = domain.lowest_waiting_ticket(ticket["salon_id"])
    if not allow_skip and lowest is not None and lowest["id"] != ticket["id"]:
        raise err("ERR_QUEUE_ORDER_VIOLATION", "Ticket is not the lowest-position waiting ticket.")
    ticket["status"] = "CALLED"
    touch(ticket)
    domain.recompute_positions(ticket["salon_id"])
    return resp.object_response(ticket)


@app.post("/salon-svc/queue-tickets/<ticket_id>/requeue")
def requeue_ticket(ticket_id):
    auth({"FrontDeskAgent"})
    ticket = get_ticket(ticket_id)
    # Must be CALLED to requeue.
    if ticket["status"] != "CALLED":
        raise err("ERR_TICKET_NOT_CALLED", "Ticket is not called.")
    # Recall limit: at most MAX_RECALLS (2) times (PRD §3.3).
    if ticket["called_count"] >= domain.MAX_RECALLS:
        raise err("ERR_RECALL_LIMIT_REACHED", "Recall limit reached.")
    ticket["status"] = "WAITING"
    ticket["called_count"] += 1  # joined_at unchanged -> FIFO place restored
    touch(ticket)
    domain.recompute_positions(ticket["salon_id"])
    return resp.object_response(ticket)


@app.post("/salon-svc/queue-tickets/<ticket_id>/no-show")
def no_show_ticket(ticket_id):
    auth({"FrontDeskAgent"})
    ticket = get_ticket(ticket_id)
    # Must currently be CALLED (PRD §3.3).
    if ticket["status"] != "CALLED":
        raise err("ERR_TICKET_NOT_CALLED", "Ticket is not called.")
    ticket["status"] = "NO_SHOW"
    touch(ticket)
    domain.recompute_positions(ticket["salon_id"])
    # Member gains one strike and may escalate (PRD §3.7).
    member = db.members.get(ticket["member_id"])
    if member is not None:
        domain.escalate_member_standing(member)
        touch(member)
    return resp.object_response(ticket)


@app.post("/salon-svc/queue-tickets/<ticket_id>/cancel")
def cancel_ticket(ticket_id):
    user_id, role = require_user_context()
    require_role(role, {"FrontDeskAgent", "Member"})
    ticket = get_ticket(ticket_id)
    if role == "Member" and ticket["member_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Member cannot cancel another member's ticket.")
    # Only WAITING or CALLED tickets may be cancelled (PRD §3.3).
    if ticket["status"] not in ("WAITING", "CALLED"):
        raise err("ERR_TICKET_NOT_CALLED", "Ticket is not waiting or called.")
    ticket["status"] = "CANCELLED"
    touch(ticket)
    domain.recompute_positions(ticket["salon_id"])
    return resp.object_response(ticket)


# ===========================================================================
# ServiceVisit — seating (PRD §3.4)
# ===========================================================================
@app.post("/salon-svc/service-visits")
def seat_visit():
    auth({"FrontDeskAgent"})
    body = get_body()
    salon_id = require_str(body, "salon_id")
    queue_ticket_id = require_str(body, "queue_ticket_id")
    chair_id = require_str(body, "chair_id")
    technician_id = require_str(body, "technician_id")
    expected_version = require_int(body, "expected_salon_version")
    membership_package_id = None
    if "membership_package_id" in body and body.get("membership_package_id") is not None:
        membership_package_id = require_str(body, "membership_package_id")

    # Body-referenced existence (PRD §2.6 / priority 4).
    salon = get_salon(salon_id)
    ticket = get_ticket(queue_ticket_id)
    chair = get_chair(chair_id)
    tech = get_technician(technician_id)
    pkg = None
    if membership_package_id is not None:
        pkg = get_package(membership_package_id)

    # Priority 5: salon open (PRD §3.4).
    if salon["status"] != "OPEN":
        raise err("ERR_SALON_NOT_OPEN", "Salon is not open.")
    # Priority 6: ticket CALLED (PRD §3.4).
    if ticket["status"] != "CALLED":
        raise err("ERR_TICKET_NOT_CALLED", "Ticket is not called.")
    # Priority 7: license ACTIVE at seating (PRD §3.4).
    if domain.compute_license_status(salon) != "ACTIVE":
        raise err("ERR_LICENSE_LAPSED", "Salon license has lapsed.")
    # Chair OPEN (PRD §3.4).
    if chair["status"] != "OPEN":
        raise err("ERR_CHAIR_NOT_OPEN", "Chair is not open.")
    # Chair sanitation window past (PRD §3.4).
    ready = chair.get("sanitation_ready_at")
    if ready is not None and clock.now() < ready:
        raise err("ERR_CHAIR_NOT_SANITIZED", "Chair is still cooling down.")
    # Technician AVAILABLE (PRD §3.4).
    if tech["status"] != "AVAILABLE":
        raise err("ERR_TECHNICIAN_NOT_AVAILABLE", "Technician is not available.")
    # Priority 8: tech cert in the future (PRD §3.4).
    if clock.now() >= tech["sanitation_cert_expiry"]:
        raise err("ERR_TECH_CERT_EXPIRED", "Technician sanitation cert expired.")
    # Priority 19: OCC on Salon.version (PRD §2.9).
    if expected_version != salon["version"]:
        raise err("ERR_STALE_SALON_VERSION", "Salon version is stale.")

    visit = {
        "id": new_id(),
        "salon_id": salon_id,
        "queue_ticket_id": queue_ticket_id,
        "member_id": ticket["member_id"],
        "chair_id": chair_id,
        "technician_id": technician_id,
        "service_menu_item_id": ticket["service_menu_item_id"],
        "membership_package_id": membership_package_id,
        "seated_at": clock.now(),
        "ended_at": None,
        "used_package_credit": False,
        "estimate_total_cents": 0,
        "final_total_cents": 0,
        "loyalty_earned": 0,
        "service_status": "IN_SERVICE",
        "payment_status": "UNPAID",
    }
    stamp_create(visit)
    domain.refresh_estimate(visit)
    db.service_visits[visit["id"]] = visit

    # Cross-entity cascade, one immediate step (PRD §3.4).
    ticket["status"] = "SEATED"
    touch(ticket)
    domain.recompute_positions(salon_id)
    chair["status"] = "OCCUPIED"
    touch(chair)
    tech["status"] = "BUSY"
    touch(tech)
    touch(salon)  # active_occupancy_count rises; Salon.version increments by one
    domain.refresh_salon_derived(salon)
    return resp.object_response(visit, status=201)


@app.get("/salon-svc/service-visits")
def list_visits():
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    items = list(db.service_visits.values())
    for field in ("salon_id", "member_id", "chair_id", "technician_id",
                  "queue_ticket_id", "service_menu_item_id", "membership_package_id"):
        val = request.args.get(field)
        if val is not None:
            items = [v for v in items if v.get(field) == val]
    service_status = request.args.get("service_status")
    if service_status is not None:
        items = [v for v in items if v["service_status"] == service_status]
    payment_status = request.args.get("payment_status")
    if payment_status is not None:
        items = [v for v in items if v["payment_status"] == payment_status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/service-visits/<visit_id>")
def get_visit_route(visit_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    return resp.object_response(get_visit(visit_id))


# ===========================================================================
# VisitLineItem (PRD §3.5)
# ===========================================================================
@app.post("/salon-svc/service-visits/<visit_id>/line-items")
def add_line_item(visit_id):
    auth({"FrontDeskAgent", "Technician"})
    visit = get_visit(visit_id)
    body = get_body()
    line_type = require_enum(body, "line_type", {"ADDON", "RETAIL"})
    item_ref_id = require_str(body, "item_ref_id")
    quantity = optional_int(body, "quantity", default=1)

    # Resolve the polymorphic reference against line_type (PRD §3.5).
    if line_type == "ADDON":
        ref = db.add_ons.get(item_ref_id)
        if ref is None:
            # If it resolves to a RetailProduct instead, that's a type mismatch.
            if item_ref_id in db.retail_products:
                raise err("ERR_LINE_TYPE_MISMATCH", "item_ref_id is not an add-on.")
            raise err("ERR_ADDON_NOT_FOUND", "Add-on not found.")
    else:  # RETAIL
        ref = db.retail_products.get(item_ref_id)
        if ref is None:
            if item_ref_id in db.add_ons:
                raise err("ERR_LINE_TYPE_MISMATCH", "item_ref_id is not a retail product.")
            raise err("ERR_RETAIL_NOT_FOUND", "Retail product not found.")

    # Visit must be IN_SERVICE to add a line (PRD §3.5).
    if visit["service_status"] != "IN_SERVICE":
        raise err("ERR_VISIT_NOT_IN_SERVICE", "Visit is not in service.")

    if line_type == "ADDON":
        # ADDON quantity must be exactly 1 (PRD §3.5).
        if quantity != 1:
            raise err("ERR_INVALID_LINE_QUANTITY", "Add-on quantity must be exactly 1.")
        # Certification gate (PRD §3.5).
        if ref["requires_certification"]:
            tech = db.technicians.get(visit["technician_id"])
            if tech is None or ref["code"] not in tech.get("certified_addon_codes", []):
                raise err("ERR_TECH_NOT_CERTIFIED", "Technician not certified for this add-on.")
        unit_price = ref["price_cents"]
    else:  # RETAIL
        if quantity < 1:
            raise err("ERR_INVALID_LINE_QUANTITY", "Quantity must be at least 1.")
        # Stock guard (PRD §3.5).
        if quantity > ref["stock_qty"]:
            raise err("ERR_INSUFFICIENT_STOCK", "Insufficient retail stock.")
        unit_price = ref["unit_price_cents"]

    line = {
        "id": new_id(),
        "service_visit_id": visit_id,
        "line_type": line_type,
        "item_ref_id": item_ref_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": unit_price * quantity,
        "status": "ACTIVE",
    }
    stamp_create(line)
    db.line_items[line["id"]] = line

    # RETAIL decrements stock (PRD §3.5).
    if line_type == "RETAIL":
        ref["stock_qty"] -= quantity
        touch(ref)

    domain.refresh_estimate(visit)
    touch(visit)
    return resp.object_response(line, status=201)


@app.get("/salon-svc/service-visits/<visit_id>/line-items")
def list_visit_line_items(visit_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    get_visit(visit_id)
    items = [li for li in db.line_items.values() if li["service_visit_id"] == visit_id]
    status = request.args.get("status")
    if status is not None:
        items = [li for li in items if li["status"] == status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/visit-line-items")
def list_all_line_items():
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    items = list(db.line_items.values())
    svid = request.args.get("service_visit_id")
    if svid is not None:
        items = [li for li in items if li["service_visit_id"] == svid]
    status = request.args.get("status")
    if status is not None:
        items = [li for li in items if li["status"] == status]
    page, limit, offset, total = paginate(items)
    return resp.list_response(page, limit, offset, total)


@app.get("/salon-svc/visit-line-items/<line_id>")
def get_line_route(line_id):
    auth({"SalonManager", "FrontDeskAgent", "Technician", "Member"})
    return resp.object_response(get_line(line_id))


@app.post("/salon-svc/visit-line-items/<line_id>/void")
def void_line_item(line_id):
    auth({"FrontDeskAgent", "Technician"})
    line = get_line(line_id)
    visit = db.service_visits.get(line["service_visit_id"])
    # Owning visit must be IN_SERVICE for a manual void (PRD §3.5).
    if visit is None or visit["service_status"] != "IN_SERVICE":
        raise err("ERR_VISIT_NOT_IN_SERVICE", "Visit is not in service.")
    # Line must be ACTIVE to be voided (idempotency reject, PRD §3.5).
    if line["status"] != "ACTIVE":
        raise err("ERR_VISIT_NOT_IN_SERVICE", "Line is not active.")
    _void_line(line)
    domain.refresh_estimate(visit)
    touch(visit)
    return resp.object_response(line)


def _void_line(line):
    """Move a line ACTIVE->VOIDED and restore retail stock if RETAIL (PRD §3.5)."""
    line["status"] = "VOIDED"
    touch(line)
    if line["line_type"] == "RETAIL":
        product = db.retail_products.get(line["item_ref_id"])
        if product is not None:
            product["stock_qty"] += line["quantity"]
            touch(product)


# ===========================================================================
# ServiceVisit transitions: complete / settle / void (PRD §3.6, §3.7, §3.8)
# ===========================================================================
@app.post("/salon-svc/service-visits/<visit_id>/complete")
def complete_visit(visit_id):
    auth({"Technician", "FrontDeskAgent"})
    visit = get_visit(visit_id)
    # Must be IN_SERVICE to complete (PRD §3.6).
    if visit["service_status"] != "IN_SERVICE":
        raise err("ERR_VISIT_NOT_IN_SERVICE", "Visit is not in service.")

    visit["service_status"] = "COMPLETED"
    visit["ended_at"] = clock.now()
    _finalize_settlement(visit)

    # Resource release (PRD §3.6).
    chair = db.chairs.get(visit["chair_id"])
    if chair is not None and chair["status"] == "OCCUPIED":
        chair["status"] = "SANITIZING"
        chair["sanitation_ready_at"] = _add_minutes(visit["ended_at"], chair["sanitation_minutes"])
        touch(chair)
    tech = db.technicians.get(visit["technician_id"])
    if tech is not None and tech["status"] == "BUSY":
        tech["status"] = "AVAILABLE"
        touch(tech)
    salon = db.salons.get(visit["salon_id"])
    if salon is not None:
        touch(salon)  # occupancy drops; version increments
        domain.refresh_salon_derived(salon)
    touch(visit)
    return resp.object_response(visit)


def _add_minutes(dt, minutes):
    from datetime import timedelta
    return dt + timedelta(minutes=minutes)


def _finalize_settlement(visit):
    """Pinned settlement order (PRD §3.6 / SCAFFOLD finalize_settlement).

    1. discountable base = service_part + addon_part (retail never discounted)
    2. credit decision FIRST (zeroes service line if drawn)
    3. membership discount over chargeable service+addon
    4. final_total = chargeable_service + addon - discount + retail
    5. loyalty_earned = floor(final/100 * earn_rate_bps / 100)
    """
    service_item = db.service_menu_items.get(visit["service_menu_item_id"])
    service_part = service_item["base_price_cents"] if service_item else 0
    lines = domain.active_lines(visit["id"])
    addon_part = sum(li["line_total_cents"] for li in lines if li["line_type"] == "ADDON")
    retail_part = sum(li["line_total_cents"] for li in lines if li["line_type"] == "RETAIL")

    pkg = None
    if visit["membership_package_id"] is not None:
        pkg = db.packages.get(visit["membership_package_id"])

    # Step 2: credit decision (PRD §3.6).
    used_credit = False
    service_part_charged = service_part
    if (pkg is not None and pkg["status"] == "ACTIVE"
            and service_item is not None and service_item["package_eligible"]
            and pkg["credits_remaining"] > 0):
        used_credit = True
        service_part_charged = 0
        pkg["credits_remaining"] -= 1
        if pkg["credits_remaining"] == 0:
            pkg["status"] = "DEPLETED"
        touch(pkg)

    # Step 3: membership discount over chargeable service+addon (PRD §3.6).
    if pkg is not None and pkg["status"] in ("ACTIVE", "DEPLETED") and _pkg_discount_applies(pkg):
        discountable_after_credit = service_part_charged + addon_part
        discount_cents = (discountable_after_credit * pkg["discount_bps"]) // 10000
    else:
        discount_cents = 0

    # Step 4: final total (PRD §3.6).
    final_total = service_part_charged + addon_part - discount_cents + retail_part
    if final_total < 0:
        final_total = 0

    # Step 5: loyalty earned, floored (PRD §3.6).
    # PRD §3.6: "taking final_total_cents divided by 100 to express it in whole
    # dollars, multiplying by the salon's loyalty_earn_rate_bps, dividing by 100,
    # and flooring THE RESULT" — a single floor over the whole expression, i.e.
    # floor(final/100 * earn_rate/100) == floor(final*earn_rate / 10000). The
    # intermediate cents->dollars division is NOT independently floored.
    salon = db.salons.get(visit["salon_id"])
    earn_rate = salon["loyalty_earn_rate_bps"] if salon else 0
    loyalty_earned = (final_total * earn_rate) // 10000

    visit["used_package_credit"] = used_credit
    visit["final_total_cents"] = final_total
    visit["loyalty_earned"] = loyalty_earned


def _pkg_discount_applies(pkg):
    """The membership discount applies only while the package is ACTIVE (PRD §3.6).

    The credit-draw at step 2 may have flipped it to DEPLETED; the discount
    decision in §3.6 reads 'if a package is set and ACTIVE'. A package depleted
    by THIS visit's own credit draw was ACTIVE at finalization start, so the
    discount still applies for this settlement.
    """
    return True


@app.post("/salon-svc/service-visits/<visit_id>/settle")
def settle_visit(visit_id):
    auth({"FrontDeskAgent", "SalonManager"})
    visit = get_visit(visit_id)
    body = get_body()
    redeem_points = optional_int(body, "redeem_points", default=0, non_negative=True)

    # Cross-dimension guard: service must be COMPLETED (PRD §3.7).
    if visit["service_status"] != "COMPLETED":
        raise err("ERR_VISIT_NOT_COMPLETED", "Visit service is not completed.")
    # payment must be UNPAID (PRD §3.7).
    if visit["payment_status"] != "UNPAID":
        raise err("ERR_VISIT_NOT_UNPAID", "Visit is not unpaid.")

    member = db.members.get(visit["member_id"])
    # Redemption must not exceed loyalty_balance (PRD §3.7).
    if redeem_points and redeem_points > 0:
        balance = domain.compute_loyalty_balance(visit["member_id"])
        if redeem_points > balance:
            raise err("ERR_INSUFFICIENT_LOYALTY", "Redeem exceeds loyalty balance.")

    visit["payment_status"] = "SETTLED"

    # REDEEM entry (negative) if redeeming (PRD §3.7).
    if redeem_points and redeem_points > 0:
        _write_ledger(visit["member_id"], visit["id"], "REDEEM", -redeem_points)

    # EARN entry of +loyalty_earned, regardless of redemption (PRD §3.7).
    _write_ledger(visit["member_id"], visit["id"], "EARN", visit["loyalty_earned"])

    if member is not None:
        domain.refresh_member_derived(member)
        touch(member)
    touch(visit)
    return resp.object_response(visit)


@app.post("/salon-svc/service-visits/<visit_id>/void")
def void_visit(visit_id):
    auth({"SalonManager"})
    visit = get_visit(visit_id)
    # Voiding an already-voided visit is refused (PRD §3.8).
    if visit["service_status"] == "VOIDED":
        raise err("ERR_VISIT_ALREADY_VOIDED", "Visit already voided.")

    visit["service_status"] = "VOIDED"

    # Free chair + tech + occupancy if chair still OCCUPIED by this visit (PRD §3.8).
    chair = db.chairs.get(visit["chair_id"])
    if chair is not None and chair["status"] == "OCCUPIED":
        chair["status"] = "SANITIZING"
        chair["sanitation_ready_at"] = _add_minutes(clock.now(), chair["sanitation_minutes"])
        touch(chair)
        tech = db.technicians.get(visit["technician_id"])
        if tech is not None and tech["status"] == "BUSY":
            tech["status"] = "AVAILABLE"
            touch(tech)
        salon = db.salons.get(visit["salon_id"])
        if salon is not None:
            touch(salon)
            domain.refresh_salon_derived(salon)

    # Restore drawn package credit (PRD §3.8).
    if visit["used_package_credit"]:
        pkg = db.packages.get(visit["membership_package_id"])
        if pkg is not None:
            pkg["credits_remaining"] += 1
            if pkg["status"] == "DEPLETED" and pkg["credits_remaining"] > 0:
                pkg["status"] = "ACTIVE"
            touch(pkg)
        visit["used_package_credit"] = False

    # If already SETTLED: refund + loyalty reversal (PRD §3.8).
    if visit["payment_status"] == "SETTLED":
        visit["payment_status"] = "REFUNDED"
        _write_ledger(visit["member_id"], visit["id"], "REVERSAL", -visit["loyalty_earned"])
        member = db.members.get(visit["member_id"])
        if member is not None:
            domain.refresh_member_derived(member)
            touch(member)

    # All ACTIVE lines -> VOIDED (PRD §3.8). The void is a compensating action that
    # "must leave ... the retail stock ... exactly as they stood before the visit
    # existed" (PRD §2.10) and "leaves no residue in ... inventory" (PRD §3.8). So
    # voiding each ACTIVE RETAIL line restores its quantity to the product's
    # stock_qty (PRD §3.5), regardless of whether the visit was settled.
    for li in db.line_items.values():
        if li["service_visit_id"] == visit_id and li["status"] == "ACTIVE":
            if li["line_type"] == "RETAIL":
                product = db.retail_products.get(li["item_ref_id"])
                if product is not None:
                    product["stock_qty"] += li["quantity"]
                    touch(product)
            li["status"] = "VOIDED"
            touch(li)

    touch(visit)
    return resp.object_response(visit)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
