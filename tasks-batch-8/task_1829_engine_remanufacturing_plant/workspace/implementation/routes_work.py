"""Work orders, machining operations, and components (PRD 3.5, 3.6, 3.7)."""

from flask import Blueprint, request

import envelope
import serializers
from auth import ALL_READ_ROLES, authorized
from errors import (
    ERR_COMPONENT_QUARANTINED,
    ERR_CORE_RETURN_NOT_GRADED,
    ERR_INTERCHANGE_INCOMPATIBLE,
    ERR_INVALID_STATE,
    ERR_OPERATIONS_INCOMPLETE,
    ERR_REUSE_GRADE_INSUFFICIENT,
    ERR_ROUTE_SEQUENCE_VIOLATION,
    ERR_SPEC_NOT_ACTIVE,
    ERR_STALE_VERSION,
    ERR_STATION_SCHEDULE_OVERLAP,
    ERR_VALIDATION,
    raise_error,
)
from services import create_engine, get_or_404
from store import db, stamp_new, sorted_rows, touch
from validate import (
    check_allowed_fields,
    filter_enum,
    get_body,
    pagination,
    req_bool,
    req_enum,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("work", __name__)

WORK_ORDER_STATUSES = {
    "QUEUED",
    "TEARDOWN",
    "MACHINING",
    "ASSEMBLY",
    "DYNO_TEST",
    "CLOSED",
    "CANCELLED",
}
OPERATION_STATUSES = {"PENDING", "COMPLETED", "FAILED"}
COMPONENT_STATUSES = {"AVAILABLE", "QUARANTINED", "CONSUMED", "SCRAPPED"}
PART_TYPES = {"CRANKSHAFT", "CYLINDER_HEAD", "ENGINE_BLOCK", "CAMSHAFT"}
OP_TYPES = {"BORE", "DECK", "CRANK_GRIND"}
REUSE_GRADES = {"REUSE_OK", "REWORK", "SCRAP"}

# Statuses in which route declaration is allowed.
ROUTE_DECLARABLE = {"QUEUED", "TEARDOWN", "MACHINING"}
# Statuses from which a work order can be cancelled.
CANCELLABLE = {"QUEUED", "TEARDOWN", "MACHINING", "ASSEMBLY"}


def _wo_ops(work_order_id):
    return [o for o in db.operations.values() if o["work_order_id"] == work_order_id]


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, ["core_return_id"])
    core_return_id = req_str(body, "core_return_id")
    core_return = get_or_404("core_returns", core_return_id)

    # PRD 3.5 narrative order: the source-return check is listed first.
    if core_return["status"] not in ("GRADED", "CLOSED") or core_return["grade"] == "REJECT":
        raise_error(
            ERR_CORE_RETURN_NOT_GRADED,
            "the source core return must be GRADED or CLOSED with a grade other than REJECT",
        )
    spec = db.build_specs[core_return["build_spec_id"]]
    if spec["status"] != "ACTIVE":
        raise_error(ERR_SPEC_NOT_ACTIVE, "the build spec must be ACTIVE")

    record = {
        "core_return_id": core_return_id,
        "build_spec_id": core_return["build_spec_id"],
        "status": "QUEUED",
        "reman_engine_id": None,
        "rework_count": 0,
    }
    stamp_new(record)
    db.work_orders[record["id"]] = record
    return envelope.created(serializers.work_order(record))


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_return = request.args.get("core_return_id")
    f_spec = request.args.get("build_spec_id")
    f_engine = request.args.get("reman_engine_id")
    f_status = filter_enum("status", WORK_ORDER_STATUSES)
    rows = list(db.work_orders.values())
    if f_return is not None:
        rows = [r for r in rows if r["core_return_id"] == f_return]
    if f_spec is not None:
        rows = [r for r in rows if r["build_spec_id"] == f_spec]
    if f_engine is not None:
        rows = [r for r in rows if r["reman_engine_id"] == f_engine]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.work_order(r) for r in page], limit, offset, total)


@bp.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("work_orders", rid)
    return envelope.ok(serializers.work_order(record))


