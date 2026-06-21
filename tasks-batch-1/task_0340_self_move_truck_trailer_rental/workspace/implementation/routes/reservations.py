"""Reservation endpoints: create, fetch, list, supplies, add-ons, confirm,
cancel, dispatch."""
from flask import Blueprint, request

import db
import lookup
import validate as V
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public, public_list
from services import calc, domain

bp = Blueprint("reservations", __name__)

ALL_ROLES = {"FleetManager", "LocationAgent", "Customer"}
CUST_LA = {"Customer", "LocationAgent"}


def _ownership_check(role, user_id, reservation):
    """Customer may only act on / read a reservation they own (PRD §2.1)."""
    if role == "Customer" and reservation["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Reservation does not belong to this customer.")


# ============================ create ============================
@bp.route("/rental/reservations", methods=["POST"])
def create_reservation():
    user_id, role = authenticate()
    require_role(role, CUST_LA)
    body = V.get_json()

    # Existence of body FKs (priority 4) — validated before structural body
    # checks per PRD §2.11 (existence comes before request validation).
    V.require_fields(body, ["customer_id", "equipment_class_id", "pickup_location_id",
                            "dropoff_location_id", "scheduled_pickup_at", "scheduled_return_at"])
    customer = lookup.require_customer(body["customer_id"])
    klass = lookup.require_class(body["equipment_class_id"])
    pickup_loc = lookup.require_location(body["pickup_location_id"])
    dropoff_loc = lookup.require_location(body["dropoff_location_id"])
    coverage_plan = None
    coverage_plan_id = body.get("coverage_plan_id")
    if coverage_plan_id is not None:
        coverage_plan = lookup.require_coverage(coverage_plan_id)

    # Customer ownership: a Customer can only create a reservation for itself.
    if role == "Customer" and body["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer may only create their own reservations.")

    # Structural validation (priority 5).
    pickup_dt = V.parse_datetime(body, "scheduled_pickup_at")
    return_dt = V.parse_datetime(body, "scheduled_return_at")
    coverage_choice = V.optional_enum(body, "coverage_choice",
                                      {"SELECTED", "DECLINED"}, "DECLINED")

    # Time range (priority 6).
    if not (return_dt > pickup_dt):
        raise err("ERR_INVALID_TIME_RANGE", "scheduled_return_at must be after scheduled_pickup_at.")

    # Coverage consistency (priority 7).
    if coverage_choice == "SELECTED":
        if coverage_plan_id is None:
            raise err("ERR_COVERAGE_MISMATCH", "SELECTED coverage requires a coverage_plan_id.")
        if not coverage_plan["active"]:
            raise err("ERR_COVERAGE_MISMATCH", "Coverage plan is not active.")
    else:  # DECLINED
        if coverage_plan_id is not None:
            raise err("ERR_COVERAGE_MISMATCH", "DECLINED coverage must not carry a coverage_plan_id.")

    # Derive trip_type.
    trip_type = "ROUND_TRIP" if body["pickup_location_id"] == body["dropoff_location_id"] else "ONE_WAY"

    # One-way drop-off (priority 8).
    if trip_type == "ONE_WAY":
        if not dropoff_loc["accepts_one_way_dropoff"]:
            raise err("ERR_ONE_WAY_DROPOFF_NOT_ALLOWED",
                      "Drop-off location does not accept one-way drop-offs.")

    planned_days = calc.ceil_days(pickup_dt, return_dt)

    row = db.make_common(db.reservations)
    row.update({
        "customer_id": body["customer_id"],
        "equipment_class_id": body["equipment_class_id"],
        "pickup_location_id": body["pickup_location_id"],
        "dropoff_location_id": body["dropoff_location_id"],
        "coverage_plan_id": coverage_plan_id,
        "trip_type": trip_type,
        "coverage_choice": coverage_choice,
        "scheduled_pickup_at": body["scheduled_pickup_at"],
        "scheduled_return_at": body["scheduled_return_at"],
        "planned_days": planned_days,
        "booking_status": "PENDING",
        "fulfillment_status": "AWAITING_DISPATCH",
        "assigned_equipment_id": None,
        "quoted_total_cents": 0,
    })
    domain.rerun_quote(row)
    db.reservations.put(row)
    return success(public(row), status=201)


