"""Assembly measurements, run-in certification (PRD 3.4)."""
from flask import Blueprint

from db import store, new_id, new_common, touch
from errors import ApiError
from middleware import (get_context, require_roles, check_customer_scope,
                        owning_customer_id_of_order, ALL_ROLES)
from response import ok, created, paginate
from services import pricing, workflow
from validation import parse_body, no_body, require_path_entity, schema_field

bp = Blueprint("quality", __name__)


def _load_order(order_id):
    return require_path_entity(store.orders, order_id)


def _require_state(order, allowed):
    if order["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order status %s does not admit this action" % order["status"])


@bp.post("/reman/orders/<order_id>/assembly-records")
def add_assembly_record(order_id):
    uid, role, _ = get_context()
    require_roles(["QualityInspector"])
    order = _load_order(order_id)
    body = parse_body({
        "backlash_mm": schema_field("number"),
        "radial_clearance_mm": schema_field("number"),
        "axial_clearance_mm": schema_field("number"),
    }, allow_empty=False)
    _require_state(order, ["ASSEMBLY"])
    record = {
        "id": new_id(),
        "reman_order_id": order["id"],
        "backlash_mm": body["backlash_mm"],
        "radial_clearance_mm": body["radial_clearance_mm"],
        "axial_clearance_mm": body["axial_clearance_mm"],
        "recorded_by": uid,
        "within_tolerance": pricing.assembly_within_tolerance(
            body["backlash_mm"], body["radial_clearance_mm"],
            body["axial_clearance_mm"]),
        "status": "ACTIVE",
    }
    new_common(record)
    store.assembly_records[record["id"]] = record
    return created(record)


@bp.get("/reman/orders/<order_id>/assembly-records")
def list_assembly_records(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = _load_order(order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(paginate(workflow.assembly_records_of_order(order_id)),
              rtype="array", pagination=paginate)


@bp.post("/reman/orders/<order_id>/submit-assembly")
def submit_assembly(order_id):
    uid, role, _ = get_context()
    require_roles(["QualityInspector"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["ASSEMBLY"])
    active = [r for r in workflow.assembly_records_of_order(order["id"])
              if r["status"] == "ACTIVE"]
    if not active:
        raise ApiError("ERR_NO_ASSEMBLY_RECORD", 422,
                       "An ACTIVE assembly record is required to submit assembly")
    latest = max(active, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    if not latest["within_tolerance"]:
        raise ApiError("ERR_TOLERANCE_EXCEEDED", 422,
                       "Latest ACTIVE assembly record is out of tolerance")
    order["status"] = "RUN_IN"
    touch(order)
    return ok(order)


@bp.post("/reman/orders/<order_id>/run-in-tests")
def add_run_in_test(order_id):
    uid, role, _ = get_context()
    require_roles(["QualityInspector"])
    order = _load_order(order_id)
    body = parse_body({
        "duration_minutes": schema_field("integer"),
        "max_temp_c": schema_field("number"),
        "vibration_mm_s": schema_field("number"),
        "oil_particle_count": schema_field("integer"),
    }, allow_empty=False)
    _require_state(order, ["RUN_IN"])
    result = pricing.run_in_result(
        body["duration_minutes"], body["max_temp_c"],
        body["vibration_mm_s"], body["oil_particle_count"])
    test = {
        "id": new_id(),
        "reman_order_id": order["id"],
        "duration_minutes": body["duration_minutes"],
        "max_temp_c": body["max_temp_c"],
        "vibration_mm_s": body["vibration_mm_s"],
        "oil_particle_count": body["oil_particle_count"],
        "oil_baseline_established": result == "PASS",
        "result": result,
        "status": "RECORDED" if result == "PASS" else "SUPERSEDED",
    }
    new_common(test)
    store.run_in_tests[test["id"]] = test
    if result == "PASS":
        # RUN_IN -> READY_TO_SHIP; compute the final invoice (PRD 3.4).
        executed = [d for d in workflow.decisions_of_order(order["id"])
                    if d["approval_status"] == "APPROVED"]
        invoice = sum(d["line_total_cents"] for d in executed)
        invoice += sum(s["freight_charge_cents"]
                       for s in workflow.shipments_of_order(order["id"])
                       if s["status"] != "CANCELLED")
        order["final_invoice_cents"] = invoice
        order["status"] = "READY_TO_SHIP"
        touch(order)
    else:
        # Automatic return to build; the ACTIVE assembly record is invalidated
        # (a leaf mutation — no further cascade).
        order["status"] = "IN_BUILD"
        touch(order)
        for record in workflow.assembly_records_of_order(order["id"]):
            if record["status"] == "ACTIVE":
                record["status"] = "INVALIDATED"
                touch(record)
    return created(test)


@bp.get("/reman/orders/<order_id>/run-in-tests")
def list_run_in_tests(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = _load_order(order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(paginate(workflow.run_in_tests_of_order(order_id)),
              rtype="array", pagination=paginate)