@bp.route("/work-orders/<rid>/advance", methods=["POST"])
def advance_work_order(rid):
    authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(body, ["target"])
    target = req_enum(body, "target", WORK_ORDER_STATUSES)
    wo = get_or_404("work_orders", rid)

    current = wo["status"]
    if current == "QUEUED" and target == "TEARDOWN":
        wo["status"] = "TEARDOWN"
    elif current == "TEARDOWN" and target == "MACHINING":
        # The route plan must be declared before machining begins.
        if not _wo_ops(wo["id"]):
            raise_error(
                ERR_INVALID_STATE,
                "at least one machine operation must be declared before machining",
            )
        wo["status"] = "MACHINING"
    elif current == "MACHINING" and target == "ASSEMBLY":
        for op in _wo_ops(wo["id"]):
            if op["status"] != "COMPLETED":
                raise_error(
                    ERR_OPERATIONS_INCOMPLETE,
                    "advancing to ASSEMBLY requires every machine operation to be COMPLETED",
                )
        if wo["reman_engine_id"] is None:
            engine = create_engine(wo)
            wo["reman_engine_id"] = engine["id"]
        wo["status"] = "ASSEMBLY"
    elif current == "ASSEMBLY" and target == "DYNO_TEST":
        wo["status"] = "DYNO_TEST"
    elif current == "DYNO_TEST" and target == "MACHINING":
        # Rework loop: permitted only when the latest dyno result is FAIL.
        engine = db.engines.get(wo["reman_engine_id"])
        if engine is None or engine["latest_dyno_result"] != "FAIL":
            raise_error(
                ERR_INVALID_STATE,
                "rework requires the engine's latest dyno result to be FAIL",
            )
        wo["rework_count"] += 1
        for op in _wo_ops(wo["id"]):
            if op["status"] == "FAILED":
                op["status"] = "PENDING"
                op["station_code"] = None
                op["scheduled_start"] = None
                op["scheduled_end"] = None
                op["result"] = None
                op["_start_dt"] = None
                op["_end_dt"] = None
                touch(op)
        wo["status"] = "MACHINING"
    else:
        raise_error(
            ERR_INVALID_STATE,
            "cannot advance a %s work order to %s" % (current, target),
        )

    touch(wo)  # each advance increments version by 1
    return envelope.ok(serializers.work_order(wo))


@bp.route("/work-orders/<rid>/cancel", methods=["POST"])
def cancel_work_order(rid):
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, [])
    wo = get_or_404("work_orders", rid)
    if wo["status"] not in CANCELLABLE:
        raise_error(
            ERR_INVALID_STATE,
            "a work order can be cancelled only from QUEUED, TEARDOWN, MACHINING, or ASSEMBLY",
        )

    # COMPONENT RELEASE compensation: every component consumed by this order
    # flips back to AVAILABLE with the link cleared.
    for comp in db.components.values():
        if comp["consumed_by_work_order_id"] == wo["id"] and comp["status"] == "CONSUMED":
            comp["status"] = "AVAILABLE"
            comp["consumed_by_work_order_id"] = None
            touch(comp)

    # Cancellation from ASSEMBLY scraps the half-built engine.
    if wo["status"] == "ASSEMBLY" and wo["reman_engine_id"] is not None:
        engine = db.engines.get(wo["reman_engine_id"])
        if engine is not None and engine["status"] == "BUILT":
            engine["status"] = "SCRAPPED"
            touch(engine)

    wo["status"] = "CANCELLED"
    touch(wo)
    return envelope.ok(serializers.work_order(wo))


