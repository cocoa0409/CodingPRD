"""Auto Repair Shop Management API — Flask entry point.

In-memory only. Store starts empty on every boot; nothing is seeded. Every
behavior traces to a PRD sentence (citations inline).
"""
import os
from decimal import Decimal

from flask import Flask, request

import db
import clock
from calculations import (
    labor_charge_cents,
    parts_extended_charge_cents,
    recompute_efficiency,
    recompute_repair_order_total,
)
from errors import ApiError
from helpers import (
    get_json_body,
    must_get,
    obj,
    opt_bool,
    opt_enum,
    opt_int,
    opt_number,
    opt_string,
    paginated_list,
    require_enum,
    require_fields,
    require_int,
    require_string,
)
from middleware import get_user_context, require_role
from response import error_response, object_response
from serializers import ser
import services

app = Flask(__name__)
app.url_map.strict_slashes = False


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 400)


# --------------------------------------------------------------------------- #
# Auth gate: runs before every route except the JSON-error handlers.
# PRD 2.6 priority 1: headers validated first on every request.
# --------------------------------------------------------------------------- #
@app.before_request
def _auth_gate():
    # The store-keeping endpoints all require headers too; there are no public
    # routes in this API. get_user_context raises on missing/malformed headers.
    request.user_id, request.user_role = get_user_context()


def role():
    return request.user_role


def uid():
    return request.user_id


# =========================================================================== #
# Customer
# =========================================================================== #
@app.route("/customers", methods=["POST"])
def create_customer():
    require_role(role(), ["ServiceAdvisor", "ShopManager"])
    body = get_json_body()
    require_fields(body, ["full_name", "phone", "email"])
    c = db.common_fields()
    c.update({
        "full_name": require_string(body, "full_name"),
        "phone": require_string(body, "phone"),
        "email": require_string(body, "email"),
    })
    db.customers[c["id"]] = c
    return obj(c, ser, 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    c = must_get(db.customers, cid)
    return obj(c, ser)


@app.route("/customers/<cid>/vehicles", methods=["GET"])
def list_customer_vehicles(cid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    must_get(db.customers, cid)
    items = [v for v in db.vehicles.values() if v["customer_id"] == cid]
    return paginated_list(items, ser)


# =========================================================================== #
# Vehicle
# =========================================================================== #
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    require_role(role(), ["ServiceAdvisor", "ShopManager"])
    body = get_json_body()
    require_fields(body, ["customer_id", "vin", "make", "model", "model_year",
                          "odometer_miles"])
    customer_id = require_string(body, "customer_id")
    # Body FK existence (PRD 2.5) -> ERR_REFERENCED_ENTITY_NOT_FOUND
    if customer_id not in db.customers:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer_id does not exist.")
    vin = require_string(body, "vin")
    make = require_string(body, "make")
    model = require_string(body, "model")
    model_year = require_int(body, "model_year")
    odometer = require_int(body, "odometer_miles")
    if odometer < 0:
        raise ApiError("ERR_INVALID_REQUEST", "odometer_miles must be >= 0.")
    # VIN unique across all vehicles (PRD 3.1) -> ERR_DUPLICATE_VIN
    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", "A vehicle with this VIN already exists.")
    v = db.common_fields()
    v.update({
        "customer_id": customer_id,
        "vin": vin,
        "make": make,
        "model": model,
        "model_year": model_year,
        "odometer_miles": odometer,
    })
    db.vehicles[v["id"]] = v
    return obj(v, ser, 201)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    v = must_get(db.vehicles, vid)
    return obj(v, ser)


# =========================================================================== #
# Technician
# =========================================================================== #
@app.route("/technicians", methods=["POST"])
def create_technician():
    require_role(role(), ["ShopManager"])
    body = get_json_body()
    require_fields(body, ["full_name"])
    full_name = require_string(body, "full_name")
    skill_level = opt_enum(body, "skill_level", {"A", "B", "C"}, "B")
    t = db.common_fields()
    t.update({
        "full_name": full_name,
        "skill_level": skill_level,
        "clocked_labor_line_id": None,
        "last_clock_out_at": None,
        "banked_flat_hours": 0,
        "banked_actual_hours": 0,
        "efficiency_pct": None,
    })
    db.technicians[t["id"]] = t
    return obj(t, ser, 201)


@app.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician"])
    t = must_get(db.technicians, tid)
    # Fetching a technician recomputes & returns efficiency_pct (PRD 3.7).
    recompute_efficiency(t)
    return obj(t, ser)


# =========================================================================== #
# ServiceBay
# =========================================================================== #
@app.route("/service-bays", methods=["POST"])
def create_service_bay():
    require_role(role(), ["ShopManager"])
    body = get_json_body()
    require_fields(body, ["bay_name"])
    bay_name = require_string(body, "bay_name")
    bay_type = opt_enum(body, "bay_type", {"GENERAL", "ALIGNMENT", "LIFT"}, "GENERAL")
    # Duplicate bay_name -> ERR_INVALID_REQUEST (PRD 3.1)
    for b in db.service_bays.values():
        if b["bay_name"] == bay_name:
            raise ApiError("ERR_INVALID_REQUEST", "bay_name must be unique.")
    b = db.common_fields()
    b.update({"bay_name": bay_name, "bay_type": bay_type})
    db.service_bays[b["id"]] = b
    return obj(b, ser, 201)


# =========================================================================== #
# LaborOperation
# =========================================================================== #
@app.route("/labor-operations", methods=["POST"])
def create_labor_operation():
    require_role(role(), ["ShopManager", "ServiceAdvisor"])
    body = get_json_body()
    require_fields(body, ["op_code", "description", "book_hours", "default_rate_cents"])
    op_code = require_string(body, "op_code")
    description = require_string(body, "description")
    # book_hours > 0, default_rate_cents > 0 (PRD 3.1)
    bh = body.get("book_hours")
    if isinstance(bh, bool) or not isinstance(bh, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "book_hours must be a number.")
    if bh <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "book_hours must be > 0.")
    drc = body.get("default_rate_cents")
    if isinstance(drc, bool) or not isinstance(drc, int):
        raise ApiError("ERR_INVALID_REQUEST", "default_rate_cents must be an integer.")
    if drc <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "default_rate_cents must be > 0.")
    # Duplicate op_code -> ERR_INVALID_REQUEST (PRD 3.1)
    for o in db.labor_operations.values():
        if o["op_code"] == op_code:
            raise ApiError("ERR_INVALID_REQUEST", "op_code must be unique.")
    o = db.common_fields()
    o.update({
        "op_code": op_code,
        "description": description,
        "book_hours": bh,
        "default_rate_cents": drc,
    })
    db.labor_operations[o["id"]] = o
    return obj(o, ser, 201)


