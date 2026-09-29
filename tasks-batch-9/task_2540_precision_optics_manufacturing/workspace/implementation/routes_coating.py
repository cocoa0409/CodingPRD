"""§3.6 CoatingChamber and CoatingRun routes."""

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, bad, filt, get_body, need_fk, ok,
                    ok_list, pagination, path_row, v_enum, v_fk, v_int, v_num,
                    v_str, v_ts)
from errors import ApiError
from store import ordered, store

bp = Blueprint("coating", __name__)

COATING_TYPES = ["AR_BROADBAND", "DIELECTRIC_MIRROR", "BEAMSPLITTER"]


# ------------------------------------------------------------------ chambers
@bp.post("/optics/coating-chambers")
def create_chamber():
    authenticate(["PlantAdmin"])
    body = get_body()

    code = v_str(body, "chamber_code", True, min_len=1, max_len=40)
    capacity = v_int(body, "slot_capacity", True, ge=1)
    coating_type = v_enum(body, "coating_type", COATING_TYPES, False, "AR_BROADBAND")

    chamber = store.new_row()
    chamber["chamber_code"] = code
    chamber["coating_type"] = coating_type
    chamber["slot_capacity"] = capacity
    store.chambers[chamber["id"]] = chamber
    return ok(logic.ser_chamber(chamber), 201)


@bp.get("/optics/coating-chambers/<row_id>")
def get_chamber(row_id):
    authenticate(ALL_ROLES)
    chamber = path_row(store.chambers, row_id, "ERR_CHAMBER_NOT_FOUND")
    return ok(logic.ser_chamber(chamber))


@bp.get("/optics/coating-chambers")
def list_chambers():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.chambers.values()))
    value = filt("coating_type")
    if value is not None:
        rows = [r for r in rows if r["coating_type"] == value]
    return ok_list(rows, logic.ser_chamber, limit, offset)


# --------------------------------------------------------------- coating runs
@bp.post("/optics/coating-runs")
def create_coating_run():
    authenticate(["ProcessTechnician"])
    body = get_body()

    wo = v_fk(body, "work_order_id", store.work_orders, "ERR_WORK_ORDER_NOT_FOUND")
    chamber = v_fk(body, "coating_chamber_id", store.chambers, "ERR_CHAMBER_NOT_FOUND")

    wo = need_fk(body, "work_order_id", wo)
    chamber = need_fk(body, "coating_chamber_id", chamber)
    recipe = v_str(body, "coating_recipe_code", True, min_len=1, max_len=40)
    start_raw, start_dt = v_ts(body, "window_start_utc", True)
    end_raw, end_dt = v_ts(body, "window_end_utc", True)

    # priority 7 — the order must be exactly FIGURE_ACCEPTED
    if wo["process_status"] != "FIGURE_ACCEPTED":
        raise ApiError("ERR_WORK_ORDER_NOT_IN_PROCESS")

    # priority 18 — window shape
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_WINDOW")
    minutes = calc.window_minutes(start_dt, end_dt)
    if minutes < calc.MIN_WINDOW_MINUTES or minutes > calc.MAX_WINDOW_MINUTES:
        raise ApiError("ERR_INVALID_WINDOW")

    # priority 20 — aggregate half-open chamber occupancy
    occupancy = 0
    for other in ordered(list(store.coating_runs.values())):
        if other["coating_chamber_id"] != chamber["id"]:
            continue
        if other["coating_status"] not in logic.CHAMBER_OCCUPYING_STATES:
            continue
        if start_dt < other["_window_end_dt"] and other["_window_start_dt"] < end_dt:
            occupancy += 1
    if occupancy >= int(chamber["slot_capacity"]):
        raise ApiError("ERR_CHAMBER_CAPACITY_EXCEEDED")

    run = store.new_row()
    run["work_order_id"] = wo["id"]
    run["coating_chamber_id"] = chamber["id"]
    run["coating_recipe_code"] = recipe
    run["window_start_utc"] = start_raw
    run["window_end_utc"] = end_raw
    run["spectral_samples"] = []
    run["in_band_sample_count"] = 0
    run["band_average_reflectance_pct"] = None
    run["worst_point_reflectance_pct"] = None
    run["spectral_verdict"] = "PENDING"
    run["strip_count"] = 0
    run["coating_status"] = "LOADED"
    run["_window_start_dt"] = start_dt
    run["_window_end_dt"] = end_dt
    store.coating_runs[run["id"]] = run

    wo["process_status"] = "COATING"
    store.touch(wo)
    return ok(logic.ser_coating_run(run), 201)


