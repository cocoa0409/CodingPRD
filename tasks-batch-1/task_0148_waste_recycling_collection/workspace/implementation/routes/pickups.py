"""Pickup, WeightTicket, ContaminationTag endpoints (PRD §3.3, §3.4)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import calculations as calc
from services import serializers as ser
from services.common import check_enum, get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("pickups", __name__)

MISS_REASONS = {"BLOCKED_ACCESS", "NOT_OUT", "TRUCK_FULL", "MISSED_BY_CREW"}
CARRIER_FAULT = {"MISSED_BY_CREW", "TRUCK_FULL"}
SEVERITIES = {"MINOR", "MAJOR", "REJECT"}


# ----------------------------- Pickup create (under stop) -----------------------------

@bp.route("/stops/<stop_id>/pickups", methods=["POST"])
def create_pickup(stop_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    stop = db.stops.get(stop_id)
    if stop is None:
        raise err("ERR_NOT_FOUND", "Stop not found.")
    body = get_json_body()
    require_fields(body, ["cart_id"])
    cart = db.carts.get(body["cart_id"])
    if cart is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced cart does not exist.")
    # ERR_PICKUP_SLOT_TAKEN: one active (non-CANCELLED) pickup per cart per stop.
    taken = any(
        p["stop_id"] == stop_id
        and p["cart_id"] == body["cart_id"]
        and p["outcome"] != "CANCELLED"
        for p in db.pickups.values()
    )
    if taken:
        raise err("ERR_PICKUP_SLOT_TAKEN", "A non-cancelled pickup already covers this cart at this stop.")
    rec = base_record()
    rec.update(
        {
            "stop_id": stop_id,
            "cart_id": body["cart_id"],
            "outcome": "SCHEDULED",
            "miss_reason": None,
            "contaminated": False,
        }
    )
    db.pickups[rec["id"]] = rec
    return success(ser.pickup(rec), status=201)


@bp.route("/pickups/<pickup_id>", methods=["GET"])
def get_pickup(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    rec = db.pickups.get(pickup_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    return success(ser.pickup(rec), status=200)


@bp.route("/pickups", methods=["GET"])
def list_pickups():
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    parse_pagination()
    items = list(db.pickups.values())
    stop_id = request.args.get("stop_id")
    cart_id = request.args.get("cart_id")
    outcome = request.args.get("outcome")
    if stop_id is not None:
        items = [p for p in items if p["stop_id"] == stop_id]
    if cart_id is not None:
        items = [p for p in items if p["cart_id"] == cart_id]
    if outcome is not None:
        items = [p for p in items if p["outcome"] == outcome]
    page, pagination = paginate(items)
    return success([ser.pickup(p) for p in page], status=200, pagination=pagination)


@bp.route("/pickups/<pickup_id>/complete", methods=["POST"])
def complete_pickup(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Driver"})
    rec = db.pickups.get(pickup_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    body = get_json_body()
    require_fields(body, ["expected_cart_version"])
    stop = db.stops.get(rec["stop_id"])
    route = db.routes.get(stop["route_id"]) if stop else None
    cart = db.carts.get(rec["cart_id"])
    # State precondition (priority 8) before OCC (priority 9).
    if (
        rec["outcome"] != "SCHEDULED"
        or route is None
        or route["status"] != "IN_PROGRESS"
        or cart is None
        or cart["status"] not in ("ASSIGNED", "ACTIVE")
    ):
        raise err("ERR_INVALID_STATE", "Pickup cannot be completed from its current state.")
    # OCC on the cart's version.
    if body["expected_cart_version"] != cart["version"]:
        raise err("ERR_STALE_VERSION", "Cart version is stale.")

    rec["outcome"] = "COMPLETED"
    touch(rec)
    # Bubble-up: stop PENDING -> SERVICED
    if stop["status"] == "PENDING":
        stop["status"] = "SERVICED"
        touch(stop)
    # Cart version increments so the next read reflects the empty.
    touch(cart)
    return success(ser.pickup(rec), status=200)


@bp.route("/pickups/<pickup_id>/miss", methods=["POST"])
def miss_pickup(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Driver"})
    rec = db.pickups.get(pickup_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    body = get_json_body()
    require_fields(body, ["miss_reason"])
    check_enum(body["miss_reason"], MISS_REASONS, "miss_reason")
    stop = db.stops.get(rec["stop_id"])
    route = db.routes.get(stop["route_id"]) if stop else None
    if (
        rec["outcome"] != "SCHEDULED"
        or route is None
        or route["status"] != "IN_PROGRESS"
    ):
        raise err("ERR_INVALID_STATE", "Pickup cannot be missed from its current state.")

    rec["outcome"] = "MISSED"
    rec["miss_reason"] = body["miss_reason"]
    touch(rec)
    # Bubble-up: stop PENDING -> SKIPPED
    if stop["status"] == "PENDING":
        stop["status"] = "SKIPPED"
        touch(stop)
    # Conditional cascade: carrier-fault reasons auto-create a PENDING credit.
    if body["miss_reason"] in CARRIER_FAULT:
        cart = db.carts.get(rec["cart_id"])
        account_id = cart["account_id"] if cart else None
        credit = base_record()
        credit.update(
            {
                "account_id": account_id,
                "source_type": "PICKUP",
                "source_pickup_id": rec["id"],
                "source_special_pickup_id": None,
                "amount_cents": calc.missed_credit_amount_cents("PICKUP"),
                "status": "PENDING",
                "applied_invoice_id": None,
            }
        )
        db.credits[credit["id"]] = credit
    return success(ser.pickup(rec), status=200)


@bp.route("/pickups/<pickup_id>/cancel", methods=["POST"])
def cancel_pickup(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.pickups.get(pickup_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    stop = db.stops.get(rec["stop_id"])
    route = db.routes.get(stop["route_id"]) if stop else None
    if (
        rec["outcome"] != "SCHEDULED"
        or route is None
        or route["status"] not in ("PLANNED", "DISPATCHED")
    ):
        raise err("ERR_INVALID_STATE", "Pickup cannot be cancelled from its current state.")
    rec["outcome"] = "CANCELLED"
    touch(rec)
    return success(ser.pickup(rec), status=200)


# ----------------------------- WeightTicket -----------------------------

@bp.route("/pickups/<pickup_id>/weight-ticket", methods=["POST"])
def create_weight_ticket(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Driver"})
    pickup = db.pickups.get(pickup_id)
    if pickup is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    body = get_json_body()
    require_fields(body, ["gross_weight_lbs", "diverted"])
    gross = body["gross_weight_lbs"]
    if not isinstance(gross, (int, float)) or isinstance(gross, bool):
        raise err("ERR_INVALID_REQUEST", "gross_weight_lbs must be a number.")
    diverted = body["diverted"]
    if not isinstance(diverted, bool):
        raise err("ERR_INVALID_REQUEST", "diverted must be a boolean.")
    # Negative gross reading -> ERR_VALIDATION (422).
    if gross < 0:
        raise err("ERR_VALIDATION", "gross_weight_lbs must be >= 0.")
    # State / business rule: only a COMPLETED pickup, at most one ticket.
    if pickup["outcome"] != "COMPLETED":
        raise err("ERR_WEIGHT_TICKET_NOT_ALLOWED", "Weight ticket allowed only on a COMPLETED pickup.")
    existing = any(wt["pickup_id"] == pickup_id for wt in db.weight_tickets.values())
    if existing:
        raise err("ERR_WEIGHT_TICKET_NOT_ALLOWED", "Pickup already has a weight ticket.")

    cart = db.carts.get(pickup["cart_id"])
    tare = cart["tare_weight_lbs"] if cart else 0
    net = calc.net_weight_lbs(gross, tare)

    rec = base_record(common_fields=False)
    rec.update(
        {
            "pickup_id": pickup_id,
            "gross_weight_lbs": gross,
            "net_weight_lbs": net,
            "diverted": diverted,
        }
    )
    db.weight_tickets[rec["id"]] = rec
    # Route total_net_weight_lbs is derived (recomputed at read), no stored bump.
    return success(ser.weight_ticket(rec), status=201)


@bp.route("/pickups/<pickup_id>/weight-ticket", methods=["GET"])
def list_weight_tickets(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    pickup = db.pickups.get(pickup_id)
    if pickup is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    parse_pagination()
    items = [wt for wt in db.weight_tickets.values() if wt["pickup_id"] == pickup_id]
    page, pagination = paginate(items)
    return success([ser.weight_ticket(wt) for wt in page], status=200, pagination=pagination)


# ----------------------------- ContaminationTag -----------------------------

@bp.route("/pickups/<pickup_id>/contamination-tags", methods=["POST"])
def create_tag(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Driver", "Dispatcher"})
    pickup = db.pickups.get(pickup_id)
    if pickup is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    body = get_json_body()
    require_fields(body, ["severity"])
    check_enum(body["severity"], SEVERITIES, "severity")
    rec = base_record()
    rec.update(
        {
            "pickup_id": pickup_id,
            "severity": body["severity"],
            "status": "OPEN",
            "note": body.get("note"),
        }
    )
    db.contamination_tags[rec["id"]] = rec
    # Reconcile: pickup.contaminated = true (an OPEN tag now exists).
    if not pickup["contaminated"]:
        pickup["contaminated"] = True
        touch(pickup)
    return success(ser.contamination_tag(rec), status=201)


@bp.route("/pickups/<pickup_id>/contamination-tags", methods=["GET"])
def list_tags(pickup_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    pickup = db.pickups.get(pickup_id)
    if pickup is None:
        raise err("ERR_NOT_FOUND", "Pickup not found.")
    parse_pagination()
    items = [t for t in db.contamination_tags.values() if t["pickup_id"] == pickup_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pagination = paginate(items)
    return success([ser.contamination_tag(t) for t in page], status=200, pagination=pagination)


@bp.route("/contamination-tags/<tag_id>", methods=["GET"])
def get_tag(tag_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Driver", "Billing"})
    rec = db.contamination_tags.get(tag_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Contamination tag not found.")
    return success(ser.contamination_tag(rec), status=200)


@bp.route("/contamination-tags/<tag_id>/clear", methods=["POST"])
def clear_tag(tag_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.contamination_tags.get(tag_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Contamination tag not found.")
    if rec["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only an OPEN tag can be cleared.")
    rec["status"] = "CLEARED"
    touch(rec)
    # Reconcile: pickup.contaminated -> false only if no other OPEN tag remains.
    pickup = db.pickups.get(rec["pickup_id"])
    if pickup is not None:
        any_open = any(
            t["pickup_id"] == pickup["id"] and t["status"] == "OPEN"
            for t in db.contamination_tags.values()
        )
        if not any_open and pickup["contaminated"]:
            pickup["contaminated"] = False
            touch(pickup)
    return success(ser.contamination_tag(rec), status=200)
