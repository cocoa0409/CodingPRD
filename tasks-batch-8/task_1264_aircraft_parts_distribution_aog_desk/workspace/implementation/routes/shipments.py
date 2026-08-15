"""Shipment and CharterSlot endpoints, incl. tender gates and the delivery
cascade."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, ALL_BUSINESS
from db import store, clock
from errors import (ApiError, ERR_INVALID_STATE, ERR_ORDER_NOT_FOUND,
                    ERR_SHIPMENT_NOT_FOUND, ERR_CHARTER_SLOT_NOT_FOUND,
                    ERR_DUPLICATE_SHIPMENT, ERR_CHARTER_WINDOW_OVERLAP,
                    ERR_COMPLIANCE_NOT_CLEARED, ERR_HAZMAT_DECLARATION_MISSING,
                    ERR_EXPORT_LICENSE_REQUIRED, ERR_EXPORT_DESTINATION_DENIED)
from helpers import (new_record, touch, get_or_404, bump_unit_status,
                     post_ledger, ser_shipment, ser_charter_slot, sort_asc,
                     order_lines_of, maybe_close_order)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_dt, fmt_dt, bad)

bp = Blueprint("shipments", __name__)

DENIED_DESTINATIONS = {"KP", "CU", "IR", "SY"}
CHARTER_BUFFER = timedelta(minutes=120)


def _shipment_customer(shipment):
    order = store["orders"].get(shipment["order_id"])
    return order["customer_id"] if order else None


@bp.post("/aog/shipments")
def create_shipment():
    require_roles("WarehouseOperator")
    body = get_body()
    order_id = as_str(req_present(body, "order_id"), "order_id")
    order = get_or_404("orders", order_id, ERR_ORDER_NOT_FOUND, "SalesOrder")
    haz_ref = body.get("hazmat_declaration_ref")
    exp_ref = body.get("export_license_ref")
    if haz_ref is not None and not isinstance(haz_ref, str):
        bad("hazmat_declaration_ref must be a string")
    if exp_ref is not None and not isinstance(exp_ref, str):
        bad("export_license_ref must be a string")
    charter_fields = ("depart_at", "arrive_at", "charter_slot_id")
    if order["freight_mode"] == "CHARTER":
        for f in charter_fields:
            if body.get(f) is None:
                bad(f"{f} is required for CHARTER shipments")
        depart_dt = as_dt(body["depart_at"], "depart_at")
        arrive_dt = as_dt(body["arrive_at"], "arrive_at")
        if arrive_dt <= depart_dt:
            bad("arrive_at must be strictly after depart_at")
        slot = get_or_404("charter_slots", body["charter_slot_id"],
                          ERR_CHARTER_SLOT_NOT_FOUND, "CharterSlot")
        depart_raw, arrive_raw = body["depart_at"], body["arrive_at"]
        slot_id = slot["id"]
    else:
        for f in charter_fields:
            if body.get(f) is not None:
                bad(f"{f} is forbidden for non-CHARTER shipments")
        depart_dt = arrive_dt = None
        depart_raw = arrive_raw = slot_id = None
        slot = None
    if slot is not None and slot["status"] == "RELEASED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Charter slot is RELEASED")
    for s in store["shipments"].values():
        if s["order_id"] == order["id"]:
            raise ApiError(ERR_DUPLICATE_SHIPMENT, 409,
                           "SalesOrder already has a shipment")
    if slot is not None:
        # 120-minute buffer diary check against live bookings on the slot
        for s in store["shipments"].values():
            if s.get("charter_slot_id") != slot["id"]:
                continue
            d2, a2 = s["_depart_dt"], s["_arrive_dt"]
            if arrive_dt <= d2:
                gap = d2 - arrive_dt
            elif a2 <= depart_dt:
                gap = depart_dt - a2
            else:
                gap = timedelta(0)
            if gap < CHARTER_BUFFER:
                raise ApiError(ERR_CHARTER_WINDOW_OVERLAP, 409,
                               "Charter booking within 120 minutes of an "
                               "existing booking on the slot")
    quote = store["quotes"].get(order["quote_id"])
    freight = quote["freight_cost_cents"] if quote else 0
    rec = new_record("shipments", {
        "order_id": order["id"],
        "hazmat_declaration_ref": haz_ref,
        "export_license_ref": exp_ref,
        "depart_at": depart_raw,
        "arrive_at": arrive_raw,
        "charter_slot_id": slot_id,
        "freight_cost_cents": freight,
        "status": "DRAFT",
        "_depart_dt": depart_dt,
        "_arrive_dt": arrive_dt,
    })
    post_ledger(order["customer_id"], "FREIGHT_DEBIT", freight, "SHIPMENT",
                rec["id"])
    return success(ser_shipment(rec), 201)


@bp.get("/aog/shipments")
def list_shipments():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["shipments"].values())
    if role == "CustomerContact":
        recs = [s for s in recs if _shipment_customer(s) == uid]
    q = request.args
    if q.get("order_id") is not None:
        recs = [s for s in recs if s["order_id"] == q.get("order_id")]
    if q.get("charter_slot_id") is not None:
        recs = [s for s in recs
                if s.get("charter_slot_id") == q.get("charter_slot_id")]
    if q.get("status") is not None:
        recs = [s for s in recs if s["status"] == q.get("status")]
    return paged([ser_shipment(s) for s in sort_asc(recs)], limit, offset)


@bp.get("/aog/shipments/<sid>")
def get_shipment(sid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("shipments", sid, ERR_SHIPMENT_NOT_FOUND, "Shipment")
    return success(ser_shipment(rec))


@bp.post("/aog/shipments/<sid>/tender")
def tender_shipment(sid):
    require_roles("WarehouseOperator")
    shipment = get_or_404("shipments", sid, ERR_SHIPMENT_NOT_FOUND, "Shipment")
    if shipment["status"] not in ("DRAFT", "EXCEPTION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT (or EXCEPTION) shipment can be tendered")
    body = get_body()
    haz = body.get("hazmat_declaration_ref")
    exp = body.get("export_license_ref")
    if haz is not None and not isinstance(haz, str):
        bad("hazmat_declaration_ref must be a string")
    if exp is not None and not isinstance(exp, str):
        bad("export_license_ref must be a string")
    if haz is not None:
        shipment["hazmat_declaration_ref"] = haz
    if exp is not None:
        shipment["export_license_ref"] = exp
    order = store["orders"][shipment["order_id"]]
    # state gates in PRD order: compliance, then fulfillment
    if order["compliance_status"] != "CLEARED":
        raise ApiError(ERR_COMPLIANCE_NOT_CLEARED, 409,
                       "Order compliance status is not CLEARED")
    if shipment["status"] == "DRAFT":
        if order["fulfillment_status"] != "ALLOCATED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Order fulfillment status is not ALLOCATED")
    else:  # re-tender after EXCEPTION: goods already shipped
        if order["fulfillment_status"] != "SHIPPED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Order fulfillment status is not SHIPPED")
    lines = order_lines_of(order["id"])
    parts = [store["parts"][l["part_id"]] for l in lines]
    if any(p["hazmat_class"] != "NONE" for p in parts) and \
            not shipment["hazmat_declaration_ref"]:
        raise ApiError(ERR_HAZMAT_DECLARATION_MISSING, 422,
                       "A hazmat declaration reference is required")
    if any(p["export_control_code"] != "EAR99" for p in parts) and \
            not shipment["export_license_ref"]:
        raise ApiError(ERR_EXPORT_LICENSE_REQUIRED, 422,
                       "An export license reference is required")
    if order["destination_country"] in DENIED_DESTINATIONS:
        raise ApiError(ERR_EXPORT_DESTINATION_DENIED, 422,
                       "Destination country is denied")
    # transitions
    for line in lines:
        unit = store["units"].get(line["allocated_unit_id"])
        if unit is not None and unit["status"] == "ALLOCATED":
            bump_unit_status(unit, "SHIPPED")
    if order["fulfillment_status"] == "ALLOCATED":
        order["fulfillment_status"] = "SHIPPED"
        touch(order)
    if order["freight_mode"] == "CHARTER" and shipment.get("charter_slot_id"):
        slot = store["charter_slots"].get(shipment["charter_slot_id"])
        if slot is not None and slot["status"] == "OPEN":
            slot["status"] = "BOOKED"
            touch(slot)
    shipment["status"] = "TENDERED"
    touch(shipment)
    shipment["status"] = "IN_TRANSIT"  # automatic fall-through
    touch(shipment)
    return success(ser_shipment(shipment))


@bp.post("/aog/shipments/<sid>/deliver")
def deliver_shipment(sid):
    require_roles("WarehouseOperator")
    shipment = get_or_404("shipments", sid, ERR_SHIPMENT_NOT_FOUND, "Shipment")
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an IN_TRANSIT shipment can be delivered")
    order = store["orders"][shipment["order_id"]]
    quote = store["quotes"].get(order["quote_id"])
    lines = order_lines_of(order["id"])
    now = clock.current
    shipment["status"] = "DELIVERED"
    touch(shipment)
    # unit transitions
    for line in lines:
        unit = store["units"].get(line["allocated_unit_id"])
        if unit is None or unit["status"] != "SHIPPED":
            continue
        if line["sale_type"] in ("OUTRIGHT", "EXCHANGE"):
            bump_unit_status(unit, "SOLD")
        else:
            bump_unit_status(unit, "ON_LOAN")
    # order dimensions
    order["fulfillment_status"] = "DELIVERED"
    order["payment_status"] = "INVOICED"
    order["invoiced_cents"] = quote["total_cents"] if quote else 0
    touch(order)
    post_ledger(order["customer_id"], "INVOICE_DEBIT", order["invoiced_cents"],
                "SALES_ORDER", order["id"])
    # core deposits + returns per EXCHANGE line
    for line in lines:
        if line["sale_type"] != "EXCHANGE":
            continue
        part = store["parts"][line["part_id"]]
        core_value = part["core_value_cents"] * line["quantity"]
        due = now + timedelta(days=21)
        cr = new_record("core_returns", {
            "order_line_id": line["id"],
            "customer_id": order["customer_id"],
            "core_value_cents": core_value,
            "due_at": fmt_dt(due),
            "received_at": None,
            "days_overdue": 0,
            "penalty_cents": 0,
            "refunded_cents": 0,
            "penalty_retained_cents": 0,
            "forfeited_cents": 0,
            "penalty_waived_cents": 0,
            "status": "OPEN",
            "verdict": None,
            "_due_dt": due,
            "_received_dt": None,
            "_inbound_unit_id": None,
        })
        post_ledger(order["customer_id"], "CORE_DEPOSIT_DEBIT", core_value,
                    "CORE_RETURN", cr["id"])
    # loans per LOAN/LEASE line
    for line in lines:
        if line["sale_type"] not in ("LOAN", "LEASE"):
            continue
        if line["sale_type"] == "LOAN":
            due = now + timedelta(days=30)
            periods = None
        else:
            periods = line["lease_periods"]
            due = now + timedelta(days=30 * periods)
        loan = new_record("loans", {
            "customer_id": order["customer_id"],
            "unit_id": line["allocated_unit_id"],
            "order_line_id": line["id"],
            "loan_type": line["sale_type"],
            "daily_rate_cents": line["unit_price_cents"],
            "lease_periods": periods,
            "start_at": fmt_dt(now),
            "due_at": fmt_dt(due),
            "returned_at": None,
            "billed_cents": 0,
            "status": "ACTIVE",
            "_start_dt": now,
            "_due_dt": due,
            "_returned_dt": None,
            "_periods_billed": 0,
        })
        if loan["loan_type"] == "LEASE":
            post_ledger(order["customer_id"], "LEASE_DEBIT",
                        30 * loan["daily_rate_cents"], "LOAN_AGREEMENT",
                        loan["id"])
            loan["_periods_billed"] = 1
    # line delivery stamps
    for line in lines:
        line["delivered_at"] = fmt_dt(now)
        line["_delivered_dt"] = now
        touch(line)
    # request cascade
    if quote is not None:
        req = store["requests"].get(quote["aog_request_id"])
        if req is not None and req["status"] == "FULFILLING":
            req["status"] = "FULFILLED"
            touch(req)
    # charter slot released after delivery
    if order["freight_mode"] == "CHARTER" and shipment.get("charter_slot_id"):
        slot = store["charter_slots"].get(shipment["charter_slot_id"])
        if slot is not None and slot["status"] == "BOOKED":
            slot["status"] = "OPEN"
            touch(slot)
    maybe_close_order(order)
    return success(ser_shipment(shipment))


# ---- CharterSlot ----

@bp.post("/aog/charter-slots")
def create_slot():
    require_roles("AogDeskAgent")
    body = get_body()
    tail = as_str(req_present(body, "tail_number"), "tail_number")
    home = as_str(req_present(body, "home_base"), "home_base")
    for s in store["charter_slots"].values():
        if s["tail_number"] == tail:
            bad("tail_number must be unique")
    rec = new_record("charter_slots", {
        "tail_number": tail,
        "home_base": home,
        "status": "OPEN",
    })
    return success(ser_charter_slot(rec), 201)


@bp.get("/aog/charter-slots")
def list_slots():
    require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["charter_slots"].values())
    q = request.args
    if q.get("status") is not None:
        recs = [s for s in recs if s["status"] == q.get("status")]
    return paged([ser_charter_slot(s) for s in sort_asc(recs)], limit, offset)


@bp.get("/aog/charter-slots/<sid>")
def get_slot(sid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("charter_slots", sid, ERR_CHARTER_SLOT_NOT_FOUND,
                     "CharterSlot")
    return success(ser_charter_slot(rec))


@bp.post("/aog/charter-slots/<sid>/release")
def release_slot(sid):
    require_roles("AogDeskAgent")
    slot = get_or_404("charter_slots", sid, ERR_CHARTER_SLOT_NOT_FOUND,
                      "CharterSlot")
    if slot["status"] == "OPEN":
        slot["status"] = "RELEASED"
        touch(slot)
    elif slot["status"] == "BOOKED":
        for s in store["shipments"].values():
            if s.get("charter_slot_id") == slot["id"] and \
                    s["status"] in ("TENDERED", "IN_TRANSIT"):
                raise ApiError(ERR_INVALID_STATE, 409,
                               "A live shipment references this slot")
        slot["status"] = "OPEN"
        touch(slot)
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "RELEASED slot cannot be released again")
    return success(ser_charter_slot(slot))
