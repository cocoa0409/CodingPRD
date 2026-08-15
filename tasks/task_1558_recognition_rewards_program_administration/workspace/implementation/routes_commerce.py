"""Routes: fulfillment vendors, catalog items, redemption orders, tax records
(PRD sections 3.5-3.6)."""
from datetime import timedelta

import db
import serialize as ser
import services as svc
import calc
from db import now, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_NOT_ACTIVE, ERR_EMPLOYEE_SUSPENDED, ERR_INVALID_QUANTITY,
    ERR_IDEMPOTENCY_CONFLICT, ERR_CATALOG_ITEM_UNAVAILABLE,
    ERR_ITEM_OUT_OF_STOCK, ERR_INSUFFICIENT_POINTS, ERR_VENDOR_SUSPENDED,
    ERR_RETURN_NOT_ALLOWED, ERR_FORBIDDEN_FOR_ROLE, ERR_NOT_FOUND,
)
from flask import Blueprint, request
from response import success
from validate import (
    auth_context, require_role, get_or_404, body, req_str, opt_str, req_int,
    opt_int, req_enum, opt_bool, parse_iso_datetime,
)
from routes_core import READ_ROLES, _sorted_rows, _paginate

bp = Blueprint("commerce", __name__)

TAXABLE_CLASSES = {"MERCHANDISE", "GIFT_CARD", "EXPERIENCE"}
REDEMPTION_ANOMALY_THRESHOLD = 50000


def _active_programs():
    return [p for p in db.programs.values() if p["status"] == "ACTIVE"]


def _resolve_order_program(employee):
    """Catalog is program-global: use the single ACTIVE program; when several
    exist, pin the program of the budget that granted the employee's oldest
    unexpired points."""
    actives = _active_programs()
    if not actives:
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "No ACTIVE program exists")
    if len(actives) == 1:
        return actives[0]
    for award in svc.active_awards(employee["id"]):
        p = db.programs.get(award["program_id"])
        if p is not None and p["status"] == "ACTIVE":
            return p
    return actives[0]


def _refund_held(order, emp, note):
    """Full refund of an order's escrow back to available points."""
    svc.post_ledger(emp, "REFUND", order["points_total"], "REDEMPTION_ORDER",
                    order["id"],
                    "%s:REFUND:%s" % (order["idempotency_key"], order["id"]),
                    note)
    svc.emp_refund_from_held(emp, order["points_total"])


def _restore_inventory(order):
    item = db.catalog_items.get(order["catalog_item_id"])
    if item is not None and item["inventory_quantity"] is not None:
        item["inventory_quantity"] += order["quantity"]
        touch(item)


def cancel_order_effects(order, emp, note="Order cancelled: full refund"):
    _refund_held(order, emp, note)
    _restore_inventory(order)
    order["fulfillment_status"] = "CANCELLED"
    order["escrow_status"] = "REFUNDED"
    touch(order)


# ---------------------------------------------------------------------------
# Fulfillment vendors
# ---------------------------------------------------------------------------

@bp.route("/api/vendors", methods=["POST"])
def create_vendor():
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    b = body()
    name = req_str(b, "name")
    vendor_code = req_str(b, "vendor_code")
    capacity = req_int(b, "daily_ship_capacity")
    lead = req_int(b, "lead_time_business_days")
    restocking = opt_int(b, "restocking_fee_percent", 20)
    categories = b.get("supported_categories")
    if capacity < 1:
        raise_err(ERR_INVALID_REQUEST, "daily_ship_capacity must be >= 1")
    if lead < 0:
        raise_err(ERR_INVALID_REQUEST, "lead_time_business_days must be >= 0")
    if restocking is None or restocking < 0 or restocking > 100:
        raise_err(ERR_INVALID_REQUEST,
                  "restocking_fee_percent must be between 0 and 100")
    if not isinstance(categories, list) or \
            any(not isinstance(c, str) for c in categories):
        raise_err(ERR_INVALID_REQUEST,
                  "supported_categories must be an array of strings")
    if any(v["vendor_code"] == vendor_code for v in db.vendors.values()):
        raise_err(ERR_INVALID_REQUEST,
                  "vendor_code already registered: %s" % vendor_code)
    v = {
        "id": db.new_id(),
        "name": name,
        "vendor_code": vendor_code,
        "daily_ship_capacity": capacity,
        "lead_time_business_days": lead,
        "restocking_fee_percent": restocking,
        "supported_categories": categories,
        "status": "ACTIVE",
    }
    db.stamp(v)
    db.vendors[v["id"]] = v
    return success(ser.vendor(v), 201)


