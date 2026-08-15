"""Vaccine orders, order lines, allocation receipts (PRD §3.5)."""

from flask import Blueprint, request

import db
from errors import (
    invalid_state, invalid_request, stale_version, ApiError,
    ERR_EMPTY_ORDER, ERR_SITE_SUSPENDED_ORDERING, ERR_LINE_ALLOCATION_MISSING,
    ERR_ALLOCATION_MISMATCH, ERR_STORAGE_UNIT_QUARANTINED, ERR_UNIT_SITE_MISMATCH,
    ERR_OVER_RECEIPT,
)
from middleware import get_auth, ALL_ROLES, ROLE_VACCINE_MANAGER, ROLE_STATE_PROGRAM_OFFICER
from response import success_object, paginate
from services.ledger import recompute_accountability_balance
from services.validate import (
    require_body, require_string, require_int, require_date, get_or_404,
)

bp = Blueprint("orders", __name__)


def serialize_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "provider_site_id": o["provider_site_id"],
        "order_number": o["order_number"],
        "submitted_by_user_id": o["submitted_by_user_id"],
        "status": o["status"],
        "expected_vfc_doses": o["expected_vfc_doses"],
        "approved_vfc_doses": o["approved_vfc_doses"],
        "received_vfc_doses": o["received_vfc_doses"],
    }


def serialize_line(line):
    return {
        "id": line["id"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
        "vaccine_order_id": line["vaccine_order_id"],
        "vaccine_product_id": line["vaccine_product_id"],
        "requested_doses": line["requested_doses"],
        "approved_doses": line["approved_doses"],
        "received_doses": line["received_doses"],
    }


def serialize_receipt(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "vaccine_order_id": r["vaccine_order_id"],
        "order_line_id": r["order_line_id"],
        "storage_unit_id": r["storage_unit_id"],
        "lot_number": r["lot_number"],
        "expires_on": r["expires_on"],
        "quantity_doses": r["quantity_doses"],
        "lot_id": r["lot_id"],
    }


def _get_site_order(site_id, order_id):
    site = get_or_404(db.provider_sites, site_id, "provider site")
    order = get_or_404(db.vaccine_orders, order_id, "vaccine order")
    if order["provider_site_id"] != site["id"]:
        from errors import not_found
        raise not_found("vaccine order")
    return site, order


@bp.route("/provider-sites/<site_id>/vaccine-orders", methods=["POST"])
def create_order(site_id):
    user_id = get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    expected_vfc_doses = require_int(body, "expected_vfc_doses", minimum=1)

    now = db.now_ts()
    order = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "order_number": db.next_order_number(site["id"]),
        "submitted_by_user_id": user_id,
        "status": "DRAFT",
        "expected_vfc_doses": expected_vfc_doses,
        "approved_vfc_doses": 0,
        "received_vfc_doses": 0,
    }
    db.vaccine_orders[order["id"]] = order
    return success_object(serialize_order(order), 201)


def _filter_orders(items, args):
    f_site = args.get("provider_site_id")
    f_status = args.get("status")
    if f_site is not None:
        items = [o for o in items if o["provider_site_id"] == f_site]
    if f_status is not None:
        items = [o for o in items if o["status"] == f_status]
    return items


