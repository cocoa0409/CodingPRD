"""InboundShipmentPlan endpoints: drafting, confirmation and the release paths."""
from flask import Blueprint, request

import calc
import clock
import db as store
import response
import serialize
import validate
from db import (RESERVING_STATUSES, db, mark_created, mark_dirty, new_row,
                order_asc, plan_lines, set_field)
from errors import ApiError
from middleware import require_fc_scope, require_roles, require_seller_scope
from routes.common import (filter_eq, finish, get_fc, get_listing, get_plan,
                           get_seller, listing_page)

bp = Blueprint("plans", __name__)

LABEL_TYPES = ("FNSKU", "MANUFACTURER_BARCODE", "NONE")
RECEIVABLE_STATUSES = ("IN_TRANSIT", "PARTIALLY_RECEIVED")


# --------------------------------------------------------------------------
# compliance rules (PRD §3.4) — ladder steps 10, 11 and 14
# --------------------------------------------------------------------------

def _check_prep(fc, line):
    if fc["prep_profile"] in ("POLYBAG_REQUIRED", "CASE_PACK_STRICT") and not line["polybagged"]:
        raise ApiError("ERR_PREP_REQUIREMENT_UNMET", 422)


def _check_label(fc, line):
    if fc["prep_profile"] in ("LABEL_ONLY", "CASE_PACK_STRICT") and line["label_type"] != "FNSKU":
        raise ApiError("ERR_LABEL_REQUIREMENT_UNMET", 422)


def _check_case_pack(fc, line):
    units = line["units"]
    case_pack = line["case_pack_units"]
    if case_pack < 1 or units < 1 or units % case_pack != 0:
        raise ApiError("ERR_CASE_PACK_VIOLATION", 422)
    if fc["prep_profile"] == "CASE_PACK_STRICT" and case_pack < fc["case_pack_min_units"]:
        raise ApiError("ERR_CASE_PACK_VIOLATION", 422)