@bp.route("/api/vendors/<vendorId>", methods=["GET"])
def get_vendor(vendorId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    v = get_or_404(db.vendors, vendorId, "FulfillmentVendor")
    return success(ser.vendor(v))


@bp.route("/api/vendors/<vendorId>/suspend", methods=["POST"])
def suspend_vendor(vendorId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    v = get_or_404(db.vendors, vendorId, "FulfillmentVendor")
    if v["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only ACTIVE vendors can be suspended")
    v["status"] = "SUSPENDED"
    touch(v)
    return success(ser.vendor(v))


@bp.route("/api/vendors/<vendorId>/reactivate", methods=["POST"])
def reactivate_vendor(vendorId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    v = get_or_404(db.vendors, vendorId, "FulfillmentVendor")
    if v["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only SUSPENDED vendors can be reactivated")
    v["status"] = "ACTIVE"
    touch(v)
    return success(ser.vendor(v))


# ---------------------------------------------------------------------------
# Catalog items
# ---------------------------------------------------------------------------

@bp.route("/api/catalog-items", methods=["POST"])
def create_catalog_item():
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    b = body()
    vendor_id = b.get("vendor_id")
    sku = req_str(b, "sku")
    name = req_str(b, "name")
    category = req_str(b, "category")
    point_cost = req_int(b, "point_cost")
    cash_value = req_int(b, "cash_value_cents")
    taxable_class = req_enum(b, "taxable_class", TAXABLE_CLASSES)
    de_minimis = opt_bool(b, "de_minimis_eligible", False)
    win_start = parse_iso_datetime(b.get("active_window_start"),
                                   "active_window_start")
    win_end = parse_iso_datetime(b.get("active_window_end"),
                                 "active_window_end")
    inventory = b.get("inventory_quantity")
    if point_cost <= 0:
        raise_err(ERR_INVALID_REQUEST, "point_cost must be > 0")
    if cash_value <= 0:
        raise_err(ERR_INVALID_REQUEST, "cash_value_cents must be > 0")
    if win_end <= win_start:
        raise_err(ERR_INVALID_REQUEST,
                  "active_window_end must be after active_window_start")
    if inventory is not None:
        if not isinstance(inventory, int) or isinstance(inventory, bool) \
                or inventory < 0:
            raise_err(ERR_INVALID_REQUEST,
                      "inventory_quantity must be null or a non-negative integer")
    # Existence: vendor FK.
    if not isinstance(vendor_id, str) or vendor_id not in db.vendors:
        raise_err(ERR_NOT_FOUND, "FulfillmentVendor not found: %s" % vendor_id)
    vendor = db.vendors[vendor_id]
    if category not in vendor["supported_categories"]:
        raise_err(ERR_INVALID_REQUEST,
                  "category must be in the vendor's supported_categories")
    if any(c["vendor_id"] == vendor_id and c["sku"] == sku
           for c in db.catalog_items.values()):
        raise_err(ERR_INVALID_REQUEST,
                  "sku must be unique per vendor: %s" % sku)
    # Program gate (stage 7): catalog item creation requires an ACTIVE program.
    if not _active_programs():
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "No ACTIVE program exists")
    # Referential scope (stage 11): vendor must be ACTIVE.
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_VENDOR_SUSPENDED, "Vendor is SUSPENDED")
    item = {
        "id": db.new_id(),
        "vendor_id": vendor_id,
        "sku": sku,
        "name": name,
        "category": category,
        "point_cost": point_cost,
        "cash_value_cents": cash_value,
        "taxable_class": taxable_class,
        "de_minimis_eligible": de_minimis,
        "active_window_start": win_start,
        "active_window_end": win_end,
        "inventory_quantity": inventory,
        "status": "ACTIVE",
    }
    db.stamp(item)
    db.catalog_items[item["id"]] = item
    return success(ser.catalog_item(item), 201)


@bp.route("/api/catalog-items/<catalogItemId>", methods=["GET"])
def get_catalog_item(catalogItemId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    c = get_or_404(db.catalog_items, catalogItemId, "CatalogItem")
    return success(ser.catalog_item(c))


@bp.route("/api/catalog-items", methods=["GET"])
def list_catalog_items():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.catalog_items.values())
    for param, field in (("vendor_id", "vendor_id"),
                         ("category", "category"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            rows = [c for c in rows if c[field] == v]
    return _paginate(rows, ser.catalog_item)


@bp.route("/api/catalog-items/<catalogItemId>", methods=["PATCH"])
def patch_catalog_item(catalogItemId):
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    item = get_or_404(db.catalog_items, catalogItemId, "CatalogItem")
    b = body()
    new_start = item["active_window_start"]
    new_end = item["active_window_end"]
    if "point_cost" in b and b["point_cost"] is not None:
        v = req_int(b, "point_cost")
        if v <= 0:
            raise_err(ERR_INVALID_REQUEST, "point_cost must be > 0")
        item["point_cost"] = v
    if "cash_value_cents" in b and b["cash_value_cents"] is not None:
        v = req_int(b, "cash_value_cents")
        if v <= 0:
            raise_err(ERR_INVALID_REQUEST, "cash_value_cents must be > 0")
        item["cash_value_cents"] = v
    if "active_window_start" in b and b["active_window_start"] is not None:
        new_start = parse_iso_datetime(b["active_window_start"],
                                       "active_window_start")
    if "active_window_end" in b and b["active_window_end"] is not None:
        new_end = parse_iso_datetime(b["active_window_end"],
                                     "active_window_end")
    if new_end <= new_start:
        raise_err(ERR_INVALID_REQUEST,
                  "active_window_end must be after active_window_start")
    item["active_window_start"] = new_start
    item["active_window_end"] = new_end
    if "inventory_quantity" in b:
        v = b["inventory_quantity"]
        if v is not None and (not isinstance(v, int) or isinstance(v, bool)
                              or v < 0):
            raise_err(ERR_INVALID_REQUEST,
                      "inventory_quantity must be null or a non-negative integer")
        item["inventory_quantity"] = v
    if "status" in b and b["status"] is not None:
        v = b["status"]
        if v not in ("ACTIVE", "RETIRED"):
            raise_err(ERR_INVALID_REQUEST, "Invalid status value")
        item["status"] = v
    touch(item)
    return success(ser.catalog_item(item))


# ---------------------------------------------------------------------------
# Redemption orders
# ---------------------------------------------------------------------------

@bp.route("/api/redemption-orders", methods=["POST"])
def create_redemption_order():
    user_id, role = auth_context()
    require_role(role, ["Employee"])
    b = body()
    catalog_item_id = b.get("catalog_item_id")
    idem_key = req_str(b, "idempotency_key")
    quantity = b.get("quantity", 1)
    if not isinstance(quantity, int) or isinstance(quantity, bool) \
            or quantity < 1 or quantity > 5:
        raise_err(ERR_INVALID_QUANTITY, "quantity must be between 1 and 5")
    # Existence: item FK and the acting employee.
    if not isinstance(catalog_item_id, str) \
            or catalog_item_id not in db.catalog_items:
        raise_err(ERR_NOT_FOUND, "CatalogItem not found: %s" % catalog_item_id)
    item = db.catalog_items[catalog_item_id]
    emp = db.employees.get(user_id)
    if emp is None:
        raise_err(ERR_NOT_FOUND, "Acting employee not found: %s" % user_id)
    # Program gate (stage 7) + program resolution.
    program = _resolve_order_program(emp)
    # Employee standing (stage 8).
    if emp["program_status"] != "ELIGIBLE":
        raise_err(ERR_EMPLOYEE_SUSPENDED, "Redeeming employee is SUSPENDED")
    # Duplicates (stage 12): idempotency replay/conflict.
    payload = {"catalog_item_id": catalog_item_id, "quantity": quantity}
    for o in db.orders.values():
        if o["employee_id"] == emp["id"] and o["idempotency_key"] == idem_key:
            if o["_payload"] == payload:
                return success(ser.redemption_order(o), 201)
            raise_err(ERR_IDEMPOTENCY_CONFLICT,
                      "idempotency_key reused with a different payload")
    # Temporal (stage 13): item ACTIVE and inside its half-open window.
    if item["status"] != "ACTIVE" or not (
            item["active_window_start"] <= now() < item["active_window_end"]):
        raise_err(ERR_CATALOG_ITEM_UNAVAILABLE,
                  "Catalog item is not available at the current time")
    # Inventory (stage 14).
    if item["inventory_quantity"] is not None \
            and item["inventory_quantity"] < quantity:
        raise_err(ERR_ITEM_OUT_OF_STOCK, "Insufficient inventory")
    # Balance (stage 17).
    points_total = item["point_cost"] * quantity
    if emp["available_points"] < points_total:
        raise_err(ERR_INSUFFICIENT_POINTS,
                  "available_points %d < points_total %d"
                  % (emp["available_points"], points_total))
    # Commit: HOLD escrow, decrement inventory, quiet abuse guard.
    order = {
        "id": db.new_id(),
        "employee_id": emp["id"],
        "program_id": program["id"],
        "catalog_item_id": item["id"],
        "quantity": quantity,
        "points_total": points_total,
        "fulfillment_status": "PENDING_SUBMISSION",
        "escrow_status": "HELD",
        "ship_date": None,
        "idempotency_key": idem_key,
        "tax_record_id": None,
        "restocking_fee_points": 0,
        "delivered_at": None,
        "_payload": payload,
    }
    db.stamp(order)
    db.orders[order["id"]] = order
    svc.post_ledger(emp, "HOLD", -points_total, "REDEMPTION_ORDER", order["id"],
                    "%s:HOLD:%s" % (idem_key, order["id"]),
                    "Escrow hold of %d points for order" % points_total)
    svc.emp_hold(emp, points_total)
    if item["inventory_quantity"] is not None:
        item["inventory_quantity"] -= quantity
        touch(item)
    if points_total > REDEMPTION_ANOMALY_THRESHOLD:
        svc.raise_system_flag(emp["id"], program["id"], "REDEMPTION_ANOMALY",
                              {"redemption_order_id": order["id"],
                               "points_total": points_total})
    return success(ser.redemption_order(order), 201)


@bp.route("/api/redemption-orders/<redemptionOrderId>", methods=["GET"])
def get_redemption_order(redemptionOrderId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    return success(ser.redemption_order(o))


@bp.route("/api/redemption-orders", methods=["GET"])
def list_redemption_orders():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.orders.values())
    for param, field in (("employee_id", "employee_id"),
                         ("catalog_item_id", "catalog_item_id"),
                         ("fulfillment_status", "fulfillment_status"),
                         ("escrow_status", "escrow_status"),
                         ("program_id", "program_id")):
        v = request.args.get(param)
        if v is not None:
            rows = [o for o in rows if o[field] == v]
    return _paginate(rows, ser.redemption_order)


@bp.route("/api/redemption-orders/<redemptionOrderId>/submit", methods=["POST"])
def submit_order(redemptionOrderId):
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    if o["fulfillment_status"] != "PENDING_SUBMISSION":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only PENDING_SUBMISSION orders can be submitted")
    item = db.catalog_items[o["catalog_item_id"]]
    vendor = db.vendors[item["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_VENDOR_SUSPENDED, "Vendor is SUSPENDED")
    o["ship_date"] = calc.assign_ship_date(vendor)
    o["fulfillment_status"] = "SUBMITTED"
    touch(o)
    return success(ser.redemption_order(o))


@bp.route("/api/redemption-orders/<redemptionOrderId>/mark-shipped", methods=["POST"])
def mark_shipped(redemptionOrderId):
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    if o["fulfillment_status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only SUBMITTED orders can be marked shipped")
    o["fulfillment_status"] = "SHIPPED"
    touch(o)
    return success(ser.redemption_order(o))


@bp.route("/api/redemption-orders/<redemptionOrderId>/mark-delivered",
          methods=["POST"])
def mark_delivered(redemptionOrderId):
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    if o["fulfillment_status"] != "SHIPPED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only SHIPPED orders can be marked delivered")
    emp = db.employees[o["employee_id"]]
    item = db.catalog_items[o["catalog_item_id"]]
    program = db.programs[o["program_id"]]
    # Settlement: escrow HELD -> SETTLED, FIFO award consumption, TaxRecord.
    svc.post_ledger(emp, "SETTLE_REDEEM", -o["points_total"],
                    "REDEMPTION_ORDER", o["id"],
                    "%s:SETTLE_REDEEM:%s" % (o["idempotency_key"], o["id"]),
                    "Settlement of %d held points" % o["points_total"])
    svc.emp_settle(emp, o["points_total"])
    svc.consume_awards_fifo(emp, o["points_total"])
    order_value = item["cash_value_cents"] * o["quantity"]
    applied = calc.de_minimis(item, emp, order_value)
    if applied:
        taxable = 0
        emp["ytd_de_minimis_cents"] += order_value
        touch(emp)
    else:
        taxable = order_value
    fed = calc.federal_rate(emp)
    state = calc.state_rate(program, emp)
    gross_up = calc.gross_up_cents(program, emp, taxable)
    tax = {
        "id": db.new_id(),
        "employee_id": emp["id"],
        "program_id": program["id"],
        "redemption_order_id": o["id"],
        "tax_year": now().year,
        "taxable_value_cents": taxable,
        "de_minimis_applied": applied,
        "federal_rate_applied": float(fed),
        "state_rate_applied": float(state),
        "estimated_gross_up_cents": gross_up,
        "final_gross_up_cents": None,
        "delta_cents": None,
        "employer_cost_cents": taxable + gross_up,
        "status": "ESTIMATED",
    }
    db.stamp(tax)
    db.tax_records[tax["id"]] = tax
    o["tax_record_id"] = tax["id"]
    o["fulfillment_status"] = "DELIVERED"
    o["escrow_status"] = "SETTLED"
    o["delivered_at"] = now()
    touch(o)
    return success(ser.redemption_order(o))


@bp.route("/api/redemption-orders/<redemptionOrderId>/cancel", methods=["POST"])
def cancel_order(redemptionOrderId):
    user_id, role = auth_context()
    require_role(role, ["Employee", "HRAdmin"])
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    if role == "Employee" and user_id != o["employee_id"]:
        raise_err(ERR_FORBIDDEN_FOR_ROLE,
                  "Employees may only cancel their own orders")
    if o["fulfillment_status"] not in ("PENDING_SUBMISSION", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only PENDING_SUBMISSION or SUBMITTED orders can be cancelled")
    emp = db.employees[o["employee_id"]]
    cancel_order_effects(o, emp)
    return success(ser.redemption_order(o))


@bp.route("/api/redemption-orders/<redemptionOrderId>/request-return",
          methods=["POST"])
def request_return(redemptionOrderId):
    user_id, role = auth_context()
    require_role(role, ["Employee"])
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    if user_id != o["employee_id"]:
        raise_err(ERR_FORBIDDEN_FOR_ROLE,
                  "Employees may only request returns on their own orders")
    if o["fulfillment_status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only DELIVERED orders can be returned")
    item = db.catalog_items[o["catalog_item_id"]]
    if item["taxable_class"] == "GIFT_CARD":
        raise_err(ERR_RETURN_NOT_ALLOWED, "Gift cards are not returnable")
    if now() > o["delivered_at"] + timedelta(days=14):
        raise_err(ERR_RETURN_NOT_ALLOWED,
                  "Return window (14 days from delivery) has passed")
    o["fulfillment_status"] = "RETURN_REQUESTED"
    touch(o)
    return success(ser.redemption_order(o))


@bp.route("/api/redemption-orders/<redemptionOrderId>/complete-return",
          methods=["POST"])
def complete_return(redemptionOrderId):
    _, role = auth_context()
    require_role(role, ["VendorOps"])
    o = get_or_404(db.orders, redemptionOrderId, "RedemptionOrder")
    if o["fulfillment_status"] != "RETURN_REQUESTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only RETURN_REQUESTED orders can complete a return")
    emp = db.employees[o["employee_id"]]
    item = db.catalog_items[o["catalog_item_id"]]
    vendor = db.vendors[item["vendor_id"]]
    fee = (o["points_total"] * vendor["restocking_fee_percent"]) // 100
    refund = o["points_total"] - fee
    svc.post_ledger(emp, "REFUND", refund, "REDEMPTION_ORDER", o["id"],
                    "%s:REFUND:%s" % (o["idempotency_key"], o["id"]),
                    "Return refund of %d points" % refund)
    svc.emp_refund_to_available(emp, refund)
    svc.post_ledger(emp, "RESTOCKING_FEE", -fee, "REDEMPTION_ORDER", o["id"],
                    "%s:RESTOCKING_FEE:%s" % (o["idempotency_key"], o["id"]),
                    "Restocking fee of %d points" % fee)
    svc.emp_restocking_fee(emp, fee)
    o["restocking_fee_points"] = fee
    o["fulfillment_status"] = "RETURNED"
    o["escrow_status"] = "SETTLED_WITH_FEE"
    # Correct the linked tax record; inventory is NOT restored on returns.
    tax = db.tax_records.get(o["tax_record_id"])
    if tax is not None:
        if tax["status"] == "ESTIMATED":
            tax["status"] = "VOIDED"
            touch(tax)
        elif tax["status"] == "FINALIZED":
            tax["status"] = "AMENDED"
            tax["taxable_value_cents"] = 0
            tax["delta_cents"] = 0 - tax["estimated_gross_up_cents"]
            touch(tax)
    touch(o)
    return success(ser.redemption_order(o))


# ---------------------------------------------------------------------------
# Tax records
# ---------------------------------------------------------------------------

@bp.route("/api/tax-records/<taxRecordId>", methods=["GET"])
def get_tax_record(taxRecordId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    t = get_or_404(db.tax_records, taxRecordId, "TaxRecord")
    return success(ser.tax_record(t))


@bp.route("/api/tax-records", methods=["GET"])
def list_tax_records():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.tax_records.values())
    for param, field in (("employee_id", "employee_id"),
                         ("program_id", "program_id"),
                         ("redemption_order_id", "redemption_order_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            rows = [t for t in rows if t[field] == v]
    year = request.args.get("tax_year")
    if year is not None:
        try:
            year_i = int(year)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "tax_year must be an integer")
        rows = [t for t in rows if t["tax_year"] == year_i]
    return _paginate(rows, ser.tax_record)
