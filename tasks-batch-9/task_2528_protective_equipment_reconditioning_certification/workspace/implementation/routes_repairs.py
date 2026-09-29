"""RepairOrder endpoints (PRD 3.6)."""
from flask import Blueprint

import calc
import cascades
import db
import helpers
import serialize
import validate
from auth import authorize
from db import touch
from errors import ApiError

bp = Blueprint("repair_orders", __name__)

READ_ROLES = ("PlantManager", "Technician", "CertifyingInspector", "ComplianceOfficer")


def _check_version(unit, expected):
    """PRD 2.5 / ladder rung 29 — evaluated last of all."""
    if expected != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION",
                       "The unit has moved on since it was read.")


@bp.post("/repair-orders")
def create_repair_order():
    caller = authorize(("Technician",))
    data = validate.body()
    equipment_unit_id = validate.req_id(data, "equipment_unit_id")
    expected_version = validate.req_int(data, "expected_equipment_unit_version")
    unit = helpers.unit(equipment_unit_id)

    if unit["recon_status"] != "REPAIR_PENDING":
        raise ApiError("ERR_UNIT_STATE_INVALID",
                       "Repair orders are only opened against REPAIR_PENDING units.")
    model = cascades.model_of(unit)
    if model is not None and model["reconditionable"] is False:
        raise ApiError("ERR_MODEL_NOT_RECONDITIONABLE",
                       "The manufacturer has withdrawn this model from reconditioning.")
    _check_version(unit, expected_version)

    record = db.base_record()
    record.update({
        "equipment_unit_id": unit["id"],
        "part_lines": [],
        "reserved_parts_cents": 0,
        "installed_parts_cents": 0,
        "labor_cents": 0,
        "warranty_claim_ref": None,
        "verification_failure_count": 0,
        "opened_by_user_id": caller.user_id,
        "installed_by_user_id": None,
        "verified_by_user_id": None,
        "cancel_reason": None,
        "status": "DRAFT",
    })
    db.db.repair_orders[record["id"]] = record
    touch(unit)
    return helpers.single(record, serialize.repair_order, 201)


@bp.get("/repair-orders/<row_id>")
def get_repair_order(row_id):
    authorize(READ_ROLES)
    return helpers.single(helpers.repair_order(row_id), serialize.repair_order)


@bp.get("/repair-orders")
def list_repair_orders():
    authorize(READ_ROLES)
    filters = {
        "equipment_unit_id": validate.query_str("equipment_unit_id"),
        "status": validate.query_enum("status", calc.REPAIR_ORDER_STATUSES),
    }
    return helpers.listing("repair_orders", serialize.repair_order, filters)


@bp.post("/repair-orders/<row_id>/part-lines")
def append_part_line(row_id):
    authorize(("Technician",))
    data = validate.body()
    approved_part_id = validate.req_id(data, "approved_part_id")
    quantity = validate.req_int(data, "quantity", minimum=1)
    lot_code = validate.req_str(data, "lot_code", max_len=100)
    oem_cert_ref = validate.opt_str(data, "oem_cert_ref", max_len=200)
    order = helpers.repair_order(row_id)
    part = helpers.part(approved_part_id)

    if order["status"] != "DRAFT":
        raise ApiError("ERR_REPAIR_ORDER_STATE_INVALID",
                       "Lines are only appended to a DRAFT order.")
    unit = db.db.equipment_units.get(order["equipment_unit_id"])
    unit_model_id = unit["model_spec_id"] if unit else None
    if part["model_spec_id"] != unit_model_id:
        raise ApiError("ERR_PART_MODEL_MISMATCH",
                       "The part is approved for a different model.")
    if part["oem_approved"] is False:
        raise ApiError("ERR_PART_NOT_APPROVED",
                       "The plant installs only manufacturer-approved components.")

    line_index = 1 + max([line["line_index"] for line in order["part_lines"]] or [0])
    unit_price = part["unit_price_cents"]
    line = {
        "line_index": line_index,
        "approved_part_id": part["id"],
        "part_number": part["part_number"],
        "component_code": part["component_code"],
        "quantity": quantity,
        "lot_code": lot_code,
        "oem_cert_ref": oem_cert_ref,
        "unit_price_cents_snapshot": unit_price,
        "line_total_cents": quantity * unit_price,
        "status": "DRAFT",
    }
    order["part_lines"].append(line)
    touch(order)
    return helpers.single(order, serialize.repair_order)


