"""§3.4 / §3.5 MetrologyInstrument, ProcessRun and MetrologyReport routes."""

from decimal import Decimal

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, filt, get_body, need_fk, ok, ok_list,
                    pagination, path_row, v_enum, v_fk, v_int, v_num, v_str, v_ts)
from errors import ApiError
from store import ordered, store

bp = Blueprint("metrology", __name__)

INSTRUMENT_TYPES = ["PHASE_SHIFTING_INTERFEROMETER", "WHITE_LIGHT_INTERFEROMETER",
                    "AFM_PROFILOMETER"]
RUN_STAGES = ["GRINDING", "POLISHING", "FIGURING"]
STAGE_ADMISSIBLE_FROM = {
    "GRINDING": ["BLANKS_RESERVED", "GRINDING"],
    "POLISHING": ["BLANKS_RESERVED", "GRINDING", "POLISHING"],
    "FIGURING": ["POLISHING", "FIGURING"],
}
NOT_WORKABLE = ["HELD", "SCRAPPED", "CANCELLED", "RELEASED_TO_ASSEMBLY"]


# ------------------------------------------------------------- instruments
@bp.post("/optics/metrology-instruments")
def create_instrument():
    authenticate(["PlantAdmin"])
    body = get_body()

    code = v_str(body, "instrument_code", True, min_len=1, max_len=40)
    itype = v_enum(body, "instrument_type", INSTRUMENT_TYPES, False,
                   "PHASE_SHIFTING_INTERFEROMETER")
    base = v_num(body, "base_uncertainty_waves", True, gt=0)
    last_cal, last_cal_dt = v_ts(body, "last_calibrated_utc", True)
    resolution = v_num(body, "lateral_resolution_um", False, Decimal("250.0"), gt=0)
    interval = v_int(body, "calibration_interval_days", False, 90, ge=1)

    inst = store.new_row()
    inst["instrument_code"] = code
    inst["instrument_type"] = itype
    inst["base_uncertainty_waves"] = base
    inst["lateral_resolution_um"] = resolution
    inst["last_calibrated_utc"] = last_cal
    inst["calibration_interval_days"] = interval
    inst["days_since_calibration"] = 0
    inst["effective_uncertainty_waves"] = base
    inst["instrument_status"] = "CALIBRATED"
    inst["booked_minutes_total"] = 0
    inst["_last_calibrated_dt"] = last_cal_dt
    store.instruments[inst["id"]] = inst
    return ok(logic.ser_instrument(inst), 201)


@bp.get("/optics/metrology-instruments/<row_id>")
def get_instrument(row_id):
    authenticate(ALL_ROLES)
    inst = path_row(store.instruments, row_id, "ERR_INSTRUMENT_NOT_FOUND")
    return ok(logic.ser_instrument(inst))


@bp.get("/optics/metrology-instruments")
def list_instruments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.instruments.values()))
    value = filt("instrument_type")
    if value is not None:
        rows = [r for r in rows if r["instrument_type"] == value]
    value = filt("instrument_status")
    if value is not None:
        rows = [r for r in rows if logic.instrument_derived(r)[2] == value]
    return ok_list(rows, logic.ser_instrument, limit, offset)


@bp.post("/optics/metrology-instruments/<row_id>/calibrations")
def record_calibration(row_id):
    authenticate(["PlantAdmin", "MetrologyTechnician"])
    inst = path_row(store.instruments, row_id, "ERR_INSTRUMENT_NOT_FOUND")
    body = get_body()

    raw, dt = v_ts(body, "calibrated_at_utc", False)
    if raw is None:
        raw, dt = store.now_str(), store.now_dt()

    inst["last_calibrated_utc"] = raw
    inst["_last_calibrated_dt"] = dt
    days, eff, status = logic.instrument_derived(inst)
    inst["days_since_calibration"] = days
    inst["effective_uncertainty_waves"] = eff
    inst["instrument_status"] = status
    store.touch(inst)
    return ok(logic.ser_instrument(inst))


