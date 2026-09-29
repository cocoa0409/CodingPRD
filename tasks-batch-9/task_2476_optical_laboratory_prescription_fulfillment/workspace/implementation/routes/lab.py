"""Lab jobs, shop operations and quality inspections (PRD 3.5 - 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers as S
import services
from auth import acting_user_id, require_roles
from envelope import created, listing, ok
from errors import ApiError
from store import db, now, sorted_rows, stamp_common, stamp_event, touch
from validate import F, json_body, parse_datetime, validate_body

bp = Blueprint("lab", __name__)

MAX_WINDOW_HOURS = 8


# --- LabJob ----------------------------------------------------------------

@bp.post("/lab-jobs")
def create_lab_job():
    body = json_body()
    data = validate_body(body, [F("rx_order_id", "string")])
    order = services.get_or_404(db.rx_orders, data["rx_order_id"], "ERR_RX_ORDER_NOT_FOUND")
    require_roles("LabTechnician")

    if services.active_job(order["id"]) is not None:
        raise ApiError("ERR_ACTIVE_LAB_JOB_EXISTS")
    if order["fulfillment_status"] not in ("LAYOUT_READY", "REMAKE_PENDING"):
        raise ApiError("ERR_ORDER_STATE_INVALID")

    layout = services.newest_layout(order["id"])
    if layout is None or layout["layout_status"] != "COMPUTED":
        raise ApiError("ERR_LAYOUT_NOT_USABLE")

    design = services.order_design(order)
    rx = services.order_prescription(order)
    route = calc.determine_route(design, rx)

    lot = None
    if route == "SURFACE_AND_EDGE":
        lot = calc.select_blank_lot(
            sorted_rows(db.lens_blank_lots), order["lens_design_id"],
            layout["required_blank_diameter_mm"],
        )
        if lot is None:
            raise ApiError("ERR_NO_ELIGIBLE_BLANK_LOT")

    job = stamp_common(
        {
            "rx_order_id": order["id"],
            "frame_layout_id": layout["id"],
            "blank_lot_id": lot["id"] if lot is not None else None,
            "route": route,
            "status": "QUEUED",
            "rework_cycle_count": 0,
            "breakage_count": 0,
            "released_at": None,
            "scrap_reason": None,
            "_holds_allocation": False,
        }
    )
    if lot is not None:
        services.allocate_blank(lot)
        job["_holds_allocation"] = True
    db.lab_jobs[job["id"]] = job

    order["fulfillment_status"] = "IN_LAB"
    services.repromise(order, route, "ROUTE_ACTUAL")
    touch(order)
    return created(S.lab_job(job))


@bp.get("/lab-jobs/<rid>")
def get_lab_job(rid):
    row = services.get_or_404(db.lab_jobs, rid, "ERR_LAB_JOB_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    return ok(S.lab_job(row))


@bp.get("/lab-jobs")
def list_lab_jobs():
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    rows = sorted_rows(db.lab_jobs)
    for arg in ("rx_order_id", "frame_layout_id", "blank_lot_id", "status", "route"):
        value = request.args.get(arg)
        if value:
            rows = [r for r in rows if r.get(arg) == value]
    return listing(rows, S.lab_job)


@bp.post("/lab-jobs/<rid>/release")
def release_lab_job(rid):
    job = services.get_or_404(db.lab_jobs, rid, "ERR_LAB_JOB_NOT_FOUND")
    require_roles("LabTechnician")
    if job["status"] != "PASSED":
        raise ApiError("ERR_LAB_JOB_STATE_INVALID")
    services.release_job_allocation(job, "consume")
    job["status"] = "RELEASED"
    job["released_at"] = now()
    touch(job)

    order = db.rx_orders.get(job["rx_order_id"])
    if order is not None:
        if order["fulfillment_status"] == "IN_LAB":
            order["fulfillment_status"] = "LAB_COMPLETE"
        if order["promised_due_at"] is not None and now() > order["promised_due_at"]:
            order["tat_commitment_status"] = "BREACHED"
        touch(order)
    return ok(S.lab_job(job))


# --- LabOperation ----------------------------------------------------------

def _occupying_ops(field, value, exclude_id=None):
    out = []
    for op in sorted_rows(db.lab_operations):
        if op.get(field) != value:
            continue
        if op["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if exclude_id is not None and op["id"] == exclude_id:
            continue
        out.append(op)
    return out


@bp.post("/lab-operations")
def create_lab_operation():
    body = json_body()
    data = validate_body(
        body,
        [
            F("lab_job_id", "string"),
            F("expected_lab_job_version", "int"),
            F("operation_type", "enum", enum=("SURFACING", "EDGING")),
            F("window_start", "datetime"),
            F("window_end", "datetime"),
            F("machine_id", "string", required=False),
            F("bay_id", "string", required=False),
        ],
    )
    job = services.get_or_404(db.lab_jobs, data["lab_job_id"], "ERR_LAB_JOB_NOT_FOUND")
    machine = None
    bay = None
    if data["machine_id"] is not None:
        machine = services.get_or_404(db.lab_machines, data["machine_id"], "ERR_LAB_MACHINE_NOT_FOUND")
    if data["bay_id"] is not None:
        bay = services.get_or_404(db.finishing_bays, data["bay_id"], "ERR_FINISHING_BAY_NOT_FOUND")
    require_roles("LabTechnician")

    if data["expected_lab_job_version"] != job["version"]:
        raise ApiError("ERR_STALE_LAB_JOB_VERSION")

    start = parse_datetime(data["window_start"])
    end = parse_datetime(data["window_end"])
    if end <= start or (end - start) > timedelta(hours=MAX_WINDOW_HOURS):
        raise ApiError("ERR_OPERATION_WINDOW_INVALID")

    op_type = data["operation_type"]
    if op_type == "SURFACING":
        if machine is None or machine["machine_type"] != "GENERATOR" or bay is not None:
            raise ApiError("ERR_RESOURCE_TYPE_MISMATCH")
    else:
        if bay is None or machine is not None:
            raise ApiError("ERR_RESOURCE_TYPE_MISMATCH")

    if op_type == "SURFACING" and job["route"] == "STOCK_EDGE_ONLY":
        raise ApiError("ERR_OPERATION_NOT_PERMITTED_FOR_ROUTE")

    if op_type == "SURFACING":
        if machine["status"] != "AVAILABLE":
            raise ApiError("ERR_MACHINE_NOT_AVAILABLE")
        if calc.machine_window_conflict(
            _occupying_ops("machine_id", machine["id"]), start, end,
            machine["calibration_buffer_minutes"],
        ):
            raise ApiError("ERR_MACHINE_WINDOW_CONFLICT")
    else:
        if bay["status"] != "OPEN":
            raise ApiError("ERR_BAY_NOT_OPEN")
        overlapping = calc.bay_overlap_count(_occupying_ops("bay_id", bay["id"]), start, end)
        if overlapping >= bay["concurrent_capacity"]:
            raise ApiError("ERR_BAY_CAPACITY_EXCEEDED")

    op = stamp_common(
        {
            "lab_job_id": job["id"],
            "machine_id": machine["id"] if machine is not None else None,
            "bay_id": bay["id"] if bay is not None else None,
            "blank_lot_id": job["blank_lot_id"] if op_type == "SURFACING" else None,
            "operation_type": op_type,
            "window_start": start,
            "window_end": end,
            "status": "SCHEDULED",
            "performed_by_user_id": None,
            "breakage_reason": None,
            "cancel_reason": None,
        }
    )
    db.lab_operations[op["id"]] = op
    touch(job)
    return created(S.lab_operation(op))


@bp.get("/lab-operations/<rid>")
def get_lab_operation(rid):
    row = services.get_or_404(db.lab_operations, rid, "ERR_LAB_OPERATION_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    return ok(S.lab_operation(row))


@bp.get("/lab-operations")
def list_lab_operations():
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    rows = sorted_rows(db.lab_operations)
    for arg in ("lab_job_id", "machine_id", "bay_id", "blank_lot_id", "operation_type", "status"):
        value = request.args.get(arg)
        if value:
            rows = [r for r in rows if r.get(arg) == value]
    return listing(rows, S.lab_operation)


def _job_admits(job, op_type):
    if op_type == "SURFACING":
        return job["route"] == "SURFACE_AND_EDGE" and job["status"] in ("QUEUED", "REWORK_QUEUED")
    if job["status"] in ("SURFACED", "REWORK_QUEUED"):
        return True
    return job["status"] == "QUEUED" and job["route"] == "STOCK_EDGE_ONLY"


@bp.post("/lab-operations/<rid>/start")
def start_lab_operation(rid):
    op = services.get_or_404(db.lab_operations, rid, "ERR_LAB_OPERATION_NOT_FOUND")
    user_id, _role = require_roles("LabTechnician")
    if op["status"] != "SCHEDULED":
        raise ApiError("ERR_OPERATION_STATE_INVALID")
    job = db.lab_jobs.get(op["lab_job_id"])
    if not _job_admits(job, op["operation_type"]):
        raise ApiError("ERR_LAB_JOB_STATE_INVALID")
    if op["operation_type"] == "SURFACING":
        machine = db.lab_machines.get(op["machine_id"])
        if machine is None or machine["status"] != "AVAILABLE":
            raise ApiError("ERR_MACHINE_NOT_AVAILABLE")
    else:
        bay = db.finishing_bays.get(op["bay_id"])
        if bay is None or bay["status"] != "OPEN":
            raise ApiError("ERR_BAY_NOT_OPEN")

    op["status"] = "RUNNING"
    op["performed_by_user_id"] = user_id
    touch(op)
    job["status"] = "SURFACING" if op["operation_type"] == "SURFACING" else "EDGING"
    touch(job)
    return ok(S.lab_operation(op))


@bp.post("/lab-operations/<rid>/complete")
def complete_lab_operation(rid):
    op = services.get_or_404(db.lab_operations, rid, "ERR_LAB_OPERATION_NOT_FOUND")
    require_roles("LabTechnician")
    if op["status"] != "RUNNING":
        raise ApiError("ERR_OPERATION_STATE_INVALID")
    op["status"] = "COMPLETED"
    touch(op)
    job = db.lab_jobs.get(op["lab_job_id"])
    if job is not None:
        job["status"] = "SURFACED" if op["operation_type"] == "SURFACING" else "EDGED"
        touch(job)
    return ok(S.lab_operation(op))


@bp.post("/lab-operations/<rid>/report-breakage")
def report_breakage(rid):
    body = json_body()
    data = validate_body(body, [F("breakage_reason", "string", min_len=1)])
    op = services.get_or_404(db.lab_operations, rid, "ERR_LAB_OPERATION_NOT_FOUND")
    require_roles("LabTechnician")
    if op["status"] != "RUNNING":
        raise ApiError("ERR_OPERATION_STATE_INVALID")
    if op["operation_type"] == "EDGING":
        raise ApiError("ERR_BREAKAGE_NOT_APPLICABLE")

    job = db.lab_jobs.get(op["lab_job_id"])
    op["status"] = "BROKEN"
    op["breakage_reason"] = data["breakage_reason"]
    touch(op)

    broken_lot_id = job["blank_lot_id"]
    services.release_job_allocation(job, "scrap")
    job["breakage_count"] += 1

    layout = db.frame_layouts.get(job["frame_layout_id"])
    replacement = calc.select_blank_lot(
        sorted_rows(db.lens_blank_lots),
        db.rx_orders[job["rx_order_id"]]["lens_design_id"],
        layout["required_blank_diameter_mm"] if layout is not None else 0,
        exclude_lot_id=broken_lot_id,
    )
    if replacement is not None:
        services.allocate_blank(replacement)
        job["blank_lot_id"] = replacement["id"]
        job["_holds_allocation"] = True
        job["status"] = "QUEUED"
        touch(job)
    else:
        job["blank_lot_id"] = None
        job["status"] = "BLANK_BACKORDER"
        touch(job)
        order = db.rx_orders.get(job["rx_order_id"])
        if order is not None:
            order["_backorder_count"] = order.get("_backorder_count", 0) + 1
            if order["promised_due_at"] is not None:
                order["promised_due_at"] = order["promised_due_at"] + timedelta(
                    hours=calc.BACKORDER_EXTENSION_HOURS
                )
            order["tat_commitment_status"] = "AT_RISK"
            touch(order)
    return ok(S.lab_operation(op))


@bp.post("/lab-operations/<rid>/cancel")
def cancel_lab_operation(rid):
    body = json_body()
    data = validate_body(body, [F("cancel_reason", "string", min_len=1)])
    op = services.get_or_404(db.lab_operations, rid, "ERR_LAB_OPERATION_NOT_FOUND")
    require_roles("LabTechnician")
    if op["status"] != "SCHEDULED":
        raise ApiError("ERR_OPERATION_STATE_INVALID")
    op["status"] = "CANCELLED"
    op["cancel_reason"] = data["cancel_reason"]
    touch(op)
    job = db.lab_jobs.get(op["lab_job_id"])
    if job is not None:
        touch(job)
    return ok(S.lab_operation(op))


# --- QualityInspection -----------------------------------------------------

def _select_standard(design_type, reference_power_abs):
    candidates = []
    today = now().date().isoformat()
    for std in sorted_rows(db.tolerance_standards):
        if std["design_type"] != design_type:
            continue
        if std["effective_from"] > today:
            continue
        if calc.D(reference_power_abs) < calc.D(std["power_band_min_abs"]):
            continue
        if calc.D(reference_power_abs) > calc.D(std["power_band_max_abs"]):
            continue
        candidates.append(std)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["effective_from"], s["_seq"]), reverse=True)
    return candidates[0]


@bp.post("/quality-inspections")
def create_quality_inspection():
    body = json_body()
    data = validate_body(
        body,
        [
            F("lab_job_id", "string"),
            F("eye", "enum", enum=("OD", "OS")),
            F("measured_sphere", "number"),
            F("measured_cylinder", "number"),
            F("measured_axis", "int", required=False, minimum=0, maximum=180),
            F("measured_prism", "number"),
            F("cosmetic_defect_codes", "array", item_kind="string", required=False, default=None),
        ],
    )
    job = services.get_or_404(db.lab_jobs, data["lab_job_id"], "ERR_LAB_JOB_NOT_FOUND")
    user_id, _role = require_roles("QualityInspector")

    if job["status"] != "EDGED":
        raise ApiError("ERR_LAB_JOB_STATE_INVALID")

    cycle = job["rework_cycle_count"]
    for existing in services.job_inspections(job["id"]):
        if existing["eye"] == data["eye"] and existing["cycle_index"] == cycle:
            raise ApiError("ERR_EYE_ALREADY_INSPECTED_THIS_CYCLE")

    defects = data["cosmetic_defect_codes"] or []
    for code in defects:
        if code not in calc.COSMETIC_DEFECT_CODES:
            raise ApiError("ERR_UNKNOWN_DEFECT_CODE")

    order = db.rx_orders.get(job["rx_order_id"])
    design = services.order_design(order)
    rx = services.order_prescription(order)
    eye = data["eye"].lower()
    rx_sphere = rx["sphere_" + eye]
    rx_cylinder = rx["cylinder_" + eye]
    rx_axis = rx["axis_" + eye]
    rx_prism = rx["prism_diopter_" + eye]

    standard = _select_standard(design["design_type"], abs(calc.D(rx_sphere)))
    if standard is None:
        raise ApiError("ERR_NO_TOLERANCE_STANDARD")

    for other in services.job_operations(job["id"]):
        if other["status"] == "COMPLETED" and other["performed_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    sphere_delta, cylinder_delta, axis_delta, prism_delta = calc.inspection_deltas(
        data["measured_sphere"], data["measured_cylinder"], data["measured_axis"],
        data["measured_prism"], rx_sphere, rx_cylinder, rx_axis, rx_prism,
    )
    failed, verdict = calc.inspection_verdict(
        sphere_delta, cylinder_delta, axis_delta, prism_delta, rx_cylinder, defects, standard
    )

    row = stamp_event(
        {
            "lab_job_id": job["id"],
            "tolerance_standard_id": standard["id"],
            "eye": data["eye"],
            "measured_sphere": data["measured_sphere"],
            "measured_cylinder": data["measured_cylinder"],
            "measured_axis": data["measured_axis"],
            "measured_prism": data["measured_prism"],
            "cosmetic_defect_codes": list(defects),
            "inspector_user_id": user_id,
            "cycle_index": cycle,
            "sphere_delta": float(sphere_delta),
            "cylinder_delta": float(cylinder_delta),
            "axis_delta": axis_delta,
            "prism_delta": float(prism_delta),
            "verdict": verdict,
            "failed_metrics": failed,
        }
    )
    db.quality_inspections[row["id"]] = row

    if verdict == "PASS":
        other_eye = "OS" if data["eye"] == "OD" else "OD"
        joined = any(
            i["eye"] == other_eye and i["cycle_index"] == cycle and i["verdict"] == "PASS"
            for i in services.job_inspections(job["id"])
        )
        if joined:
            job["status"] = "PASSED"
            touch(job)
    else:
        if cycle < 2:
            job["status"] = "REWORK_QUEUED"
            job["rework_cycle_count"] = cycle + 1
            touch(job)
        else:
            services.release_job_allocation(job, "scrap")
            job["status"] = "SCRAPPED"
            job["scrap_reason"] = "REWORK_LIMIT"
            touch(job)
    return created(S.quality_inspection(row))


@bp.get("/quality-inspections/<rid>")
def get_quality_inspection(rid):
    row = services.get_or_404(db.quality_inspections, rid, "ERR_QUALITY_INSPECTION_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    return ok(S.quality_inspection(row))


@bp.get("/quality-inspections")
def list_quality_inspections():
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    rows = sorted_rows(db.quality_inspections)
    for arg in ("lab_job_id", "tolerance_standard_id", "eye", "verdict"):
        value = request.args.get(arg)
        if value:
            rows = [r for r in rows if r.get(arg) == value]
    cycle = request.args.get("cycle_index")
    if cycle not in (None, ""):
        try:
            wanted = int(cycle)
        except (TypeError, ValueError):
            wanted = None
        if wanted is not None:
            rows = [r for r in rows if r["cycle_index"] == wanted]
    return listing(rows, S.quality_inspection)
