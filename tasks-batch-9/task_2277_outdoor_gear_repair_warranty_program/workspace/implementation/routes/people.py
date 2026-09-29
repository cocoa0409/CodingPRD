"""Customers, gear units (incl. trade-in and the resale channel) and technicians."""

from flask import Blueprint

import calc
import services as svc
from core import (
    db, fail, get_body, iso, new_row, now, ordered, page, pagination, q_str,
    require, respond, respond_list, set_fields, v_enum, v_instant, v_int, v_list,
    v_string,
)

bp = Blueprint("people", __name__)

LOYALTY_TIERS = ("STANDARD", "PRO")
ROSTER_STATES = ("ACTIVE", "ON_LEAVE", "INACTIVE")
WARRANTY_STATES = ("IN_WARRANTY", "EXPIRED", "LIFETIME")


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #

@bp.post("/customers")
def create_customer():
    require("ServiceAgent", "ProgramAdmin")
    body = get_body()
    full_name = v_string(body, "full_name", required=True, min_len=1, max_len=200)
    email = v_string(body, "email", required=True, min_len=5, max_len=120)
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "Field 'email' must contain an at-sign.")
    tier = v_enum(body, "loyalty_tier", LOYALTY_TIERS, default="STANDARD")

    for existing in db.customers.values():
        if existing["email"] == email:
            fail("ERR_EMAIL_TAKEN")

    row = new_row()
    row.update({
        "email": email,
        "full_name": full_name,
        "loyalty_tier": tier,
        "lifetime_claim_count": 0,
        "trade_in_credit_cents": 0,
    })
    db.customers[row["id"]] = row
    return respond(svc.ser(row), 201)


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    ctx = require("Customer", "ServiceAgent", "ProgramAdmin")
    if ctx.is_customer and customer_id != ctx.user_id:
        if customer_id in db.customers:
            fail("ERR_NOT_RESOURCE_OWNER")
    customer = svc.need(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    return respond(svc.ser(customer))


# --------------------------------------------------------------------------- #
# Gear units
# --------------------------------------------------------------------------- #

@bp.post("/gear-items")
def create_item():
    ctx = require("Customer", "ServiceAgent")
    body = get_body()

    # check 5 -- a Customer may only register their own unit
    if ctx.is_customer and body.get("owner_customer_id") not in (None, ctx.user_id):
        fail("ERR_NOT_RESOURCE_OWNER")

    # check 7 -- body references resolve
    model = svc.fk(body, "gear_model_id", db.gear_models, "ERR_GEAR_MODEL_NOT_FOUND")
    owner = svc.fk(body, "owner_customer_id", db.customers, "ERR_CUSTOMER_NOT_FOUND")

    # check 9 -- shape
    if model is None:
        fail("ERR_INVALID_REQUEST", "Field 'gear_model_id' is required.")
    if owner is None:
        fail("ERR_INVALID_REQUEST", "Field 'owner_customer_id' is required.")
    serial_number = v_string(body, "serial_number", required=True, min_len=3, max_len=40)
    purchase_date = v_instant(body, "purchase_date", required=True)
    purchase_price = v_int(body, "purchase_price_cents", required=True, min_value=0)
    proof_type = v_enum(body, "proof_of_purchase_type", calc.PROOF_TYPES, default="NONE")
    proof_ref = v_string(body, "proof_of_purchase_ref", max_len=200)
    condition_grade = v_enum(body, "condition_grade", calc.CONDITION_GRADES)

    # check 30 -- purchase date not in the future
    if purchase_date > now():
        fail("ERR_PURCHASE_DATE_IN_FUTURE")

    # check 45 -- serial unique within the model
    for existing in db.gear_items.values():
        if (
            existing["gear_model_id"] == model["id"]
            and existing["serial_number"] == serial_number
        ):
            fail("ERR_SERIAL_ALREADY_REGISTERED")

    if proof_type == "NONE":
        proof_ref = None

    row = new_row()
    row.update({
        "gear_model_id": model["id"],
        "owner_customer_id": owner["id"],
        "serial_number": serial_number,
        "purchase_date": iso(purchase_date),
        "purchase_price_cents": purchase_price,
        "proof_of_purchase_type": proof_type,
        "proof_of_purchase_ref": proof_ref,
        "condition_grade": condition_grade,
        "disposition_status": "WITH_CUSTOMER",
        "age_months": 0,
        "warranty_state": "EXPIRED",
        "replacement_value_depreciated_cents": 0,
        "replacement_value_successor_cents": 0,
        "trade_in_credit_cents": 0,
        "refurb_list_price_cents": None,
        "resale_price_cents": None,
    })
    row.update(svc.item_derived(row))
    db.gear_items[row["id"]] = row
    return respond(svc.ser_item(row), 201)


@bp.get("/gear-items/<item_id>")
def read_item(item_id):
    ctx = require(
        "Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin"
    )
    item = svc.need(db.gear_items, item_id, "ERR_GEAR_ITEM_NOT_FOUND")
    svc.guard_owner(ctx, item)
    return respond(svc.ser_item(item))


@bp.get("/gear-items")
def list_items():
    require("Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    model_id = q_str("gear_model_id")
    owner_id = q_str("owner_customer_id")
    disposition = q_str("disposition_status")
    if disposition is not None and disposition not in calc.DISPOSITION_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'disposition_status' is invalid.")
    warranty = q_str("warranty_state")
    if warranty is not None and warranty not in WARRANTY_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'warranty_state' is invalid.")
    limit, offset = pagination()

    rows = []
    for item in ordered(db.gear_items):
        svc.refresh_item(item)
        if model_id is not None and item["gear_model_id"] != model_id:
            continue
        if owner_id is not None and item["owner_customer_id"] != owner_id:
            continue
        if disposition is not None and item["disposition_status"] != disposition:
            continue
        if warranty is not None and item["warranty_state"] != warranty:
            continue
        rows.append(item)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.post("/gear-items/<item_id>/trade-in")
def trade_in(item_id):
    ctx = require("Customer", "ServiceAgent")
    item = svc.need(db.gear_items, item_id, "ERR_GEAR_ITEM_NOT_FOUND")
    svc.guard_owner(ctx, item)
    body = get_body()
    grade = v_enum(body, "condition_grade", calc.CONDITION_GRADES, required=True)

    # check 17 -- the unit is not already terminal
    if item["disposition_status"] in calc.ITEM_TERMINAL:
        fail("ERR_ALREADY_TERMINAL")
    # check 49 -- only an irreparable unit may be traded in
    if item["disposition_status"] != "IRREPARABLE_HOLD":
        fail("ERR_ITEM_NOT_IRREPARABLE")

    svc.refresh_item(item)
    claim = svc.driving_claim_for_item(item)
    goodwill = claim is not None and claim.get("decision") in ("WARRANTY_REPAIR", "WARRANTY_REPLACE")
    credit = calc.trade_in_credit(
        item["replacement_value_depreciated_cents"], grade, goodwill
    )
    refurb = calc.refurb_list_price(item["replacement_value_successor_cents"])

    set_fields(
        item,
        condition_grade=grade,
        trade_in_credit_cents=credit,
        refurb_list_price_cents=refurb,
        disposition_status="TRADED_IN",
    )

    owner = svc.owner_of_item(item)
    if owner is not None:
        set_fields(owner, trade_in_credit_cents=owner["trade_in_credit_cents"] + credit)

    if claim is not None:
        set_fields(claim, status="CLOSED_REPLACED")
        svc.release_claim_liability(claim, "CLAIM_CLOSED")
        svc.recompute_center_liability(svc.center_of(claim))

    return respond(svc.ser_item(item))


DISPOSITION_HOPS = {
    "TRADED_IN": ("REFURB_LISTED", "RECYCLED"),
    "REFURB_LISTED": ("RESOLD", "RECYCLED"),
}


@bp.post("/gear-items/<item_id>/disposition")
def move_disposition(item_id):
    require("PartsCoordinator", "ProgramAdmin")
    item = svc.need(db.gear_items, item_id, "ERR_GEAR_ITEM_NOT_FOUND")
    body = get_body()
    target = v_enum(body, "to", calc.DISPOSITION_STATES, required=True)
    sale_price = v_int(body, "sale_price_cents", min_value=0)
    if target == "RESOLD" and sale_price is None:
        fail("ERR_INVALID_REQUEST", "Field 'sale_price_cents' is required for a resale.")

    # check 16 -- legal resale-channel hop
    if target not in DISPOSITION_HOPS.get(item["disposition_status"], ()):
        fail("ERR_INVALID_DISPOSITION_STATE")

    updates = {"disposition_status": target}
    if target == "RESOLD":
        updates["resale_price_cents"] = sale_price
    set_fields(item, **updates)
    return respond(svc.ser_item(item))


# --------------------------------------------------------------------------- #
# Technicians
# --------------------------------------------------------------------------- #

def _validate_certifications(raw):
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "Field 'certifications' must be a non-empty array.")
    seen = set()
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each certification must be an object.")
        work_type = entry.get("work_type")
        level = entry.get("level")
        if work_type not in calc.WORK_TYPES:
            fail("ERR_INVALID_REQUEST", "Certification 'work_type' is not recognised.")
        if isinstance(level, bool) or not isinstance(level, int) or level < 1 or level > 3:
            fail("ERR_INVALID_REQUEST", "Certification 'level' must be an integer 1..3.")
        if work_type in seen:
            fail("ERR_INVALID_REQUEST", "At most one certification per work_type.")
        seen.add(work_type)
        cleaned.append({"work_type": work_type, "level": level})
    return cleaned


@bp.post("/technicians")
def create_technician():
    require("ProgramAdmin")
    body = get_body()
    center = svc.fk(body, "service_center_id", db.service_centers, "ERR_SERVICE_CENTER_NOT_FOUND")
    if center is None:
        fail("ERR_INVALID_REQUEST", "Field 'service_center_id' is required.")
    full_name = v_string(body, "full_name", required=True, min_len=1, max_len=200)
    employee_code = v_string(body, "employee_code", required=True, min_len=2, max_len=24)
    status = v_enum(body, "status", ROSTER_STATES, default="ACTIVE")
    if "certifications" not in body or body["certifications"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'certifications' is required.")
    certifications = _validate_certifications(body["certifications"])

    for existing in db.technicians.values():
        if existing["employee_code"] == employee_code:
            fail("ERR_EMPLOYEE_CODE_TAKEN")

    row = new_row()
    row.update({
        "service_center_id": center["id"],
        "full_name": full_name,
        "employee_code": employee_code,
        "status": status,
        "certifications": certifications,
        "scheduled_minutes_open": 0,
        "completed_minutes": 0,
    })
    db.technicians[row["id"]] = row
    return respond(svc.ser(row), 201)


@bp.get("/technicians/<technician_id>")
def read_technician(technician_id):
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    technician = svc.need(db.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")
    return respond(svc.ser(technician))


@bp.get("/technicians")
def list_technicians():
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    center_id = q_str("service_center_id")
    status = q_str("status")
    if status is not None and status not in ROSTER_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    work_type = q_str("work_type")
    if work_type is not None and work_type not in calc.WORK_TYPES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'work_type' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for technician in ordered(db.technicians):
        if center_id is not None and technician["service_center_id"] != center_id:
            continue
        if status is not None and technician["status"] != status:
            continue
        if work_type is not None and svc.cert_level(technician, work_type) is None:
            continue
        rows.append(technician)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.patch("/technicians/<technician_id>")
def patch_technician(technician_id):
    require("ProgramAdmin")
    technician = svc.need(db.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")
    body = get_body()
    status = v_enum(body, "status", ROSTER_STATES)
    updates = {}
    if status is not None:
        updates["status"] = status
    if "certifications" in body and body["certifications"] is not None:
        updates["certifications"] = _validate_certifications(body["certifications"])
    set_fields(technician, **updates)
    return respond(svc.ser(technician))
