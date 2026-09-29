"""Engineering changes and the warranty design-feedback loop."""

import calc
import lookup
import response
import serializers as ser
import services
import validation as v
from db import db, new_record, touch
from errors import ApiError, invalid
from flask import Blueprint, g
from middleware import (ENGINEERING_LEAD, PLANT_ADMIN, PRODUCTION_PLANNER, QUALITY_INSPECTOR,
                        WARRANTY_ANALYST, endpoint)

change_bp = Blueprint("change", __name__)

ORIGINS = ("MANUAL", "WARRANTY")
CHANGE_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED",
                   "REJECTED", "CUT_IN", "CLOSED", "CANCELLED")
DECISIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")
DISPOSITIONS = ("DESIGN_DEFECT", "SUPPLIER_DEFECT", "NO_FAULT_FOUND")
RETURN_STATUSES = ("RECEIVED", "TEARDOWN", "ANALYZED_DESIGN", "ANALYZED_SUPPLIER", "CLOSED")
ANALYZED = ("ANALYZED_DESIGN", "ANALYZED_SUPPLIER")


# =========================================================================== #
# EngineeringChange
# =========================================================================== #
@change_bp.post("/engineering-changes")
@endpoint([ENGINEERING_LEAD])
def create_engineering_change():
    body = v.body()
    model_variant_id = v.req_str(body, "model_variant_id")
    affected_part_id = v.req_str(body, "affected_part_id")
    target_line_id = v.req_str(body, "target_line_id")
    position_code = v.req_str(body, "bom_position_code")
    cut_in_index = v.req_int(body, "cut_in_sequence_index", minimum=1)
    replacement_part_id = v.opt_str(body, "replacement_part_id", min_len=1)
    new_qty = v.opt_num(body, "new_qty_per_unit", exclusive_min=0)

    lookup.must(lookup.MODEL_VARIANT, model_variant_id)
    lookup.must(lookup.PART, affected_part_id)
    lookup.must(lookup.LINE, target_line_id)
    lookup.must_fk(lookup.PART, replacement_part_id)

    change = new_record()
    change.update({
        "origin": "MANUAL",
        "model_variant_id": model_variant_id,
        "bom_position_code": position_code,
        "affected_part_id": affected_part_id,
        "replacement_part_id": replacement_part_id,
        "target_line_id": target_line_id,
        "source_warranty_return_id": None,
        "cut_in_sequence_index": cut_in_index,
        "new_qty_per_unit": new_qty,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "revision_round": 0,
        "cut_in_at": None,
        "status": "DRAFT",
    })
    db.engineering_changes[change["id"]] = change
    return response.created(ser.engineering_change_out(change))


@change_bp.get("/engineering-changes/<change_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, ENGINEERING_LEAD, WARRANTY_ANALYST, QUALITY_INSPECTOR])
def read_engineering_change(change_id):
    change = lookup.must(lookup.ENGINEERING_CHANGE, change_id)
    return response.ok(ser.engineering_change_out(change))


@change_bp.get("/engineering-changes")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, ENGINEERING_LEAD, WARRANTY_ANALYST, QUALITY_INSPECTOR])
def list_engineering_changes():
    limit, offset = v.pagination()
    model_variant_id = v.q_str("model_variant_id")
    affected_part_id = v.q_str("affected_part_id")
    replacement_part_id = v.q_str("replacement_part_id")
    target_line_id = v.q_str("target_line_id")
    source_return_id = v.q_str("source_warranty_return_id")
    origin = v.q_enum("origin", ORIGINS)
    status = v.q_enum("status", CHANGE_STATUSES)

    lookup.must_fk(lookup.MODEL_VARIANT, model_variant_id)
    lookup.must_fk(lookup.PART, affected_part_id)
    lookup.must_fk(lookup.PART, replacement_part_id)
    lookup.must_fk(lookup.LINE, target_line_id)
    lookup.must_fk(lookup.WARRANTY_RETURN, source_return_id)

    items = list(db.engineering_changes.values())
    if model_variant_id is not None:
        items = [c for c in items if c["model_variant_id"] == model_variant_id]
    if affected_part_id is not None:
        items = [c for c in items if c["affected_part_id"] == affected_part_id]
    if replacement_part_id is not None:
        items = [c for c in items if c["replacement_part_id"] == replacement_part_id]
    if target_line_id is not None:
        items = [c for c in items if c["target_line_id"] == target_line_id]
    if source_return_id is not None:
        items = [c for c in items if c["source_warranty_return_id"] == source_return_id]
    if origin is not None:
        items = [c for c in items if c["origin"] == origin]
    if status is not None:
        items = [c for c in items if c["status"] == status]

    items = lookup.sort_created(items)
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.engineering_change_out(c) for c in window], limit, offset, total)


