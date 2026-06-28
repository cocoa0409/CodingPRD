"""Return inspection, damage line item & settlement routes (PRD §3.11)."""
from flask import Blueprint, request

import errors
from db import db, stamp_create, touch
from middleware import get_identity, require_roles, parse_pagination
from response import object_response, array_response
from services import calc, serialize, common
from services import invoices as inv_svc

bp = Blueprint("returns", __name__)

SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}


@bp.route("/return-inspections", methods=["POST"])
def open_inspection():
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.11)
    body = common.get_body()
    subscription_id = common.require_str(body, "subscription_id")
    vehicle_id = common.require_str(body, "vehicle_id")
    reported = common.require_int(body, "reported_odometer_miles", min_value=0)
    common.resolve(db.subscriptions, subscription_id)
    vehicle = common.resolve(db.vehicles, vehicle_id)

    rec = {
        "subscription_id": subscription_id,
        "vehicle_id": vehicle_id,
        "status": "OPEN",
        "reported_odometer_miles": reported,
        "total_damage_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
        "balance_due_cents": 0,
    }
    stamp_create(rec)
    db.return_inspections[rec["id"]] = rec

    # If vehicle still ASSIGNED, move ASSIGNED->IN_INSPECTION (PRD §3.11).
    if vehicle["status"] == "ASSIGNED":
        vehicle["status"] = "IN_INSPECTION"
        touch(vehicle)
        common.recompute_fleet(vehicle["fleet_id"])
    return object_response(serialize.serialize_return_inspection(rec), 201)


@bp.route("/return-inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.return_inspections, rid)
    return object_response(serialize.serialize_return_inspection(rec))


@bp.route("/return-inspections", methods=["GET"])
def list_inspections():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    records = list(db.return_inspections.values())
    records = common.filter_equals(records, "subscription_id", request.args.get("subscription_id"))
    records = common.filter_equals(records, "vehicle_id", request.args.get("vehicle_id"))
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_return_inspection(r) for r in page], limit, offset, total)


@bp.route("/return-inspections/<rid>/damage-line-items", methods=["POST"])
def add_damage(rid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.11)
    inspection = common.resolve(db.return_inspections, rid)
    body = common.get_body()
    severity = common.require_enum(body, "severity", SEVERITIES)
    amount = common.require_int(body, "amount_cents", min_value=1)
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise errors.invalid_request("note must be a string.")

    # damage recorded while inspection OPEN (PRD §3.11).
    if inspection["status"] != "OPEN":
        raise errors.invalid_state("Inspection must be OPEN to add damage line items.")

    rec = {
        "inspection_id": rid,
        "severity": severity,
        "amount_cents": amount,
        "note": note,
    }
    stamp_create(rec)
    db.damage_line_items[rec["id"]] = rec
    return object_response(serialize.serialize_damage_line_item(rec), 201)


@bp.route("/return-inspections/<rid>/damage-line-items", methods=["GET"])
def list_damage(rid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    common.resolve(db.return_inspections, rid)
    limit, offset = parse_pagination()
    records = [d for d in db.damage_line_items.values() if d["inspection_id"] == rid]
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_damage_line_item(r) for r in page], limit, offset, total)


@bp.route("/return-inspections/<rid>/assess", methods=["POST"])
def assess(rid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.11)
    inspection = common.resolve(db.return_inspections, rid)
    if inspection["status"] != "OPEN":
        raise errors.invalid_state("Inspection must be OPEN to assess.")
    total = sum(d["amount_cents"] for d in db.damage_line_items.values()
                if d["inspection_id"] == rid)
    inspection["total_damage_cents"] = total
    inspection["status"] = "ASSESSED"
    touch(inspection)
    return object_response(serialize.serialize_return_inspection(inspection))


@bp.route("/return-inspections/<rid>/settle", methods=["POST"])
def settle(rid):
    _, role = get_identity()
    require_roles(role, {"BillingAdmin"})  # exclusive (PRD §3.11)
    inspection = common.resolve(db.return_inspections, rid)
    if inspection["status"] != "ASSESSED":
        raise errors.invalid_state("Inspection must be ASSESSED to settle.")
    sub = db.subscriptions[inspection["subscription_id"]]
    vehicle = db.vehicles[inspection["vehicle_id"]]

    # settle requires RETURN_PENDING, OR the early-cancel path: active_vehicle is this
    # vehicle and the vehicle is IN_INSPECTION (PRD §3.11).
    ok = (sub["lifecycle_status"] == "RETURN_PENDING") or (
        sub["active_vehicle_id"] == vehicle["id"] and vehicle["status"] == "IN_INSPECTION"
    )
    if not ok:
        raise errors.invalid_state("Subscription not in a settleable return state.")

    # deposit waterfall (PRD §3.11).
    unpaid_cycle = inv_svc.unpaid_sum(sub["id"], "CYCLE")
    unpaid_early = inv_svc.unpaid_sum(sub["id"], "EARLY_CANCEL")
    applied, refunded, balance_due = calc.deposit_waterfall(
        inspection["total_damage_cents"], unpaid_cycle, unpaid_early, sub["deposit_held_cents"]
    )
    inspection["deposit_applied_cents"] = applied
    inspection["deposit_refunded_cents"] = refunded
    inspection["balance_due_cents"] = balance_due
    inspection["status"] = "SETTLED"
    touch(inspection)

    # RETURN_SETTLEMENT invoice amount = balance_due (PRD §3.11).
    inv_svc.post_invoice(sub["id"], "RETURN_SETTLEMENT", inspection["id"], balance_due)

    # release vehicle (PRD §3.11).
    if vehicle["status"] == "IN_INSPECTION":
        vehicle["status"] = "AVAILABLE"
        vehicle["active_subscription_id"] = None
        touch(vehicle)
        common.recompute_fleet(vehicle["fleet_id"])

    # subscription cascade.
    was_return_pending = sub["lifecycle_status"] == "RETURN_PENDING"
    sub["active_vehicle_id"] = None
    if was_return_pending:
        sub["lifecycle_status"] = "CLOSED"
    touch(sub)
    return object_response(serialize.serialize_return_inspection(inspection))
