"""Parts: sourcing pipeline with traceability checkpoints (PRD 3.6)."""

from flask import Blueprint

import db
import envelope
import ops
from errors import ApiError
from middleware import require_roles
from validate import (
    apply_filters,
    body,
    get_row,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("parts", __name__)

TRACE_REQUIRED_CONDITIONS = ("OVERHAUL", "SERVICEABLE")


def _trace_missing(part):
    return (
        part["condition"] in TRACE_REQUIRED_CONDITIONS
        and not part.get("trace_doc_ref")
    )


@bp.post("/api/parts")
@require_roles("Mechanic", "PartsClerk")
def create_part():
    b = body()
    discrepancy_id = req_str(b, "discrepancy_id")
    part_number = req_str(b, "part_number")
    serial_number = opt_str(b, "serial_number")
    condition = req_enum(b, "condition", ("NEW", "OVERHAUL", "SERVICEABLE"))
    trace_doc_ref = opt_str(b, "trace_doc_ref")
    unit_cost_cents = req_int(b, "unit_cost_cents")
    quantity = req_int(b, "quantity")
    get_row(db.DISCREPANCIES, discrepancy_id)
    if quantity < 1:
        raise ApiError("ERR_VALIDATION", "quantity must be at least 1.")
    part = {
        "discrepancy_id": discrepancy_id,
        "part_number": part_number,
        "serial_number": serial_number,
        "condition": condition,
        "trace_doc_ref": trace_doc_ref,
        "unit_cost_cents": unit_cost_cents,
        "quantity": quantity,
        "status": "REQUESTED",
    }
    db.stamp_new(part)
    db.PARTS[part["id"]] = part
    return envelope.created(ops.pub(part, ops.PART_F))


@bp.get("/api/parts")
@require_roles("ShopManager", "Mechanic", "PartsClerk")
def list_parts():
    rows = apply_filters(
        list(db.PARTS.values()),
        {"discrepancy_id": "discrepancy_id", "status": "status"},
    )
    return paginate(rows, ops.PART_F)


@bp.get("/api/parts/<rid>")
@require_roles("ShopManager", "Mechanic", "PartsClerk")
def get_part(rid):
    part = get_row(db.PARTS, rid)
    return envelope.ok(ops.pub(part, ops.PART_F))


@bp.post("/api/parts/<rid>/mark-sourced")
@require_roles("PartsClerk")
def mark_sourced(rid):
    part = get_row(db.PARTS, rid)
    if part["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED part can be sourced.")
    # First traceability checkpoint (priority 8).
    if _trace_missing(part):
        raise ApiError("ERR_TRACEABILITY_MISSING")
    part["status"] = "SOURCED"
    db.touch(part)
    return envelope.ok(ops.pub(part, ops.PART_F))


@bp.post("/api/parts/<rid>/receive")
@require_roles("PartsClerk")
def receive_part(rid):
    part = get_row(db.PARTS, rid)
    if part["status"] != "SOURCED":
        raise ApiError("ERR_INVALID_STATE", "Only a SOURCED part can be received.")
    part["status"] = "RECEIVED"
    db.touch(part)
    return envelope.ok(ops.pub(part, ops.PART_F))


@bp.post("/api/parts/<rid>/install")
@require_roles("Mechanic")
def install_part(rid):
    part = get_row(db.PARTS, rid)
    if part["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED part can be installed.")
    disc = get_row(db.DISCREPANCIES, part["discrepancy_id"])
    if disc["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE", "The parent discrepancy must stand APPROVED."
        )
    # Traceability re-check (priority 8) precedes the invoice lock (priority 10).
    if _trace_missing(part):
        raise ApiError("ERR_TRACEABILITY_MISSING")
    if ops.invoice_locked(disc["work_order_id"]):
        raise ApiError("ERR_INVOICE_LOCKED")
    part["status"] = "INSTALLED"
    db.touch(part)
    return envelope.ok(ops.pub(part, ops.PART_F))


@bp.post("/api/parts/<rid>/return")
@require_roles("PartsClerk")
def return_part(rid):
    part = get_row(db.PARTS, rid)
    if part["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED part can be returned.")
    part["status"] = "RETURNED"
    db.touch(part)
    return envelope.ok(ops.pub(part, ops.PART_F))
