"""Shoe / Leather & Watch Repair API — Flask entry point.

In-memory storage only; state starts empty on every boot. No seeding.
Binds 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask, request

import clock
import db
import calculations as calc
import services as svc
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response, error_response
from serialize import public, public_list
from validation import (
    get_json_body, parse_pagination, paginate,
    require_str, require_int, require_enum, present,
)

app = Flask(__name__)

ITEM_CATEGORIES = {"SHOE", "LEATHER", "WATCH"}
CONDITION_GRADES = {"EXCELLENT", "GOOD", "FAIR", "POOR"}
NOTIFY_CHANNELS = {"EMAIL", "SMS"}
PRIORITIES = {"STANDARD", "RUSH"}
PAYMENT_METHODS = {"CASH", "CARD", "STORE_CREDIT"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % err, 500)


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> not-found family)
# ---------------------------------------------------------------------------
def _lookup(coll, rid, err_id):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(err_id, "Resource not found")
    return rec


def find_ticket(tid):
    return _lookup(db.repair_tickets, tid, "ERR_TICKET_NOT_FOUND")


def find_estimate(eid):
    return _lookup(db.estimates, eid, "ERR_ESTIMATE_NOT_FOUND")


def find_part(pid):
    return _lookup(db.parts_orders, pid, "ERR_PARTS_ORDER_NOT_FOUND")


def find_line(lid):
    return _lookup(db.service_lines, lid, "ERR_SERVICE_LINE_NOT_FOUND")


def find_item(iid):
    return _lookup(db.ticket_items, iid, "ERR_TICKET_ITEM_NOT_FOUND")


def find_claim(cid):
    return _lookup(db.warranty_claims, cid, "ERR_CLAIM_NOT_FOUND")


def find_customer(cid):
    return _lookup(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")


def find_service_type(sid):
    return _lookup(db.service_types, sid, "ERR_SERVICE_TYPE_NOT_FOUND")


def find_technician(tid):
    # No dedicated not-found in catalog; technicians are referenced via FK only.
    return db.technicians.get(tid)


def check_occ(ticket, body):
    """OCC check (priority 7): expected_ticket_version must match ticket.version."""
    expected = body.get("expected_ticket_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_ticket_version must be an integer")
    if expected != ticket["version"]:
        raise ApiError("ERR_STALE_TICKET_VERSION", "Ticket version is stale")


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    body = get_json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or raw.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required")
    try:
        dt = clock.parse_iso(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 timestamp")
    clock.set_now(dt)
    return object_response({"now": clock.to_iso(dt)}, 200)


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = require_str(body, "phone")
    notify_channel = "EMAIL"
    if present(body, "notify_channel"):
        notify_channel = require_enum(body, "notify_channel", NOTIFY_CHANNELS)

    # uniqueness (priority 5)
    for c in db.customers.values():
        if c["email"] == email:
            raise ApiError("ERR_DUPLICATE_KEY", "Customer email already exists")

    rec = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "notify_channel": notify_channel,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.customers[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/customers", methods=["GET"])
def list_customers():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    limit, offset = parse_pagination()
    email = request.args.get("email")
    records = list(db.customers.values())
    if email is not None:
        records = [c for c in records if c["email"] == email]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = find_customer(cid)
    return object_response(public(rec), 200)


# ===========================================================================
# ServiceType
# ===========================================================================
@app.route("/service-types", methods=["POST"])
def create_service_type():
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    body = get_json_body()
    code = require_str(body, "code")
    name = require_str(body, "name")
    item_category = require_enum(body, "item_category", ITEM_CATEGORIES)
    base_price_cents = require_int(body, "base_price_cents", minimum=0)
    standard_turnaround_days = require_int(body, "standard_turnaround_days", minimum=1)
    warranty_days = require_int(body, "warranty_days", minimum=0)
    rush_eligible = True
    if present(body, "rush_eligible"):
        v = body.get("rush_eligible")
        if not isinstance(v, bool):
            raise ApiError("ERR_INVALID_REQUEST", "rush_eligible must be boolean")
        rush_eligible = v

    for st in db.service_types.values():
        if st["code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY", "ServiceType code already exists")

    rec = {
        "id": db.new_id(),
        "code": code,
        "name": name,
        "item_category": item_category,
        "base_price_cents": base_price_cents,
        "standard_turnaround_days": standard_turnaround_days,
        "rush_eligible": rush_eligible,
        "warranty_days": warranty_days,
        "active": True,
    }
    db.stamp_create(rec)
    db.service_types[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/service-types", methods=["GET"])
def list_service_types():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    limit, offset = parse_pagination()
    item_category = request.args.get("item_category")
    records = list(db.service_types.values())
    if item_category is not None:
        records = [s for s in records if s["item_category"] == item_category]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/service-types/<sid>", methods=["GET"])
def get_service_type(sid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    rec = find_service_type(sid)
    return object_response(public(rec), 200)


@app.route("/service-types/<sid>/retire", methods=["POST"])
def retire_service_type(sid):
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    rec = find_service_type(sid)
    rec["active"] = False
    db.touch(rec)
    return object_response(public(rec), 200)


# ===========================================================================
# Technician
# ===========================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    body = get_json_body()
    display_name = require_str(body, "display_name")
    skills = body.get("skills")
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise ApiError("ERR_INVALID_REQUEST", "skills must be an array of strings")
    for s in skills:
        if s not in ITEM_CATEGORIES:
            raise ApiError("ERR_INVALID_REQUEST", "skills must be a subset of item categories")

    rec = {
        "id": db.new_id(),
        "display_name": display_name,
        "skills": skills,
        "active": True,
    }
    db.stamp_create(rec)
    db.technicians[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/technicians", methods=["GET"])
def list_technicians():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    limit, offset = parse_pagination()
    records = list(db.technicians.values())
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    rec = find_technician(tid)
    if rec is None:
        # technician has no dedicated not-found in the catalog; treat as 404 generic
        raise ApiError("ERR_FK_NOT_FOUND", "Technician not found")
    return object_response(public(rec), 200)


# ===========================================================================
# RepairTicket
# ===========================================================================
@app.route("/repair-tickets", methods=["POST"])
def create_ticket():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk"})
    body = get_json_body()
    customer_id = require_str(body, "customer_id")

    priority = "STANDARD"
    if present(body, "priority"):
        priority = require_enum(body, "priority", PRIORITIES)

    assigned_technician_id = None
    if present(body, "assigned_technician_id"):
        assigned_technician_id = require_str(body, "assigned_technician_id")

    # FK resolution (priority 4)
    if customer_id not in db.customers:
        raise ApiError("ERR_FK_NOT_FOUND", "customer_id does not resolve")
    if assigned_technician_id is not None and assigned_technician_id not in db.technicians:
        raise ApiError("ERR_FK_NOT_FOUND", "assigned_technician_id does not resolve")

    rec = {
        "id": db.new_id(),
        "customer_id": customer_id,
        "drop_off_at": clock.now(),
        "priority": priority,
        "repair_status": "INTAKE",
        "notify_status": "NONE",
        "ready_by": None,
        "ready_at": None,
        "sla_breached": False,
        "approved_estimate_id": None,
        "final_charge_cents": None,
        "amount_paid_cents": 0,
        "warranty_expires_at": None,
        "picked_up_at": None,
        "assigned_technician_id": assigned_technician_id,
    }
    db.stamp_create(rec)
    db.repair_tickets[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/repair-tickets", methods=["GET"])
def list_tickets():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    limit, offset = parse_pagination()
    records = list(db.repair_tickets.values())
    for field in ("customer_id", "approved_estimate_id", "assigned_technician_id", "repair_status"):
        val = request.args.get(field)
        if val is not None:
            records = [t for t in records if t.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/repair-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = find_ticket(tid)
    return object_response(public(rec), 200)


@app.route("/repair-tickets/<tid>", methods=["PATCH"])
def patch_ticket(tid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager"})
    ticket = find_ticket(tid)
    body = get_json_body()

    new_tech = None
    if present(body, "assigned_technician_id"):
        new_tech = require_str(body, "assigned_technician_id")
        if new_tech not in db.technicians:
            raise ApiError("ERR_FK_NOT_FOUND", "assigned_technician_id does not resolve")

    new_priority = None
    if present(body, "priority"):
        new_priority = require_enum(body, "priority", PRIORITIES)

    changed = False
    if new_tech is not None:
        ticket["assigned_technician_id"] = new_tech
        changed = True
    if new_priority is not None:
        ticket["priority"] = new_priority
        changed = True
    if changed:
        db.touch(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/start-repair", methods=["POST"])
def ticket_start_repair(tid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    ticket = find_ticket(tid)
    svc.start_repair(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/mark-ready", methods=["POST"])
def ticket_mark_ready(tid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    ticket = find_ticket(tid)
    svc.mark_ready(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/notify-ready", methods=["POST"])
def ticket_notify_ready(tid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk"})
    ticket = find_ticket(tid)
    svc.notify_ready(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/pickup", methods=["POST"])
def ticket_pickup(tid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk"})
    ticket = find_ticket(tid)
    svc.pickup(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/flag-unclaimed", methods=["POST"])
def ticket_flag_unclaimed(tid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk"})
    ticket = find_ticket(tid)
    svc.flag_unclaimed(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/dispose", methods=["POST"])
def ticket_dispose(tid):
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    ticket = find_ticket(tid)
    svc.dispose(ticket)
    return object_response(public(ticket), 200)


@app.route("/repair-tickets/<tid>/cancel", methods=["POST"])
def ticket_cancel(tid):
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    ticket = find_ticket(tid)
    svc.cancel_ticket(ticket)
    return object_response(public(ticket), 200)


# ===========================================================================
# TicketItem
# ===========================================================================
@app.route("/ticket-items", methods=["POST"])
def create_ticket_item():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk"})
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    item_category = require_enum(body, "item_category", ITEM_CATEGORIES)
    description = require_str(body, "description")
    condition_grade = require_enum(body, "condition_grade", CONDITION_GRADES)
    condition_notes = ""
    if present(body, "condition_notes"):
        condition_notes = require_str(body, "condition_notes", allow_empty=True)

    if ticket_id not in db.repair_tickets:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_id does not resolve")

    rec = {
        "id": db.new_id(),
        "ticket_id": ticket_id,
        "item_category": item_category,
        "description": description,
        "condition_grade": condition_grade,
        "condition_notes": condition_notes,
    }
    db.stamp_create(rec)
    db.ticket_items[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/ticket-items", methods=["GET"])
def list_ticket_items():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    limit, offset = parse_pagination()
    records = list(db.ticket_items.values())
    ticket_id = request.args.get("ticket_id")
    if ticket_id is not None:
        records = [i for i in records if i["ticket_id"] == ticket_id]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/ticket-items/<iid>", methods=["GET"])
def get_ticket_item(iid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = find_item(iid)
    return object_response(public(rec), 200)


# ===========================================================================
# ServiceLine
# ===========================================================================
@app.route("/service-lines", methods=["POST"])
def create_service_line():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "RepairTechnician"})
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    ticket_item_id = require_str(body, "ticket_item_id")
    service_type_id = require_str(body, "service_type_id")

    # FK resolution + same-ticket consistency (priority 4)
    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_id does not resolve")
    item = db.ticket_items.get(ticket_item_id)
    if item is None:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_item_id does not resolve")
    if item["ticket_id"] != ticket_id:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_item_id belongs to a different ticket")
    service_type = db.service_types.get(service_type_id)
    if service_type is None:
        raise ApiError("ERR_FK_NOT_FOUND", "service_type_id does not resolve")

    # catalog eligibility (priority 6): active + category match
    if not service_type.get("active", False):
        raise ApiError("ERR_INVALID_REQUEST", "ServiceType is retired")
    if service_type["item_category"] != item["item_category"]:
        raise ApiError("ERR_INVALID_REQUEST", "ServiceType category does not match item category")

    rec = {
        "id": db.new_id(),
        "ticket_id": ticket_id,
        "ticket_item_id": ticket_item_id,
        "service_type_id": service_type_id,
        "quoted_price_cents": service_type["base_price_cents"],
        "adjusted_price_cents": None,
        "status": "QUOTED",
    }
    db.stamp_create(rec)
    db.service_lines[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/service-lines", methods=["GET"])
def list_service_lines():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    limit, offset = parse_pagination()
    records = list(db.service_lines.values())
    for field in ("ticket_id", "ticket_item_id", "service_type_id"):
        val = request.args.get(field)
        if val is not None:
            records = [s for s in records if s.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/service-lines/<lid>", methods=["GET"])
def get_service_line(lid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = find_line(lid)
    return object_response(public(rec), 200)


@app.route("/service-lines/<lid>", methods=["PATCH"])
def patch_service_line(lid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    line = find_line(lid)
    body = get_json_body()
    ticket = db.repair_tickets.get(line["ticket_id"])

    # validate adjusted_price_cents shape if present
    set_adjusted = present(body, "adjusted_price_cents")
    if set_adjusted:
        adj = require_int(body, "adjusted_price_cents", minimum=0)

    set_status = present(body, "status")
    if set_status:
        status = body.get("status")
        if status != "COMPLETED":
            raise ApiError("ERR_INVALID_REQUEST", "status may only be set to COMPLETED")

    # Apply adjusted price (allowed while line QUOTED and ticket IN_REPAIR per §3.6)
    if set_adjusted:
        if line["status"] != "QUOTED":
            raise ApiError("ERR_INVALID_TICKET_STATE", "Service line not QUOTED")
        if ticket is None or ticket["repair_status"] != "IN_REPAIR":
            raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not IN_REPAIR")
        line["adjusted_price_cents"] = adj
        db.touch(line)
        db.touch(ticket)

    if set_status:
        svc.complete_line(line, ticket)

    return object_response(public(line), 200)


# ===========================================================================
# Estimate
# ===========================================================================
@app.route("/estimates", methods=["POST"])
def create_estimate():
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    authored_by_technician_id = require_str(body, "authored_by_technician_id")
    supersedes_estimate_id = None
    if present(body, "supersedes_estimate_id"):
        supersedes_estimate_id = require_str(body, "supersedes_estimate_id")

    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_id does not resolve")
    if authored_by_technician_id not in db.technicians:
        raise ApiError("ERR_FK_NOT_FOUND", "authored_by_technician_id does not resolve")
    if supersedes_estimate_id is not None:
        prior = db.estimates.get(supersedes_estimate_id)
        if prior is None:
            raise ApiError("ERR_FK_NOT_FOUND", "supersedes_estimate_id does not resolve")
        if prior["ticket_id"] != ticket_id:
            raise ApiError("ERR_FK_NOT_FOUND", "supersedes_estimate_id belongs to a different ticket")

    # revision_number
    if supersedes_estimate_id is not None:
        revision_number = db.estimates[supersedes_estimate_id]["revision_number"] + 1
    else:
        revision_number = 1

    rec = {
        "id": db.new_id(),
        "ticket_id": ticket_id,
        "supersedes_estimate_id": supersedes_estimate_id,
        "revision_number": revision_number,
        "authored_by_technician_id": authored_by_technician_id,
        "labor_subtotal_cents": 0,
        "parts_subtotal_cents": 0,
        "rush_surcharge_cents": 0,
        "estimate_total_cents": 0,
        "status": "DRAFT",
    }
    # compute provisional totals at draft time
    totals = calc.estimate_total(ticket_id, ticket["priority"], "PROVISIONAL")
    rec.update(totals)
    db.stamp_create(rec)
    db.estimates[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/estimates", methods=["GET"])
def list_estimates():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    limit, offset = parse_pagination()
    records = list(db.estimates.values())
    for field in ("ticket_id", "supersedes_estimate_id", "authored_by_technician_id"):
        val = request.args.get(field)
        if val is not None:
            records = [e for e in records if e.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = find_estimate(eid)
    return object_response(public(rec), 200)


@app.route("/estimates/<eid>/present", methods=["POST"])
def estimate_present(eid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    estimate = find_estimate(eid)
    body = get_json_body()
    ticket = db.repair_tickets.get(estimate["ticket_id"])
    # OCC check (priority 7) before state check (priority 8)
    check_occ(ticket, body)
    svc.present_estimate(estimate, ticket)
    return object_response(public(estimate), 200)


@app.route("/estimates/<eid>/approve", methods=["POST"])
def estimate_approve(eid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    estimate = find_estimate(eid)
    ticket = db.repair_tickets.get(estimate["ticket_id"])
    # owner check: acting customer must be ticket owner
    if ticket is None or user_id != ticket["customer_id"]:
        raise ApiError("ERR_NOT_TICKET_OWNER", "Acting customer is not the ticket owner")
    svc.approve_estimate(estimate, ticket)
    return object_response(public(estimate), 200)


@app.route("/estimates/<eid>/reject", methods=["POST"])
def estimate_reject(eid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    estimate = find_estimate(eid)
    ticket = db.repair_tickets.get(estimate["ticket_id"])
    if ticket is None or user_id != ticket["customer_id"]:
        raise ApiError("ERR_NOT_TICKET_OWNER", "Acting customer is not the ticket owner")
    svc.reject_estimate(estimate, ticket)
    return object_response(public(estimate), 200)


# ===========================================================================
# PartsOrder
# ===========================================================================
@app.route("/parts-orders", methods=["POST"])
def create_parts_order():
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    service_line_id = require_str(body, "service_line_id")
    part_name = require_str(body, "part_name")
    supplier_cost_cents = require_int(body, "supplier_cost_cents", minimum=0)
    quantity = 1
    if present(body, "quantity"):
        quantity = require_int(body, "quantity", minimum=1)
    lead_time_days = require_int(body, "lead_time_days", minimum=0)

    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_id does not resolve")
    line = db.service_lines.get(service_line_id)
    if line is None:
        raise ApiError("ERR_FK_NOT_FOUND", "service_line_id does not resolve")
    if line["ticket_id"] != ticket_id:
        raise ApiError("ERR_FK_NOT_FOUND", "service_line_id belongs to a different ticket")

    is_redo = svc.is_redo_ticket(ticket_id)
    marked_up = calc.parts_markup(supplier_cost_cents, quantity, is_redo)

    rec = {
        "id": db.new_id(),
        "ticket_id": ticket_id,
        "service_line_id": service_line_id,
        "part_name": part_name,
        "supplier_cost_cents": supplier_cost_cents,
        "quantity": quantity,
        "marked_up_cost_cents": marked_up,
        "lead_time_days": lead_time_days,
        "status": "REQUESTED",
    }
    db.stamp_create(rec)
    db.parts_orders[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/parts-orders", methods=["GET"])
def list_parts_orders():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    limit, offset = parse_pagination()
    records = list(db.parts_orders.values())
    for field in ("ticket_id", "service_line_id"):
        val = request.args.get(field)
        if val is not None:
            records = [p for p in records if p.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/parts-orders/<pid>", methods=["GET"])
def get_parts_order(pid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician"})
    rec = find_part(pid)
    return object_response(public(rec), 200)


@app.route("/parts-orders/<pid>/order", methods=["POST"])
def parts_order_order(pid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    part = find_part(pid)
    ticket = db.repair_tickets.get(part["ticket_id"])
    svc.order_part(part, ticket)
    return object_response(public(part), 200)


@app.route("/parts-orders/<pid>/receive", methods=["POST"])
def parts_order_receive(pid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    part = find_part(pid)
    ticket = db.repair_tickets.get(part["ticket_id"])
    svc.receive_part(part, ticket)
    return object_response(public(part), 200)


@app.route("/parts-orders/<pid>/cancel", methods=["POST"])
def parts_order_cancel(pid):
    _, role = get_auth()
    require_roles(role, {"RepairTechnician"})
    part = find_part(pid)
    ticket = db.repair_tickets.get(part["ticket_id"])
    svc.cancel_part(part, ticket)
    return object_response(public(part), 200)


# ===========================================================================
# Payment
# ===========================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk"})
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    amount_cents = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", PAYMENT_METHODS)

    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_id does not resolve")

    # OCC (priority 7)
    check_occ(ticket, body)

    rec = {
        "id": db.new_id(),
        "ticket_id": ticket_id,
        "amount_cents": amount_cents,
        "method": method,
        "state": "CAPTURED",
    }
    db.stamp_audit_create(rec)
    db.payments[rec["id"]] = rec

    svc.recompute_amount_paid(ticket)
    db.touch(ticket)
    return object_response(public(rec), 201)


@app.route("/payments", methods=["GET"])
def list_payments():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager"})
    limit, offset = parse_pagination()
    records = list(db.payments.values())
    ticket_id = request.args.get("ticket_id")
    if ticket_id is not None:
        records = [p for p in records if p["ticket_id"] == ticket_id]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager"})
    rec = db.payments.get(pid)
    if rec is None:
        raise ApiError("ERR_FK_NOT_FOUND", "Payment not found")
    return object_response(public(rec), 200)


@app.route("/payments/<pid>/refund", methods=["POST"])
def payment_refund(pid):
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    payment = db.payments.get(pid)
    if payment is None:
        raise ApiError("ERR_FK_NOT_FOUND", "Payment not found")
    ticket = db.repair_tickets.get(payment["ticket_id"])
    svc.refund_payment(payment, ticket)
    return object_response(public(payment), 200)


# ===========================================================================
# Notification
# ===========================================================================
@app.route("/notifications", methods=["GET"])
def list_notifications():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    limit, offset = parse_pagination()
    records = list(db.notifications.values())
    ticket_id = request.args.get("ticket_id")
    if ticket_id is not None:
        records = [n for n in records if n["ticket_id"] == ticket_id]
    kind = request.args.get("kind")
    if kind is not None:
        records = [n for n in records if n["kind"] == kind]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/notifications/<nid>", methods=["GET"])
def get_notification(nid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = db.notifications.get(nid)
    if rec is None:
        raise ApiError("ERR_FK_NOT_FOUND", "Notification not found")
    return object_response(public(rec), 200)


# ===========================================================================
# WarrantyClaim
# ===========================================================================
@app.route("/warranty-claims", methods=["POST"])
def create_warranty_claim():
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    service_line_id = require_str(body, "service_line_id")
    reported_by_customer_id = require_str(body, "reported_by_customer_id")
    defect_description = require_str(body, "defect_description")

    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_FK_NOT_FOUND", "ticket_id does not resolve")
    line = db.service_lines.get(service_line_id)
    if line is None:
        raise ApiError("ERR_FK_NOT_FOUND", "service_line_id does not resolve")
    if line["ticket_id"] != ticket_id:
        raise ApiError("ERR_FK_NOT_FOUND", "service_line_id belongs to a different ticket")
    if reported_by_customer_id not in db.customers:
        raise ApiError("ERR_FK_NOT_FOUND", "reported_by_customer_id does not resolve")
    # claimant must equal ticket.customer_id
    if reported_by_customer_id != ticket["customer_id"]:
        raise ApiError("ERR_FK_NOT_FOUND", "reported_by_customer_id is not the ticket owner")

    # warranty window (priority 10): ticket PICKED_UP and clock <= warranty_expires_at
    if ticket["repair_status"] != "PICKED_UP":
        raise ApiError("ERR_WARRANTY_EXPIRED", "Ticket not picked up")
    expires = ticket.get("warranty_expires_at")
    if expires is None or clock.now() > expires:
        raise ApiError("ERR_WARRANTY_EXPIRED", "Warranty has expired")

    rec = {
        "id": db.new_id(),
        "ticket_id": ticket_id,
        "service_line_id": service_line_id,
        "reported_by_customer_id": reported_by_customer_id,
        "defect_description": defect_description,
        "ruled_by_technician_id": None,
        "status": "FILED",
        "redo_ticket_id": None,
    }
    db.stamp_create(rec)
    db.warranty_claims[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/warranty-claims", methods=["GET"])
def list_warranty_claims():
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    limit, offset = parse_pagination()
    records = list(db.warranty_claims.values())
    for field in ("ticket_id", "service_line_id", "reported_by_customer_id",
                  "ruled_by_technician_id", "redo_ticket_id"):
        val = request.args.get(field)
        if val is not None:
            records = [c for c in records if c.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@app.route("/warranty-claims/<cid>", methods=["GET"])
def get_warranty_claim(cid):
    _, role = get_auth()
    require_roles(role, {"FrontDeskClerk", "ShopManager", "RepairTechnician", "Customer"})
    rec = find_claim(cid)
    return object_response(public(rec), 200)


@app.route("/warranty-claims/<cid>/approve", methods=["POST"])
def warranty_claim_approve(cid):
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    claim = find_claim(cid)
    body = get_json_body()
    ruled_by_technician_id = require_str(body, "ruled_by_technician_id")
    if ruled_by_technician_id not in db.technicians:
        raise ApiError("ERR_FK_NOT_FOUND", "ruled_by_technician_id does not resolve")
    svc.approve_claim(claim, ruled_by_technician_id)
    return object_response(public(claim), 200)


@app.route("/warranty-claims/<cid>/deny", methods=["POST"])
def warranty_claim_deny(cid):
    _, role = get_auth()
    require_roles(role, {"ShopManager"})
    claim = find_claim(cid)
    body = get_json_body()
    ruled_by_technician_id = require_str(body, "ruled_by_technician_id")
    if ruled_by_technician_id not in db.technicians:
        raise ApiError("ERR_FK_NOT_FOUND", "ruled_by_technician_id does not resolve")
    svc.deny_claim(claim, ruled_by_technician_id)
    return object_response(public(claim), 200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