# =========================================================================== #
# MarkupTier
# =========================================================================== #
@app.route("/markup-tiers", methods=["POST"])
def create_markup_tier():
    require_role(role(), ["PartsManager", "ShopManager"])
    body = get_json_body()
    require_fields(body, ["tier_index", "lower_bound_cents", "markup_pct"])
    tier_index = require_int(body, "tier_index")
    if tier_index < 0:
        raise ApiError("ERR_INVALID_REQUEST", "tier_index must be >= 0.")
    lower = require_int(body, "lower_bound_cents")
    if lower < 0:
        raise ApiError("ERR_INVALID_REQUEST", "lower_bound_cents must be >= 0.")
    upper = opt_int(body, "upper_bound_cents", None)
    if upper is not None and upper <= lower:
        raise ApiError("ERR_INVALID_REQUEST", "upper_bound_cents must be > lower_bound_cents.")
    markup_pct = opt_number(body, "markup_pct", None)
    if markup_pct is None:
        raise ApiError("ERR_INVALID_REQUEST", "markup_pct is required.")
    if markup_pct < 0:
        raise ApiError("ERR_INVALID_REQUEST", "markup_pct must be >= 0.")

    # Duplicate tier_index or overlapping band -> ERR_INVALID_REQUEST (PRD 3.1)
    for t in db.markup_tiers.values():
        if t["tier_index"] == tier_index:
            raise ApiError("ERR_INVALID_REQUEST", "tier_index must be unique.")
        if _bands_overlap(lower, upper, t["lower_bound_cents"], t["upper_bound_cents"]):
            raise ApiError("ERR_INVALID_REQUEST", "markup tier band overlaps an existing tier.")

    t = db.common_fields()
    t.update({
        "tier_index": tier_index,
        "lower_bound_cents": lower,
        "upper_bound_cents": upper,
        "markup_pct": markup_pct,
    })
    db.markup_tiers[t["id"]] = t
    return obj(t, ser, 201)


def _bands_overlap(lo1, hi1, lo2, hi2):
    # half-open [lo, hi); null hi == +inf
    a_hi = float("inf") if hi1 is None else hi1
    b_hi = float("inf") if hi2 is None else hi2
    return lo1 < b_hi and lo2 < a_hi


@app.route("/markup-tiers", methods=["GET"])
def list_markup_tiers():
    require_role(role(), ["PartsManager", "ShopManager", "ServiceAdvisor"])
    # Listed in tier_index order (PRD 3.1).
    from helpers import parse_pagination
    from response import array_response
    limit, offset = parse_pagination()
    ordered = sorted(db.markup_tiers.values(), key=lambda t: t["tier_index"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response([ser(r) for r in page], limit, offset, total)


# =========================================================================== #
# RepairOrder
# =========================================================================== #
@app.route("/repair-orders", methods=["POST"])
def create_repair_order():
    require_role(role(), ["ServiceAdvisor", "ShopManager"])
    body = get_json_body()
    require_fields(body, ["customer_id", "vehicle_id"])
    customer_id = require_string(body, "customer_id")
    vehicle_id = require_string(body, "vehicle_id")
    comeback_of = opt_string(body, "comeback_of_ro_id", None)
    # Body FK existence (PRD 2.5)
    if customer_id not in db.customers:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "customer_id does not exist.")
    if vehicle_id not in db.vehicles:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "vehicle_id does not exist.")
    if comeback_of is not None and comeback_of not in db.repair_orders:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "comeback_of_ro_id does not exist.")
    tax_rate = opt_number(body, "tax_rate", 0.0)
    if tax_rate < 0:
        raise ApiError("ERR_INVALID_REQUEST", "tax_rate must be >= 0.")

    # Warranty window validated at creation when comeback (PRD 3.2 / 3.8)
    if comeback_of is not None:
        original = db.repair_orders[comeback_of]
        vehicle = db.vehicles[vehicle_id]
        services.check_warranty_window(original, vehicle)

    ro = db.common_fields()
    ro.update({
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "bay_id": None,
        "comeback_of_ro_id": comeback_of,
        "is_comeback": comeback_of is not None,
        "scheduled_start": None,
        "scheduled_end": None,
        "tax_rate": tax_rate,
        "labor_total_cents": 0,
        "parts_total_cents": 0,
        "core_deposit_total_cents": 0,
        "tax_cents": 0,
        "grand_total_cents": 0,
        "approved_work_value_cents": 0,
        "authorized_total_cents": None,
        "authorized_version": None,
        "closed_at": None,
        "close_odometer_miles": None,
        "status": "ESTIMATE",
    })
    db.repair_orders[ro["id"]] = ro
    return obj(ro, ser, 201)