@bp.route("/provider-sites/<site_id>/vaccine-orders", methods=["GET"])
def list_orders(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [o for o in db.vaccine_orders.values() if o["provider_site_id"] == site["id"]]
    items = _filter_orders(items, request.args)
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    return paginate([serialize_order(o) for o in items], request.args)


@bp.route("/vaccine-orders", methods=["GET"])
def list_orders_global():
    get_auth(ALL_ROLES)
    items = list(db.vaccine_orders.values())
    items = _filter_orders(items, request.args)
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    return paginate([serialize_order(o) for o in items], request.args)


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>", methods=["GET"])
def get_order(site_id, order_id):
    get_auth(ALL_ROLES)
    _, order = _get_site_order(site_id, order_id)
    return success_object(serialize_order(order))


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/lines", methods=["POST"])
def create_order_line(site_id, order_id):
    get_auth([ROLE_VACCINE_MANAGER])
    _, order = _get_site_order(site_id, order_id)
    if order["status"] != "DRAFT":
        raise invalid_state("Order must be DRAFT to add lines")
    body = require_body(request.get_json(silent=True))
    vaccine_product_id = require_string(body, "vaccine_product_id")
    requested_doses = require_int(body, "requested_doses", minimum=1)
    product = get_or_404(db.vaccine_products, vaccine_product_id, "vaccine product")

    now = db.now_ts()
    line = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "vaccine_order_id": order["id"],
        "vaccine_product_id": product["id"],
        "requested_doses": requested_doses,
        "approved_doses": None,
        "received_doses": 0,
    }
    db.order_lines[line["id"]] = line
    return success_object(serialize_line(line), 201)


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/lines", methods=["GET"])
def list_order_lines(site_id, order_id):
    get_auth(ALL_ROLES)
    _, order = _get_site_order(site_id, order_id)
    items = [l for l in db.order_lines.values() if l["vaccine_order_id"] == order["id"]]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize_line(l) for l in items], request.args)


@bp.route("/order-lines", methods=["GET"])
def list_order_lines_global():
    get_auth(ALL_ROLES)
    items = list(db.order_lines.values())
    f_order = request.args.get("vaccine_order_id")
    f_product = request.args.get("vaccine_product_id")
    if f_order is not None:
        items = [l for l in items if l["vaccine_order_id"] == f_order]
    if f_product is not None:
        items = [l for l in items if l["vaccine_product_id"] == f_product]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return paginate([serialize_line(l) for l in items], request.args)