# ---------------------------------------------------------------------------
# Machining operations
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<rid>/operations", methods=["POST"])
def create_operation(rid):
    authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(body, ["op_type", "sequence", "expected_work_order_version"])
    op_type = req_enum(body, "op_type", OP_TYPES)
    sequence = req_int(body, "sequence", minimum=1)
    expected_version = req_int(body, "expected_work_order_version")

    wo = get_or_404("work_orders", rid)

    # Body well-formedness: sequence must equal the 1-based position of op_type
    # in the spec's required_op_sequence.
    spec = db.build_specs[wo["build_spec_id"]]
    try:
        expected_position = spec["required_op_sequence"].index(op_type) + 1
    except ValueError:
        expected_position = None
    if expected_position is None or sequence != expected_position:
        raise_error(
            ERR_VALIDATION,
            "sequence must equal the 1-based position of %s in the spec's "
            "required_op_sequence" % op_type,
        )

    if wo["status"] not in ROUTE_DECLARABLE:
        raise_error(
            ERR_INVALID_STATE,
            "operations may be declared only while the work order is QUEUED, "
            "TEARDOWN, or MACHINING",
        )

    # OCC guard on the work order version (PRD 2.9).
    if expected_version != wo["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_work_order_version does not match the work order's current version",
        )

    record = {
        "work_order_id": wo["id"],
        "op_type": op_type,
        "sequence": sequence,
        "station_code": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "result": None,
        "status": "PENDING",
        "attempt_count": 0,
        "_start_dt": None,
        "_end_dt": None,
    }
    stamp_new(record)
    db.operations[record["id"]] = record
    touch(wo)  # declaring an operation increments the work order's version
    return envelope.created(serializers.machine_operation(record))


@bp.route("/work-orders/<rid>/operations", methods=["GET"])
def list_operations(rid):
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_status = filter_enum("status", OPERATION_STATUSES)
    wo = get_or_404("work_orders", rid)
    rows = _wo_ops(wo["id"])
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.machine_operation(r) for r in page], limit, offset, total)


@bp.route("/operations/<rid>/perform", methods=["POST"])
def perform_operation(rid):
    authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(body, ["station_code", "scheduled_start", "scheduled_end", "result"])
    station_code = req_str(body, "station_code")
    start_raw, start_dt = req_instant(body, "scheduled_start")
    end_raw, end_dt = req_instant(body, "scheduled_end")
    result = req_enum(body, "result", {"PASS", "FAIL"})
    if not end_dt > start_dt:
        raise_error(ERR_VALIDATION, "scheduled_end must be strictly after scheduled_start")

    op = get_or_404("operations", rid)
    if op["status"] not in ("PENDING", "FAILED"):
        raise_error(ERR_INVALID_STATE, "COMPLETED is terminal for a machine operation")
    wo = db.work_orders[op["work_order_id"]]
    if wo["status"] != "MACHINING":
        raise_error(
            ERR_INVALID_STATE,
            "an operation may be performed only while the work order is in MACHINING",
        )

    # Station occupancy first (PRD 3.6): no other operation -- any status,
    # excluding this one (a re-perform replaces its own stored window) -- may
    # hold a stored window on the same station_code overlapping the requested
    # half-open interval [scheduled_start, scheduled_end).  Adjacency allowed.
    for other in db.operations.values():
        if other["id"] == op["id"]:
            continue
        if other["station_code"] != station_code:
            continue
        if other["_start_dt"] is None or other["_end_dt"] is None:
            continue
        if other["_start_dt"] < end_dt and start_dt < other["_end_dt"]:
            raise_error(
                ERR_STATION_SCHEDULE_OVERLAP,
                "another operation holds an overlapping window on station %s" % station_code,
            )

    # Route order second: every same-work-order operation with a smaller
    # sequence must already be COMPLETED.
    for other in _wo_ops(wo["id"]):
        if other["sequence"] < op["sequence"] and other["status"] != "COMPLETED":
            raise_error(
                ERR_ROUTE_SEQUENCE_VIOLATION,
                "operation %s (sequence %s) is not COMPLETED"
                % (other["id"], other["sequence"]),
            )

    op["station_code"] = station_code
    op["scheduled_start"] = start_raw
    op["scheduled_end"] = end_raw
    op["_start_dt"] = start_dt
    op["_end_dt"] = end_dt
    op["result"] = result
    op["status"] = "COMPLETED" if result == "PASS" else "FAILED"
    op["attempt_count"] += 1
    touch(op)
    return envelope.ok(serializers.machine_operation(op))


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<rid>/components", methods=["POST"])
def salvage_component(rid):
    authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(body, ["part_type", "interchange_group"])
    part_type = req_enum(body, "part_type", PART_TYPES)
    interchange_group = req_str(body, "interchange_group")
    wo = get_or_404("work_orders", rid)
    if wo["status"] != "TEARDOWN":
        raise_error(
            ERR_INVALID_STATE, "components may be salvaged only during TEARDOWN"
        )
    record = {
        "work_order_id": wo["id"],
        "part_type": part_type,
        "interchange_group": interchange_group,
        "reuse_grade": None,
        "status": "AVAILABLE",
        "consumed_by_work_order_id": None,
    }
    stamp_new(record)
    db.components[record["id"]] = record
    return envelope.created(serializers.component(record))