@bp.get("/optics/coating-runs/<row_id>")
def get_coating_run(row_id):
    authenticate(ALL_ROLES)
    run = path_row(store.coating_runs, row_id, "ERR_COATING_RUN_NOT_FOUND")
    return ok(logic.ser_coating_run(run))


@bp.get("/optics/coating-runs")
def list_coating_runs():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.coating_runs.values()))
    for name in ("work_order_id", "coating_chamber_id", "coating_status",
                 "spectral_verdict"):
        value = filt(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return ok_list(rows, logic.ser_coating_run, limit, offset)


@bp.post("/optics/coating-runs/<row_id>/deposit")
def deposit(row_id):
    authenticate(["ProcessTechnician"])
    run = path_row(store.coating_runs, row_id, "ERR_COATING_RUN_NOT_FOUND")
    if run["coating_status"] != "LOADED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    run["coating_status"] = "DEPOSITED"
    store.touch(run)
    return ok(logic.ser_coating_run(run))


@bp.post("/optics/coating-runs/<row_id>/spectral-verification")
def spectral_verification(row_id):
    authenticate(["ProcessTechnician", "MetrologyTechnician"])
    run = path_row(store.coating_runs, row_id, "ERR_COATING_RUN_NOT_FOUND")
    body = get_body()

    if "spectral_samples" not in body or body["spectral_samples"] is None:
        bad("spectral_samples", "is required.")
    raw_samples = body["spectral_samples"]
    if not isinstance(raw_samples, list):
        bad("spectral_samples", "must be an array.")
    if not raw_samples:
        bad("spectral_samples", "must be a non-empty array.")

    samples = []
    for index, entry in enumerate(raw_samples):
        if not isinstance(entry, dict):
            bad("spectral_samples[%d]" % index, "must be an object.")
        wavelength = v_int(entry, "wavelength_nm", True, ge=0)
        reflectance = v_num(entry, "reflectance_pct", True, ge=0)
        samples.append({"wavelength_nm": wavelength, "reflectance_pct": reflectance})

    if run["coating_status"] != "DEPOSITED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    wo = store.work_orders.get(run["work_order_id"])
    design = store.designs.get(wo["design_id"]) if wo else None

    lo = int(design["wavelength_min_nm"])
    hi = int(design["wavelength_max_nm"])
    in_band = [s for s in samples if lo <= s["wavelength_nm"] <= hi]

    if len(in_band) < calc.MIN_IN_BAND_SAMPLES:
        raise ApiError("ERR_SPECTRAL_SAMPLE_INSUFFICIENT")

    run["spectral_samples"] = samples
    run["in_band_sample_count"] = len(in_band)
    avg, worst, verdict = calc.spectral_aggregates(in_band)
    run["band_average_reflectance_pct"] = avg
    run["worst_point_reflectance_pct"] = worst
    run["spectral_verdict"] = verdict
    run["coating_status"] = "VERIFIED_PASS" if verdict == "PASS" else "VERIFIED_FAIL"
    store.touch(run)

    if verdict == "PASS" and wo is not None and wo["process_status"] == "COATING":
        wo["process_status"] = "COATED"
        store.touch(wo)

    return ok(logic.ser_coating_run(run))


@bp.post("/optics/coating-runs/<row_id>/strip")
def strip(row_id):
    authenticate(["ProcessTechnician"])
    run = path_row(store.coating_runs, row_id, "ERR_COATING_RUN_NOT_FOUND")

    if run["coating_status"] != "VERIFIED_FAIL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    run["strip_count"] = int(run["strip_count"]) + 1
    wo = store.work_orders.get(run["work_order_id"])

    if int(run["strip_count"]) <= 1:
        run["coating_status"] = "LOADED"
        run["spectral_samples"] = []
        run["in_band_sample_count"] = 0
        run["band_average_reflectance_pct"] = None
        run["worst_point_reflectance_pct"] = None
        run["spectral_verdict"] = "PENDING"
        store.touch(run)
        if wo is not None and wo["process_status"] in ("COATING", "COATED"):
            wo["process_status"] = "COATING"
            store.touch(wo)
    else:
        run["coating_status"] = "SCRAPPED"
        store.touch(run)
        if wo is not None and wo["process_status"] in ("COATING", "COATED"):
            logic.scrap_work_order(wo, "COATING_STRIP_LIMIT")

    return ok(logic.ser_coating_run(run))
