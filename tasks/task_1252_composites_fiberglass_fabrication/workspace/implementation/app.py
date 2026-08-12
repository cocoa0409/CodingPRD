"""Composites & Fiberglass Fabrication API — Flask entry point."""

import os
from datetime import timedelta

from flask import Flask

import db
import services as S
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import success, error

app = Flask(__name__, static_folder=None)
app.config["JSON_SORT_KEYS"] = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def _api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _not_found(e):
    return error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    return error("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def _internal(e):
    return error("ERR_INTERNAL", 500, "Internal server error")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["ShopManager"])
    b = S.get_body()
    raw = b.get("to_iso8601")
    dt = S.parse_dt(raw)
    if dt is None:
        S.bad_request("Field 'to_iso8601' is required and must be an ISO 8601 datetime")
    db.set_clock(dt)
    return success({"current_utc": S.fmt_clock(dt)}, 200, "object")


# ---------------------------------------------------------------------------
# EmissionPermit
# ---------------------------------------------------------------------------

@app.post("/emission-permits")
def create_permit():
    authenticate(["EHSOfficer"])
    b = S.get_body()
    # priority 4: shape
    code = S.f_str(b, "permit_code")
    ps_raw, ps_dt = S.f_dt(b, "period_start")
    pe_raw, pe_dt = S.f_dt(b, "period_end")
    quota = S.f_num(b, "styrene_quota_kg")
    if S.D(quota) <= 0:
        S.bad_request("Field 'styrene_quota_kg' must be > 0")
    warn = b.get("warning_threshold_pct", 0.85)
    if not S.is_num(warn) or not (S.D(warn) > 0 and S.D(warn) <= 1):
        S.bad_request("Field 'warning_threshold_pct' must be in (0, 1]")
    if not pe_dt > ps_dt:
        S.bad_request("Field 'period_end' must be strictly after 'period_start'")
    # priority 8: uniqueness
    for p in db.STORE["permits"].values():
        if p["permit_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "permit_code already exists")
    rec = db.new_base()
    rec.update({
        "permit_code": code,
        "period_start": ps_raw,
        "period_end": pe_raw,
        "styrene_quota_kg": quota,
        "warning_threshold_pct": warn,
        "status": "ACTIVE",
        "_period_start_dt": ps_dt,
        "_period_end_dt": pe_dt,
        "_styrene_used": S.D("0"),
    })
    db.STORE["permits"][rec["id"]] = rec
    return success(S.permit_out(rec), 201, "object")


@app.get("/emission-permits/<pid>")
def get_permit(pid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("permits", pid, "EmissionPermit")
    return success(S.permit_out(rec), 200, "object")


@app.post("/emission-permits/<pid>/close")
def close_permit(pid):
    authenticate(["EHSOfficer"])
    rec = S.get_or_404("permits", pid, "EmissionPermit")
    if rec["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Permit is already CLOSED")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return success(S.permit_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# Mold
# ---------------------------------------------------------------------------

@app.post("/molds")
def create_mold():
    authenticate(["ToolingEngineer"])
    b = S.get_body()
    code = S.f_str(b, "mold_code")
    interval = S.f_int(b, "maintenance_interval_cycles")
    if interval < 1:
        S.bad_request("Field 'maintenance_interval_cycles' must be >= 1")
    ppr = S.f_int(b, "prototype_parts_required")
    if ppr < 0:
        S.bad_request("Field 'prototype_parts_required' must be >= 0")
    phase = b.get("tooling_phase", "PROTOTYPE")
    if not isinstance(phase, str) or phase not in S.TOOLING_PHASES:
        S.bad_request("Field 'tooling_phase' must be one of PROTOTYPE, TRANSITION, PRODUCTION")
    if phase == "TRANSITION":
        S.bad_request("Field 'tooling_phase' may only be PROTOTYPE or PRODUCTION at creation")
    for m in db.STORE["molds"].values():
        if m["mold_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "mold_code already exists")
    rec = db.new_base()
    rec.update({
        "mold_code": code,
        "tooling_phase": phase,
        "maintenance_interval_cycles": interval,
        "cycles_since_maintenance": 0,
        "prototype_parts_required": ppr,
        "prototype_parts_validated": 0,
        "status": "ACTIVE",
    })
    db.STORE["molds"][rec["id"]] = rec
    return success(S.mold_out(rec), 201, "object")


@app.get("/molds/<mid>")
def get_mold(mid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("molds", mid, "Mold")
    return success(S.mold_out(rec), 200, "object")


@app.patch("/molds/<mid>")
def patch_mold(mid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("molds", mid, "Mold")
    b = S.get_body()
    emv = b.get("expected_mold_version")
    if not S.is_int(emv):
        S.bad_request("Field 'expected_mold_version' is required and must be an integer")
    if "maintenance_interval_cycles" in b:
        v = b["maintenance_interval_cycles"]
        if not S.is_int(v) or v < 1:
            S.bad_request("Field 'maintenance_interval_cycles' must be an integer >= 1")
    if "prototype_parts_required" in b:
        v = b["prototype_parts_required"]
        if not S.is_int(v) or v < 0:
            S.bad_request("Field 'prototype_parts_required' must be an integer >= 0")
    # priority 5: OCC
    if emv != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_mold_version does not match current version")
    if "maintenance_interval_cycles" in b:
        rec["maintenance_interval_cycles"] = b["maintenance_interval_cycles"]
    if "prototype_parts_required" in b:
        rec["prototype_parts_required"] = b["prototype_parts_required"]
    db.touch(rec)
    return success(S.mold_out(rec), 200, "object")


@app.post("/molds/<mid>/start-maintenance")
def mold_start_maintenance(mid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("molds", mid, "Mold")
    if rec["status"] != "MAINTENANCE_DUE":
        raise ApiError("ERR_INVALID_STATE", 409, "Mold is not MAINTENANCE_DUE")
    rec["status"] = "IN_MAINTENANCE"
    db.touch(rec)
    return success(S.mold_out(rec), 200, "object")


@app.post("/molds/<mid>/complete-maintenance")
def mold_complete_maintenance(mid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("molds", mid, "Mold")
    if rec["status"] != "IN_MAINTENANCE":
        raise ApiError("ERR_INVALID_STATE", 409, "Mold is not IN_MAINTENANCE")
    rec["status"] = "ACTIVE"
    rec["cycles_since_maintenance"] = 0
    db.touch(rec)
    return success(S.mold_out(rec), 200, "object")


@app.post("/molds/<mid>/transition-phase")
def mold_transition_phase(mid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("molds", mid, "Mold")
    b = S.get_body()
    target = b.get("target_phase")
    if not isinstance(target, str) or target not in S.TOOLING_PHASES:
        S.bad_request("Field 'target_phase' must be one of PROTOTYPE, TRANSITION, PRODUCTION")
    if rec["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "Mold is RETIRED")
    cur = rec["tooling_phase"]
    if (cur, target) == ("PROTOTYPE", "TRANSITION"):
        if rec["prototype_parts_validated"] < rec["prototype_parts_required"]:
            raise ApiError("ERR_TOOLING_PHASE_GATE", 409,
                           "prototype_parts_validated below prototype_parts_required")
    elif (cur, target) == ("TRANSITION", "PRODUCTION"):
        for w in db.STORE["work_orders"].values():
            if w["mold_id"] == rec["id"] and w["status"] not in ("ACCEPTED", "SCRAPPED"):
                raise ApiError("ERR_TOOLING_PHASE_GATE", 409,
                               "Work orders in non-terminal status block PRODUCTION")
    elif (cur, target) == ("TRANSITION", "PROTOTYPE"):
        pass
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No tooling_phase transition from %s to %s" % (cur, target))
    rec["tooling_phase"] = target
    db.touch(rec)
    return success(S.mold_out(rec), 200, "object")


@app.post("/molds/<mid>/retire")
def mold_retire(mid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("molds", mid, "Mold")
    if rec["status"] not in ("ACTIVE", "MAINTENANCE_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Mold cannot be retired from %s" % rec["status"])
    if S.mold_currently_occupied(rec["id"]) is not None:
        raise ApiError("ERR_MOLD_OCCUPANCY_CONFLICT", 409, "A work order currently occupies the mold")
    rec["status"] = "RETIRED"
    db.touch(rec)
    return success(S.mold_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# PlyBook
# ---------------------------------------------------------------------------

def _validate_plies(v):
    if not isinstance(v, list) or len(v) < 1:
        S.bad_request("Field 'plies' must be a non-empty array")
    last_seq = None
    for i, ply in enumerate(v):
        if not isinstance(ply, dict):
            S.bad_request("Each ply must be an object")
        for f in ("seq", "material_code", "orientation_deg", "areal_weight_g_m2"):
            if f not in ply:
                S.bad_request("Ply %d is missing field '%s'" % (i, f))
        if not S.is_int(ply["seq"]):
            S.bad_request("Ply 'seq' must be an integer")
        if not isinstance(ply["material_code"], str):
            S.bad_request("Ply 'material_code' must be a string")
        if not S.is_num(ply["orientation_deg"]):
            S.bad_request("Ply 'orientation_deg' must be a number")
        if not S.is_num(ply["areal_weight_g_m2"]):
            S.bad_request("Ply 'areal_weight_g_m2' must be a number")
        if last_seq is not None and ply["seq"] <= last_seq:
            S.bad_request("Ply 'seq' values must be unique and ascending")
        last_seq = ply["seq"]


@app.post("/ply-books")
def create_ply_book():
    authenticate(["ToolingEngineer"])
    b = S.get_body()
    part_number = S.f_str(b, "part_number")
    revision = S.f_str(b, "revision")
    area = S.f_num(b, "part_area_m2")
    if S.D(area) <= 0:
        S.bad_request("Field 'part_area_m2' must be > 0")
    if "plies" not in b:
        S.bad_request("Field 'plies' is required")
    _validate_plies(b["plies"])
    resin_system = b.get("resin_system")
    if not isinstance(resin_system, str) or resin_system not in S.RESIN_SYSTEMS:
        S.bad_request("Field 'resin_system' must be one of POLYESTER, VINYL_ESTER, EPOXY")
    tfvp = S.f_num(b, "target_fiber_volume_pct")
    if not (S.D(tfvp) > 0 and S.D(tfvp) < 1):
        S.bad_request("Field 'target_fiber_volume_pct' must be in (0, 1)")
    tol = b.get("tolerance_pct", 0.05)
    if not S.is_num(tol) or not (S.D(tol) > 0 and S.D(tol) <= S.D("0.5")):
        S.bad_request("Field 'tolerance_pct' must be in (0, 0.5]")
    mra = b.get("max_repair_attempts", 2)
    if not S.is_int(mra) or mra < 0:
        S.bad_request("Field 'max_repair_attempts' must be an integer >= 0")
    for pb in db.STORE["ply_books"].values():
        if pb["part_number"] == part_number and pb["revision"] == revision:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "(part_number, revision) already exists")
    rec = db.new_base()
    rec.update({
        "part_number": part_number,
        "revision": revision,
        "part_area_m2": area,
        "plies": b["plies"],
        "resin_system": resin_system,
        "target_fiber_volume_pct": tfvp,
        "tolerance_pct": tol,
        "max_repair_attempts": mra,
        "status": "DRAFT",
    })
    db.STORE["ply_books"][rec["id"]] = rec
    return success(S.ply_book_out(rec), 201, "object")


@app.get("/ply-books/<pid>")
def get_ply_book(pid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("ply_books", pid, "PlyBook")
    return success(S.ply_book_out(rec), 200, "object")


@app.patch("/ply-books/<pid>")
def patch_ply_book(pid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("ply_books", pid, "PlyBook")
    b = S.get_body()
    epv = b.get("expected_ply_book_version")
    if not S.is_int(epv):
        S.bad_request("Field 'expected_ply_book_version' is required and must be an integer")
    if "part_area_m2" in b:
        if not S.is_num(b["part_area_m2"]) or S.D(b["part_area_m2"]) <= 0:
            S.bad_request("Field 'part_area_m2' must be > 0")
    if "plies" in b:
        _validate_plies(b["plies"])
    if "target_fiber_volume_pct" in b:
        v = b["target_fiber_volume_pct"]
        if not S.is_num(v) or not (S.D(v) > 0 and S.D(v) < 1):
            S.bad_request("Field 'target_fiber_volume_pct' must be in (0, 1)")
    if "tolerance_pct" in b:
        v = b["tolerance_pct"]
        if not S.is_num(v) or not (S.D(v) > 0 and S.D(v) <= S.D("0.5")):
            S.bad_request("Field 'tolerance_pct' must be in (0, 0.5]")
    if "max_repair_attempts" in b:
        if not S.is_int(b["max_repair_attempts"]) or b["max_repair_attempts"] < 0:
            S.bad_request("Field 'max_repair_attempts' must be an integer >= 0")
    # priority 5: OCC
    if epv != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_ply_book_version does not match current version")
    # priority 6: state
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_PLY_BOOK_NOT_DRAFT", 409, "Only a DRAFT ply book may be edited")
    for f in ("part_area_m2", "plies", "target_fiber_volume_pct", "tolerance_pct", "max_repair_attempts"):
        if f in b:
            rec[f] = b[f]
    db.touch(rec)
    return success(S.ply_book_out(rec), 200, "object")


@app.post("/ply-books/<pid>/approve")
def approve_ply_book(pid):
    authenticate(["ToolingEngineer"])
    rec = S.get_or_404("ply_books", pid, "PlyBook")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_PLY_BOOK_NOT_DRAFT", 409, "Only a DRAFT ply book may be approved")
    rec["status"] = "APPROVED"
    db.touch(rec)
    for other in db.STORE["ply_books"].values():
        if other["id"] != rec["id"] and other["part_number"] == rec["part_number"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    return success(S.ply_book_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# WorkOrder
# ---------------------------------------------------------------------------

@app.post("/work-orders")
def create_work_order():
    authenticate(["ShopManager"])
    b = S.get_body()
    # priority 3: existence of body FKs, left-to-right
    mold_id = b.get("mold_id")
    book_id = b.get("ply_book_id")
    mold = None
    book = None
    if isinstance(mold_id, str):
        mold = db.STORE["molds"].get(mold_id)
        if mold is None:
            S.not_found("Mold")
    if isinstance(book_id, str):
        book = db.STORE["ply_books"].get(book_id)
        if book is None:
            S.not_found("PlyBook")
    # priority 4: shape
    won = S.f_str(b, "work_order_no")
    part_number = S.f_str(b, "part_number")
    if mold is None:
        S.bad_request("Field 'mold_id' is required and must be a string")
    if book is None:
        S.bad_request("Field 'ply_book_id' is required and must be a string")
    qty = S.f_int(b, "quantity")
    if qty < 1:
        S.bad_request("Field 'quantity' must be >= 1")
    due_raw, _ = S.f_dt(b, "due_date")
    # priority 8: cross-entity configuration gates
    if mold["status"] == "RETIRED":
        raise ApiError("ERR_MOLD_NOT_AVAILABLE", 409, "Mold is RETIRED")
    if book["status"] != "APPROVED" or book["part_number"] != part_number:
        raise ApiError("ERR_PLY_BOOK_NOT_APPROVED", 409,
                       "Ply book is not APPROVED or part_number mismatch")
    if mold["tooling_phase"] in ("PROTOTYPE", "TRANSITION") and qty > S.PROTOTYPE_MAX_QUANTITY:
        raise ApiError("ERR_PROTOTYPE_QUANTITY_CAP", 409,
                       "quantity exceeds the prototype lot-size cap of 5")
    for w in db.STORE["work_orders"].values():
        if w["work_order_no"] == won:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "work_order_no already exists")
    target = S.theoretical_part_weight_g(book)
    rec = db.new_base()
    rec.update({
        "work_order_no": won,
        "part_number": part_number,
        "mold_id": mold["id"],
        "ply_book_id": book["id"],
        "pinned_ply_book_version": book["version"],
        "quantity": qty,
        "due_date": due_raw,
        "target_part_weight_g": float(target),
        "actual_part_weight_g": None,
        "weight_deviation_pct": None,
        "layup_started_at": None,
        "demolded_at": None,
        "repair_count": 0,
        "scrap_reason": None,
        "status": "RELEASED",
    })
    db.STORE["work_orders"][rec["id"]] = rec
    return success(S.work_order_out(rec), 201, "object")


@app.get("/work-orders")
def list_work_orders():
    authenticate(ALL_ROLES)
    data, pagination = S.paginate(
        db.STORE["work_orders"], S.work_order_out,
        [("mold_id", "mold_id"), ("ply_book_id", "ply_book_id"), ("status", "status")],
    )
    return success(data, 200, "array", pagination)


@app.get("/work-orders/<wid>")
def get_work_order(wid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("work_orders", wid, "WorkOrder")
    return success(S.work_order_out(rec), 200, "object")


@app.post("/work-orders/<wid>/start-layup")
def start_layup(wid):
    authenticate(["Laminator"])
    rec = S.get_or_404("work_orders", wid, "WorkOrder")
    # priority 6: state
    if rec["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not RELEASED")
    # priority 7: compliance
    if S.select_permit() is None:
        raise ApiError("ERR_NO_ACTIVE_PERMIT", 409,
                       "No ACTIVE emission permit covers the current logical time")
    # priority 8: configuration gates
    mold = db.STORE["molds"][rec["mold_id"]]
    if mold["status"] != "ACTIVE":
        raise ApiError("ERR_MOLD_NOT_AVAILABLE", 409, "Mold is not ACTIVE")
    # priority 9: mold occupancy (closed interval)
    t = db.now()
    if S.mold_occupied_by_other(rec) is not None:
        raise ApiError("ERR_MOLD_OCCUPANCY_CONFLICT", 409, "Another work order occupies the mold")
    for other in db.STORE["work_orders"].values():
        if other["id"] == rec["id"] or other["mold_id"] != rec["mold_id"]:
            continue
        if other["demolded_at"] is not None and t <= other["_demolded_dt"]:
            raise ApiError("ERR_MOLD_OCCUPANCY_CONFLICT", 409,
                           "Current time is not strictly after a prior occupant's demolded_at")
    rec["layup_started_at"] = db.fmt_dt(t)
    rec["status"] = "LAYUP_IN_PROGRESS"
    db.touch(rec)
    return success(S.work_order_out(rec), 200, "object")


@app.post("/work-orders/<wid>/complete-layup")
def complete_layup(wid):
    authenticate(["Laminator"])
    rec = S.get_or_404("work_orders", wid, "WorkOrder")
    if rec["status"] != "LAYUP_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not LAYUP_IN_PROGRESS")
    has_active = any(
        s["work_order_id"] == rec["id"] and s["status"] == "ACTIVE"
        for s in db.STORE["layup_sessions"].values()
    )
    if not has_active:
        raise ApiError("ERR_INVALID_STATE", 409, "No ACTIVE layup session exists for this work order")
    rec["status"] = "AWAITING_CURE"
    db.touch(rec)
    return success(S.work_order_out(rec), 200, "object")


@app.post("/work-orders/<wid>/demold")
def demold(wid):
    authenticate(["Laminator"])
    rec = S.get_or_404("work_orders", wid, "WorkOrder")
    b = S.get_body()
    actual = S.f_num(b, "actual_part_weight_g")
    if S.D(actual) <= 0:
        S.bad_request("Field 'actual_part_weight_g' must be > 0")
    if rec["status"] != "CURED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not CURED")
    target = S.D(rec["target_part_weight_g"])
    deviation = S.weight_deviation(actual, target)
    mold = db.STORE["molds"][rec["mold_id"]]
    book = db.STORE["ply_books"][rec["ply_book_id"]]
    if mold["tooling_phase"] == "PRODUCTION":
        tolerance = S.D(book["tolerance_pct"])
    else:
        tolerance = S.PROTOTYPE_TOLERANCE_PCT
    t = db.now()
    rec["actual_part_weight_g"] = actual
    rec["weight_deviation_pct"] = float(deviation)
    rec["demolded_at"] = db.fmt_dt(t)
    rec["_demolded_dt"] = t
    if deviation <= tolerance:
        rec["status"] = "IN_INSPECTION"
    else:
        rec["status"] = "SCRAPPED"
        rec["scrap_reason"] = "WEIGHT_OUT_OF_TOLERANCE"
    db.touch(rec)
    return success(S.work_order_out(rec), 200, "object")


@app.post("/work-orders/<wid>/scrap")
def scrap_work_order(wid):
    authenticate(["ShopManager"])
    rec = S.get_or_404("work_orders", wid, "WorkOrder")
    if rec["status"] not in ("RELEASED", "LAYUP_IN_PROGRESS", "AWAITING_CURE", "CURE_SCHEDULED", "REPAIR"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Work order cannot be scrapped from %s" % rec["status"])
    if rec["status"] == "CURE_SCHEDULED":
        for c in db.STORE["cure_cycles"].values():
            if c["work_order_id"] == rec["id"] and c["status"] == "SCHEDULED":
                c["status"] = "ABORTED"
                db.touch(c)
    if rec["status"] == "REPAIR":
        for r in db.STORE["repairs"].values():
            if r["work_order_id"] == rec["id"] and r["status"] == "OPEN":
                r["status"] = "SUPERSEDED"
                db.touch(r)
    if rec["layup_started_at"] is not None and rec["demolded_at"] is None:
        t = db.now()
        rec["demolded_at"] = db.fmt_dt(t)
        rec["_demolded_dt"] = t
    rec["scrap_reason"] = "MANUAL"
    rec["status"] = "SCRAPPED"
    db.touch(rec)
    return success(S.work_order_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# ResinBatch
# ---------------------------------------------------------------------------

@app.post("/resin-batches")
def create_resin_batch():
    authenticate(["Laminator"])
    b = S.get_body()
    code = S.f_str(b, "batch_code")
    resin_system = b.get("resin_system")
    if not isinstance(resin_system, str) or resin_system not in S.RESIN_SYSTEMS:
        S.bad_request("Field 'resin_system' must be one of POLYESTER, VINYL_ESTER, EPOXY")
    resin_mass = S.f_num(b, "resin_mass_g")
    if S.D(resin_mass) <= 0:
        S.bad_request("Field 'resin_mass_g' must be > 0")
    catalyst_mass = S.f_num(b, "catalyst_mass_g")
    if S.D(catalyst_mass) <= 0:
        S.bad_request("Field 'catalyst_mass_g' must be > 0")
    target_ratio = S.f_num(b, "target_ratio_pct")
    if S.D(target_ratio) <= 0:
        S.bad_request("Field 'target_ratio_pct' must be > 0")
    ratio_tol = S.f_num(b, "ratio_tolerance_pct")
    if S.D(ratio_tol) <= 0:
        S.bad_request("Field 'ratio_tolerance_pct' must be > 0")
    nominal = S.f_int(b, "nominal_pot_life_minutes")
    if nominal < 1:
        S.bad_request("Field 'nominal_pot_life_minutes' must be >= 1")
    ambient = b.get("ambient_temp_c")
    if ambient is not None:
        if not S.is_num(ambient):
            S.bad_request("Field 'ambient_temp_c' must be a number")
        if not (S.D(ambient) >= -10 and S.D(ambient) <= 60):
            S.bad_request("Field 'ambient_temp_c' must be between -10 and 60")
    for rb in db.STORE["resin_batches"].values():
        if rb["batch_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "batch_code already exists")
    actual_ratio = S.actual_ratio_pct(catalyst_mass, resin_mass)
    effective = S.effective_pot_life(nominal, ambient)
    mixed = db.now()
    expires = mixed + timedelta(minutes=effective)
    total = S.D(resin_mass) + S.D(catalyst_mass)
    rejected = abs(actual_ratio - S.D(target_ratio)) > S.D(ratio_tol)
    rec = db.new_base()
    rec.update({
        "batch_code": code,
        "resin_system": resin_system,
        "resin_mass_g": resin_mass,
        "catalyst_mass_g": catalyst_mass,
        "target_ratio_pct": target_ratio,
        "ratio_tolerance_pct": ratio_tol,
        "nominal_pot_life_minutes": nominal,
        "ambient_temp_c": ambient,
        "effective_pot_life_minutes": effective,
        "mixed_at": db.fmt_dt(mixed),
        "expires_at": db.fmt_dt(expires),
        "status": "REJECTED" if rejected else "MIXED",
        "_actual_ratio": actual_ratio,
        "_expires_dt": expires,
        "_total": total,
        "_consumed": S.D("0"),
        "_quenched": S.D("0"),
    })
    db.STORE["resin_batches"][rec["id"]] = rec
    return success(S.resin_batch_out(rec), 201, "object")


@app.get("/resin-batches/<bid>")
def get_resin_batch(bid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("resin_batches", bid, "ResinBatch")
    S.maybe_expire_batch(rec)
    return success(S.resin_batch_out(rec), 200, "object")


@app.post("/resin-batches/<bid>/quench")
def quench_resin_batch(bid):
    authenticate(["Laminator"])
    rec = S.get_or_404("resin_batches", bid, "ResinBatch")
    if rec["status"] not in ("MIXED", "PARTIALLY_CONSUMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Batch cannot be quenched from %s" % rec["status"])
    rec["_quenched"] = S.batch_remaining(rec)
    rec["status"] = "QUENCHED"
    db.touch(rec)
    return success(S.resin_batch_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# LayupSession
# ---------------------------------------------------------------------------

@app.post("/layup-sessions")
def create_layup_session():
    uid, _ = authenticate(["Laminator"])
    b = S.get_body()
    # priority 3: existence of body FKs, left-to-right
    wo_id = b.get("work_order_id")
    batch_id = b.get("resin_batch_id")
    wo = None
    batch = None
    if isinstance(wo_id, str):
        wo = db.STORE["work_orders"].get(wo_id)
        if wo is None:
            S.not_found("WorkOrder")
    if isinstance(batch_id, str):
        batch = db.STORE["resin_batches"].get(batch_id)
        if batch is None:
            S.not_found("ResinBatch")
    # priority 4: shape
    if wo is None:
        S.bad_request("Field 'work_order_id' is required and must be a string")
    if batch is None:
        S.bad_request("Field 'resin_batch_id' is required and must be a string")
    used = S.f_num(b, "resin_used_g")
    if S.D(used) <= 0:
        S.bad_request("Field 'resin_used_g' must be > 0")
    # priority 6: state
    if wo["status"] != "LAYUP_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not LAYUP_IN_PROGRESS")
    if batch["status"] not in ("MIXED", "PARTIALLY_CONSUMED"):
        raise ApiError("ERR_RESIN_BATCH_NOT_USABLE", 409,
                       "Batch is %s and can never/ no longer be consumed" % batch["status"])
    # priority 7: compliance gates
    permit = S.select_permit()
    if permit is None:
        raise ApiError("ERR_NO_ACTIVE_PERMIT", 409,
                       "No ACTIVE emission permit covers the current logical time")
    session_kg = S.styrene_session_kg(used, batch["resin_system"])
    if permit["_styrene_used"] + session_kg > S.D(permit["styrene_quota_kg"]):
        raise ApiError("ERR_PERMIT_QUOTA_EXCEEDED", 409,
                       "Session posting would exceed the permit styrene quota")
    if db.now() > batch["_expires_dt"]:
        batch["status"] = "EXPIRED"
        db.touch(batch)
        raise ApiError("ERR_RESIN_POT_LIFE_EXPIRED", 409, "Resin batch is past its pot-life window")
    if S.D(used) > S.batch_remaining(batch):
        raise ApiError("ERR_RESIN_MASS_INSUFFICIENT", 409,
                       "resin_used_g exceeds the batch's remaining mass")
    # priority 8: cross-entity gates
    book = db.STORE["ply_books"][wo["ply_book_id"]]
    if batch["resin_system"] != book["resin_system"]:
        raise ApiError("ERR_RESIN_SYSTEM_MISMATCH", 409,
                       "Batch resin_system differs from the ply book resin_system")
    # apply: session + three-link cascade
    t = db.now()
    rec = db.new_base()
    rec.update({
        "work_order_id": wo["id"],
        "resin_batch_id": batch["id"],
        "permit_id": permit["id"],
        "resin_used_g": used,
        "laminator_id": uid,
        "session_at": db.fmt_dt(t),
        "status": "ACTIVE",
        "_styrene_kg": session_kg,
    })
    db.STORE["layup_sessions"][rec["id"]] = rec
    # link 1: batch consumption
    batch["_consumed"] += S.D(used)
    remaining = S.batch_remaining(batch)
    batch["status"] = "EXHAUSTED" if remaining == 0 else "PARTIALLY_CONSUMED"
    db.touch(batch)
    # link 2 + 3: permit posting and quota flip
    permit["_styrene_used"] += session_kg
    if permit["_styrene_used"] >= S.D(permit["styrene_quota_kg"]):
        permit["status"] = "EXHAUSTED"
    db.touch(permit)
    return success(S.layup_session_out(rec), 201, "object")


@app.get("/layup-sessions")
def list_layup_sessions():
    authenticate(ALL_ROLES)
    data, pagination = S.paginate(
        db.STORE["layup_sessions"], S.layup_session_out,
        [("work_order_id", "work_order_id"), ("resin_batch_id", "resin_batch_id"),
         ("permit_id", "permit_id"), ("status", "status")],
    )
    return success(data, 200, "array", pagination)


@app.get("/layup-sessions/<sid>")
def get_layup_session(sid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("layup_sessions", sid, "LayupSession")
    return success(S.layup_session_out(rec), 200, "object")


@app.post("/layup-sessions/<sid>/void")
def void_layup_session(sid):
    authenticate(["ShopManager"])
    rec = S.get_or_404("layup_sessions", sid, "LayupSession")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Layup session is not ACTIVE")
    batch = db.STORE["resin_batches"][rec["resin_batch_id"]]
    if batch["status"] == "QUENCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Disposed mass cannot be returned (batch QUENCHED)")
    rec["status"] = "VOIDED"
    db.touch(rec)
    # compensation on the batch
    batch["_consumed"] -= S.D(rec["resin_used_g"])
    if batch["status"] in ("MIXED", "PARTIALLY_CONSUMED", "EXHAUSTED"):
        remaining = S.batch_remaining(batch)
        batch["status"] = "MIXED" if remaining == batch["_total"] else "PARTIALLY_CONSUMED"
    db.touch(batch)
    # compensation on the permit (exact stored value, never recomputed)
    permit = db.STORE["permits"].get(rec["permit_id"])
    if permit is not None:
        permit["_styrene_used"] -= rec["_styrene_kg"]
        if permit["status"] == "EXHAUSTED" and permit["_styrene_used"] < S.D(permit["styrene_quota_kg"]):
            permit["status"] = "ACTIVE"
        db.touch(permit)
    return success(S.layup_session_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# CureEquipment
# ---------------------------------------------------------------------------

@app.post("/cure-equipment")
def create_equipment():
    authenticate(["ShopManager"])
    b = S.get_body()
    code = S.f_str(b, "equipment_code")
    kind = b.get("kind")
    if not isinstance(kind, str) or kind not in S.EQUIPMENT_KINDS:
        S.bad_request("Field 'kind' must be one of OVEN, AUTOCLAVE")
    max_parts = S.f_int(b, "max_parts_per_cycle")
    if max_parts < 1:
        S.bad_request("Field 'max_parts_per_cycle' must be >= 1")
    turnaround = S.f_int(b, "turnaround_minutes")
    if turnaround < 0:
        S.bad_request("Field 'turnaround_minutes' must be >= 0")
    max_temp = S.f_num(b, "max_temperature_c")
    if S.D(max_temp) <= 0:
        S.bad_request("Field 'max_temperature_c' must be > 0")
    max_pressure = S.f_num(b, "max_pressure_bar")
    if S.D(max_pressure) < 0:
        S.bad_request("Field 'max_pressure_bar' must be >= 0")
    if kind == "AUTOCLAVE" and not S.D(max_pressure) > 0:
        S.bad_request("Field 'max_pressure_bar' must be > 0 for AUTOCLAVE equipment")
    if kind == "OVEN" and S.D(max_pressure) != 0:
        S.bad_request("Field 'max_pressure_bar' must be 0 for OVEN equipment")
    for e in db.STORE["equipment"].values():
        if e["equipment_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "equipment_code already exists")
    rec = db.new_base()
    rec.update({
        "equipment_code": code,
        "kind": kind,
        "max_parts_per_cycle": max_parts,
        "turnaround_minutes": turnaround,
        "max_temperature_c": max_temp,
        "max_pressure_bar": max_pressure,
        "status": "AVAILABLE",
    })
    db.STORE["equipment"][rec["id"]] = rec
    return success(S.equipment_out(rec), 201, "object")


@app.get("/cure-equipment/<eid>")
def get_equipment(eid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("equipment", eid, "CureEquipment")
    return success(S.equipment_out(rec), 200, "object")


@app.post("/cure-equipment/<eid>/out-of-service")
def equipment_out_of_service(eid):
    authenticate(["ShopManager"])
    rec = S.get_or_404("equipment", eid, "CureEquipment")
    if rec["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment is not AVAILABLE")
    for c in db.STORE["cure_cycles"].values():
        if c["equipment_id"] == rec["id"] and c["status"] == "RUNNING":
            raise ApiError("ERR_INVALID_STATE", 409, "A cure cycle is RUNNING on this equipment")
    rec["status"] = "OUT_OF_SERVICE"
    db.touch(rec)
    return success(S.equipment_out(rec), 200, "object")


@app.post("/cure-equipment/<eid>/return-to-service")
def equipment_return_to_service(eid):
    authenticate(["ShopManager"])
    rec = S.get_or_404("equipment", eid, "CureEquipment")
    if rec["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment is not OUT_OF_SERVICE")
    rec["status"] = "AVAILABLE"
    db.touch(rec)
    return success(S.equipment_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# CureCycle
# ---------------------------------------------------------------------------

@app.post("/cure-cycles")
def create_cure_cycle():
    authenticate(["CureTechnician"])
    b = S.get_body()
    # priority 3: existence of body FKs, left-to-right
    wo_id = b.get("work_order_id")
    eq_id = b.get("equipment_id")
    wo = None
    equip = None
    if isinstance(wo_id, str):
        wo = db.STORE["work_orders"].get(wo_id)
        if wo is None:
            S.not_found("WorkOrder")
    if isinstance(eq_id, str):
        equip = db.STORE["equipment"].get(eq_id)
        if equip is None:
            S.not_found("CureEquipment")
    # priority 4: shape
    if wo is None:
        S.bad_request("Field 'work_order_id' is required and must be a string")
    if equip is None:
        S.bad_request("Field 'equipment_id' is required and must be a string")
    ramp = S.f_num(b, "ramp_rate_c_per_min")
    if S.D(ramp) <= 0:
        S.bad_request("Field 'ramp_rate_c_per_min' must be > 0")
    soak_temp = S.f_num(b, "soak_temp_c")
    if S.D(soak_temp) <= 0:
        S.bad_request("Field 'soak_temp_c' must be > 0")
    soak_minutes = S.f_int(b, "soak_minutes")
    if soak_minutes < 1:
        S.bad_request("Field 'soak_minutes' must be >= 1")
    ss_raw, ss_dt = S.f_dt(b, "scheduled_start")
    se_raw, se_dt = S.f_dt(b, "scheduled_end")
    pressure = b.get("pressure_bar")
    if pressure is not None and (not S.is_num(pressure) or S.D(pressure) < 0):
        S.bad_request("Field 'pressure_bar' must be a number >= 0")
    # priority 6: state
    if wo["status"] not in ("AWAITING_CURE", "REPAIR"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Work order must be AWAITING_CURE or in REPAIR to schedule a cure")
    # priority 8: configuration gates
    if wo["demolded_at"] is None:
        mold = db.STORE["molds"][wo["mold_id"]]
        if mold["status"] != "ACTIVE":
            raise ApiError("ERR_MOLD_NOT_AVAILABLE", 409,
                           "Mold must be ACTIVE for a first, mold-bearing cure")
    if equip["status"] != "AVAILABLE":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409, "Equipment is not AVAILABLE")
    # priority 9: temporal / geometric rules
    if not se_dt > ss_dt:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "scheduled_end must be strictly after scheduled_start")
    if equip["kind"] == "OVEN" and pressure is not None:
        raise ApiError("ERR_PRESSURE_REQUIRES_AUTOCLAVE", 422,
                       "pressure_bar must be absent for OVEN equipment")
    if equip["kind"] == "AUTOCLAVE":
        if pressure is None:
            raise ApiError("ERR_PRESSURE_REQUIRES_AUTOCLAVE", 422,
                           "pressure_bar is required for AUTOCLAVE equipment")
        if S.D(pressure) > S.D(equip["max_pressure_bar"]):
            raise ApiError("ERR_PRESSURE_REQUIRES_AUTOCLAVE", 422,
                           "pressure_bar exceeds equipment max_pressure_bar")
    if S.D(soak_temp) > S.D(equip["max_temperature_c"]):
        raise ApiError("ERR_CURE_ENVELOPE_EXCEEDED", 422,
                       "soak_temp_c exceeds equipment max_temperature_c")
    candidates = [
        c for c in db.STORE["cure_cycles"].values()
        if c["equipment_id"] == equip["id"] and c["status"] in ("SCHEDULED", "RUNNING")
    ]
    if equip["kind"] == "AUTOCLAVE":
        ta = timedelta(minutes=equip["turnaround_minutes"])
        for c in candidates:
            if not (ss_dt >= c["_se_dt"] + ta or se_dt + ta <= c["_ss_dt"]):
                raise ApiError("ERR_TURNAROUND_BUFFER_VIOLATION", 409,
                               "Autoclave turnaround buffer violated")
    # priority 10: capacity
    overlapping = [
        c for c in candidates
        if c["_ss_dt"] < se_dt and ss_dt < c["_se_dt"]
    ]
    total_qty = sum(db.STORE["work_orders"][c["work_order_id"]]["quantity"] for c in overlapping)
    if total_qty + wo["quantity"] > equip["max_parts_per_cycle"]:
        raise ApiError("ERR_EQUIPMENT_CAPACITY_EXCEEDED", 409,
                       "Overlapping cycles exceed equipment capacity")
    rec = db.new_base()
    rec.update({
        "work_order_id": wo["id"],
        "equipment_id": equip["id"],
        "ramp_rate_c_per_min": ramp,
        "soak_temp_c": soak_temp,
        "soak_minutes": soak_minutes,
        "pressure_bar": pressure,
        "scheduled_start": ss_raw,
        "scheduled_end": se_raw,
        "uses_mold": wo["demolded_at"] is None,
        "recorded_min_temp_c": None,
        "recorded_max_temp_c": None,
        "recorded_soak_minutes": None,
        "recorded_ramp_rate_c_per_min": None,
        "cure_log_ok": None,
        "status": "SCHEDULED",
        "_ss_dt": ss_dt,
        "_se_dt": se_dt,
        "_score": None,
    })
    db.STORE["cure_cycles"][rec["id"]] = rec
    wo["status"] = "CURE_SCHEDULED"
    db.touch(wo)
    return success(S.cure_cycle_out(rec), 201, "object")


@app.get("/cure-cycles")
def list_cure_cycles():
    authenticate(ALL_ROLES)
    data, pagination = S.paginate(
        db.STORE["cure_cycles"], S.cure_cycle_out,
        [("work_order_id", "work_order_id"), ("equipment_id", "equipment_id"),
         ("status", "status")],
    )
    return success(data, 200, "array", pagination)


@app.get("/cure-cycles/<cid>")
def get_cure_cycle(cid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("cure_cycles", cid, "CureCycle")
    return success(S.cure_cycle_out(rec), 200, "object")


@app.post("/cure-cycles/<cid>/start")
def start_cure_cycle(cid):
    authenticate(["CureTechnician"])
    rec = S.get_or_404("cure_cycles", cid, "CureCycle")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cure cycle is not SCHEDULED")
    equip = db.STORE["equipment"][rec["equipment_id"]]
    if equip["status"] != "AVAILABLE":
        raise ApiError("ERR_EQUIPMENT_NOT_AVAILABLE", 409, "Equipment is not AVAILABLE")
    rec["status"] = "RUNNING"
    db.touch(rec)
    wo = db.STORE["work_orders"][rec["work_order_id"]]
    wo["status"] = "IN_CURE"
    db.touch(wo)
    return success(S.cure_cycle_out(rec), 200, "object")


@app.post("/cure-cycles/<cid>/complete")
def complete_cure_cycle(cid):
    authenticate(["CureTechnician"])
    rec = S.get_or_404("cure_cycles", cid, "CureCycle")
    b = S.get_body()
    rmin = S.f_num(b, "recorded_min_temp_c")
    rmax = S.f_num(b, "recorded_max_temp_c")
    rsoak = S.f_int(b, "recorded_soak_minutes")
    if rsoak < 0:
        S.bad_request("Field 'recorded_soak_minutes' must be >= 0")
    rramp = S.f_num(b, "recorded_ramp_rate_c_per_min")
    if S.D(rramp) < 0:
        S.bad_request("Field 'recorded_ramp_rate_c_per_min' must be >= 0")
    if rec["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Cure cycle is not RUNNING")
    rec["recorded_min_temp_c"] = rmin
    rec["recorded_max_temp_c"] = rmax
    rec["recorded_soak_minutes"] = rsoak
    rec["recorded_ramp_rate_c_per_min"] = rramp
    score, ok = S.cure_deviation(rec)
    rec["_score"] = score
    rec["cure_log_ok"] = ok
    rec["status"] = "COMPLETED"
    db.touch(rec)
    wo = db.STORE["work_orders"][rec["work_order_id"]]
    wo["status"] = "CURED" if ok else "AWAITING_CURE"
    db.touch(wo)
    if rec["uses_mold"]:
        mold = db.STORE["molds"][wo["mold_id"]]
        mold["cycles_since_maintenance"] += 1
        if (mold["cycles_since_maintenance"] >= mold["maintenance_interval_cycles"]
                and mold["status"] == "ACTIVE"):
            mold["status"] = "MAINTENANCE_DUE"
        db.touch(mold)
    return success(S.cure_cycle_out(rec), 200, "object")


@app.post("/cure-cycles/<cid>/abort")
def abort_cure_cycle(cid):
    authenticate(["CureTechnician"])
    rec = S.get_or_404("cure_cycles", cid, "CureCycle")
    if rec["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Cure cycle is not RUNNING")
    rec["status"] = "ABORTED"
    db.touch(rec)
    wo = db.STORE["work_orders"][rec["work_order_id"]]
    wo["status"] = "AWAITING_CURE"
    db.touch(wo)
    return success(S.cure_cycle_out(rec), 200, "object")


# ---------------------------------------------------------------------------
# Inspection / Repair
# ---------------------------------------------------------------------------

@app.post("/inspections")
def create_inspection():
    uid, _ = authenticate(["QualityInspector"])
    b = S.get_body()
    wo_id = b.get("work_order_id")
    wo = None
    if isinstance(wo_id, str):
        wo = db.STORE["work_orders"].get(wo_id)
        if wo is None:
            S.not_found("WorkOrder")
    if wo is None:
        S.bad_request("Field 'work_order_id' is required and must be a string")
    method = b.get("method")
    if not isinstance(method, str) or method not in S.INSPECTION_METHODS:
        S.bad_request("Field 'method' must be one of ULTRASONIC, TAP_TEST, VISUAL")
    void_pct = S.f_num(b, "void_content_pct")
    if S.D(void_pct) < 0:
        S.bad_request("Field 'void_content_pct' must be >= 0")
    delam = S.f_num(b, "delamination_area_cm2")
    if S.D(delam) < 0:
        S.bad_request("Field 'delamination_area_cm2' must be >= 0")
    # priority 6: state
    if wo["status"] != "IN_INSPECTION":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not IN_INSPECTION")
    # priority 8: segregation of duties, then repair limit
    for s in db.STORE["layup_sessions"].values():
        if (s["work_order_id"] == wo["id"] and s["status"] == "ACTIVE"
                and s["laminator_id"] == uid):
            raise ApiError("ERR_SOD_INSPECTOR_LAMINATOR", 403,
                           "Inspector may not inspect their own layup")
    result = S.inspection_disposition(void_pct, delam)
    book = db.STORE["ply_books"][wo["ply_book_id"]]
    if result == "REPAIR_REQUIRED" and wo["repair_count"] >= book["max_repair_attempts"]:
        raise ApiError("ERR_REPAIR_LIMIT_EXCEEDED", 409,
                       "repair_count has reached the ply book's max_repair_attempts")
    t = db.now()
    rec = db.new_base()
    rec.update({
        "work_order_id": wo["id"],
        "inspector_id": uid,
        "method": method,
        "void_content_pct": void_pct,
        "delamination_area_cm2": delam,
        "result": result,
        "inspected_at": db.fmt_dt(t),
        "created_repair_id": None,
    })
    db.STORE["inspections"][rec["id"]] = rec
    if result == "PASS":
        wo["status"] = "ACCEPTED"
        db.touch(wo)
        for r in db.STORE["repairs"].values():
            if r["work_order_id"] == wo["id"] and r["status"] == "OPEN":
                r["status"] = "CLOSED"
                db.touch(r)
        mold = db.STORE["molds"][wo["mold_id"]]
        if mold["tooling_phase"] == "PROTOTYPE":
            mold["prototype_parts_validated"] += 1
            db.touch(mold)
    elif result == "REPAIR_REQUIRED":
        for r in db.STORE["repairs"].values():
            if r["work_order_id"] == wo["id"] and r["status"] == "OPEN":
                r["status"] = "SUPERSEDED"
                db.touch(r)
        repair = db.new_base()
        repair.update({
            "work_order_id": wo["id"],
            "source_inspection_id": rec["id"],
            "repair_seq": wo["repair_count"] + 1,
            "status": "OPEN",
        })
        db.STORE["repairs"][repair["id"]] = repair
        rec["created_repair_id"] = repair["id"]
        wo["repair_count"] += 1
        wo["status"] = "REPAIR"
        db.touch(wo)
    else:  # FAIL
        wo["status"] = "SCRAPPED"
        wo["scrap_reason"] = "INSPECTION_FAIL"
        db.touch(wo)
        for r in db.STORE["repairs"].values():
            if r["work_order_id"] == wo["id"] and r["status"] == "OPEN":
                r["status"] = "SUPERSEDED"
                db.touch(r)
    return success(S.inspection_out(rec), 201, "object")


@app.get("/inspections")
def list_inspections():
    authenticate(ALL_ROLES)
    data, pagination = S.paginate(
        db.STORE["inspections"], S.inspection_out,
        [("work_order_id", "work_order_id"), ("result", "result")],
    )
    return success(data, 200, "array", pagination)


@app.get("/inspections/<iid>")
def get_inspection(iid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("inspections", iid, "Inspection")
    return success(S.inspection_out(rec), 200, "object")


@app.get("/repairs")
def list_repairs():
    authenticate(ALL_ROLES)
    data, pagination = S.paginate(
        db.STORE["repairs"], S.repair_out,
        [("work_order_id", "work_order_id"), ("source_inspection_id", "source_inspection_id"),
         ("status", "status")],
    )
    return success(data, 200, "array", pagination)


@app.get("/repairs/<rid>")
def get_repair(rid):
    authenticate(ALL_ROLES)
    rec = S.get_or_404("repairs", rid, "Repair")
    return success(S.repair_out(rec), 200, "object")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