@bp.route("/work-orders/<rid>/components", methods=["GET"])
def list_components(rid):
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_status = filter_enum("status", COMPONENT_STATUSES)
    f_part = filter_enum("part_type", PART_TYPES)
    wo = get_or_404("work_orders", rid)
    rows = [c for c in db.components.values() if c["work_order_id"] == wo["id"]]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_part is not None:
        rows = [r for r in rows if r["part_type"] == f_part]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.component(r) for r in page], limit, offset, total)


@bp.route("/components/<rid>", methods=["GET"])
def get_component(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("components", rid)
    return envelope.ok(serializers.component(record))


@bp.route("/components/<rid>/inspect", methods=["POST"])
def inspect_component(rid):
    authorized(["QualityInspector"])
    body = get_body()
    check_allowed_fields(body, ["reuse_grade", "quarantine"])
    reuse_grade = req_enum(body, "reuse_grade", REUSE_GRADES)
    quarantine = req_bool(body, "quarantine")
    comp = get_or_404("components", rid)

    if comp["status"] in ("CONSUMED", "SCRAPPED"):
        raise_error(
            ERR_INVALID_STATE,
            "a %s component cannot be inspected" % comp["status"],
        )

    if reuse_grade == "SCRAP":
        # SCRAP moves the component to SCRAPPED from AVAILABLE or QUARANTINED.
        comp["reuse_grade"] = "SCRAP"
        comp["status"] = "SCRAPPED"
    elif comp["status"] == "AVAILABLE":
        comp["reuse_grade"] = reuse_grade
        if quarantine:
            comp["status"] = "QUARANTINED"
        # quarantine=false re-sets the grade while staying AVAILABLE.
    else:  # QUARANTINED
        if quarantine:
            raise_error(
                ERR_INVALID_STATE,
                "a QUARANTINED component must be released (quarantine=false) or scrapped",
            )
        comp["reuse_grade"] = reuse_grade
        comp["status"] = "AVAILABLE"

    touch(comp)
    return envelope.ok(serializers.component(comp))


@bp.route("/work-orders/<rid>/consume", methods=["POST"])
def consume_component(rid):
    authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(body, ["component_id"])
    component_id = req_str(body, "component_id")
    wo = get_or_404("work_orders", rid)
    comp = get_or_404("components", component_id)

    # General state gate first: the work order must be in ASSEMBLY, and the
    # component must be in a state that permits the transition at all.
    if wo["status"] != "ASSEMBLY":
        raise_error(
            ERR_INVALID_STATE, "components may be consumed only during ASSEMBLY"
        )
    if comp["status"] in ("CONSUMED", "SCRAPPED"):
        raise_error(
            ERR_INVALID_STATE, "a %s component cannot be consumed" % comp["status"]
        )
    # Quarantine gate, deliberately distinct from the general state check.
    if comp["status"] == "QUARANTINED":
        raise_error(ERR_COMPONENT_QUARANTINED, "the component is QUARANTINED")
    # Reuse gate.
    spec = db.build_specs[wo["build_spec_id"]]
    if comp["reuse_grade"] is None or comp["reuse_grade"] not in spec["allowed_reuse_grades"]:
        raise_error(
            ERR_REUSE_GRADE_INSUFFICIENT,
            "the component reuse grade is null or not allowed by the spec",
        )
    # Interchange gate.
    if comp["interchange_group"] not in spec["allowed_interchange_groups"]:
        raise_error(
            ERR_INTERCHANGE_INCOMPATIBLE,
            "the component interchange group is not allowed by the spec",
        )

    comp["status"] = "CONSUMED"
    comp["consumed_by_work_order_id"] = wo["id"]
    touch(comp)
    return envelope.ok(serializers.component(comp))