@app.route("/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    ro = must_get(db.repair_orders, rid)
    return obj(ro, ser)


@app.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    items = list(db.repair_orders.values())
    for key in ("customer_id", "vehicle_id", "bay_id", "comeback_of_ro_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    return paginated_list(items, ser)


@app.route("/repair-orders/<rid>/schedule", methods=["POST"])
def schedule_repair_order(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager"])
    ro = must_get(db.repair_orders, rid)
    body = get_json_body()
    require_fields(body, ["bay_id", "scheduled_start", "scheduled_end"])
    bay_id = require_string(body, "bay_id")
    if bay_id not in db.service_bays:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "bay_id does not exist.")
    start_raw = require_string(body, "scheduled_start")
    end_raw = require_string(body, "scheduled_end")
    try:
        start = clock.parse_iso(start_raw)
        end = clock.parse_iso(end_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_start/scheduled_end must be ISO 8601.")
    # window end strictly after start (PRD 3.2)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be after scheduled_start.")

    # Half-open [start, end) must not overlap another RO on the same bay;
    # touching endpoints allowed (PRD 3.2). -> ERR_BAY_DOUBLE_BOOKED
    for other in db.repair_orders.values():
        if other["id"] == ro["id"]:
            continue
        if other["bay_id"] != bay_id:
            continue
        if other["scheduled_start"] is None or other["scheduled_end"] is None:
            continue
        o_start = clock.parse_iso(other["scheduled_start"])
        o_end = clock.parse_iso(other["scheduled_end"])
        if start < o_end and o_start < end:
            raise ApiError("ERR_BAY_DOUBLE_BOOKED",
                           "Bay window overlaps another repair order on this bay.")

    ro["bay_id"] = bay_id
    ro["scheduled_start"] = start_raw
    ro["scheduled_end"] = end_raw
    db.touch(ro)
    return obj(ro, ser)


@app.route("/repair-orders/<rid>/authorize", methods=["POST"])
def authorize_repair_order(rid):
    # Customer-exclusive (PRD 3.3); ShopManager is NOT granted this override.
    require_role(role(), ["Customer"])
    ro = must_get(db.repair_orders, rid)

    # Ownership is priority 2 (PRD 2.6) — checked before body validation (5)
    # and state (6). Acting customer must own the RO's vehicle (PRD 3.3) -> 403.
    vehicle = db.vehicles.get(ro["vehicle_id"])
    if vehicle is None or vehicle["customer_id"] != uid():
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "Customer does not own this repair order's vehicle.")

    body = get_json_body()
    # expected_repair_order_version is non-optional (PRD 2.9)
    if "expected_repair_order_version" not in body or body["expected_repair_order_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_repair_order_version is required.")
    expected = require_int(body, "expected_repair_order_version")

    # State: only ESTIMATE -> APPROVED (PRD 3.3)
    if ro["status"] != "ESTIMATE":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not in ESTIMATE status.")

    # Something to bill (PRD 3.3) -> ERR_NOTHING_TO_AUTHORIZE
    has_labor = any(l["repair_order_id"] == ro["id"] for l in db.labor_lines.values())
    has_part = any(p["repair_order_id"] == ro["id"] for p in db.part_lines.values())
    has_approved_job = any(
        j["repair_order_id"] == ro["id"] and j["status"] == "APPROVED"
        for j in db.recommended_jobs.values()
    )
    if not (has_labor or has_part or has_approved_job):
        raise ApiError("ERR_NOTHING_TO_AUTHORIZE",
                       "Repair order has nothing to authorize.")

    # OCC (PRD 2.9) -> ERR_STALE_VERSION
    if expected != ro["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_repair_order_version is stale.")

    # snapshot grand total, advance to APPROVED, increment version,
    # authorized_version = version AFTER this mutation (PRD 3.3)
    ro["authorized_total_cents"] = ro["grand_total_cents"]
    ro["status"] = "APPROVED"
    db.touch(ro)
    ro["authorized_version"] = ro["version"]
    return obj(ro, ser)


@app.route("/repair-orders/<rid>/transition", methods=["POST"])
def transition_repair_order(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager"])
    ro = must_get(db.repair_orders, rid)
    body = get_json_body()
    action = require_enum(body, "action",
                          {"START", "HOLD", "RESUME", "INVOICE", "CLOSE", "CANCEL"})

    if action == "START":
        if ro["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Repair order is not APPROVED.")
        if ro["bay_id"] is None:
            raise ApiError("ERR_BAY_NOT_ASSIGNED", "Repair order has no assigned bay.")
        ro["status"] = "IN_PROGRESS"
        db.touch(ro)

    elif action == "HOLD":
        if ro["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", "Repair order is not IN_PROGRESS.")
        ro["status"] = "ON_HOLD"
        db.touch(ro)
        _pause_labor_lines(ro)

    elif action == "RESUME":
        if ro["status"] != "ON_HOLD":
            raise ApiError("ERR_INVALID_STATE", "Repair order is not ON_HOLD.")
        ro["status"] = "IN_PROGRESS"
        db.touch(ro)

    elif action == "INVOICE":
        if ro["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", "Repair order is not COMPLETED.")
        ro["status"] = "INVOICED"
        db.touch(ro)

    elif action == "CLOSE":
        if ro["status"] != "INVOICED":
            raise ApiError("ERR_INVALID_STATE", "Repair order is not INVOICED.")
        # refused while any core charge still CHARGED (PRD 3.3) -> ERR_CORE_OUTSTANDING
        outstanding = any(
            c["repair_order_id"] == ro["id"] and c["status"] == "CHARGED"
            for c in db.core_charges.values()
        )
        if outstanding:
            raise ApiError("ERR_CORE_OUTSTANDING", "A core charge is still CHARGED.")
        vehicle = db.vehicles[ro["vehicle_id"]]
        ro["status"] = "CLOSED"
        ro["closed_at"] = clock.now_iso()
        ro["close_odometer_miles"] = vehicle["odometer_miles"]
        db.touch(ro)

    elif action == "CANCEL":
        if ro["status"] not in ("ESTIMATE", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE", "Repair order is not ESTIMATE or APPROVED.")
        ro["status"] = "CANCELLED"
        db.touch(ro)
        # Forfeit still-CHARGED cores (PRD 3.3). A forfeit leaves
        # core_deposit_total_cents unchanged — "forfeited deposits remain billed"
        # (PRD 3.12) — so we deliberately do NOT recompute totals here.
        for c in db.core_charges.values():
            if c["repair_order_id"] == ro["id"] and c["status"] == "CHARGED":
                c["status"] = "FORFEITED"
                db.touch(c)

    return obj(ro, ser)


def _pause_labor_lines(ro):
    """ON_HOLD side effect: each IN_PROGRESS labor line -> PAUSED, auto-close
    open clock sessions exactly like a clock-out (PRD 3.3)."""
    for line in db.labor_lines.values():
        if line["repair_order_id"] != ro["id"]:
            continue
        if line["status"] != "IN_PROGRESS":
            continue
        if line["open_clock_at"] is not None:
            _auto_close_session(line, clock.now())
        line["status"] = "PAUSED"
        db.touch(line)
        if line["billing_method"] == "TIME_AND_MATERIALS":
            line["charge_cents"] = labor_charge_cents(line)
    recompute_repair_order_total(ro)


def _auto_close_session(line, at):
    """Accumulate elapsed hours, clear open clock, free the technician."""
    open_at = clock.parse_iso(line["open_clock_at"])
    elapsed_hours = (at - open_at).total_seconds() / 3600.0
    from calculations import round_hours
    line["actual_hours"] = round_hours(Decimal(str(line["actual_hours"]))
                                       + Decimal(str(elapsed_hours)))
    line["open_clock_at"] = None
    tech_id = line.get("technician_id")
    if tech_id and tech_id in db.technicians:
        tech = db.technicians[tech_id]
        if tech.get("clocked_labor_line_id") == line["id"]:
            tech["clocked_labor_line_id"] = None
            tech["last_clock_out_at"] = clock.to_iso(at)
            db.touch(tech)


@app.route("/repair-orders/<rid>/complete", methods=["POST"])
def complete_repair_order(rid):
    require_role(role(), ["Technician", "ShopManager"])
    ro = must_get(db.repair_orders, rid)
    # State (PRD 3.3) -> ERR_INVALID_STATE
    if ro["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not IN_PROGRESS.")
    ro_lines = [l for l in db.labor_lines.values() if l["repair_order_id"] == ro["id"]]
    # Every labor line COMPLETED (PRD 3.3) -> ERR_LABOR_NOT_DONE
    if any(l["status"] != "COMPLETED" for l in ro_lines):
        raise ApiError("ERR_LABOR_NOT_DONE", "Not every labor line is COMPLETED.")
    # Inspection (if any) SUBMITTED or REVIEWED (PRD 3.3) -> ERR_INSPECTION_NOT_SUBMITTED
    ro_inspections = [i for i in db.inspections.values() if i["repair_order_id"] == ro["id"]]
    for insp in ro_inspections:
        if insp["status"] not in ("SUBMITTED", "REVIEWED"):
            raise ApiError("ERR_INSPECTION_NOT_SUBMITTED",
                           "An inspection on this order is not submitted.")
    # If any inspection item is RED, no RED RecommendedJob may still be PENDING
    # (PRD 3.3) -> ERR_RED_WORK_UNRESOLVED
    has_red_item = any(
        any(it.get("severity") == "RED" for it in insp["items"])
        for insp in ro_inspections
    )
    if has_red_item:
        pending_red = any(
            j["repair_order_id"] == ro["id"]
            and j["status"] == "PENDING"
            and j["severity"] == "RED"
            for j in db.recommended_jobs.values()
        )
        if pending_red:
            raise ApiError("ERR_RED_WORK_UNRESOLVED",
                           "A RED-severity recommended job is still PENDING.")

    ro["status"] = "COMPLETED"
    db.touch(ro)

    # Cascade complete-credit: each COMPLETED non-warranty labor line with a tech
    # credits that tech's banked hours (PRD 3.7).
    for line in ro_lines:
        if line["status"] != "COMPLETED":
            continue
        if line["is_warranty"]:
            continue
        tech_id = line.get("technician_id")
        if not tech_id or tech_id not in db.technicians:
            continue
        tech = db.technicians[tech_id]
        tech["banked_flat_hours"] = float(Decimal(str(tech["banked_flat_hours"]))
                                          + Decimal(str(line["book_hours"])))
        tech["banked_actual_hours"] = float(Decimal(str(tech["banked_actual_hours"]))
                                            + Decimal(str(line["actual_hours"])))
        recompute_efficiency(tech)
        db.touch(tech)

    # If RO is a comeback: each warranty labor line debits the ORIGINAL RO's
    # assigned technician banked_flat_hours by that line's book_hours (PRD 3.7).
    if ro["is_comeback"] and ro["comeback_of_ro_id"]:
        original = db.repair_orders.get(ro["comeback_of_ro_id"])
        if original is not None:
            orig_tech = _original_ro_technician(original)
            for line in ro_lines:
                if not line["is_warranty"]:
                    continue
                if orig_tech is not None:
                    orig_tech["banked_flat_hours"] = float(
                        Decimal(str(orig_tech["banked_flat_hours"]))
                        - Decimal(str(line["book_hours"]))
                    )
                    recompute_efficiency(orig_tech)
                    db.touch(orig_tech)

    recompute_repair_order_total(ro)
    return obj(ro, ser)


def _original_ro_technician(original):
    """The original RO's assigned technician. Interpreted as the technician on
    the original RO's labor lines (PRD 3.7 'the original order's assigned
    technician'). Use the first labor line bearing a technician."""
    for line in db.labor_lines.values():
        if line["repair_order_id"] == original["id"] and line.get("technician_id"):
            tech = db.technicians.get(line["technician_id"])
            if tech is not None:
                return tech
    return None


# =========================================================================== #
# LaborLine
# =========================================================================== #
@app.route("/repair-orders/<rid>/labor-lines", methods=["POST"])
def add_labor_line(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician"])
    ro = must_get(db.repair_orders, rid)
    body = get_json_body()
    require_fields(body, ["labor_operation_id"])
    labor_op_id = require_string(body, "labor_operation_id")
    technician_id = opt_string(body, "technician_id", None)
    if labor_op_id not in db.labor_operations:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "labor_operation_id does not exist.")
    if technician_id is not None and technician_id not in db.technicians:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "technician_id does not exist.")
    billing_method = opt_enum(body, "billing_method",
                              {"FLAT_RATE", "TIME_AND_MATERIALS"}, "FLAT_RATE")
    rate_cents = opt_int(body, "rate_cents", None)
    if rate_cents is not None and rate_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "rate_cents must be > 0.")
    is_warranty = opt_bool(body, "is_warranty", False)

    # RO not editable (PRD 3.4) -> ERR_RO_NOT_EDITABLE
    if ro["status"] in services.RO_NON_EDITABLE:
        raise ApiError("ERR_RO_NOT_EDITABLE", "Repair order is not editable.")

    # is_warranty -> validate owning RO is a comeback within warranty (PRD 3.8)
    if is_warranty:
        _require_warranty_window(ro)

    line = services.create_labor_line(ro, labor_op_id, technician_id,
                                      billing_method, rate_cents, is_warranty)
    return obj(line, ser, 201)


def _require_warranty_window(ro):
    if not ro["is_comeback"] or not ro["comeback_of_ro_id"]:
        raise ApiError("ERR_WARRANTY_EXPIRED",
                       "Warranty line requires the order to be a comeback.")
    original = db.repair_orders.get(ro["comeback_of_ro_id"])
    if original is None:
        raise ApiError("ERR_WARRANTY_EXPIRED", "Original repair order not found.")
    vehicle = db.vehicles[ro["vehicle_id"]]
    services.check_warranty_window(original, vehicle)


@app.route("/repair-orders/<rid>/labor-lines", methods=["GET"])
def list_ro_labor_lines(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    must_get(db.repair_orders, rid)
    items = [l for l in db.labor_lines.values() if l["repair_order_id"] == rid]
    return paginated_list(items, ser)


@app.route("/labor-lines/<lid>", methods=["GET"])
def get_labor_line(lid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician"])
    line = must_get(db.labor_lines, lid)
    return obj(line, ser)


@app.route("/labor-lines", methods=["GET"])
def list_labor_lines():
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician"])
    items = list(db.labor_lines.values())
    for key in ("technician_id", "labor_operation_id", "repair_order_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    return paginated_list(items, ser)


@app.route("/labor-lines/<lid>/clock-in", methods=["POST"])
def clock_in(lid):
    require_role(role(), ["Technician"])
    line = must_get(db.labor_lines, lid)
    body = get_json_body()
    require_fields(body, ["technician_id", "clock_in"])
    technician_id = require_string(body, "technician_id")
    if technician_id not in db.technicians:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "technician_id does not exist.")
    clock_in_raw = require_string(body, "clock_in")
    try:
        clock_in_dt = clock.parse_iso(clock_in_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "clock_in must be ISO 8601.")
    tech = db.technicians[technician_id]

    # Owning RO IN_PROGRESS; line NOT_STARTED or PAUSED (PRD 3.4) -> ERR_INVALID_STATE
    ro = db.repair_orders[line["repair_order_id"]]
    if ro["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Owning repair order is not IN_PROGRESS.")
    if line["status"] not in ("NOT_STARTED", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "Labor line cannot be clocked in from its state.")

    # Tech conflict guards (PRD 3.9) -> ERR_TECH_DOUBLE_CLOCKED
    if tech["clocked_labor_line_id"] is not None:
        raise ApiError("ERR_TECH_DOUBLE_CLOCKED", "Technician is already clocked in.")
    if tech["last_clock_out_at"] is not None:
        last_out = clock.parse_iso(tech["last_clock_out_at"])
        buffer_end = last_out + _cleanup_buffer()
        if clock_in_dt < buffer_end:
            raise ApiError("ERR_TECH_DOUBLE_CLOCKED",
                           "Clock-in is within the cleanup buffer of the last clock-out.")

    line["open_clock_at"] = clock_in_raw
    line["status"] = "IN_PROGRESS"
    db.touch(line)
    tech["clocked_labor_line_id"] = line["id"]
    db.touch(tech)
    return obj(line, ser)


def _cleanup_buffer():
    from datetime import timedelta
    return timedelta(minutes=services.CLEANUP_BUFFER_MINUTES)


@app.route("/labor-lines/<lid>/clock-out", methods=["POST"])
def clock_out(lid):
    require_role(role(), ["Technician"])
    line = must_get(db.labor_lines, lid)
    body = get_json_body()
    require_fields(body, ["clock_out"])
    clock_out_raw = require_string(body, "clock_out")
    try:
        clock_out_dt = clock.parse_iso(clock_out_raw)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "clock_out must be ISO 8601.")

    # Open session required (PRD 3.4) -> ERR_INVALID_STATE
    if line["open_clock_at"] is None:
        raise ApiError("ERR_INVALID_STATE", "Labor line has no open clock session.")
    open_at = clock.parse_iso(line["open_clock_at"])
    # clock_out strictly later (PRD 3.4) -> ERR_INVALID_REQUEST
    if clock_out_dt <= open_at:
        raise ApiError("ERR_INVALID_REQUEST", "clock_out must be after open_clock_at.")

    from calculations import round_hours
    elapsed_hours = (clock_out_dt - open_at).total_seconds() / 3600.0
    line["actual_hours"] = round_hours(Decimal(str(line["actual_hours"]))
                                       + Decimal(str(elapsed_hours)))
    line["open_clock_at"] = None
    db.touch(line)

    tech_id = line.get("technician_id")
    # The technician holding the open session is the one whose clocked_labor_line_id
    # points at this line.
    for tech in db.technicians.values():
        if tech["clocked_labor_line_id"] == line["id"]:
            tech["clocked_labor_line_id"] = None
            tech["last_clock_out_at"] = clock_out_raw
            db.touch(tech)

    # T&M: recompute charge_cents + RO totals (PRD 3.4)
    if line["billing_method"] == "TIME_AND_MATERIALS":
        line["charge_cents"] = labor_charge_cents(line)
        db.touch(line)
        recompute_repair_order_total(db.repair_orders[line["repair_order_id"]])
    return obj(line, ser)


@app.route("/labor-lines/<lid>/complete", methods=["POST"])
def complete_labor_line(lid):
    require_role(role(), ["Technician", "ShopManager"])
    line = must_get(db.labor_lines, lid)
    # IN_PROGRESS or PAUSED (PRD 3.4) -> ERR_INVALID_STATE
    if line["status"] not in ("IN_PROGRESS", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "Labor line is not IN_PROGRESS or PAUSED.")
    # No open session (PRD 3.4) -> ERR_OPEN_TIME_ENTRY
    if line["open_clock_at"] is not None:
        raise ApiError("ERR_OPEN_TIME_ENTRY", "An open clock session remains.")
    line["status"] = "COMPLETED"
    line["charge_cents"] = labor_charge_cents(line)
    db.touch(line)
    recompute_repair_order_total(db.repair_orders[line["repair_order_id"]])
    return obj(line, ser)


# =========================================================================== #
# PartLine
# =========================================================================== #
@app.route("/repair-orders/<rid>/part-lines", methods=["POST"])
def add_part_line(rid):
    require_role(role(), ["PartsManager", "ServiceAdvisor", "ShopManager"])
    ro = must_get(db.repair_orders, rid)
    body = get_json_body()
    require_fields(body, ["part_number", "description", "quantity", "unit_cost_cents"])
    part_number = require_string(body, "part_number")
    description = require_string(body, "description")
    quantity = require_int(body, "quantity")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity must be > 0.")
    unit_cost = require_int(body, "unit_cost_cents")
    if unit_cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be >= 0.")
    markup_mode = opt_enum(body, "markup_mode", {"MARGINAL", "FLAT_BRACKET"}, "MARGINAL")
    has_core = opt_bool(body, "has_core", False)
    core_deposit = opt_int(body, "core_deposit_cents", 0)
    if core_deposit < 0:
        raise ApiError("ERR_INVALID_REQUEST", "core_deposit_cents must be >= 0.")
    is_warranty = opt_bool(body, "is_warranty", False)

    # RO not editable (PRD 3.5) -> ERR_RO_NOT_EDITABLE
    if ro["status"] in services.RO_NON_EDITABLE:
        raise ApiError("ERR_RO_NOT_EDITABLE", "Repair order is not editable.")

    if is_warranty:
        _require_warranty_window(ro)

    # create_part_line computes markup (may raise ERR_MARKUP_TIER_MISSING),
    # cascades a CoreCharge when has_core, recomputes totals.
    line = services.create_part_line(ro, part_number, description, quantity,
                                     unit_cost, markup_mode, has_core,
                                     core_deposit, is_warranty)
    return obj(line, ser, 201)


@app.route("/repair-orders/<rid>/part-lines", methods=["GET"])
def list_ro_part_lines(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager",
                          "Technician", "Customer"])
    must_get(db.repair_orders, rid)
    items = [p for p in db.part_lines.values() if p["repair_order_id"] == rid]
    return paginated_list(items, ser)


@app.route("/part-lines/<pid>", methods=["GET"])
def get_part_line(pid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager"])
    p = must_get(db.part_lines, pid)
    return obj(p, ser)


@app.route("/part-lines/<pid>/install", methods=["POST"])
def install_part_line(pid):
    require_role(role(), ["Technician", "PartsManager", "ShopManager"])
    p = must_get(db.part_lines, pid)
    # QUOTED -> INSTALLED (PRD 3.5) -> ERR_INVALID_STATE otherwise
    if p["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Part line is not QUOTED.")
    p["status"] = "INSTALLED"
    db.touch(p)
    return obj(p, ser)


# =========================================================================== #
# CoreCharge
# =========================================================================== #
@app.route("/repair-orders/<rid>/core-charges", methods=["GET"])
def list_ro_core_charges(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager", "Customer"])
    must_get(db.repair_orders, rid)
    items = [c for c in db.core_charges.values() if c["repair_order_id"] == rid]
    return paginated_list(items, ser)


@app.route("/core-charges/<cid>", methods=["GET"])
def get_core_charge(cid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager"])
    c = must_get(db.core_charges, cid)
    return obj(c, ser)


@app.route("/core-charges", methods=["GET"])
def list_core_charges():
    require_role(role(), ["ServiceAdvisor", "ShopManager", "PartsManager"])
    items = list(db.core_charges.values())
    for key in ("part_line_id", "repair_order_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return paginated_list(items, ser)


@app.route("/core-charges/<cid>/return", methods=["POST"])
def return_core_charge(cid):
    require_role(role(), ["PartsManager", "ShopManager"])
    c = must_get(db.core_charges, cid)
    # CHARGED required (PRD 3.12) -> ERR_INVALID_STATE
    if c["status"] != "CHARGED":
        raise ApiError("ERR_INVALID_STATE", "Core charge is not CHARGED.")
    ro = db.repair_orders[c["repair_order_id"]]
    # Owning RO not CLOSED or CANCELLED (PRD 3.12) -> ERR_INVALID_STATE
    if ro["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", "Owning repair order is CLOSED or CANCELLED.")
    c["status"] = "CORE_RETURNED"
    c["refunded_cents"] = c["deposit_cents"]
    db.touch(c)
    # Subtract the deposit from the conserved core total to restore the core
    # invariant (PRD 3.12), then recompute the rest of the totals.
    ro["core_deposit_total_cents"] -= c["deposit_cents"]
    recompute_repair_order_total(ro)
    return obj(c, ser)


@app.route("/core-charges/<cid>/forfeit", methods=["POST"])
def forfeit_core_charge(cid):
    require_role(role(), ["PartsManager", "ShopManager"])
    c = must_get(db.core_charges, cid)
    # CHARGED required (PRD 3.12) -> ERR_INVALID_STATE
    if c["status"] != "CHARGED":
        raise ApiError("ERR_INVALID_STATE", "Core charge is not CHARGED.")
    c["status"] = "FORFEITED"
    db.touch(c)
    # Forfeited deposit is retained by the shop and remains billed, so
    # core_deposit_total_cents is unchanged and we do NOT recompute (PRD 3.12).
    return obj(c, ser)


# =========================================================================== #
# Inspection
# =========================================================================== #
@app.route("/repair-orders/<rid>/inspections", methods=["POST"])
def create_inspection(rid):
    require_role(role(), ["Technician", "ShopManager"])
    ro = must_get(db.repair_orders, rid)
    body = get_json_body()
    require_fields(body, ["technician_id"])
    technician_id = require_string(body, "technician_id")
    if technician_id not in db.technicians:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "technician_id does not exist.")
    insp = db.common_fields()
    insp.update({
        "repair_order_id": ro["id"],
        "technician_id": technician_id,
        "items": [],
        "worst_severity": "GREEN",
        "red_item_count": 0,
        "status": "DRAFT",
    })
    db.inspections[insp["id"]] = insp
    return obj(insp, ser, 201)


@app.route("/repair-orders/<rid>/inspections", methods=["GET"])
def list_ro_inspections(rid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician", "Customer"])
    must_get(db.repair_orders, rid)
    items = [i for i in db.inspections.values() if i["repair_order_id"] == rid]
    return paginated_list(items, ser)


@app.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician", "Customer"])
    i = must_get(db.inspections, iid)
    return obj(i, ser)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician", "Customer"])
    items = list(db.inspections.values())
    for key in ("technician_id", "repair_order_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    return paginated_list(items, ser)


@app.route("/inspections/<iid>/items", methods=["POST"])
def append_inspection_item(iid):
    require_role(role(), ["Technician", "ShopManager"])
    insp = must_get(db.inspections, iid)
    body = get_json_body()
    require_fields(body, ["point_name"])
    point_name = require_string(body, "point_name")
    severity = opt_enum(body, "severity", {"GREEN", "YELLOW", "RED"}, "GREEN")
    note = opt_string(body, "note", None)
    # Append only to DRAFT (PRD 3.10) -> ERR_INVALID_STATE
    if insp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Inspection is not DRAFT.")
    item = {"point_name": point_name, "severity": severity}
    if note is not None:
        item["note"] = note
    insp["items"].append(item)
    db.touch(insp)
    return obj(insp, ser)


@app.route("/inspections/<iid>/submit", methods=["POST"])
def submit_inspection(iid):
    require_role(role(), ["Technician", "ShopManager"])
    insp = must_get(db.inspections, iid)
    # DRAFT required (PRD 3.10) -> ERR_INVALID_STATE
    if insp["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Inspection is not DRAFT.")
    # At least one item (PRD 3.10) -> ERR_INSPECTION_EMPTY
    if len(insp["items"]) == 0:
        raise ApiError("ERR_INSPECTION_EMPTY", "Inspection has no items.")
    _recompute_severity(insp)
    insp["status"] = "SUBMITTED"
    db.touch(insp)
    return obj(insp, ser)


def _recompute_severity(insp):
    severities = [it.get("severity", "GREEN") for it in insp["items"]]
    if "RED" in severities:
        insp["worst_severity"] = "RED"
    elif "YELLOW" in severities:
        insp["worst_severity"] = "YELLOW"
    else:
        insp["worst_severity"] = "GREEN"
    insp["red_item_count"] = sum(1 for s in severities if s == "RED")


@app.route("/inspections/<iid>/review", methods=["POST"])
def review_inspection(iid):
    require_role(role(), ["ServiceAdvisor", "ShopManager"])
    insp = must_get(db.inspections, iid)
    # SUBMITTED required (PRD 3.10) -> ERR_INVALID_STATE
    if insp["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Inspection is not SUBMITTED.")
    insp["status"] = "REVIEWED"
    db.touch(insp)
    return obj(insp, ser)


# =========================================================================== #
# RecommendedJob
# =========================================================================== #
@app.route("/inspections/<iid>/recommended-jobs", methods=["POST"])
def create_recommended_job(iid):
    require_role(role(), ["Technician", "ServiceAdvisor", "ShopManager"])
    insp = must_get(db.inspections, iid)
    body = get_json_body()
    require_fields(body, ["repair_order_id", "labor_operation_id"])
    repair_order_id = require_string(body, "repair_order_id")
    labor_operation_id = require_string(body, "labor_operation_id")
    if repair_order_id not in db.repair_orders:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "repair_order_id does not exist.")
    if labor_operation_id not in db.labor_operations:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "labor_operation_id does not exist.")
    part_number = opt_string(body, "part_number", None)
    part_quantity = opt_int(body, "part_quantity", 0)
    if part_quantity < 0:
        raise ApiError("ERR_INVALID_REQUEST", "part_quantity must be >= 0.")
    part_unit_cost = opt_int(body, "part_unit_cost_cents", 0)
    if part_unit_cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", "part_unit_cost_cents must be >= 0.")
    has_core = opt_bool(body, "has_core", False)
    core_deposit = opt_int(body, "core_deposit_cents", 0)
    if core_deposit < 0:
        raise ApiError("ERR_INVALID_REQUEST", "core_deposit_cents must be >= 0.")
    severity = opt_enum(body, "severity", {"YELLOW", "RED"}, "YELLOW")

    # estimated_value_cents = flat-rate labor for op + FLAT_BRACKET-marked-up
    # part cost (PRD 3.10).
    op = db.labor_operations[labor_operation_id]
    labor_value = labor_charge_cents({
        "is_warranty": False,
        "billing_method": "FLAT_RATE",
        "book_hours": op["book_hours"],
        "rate_cents": None,
        "labor_operation_id": labor_operation_id,
    })
    part_value = 0
    if part_number is not None and part_quantity > 0:
        part_value = parts_extended_charge_cents(part_quantity, part_unit_cost,
                                                 "FLAT_BRACKET", False)
    estimated_value = labor_value + part_value

    job = db.common_fields()
    job.update({
        "inspection_id": insp["id"],
        "repair_order_id": repair_order_id,
        "labor_operation_id": labor_operation_id,
        "part_number": part_number,
        "part_quantity": part_quantity,
        "part_unit_cost_cents": part_unit_cost,
        "has_core": has_core,
        "core_deposit_cents": core_deposit,
        "estimated_value_cents": estimated_value,
        "severity": severity,
        "created_labor_line_id": None,
        "created_part_line_id": None,
        "status": "PENDING",
    })
    db.recommended_jobs[job["id"]] = job
    return obj(job, ser, 201)


@app.route("/inspections/<iid>/recommended-jobs", methods=["GET"])
def list_inspection_recommended_jobs(iid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician", "Customer"])
    must_get(db.inspections, iid)
    items = [j for j in db.recommended_jobs.values() if j["inspection_id"] == iid]
    return paginated_list(items, ser)


@app.route("/recommended-jobs/<jid>", methods=["GET"])
def get_recommended_job(jid):
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician", "Customer"])
    j = must_get(db.recommended_jobs, jid)
    return obj(j, ser)


@app.route("/recommended-jobs", methods=["GET"])
def list_recommended_jobs():
    require_role(role(), ["ServiceAdvisor", "ShopManager", "Technician", "Customer"])
    items = list(db.recommended_jobs.values())
    for key in ("repair_order_id", "labor_operation_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [j for j in items if j.get(key) == val]
    return paginated_list(items, ser)


@app.route("/recommended-jobs/<jid>/decision", methods=["POST"])
def decide_recommended_job(jid):
    # Customer-exclusive (PRD 3.11)
    require_role(role(), ["Customer"])
    job = must_get(db.recommended_jobs, jid)

    ro = db.repair_orders[job["repair_order_id"]]
    # Ownership is priority 2 (PRD 2.6) — checked before body validation (5)
    # and state (6). Customer must own the RO's vehicle (PRD 3.11) -> 403.
    vehicle = db.vehicles.get(ro["vehicle_id"])
    if vehicle is None or vehicle["customer_id"] != uid():
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Customer does not own this recommended job's vehicle.")

    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVE", "DECLINE", "DEFER"})

    if decision == "DECLINE":
        # PENDING or DEFERRED -> DECLINED (PRD 3.11)
        if job["status"] not in ("PENDING", "DEFERRED"):
            raise ApiError("ERR_INVALID_STATE", "Recommended job cannot be declined.")
        job["status"] = "DECLINED"
        db.touch(job)

    elif decision == "DEFER":
        # PENDING -> DEFERRED (PRD 3.11)
        if job["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Recommended job cannot be deferred.")
        job["status"] = "DEFERRED"
        db.touch(job)

    else:  # APPROVE
        # PENDING or DEFERRED -> APPROVED (PRD 3.11)
        if job["status"] not in ("PENDING", "DEFERRED"):
            raise ApiError("ERR_INVALID_STATE", "Recommended job cannot be approved.")
        # Owning RO must be ESTIMATE/APPROVED/IN_PROGRESS/ON_HOLD (PRD 3.11)
        if ro["status"] not in ("ESTIMATE", "APPROVED", "IN_PROGRESS", "ON_HOLD"):
            raise ApiError("ERR_INVALID_STATE",
                           "Owning repair order is not in an approvable state.")
        job["status"] = "APPROVED"
        db.touch(job)
        _materialize_recommended_job(job, ro)
        recompute_repair_order_total(ro)

    return obj(job, ser)


def _materialize_recommended_job(job, ro):
    """Approval cascade (PRD 3.11): create LaborLine, optional PartLine (+ core)."""
    # link 1: LaborLine from labor_operation_id
    labor_line = services.create_labor_line(
        ro,
        job["labor_operation_id"],
        None,                 # no technician on a materialized recommended line
        "FLAT_RATE",          # default billing method
        None,                 # default rate
        False,                # not warranty
    )
    job["created_labor_line_id"] = labor_line["id"]

    # link 2: PartLine when part_number set
    if job["part_number"] is not None:
        part_line = services.create_part_line(
            ro,
            job["part_number"],
            job["part_number"],          # description default to part number
            job["part_quantity"],
            job["part_unit_cost_cents"],
            "FLAT_BRACKET",              # estimate used FLAT_BRACKET; materialize same
            job["has_core"],
            job["core_deposit_cents"],
            False,
        )
        job["created_part_line_id"] = part_line["id"]
    db.touch(job)


# =========================================================================== #
# Test-driving clock
# =========================================================================== #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(role(), ["ShopManager"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = require_string(body, "to_iso8601")
    try:
        dt = clock.parse_iso(to_iso)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601.")
    clock.set_now(dt)
    # output: null -> empty data object
    return object_response({}, 200)


if __name__ == "__main__":
    clock.reset()  # in-memory clock starts un-overridden on every boot
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