@change_bp.post("/engineering-changes/<change_id>/submit")
@endpoint([ENGINEERING_LEAD])
def submit_change(change_id):
    change = lookup.must(lookup.ENGINEERING_CHANGE, change_id)
    if change["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")
    change["status"] = "SUBMITTED"
    change["submitted_by_user_id"] = g.user_id
    touch(change)
    services.mark_part_change_pending(change["affected_part_id"])
    return response.ok(ser.engineering_change_out(change))


@change_bp.post("/engineering-changes/<change_id>/start-review")
@endpoint([ENGINEERING_LEAD])
def start_review(change_id):
    change = lookup.must(lookup.ENGINEERING_CHANGE, change_id)
    if change["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    change["status"] = "UNDER_REVIEW"
    touch(change)
    return response.ok(ser.engineering_change_out(change))


@change_bp.post("/engineering-changes/<change_id>/decide")
@endpoint([ENGINEERING_LEAD])
def decide_change(change_id):
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    v.opt_str(body, "note")
    change = lookup.must(lookup.ENGINEERING_CHANGE, change_id)

    # 8 — segregation of duties
    if change["submitted_by_user_id"] is not None and change["submitted_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # 9 — state
    if change["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    change["decided_by_user_id"] = g.user_id
    if decision == "APPROVE":
        change["status"] = "APPROVED"
        touch(change)
    elif decision == "REJECT":
        change["status"] = "REJECTED"
        touch(change)
        services.maybe_release_part(change["affected_part_id"], exclude_change_id=change["id"])
    else:
        change["revision_round"] += 1
        if change["revision_round"] > calc.EC_MAX_REVISION_ROUNDS:
            change["status"] = "CANCELLED"
            touch(change)
            services.maybe_release_part(change["affected_part_id"], exclude_change_id=change["id"])
        else:
            change["status"] = "REVISION_REQUESTED"
            touch(change)
    return response.ok(ser.engineering_change_out(change))


@change_bp.post("/engineering-changes/<change_id>/cut-in")
@endpoint([ENGINEERING_LEAD])
def cut_in(change_id):
    body = v.body()
    replacement_part_id = v.opt_str(body, "replacement_part_id", min_len=1)
    new_qty = v.opt_num(body, "new_qty_per_unit", exclusive_min=0)
    change = lookup.must(lookup.ENGINEERING_CHANGE, change_id)
    lookup.must_fk(lookup.PART, replacement_part_id)

    effective_replacement = (replacement_part_id if replacement_part_id is not None
                             else change["replacement_part_id"])
    services.cut_in_change(change, effective_replacement, new_qty)
    return response.ok(ser.engineering_change_out(change))


# =========================================================================== #
# WarrantyReturn
# =========================================================================== #
@change_bp.post("/warranty-returns")
@endpoint([WARRANTY_ANALYST])
def create_warranty_return():
    body = v.body()
    production_unit_id = v.req_str(body, "production_unit_id")
    failure_code = v.req_str(body, "failure_code")
    field_hours = v.req_num(body, "field_hours", minimum=0)
    returned_at = v.opt_dt(body, "returned_at")

    unit = lookup.must(lookup.PRODUCTION_UNIT, production_unit_id)
    if unit["assembly_status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE")

    ret = new_record()
    ret.update({
        "production_unit_id": production_unit_id,
        "failure_code": failure_code,
        "field_hours": field_hours,
        "returned_at": returned_at if returned_at is not None else db.clock,
        "teardown_started_at": None,
        "disposition": None,
        "root_cause_part_id": None,
        "engineering_change_id": None,
        "design_feedback_note": None,
        "status": "RECEIVED",
    })
    db.warranty_returns[ret["id"]] = ret
    return response.created(ser.warranty_return_out(ret))


@change_bp.get("/warranty-returns/<return_id>")
@endpoint([PLANT_ADMIN, ENGINEERING_LEAD, WARRANTY_ANALYST, QUALITY_INSPECTOR])
def read_warranty_return(return_id):
    ret = lookup.must(lookup.WARRANTY_RETURN, return_id)
    return response.ok(ser.warranty_return_out(ret))


@change_bp.get("/warranty-returns")
@endpoint([PLANT_ADMIN, ENGINEERING_LEAD, WARRANTY_ANALYST, QUALITY_INSPECTOR])
def list_warranty_returns():
    limit, offset = v.pagination()
    production_unit_id = v.q_str("production_unit_id")
    root_cause_part_id = v.q_str("root_cause_part_id")
    change_id = v.q_str("engineering_change_id")
    disposition = v.q_enum("disposition", DISPOSITIONS)
    status = v.q_enum("status", RETURN_STATUSES)

    lookup.must_fk(lookup.PRODUCTION_UNIT, production_unit_id)
    lookup.must_fk(lookup.PART, root_cause_part_id)
    lookup.must_fk(lookup.ENGINEERING_CHANGE, change_id)

    items = list(db.warranty_returns.values())
    if production_unit_id is not None:
        items = [w for w in items if w["production_unit_id"] == production_unit_id]
    if root_cause_part_id is not None:
        items = [w for w in items if w["root_cause_part_id"] == root_cause_part_id]
    if change_id is not None:
        items = [w for w in items if w["engineering_change_id"] == change_id]
    if disposition is not None:
        items = [w for w in items if w["disposition"] == disposition]
    if status is not None:
        items = [w for w in items if w["status"] == status]

    items.sort(key=lambda w: (w["returned_at"], w["created_at"], w["_seq"]))
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.warranty_return_out(w) for w in window], limit, offset, total)


@change_bp.post("/warranty-returns/<return_id>/teardown")
@endpoint([WARRANTY_ANALYST])
def teardown(return_id):
    ret = lookup.must(lookup.WARRANTY_RETURN, return_id)
    if ret["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    ret["status"] = "TEARDOWN"
    ret["teardown_started_at"] = db.clock
    touch(ret)
    return response.ok(ser.warranty_return_out(ret))


def _historical_bom(unit):
    slot = db.build_slots.get(unit["build_slot_id"])
    if slot is None:
        return {}
    return calc.resolve_bom(slot["model_variant_id"], unit["built_at_sequence_index"],
                            include_superseded=True)


@change_bp.post("/warranty-returns/<return_id>/analyze")
@endpoint([WARRANTY_ANALYST])
def analyze(return_id):
    body = v.body()
    disposition = v.req_enum(body, "disposition", DISPOSITIONS)
    root_cause_part_id = v.opt_str(body, "root_cause_part_id", min_len=1)
    if disposition in ("DESIGN_DEFECT", "SUPPLIER_DEFECT") and root_cause_part_id is None:
        raise invalid("root_cause_part_id is required for this disposition")
    if disposition == "NO_FAULT_FOUND" and root_cause_part_id is not None:
        raise invalid("root_cause_part_id must be absent for NO_FAULT_FOUND")

    ret = lookup.must(lookup.WARRANTY_RETURN, return_id)
    part = lookup.must_fk(lookup.PART, root_cause_part_id)

    # 9 — state
    if ret["status"] != "TEARDOWN":
        raise ApiError("ERR_INVALID_STATE")

    unit = db.production_units.get(ret["production_unit_id"])
    if part is not None:
        # 15 — the charged part must appear on the unit's as-built BOM
        bom = _historical_bom(unit) if unit is not None else {}
        if not any(line["part_id"] == part["id"] for line in bom.values()):
            raise ApiError("ERR_BOM_NOT_EFFECTIVE")

    # --- BRANCH C ---------------------------------------------------------- #
    if disposition == "NO_FAULT_FOUND":
        ret["disposition"] = "NO_FAULT_FOUND"
        ret["status"] = "CLOSED"
        touch(ret)
        return response.ok(ser.warranty_return_out(ret))

    ret["disposition"] = disposition
    ret["root_cause_part_id"] = part["id"]
    ret["status"] = "ANALYZED_DESIGN" if disposition == "DESIGN_DEFECT" else "ANALYZED_SUPPLIER"

    part["field_failure_count"] += 1
    metrics = services.recompute_part_cohort_rate(part)
    touch(part)

    if disposition == "DESIGN_DEFECT":
        # BRANCH A — mint a WARRANTY-origin change when the trigger is breached
        if metrics["cohort_failure_rate_per_1000"] >= calc.WARRANTY_RATE_TRIGGER:
            minted = services.mint_warranty_change(ret, unit, part)
            ret["engineering_change_id"] = minted["id"]
    else:
        # BRANCH B — charge the supplier, no change is minted
        supplier = db.suppliers.get(part["supplier_id"])
        if supplier is not None:
            supplier["quality_penalty_count"] += 1
            services.rescore_supplier(supplier)

    touch(ret)
    return response.ok(ser.warranty_return_out(ret))


@change_bp.post("/warranty-returns/<return_id>/close")
@endpoint([WARRANTY_ANALYST])
def close_return(return_id):
    body = v.body()
    note = v.opt_str(body, "design_feedback_note")
    ret = lookup.must(lookup.WARRANTY_RETURN, return_id)
    if ret["status"] not in ANALYZED:
        raise ApiError("ERR_INVALID_STATE")
    ret["status"] = "CLOSED"
    if note is not None:
        ret["design_feedback_note"] = note
    touch(ret)
    return response.ok(ser.warranty_return_out(ret))


@change_bp.post("/warranty-returns/<return_id>/withdraw")
@endpoint([WARRANTY_ANALYST])
def withdraw_return(return_id):
    body = v.body()
    v.opt_str(body, "reason")
    ret = lookup.must(lookup.WARRANTY_RETURN, return_id)
    if ret["status"] not in ANALYZED:
        raise ApiError("ERR_INVALID_STATE")

    was_supplier_defect = ret["disposition"] == "SUPPLIER_DEFECT"
    part = db.parts.get(ret["root_cause_part_id"])

    # COMPENSATION 1 — the attribution is withdrawn, the part id kept for audit
    ret["disposition"] = "NO_FAULT_FOUND"
    ret["status"] = "CLOSED"

    # COMPENSATION 2 — defect attribution conservation
    if part is not None:
        if part["field_failure_count"] > 0:
            part["field_failure_count"] -= 1
        services.recompute_part_cohort_rate(part)
        touch(part)

    # COMPENSATION 3a — refund the supplier quality charge
    if was_supplier_defect and part is not None:
        supplier = db.suppliers.get(part["supplier_id"])
        if supplier is not None and supplier["quality_penalty_count"] > 0:
            supplier["quality_penalty_count"] -= 1
            services.rescore_supplier(supplier)

    # COMPENSATION 3b — cancel a still-open WARRANTY-origin change
    change = db.engineering_changes.get(ret["engineering_change_id"])
    if (change is not None and change["origin"] == "WARRANTY"
            and change["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW")):
        change["status"] = "CANCELLED"
        touch(change)
        services.maybe_release_part(change["affected_part_id"], exclude_change_id=change["id"])

    touch(ret)
    return response.ok(ser.warranty_return_out(ret))