@bp.route("/rental/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)
    return success(public(res))


@bp.route("/rental/reservations", methods=["GET"])
def list_reservations():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = V.parse_pagination()
    rows = db.reservations.all()
    # Customers only see their own reservations.
    if role == "Customer":
        rows = [r for r in rows if r["customer_id"] == user_id]
    for field in ("customer_id", "pickup_location_id", "dropoff_location_id",
                  "equipment_class_id", "coverage_plan_id", "assigned_equipment_id",
                  "booking_status", "fulfillment_status"):
        val = request.args.get(field)
        if val:
            rows = [r for r in rows if r.get(field) == val]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ supplies ============================
@bp.route("/rental/reservations/<rid>/supplies", methods=["POST"])
def add_supply_line(rid):
    user_id, role = authenticate()
    require_role(role, CUST_LA)
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)
    body = V.get_json()
    V.require_fields(body, ["supply_id", "quantity"])
    supply = lookup.require_supply(body["supply_id"])
    quantity = V.require_int(body, "quantity", minimum=1)

    # State lock (priority 14).
    if res["booking_status"] != "PENDING":
        raise err("ERR_RESERVATION_LOCKED", "Reservation is no longer PENDING.")

    # Stock (priority 13).
    if quantity > supply["stock_qty"]:
        raise err("ERR_INSUFFICIENT_STOCK", "Requested quantity exceeds stock.")

    line = db.make_common(db.supply_lines)
    line.update({
        "reservation_id": rid,
        "supply_id": supply["id"],
        "quantity": quantity,
        "unit_price_cents": supply["unit_price_cents"],
        "refunded_units": 0,
    })
    supply["stock_qty"] -= quantity
    db.touch(supply)
    db.supply_lines.put(line)
    domain.rerun_quote(res)
    db.touch(res)
    return success(public(line), status=201)


@bp.route("/rental/reservations/<rid>/supplies/<line_id>", methods=["DELETE"])
def remove_supply_line(rid, line_id):
    user_id, role = authenticate()
    require_role(role, CUST_LA)
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)
    line = db.supply_lines.get(line_id)
    if line is None or line["reservation_id"] != rid:
        raise err("ERR_NOT_FOUND", "Supply line not found on this reservation.")

    if res["booking_status"] != "PENDING":
        raise err("ERR_RESERVATION_LOCKED", "Reservation is no longer PENDING.")

    supply = db.supplies.get(line["supply_id"])
    if supply is not None:
        supply["stock_qty"] += line["quantity"]
        db.touch(supply)
    db.supply_lines.delete(line_id)
    domain.rerun_quote(res)
    db.touch(res)
    return success(public(line))


@bp.route("/rental/reservations/<rid>/supplies", methods=["GET"])
def list_supply_lines(rid):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)
    limit, offset = V.parse_pagination()
    rows = domain.supply_lines_for(rid)
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ add-ons ============================
@bp.route("/rental/reservations/<rid>/addons", methods=["POST"])
def add_addon(rid):
    user_id, role = authenticate()
    require_role(role, CUST_LA)
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)
    body = V.get_json()
    V.require_fields(body, ["addon_type", "quantity"])
    addon_type = V.require_enum(body, "addon_type",
                                {"UTILITY_DOLLY", "APPLIANCE_DOLLY", "FURNITURE_PAD_DOZEN"})
    quantity = V.require_int(body, "quantity", minimum=1)

    if res["booking_status"] != "PENDING":
        raise err("ERR_RESERVATION_LOCKED", "Reservation is no longer PENDING.")

    row = db.make_common(db.addons)
    row.update({
        "reservation_id": rid,
        "addon_type": addon_type,
        "quantity": quantity,
        "daily_rate_cents": calc.ADDON_RATES[addon_type],
    })
    db.addons.put(row)
    domain.rerun_quote(res)
    db.touch(res)
    return success(public(row), status=201)


@bp.route("/rental/reservations/<rid>/addons", methods=["GET"])
def list_addons(rid):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)
    limit, offset = V.parse_pagination()
    rows = domain.addons_for(rid)
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


