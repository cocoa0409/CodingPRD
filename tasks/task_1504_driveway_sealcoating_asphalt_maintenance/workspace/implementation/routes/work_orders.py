"""WorkOrder endpoints: schedule/reschedule/start/finish/complete/cancel + striping."""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, request

from clock import now, now_iso_ms, format_iso_ms, parse_iso, today_date
from db import DB
from middleware import (
    require_role, get_json_body, check_unknown_fields, require_fields,
    require_number, base_fields, paginate, err, touch, valid_date_str, parse_date,
)
from response import success_object, success_list
from errors import (
    ERR_WORK_ORDER_NOT_FOUND, ERR_ROUTE_SHEET_NOT_FOUND, ERR_MATERIAL_LOT_NOT_FOUND,
    ERR_PROPERTY_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_WORK_ORDER_NOT_SCHEDULABLE, ERR_ROUTE_SHEET_NOT_SCHEDULABLE,
    ERR_OUTSIDE_SEASON, ERR_DATE_IN_PAST, ERR_RESEAL_INTERVAL_NOT_MET,
    ERR_ROUTE_CAPACITY_EXCEEDED, ERR_ROUTE_DRIVE_LIMIT_EXCEEDED,
    ERR_CREW_WINDOW_OVERLAP, ERR_ACCESS_WINDOW_OVERLAP,
    ERR_MATERIAL_LOT_UNAVAILABLE, ERR_INSUFFICIENT_MATERIAL,
    ERR_INVALID_WINDOW_HOURS, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
    ERR_WORK_ORDER_NOT_STARTABLE, ERR_WORK_ORDER_NOT_FINISHABLE,
    ERR_WORK_ORDER_NOT_CANCELLABLE, ERR_DISPLACEMENT_NOT_CLEARED,
    ERR_CURE_INCOMPLETE, ERR_STRIPING_NOT_VERIFIED, ERR_STRIPING_NOT_PLANNABLE,
    ERR_STRIPING_COMMERCIAL_ONLY,
)
from services import (
    weather_gate, cure_hours, material_gallons_required, refresh_material_lot,
    refresh_route_sheet, find_displacement_plan_for_work_order,
    lazy_route_sheet_completion, invoice_settlement, ada_stall_requirement,
    date_at_hour_utc,
)
from middleware import add_months

bp = Blueprint("work_orders", __name__)