@bp.route("/order-lines/<line_id>", methods=["GET"])
def get_order_line(line_id):
    get_auth(ALL_ROLES)
    line = get_or_404(db.order_lines, line_id, "order line")
    return success_object(serialize_line(line))


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/submit", methods=["POST"])
def submit_order(site_id, order_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, order = _get_site_order(site_id, order_id)
    if order["status"] != "DRAFT":
        raise invalid_state("Order must be DRAFT to submit")
    lines = [l for l in db.order_lines.values() if l["vaccine_order_id"] == order["id"]]
    if not lines:
        raise ApiError(ERR_EMPTY_ORDER, "Order submission requires at least one OrderLine", 422)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_SUSPENDED_ORDERING,
                       "Site is in SUSPENDED_ORDERING; order submission forbidden", 409)
    order["status"] = "SUBMITTED"
    order["updated_at"] = db.now_ts()
    order["version"] += 1
    return success_object(serialize_order(order))


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/approve", methods=["POST"])
def approve_order(site_id, order_id):
    get_auth([ROLE_STATE_PROGRAM_OFFICER])
    site, order = _get_site_order(site_id, order_id)
    body = require_body(request.get_json(silent=True))

    # Parse OCC + allocation fields (presence/type checks are request validation)
    if "expected_provider_site_version" not in body or body["expected_provider_site_version"] is None:
        raise invalid_request("Missing required field: expected_provider_site_version")
    expected_site_version = body["expected_provider_site_version"]
    if isinstance(expected_site_version, bool) or not isinstance(expected_site_version, int):
        raise invalid_request("Field expected_provider_site_version must be an integer")

    approved_vfc_doses = require_int(body, "approved_vfc_doses", minimum=0)

    line_allocations = body.get("line_allocations")
    if line_allocations is not None and not isinstance(line_allocations, (dict, list)):
        raise invalid_request("line_allocations must be an object or array")

    # Priority 4: OCC check (before state per §2.12 ordering)
    if expected_site_version != site["version"]:
        raise stale_version()

    # Priority 5: state check
    if order["status"] != "SUBMITTED":
        raise invalid_state("Order must be SUBMITTED to approve")

    lines = [l for l in db.order_lines.values() if l["vaccine_order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))

    # Apply line allocations: explicit map/list or proportional default.
    if line_allocations is None:
        # Proportional distribution of approved total across lines by requested_doses,
        # with any remainder going to the earliest lines one dose at a time.
        total_requested = sum(l["requested_doses"] for l in lines)
        if lines:
            if total_requested > 0:
                allocated = []
                running = 0
                for i, l in enumerate(lines):
                    if i < len(lines) - 1:
                        share = (approved_vfc_doses * l["requested_doses"]) // total_requested
                        allocated.append(share)
                        running += share
                    else:
                        allocated.append(approved_vfc_doses - running)
                for l, a in zip(lines, allocated):
                    l["approved_doses"] = a
            else:
                for l in lines:
                    l["approved_doses"] = 0
    else:
        # Normalize to a dict {line_id: approved_doses}
        alloc_map = {}
        if isinstance(line_allocations, dict):
            for k, v in line_allocations.items():
                alloc_map[k] = v
        else:
            for entry in line_allocations:
                if not isinstance(entry, dict) or "order_line_id" not in entry:
                    raise invalid_request("line_allocations entries must contain order_line_id")
                alloc_map[entry["order_line_id"]] = entry.get("approved_doses")
        for l in lines:
            if l["id"] in alloc_map:
                v = alloc_map[l["id"]]
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise invalid_request("approved_doses must be a non-negative integer")
                l["approved_doses"] = v

    # Every line must carry an approved_doses value
    if any(l["approved_doses"] is None for l in lines):
        raise ApiError(ERR_LINE_ALLOCATION_MISSING,
                       "At least one OrderLine lacks approved_doses at approval time", 422)

    # Sum must equal the order-level approved_vfc_doses
    if sum(l["approved_doses"] for l in lines) != approved_vfc_doses:
        raise ApiError(ERR_ALLOCATION_MISMATCH,
                       "Sum of OrderLine.approved_doses != VaccineOrder.approved_vfc_doses", 422)

    order["approved_vfc_doses"] = approved_vfc_doses
    order["status"] = "APPROVED"
    order["updated_at"] = db.now_ts()
    order["version"] += 1
    for l in lines:
        l["updated_at"] = db.now_ts()
        l["version"] += 1

    # Approval increments the site version by one (OCC parent mutation)
    site["updated_at"] = db.now_ts()
    site["version"] += 1

    return success_object(serialize_order(order))


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(site_id, order_id):
    get_auth([ROLE_VACCINE_MANAGER])
    _, order = _get_site_order(site_id, order_id)
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise invalid_state("Order must be DRAFT or SUBMITTED to cancel")
    order["status"] = "CANCELLED"
    order["updated_at"] = db.now_ts()
    order["version"] += 1
    return success_object(serialize_order(order))


# -------------------------- Allocation Receipts ----------------------------

@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/allocation-receipts", methods=["POST"])
def create_allocation_receipt(site_id, order_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, order = _get_site_order(site_id, order_id)
    body = require_body(request.get_json(silent=True))
    order_line_id = require_string(body, "order_line_id")
    storage_unit_id = require_string(body, "storage_unit_id")
    lot_number = require_string(body, "lot_number")
    expires_on_raw, expires_on_date = require_date(body, "expires_on")
    quantity_doses = require_int(body, "quantity_doses", minimum=1)

    # Existence
    line = get_or_404(db.order_lines, order_line_id, "order line")
    if line["vaccine_order_id"] != order["id"]:
        from errors import not_found
        raise not_found("order line")
    unit = get_or_404(db.storage_units, storage_unit_id, "storage unit")

    # Order must be in a receivable state
    if order["status"] not in ("APPROVED", "PARTIALLY_RECEIVED"):
        raise invalid_state("Order must be APPROVED or PARTIALLY_RECEIVED to post receipts")

    # Quarantine check (p6) then referential unit-site check (p12)
    if unit["active_excursion_id"] is not None:
        raise ApiError(ERR_STORAGE_UNIT_QUARANTINED, "Storage unit has an active excursion", 409)
    if unit["provider_site_id"] != site["id"]:
        raise ApiError(ERR_UNIT_SITE_MISMATCH,
                       "Storage unit does not belong to the referenced provider site", 422)

    # Over-receipt guard
    if line["received_doses"] + quantity_doses > line["approved_doses"]:
        raise ApiError(ERR_OVER_RECEIPT,
                       "AllocationReceipt would push OrderLine.received_doses above approved_doses",
                       422)

    # Create the PUBLIC_VFC lot
    now = db.now_ts()
    lot = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "storage_unit_id": unit["id"],
        "vaccine_product_id": line["vaccine_product_id"],
        "lot_number": lot_number,
        "stock_type": "PUBLIC_VFC",
        "quantity_on_hand": quantity_doses,
        "quantity_borrowed_in": 0,
        "expires_on": expires_on_raw,
        "_expires_on_date": expires_on_date,
        "status": "AVAILABLE",
        "received_via_order_id": order["id"],
        "expired_written_off_doses": 0,
    }
    db.lots[lot["id"]] = lot

    receipt = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "vaccine_order_id": order["id"],
        "order_line_id": line["id"],
        "storage_unit_id": unit["id"],
        "lot_number": lot_number,
        "expires_on": expires_on_raw,
        "quantity_doses": quantity_doses,
        "lot_id": lot["id"],
    }
    db.allocation_receipts[receipt["id"]] = receipt

    # Update line + order running totals and auto-transition the order
    line["received_doses"] += quantity_doses
    line["updated_at"] = db.now_ts()
    line["version"] += 1

    order["received_vfc_doses"] = sum(
        l["received_doses"] for l in db.order_lines.values() if l["vaccine_order_id"] == order["id"]
    )
    if order["received_vfc_doses"] == order["approved_vfc_doses"]:
        order["status"] = "FULLY_RECEIVED"
    elif order["received_vfc_doses"] > 0:
        order["status"] = "PARTIALLY_RECEIVED"
    order["updated_at"] = db.now_ts()
    order["version"] += 1

    recompute_accountability_balance(site["id"])

    return success_object(serialize_receipt(receipt), 201)


@bp.route("/provider-sites/<site_id>/vaccine-orders/<order_id>/allocation-receipts", methods=["GET"])
def list_allocation_receipts(site_id, order_id):
    get_auth(ALL_ROLES)
    _, order = _get_site_order(site_id, order_id)
    items = [r for r in db.allocation_receipts.values() if r["vaccine_order_id"] == order["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return paginate([serialize_receipt(r) for r in items], request.args)


@bp.route("/allocation-receipts/<receipt_id>", methods=["GET"])
def get_allocation_receipt(receipt_id):
    get_auth(ALL_ROLES)
    receipt = get_or_404(db.allocation_receipts, receipt_id, "allocation receipt")
    return success_object(serialize_receipt(receipt))


@bp.route("/allocation-receipts", methods=["GET"])
def list_allocation_receipts_global():
    get_auth(ALL_ROLES)
    items = list(db.allocation_receipts.values())
    f_order = request.args.get("vaccine_order_id")
    f_line = request.args.get("order_line_id")
    f_unit = request.args.get("storage_unit_id")
    f_lot = request.args.get("lot_id")
    if f_order is not None:
        items = [r for r in items if r["vaccine_order_id"] == f_order]
    if f_line is not None:
        items = [r for r in items if r["order_line_id"] == f_line]
    if f_unit is not None:
        items = [r for r in items if r["storage_unit_id"] == f_unit]
    if f_lot is not None:
        items = [r for r in items if r["lot_id"] == f_lot]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return paginate([serialize_receipt(r) for r in items], request.args)