def _windows_intersect(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection."""
    return a_start < b_end and b_start < a_end


def _effective_capacity(fc):
    capacity = fc["receiving_capacity_units_per_window"]
    if fc["receiving_status"] == "THROTTLED":
        return capacity // 2
    return capacity


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------

@bp.post("/fulfillment/inbound-shipment-plans")
@require_roles("SellerOperator")
def create_plan():
    data = validate.body()
    seller_account_id = validate.req_str(data, "seller_account_id")
    destination_fc_id = validate.req_str(data, "destination_fc_id")
    window_start = validate.req_dt(data, "appointment_window_start")
    window_end = validate.req_dt(data, "appointment_window_end")
    expected_version = validate.req_int(data, "expected_seller_account_version")

    seller = get_seller(seller_account_id)
    get_fc(destination_fc_id)
    require_seller_scope(seller_account_id)

    if expected_version != seller["version"]:
        raise ApiError("ERR_STALE_SELLER_VERSION", 412)

    if window_end <= window_start:
        raise ApiError("ERR_APPOINTMENT_WINDOW_INVALID", 422)
    if window_start < clock.now():
        raise ApiError("ERR_APPOINTMENT_WINDOW_IN_PAST", 422)

    row = new_row()
    row.update({
        "seller_account_id": seller_account_id,
        "destination_fc_id": destination_fc_id,
        "appointment_window_start": window_start,
        "appointment_window_end": window_end,
        "status": "DRAFT",
        "declared_units": 0,
        "provisional_allocated_units": 0,
        "final_allocated_units": 0,
        "allocated_units": 0,
        "allocation_status": "WITHIN_LIMIT",
        "prep_compliance_status": "PENDING",
        "received_units": 0,
        "missing_units": 0,
        "confirmed_at": None,
        "_absorb": {},
        "_contrib": {},
    })
    db.plans[row["id"]] = row
    mark_created(row)
    calc.run_provisional(row)

    # PRD §2.10: a successful plan creation increments the seller's version by 1.
    mark_dirty(seller)
    return finish(lambda: serialize.plan(row), 201)


@bp.get("/fulfillment/inbound-shipment-plans")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator")
def list_plans():
    rows = order_asc(list(db.plans.values()))
    rows = filter_eq(rows, request.args, "seller_account_id")
    rows = filter_eq(rows, request.args, "destination_fc_id")
    rows = filter_eq(rows, request.args, "status")
    return listing_page(rows, serialize.plan, request.args)


@bp.get("/fulfillment/inbound-shipment-plans/<plan_id>")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator")
def read_plan(plan_id):
    plan = get_plan(plan_id)
    return response.object_response(serialize.plan(plan), 200)


@bp.get("/fulfillment/inbound-shipment-plans/<plan_id>/line-items")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator")
def list_plan_line_items(plan_id):
    get_plan(plan_id)
    rows = plan_lines(plan_id)
    return listing_page(rows, serialize.line_item, request.args)


@bp.post("/fulfillment/inbound-shipment-plans/<plan_id>/line-items")
@require_roles("SellerOperator")
def create_line_item(plan_id):
    data = validate.body()
    sku_listing_id = validate.req_str(data, "sku_listing_id")
    units = validate.req_int(data, "units", minimum=1)
    case_pack_units = validate.req_int(data, "case_pack_units", minimum=1)
    polybagged = validate.req_bool(data, "polybagged")
    label_type = validate.req_enum(data, "label_type", LABEL_TYPES)

    plan = get_plan(plan_id)
    listing = get_listing(sku_listing_id)
    require_seller_scope(plan["seller_account_id"])

    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", 409)

    fc = get_fc(plan["destination_fc_id"])
    candidate = {
        "units": units,
        "case_pack_units": case_pack_units,
        "polybagged": polybagged,
        "label_type": label_type,
    }
    _check_prep(fc, candidate)
    _check_label(fc, candidate)
    _check_case_pack(fc, candidate)

    if listing["seller_account_id"] != plan["seller_account_id"]:
        raise ApiError("ERR_LISTING_SELLER_MISMATCH", 422)

    row = new_row()
    row.update({
        "shipment_plan_id": plan_id,
        "sku_listing_id": sku_listing_id,
        "units": units,
        "case_pack_units": case_pack_units,
        "polybagged": polybagged,
        "label_type": label_type,
        "provisional_allocated_units": 0,
        "final_allocated_units": 0,
        "received_units": 0,
        "shortfall_units": 0,
    })
    db.line_items[row["id"]] = row
    mark_created(row)

    set_field(plan, "declared_units", sum(li["units"] for li in plan_lines(plan_id)))
    calc.run_provisional(plan)
    return finish(lambda: serialize.line_item(row), 201)


@bp.post("/fulfillment/inbound-shipment-plans/<plan_id>/confirm")
@require_roles("SellerOperator")
def confirm_plan(plan_id):
    data = validate.body()
    validate.opt_str(data, "confirmation_note")

    plan = get_plan(plan_id)
    require_seller_scope(plan["seller_account_id"])

    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", 409)

    fc = get_fc(plan["destination_fc_id"])
    if fc["receiving_status"] == "SUSPENDED":
        raise ApiError("ERR_FC_RECEIVING_SUSPENDED", 409)

    quota = store.active_quota(plan["seller_account_id"])
    if quota is None:
        raise ApiError("ERR_NO_ACTIVE_RESTOCK_QUOTA", 409)

    lines = plan_lines(plan_id)
    for line in lines:
        _check_prep(fc, line)
    for line in lines:
        _check_label(fc, line)
    for line in lines:
        _check_case_pack(fc, line)

    if not lines:
        raise ApiError("ERR_PLAN_HAS_NO_LINE_ITEMS", 422)

    # ladder step 18 — destination-centre receiving-window capacity
    overlap = sum(
        other["declared_units"] for other in db.plans.values()
        if other["id"] != plan["id"]
        and other["destination_fc_id"] == fc["id"]
        and other["status"] in RESERVING_STATUSES
        and _windows_intersect(other["appointment_window_start"],
                               other["appointment_window_end"],
                               plan["appointment_window_start"],
                               plan["appointment_window_end"]))
    if overlap + plan["declared_units"] > _effective_capacity(fc):
        raise ApiError("ERR_FC_RECEIVING_CAPACITY_EXCEEDED", 422)

    # ladder step 19 — the FINAL allocation waterfall
    grants, total = calc.compute_final(plan)
    if total < plan["declared_units"]:
        raise ApiError("ERR_RESTOCK_LIMIT_EXCEEDED", 422)

    for line, grant in grants:
        set_field(line, "final_allocated_units", grant)
    set_field(plan, "final_allocated_units", total)
    set_field(plan, "allocated_units", total)
    set_field(plan, "prep_compliance_status", "COMPLIANT")
    set_field(plan, "confirmed_at", clock.now())
    set_field(plan, "status", "CONFIRMED")
    set_field(quota, "utilized_units", quota["utilized_units"] + plan["allocated_units"])

    calc.refresh_sibling_drafts(plan)
    return finish(lambda: serialize.plan(plan), 200)


@bp.post("/fulfillment/inbound-shipment-plans/<plan_id>/revert-to-draft")
@require_roles("SellerOperator")
def revert_plan(plan_id):
    data = validate.body()
    validate.opt_str(data, "revert_reason")

    plan = get_plan(plan_id)
    require_seller_scope(plan["seller_account_id"])
    if plan["status"] != "CONFIRMED":
        raise ApiError("ERR_PLAN_NOT_CONFIRMED", 409)

    released = plan["allocated_units"]
    quota = store.active_quota(plan["seller_account_id"])
    if quota is not None:
        set_field(quota, "utilized_units", max(0, quota["utilized_units"] - released))

    set_field(plan, "status", "DRAFT")
    set_field(plan, "allocated_units", 0)
    set_field(plan, "final_allocated_units", 0)
    for line in plan_lines(plan_id):
        set_field(line, "final_allocated_units", 0)
    set_field(plan, "prep_compliance_status", "PENDING")
    set_field(plan, "confirmed_at", None)
    calc.run_provisional(plan)
    return finish(lambda: serialize.plan(plan), 200)


@bp.post("/fulfillment/inbound-shipment-plans/<plan_id>/ship")
@require_roles("SellerOperator")
def ship_plan(plan_id):
    data = validate.body()
    validate.opt_str(data, "carrier_reference")

    plan = get_plan(plan_id)
    require_seller_scope(plan["seller_account_id"])
    if plan["status"] != "CONFIRMED":
        raise ApiError("ERR_PLAN_NOT_CONFIRMED", 409)

    set_field(plan, "status", "IN_TRANSIT")
    return finish(lambda: serialize.plan(plan), 200)


@bp.post("/fulfillment/inbound-shipment-plans/<plan_id>/cancel")
@require_roles("SellerOperator")
def cancel_plan(plan_id):
    data = validate.body()
    validate.opt_str(data, "cancellation_reason")

    plan = get_plan(plan_id)
    require_seller_scope(plan["seller_account_id"])
    if plan["status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError("ERR_PLAN_NOT_CANCELLABLE", 409)

    from_draft = plan["status"] == "DRAFT"
    released = plan["allocated_units"]

    set_field(plan, "status", "CANCELLED")
    if from_draft:
        set_field(plan, "provisional_allocated_units", 0)
        for line in plan_lines(plan_id):
            set_field(line, "provisional_allocated_units", 0)
    else:
        quota = store.active_quota(plan["seller_account_id"])
        if quota is not None:
            set_field(quota, "utilized_units", max(0, quota["utilized_units"] - released))
        set_field(plan, "allocated_units", 0)
        set_field(plan, "final_allocated_units", 0)
        set_field(plan, "provisional_allocated_units", 0)

    calc.refresh_sibling_drafts(plan)
    return finish(lambda: serialize.plan(plan), 200)


@bp.post("/fulfillment/inbound-shipment-plans/<plan_id>/receive")
@require_roles("FcOperator")
def receive_plan(plan_id):
    data = validate.body()
    if "received_lines" not in data or not isinstance(data["received_lines"], list):
        validate.bad("Field 'received_lines' must be an array.")
    if not data["received_lines"]:
        validate.bad("Field 'received_lines' must be a non-empty array.")
    validate.opt_str(data, "receipt_note")

    parsed = []
    for index, element in enumerate(data["received_lines"]):
        if not isinstance(element, dict):
            validate.bad("Element %d of 'received_lines' must be an object." % index)
        parsed.append({
            "shipment_line_item_id": validate.req_str(element, "shipment_line_item_id"),
            "received_units": validate.req_int(element, "received_units", minimum=0),
            "unfulfillable_units": validate.req_int(element, "unfulfillable_units", minimum=0),
        })

    plan = get_plan(plan_id)

    resolved = []
    for element in parsed:
        line = db.line_items.get(element["shipment_line_item_id"])
        if line is None or line["shipment_plan_id"] != plan_id:
            raise ApiError("ERR_LINE_ITEM_NOT_FOUND", 404)
        resolved.append((line, element))

    require_fc_scope(plan["destination_fc_id"])

    if plan["status"] not in RECEIVABLE_STATUSES:
        raise ApiError("ERR_PLAN_NOT_RECEIVABLE", 409)

    now = clock.now()
    absorb = plan.setdefault("_absorb", {})
    contrib = plan.setdefault("_contrib", {})

    for line, element in resolved:
        lot = calc.select_receive_lot(line["sku_listing_id"], plan["destination_fc_id"])
        if lot is None:
            lot = _new_lot(line["sku_listing_id"], plan["destination_fc_id"], now)
        received = element["received_units"]
        unfulfillable = element["unfulfillable_units"]
        set_field(lot, "fulfillable_units", lot["fulfillable_units"] + received)
        set_field(lot, "unfulfillable_units", lot["unfulfillable_units"] + unfulfillable)
        set_field(lot, "units_received_total",
                  lot["units_received_total"] + received + unfulfillable)
        set_field(line, "received_units", line["received_units"] + received)
        absorb[line["id"]] = lot["id"]

    lines = plan_lines(plan_id)
    total_received = sum(li["received_units"] for li in lines)
    set_field(plan, "received_units", total_received)

    if total_received >= plan["declared_units"]:
        set_field(plan, "missing_units", 0)
        for line in lines:
            set_field(line, "shortfall_units", 0)
        _apply_shortfalls(plan, lines, absorb, contrib, now, clearing=True)
        set_field(plan, "status", "RECEIVED_COMPLETE")
        set_field(plan, "allocated_units", 0)
    else:
        set_field(plan, "missing_units", plan["declared_units"] - total_received)
        for line in lines:
            set_field(line, "shortfall_units",
                      max(0, line["units"] - line["received_units"]))
        _apply_shortfalls(plan, lines, absorb, contrib, now, clearing=False)
        set_field(plan, "status", "PARTIALLY_RECEIVED")

    return finish(lambda: serialize.plan(plan), 200)


def _new_lot(sku_listing_id, fc_id, at):
    row = new_row()
    row.update({
        "sku_listing_id": sku_listing_id,
        "fulfillment_center_id": fc_id,
        "first_received_at": at,
        "units_received_total": 0,
        "fulfillable_units": 0,
        "unfulfillable_units": 0,
        "units_reserved_for_removal": 0,
        "units_removed": 0,
        "units_shipped_mcf": 0,
        "missing_units": 0,
        "lot_status": "ACTIVE",
        "reconciliation_status": "RECONCILED",
        "aged_bucket": "UNDER_181",
        "ltsf_exposed": False,
        "storage_fee_accrued_cents": 0,
        "discrepancy_opened_at": None,
        "unfulfillable_recorded_at": None,
        "last_removal_completed_at": None,
    })
    db.lots[row["id"]] = row
    mark_created(row)
    return row


def _apply_shortfalls(plan, lines, absorb, contrib, now, clearing):
    """Adjust each absorbing lot's missing_units by the delta this receipt caused."""
    for line in lines:
        lot_id = absorb.get(line["id"])
        if lot_id is None:
            continue
        lot = db.lots.get(lot_id)
        if lot is None:
            continue
        previous = contrib.get(line["id"], 0)
        target = 0 if clearing else line["shortfall_units"]
        delta = target - previous
        if delta:
            set_field(lot, "missing_units", max(0, lot["missing_units"] + delta))
        contrib[line["id"]] = target
        if lot["missing_units"] >= 1 and lot["reconciliation_status"] == "RECONCILED":
            set_field(lot, "reconciliation_status", "DISCREPANCY_OPEN")
            set_field(lot, "discrepancy_opened_at", now)
        elif lot["missing_units"] == 0 and lot["reconciliation_status"] == "DISCREPANCY_OPEN":
            set_field(lot, "reconciliation_status", "RECONCILED")