def serialize_work_order(w):
    return {
        "id": w["id"],
        "property_id": w["property_id"],
        "quote_id": w["quote_id"],
        "warranty_claim_id": w["warranty_claim_id"],
        "route_sheet_id": w["route_sheet_id"],
        "material_lot_id": w["material_lot_id"],
        "include_crack_fill": w["include_crack_fill"],
        "include_patch": w["include_patch"],
        "include_seal": w["include_seal"],
        "include_striping": w["include_striping"],
        "coats": w["coats"],
        "material_grade": w["material_grade"],
        "quoted_area_sqft": w["quoted_area_sqft"],
        "quoted_total_cents": w["quoted_total_cents"],
        "scheduled_date": w["scheduled_date"],
        "window_start_hour": w["window_start_hour"],
        "window_end_hour": w["window_end_hour"],
        "drive_minutes_est": w["drive_minutes_est"],
        "vehicles_to_move": w["vehicles_to_move"],
        "reserved_gallons": w["reserved_gallons"],
        "execution_status": w["execution_status"],
        "billing_status": w["billing_status"],
        "striping_status": w["striping_status"],
        "stall_count": w["stall_count"],
        "ada_stalls_required": w["ada_stalls_required"],
        "stripe_linear_ft_computed": w["stripe_linear_ft_computed"],
        "actual_area_sqft": w["actual_area_sqft"],
        "actual_crack_ft": w["actual_crack_ft"],
        "actual_pothole_area_sqft": w["actual_pothole_area_sqft"],
        "actual_stripe_ft": w["actual_stripe_ft"],
        "gallons_used": w["gallons_used"],
        "started_at": w["started_at"],
        "finished_at": w["finished_at"],
        "cure_until": w["cure_until"],
        "completed_at": w["completed_at"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


# -------------------- list & get --------------------

@bp.get("/api/work-orders")
def list_work_orders():
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    items = list(DB.work_orders.values())
    if role == "Customer":
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        items = [w for w in items if w["property_id"] in own_props]
    for f in ["property_id", "quote_id", "route_sheet_id", "material_lot_id",
              "warranty_claim_id", "execution_status"]:
        v = request.args.get(f)
        if v:
            items = [w for w in items if str(w.get(f)) == v]
    items.sort(key=lambda w: w["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_work_order(w) for w in page], limit, offset, total)


@bp.get("/api/work-orders/<workOrderId>")
def get_work_order(workOrderId):
    user_id, role = require_role("OfficeAdmin", "Estimator", "Dispatcher", "CrewLead", "Customer")
    w = DB.work_orders.get(workOrderId)
    if w is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if role == "Customer":
        prop = DB.properties.get(w["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    return success_object(serialize_work_order(w))


# -------------------- helpers --------------------

def _validate_window_hours(body):
    """Returns (start_hour, end_hour). Raises ERR_INVALID_WINDOW_HOURS or ERR_INVALID_REQUEST."""
    require_fields(body, ["window_start_hour", "window_end_hour"])
    s = body["window_start_hour"]
    e = body["window_end_hour"]
    if not isinstance(s, int) or isinstance(s, bool) or not isinstance(e, int) or isinstance(e, bool):
        raise err(ERR_INVALID_WINDOW_HOURS, 400,
                  "window_end_hour <= window_start_hour or hours outside 6..20")
    if s < 6 or s > 19 or e < 7 or e > 20 or e <= s:
        raise err(ERR_INVALID_WINDOW_HOURS, 400,
                  "window_end_hour <= window_start_hour or hours outside 6..20")
    return s, e


def _season_gate(date_str):
    d = parse_date(date_str)
    md = (d.month, d.day)
    if not ((4, 1) <= md <= (10, 31)):
        raise err(ERR_OUTSIDE_SEASON, 422, "scheduled_date falls outside [04-01, 10-31]")
    if d < today_date():
        raise err(ERR_DATE_IN_PAST, 422,
                  "scheduled_date before current clock date, or start attempted on a date other than scheduled_date")


def _check_window_overlap(sheet_id, start_h, end_h, exclude_wo_id=None):
    """Half-open interval overlap with other non-cancelled WOs on same sheet."""
    for wo in DB.work_orders.values():
        if wo["route_sheet_id"] == sheet_id and wo["id"] != exclude_wo_id \
           and wo["execution_status"] not in ("CANCELLED",):
            if wo["window_start_hour"] is None:
                continue
            # half-open overlap: [s1,e1) overlaps [s2,e2) iff s1 < e2 and s2 < e1
            if start_h < wo["window_end_hour"] and wo["window_start_hour"] < end_h:
                raise err(ERR_CREW_WINDOW_OVERLAP, 409,
                          "Half-open work-window collision with another work order on the same sheet")


def _check_access_overlap(property_id, block_start_iso, block_end_iso, exclude_wo_id=None):
    """Cure-buffered access-block overlap with other non-cancelled WOs on same property."""
    s1 = parse_iso(block_start_iso)
    e1 = parse_iso(block_end_iso)
    for wo in DB.work_orders.values():
        if wo["property_id"] == property_id and wo["id"] != exclude_wo_id \
           and wo["execution_status"] not in ("CANCELLED",):
            plan = find_displacement_plan_for_work_order(wo["id"])
            if plan is None or plan["status"] == "CANCELLED":
                continue
            if plan["access_block_start"] is None or plan["access_block_end"] is None:
                continue
            s2 = parse_iso(plan["access_block_start"])
            e2 = parse_iso(plan["access_block_end"])
            if s1 < e2 and s2 < e1:
                raise err(ERR_ACCESS_WINDOW_OVERLAP, 409,
                          "Cure-buffered access-block collision with another work order on the same property")


def _apply_booking(wo, sheet, lot, scheduled_date, window_start, window_end,
                   drive_minutes, vehicles_to_move, material):
    """Apply a booking + reservation. Creates a fresh DisplacementPlan."""
    gallons = material_gallons_required(
        wo["quoted_area_sqft"], wo["coats"], material["coverage_sqft_per_gallon"],
        wo["include_seal"],
    )
    wo["route_sheet_id"] = sheet["id"]
    wo["material_lot_id"] = lot["id"]
    wo["scheduled_date"] = scheduled_date
    wo["window_start_hour"] = window_start
    wo["window_end_hour"] = window_end
    wo["drive_minutes_est"] = drive_minutes
    wo["vehicles_to_move"] = vehicles_to_move
    wo["reserved_gallons"] = gallons
    wo["execution_status"] = "SCHEDULED"
    touch(wo)

    # Lot cascade
    lot["reserved_gallons"] = lot["reserved_gallons"] + gallons
    if lot["status"] == "RECEIVED":
        lot["status"] = "IN_USE"
    refresh_material_lot(lot)

    # Sheet cascade
    refresh_route_sheet(sheet)

    # DisplacementPlan
    plan = base_fields()
    provisional_cure_h = cure_hours(material, scheduled_date)
    access_block_start_dt = parse_iso(date_at_hour_utc(scheduled_date, window_start))
    access_block_end_dt = parse_iso(date_at_hour_utc(scheduled_date, window_end)) + timedelta(hours=provisional_cure_h)
    plan.update({
        "work_order_id": wo["id"],
        "vehicles_to_move": vehicles_to_move,
        "notice_sent_at": None,
        "access_block_start": format_iso_ms(access_block_start_dt),
        "access_block_end": format_iso_ms(access_block_end_dt),
        "status": "NOTICE_PENDING",
    })
    DB.displacement_plans[plan["id"]] = plan


def _release_booking(wo):
    """Release the current booking + reservation on sheet and lot."""
    old_sheet = DB.route_sheets.get(wo["route_sheet_id"]) if wo["route_sheet_id"] else None
    old_lot = DB.material_lots.get(wo["material_lot_id"]) if wo["material_lot_id"] else None
    if old_lot is not None:
        old_lot["reserved_gallons"] = max(0, old_lot["reserved_gallons"] - (wo["reserved_gallons"] or 0))
    wo["reserved_gallons"] = 0
    # Detach the work order from its sheet/lot BEFORE recomputing aggregates,
    # so the old sheet's booked area and drive minutes actually shrink
    # (PRD §3.5 compensating release on cancel/reschedule).
    wo["route_sheet_id"] = None
    wo["material_lot_id"] = None
    if old_lot is not None:
        refresh_material_lot(old_lot)
    if old_sheet is not None:
        refresh_route_sheet(old_sheet)


def _schedule_gates(wo, body, material, is_reschedule=False):
    """Run all gates for schedule/reschedule. Returns (sheet, lot, scheduled_date, ws, we, drive, vehicles)."""
    require_fields(body, ["route_sheet_id", "scheduled_date", "window_start_hour",
                          "window_end_hour", "drive_minutes_est"])
    sheet_id = body["route_sheet_id"]
    scheduled_date = body["scheduled_date"]
    if not valid_date_str(scheduled_date):
        raise err(ERR_INVALID_REQUEST, 400, "scheduled_date must be YYYY-MM-DD")

    # Gate 2: route sheet
    sheet = DB.route_sheets.get(sheet_id)
    if sheet is None:
        raise err(ERR_ROUTE_SHEET_NOT_FOUND, 404, "Route sheet id does not exist")
    lazy_route_sheet_completion(sheet)
    if sheet["status"] not in ("OPEN", "PUBLISHED"):
        raise err(ERR_ROUTE_SHEET_NOT_SCHEDULABLE, 409,
                  "Sheet not OPEN/PUBLISHED, crew inactive, or service_date mismatch")
    if sheet["service_date"] != scheduled_date:
        raise err(ERR_ROUTE_SHEET_NOT_SCHEDULABLE, 409,
                  "Sheet not OPEN/PUBLISHED, crew inactive, or service_date mismatch")
    crew = DB.crews.get(sheet["crew_id"])
    if crew is None or not crew["active"]:
        raise err(ERR_ROUTE_SHEET_NOT_SCHEDULABLE, 409,
                  "Sheet not OPEN/PUBLISHED, crew inactive, or service_date mismatch")

    # Gate 3: weather
    weather_gate(material, scheduled_date)

    # Gate 4: season + not-in-past
    _season_gate(scheduled_date)

    # Gate 5: reseal interval
    if wo["include_seal"] and wo["warranty_claim_id"] is None:
        prop = DB.properties.get(wo["property_id"])
        if prop is not None and prop["next_seal_eligible_on"] is not None:
            eligible_date = parse_iso(prop["next_seal_eligible_on"]).date()
            if parse_date(scheduled_date) < eligible_date:
                raise err(ERR_RESEAL_INTERVAL_NOT_MET, 422,
                          "Non-warranty seal job scheduled before Property.next_seal_eligible_on")

    # Window hours validation
    ws, we = _validate_window_hours(body)

    drive = body["drive_minutes_est"]
    if not isinstance(drive, int) or isinstance(drive, bool) or drive < 0:
        raise err(ERR_INVALID_REQUEST, 400, "drive_minutes_est must be a non-negative integer")
    vehicles = body.get("vehicles_to_move", 0)
    if not isinstance(vehicles, int) or isinstance(vehicles, bool) or vehicles < 0:
        raise err(ERR_INVALID_REQUEST, 400, "vehicles_to_move must be a non-negative integer")

    # Gate 6: capacity
    if sheet["booked_sqft"] + (wo["quoted_area_sqft"] or 0) > sheet["capacity_sqft"]:
        raise err(ERR_ROUTE_CAPACITY_EXCEEDED, 409,
                  "booked_sqft + candidate area > capacity_sqft")
    # Gate 7: drive limit
    if sheet["total_drive_minutes"] + drive > 180:
        raise err(ERR_ROUTE_DRIVE_LIMIT_EXCEEDED, 409,
                  "total_drive_minutes + candidate drive > 180")
    # Gate 8: crew window overlap
    _check_window_overlap(sheet["id"], ws, we, exclude_wo_id=wo["id"] if is_reschedule else None)
    # Gate 9: access overlap — compute provisional block
    provisional_cure = cure_hours(material, scheduled_date)
    block_start = date_at_hour_utc(scheduled_date, ws)
    block_end = format_iso_ms(parse_iso(date_at_hour_utc(scheduled_date, we)) + timedelta(hours=provisional_cure))
    _check_access_overlap(wo["property_id"], block_start, block_end,
                          exclude_wo_id=wo["id"] if is_reschedule else None)

    # Gate 10: material lot
    lot_id = body.get("material_lot_id")
    if not is_reschedule:
        require_fields(body, ["material_lot_id"])
        lot_id = body["material_lot_id"]
    else:
        # reschedule: PRD lists input without material_lot_id (carries over)
        # scaffold endpoint input is [route_sheet_id, scheduled_date, window_start_hour,
        # window_end_hour, drive_minutes_est, expected_work_order_version]
        # so material_lot_id comes from the existing WO
        lot_id = wo["material_lot_id"]
    lot = DB.material_lots.get(lot_id)
    if lot is None:
        raise err(ERR_MATERIAL_LOT_NOT_FOUND, 404, "Material lot id does not exist")
    if lot["status"] not in ("RECEIVED", "IN_USE"):
        raise err(ERR_MATERIAL_LOT_UNAVAILABLE, 409, "Lot QUARANTINED or DEPLETED when referenced")
    # Material match: the lot's material must equal the quote's material
    quote = DB.quotes.get(wo["quote_id"]) if wo["quote_id"] else None
    if wo["warranty_claim_id"] is not None:
        # warranty repair — use original WO's quote for material
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        orig_wo = None
        if claim and claim.get("warranty_record_id"):
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec:
                orig_wo = DB.work_orders.get(rec["work_order_id"])
        if orig_wo is not None:
            quote = DB.quotes.get(orig_wo["quote_id"])
    expected_material_id = quote["material_id"] if quote else None
    if expected_material_id is not None and lot["material_id"] != expected_material_id:
        raise err(ERR_INSUFFICIENT_MATERIAL, 422,
                  "lot.material_id does not match the quote's material")
    gallons_needed = material_gallons_required(
        wo["quoted_area_sqft"], wo["coats"], material["coverage_sqft_per_gallon"],
        wo["include_seal"],
    )
    if lot["on_hand_gallons"] < gallons_needed:
        raise err(ERR_INSUFFICIENT_MATERIAL, 422,
                  "on_hand_gallons below required gallons at schedule")

    return sheet, lot, scheduled_date, ws, we, drive, vehicles


# -------------------- schedule --------------------

@bp.post("/api/work-orders/<workOrderId>/schedule")
def schedule_work_order(workOrderId):
    require_role("Dispatcher")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["execution_status"] != "PENDING":
        raise err(ERR_WORK_ORDER_NOT_SCHEDULABLE, 409,
                  "schedule/reschedule requires PENDING or WEATHER_HOLD respectively")
    body = get_json_body()
    check_unknown_fields(body, {"route_sheet_id", "material_lot_id", "scheduled_date",
                                 "window_start_hour", "window_end_hour",
                                 "drive_minutes_est", "vehicles_to_move"})
    require_fields(body, ["route_sheet_id", "material_lot_id", "scheduled_date",
                          "window_start_hour", "window_end_hour", "drive_minutes_est",
                          "vehicles_to_move"])
    # Resolve material
    quote = DB.quotes.get(wo["quote_id"]) if wo["quote_id"] else None
    if wo["warranty_claim_id"] is not None:
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        orig_wo = None
        if claim and claim.get("warranty_record_id"):
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec:
                orig_wo = DB.work_orders.get(rec["work_order_id"])
        if orig_wo is not None:
            quote = DB.quotes.get(orig_wo["quote_id"])
    material = DB.materials.get(quote["material_id"]) if quote else None

    sheet, lot, scheduled_date, ws, we, drive, vehicles = _schedule_gates(
        wo, body, material, is_reschedule=False)
    vehicles = body["vehicles_to_move"]

    _apply_booking(wo, sheet, lot, scheduled_date, ws, we, drive, vehicles, material)

    # If this is a warranty-repair WO, move claim APPROVED -> REPAIR_SCHEDULED
    if wo["warranty_claim_id"] is not None:
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        if claim is not None and claim["status"] == "APPROVED":
            claim["status"] = "REPAIR_SCHEDULED"
            touch(claim)

    return success_object(serialize_work_order(wo))


# -------------------- reschedule --------------------

@bp.post("/api/work-orders/<workOrderId>/reschedule")
def reschedule_work_order(workOrderId):
    require_role("Dispatcher")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["execution_status"] != "WEATHER_HOLD":
        raise err(ERR_WORK_ORDER_NOT_SCHEDULABLE, 409,
                  "schedule/reschedule requires PENDING or WEATHER_HOLD respectively")
    body = get_json_body()
    check_unknown_fields(body, {"route_sheet_id", "scheduled_date", "window_start_hour",
                                 "window_end_hour", "drive_minutes_est",
                                 "expected_work_order_version"})
    require_fields(body, ["route_sheet_id", "scheduled_date", "window_start_hour",
                          "window_end_hour", "drive_minutes_est",
                          "expected_work_order_version"])
    expected = body["expected_work_order_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_INVALID_REQUEST, 400, "expected_work_order_version must be an integer")

    # Resolve material
    quote = DB.quotes.get(wo["quote_id"]) if wo["quote_id"] else None
    if wo["warranty_claim_id"] is not None:
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        orig_wo = None
        if claim and claim.get("warranty_record_id"):
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec:
                orig_wo = DB.work_orders.get(rec["work_order_id"])
        if orig_wo is not None:
            quote = DB.quotes.get(orig_wo["quote_id"])
    material = DB.materials.get(quote["material_id"]) if quote else None

    # Run all gates (uses existing material_lot_id)
    sheet, lot, scheduled_date, ws, we, drive, _vehicles = _schedule_gates(
        wo, body, material, is_reschedule=True)

    # OCC after all other gates per PRD priority ordering (OCC is priority 11, last)
    if expected != wo["version"]:
        raise err(ERR_STALE_VERSION, 412,
                  "expected_work_order_version does not match the work order's current version")

    # Release old booking + reservation
    old_plan = find_displacement_plan_for_work_order(wo["id"])
    _release_booking(wo)

    # Apply new booking; carry over vehicles_to_move from before
    vehicles = wo["vehicles_to_move"] if wo["vehicles_to_move"] is not None else 0
    # Remove old plan; _apply_booking creates a new one. Per PRD the plan's window is
    # recomputed and it resets to NOTICE_PENDING with notice_sent_at cleared.
    if old_plan is not None:
        # Reuse existing plan: recompute window and reset
        provisional_cure = cure_hours(material, scheduled_date)
        abs_start = date_at_hour_utc(scheduled_date, ws)
        abs_end = format_iso_ms(parse_iso(date_at_hour_utc(scheduled_date, we)) + timedelta(hours=provisional_cure))
        old_plan["access_block_start"] = abs_start
        old_plan["access_block_end"] = abs_end
        if old_plan["status"] in ("NOTICE_SENT", "CLEARED", "STALE"):
            old_plan["status"] = "NOTICE_PENDING"
            old_plan["notice_sent_at"] = None
        touch(old_plan)
        # Apply booking WITHOUT creating a new plan
        gallons = material_gallons_required(
            wo["quoted_area_sqft"], wo["coats"], material["coverage_sqft_per_gallon"],
            wo["include_seal"],
        )
        wo["route_sheet_id"] = sheet["id"]
        wo["material_lot_id"] = lot["id"]
        wo["scheduled_date"] = scheduled_date
        wo["window_start_hour"] = ws
        wo["window_end_hour"] = we
        wo["drive_minutes_est"] = drive
        wo["reserved_gallons"] = gallons
        wo["execution_status"] = "SCHEDULED"
        touch(wo)
        lot["reserved_gallons"] = lot["reserved_gallons"] + gallons
        if lot["status"] == "RECEIVED":
            lot["status"] = "IN_USE"
        refresh_material_lot(lot)
        refresh_route_sheet(sheet)
    else:
        _apply_booking(wo, sheet, lot, scheduled_date, ws, we, drive, vehicles, material)

    return success_object(serialize_work_order(wo))


# -------------------- start --------------------

@bp.post("/api/work-orders/<workOrderId>/start")
def start_work_order(workOrderId):
    require_role("CrewLead")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["execution_status"] != "SCHEDULED":
        raise err(ERR_WORK_ORDER_NOT_STARTABLE, 409, "start requires SCHEDULED")
    # Current clock date must equal scheduled_date
    if str(today_date()) != wo["scheduled_date"]:
        raise err(ERR_DATE_IN_PAST, 422,
                  "start attempted on a date other than scheduled_date")
    # Displacement plan must be CLEARED
    plan = find_displacement_plan_for_work_order(wo["id"])
    if plan is None or plan["status"] != "CLEARED":
        raise err(ERR_DISPLACEMENT_NOT_CLEARED, 409,
                  "start requires DisplacementPlan in CLEARED")
    # Weather gate re-run
    quote = DB.quotes.get(wo["quote_id"]) if wo["quote_id"] else None
    if wo["warranty_claim_id"] is not None:
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        orig_wo = None
        if claim and claim.get("warranty_record_id"):
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec:
                orig_wo = DB.work_orders.get(rec["work_order_id"])
        if orig_wo is not None:
            quote = DB.quotes.get(orig_wo["quote_id"])
    material = DB.materials.get(quote["material_id"]) if quote else None
    weather_gate(material, wo["scheduled_date"])
    # Lot must still be usable
    lot = DB.material_lots.get(wo["material_lot_id"])
    if lot is None:
        raise err(ERR_MATERIAL_LOT_NOT_FOUND, 404, "Material lot id does not exist")
    if lot["status"] not in ("RECEIVED", "IN_USE"):
        raise err(ERR_MATERIAL_LOT_UNAVAILABLE, 409,
                  "Lot QUARANTINED or DEPLETED when referenced")
    wo["execution_status"] = "IN_PROGRESS"
    wo["started_at"] = now_iso_ms()
    touch(wo)
    return success_object(serialize_work_order(wo))


# -------------------- finish-application --------------------

@bp.post("/api/work-orders/<workOrderId>/finish-application")
def finish_application(workOrderId):
    require_role("CrewLead")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["execution_status"] != "IN_PROGRESS":
        raise err(ERR_WORK_ORDER_NOT_FINISHABLE, 409,
                  "finish-application requires IN_PROGRESS; complete requires CURING; mark-applied requires CURING/COMPLETED execution")
    body = get_json_body()
    check_unknown_fields(body, {"actual_area_sqft", "actual_crack_ft",
                                 "actual_pothole_area_sqft", "actual_stripe_ft",
                                 "gallons_used"})
    require_fields(body, ["actual_area_sqft", "actual_crack_ft",
                          "actual_pothole_area_sqft", "actual_stripe_ft", "gallons_used"])
    actual_area = require_number(body, "actual_area_sqft", ge=0)
    actual_crack = require_number(body, "actual_crack_ft", ge=0)
    actual_pothole = require_number(body, "actual_pothole_area_sqft", ge=0)
    actual_stripe = require_number(body, "actual_stripe_ft", ge=0)
    gallons_used = require_number(body, "gallons_used", ge=0)
    if gallons_used > (wo["reserved_gallons"] or 0):
        raise err(ERR_INSUFFICIENT_MATERIAL, 422,
                  "gallons_used above the reservation at finish")

    wo["actual_area_sqft"] = actual_area
    wo["actual_crack_ft"] = actual_crack
    wo["actual_pothole_area_sqft"] = actual_pothole
    wo["actual_stripe_ft"] = actual_stripe
    wo["gallons_used"] = gallons_used
    finished_at = now()
    wo["finished_at"] = format_iso_ms(finished_at)
    # Observed-variant cure projection: keyed to finish date's latest snapshot
    quote = DB.quotes.get(wo["quote_id"]) if wo["quote_id"] else None
    if wo["warranty_claim_id"] is not None:
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        orig_wo = None
        if claim and claim.get("warranty_record_id"):
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec:
                orig_wo = DB.work_orders.get(rec["work_order_id"])
        if orig_wo is not None:
            quote = DB.quotes.get(orig_wo["quote_id"])
    material = DB.materials.get(quote["material_id"]) if quote else None
    finish_date_str = finished_at.date().strftime("%Y-%m-%d")
    hours = cure_hours(material, finish_date_str)
    cure_until = finished_at + timedelta(hours=hours)
    wo["cure_until"] = format_iso_ms(cure_until)
    # Finalize displacement plan access_block_end
    plan = find_displacement_plan_for_work_order(wo["id"])
    if plan is not None:
        plan["access_block_end"] = wo["cure_until"]
        touch(plan)
    # Lot ledger settles
    lot = DB.material_lots.get(wo["material_lot_id"])
    if lot is not None:
        lot["reserved_gallons"] = max(0, lot["reserved_gallons"] - (wo["reserved_gallons"] or 0))
        lot["consumed_gallons"] = lot["consumed_gallons"] + gallons_used
        refresh_material_lot(lot)
    wo["reserved_gallons"] = 0
    wo["execution_status"] = "CURING"
    touch(wo)
    return success_object(serialize_work_order(wo))


# -------------------- complete --------------------

@bp.post("/api/work-orders/<workOrderId>/complete")
def complete_work_order(workOrderId):
    require_role("CrewLead")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["execution_status"] != "CURING":
        raise err(ERR_WORK_ORDER_NOT_FINISHABLE, 409,
                  "finish-application requires IN_PROGRESS; complete requires CURING; mark-applied requires CURING/COMPLETED execution")
    if wo["cure_until"] is None or now() < parse_iso(wo["cure_until"]):
        raise err(ERR_CURE_INCOMPLETE, 422, "complete attempted before cure_until")
    if wo["include_striping"] and wo["striping_status"] != "VERIFIED":
        raise err(ERR_STRIPING_NOT_VERIFIED, 409,
                  "complete requires VERIFIED striping when include_striping")

    wo["execution_status"] = "COMPLETED"
    wo["completed_at"] = now_iso_ms()
    touch(wo)

    # Resolve material
    quote = DB.quotes.get(wo["quote_id"]) if wo["quote_id"] else None
    orig_wo = None
    if wo["warranty_claim_id"] is not None:
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        if claim and claim.get("warranty_record_id"):
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec:
                orig_wo = DB.work_orders.get(rec["work_order_id"])
        if orig_wo is not None:
            quote = DB.quotes.get(orig_wo["quote_id"])
    material = DB.materials.get(quote["material_id"]) if quote else None

    # Create Invoice (DRAFT)
    line_items, subtotal, surcharge, total = invoice_settlement(wo, wo["material_grade"])
    inv = base_fields()
    inv.update({
        "work_order_id": wo["id"],
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "fuel_surcharge_cents": surcharge,
        "total_cents": total,
        "issued_at": None,
        "paid_at": None,
        "status": "DRAFT",
    })
    DB.invoices[inv["id"]] = inv

    if wo["warranty_claim_id"] is None:
        # Create WarrantyRecord ACTIVE
        wr = base_fields()
        completion_date = now().date()
        warranty_months = material["warranty_months"] + (6 if wo["coats"] == 2 else 0)
        wr.update({
            "work_order_id": wo["id"],
            "property_id": wo["property_id"],
            "warranty_months": warranty_months,
            "started_on": completion_date.strftime("%Y-%m-%d"),
            "expires_on": add_months(completion_date, warranty_months).strftime("%Y-%m-%d"),
            "status": "ACTIVE",
        })
        DB.warranty_records[wr["id"]] = wr

        # Update property seal cycle when include_seal
        if wo["include_seal"]:
            prop = DB.properties.get(wo["property_id"])
            if prop is not None:
                prop["last_completed_seal_on"] = wo["completed_at"]
                # next_seal_eligible_on = completion timestamp + reapplication_months
                # (PRD §3.1: "the completion timestamp plus that job's material
                # reapplication_months" — the time-of-day is preserved).
                completed_dt = parse_iso(wo["completed_at"])
                eligible_d = add_months(completed_dt.date(), material["reapplication_months"])
                prop["next_seal_eligible_on"] = format_iso_ms(
                    completed_dt.replace(year=eligible_d.year, month=eligible_d.month,
                                         day=eligible_d.day))
                touch(prop)
    else:
        # Warranty repair: resolve the claim, exhaust the record
        claim = DB.warranty_claims.get(wo["warranty_claim_id"])
        if claim is not None and claim["status"] == "REPAIR_SCHEDULED":
            claim["status"] = "RESOLVED"
            touch(claim)
            rec = DB.warranty_records.get(claim["warranty_record_id"])
            if rec is not None and rec["status"] == "CLAIM_OPEN":
                rec["status"] = "EXHAUSTED"
                touch(rec)

    return success_object(serialize_work_order(wo))


# -------------------- cancel --------------------

@bp.post("/api/work-orders/<workOrderId>/cancel")
def cancel_work_order(workOrderId):
    require_role("Dispatcher")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["execution_status"] not in ("PENDING", "SCHEDULED", "WEATHER_HOLD"):
        raise err(ERR_WORK_ORDER_NOT_CANCELLABLE, 409,
                  "cancel requires PENDING, SCHEDULED, or WEATHER_HOLD")
    # Compensation cascade
    if wo["route_sheet_id"] or wo["material_lot_id"]:
        _release_booking(wo)
    # Displacement plan -> CANCELLED
    plan = find_displacement_plan_for_work_order(wo["id"])
    if plan is not None:
        plan["status"] = "CANCELLED"
        touch(plan)
    wo["execution_status"] = "CANCELLED"
    touch(wo)
    return success_object(serialize_work_order(wo))


# -------------------- striping --------------------

@bp.post("/api/work-orders/<workOrderId>/striping/plan")
def striping_plan(workOrderId):
    require_role("Estimator")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if not wo["include_striping"] or wo["striping_status"] != "PLANNING":
        raise err(ERR_STRIPING_NOT_PLANNABLE, 409,
                  "Striping action requires the matching striping_status")
    prop = DB.properties.get(wo["property_id"])
    if prop is None or prop["lot_kind"] != "COMMERCIAL_LOT":
        raise err(ERR_STRIPING_COMMERCIAL_ONLY, 422,
                  "Striping scope or striping plan on a RESIDENTIAL_DRIVEWAY property")
    body = get_json_body()
    check_unknown_fields(body, {"stall_count"})
    require_fields(body, ["stall_count"])
    stall_count = body["stall_count"]
    if not isinstance(stall_count, int) or isinstance(stall_count, bool) or stall_count < 0:
        raise err(ERR_INVALID_REQUEST, 400, "stall_count must be a non-negative integer")
    ada = ada_stall_requirement(stall_count)
    wo["stall_count"] = stall_count
    wo["ada_stalls_required"] = ada
    wo["stripe_linear_ft_computed"] = stall_count * 18 + ada * 40
    wo["striping_status"] = "PLANNED"
    touch(wo)
    return success_object(serialize_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/striping/approve")
def striping_approve(workOrderId):
    require_role("Estimator")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["striping_status"] != "PLANNED":
        raise err(ERR_STRIPING_NOT_PLANNABLE, 409,
                  "Striping action requires the matching striping_status")
    wo["striping_status"] = "APPROVED"
    touch(wo)
    return success_object(serialize_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/striping/mark-applied")
def striping_mark_applied(workOrderId):
    require_role("CrewLead")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["striping_status"] != "APPROVED":
        raise err(ERR_STRIPING_NOT_PLANNABLE, 409,
                  "Striping action requires the matching striping_status")
    if wo["execution_status"] not in ("CURING", "COMPLETED"):
        raise err(ERR_WORK_ORDER_NOT_FINISHABLE, 409,
                  "mark-applied requires CURING/COMPLETED execution")
    wo["striping_status"] = "APPLIED"
    touch(wo)
    return success_object(serialize_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/striping/verify")
def striping_verify(workOrderId):
    require_role("Estimator")
    wo = DB.work_orders.get(workOrderId)
    if wo is None:
        raise err(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order id does not exist")
    if wo["striping_status"] != "APPLIED":
        raise err(ERR_STRIPING_NOT_PLANNABLE, 409,
                  "Striping action requires the matching striping_status")
    wo["striping_status"] = "VERIFIED"
    touch(wo)
    return success_object(serialize_work_order(wo))