# -------------------------------------------------------------- process runs
@bp.post("/optics/process-runs")
def create_run():
    authenticate(["ProcessTechnician"])
    body = get_body()

    wo = v_fk(body, "work_order_id", store.work_orders, "ERR_WORK_ORDER_NOT_FOUND")
    inst = v_fk(body, "metrology_instrument_id", store.instruments,
                "ERR_INSTRUMENT_NOT_FOUND")

    wo = need_fk(body, "work_order_id", wo)
    inst = need_fk(body, "metrology_instrument_id", inst)
    run_stage = v_enum(body, "run_stage", RUN_STAGES, True)
    start_raw, start_dt = v_ts(body, "metrology_window_start_utc", True)
    end_raw, end_dt = v_ts(body, "metrology_window_end_utc", True)

    # priority 14 — the stage gate
    if wo["process_status"] not in STAGE_ADMISSIBLE_FROM[run_stage]:
        raise ApiError("ERR_RUN_STAGE_OUT_OF_ORDER")

    # priority 15 — at most one run in flight per order
    for other in store.runs.values():
        if (other["work_order_id"] == wo["id"]
                and other["run_status"] in logic.STATION_OCCUPYING_RUN_STATES):
            raise ApiError("ERR_RUN_ALREADY_OPEN")

    # priority 16 — the station must be calibrated now
    days, eff, status = logic.instrument_derived(inst)
    if status == "OVERDUE":
        raise ApiError("ERR_INSTRUMENT_CALIBRATION_OVERDUE")

    # priority 17 — the capability ratio
    design = store.designs.get(wo["design_id"])
    ratio = calc.capability_ratio(eff, design["tolerance_budget_waves"])
    if ratio > calc.MAX_CAPABILITY_RATIO:
        raise ApiError("ERR_METROLOGY_CAPABILITY_INSUFFICIENT")

    # priority 18 — window shape
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_WINDOW")
    minutes = calc.window_minutes(start_dt, end_dt)
    if minutes < calc.MIN_WINDOW_MINUTES or minutes > calc.MAX_WINDOW_MINUTES:
        raise ApiError("ERR_INVALID_WINDOW")

    # priority 19 — the station conflict scan, closed endpoints + purge buffer
    purge = calc.INSTRUMENT_PURGE_MINUTES * 60
    for other in ordered(list(store.runs.values())):
        if other["metrology_instrument_id"] != inst["id"]:
            continue
        if other["run_status"] not in logic.STATION_OCCUPYING_RUN_STATES:
            continue
        o_start = other["_window_start_dt"]
        o_end = other["_window_end_dt"]
        if ((start_dt - o_end).total_seconds() < purge
                and (o_start - end_dt).total_seconds() < purge):
            raise ApiError("ERR_INSTRUMENT_WINDOW_CONFLICT")

    run = store.new_row()
    run["work_order_id"] = wo["id"]
    run["metrology_instrument_id"] = inst["id"]
    run["run_stage"] = run_stage
    run["metrology_window_start_utc"] = start_raw
    run["metrology_window_end_utc"] = end_raw
    run["window_minutes"] = minutes
    run["capability_ratio_at_scheduling"] = ratio
    run["material_removed_nm"] = None
    run["started_at_utc"] = None
    run["run_status"] = "SCHEDULED"
    run["cancel_reason"] = None
    run["_window_start_dt"] = start_dt
    run["_window_end_dt"] = end_dt
    run["_started_sort"] = None
    store.runs[run["id"]] = run

    logic.instrument_book(inst, minutes)
    return ok(logic.ser_run(run), 201)


@bp.get("/optics/process-runs/<row_id>")
def get_run(row_id):
    authenticate(ALL_ROLES)
    run = path_row(store.runs, row_id, "ERR_PROCESS_RUN_NOT_FOUND")
    return ok(logic.ser_run(run))


