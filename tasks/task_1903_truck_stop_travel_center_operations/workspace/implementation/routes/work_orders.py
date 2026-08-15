"""Work orders, road service and shop parts (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_BAY_DOUBLE_BOOKED, ERR_BAY_MAINTENANCE_CONFLICT,
    ERR_BAY_OCCUPIED, ERR_CREDIT_LIMIT_EXCEEDED, ERR_FLEET_NOT_ACTIVE,
    ERR_INSUFFICIENT_STOCK, ERR_INVALID_PRICING_MODE, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_LOW_STOCK_APPROVAL_REQUIRED, ERR_NOT_FOUND,
    ERR_SHIFT_NOT_OPEN,
)
from middleware import authorized, scope_fleet, scope_technician
from response import success_object
from routes.helpers import list_from, list_response, public
from services import pricing
from services.core import new_record, recompute_stock_low, touch, adjust_shift_expected
from util import fmt_dt, parse_dt
from validate import (
    get_body, query_filter, require_path_resource, req_dt, req_int, req_str,
    valid_dt, valid_enum, valid_pos_number, req_number,
)

bp = Blueprint("work_orders", __name__)

WO_STATUSES = ["CREATED", "ESTIMATED", "APPROVED", "SCHEDULED", "IN_SHOP",
               "IN_PROGRESS", "WAITING_VENDOR", "READY_FOR_PICKUP", "CLOSED", "CANCELLED"]
NON_TERMINAL = ["CREATED", "ESTIMATED", "APPROVED", "SCHEDULED", "IN_SHOP",
                "IN_PROGRESS", "WAITING_VENDOR", "READY_FOR_PICKUP"]
READ_ROLES = ["GeneralManager", "MaintenanceTech", "ShiftManager", "Cashier"]


def _fk(collection, body, field):
    v = body.get(field)
    if v is None:
        return None
    obj = db[collection].get(v) if isinstance(v, str) else None
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"body reference {field} does not resolve: {v}")
    return obj


@bp.post("/sites/<sid>/work-orders")
def create_work_order(sid):
    authorized(["Cashier", "MaintenanceTech", "GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    fleet = _fk("fleet_accounts", body, "fleet_account_id")
    plate = req_str(body, "vehicle_plate")
    complaint = req_str(body, "complaint")
    rec = new_record("work_orders", {
        "site_id": site["id"],
        "vehicle_plate": plate,
        "complaint": complaint,
        "fleet_account_id": fleet["id"] if fleet else None,
        "technician_id": None,
        "bay_id": None,
        "scheduled_from": None,
        "scheduled_to": None,
        "status": "CREATED",
        "is_road_service": False,
        "road_location_text": None,
        "labor_hours_est": None,
        "labor_hours_actual": None,
        "parts_total_cents": None,
        "labor_total_cents": None,
        "environmental_fee_cents": None,
        "shop_supplies_cents": None,
        "invoice_total_cents": None,
        "payment_status": "UNPAID",
        "vendor_out_reason": None,
        "_pay_tender": None,
        "_vendor_out_name": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/work-orders")
def list_work_orders(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", WO_STATUSES),
        "fleet_account_id": query_filter("fleet_account_id"),
    }
    return list_response("work_orders", filters)


@bp.get("/work-orders/<rid>")
def get_work_order(rid):
    caller = authorized(READ_ROLES + ["FleetManager"])
    wo = require_path_resource("work_orders", rid)
    scope_fleet(caller, wo["fleet_account_id"])
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/estimate")
def estimate(rid):
    authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] != "CREATED":
        raise_error(ERR_INVALID_STATE, "work order is not CREATED")
    body = get_body()
    wo["labor_hours_est"] = req_number(body, "labor_hours_est", positive=True)
    wo["status"] = "ESTIMATED"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/approve-estimate")
def approve_estimate(rid):
    caller = authorized(["GeneralManager", "FleetManager"])
    wo = require_path_resource("work_orders", rid)
    scope_fleet(caller, wo["fleet_account_id"])
    if wo["status"] != "ESTIMATED":
        raise_error(ERR_INVALID_STATE, "work order is not ESTIMATED")
    if wo["fleet_account_id"] is not None:
        fleet = db["fleet_accounts"].get(wo["fleet_account_id"])
        if fleet is not None and fleet["status"] != "ACTIVE":
            raise_error(ERR_FLEET_NOT_ACTIVE, "fleet account is not ACTIVE")
    wo["status"] = "APPROVED"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/schedule")
def schedule(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    body = get_body()
    bay = _fk("bays", body, "bay_id")
    tech = _fk("technicians", body, "technician_id")
    if bay is not None and bay["site_id"] != wo["site_id"]:
        raise_error(ERR_NOT_FOUND, "bay does not belong to the work order's site")
    if tech is not None and tech["site_id"] != wo["site_id"]:
        raise_error(ERR_NOT_FOUND, "technician does not belong to the work order's site")
    if wo["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "work order is not APPROVED")
    if tech is not None and tech["status"] != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "technician is not AVAILABLE")
    from_raw = body.get("scheduled_from")
    to_raw = body.get("scheduled_to")
    if valid_dt(from_raw) and valid_dt(to_raw) and bay is not None:
        w_from = parse_dt(from_raw)
        w_to = parse_dt(to_raw)
        if w_to > w_from:
            # Half-open overlap vs non-terminal scheduled windows on the same bay
            for other in db["work_orders"].values():
                if other["bay_id"] != bay["id"] or other["id"] == wo["id"]:
                    continue
                if other["status"] not in ("SCHEDULED", "IN_SHOP", "IN_PROGRESS"):
                    continue
                o_from = parse_dt(other["scheduled_from"])
                o_to = parse_dt(other["scheduled_to"])
                if w_from < o_to and o_from < w_to:
                    raise_error(ERR_BAY_DOUBLE_BOOKED,
                                "schedule window overlaps another work order on this bay")
            # Closed-interval maintenance blocks: may not even be touched
            for block in bay["maintenance_blocks"]:
                b_from = parse_dt(block["blocked_from"])
                b_to = parse_dt(block["blocked_to"])
                if w_from <= b_to and b_from <= w_to:
                    raise_error(ERR_BAY_MAINTENANCE_CONFLICT,
                                "schedule window touches a maintenance block on this bay")
    # Final shape validation
    if bay is None:
        raise_error(ERR_INVALID_REQUEST, "bay_id is required")
    if tech is None:
        raise_error(ERR_INVALID_REQUEST, "technician_id is required")
    if not valid_dt(from_raw) or not valid_dt(to_raw):
        raise_error(ERR_INVALID_REQUEST, "scheduled_from/scheduled_to must be ISO 8601 datetimes")
    w_from = parse_dt(from_raw)
    w_to = parse_dt(to_raw)
    if w_to <= w_from:
        raise_error(ERR_INVALID_REQUEST, "scheduled_to must be after scheduled_from")
    wo["bay_id"] = bay["id"]
    wo["technician_id"] = tech["id"]
    wo["scheduled_from"] = fmt_dt(w_from)
    wo["scheduled_to"] = fmt_dt(w_to)
    wo["status"] = "SCHEDULED"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/check-in")
def check_in(rid):
    authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "work order is not SCHEDULED")
    bay = db["bays"].get(wo["bay_id"])
    if bay is None or bay["status"] != "IDLE":
        raise_error(ERR_BAY_OCCUPIED, "bay is not IDLE")
    wo["status"] = "IN_SHOP"
    touch(wo)
    bay["status"] = "OCCUPIED"
    touch(bay)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/start-work")
def start_work(rid):
    caller = authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    scope_technician(caller, wo["technician_id"])
    if wo["status"] != "IN_SHOP":
        raise_error(ERR_INVALID_STATE, "work order is not IN_SHOP")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/parts")
def issue_part(rid):
    caller = authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    scope_technician(caller, wo["technician_id"])
    body = get_body()
    item = _fk("stock_items", body, "stock_item_id")
    if wo["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "parts can be issued only while work is IN_PROGRESS")
    if item is not None and item["is_low_stock"]:
        raise_error(ERR_LOW_STOCK_APPROVAL_REQUIRED,
                    "stock item is low; replenish before issuing")
    qty = body.get("quantity")
    if item is not None and valid_int_pos(qty) and qty > item["on_hand_quantity"]:
        raise_error(ERR_INSUFFICIENT_STOCK, "quantity exceeds on-hand stock")
    if item is None:
        raise_error(ERR_INVALID_REQUEST, "stock_item_id is required")
    if not valid_int_pos(qty):
        raise_error(ERR_INVALID_REQUEST, "quantity must be a positive integer")
    item["on_hand_quantity"] -= qty
    recompute_stock_low(item)
    touch(item)
    part = new_record("work_order_parts", {
        "work_order_id": wo["id"],
        "stock_item_id": item["id"],
        "quantity": qty,
        "returned_quantity": 0,
        "unit_price_cents": item["unit_price_cents"],
        "status": "ISSUED",
    })
    return success_object(public(part), status=201)


def valid_int_pos(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


@bp.get("/work-orders/<rid>/parts")
def list_parts(rid):
    authorized(["GeneralManager", "MaintenanceTech", "Cashier"])
    wo = require_path_resource("work_orders", rid)
    parts = [p for p in db["work_order_parts"].values() if p["work_order_id"] == wo["id"]]
    return list_from(parts)


@bp.post("/work-order-parts/<rid>/return")
def return_part(rid):
    caller = authorized(["MaintenanceTech"])
    part = require_path_resource("work_order_parts", rid)
    wo = db["work_orders"].get(part["work_order_id"])
    scope_technician(caller, wo["technician_id"] if wo else None)
    if wo is None or wo["status"] not in ("IN_PROGRESS", "WAITING_VENDOR"):
        raise_error(ERR_INVALID_STATE,
                    "parts can be returned only while work is IN_PROGRESS or WAITING_VENDOR")
    body = get_body()
    qty = body.get("quantity")
    if not valid_int_pos(qty):
        raise_error(ERR_INVALID_REQUEST, "quantity must be a positive integer")
    outstanding = part["quantity"] - part["returned_quantity"]
    if qty > outstanding:
        raise_error(ERR_INVALID_REQUEST, "return quantity exceeds the issued remainder")
    part["returned_quantity"] += qty
    if part["returned_quantity"] == part["quantity"]:
        part["status"] = "RETURNED"
    touch(part)
    item = db["stock_items"].get(part["stock_item_id"])
    if item is not None:
        item["on_hand_quantity"] += qty
        recompute_stock_low(item)
        touch(item)
    return success_object(public(part))


@bp.post("/work-orders/<rid>/dispatch-road")
def dispatch_road(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    body = get_body()
    tech = _fk("technicians", body, "technician_id")
    if wo["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "work order is not APPROVED")
    if tech is not None and tech["site_id"] != wo["site_id"]:
        raise_error(ERR_NOT_FOUND, "technician does not belong to the work order's site")
    if tech is not None and tech["status"] != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "technician is not AVAILABLE")
    if tech is None:
        raise_error(ERR_INVALID_REQUEST, "technician_id is required")
    location = req_str(body, "location_text")
    wo["technician_id"] = tech["id"]
    wo["is_road_service"] = True
    wo["road_location_text"] = location
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return success_object(public(wo))


def _compute_invoice(wo):
    tech = db["technicians"].get(wo["technician_id"])
    invoice = pricing.shop_invoice(wo, tech)
    for k, v in invoice.items():
        wo[k] = v


@bp.post("/work-orders/<rid>/road-complete")
def road_complete(rid):
    authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] != "IN_PROGRESS" or not wo["is_road_service"]:
        raise_error(ERR_INVALID_STATE, "work order is not an in-progress road-service call")
    body = get_body()
    hours = body.get("labor_hours_actual")
    if not valid_pos_number(hours):
        raise_error(ERR_INVALID_REQUEST, "labor_hours_actual must be a positive number")
    wo["labor_hours_actual"] = hours
    _compute_invoice(wo)
    wo["status"] = "READY_FOR_PICKUP"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/send-to-vendor")
def send_to_vendor(rid):
    authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "work order is not IN_PROGRESS")
    if wo["is_road_service"]:
        raise_error(ERR_INVALID_STATE, "road-service work cannot be sent to an outside vendor")
    body = get_body()
    vendor_name = req_str(body, "vendor_name")
    reason = req_str(body, "reason")
    wo["vendor_out_reason"] = reason
    wo["_vendor_out_name"] = vendor_name
    wo["status"] = "WAITING_VENDOR"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/return-from-vendor")
def return_from_vendor(rid):
    authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] != "WAITING_VENDOR":
        raise_error(ERR_INVALID_STATE, "work order is not WAITING_VENDOR")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/complete-work")
def complete_work(rid):
    authorized(["MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] != "IN_PROGRESS" or wo["is_road_service"]:
        raise_error(ERR_INVALID_STATE, "work order is not in-progress bay work")
    body = get_body()
    hours = body.get("labor_hours_actual")
    if not valid_pos_number(hours):
        raise_error(ERR_INVALID_REQUEST, "labor_hours_actual must be a positive number")
    wo["labor_hours_actual"] = hours
    _compute_invoice(wo)
    wo["status"] = "READY_FOR_PICKUP"
    touch(wo)
    bay = db["bays"].get(wo["bay_id"])
    if bay is not None and bay["status"] == "OCCUPIED":
        bay["status"] = "IDLE"
        touch(bay)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/close")
def close_work_order(rid):
    authorized(["Cashier", "GeneralManager"])
    wo = require_path_resource("work_orders", rid)
    body = get_body()
    # p6: optional payload shift must resolve
    shift = None
    if body.get("shift_id") is not None:
        shift = db["shifts"].get(body["shift_id"]) if isinstance(body.get("shift_id"), str) else None
        if shift is None:
            raise_error(ERR_NOT_FOUND, "shift_id does not resolve")
    if wo["status"] != "READY_FOR_PICKUP":
        raise_error(ERR_INVALID_STATE, "work order is not READY_FOR_PICKUP")
    if wo["payment_status"] != "UNPAID":
        raise_error(ERR_INVALID_STATE, "work order payment must be UNPAID")
    tender = body.get("tender_type")
    fleet = db["fleet_accounts"].get(wo["fleet_account_id"]) \
        if wo["fleet_account_id"] else None
    if tender == "CASH":
        if shift is not None and shift["status"] != "OPEN":
            raise_error(ERR_SHIFT_NOT_OPEN, "cash close requires an OPEN shift")
    if tender == "FLEET_BILLING":
        if fleet is None:
            raise_error(ERR_INVALID_PRICING_MODE,
                        "FLEET_BILLING tender requires a fleet-billed work order")
        if fleet["status"] != "ACTIVE":
            raise_error(ERR_FLEET_NOT_ACTIVE, "fleet account is not ACTIVE")
        if fleet["current_balance_cents"] + wo["invoice_total_cents"] > fleet["credit_limit_cents"]:
            raise_error(ERR_CREDIT_LIMIT_EXCEEDED,
                        "projected balance exceeds the fleet credit limit")
    if not valid_enum(tender, ["CASH", "CARD", "FLEET_BILLING"]):
        raise_error(ERR_INVALID_REQUEST, "tender_type must be CASH, CARD or FLEET_BILLING")
    if tender == "CASH" and shift is None:
        raise_error(ERR_INVALID_REQUEST, "cash close requires shift_id")

    if tender == "FLEET_BILLING":
        wo["payment_status"] = "BILLED"
        fleet["current_balance_cents"] += wo["invoice_total_cents"]
        touch(fleet)
    else:
        wo["payment_status"] = "PAID"
        if tender == "CASH":
            adjust_shift_expected(shift, wo["invoice_total_cents"])
    wo["_pay_tender"] = tender
    wo["status"] = "CLOSED"
    touch(wo)
    return success_object(public(wo))


@bp.post("/work-orders/<rid>/cancel")
def cancel_work_order(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    wo = require_path_resource("work_orders", rid)
    if wo["status"] not in NON_TERMINAL:
        raise_error(ERR_INVALID_STATE, "work order cannot be cancelled from its current state")
    if wo["payment_status"] != "UNPAID":
        raise_error(ERR_INVALID_STATE, "only an UNPAID work order can be cancelled")
    # Return every issued part line's outstanding quantity to stock
    for part in db["work_order_parts"].values():
        if part["work_order_id"] != wo["id"]:
            continue
        outstanding = part["quantity"] - part["returned_quantity"]
        if outstanding > 0:
            item = db["stock_items"].get(part["stock_item_id"])
            if item is not None:
                item["on_hand_quantity"] += outstanding
                recompute_stock_low(item)
                touch(item)
            part["returned_quantity"] = part["quantity"]
            part["status"] = "RETURNED"
            touch(part)
    # Free the bay if this order occupies it
    if wo["bay_id"] and wo["status"] in ("IN_SHOP", "IN_PROGRESS"):
        bay = db["bays"].get(wo["bay_id"])
        if bay is not None and bay["status"] == "OCCUPIED":
            bay["status"] = "IDLE"
            touch(bay)
    wo["status"] = "CANCELLED"
    touch(wo)
    return success_object(public(wo))