@bp.post("/repair-orders/<row_id>/submit")
def submit_repair_order(row_id):
    authorize(("Technician",))
    validate.body()
    order = helpers.repair_order(row_id)

    if order["status"] != "DRAFT":
        raise ApiError("ERR_REPAIR_ORDER_STATE_INVALID",
                       "Only a DRAFT order can be submitted.")
    if not order["part_lines"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "An order with no part lines cannot be submitted.")

    # PRD 2.8: every line is checked before any bucket moves, so a refused
    # reservation leaves all three buckets exactly as they were.
    plan = []
    for line in order["part_lines"]:
        part = db.db.approved_parts.get(line["approved_part_id"])
        if part is None or line["quantity"] > part["on_hand_qty"]:
            raise ApiError("ERR_PART_STOCK_INSUFFICIENT",
                           "The parts cage cannot cover every line of this order.")
        plan.append((part, line))

    for part, line in plan:
        cascades.reserve_part(part, line["quantity"])
        line["status"] = "RESERVED"
    cascades.refresh_order_totals(order)
    order["status"] = "PARTS_PENDING"
    touch(order)
    return helpers.single(order, serialize.repair_order)


@bp.post("/repair-orders/<row_id>/install")
def install_repair_order(row_id):
    caller = authorize(("Technician",))
    data = validate.body()
    warranty_claim_ref = validate.opt_str(data, "warranty_claim_ref", max_len=200)
    order = helpers.repair_order(row_id)

    if order["status"] != "PARTS_PENDING":
        raise ApiError("ERR_REPAIR_ORDER_STATE_INVALID",
                       "Installation is only recorded on a PARTS_PENDING order.")
    unit = db.db.equipment_units.get(order["equipment_unit_id"])
    if (unit is not None and unit["warranty_coverage"] == "IN_WARRANTY"
            and warranty_claim_ref is None):
        raise ApiError("ERR_WARRANTY_CLAIM_REQUIRED",
                       "An in-warranty repair must be attributed to a claim first.")

    for line in order["part_lines"]:
        if line["status"] != "RESERVED":
            continue
        part = db.db.approved_parts.get(line["approved_part_id"])
        if part is not None:
            cascades.consume_part(part, line["quantity"])
        line["status"] = "INSTALLED"
    cascades.refresh_order_totals(order)
    if warranty_claim_ref is not None:
        order["warranty_claim_ref"] = warranty_claim_ref
    order["installed_by_user_id"] = caller.user_id
    order["status"] = "INSTALLED"
    touch(order)
    return helpers.single(order, serialize.repair_order)


@bp.post("/repair-orders/<row_id>/verify")
def verify_repair_order(row_id):
    caller = authorize(("Technician",))
    data = validate.body()
    outcome = validate.req_enum(data, "outcome", calc.VERIFY_OUTCOMES)
    validate.opt_str(data, "note", max_len=1000)
    order = helpers.repair_order(row_id)

    if order["status"] != "INSTALLED":
        raise ApiError("ERR_REPAIR_ORDER_STATE_INVALID",
                       "Only an INSTALLED order can be verified.")
    if caller.user_id is not None and caller.user_id == order["installed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The installing technician cannot sign off their own work.")

    unit = db.db.equipment_units.get(order["equipment_unit_id"])
    if outcome == "PASSED":
        order["verified_by_user_id"] = caller.user_id
        order["labor_cents"] = calc.REPAIR_LABOR_CENTS
        order["status"] = "CLOSED"
        touch(order)
        if unit is not None and unit["recon_status"] == "REPAIR_PENDING":
            unit["recon_status"] = "REPAIRED"
            touch(unit)
        return helpers.single(order, serialize.repair_order)

    attempts = (order["verification_failure_count"] or 0) + 1
    order["verification_failure_count"] = attempts
    if attempts <= calc.MAX_VERIFICATION_ATTEMPTS:
        # Consumed parts stay INSTALLED; they were physically fitted.
        order["status"] = "PARTS_PENDING"
        touch(order)
        return helpers.single(order, serialize.repair_order)

    order["cancel_reason"] = "verification attempts exhausted"
    order["status"] = "CANCELLED"
    touch(order)
    if unit is not None:
        cascades.condemn_cascade(unit, "REPAIR_UNSUCCESSFUL")
    return helpers.single(order, serialize.repair_order)


@bp.post("/repair-orders/<row_id>/cancel")
def cancel_repair_order(row_id):
    authorize(("Technician", "PlantManager"))
    data = validate.body()
    cancel_reason = validate.req_str(data, "cancel_reason", max_len=500)
    order = helpers.repair_order(row_id)

    if order["status"] not in ("DRAFT", "PARTS_PENDING"):
        raise ApiError("ERR_REPAIR_ORDER_STATE_INVALID",
                       "Only a DRAFT or PARTS_PENDING order can be cancelled.")

    for line in order["part_lines"]:
        if line["status"] != "RESERVED":
            continue
        part = db.db.approved_parts.get(line["approved_part_id"])
        if part is not None:
            cascades.release_part(part, line["quantity"])
        line["status"] = "DRAFT"
    cascades.refresh_order_totals(order)
    order["cancel_reason"] = cancel_reason
    order["status"] = "CANCELLED"
    touch(order)
    return helpers.single(order, serialize.repair_order)