@bp.get("/optics/process-runs")
def list_runs():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.runs.values()))
    for name in ("work_order_id", "metrology_instrument_id", "run_stage", "run_status"):
        value = filt(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return ok_list(rows, logic.ser_run, limit, offset)


@bp.get("/optics/process-runs/<row_id>/metrology-reports")
def list_run_reports(row_id):
    authenticate(ALL_ROLES)
    run = path_row(store.runs, row_id, "ERR_PROCESS_RUN_NOT_FOUND")
    limit, offset = pagination()
    rows = ordered([r for r in store.reports.values()
                    if r["process_run_id"] == run["id"]])
    value = filt("report_status")
    if value is not None:
        rows = [r for r in rows if r["report_status"] == value]
    return ok_list(rows, logic.ser_report, limit, offset)


@bp.post("/optics/process-runs/<row_id>/start")
def start_run(row_id):
    authenticate(["ProcessTechnician"])
    run = path_row(store.runs, row_id, "ERR_PROCESS_RUN_NOT_FOUND")

    if run["run_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    wo = store.work_orders.get(run["work_order_id"])
    if wo is None or wo["process_status"] in NOT_WORKABLE:
        raise ApiError("ERR_WORK_ORDER_NOT_IN_PROCESS")

    run["run_status"] = "IN_PROCESS"
    run["started_at_utc"] = store.now_str()
    now = store.now_dt()
    run["_started_sort"] = now.isoformat() if now is not None else ""
    store.touch(run)

    wo["process_status"] = run["run_stage"]
    store.touch(wo)
    return ok(logic.ser_run(run))


@bp.post("/optics/process-runs/<row_id>/complete")
def complete_run(row_id):
    authenticate(["ProcessTechnician"])
    run = path_row(store.runs, row_id, "ERR_PROCESS_RUN_NOT_FOUND")
    body = get_body()

    removed = v_num(body, "material_removed_nm", True, ge=0)

    if run["run_status"] != "IN_PROCESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    run["material_removed_nm"] = removed
    run["run_status"] = "AWAITING_METROLOGY"
    store.touch(run)
    return ok(logic.ser_run(run))


@bp.post("/optics/process-runs/<row_id>/cancel")
def cancel_run(row_id):
    authenticate(["ProcessTechnician", "QualityManager"])
    run = path_row(store.runs, row_id, "ERR_PROCESS_RUN_NOT_FOUND")
    body = get_body()

    reason = v_str(body, "cancel_reason", False, None, min_len=1, max_len=500)

    if run["run_status"] not in logic.OPEN_RUN_STATES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    logic.cancel_run(run, reason or "CANCELLED_BY_OPERATOR")
    return ok(logic.ser_run(run))


# ----------------------------------------------------------- metrology reports
@bp.post("/optics/metrology-reports")
def create_report():
    user_id, _role = authenticate(["MetrologyTechnician"])
    body = get_body()

    run = v_fk(body, "process_run_id", store.runs, "ERR_PROCESS_RUN_NOT_FOUND")
    run = need_fk(body, "process_run_id", run)

    surface_rms = v_num(body, "surface_rms_waves", True, ge=0)
    surface_pv = v_num(body, "surface_pv_waves", False, Decimal("0.0000"), ge=0)
    roughness = v_num(body, "surface_roughness_nm_rms", False, Decimal("0.0000"), ge=0)
    twf = v_num(body, "transmitted_wavefront_rms_waves", False, Decimal("0.0000"), ge=0)

    wo = store.work_orders.get(run["work_order_id"])
    design = store.designs.get(wo["design_id"]) if wo else None

    report = store.new_row()
    report["process_run_id"] = run["id"]
    report["surface_rms_waves"] = surface_rms
    report["surface_pv_waves"] = surface_pv
    report["surface_roughness_nm_rms"] = roughness
    report["transmitted_wavefront_rms_waves"] = twf
    report["stage_figure_budget_waves"] = calc.stage_figure_budget(
        design["surface_figure_budget_waves"], run["run_stage"])
    report["verdict"] = "PENDING"
    report["report_status"] = "DRAFT"
    report["recorded_by_user_id"] = user_id
    report["signed_by_user_id"] = None
    report["signed_at_utc"] = None
    report["signature_note"] = None
    store.reports[report["id"]] = report
    return ok(logic.ser_report(report), 201)


@bp.get("/optics/metrology-reports/<row_id>")
def get_report(row_id):
    authenticate(ALL_ROLES)
    report = path_row(store.reports, row_id, "ERR_METROLOGY_REPORT_NOT_FOUND")
    return ok(logic.ser_report(report))


@bp.post("/optics/metrology-reports/<row_id>/sign")
def sign_report(row_id):
    user_id, _role = authenticate(["MetrologyTechnician", "QualityManager"])
    report = path_row(store.reports, row_id, "ERR_METROLOGY_REPORT_NOT_FOUND")
    body = get_body()

    note = v_str(body, "signature_note", False, None, min_len=1, max_len=1000)

    run = store.runs.get(report["process_run_id"])
    wo = store.work_orders.get(run["work_order_id"]) if run else None
    design = store.designs.get(wo["design_id"]) if wo else None

    # priority 7 — report and run states
    if report["report_status"] != "DRAFT":
        raise ApiError("ERR_REPORT_ALREADY_SIGNED")
    if run is None or run["run_status"] != "AWAITING_METROLOGY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # priority 12 — segregation of duties
    if user_id == report["recorded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # priority 16 — calibration re-checked at the current clock instant
    inst = store.instruments.get(run["metrology_instrument_id"])
    if inst is None or logic.instrument_derived(inst)[2] == "OVERDUE":
        raise ApiError("ERR_INSTRUMENT_CALIBRATION_OVERDUE")

    verdict = calc.acceptance_verdict(report, run["run_stage"], design)
    report["verdict"] = verdict
    report["report_status"] = "SIGNED"
    report["signed_by_user_id"] = user_id
    report["signed_at_utc"] = store.now_str()
    report["signature_note"] = note
    store.touch(report)

    run["run_status"] = "ACCEPTED" if verdict == "ACCEPTED" else "REWORK_REQUIRED"
    store.touch(run)

    stage = run["run_stage"]
    suppressed = wo["process_status"] in logic.SUPPRESS_PROCESS_ADVANCE

    if verdict == "ACCEPTED":
        logic.recompute_removal_ledger(wo)
        if not suppressed:
            wo["process_status"] = calc.STAGE_ADVANCE_MAP[stage]
        store.touch(wo)
    elif stage == "FIGURING":
        wo["figuring_iteration_count"] = int(wo["figuring_iteration_count"]) + 1
        logic.recompute_removal_ledger(wo)
        store.touch(wo)
        if not suppressed:
            remaining = Decimal(wo["remaining_center_thickness_um"])
            if remaining < Decimal(design["min_center_thickness_um"]):
                logic.scrap_work_order(wo, "MIN_THICKNESS_BREACH")
            elif int(wo["figuring_iteration_count"]) >= calc.MAX_FIGURING_ITERATIONS:
                logic.scrap_work_order(wo, "FIGURE_CONVERGENCE_FAILURE")
            else:
                wo["process_status"] = "POLISHING"
                store.touch(wo)
    else:
        logic.recompute_removal_ledger(wo)
        store.touch(wo)

    return ok(logic.ser_report(report))