# ============================ confirm ============================
@bp.route("/rental/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)

    # State (priority 9).
    if res["booking_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Reservation must be PENDING to confirm.")

    klass = db.equipment_classes.get(res["equipment_class_id"])

    # Coverage required (priority 11).
    if klass["requires_coverage"] and res["coverage_choice"] != "SELECTED":
        raise err("ERR_COVERAGE_REQUIRED", "This class requires coverage.")

    # Round-trip double-booking gate (priority 18).
    earmark_unit = None
    if res["trip_type"] == "ROUND_TRIP":
        stationed = domain.stationed_units_for_confirm(res)
        if stationed:
            # At least one stationed unit must have no colliding CONFIRMED window.
            any_free = any(
                not domain.equipment_window_collides(eq["id"], res,
                                                     exclude_reservation_id=res["id"])
                for eq in stationed
            )
            if not any_free:
                raise err("ERR_EQUIPMENT_DOUBLE_BOOKED",
                          "Every stationed unit collides with a confirmed reservation.")
        # Earmark an AVAILABLE non-colliding unit (may be None -> un-earmarked).
        earmark_unit = domain.pick_earmark_unit(res)

    # Commit.
    res["booking_status"] = "CONFIRMED"
    domain.rerun_quote(res)
    if earmark_unit is not None:
        earmark_unit["status"] = "RESERVED"
        db.touch(earmark_unit)
        res["assigned_equipment_id"] = earmark_unit["id"]
        domain.recompute_on_lot_count(earmark_unit["current_location_id"])
    db.touch(res)
    return success(public(res))


# ============================ cancel ============================
@bp.route("/rental/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    res = lookup.require_reservation(rid)
    _ownership_check(role, user_id, res)

    if res["booking_status"] not in ("PENDING", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Reservation cannot be cancelled in its current state.")
    if res["fulfillment_status"] != "AWAITING_DISPATCH":
        raise err("ERR_INVALID_STATE", "Reservation cannot be cancelled after dispatch.")

    # Restore supply stock (cascade).
    for line in domain.supply_lines_for(rid):
        supply = db.supplies.get(line["supply_id"])
        if supply is not None:
            supply["stock_qty"] += line["quantity"]
            db.touch(supply)

    # Release earmarked equipment (cascade).
    if res.get("assigned_equipment_id"):
        eq = db.equipment.get(res["assigned_equipment_id"])
        if eq is not None and eq["status"] == "RESERVED":
            eq["status"] = "AVAILABLE"
            db.touch(eq)
            domain.recompute_on_lot_count(eq["current_location_id"])
        res["assigned_equipment_id"] = None

    res["booking_status"] = "CANCELLED"
    db.touch(res)
    return success(public(res))


# ============================ dispatch ============================
@bp.route("/rental/reservations/<rid>/dispatch", methods=["POST"])
def dispatch_reservation(rid):
    user_id, role = authenticate()
    require_role(role, {"LocationAgent"})
    res = lookup.require_reservation(rid)
    body = V.get_json()
    V.require_fields(body, ["expected_reservation_version"])
    expected_version = V.require_int(body, "expected_reservation_version")

    # State (priority 9): fulfillment must be AWAITING_DISPATCH and booking CONFIRMED.
    if res["booking_status"] != "CONFIRMED" or res["fulfillment_status"] != "AWAITING_DISPATCH":
        raise err("ERR_INVALID_STATE", "Reservation is not in a dispatchable state.")

    klass = db.equipment_classes.get(res["equipment_class_id"])
    customer = db.customers.get(res["customer_id"])

    # License (priority 10).
    if klass["category"] == "TRUCK" and not customer["license_verified"]:
        raise err("ERR_LICENSE_NOT_VERIFIED", "Customer license is not verified.")

    # Coverage required (priority 11).
    if klass["requires_coverage"] and res["coverage_choice"] != "SELECTED":
        raise err("ERR_COVERAGE_REQUIRED", "This class requires coverage.")

    # Pickup location OPEN (part of dispatch preconditions).
    pickup_loc = db.locations.get(res["pickup_location_id"])
    if pickup_loc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Pickup location is not OPEN.")

    # Selector (priority 15).
    chosen = None
    if res["trip_type"] == "ROUND_TRIP" and res.get("assigned_equipment_id"):
        eq = db.equipment.get(res["assigned_equipment_id"])
        if eq is not None and eq["status"] == "RESERVED":
            chosen = eq
    if chosen is None:
        candidates = domain.dispatch_candidates(res)
        if not candidates:
            raise err("ERR_NO_EQUIPMENT_AVAILABLE", "No equipment available to dispatch.")
        chosen = domain.rank_candidates(candidates, res)[0]

    # OCC (priority 20) — last gate.
    if expected_version != res["version"]:
        raise err("ERR_STALE_VERSION", "Reservation version is stale.")

    # Commit dispatch.
    prior_loc = chosen["current_location_id"]
    chosen["status"] = "IN_TRANSIT"  # DISPATCHED -> IN_TRANSIT (immediate follow-on)
    chosen["current_location_id"] = None
    db.touch(chosen)
    if prior_loc:
        domain.recompute_on_lot_count(prior_loc)

    res["assigned_equipment_id"] = chosen["id"]
    res["fulfillment_status"] = "DISPATCHED"
    db.touch(res)

    contract = db.make_common(db.contracts)
    contract.update({
        "reservation_id": rid,
        "equipment_id": chosen["id"],
        "pickup_odometer_miles": chosen["odometer_miles"],
        "pickup_fuel_eighths": chosen["fuel_level_eighths"],
        "return_odometer_miles": None,
        "return_fuel_eighths": None,
        "miles_driven": None,
        "actual_return_at": None,
        "status": "ACTIVE",
        "settlement_total_cents": None,
        "damage_charge_cents": 0,
    })
    db.contracts.put(contract)
    return success(public(contract), status=201)
