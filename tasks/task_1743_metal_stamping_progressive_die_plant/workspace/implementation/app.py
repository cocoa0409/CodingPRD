"""Metal Stamping & Progressive Die Plant API — Flask entry point.

In-memory only; store starts empty on every boot. All state machines,
calculations, validations, and the validation pipeline order follow PRD.md.
"""
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask

import db
from errors import (
    ApiError,
    invalid_request,
    not_found,
    invalid_state,
    stale_version,
    quality_hold,
    segregation,
    capacity,
    material_mismatch,
    schedule_conflict,
    changeover_conflict,
    ppap_level_mismatch,
    release_gate,
    coil_weight,
    price_floor,
    duplicate,
    no_shots,
    rejects_exceed,
    return_exceeded,
    order_not_completed,
    audit_findings,
)
from middleware import require_role
from util import (
    now,
    set_now,
    iso_now,
    format_ts,
    parse_dt,
    success_object,
    success_list,
    error_response,
    get_pagination,
    get_body,
    require_fields,
    as_str,
    as_int,
    as_number,
    as_bool,
    as_enum,
    round3,
    round6,
    round2,
    num,
    touch,
    common_fields,
    ledger_fields,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(not_found())


@app.errorhandler(405)
def handle_405(err):
    return error_response(not_found())


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError("ERR_INTERNAL", str(getattr(err, "original_exception", err)), 500))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def ser_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "customer_code": c["customer_code"],
        "steel_index_basis": c["steel_index_basis"],
        "base_index_value": num(c["base_index_value"]),
        "pass_through_pct": num(c["pass_through_pct"]),
        "active": c["active"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_part(p):
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "part_number": p["part_number"],
        "material_spec": p["material_spec"],
        "thickness_mm": num(p["thickness_mm"]),
        "net_weight_kg": num(p["net_weight_kg"]),
        "base_piece_price_cents": p["base_piece_price_cents"],
        "ppap_required_level": p["ppap_required_level"],
        "steel_content_kg": num(p["steel_content_kg"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_die(d):
    return {
        "id": d["id"],
        "die_code": d["die_code"],
        "die_type": d["die_type"],
        "total_stations": d["total_stations"],
        "rated_tonnage": d["rated_tonnage"],
        "min_bed_width_mm": d["min_bed_width_mm"],
        "status": d["status"],
        "total_shots_lifetime": d["total_shots_lifetime"],
        "shots_since_repair": d["shots_since_repair"],
        "repair_threshold_shots": d["repair_threshold_shots"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_press(p):
    return {
        "id": p["id"],
        "press_code": p["press_code"],
        "tonnage": p["tonnage"],
        "bed_width_mm": p["bed_width_mm"],
        "strokes_per_min": p["strokes_per_min"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "part_id": a["part_id"],
        "die_id": a["die_id"],
        "qualified": a["qualified"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_coil(c):
    return {
        "id": c["id"],
        "coil_number": c["coil_number"],
        "heat_lot_number": c["heat_lot_number"],
        "material_spec": c["material_spec"],
        "thickness_mm": num(c["thickness_mm"]),
        "received_weight_kg": num(c["received_weight_kg"]),
        "remaining_weight_kg": num(c["remaining_weight_kg"]),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_layout(l):
    return {
        "id": l["id"],
        "part_id": l["part_id"],
        "revision": l["revision"],
        "strip_width_mm": num(l["strip_width_mm"]),
        "pitch_mm": num(l["pitch_mm"]),
        "parts_per_strip_segment": l["parts_per_strip_segment"],
        "gross_weight_per_part_kg": num(l["gross_weight_per_part_kg"]),
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "part_id": o["part_id"],
        "quantity_ordered": o["quantity_ordered"],
        "due_date": o["due_date"],
        "status": o["status"],
        "quantity_produced_good": o["quantity_produced_good"],
        "quantity_scrapped": o["quantity_scrapped"],
        "steel_index_at_release": (num(o["steel_index_at_release"]) if o["steel_index_at_release"] is not None else None),
        "pricing_variant": o["pricing_variant"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_change_event(e):
    return {
        "id": e["id"],
        "press_id": e["press_id"],
        "from_die_id": e["from_die_id"],
        "to_die_id": e["to_die_id"],
        "planned_start": e["planned_start"],
        "planned_end": e["planned_end"],
        "actual_start": e["actual_start"],
        "actual_end": e["actual_end"],
        "smed_target_minutes": e["smed_target_minutes"],
        "status": e["status"],
        "variance_minutes": e["variance_minutes"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_run(r):
    return {
        "id": r["id"],
        "production_order_id": r["production_order_id"],
        "press_id": r["press_id"],
        "die_id": r["die_id"],
        "coil_id": r["coil_id"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "status": r["status"],
        "shots_recorded": r["shots_recorded"],
        "good_count": r["good_count"],
        "reject_count": r["reject_count"],
        "steel_consumed_kg": (num(r["steel_consumed_kg"]) if r["steel_consumed_kg"] is not None else None),
        "standard_scrap_rate": (num(r["standard_scrap_rate"]) if r.get("standard_scrap_rate") is not None else None),
        "actual_scrap_rate": (num(r["actual_scrap_rate"]) if r.get("actual_scrap_rate") is not None else None),
        "scrap_variance": (num(r["scrap_variance"]) if r.get("scrap_variance") is not None else None),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_reject_event(e):
    return {
        "id": e["id"],
        "production_run_id": e["production_run_id"],
        "station_number": e["station_number"],
        "sensor_code": e["sensor_code"],
        "quantity": e["quantity"],
        "sensed_at": e["sensed_at"],
        "created_at": e["created_at"],
    }


def ser_outside(o):
    return {
        "id": o["id"],
        "production_order_id": o["production_order_id"],
        "operation_type": o["operation_type"],
        "quantity_sent": o["quantity_sent"],
        "quantity_returned_good": o["quantity_returned_good"],
        "quantity_returned_scrap": o["quantity_returned_scrap"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_ppap(s):
    return {
        "id": s["id"],
        "part_id": s["part_id"],
        "level": s["level"],
        "submission_revision": s["submission_revision"],
        "control_plan_attached": s["control_plan_attached"],
        "status": s["status"],
        "rejection_reason": s["rejection_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_audit(a):
    return {
        "id": a["id"],
        "press_id": a["press_id"],
        "audit_tier": a["audit_tier"],
        "scheduled_date": a["scheduled_date"],
        "executed_at": a["executed_at"],
        "result": a["result"],
        "findings_count": a["findings_count"],
        "escalated_from_id": a["escalated_from_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_index_pub(p):
    return {
        "id": p["id"],
        "index_code": p["index_code"],
        "published_at": p["published_at"],
        "value_usd_per_ton": num(p["value_usd_per_ton"]),
        "created_at": p["created_at"],
    }


def ser_price_adjustment(a):
    return {
        "id": a["id"],
        "production_order_id": a["production_order_id"],
        "variant_applied": a["variant_applied"],
        "base_index_value": num(a["base_index_value"]),
        "applied_index_value": num(a["applied_index_value"]),
        "adjusted_piece_price_cents": a["adjusted_piece_price_cents"],
        "created_at": a["created_at"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers (existence check)
# ---------------------------------------------------------------------------

def get_or_404(store, key):
    ent = store.get(key)
    if ent is None:
        raise not_found()
    return ent


def latest_index_value(index_code, reference_dt):
    """Latest IndexPublication for index_code with published_at <= reference_dt.
    Selector: max published_at; tie-break: earliest created_at ASC. Returns Decimal or None."""
    best = None
    for pub in db.index_publications.values():
        if pub["index_code"] != index_code:
            continue
        if pub["_published_dt"] > reference_dt:
            continue
        if best is None:
            best = pub
            continue
        if pub["_published_dt"] > best["_published_dt"]:
            best = pub
        elif pub["_published_dt"] == best["_published_dt"]:
            if pub["_created_seq"] < best["_created_seq"]:
                best = pub
    if best is None:
        return None
    return best["value_usd_per_ton"]


# Creation-sequence counter to provide a deterministic created_at ordering
# tiebreak that matches insertion order for identical timestamps.
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Clock + Index publications
# ---------------------------------------------------------------------------

@app.post("/api/_clock/set_current_utc")
def clock_set():
    require_role("PlantAdmin")
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    set_now(dt)
    return success_object({}, 200)


@app.post("/api/index-publications")
def index_pub_create():
    require_role("PlantAdmin")
    body = get_body()
    require_fields(body, ["index_code", "published_at", "value_usd_per_ton"])
    index_code = as_enum(body.get("index_code"), "index_code", {"CRU_HRC", "CRU_CRC", "LME_STEEL_SCRAP"})
    published_dt = parse_dt(body.get("published_at"), "published_at")
    value = as_number(body.get("value_usd_per_ton"), "value_usd_per_ton", minimum=0)
    rec = ledger_fields()
    rec["index_code"] = index_code
    rec["published_at"] = format_ts(published_dt)
    rec["value_usd_per_ton"] = value
    rec["_published_dt"] = published_dt
    rec["_created_seq"] = next_seq()
    db.index_publications[rec["id"]] = rec
    return success_object(ser_index_pub(rec), 201)


@app.get("/api/index-publications")
def index_pub_list():
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst")
    limit, offset = get_pagination()
    items = list(db.index_publications.values())
    index_code = None
    from flask import request as _req
    if "index_code" in _req.args:
        index_code = _req.args.get("index_code")
    if index_code:
        items = [p for p in items if p["index_code"] == index_code]
    items.sort(key=lambda p: (p["_created_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_index_pub(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@app.post("/api/customers")
def customer_create():
    require_role("PlantAdmin")
    body = get_body()
    require_fields(body, ["name", "customer_code", "steel_index_basis", "base_index_value", "pass_through_pct"])
    name = as_str(body.get("name"), "name")
    code = as_str(body.get("customer_code"), "customer_code")
    basis = as_enum(body.get("steel_index_basis"), "steel_index_basis", {"CRU_HRC", "CRU_CRC", "LME_STEEL_SCRAP"})
    base_index = as_number(body.get("base_index_value"), "base_index_value", minimum=0)
    ptp = as_number(body.get("pass_through_pct"), "pass_through_pct", minimum=0)
    if ptp > 1:
        raise invalid_request("pass_through_pct must be <= 1")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise invalid_request("active must be a boolean")
    for c in db.customers.values():
        if c["customer_code"] == code:
            raise duplicate("customer_code already exists")
    rec = common_fields()
    rec.update({
        "name": name,
        "customer_code": code,
        "steel_index_basis": basis,
        "base_index_value": base_index,
        "pass_through_pct": ptp,
        "active": active,
    })
    db.customers[rec["id"]] = rec
    return success_object(ser_customer(rec), 201)


@app.get("/api/customers")
def customer_list():
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst")
    limit, offset = get_pagination()
    items = list(db.customers.values())
    from flask import request as _req
    if "active" in _req.args:
        want = _req.args.get("active")
        want_bool = want.lower() == "true"
        items = [c for c in items if c["active"] == want_bool]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_customer(c) for c in page], limit, offset, total)


@app.get("/api/customers/<cid>")
def customer_get(cid):
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst")
    c = get_or_404(db.customers, cid)
    return success_object(ser_customer(c))


@app.get("/api/customers/<cid>/parts")
def customer_parts(cid):
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst")
    get_or_404(db.customers, cid)
    limit, offset = get_pagination()
    items = [p for p in db.parts.values() if p["customer_id"] == cid]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_part(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

@app.post("/api/parts")
def part_create():
    require_role("ProcessEngineer")
    body = get_body()
    require_fields(body, ["customer_id", "part_number", "material_spec", "thickness_mm",
                          "net_weight_kg", "base_piece_price_cents", "ppap_required_level"])
    cust = get_or_404(db.customers, as_str(body.get("customer_id"), "customer_id"))
    part_number = as_str(body.get("part_number"), "part_number")
    material_spec = as_str(body.get("material_spec"), "material_spec")
    thickness = as_number(body.get("thickness_mm"), "thickness_mm", minimum=0, minimum_exclusive=True)
    net_weight = as_number(body.get("net_weight_kg"), "net_weight_kg", minimum=0)
    base_price = as_int(body.get("base_piece_price_cents"), "base_piece_price_cents", minimum=1)
    ppap_level = as_int(body.get("ppap_required_level"), "ppap_required_level")
    if ppap_level < 1 or ppap_level > 5:
        raise invalid_request("ppap_required_level must be between 1 and 5")
    for p in db.parts.values():
        if p["customer_id"] == cust["id"] and p["part_number"] == part_number:
            raise duplicate("part_number already exists for this customer")
    rec = common_fields()
    rec.update({
        "customer_id": cust["id"],
        "part_number": part_number,
        "material_spec": material_spec,
        "thickness_mm": thickness,
        "net_weight_kg": net_weight,
        "base_piece_price_cents": base_price,
        "ppap_required_level": ppap_level,
        "steel_content_kg": Decimal("0"),
    })
    db.parts[rec["id"]] = rec
    return success_object(ser_part(rec), 201)


@app.get("/api/parts")
def part_list():
    require_role("PlantAdmin", "ProcessEngineer", "ProductionPlanner", "QualityEngineer", "CostAnalyst")
    limit, offset = get_pagination()
    items = list(db.parts.values())
    from flask import request as _req
    if "customer_id" in _req.args:
        cid = _req.args.get("customer_id")
        items = [p for p in items if p["customer_id"] == cid]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_part(p) for p in page], limit, offset, total)


@app.get("/api/parts/<pid>")
def part_get(pid):
    require_role("PlantAdmin", "ProcessEngineer", "ProductionPlanner", "QualityEngineer", "CostAnalyst")
    p = get_or_404(db.parts, pid)
    return success_object(ser_part(p))


@app.get("/api/parts/<pid>/strip-layouts")
def part_layouts(pid):
    require_role("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    get_or_404(db.parts, pid)
    limit, offset = get_pagination()
    items = [l for l in db.strip_layouts.values() if l["part_id"] == pid]
    from flask import request as _req
    if "status" in _req.args:
        st = _req.args.get("status")
        items = [l for l in items if l["status"] == st]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_layout(l) for l in page], limit, offset, total)


@app.get("/api/parts/<pid>/ppap-submissions")
def part_ppaps(pid):
    require_role("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    get_or_404(db.parts, pid)
    limit, offset = get_pagination()
    items = [s for s in db.ppap_submissions.values() if s["part_id"] == pid]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_ppap(s) for s in page], limit, offset, total)


@app.get("/api/parts/<pid>/die-assignments")
def part_assignments(pid):
    require_role("PlantAdmin", "ProcessEngineer", "ProductionPlanner")
    get_or_404(db.parts, pid)
    limit, offset = get_pagination()
    items = [a for a in db.part_die_assignments.values() if a["part_id"] == pid]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_assignment(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Dies
# ---------------------------------------------------------------------------

@app.post("/api/dies")
def die_create():
    require_role("ToolroomManager")
    body = get_body()
    require_fields(body, ["die_code", "die_type", "total_stations", "rated_tonnage",
                          "min_bed_width_mm", "repair_threshold_shots"])
    code = as_str(body.get("die_code"), "die_code")
    dtype = as_enum(body.get("die_type"), "die_type", {"PROGRESSIVE", "TRANSFER"})
    stations = as_int(body.get("total_stations"), "total_stations", minimum=1)
    tonnage = as_int(body.get("rated_tonnage"), "rated_tonnage", minimum=1)
    bed = as_int(body.get("min_bed_width_mm"), "min_bed_width_mm", minimum=1)
    threshold = as_int(body.get("repair_threshold_shots"), "repair_threshold_shots", minimum=1)
    for d in db.dies.values():
        if d["die_code"] == code:
            raise duplicate("die_code already exists")
    rec = common_fields()
    rec.update({
        "die_code": code,
        "die_type": dtype,
        "total_stations": stations,
        "rated_tonnage": tonnage,
        "min_bed_width_mm": bed,
        "status": "AVAILABLE",
        "total_shots_lifetime": 0,
        "shots_since_repair": 0,
        "repair_threshold_shots": threshold,
    })
    db.dies[rec["id"]] = rec
    return success_object(ser_die(rec), 201)


@app.get("/api/dies")
def die_list():
    require_role("PlantAdmin", "ToolroomManager", "SetupLead", "ProductionPlanner")
    limit, offset = get_pagination()
    items = list(db.dies.values())
    from flask import request as _req
    if "status" in _req.args:
        st = _req.args.get("status")
        items = [d for d in items if d["status"] == st]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_die(d) for d in page], limit, offset, total)


@app.get("/api/dies/<did>")
def die_get(did):
    require_role("PlantAdmin", "ToolroomManager", "SetupLead", "ProductionPlanner")
    d = get_or_404(db.dies, did)
    return success_object(ser_die(d))


def _abort_scheduled_runs_for_die(die_id):
    for r in db.production_runs.values():
        if r["die_id"] == die_id and r["status"] == "SCHEDULED":
            r["status"] = "ABORTED"
            touch(r)


@app.post("/api/dies/<did>/send-to-repair")
def die_send_repair(did):
    require_role("ToolroomManager")
    d = get_or_404(db.dies, did)
    if d["status"] not in ("AVAILABLE", "ASSIGNED"):
        raise invalid_state("Die must be AVAILABLE or ASSIGNED to send to repair")
    if d["shots_since_repair"] < d["repair_threshold_shots"]:
        raise invalid_state("Die has not reached its repair threshold")
    d["status"] = "IN_REPAIR"
    touch(d)
    _abort_scheduled_runs_for_die(d["id"])
    return success_object(ser_die(d))


@app.post("/api/dies/<did>/complete-repair")
def die_complete_repair(did):
    require_role("ToolroomManager")
    d = get_or_404(db.dies, did)
    if d["status"] != "IN_REPAIR":
        raise invalid_state("Die must be IN_REPAIR to complete repair")
    d["status"] = "AVAILABLE"
    d["shots_since_repair"] = 0
    touch(d)
    return success_object(ser_die(d))


@app.post("/api/dies/<did>/retire")
def die_retire(did):
    require_role("ToolroomManager")
    d = get_or_404(db.dies, did)
    if d["status"] != "AVAILABLE":
        raise invalid_state("Die must be AVAILABLE to retire")
    for r in db.production_runs.values():
        if r["die_id"] == d["id"] and r["status"] in ("SCHEDULED", "RUNNING"):
            raise invalid_state("Die has active production runs")
    d["status"] = "RETIRED"
    touch(d)
    # Delete all part-die assignments referencing this die
    to_delete = [aid for aid, a in db.part_die_assignments.items() if a["die_id"] == d["id"]]
    for aid in to_delete:
        del db.part_die_assignments[aid]
    return success_object(ser_die(d))


# ---------------------------------------------------------------------------
# Presses
# ---------------------------------------------------------------------------

@app.post("/api/presses")
def press_create():
    require_role("PlantAdmin")
    body = get_body()
    require_fields(body, ["press_code", "tonnage", "bed_width_mm", "strokes_per_min"])
    code = as_str(body.get("press_code"), "press_code")
    tonnage = as_int(body.get("tonnage"), "tonnage", minimum=1)
    bed = as_int(body.get("bed_width_mm"), "bed_width_mm", minimum=1)
    spm = as_int(body.get("strokes_per_min"), "strokes_per_min", minimum=1)
    for p in db.presses.values():
        if p["press_code"] == code:
            raise duplicate("press_code already exists")
    rec = common_fields()
    rec.update({
        "press_code": code,
        "tonnage": tonnage,
        "bed_width_mm": bed,
        "strokes_per_min": spm,
        "status": "IDLE",
    })
    db.presses[rec["id"]] = rec
    return success_object(ser_press(rec), 201)


@app.get("/api/presses")
def press_list():
    require_role("PlantAdmin", "ProductionPlanner", "SetupLead", "PressOperator", "QualityEngineer")
    limit, offset = get_pagination()
    items = list(db.presses.values())
    from flask import request as _req
    if "status" in _req.args:
        st = _req.args.get("status")
        items = [p for p in items if p["status"] == st]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_press(p) for p in page], limit, offset, total)


@app.get("/api/presses/<pid>")
def press_get(pid):
    require_role("PlantAdmin", "ProductionPlanner", "SetupLead", "PressOperator", "QualityEngineer")
    p = get_or_404(db.presses, pid)
    return success_object(ser_press(p))


@app.get("/api/presses/<pid>/die-change-events")
def press_change_events(pid):
    require_role("PlantAdmin", "ProductionPlanner", "SetupLead")
    get_or_404(db.presses, pid)
    limit, offset = get_pagination()
    items = [e for e in db.die_change_events.values() if e["press_id"] == pid]
    from flask import request as _req
    if "status" in _req.args:
        st = _req.args.get("status")
        items = [e for e in items if e["status"] == st]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_change_event(e) for e in page], limit, offset, total)


@app.get("/api/presses/<pid>/production-runs")
def press_runs(pid):
    require_role("PlantAdmin", "ProductionPlanner", "PressOperator")
    get_or_404(db.presses, pid)
    limit, offset = get_pagination()
    items = [r for r in db.production_runs.values() if r["press_id"] == pid]
    from flask import request as _req
    if "status" in _req.args:
        st = _req.args.get("status")
        items = [r for r in items if r["status"] == st]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_run(r) for r in page], limit, offset, total)


@app.get("/api/presses/<pid>/layered-audits")
def press_audits(pid):
    require_role("PlantAdmin", "QualityEngineer")
    get_or_404(db.presses, pid)
    limit, offset = get_pagination()
    items = [a for a in db.layered_audits.values() if a["press_id"] == pid]
    from flask import request as _req
    if "result" in _req.args:
        v = _req.args.get("result")
        items = [a for a in items if a["result"] == v]
    if "audit_tier" in _req.args:
        v = _req.args.get("audit_tier")
        try:
            vt = int(v)
        except (ValueError, TypeError):
            raise invalid_request("audit_tier must be an integer")
        items = [a for a in items if a["audit_tier"] == vt]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_audit(a) for a in page], limit, offset, total)


@app.get("/api/presses/<pid>/smed-performance")
def press_smed(pid):
    require_role("PlantAdmin", "SetupLead", "ProductionPlanner")
    get_or_404(db.presses, pid)
    completed = [e for e in db.die_change_events.values()
                 if e["press_id"] == pid and e["status"] == "COMPLETED" and e["variance_minutes"] is not None]
    # Order by actual_end DESC, tie-break earliest created_at ASC
    def sort_key(e):
        return e["_actual_end_dt"]
    completed.sort(key=lambda e: e["created_at"])  # earliest created first for ties
    completed.sort(key=sort_key, reverse=True)  # actual_end DESC
    n = min(10, len(completed))
    selected = completed[:n]
    if n == 0:
        avg = Decimal("0")
    else:
        total_var = sum(Decimal(e["variance_minutes"]) for e in selected)
        avg = round2(total_var / Decimal(n))
    return success_object({
        "press_id": pid,
        "events_considered": n,
        "average_variance_minutes": num(avg),
    })


# ---------------------------------------------------------------------------
# Part-Die Assignments
# ---------------------------------------------------------------------------

@app.post("/api/part-die-assignments")
def assignment_create():
    require_role("ProcessEngineer")
    body = get_body()
    require_fields(body, ["part_id", "die_id"])
    part = get_or_404(db.parts, as_str(body.get("part_id"), "part_id"))
    die = get_or_404(db.dies, as_str(body.get("die_id"), "die_id"))
    rec = common_fields()
    rec.update({
        "part_id": part["id"],
        "die_id": die["id"],
        "qualified": False,
    })
    db.part_die_assignments[rec["id"]] = rec
    return success_object(ser_assignment(rec), 201)


@app.get("/api/part-die-assignments")
def assignment_list():
    require_role("PlantAdmin", "ProcessEngineer", "ProductionPlanner")
    limit, offset = get_pagination()
    items = list(db.part_die_assignments.values())
    from flask import request as _req
    if "part_id" in _req.args:
        v = _req.args.get("part_id")
        items = [a for a in items if a["part_id"] == v]
    if "die_id" in _req.args:
        v = _req.args.get("die_id")
        items = [a for a in items if a["die_id"] == v]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_assignment(a) for a in page], limit, offset, total)


@app.get("/api/part-die-assignments/<aid>")
def assignment_get(aid):
    require_role("PlantAdmin", "ProcessEngineer", "ProductionPlanner")
    a = get_or_404(db.part_die_assignments, aid)
    return success_object(ser_assignment(a))


# ---------------------------------------------------------------------------
# Steel coils
# ---------------------------------------------------------------------------

@app.post("/api/steel-coils")
def coil_create():
    require_role("ShippingClerk")
    body = get_body()
    require_fields(body, ["coil_number", "heat_lot_number", "material_spec", "thickness_mm", "received_weight_kg"])
    number = as_str(body.get("coil_number"), "coil_number")
    heat_lot = as_str(body.get("heat_lot_number"), "heat_lot_number")
    material = as_str(body.get("material_spec"), "material_spec")
    thickness = as_number(body.get("thickness_mm"), "thickness_mm", minimum=0, minimum_exclusive=True)
    received = round3(as_number(body.get("received_weight_kg"), "received_weight_kg", minimum=0, minimum_exclusive=True))
    for c in db.steel_coils.values():
        if c["coil_number"] == number:
            raise duplicate("coil_number already exists")
    rec = common_fields()
    rec.update({
        "coil_number": number,
        "heat_lot_number": heat_lot,
        "material_spec": material,
        "thickness_mm": thickness,
        "received_weight_kg": received,
        "remaining_weight_kg": received,
        "status": "RECEIVED",
    })
    db.steel_coils[rec["id"]] = rec
    return success_object(ser_coil(rec), 201)


@app.get("/api/steel-coils")
def coil_list():
    require_role("PlantAdmin", "ShippingClerk", "QualityEngineer", "ProductionPlanner")
    limit, offset = get_pagination()
    items = list(db.steel_coils.values())
    from flask import request as _req
    if "status" in _req.args:
        st = _req.args.get("status")
        items = [c for c in items if c["status"] == st]
    if "heat_lot_number" in _req.args:
        v = _req.args.get("heat_lot_number")
        items = [c for c in items if c["heat_lot_number"] == v]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_coil(c) for c in page], limit, offset, total)


@app.get("/api/steel-coils/<cid>")
def coil_get(cid):
    require_role("PlantAdmin", "ShippingClerk", "QualityEngineer", "ProductionPlanner", "PressOperator")
    c = get_or_404(db.steel_coils, cid)
    return success_object(ser_coil(c))


@app.post("/api/steel-coils/<cid>/approve")
def coil_approve(cid):
    require_role("QualityEngineer")
    c = get_or_404(db.steel_coils, cid)
    if c["status"] != "RECEIVED":
        raise invalid_state("Coil must be RECEIVED to approve")
    c["status"] = "APPROVED"
    touch(c)
    return success_object(ser_coil(c))


@app.post("/api/steel-coils/<cid>/reject")
def coil_reject(cid):
    require_role("QualityEngineer")
    c = get_or_404(db.steel_coils, cid)
    if c["status"] != "RECEIVED":
        raise invalid_state("Coil must be RECEIVED to reject")
    c["status"] = "REJECTED"
    touch(c)
    return success_object(ser_coil(c))


@app.post("/api/steel-coils/<cid>/hold")
def coil_hold(cid):
    require_role("QualityEngineer")
    c = get_or_404(db.steel_coils, cid)
    if c["status"] != "APPROVED":
        raise invalid_state("Coil must be APPROVED to hold")
    c["status"] = "ON_HOLD"
    touch(c)
    return success_object(ser_coil(c))


@app.post("/api/steel-coils/<cid>/release-hold")
def coil_release_hold(cid):
    require_role("QualityEngineer")
    c = get_or_404(db.steel_coils, cid)
    if c["status"] != "ON_HOLD":
        raise invalid_state("Coil must be ON_HOLD to release hold")
    c["status"] = "APPROVED"
    touch(c)
    return success_object(ser_coil(c))


# ---------------------------------------------------------------------------
# Heat lot exposure (computed read)
# ---------------------------------------------------------------------------

@app.get("/api/heat-lots/<heat_lot_number>/exposure")
def heat_lot_exposure(heat_lot_number):
    require_role("PlantAdmin", "QualityEngineer", "CostAnalyst")
    coils = [c for c in db.steel_coils.values() if c["heat_lot_number"] == heat_lot_number]
    exposure = Decimal("0")
    exposure_coil_ids = set()
    for c in coils:
        if c["status"] in ("APPROVED", "ON_HOLD", "QUARANTINED"):
            exposure += c["remaining_weight_kg"]
            exposure_coil_ids.add(c["id"])
    all_coil_ids = {c["id"] for c in coils}
    affected = set()
    for r in db.production_runs.values():
        if r["coil_id"] in all_coil_ids and r["status"] in ("SCHEDULED", "RUNNING", "COMPLETED"):
            affected.add(r["production_order_id"])
    return success_object({
        "heat_lot_number": heat_lot_number,
        "exposure_kg": num(round3(exposure)),
        "affected_order_ids": sorted(affected),
    })


# ---------------------------------------------------------------------------
# Strip layouts
# ---------------------------------------------------------------------------

@app.post("/api/strip-layouts")
def layout_create():
    require_role("ProcessEngineer")
    body = get_body()
    require_fields(body, ["part_id", "revision", "strip_width_mm", "pitch_mm",
                          "parts_per_strip_segment", "gross_weight_per_part_kg"])
    part = get_or_404(db.parts, as_str(body.get("part_id"), "part_id"))
    revision = as_str(body.get("revision"), "revision")
    strip_w = as_number(body.get("strip_width_mm"), "strip_width_mm", minimum=0, minimum_exclusive=True)
    pitch = as_number(body.get("pitch_mm"), "pitch_mm", minimum=0, minimum_exclusive=True)
    pps = as_int(body.get("parts_per_strip_segment"), "parts_per_strip_segment", minimum=1)
    gross = as_number(body.get("gross_weight_per_part_kg"), "gross_weight_per_part_kg", minimum=0, minimum_exclusive=True)
    rec = common_fields()
    rec.update({
        "part_id": part["id"],
        "revision": revision,
        "strip_width_mm": strip_w,
        "pitch_mm": pitch,
        "parts_per_strip_segment": pps,
        "gross_weight_per_part_kg": gross,
        "status": "DRAFT",
    })
    db.strip_layouts[rec["id"]] = rec
    return success_object(ser_layout(rec), 201)


@app.get("/api/strip-layouts/<lid>")
def layout_get(lid):
    require_role("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    l = get_or_404(db.strip_layouts, lid)
    return success_object(ser_layout(l))


@app.post("/api/strip-layouts/<lid>/approve")
def layout_approve(lid):
    require_role("ProcessEngineer")
    l = get_or_404(db.strip_layouts, lid)
    if l["status"] != "DRAFT":
        raise invalid_state("Layout must be DRAFT to approve")
    body = get_body()
    require_fields(body, ["expected_part_version"])
    expected = body.get("expected_part_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_part_version must be an integer")
    part = get_or_404(db.parts, l["part_id"])
    if part["version"] != expected:
        raise stale_version("expected_part_version does not match current part version")
    # Supersede any previously APPROVED layout for this part
    for other in db.strip_layouts.values():
        if other["part_id"] == part["id"] and other["status"] == "APPROVED" and other["id"] != l["id"]:
            other["status"] = "SUPERSEDED"
            touch(other)
    l["status"] = "APPROVED"
    touch(l)
    part["steel_content_kg"] = l["gross_weight_per_part_kg"]
    touch(part)
    return success_object(ser_layout(l))


# ---------------------------------------------------------------------------
# Production orders
# ---------------------------------------------------------------------------

@app.post("/api/production-orders")
def order_create():
    require_role("ProductionPlanner")
    body = get_body()
    require_fields(body, ["part_id", "quantity_ordered", "due_date"])
    part = get_or_404(db.parts, as_str(body.get("part_id"), "part_id"))
    qty = as_int(body.get("quantity_ordered"), "quantity_ordered", minimum=1)
    due_dt = parse_dt(body.get("due_date"), "due_date")
    variant = body.get("pricing_variant", "RELEASE_LOCKED")
    if variant not in ("RELEASE_LOCKED", "SHIPMENT_SPOT"):
        raise invalid_request("pricing_variant must be RELEASE_LOCKED or SHIPMENT_SPOT")
    rec = common_fields()
    rec.update({
        "part_id": part["id"],
        "quantity_ordered": qty,
        "due_date": format_ts(due_dt),
        "status": "OPEN",
        "quantity_produced_good": 0,
        "quantity_scrapped": 0,
        "steel_index_at_release": None,
        "pricing_variant": variant,
    })
    db.production_orders[rec["id"]] = rec
    return success_object(ser_order(rec), 201)


@app.get("/api/production-orders")
def order_list():
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst", "PressOperator")
    limit, offset = get_pagination()
    items = list(db.production_orders.values())
    from flask import request as _req
    if "part_id" in _req.args:
        v = _req.args.get("part_id")
        items = [o for o in items if o["part_id"] == v]
    if "status" in _req.args:
        v = _req.args.get("status")
        items = [o for o in items if o["status"] == v]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_order(o) for o in page], limit, offset, total)


@app.get("/api/production-orders/<oid>")
def order_get(oid):
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst", "PressOperator")
    o = get_or_404(db.production_orders, oid)
    return success_object(ser_order(o))


@app.post("/api/production-orders/<oid>/release")
def order_release(oid):
    require_role("ProductionPlanner")
    o = get_or_404(db.production_orders, oid)
    if o["status"] != "OPEN":
        raise invalid_state("Order must be OPEN to release")
    body = get_body()
    require_fields(body, ["expected_order_version"])
    expected = body.get("expected_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_order_version must be an integer")
    if o["version"] != expected:
        raise stale_version("expected_order_version does not match current order version")
    part = db.parts.get(o["part_id"])
    customer = db.customers.get(part["customer_id"]) if part else None
    # Release gates
    if not customer or not customer["active"]:
        raise release_gate("Customer is not active")
    qualified = any(a for a in db.part_die_assignments.values()
                    if a["part_id"] == part["id"] and a["qualified"])
    if not qualified:
        raise release_gate("No qualified part-die assignment for this part")
    layout_ok = any(l for l in db.strip_layouts.values()
                    if l["part_id"] == part["id"] and l["status"] == "APPROVED")
    if not layout_ok:
        raise release_gate("No APPROVED strip layout for this part")
    ppap_ok = any(s for s in db.ppap_submissions.values()
                  if s["part_id"] == part["id"] and s["status"] == "APPROVED")
    if not ppap_ok:
        raise release_gate("No APPROVED PPAP submission for this part")
    # Capture the index at release using the logical clock
    idx = latest_index_value(customer["steel_index_basis"], now())
    o["steel_index_at_release"] = idx
    o["status"] = "RELEASED"
    touch(o)
    return success_object(ser_order(o))


@app.post("/api/production-orders/<oid>/complete")
def order_complete(oid):
    require_role("ProductionPlanner")
    o = get_or_404(db.production_orders, oid)
    if o["status"] != "IN_PROGRESS":
        raise invalid_state("Order must be IN_PROGRESS to complete")
    if o["quantity_produced_good"] < o["quantity_ordered"]:
        raise invalid_state("Produced good quantity has not reached the ordered quantity")
    for r in db.production_runs.values():
        if r["production_order_id"] == o["id"] and r["status"] == "RUNNING":
            raise invalid_state("Order still has a RUNNING production run")
    o["status"] = "COMPLETED"
    touch(o)
    return success_object(ser_order(o))


@app.post("/api/production-orders/<oid>/close")
def order_close(oid):
    require_role("ProductionPlanner")
    o = get_or_404(db.production_orders, oid)
    if o["status"] != "COMPLETED":
        raise invalid_state("Order must be COMPLETED to close")
    for op in db.outside_processing_orders.values():
        if op["production_order_id"] == o["id"] and op["status"] != "CLOSED":
            raise invalid_state("Order has outside processing orders that are not CLOSED")
    part = db.parts.get(o["part_id"])
    customer = db.customers.get(part["customer_id"]) if part else None
    # Select applied_index_value per variant
    if o["pricing_variant"] == "RELEASE_LOCKED":
        applied = o["steel_index_at_release"]
    else:  # SHIPMENT_SPOT
        applied = latest_index_value(customer["steel_index_basis"], now())
    if applied is None:
        applied = customer["base_index_value"]
    base_index = customer["base_index_value"]
    index_delta = Decimal(str(applied)) - Decimal(str(base_index))
    pass_through = index_delta * Decimal(str(customer["pass_through_pct"]))
    steel_content = Decimal(str(part["steel_content_kg"]))
    material_term_cents = pass_through * steel_content * Decimal(100) / Decimal(1000)
    material_term_rounded = material_term_cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    adjusted = int(part["base_piece_price_cents"]) + int(material_term_rounded)
    if adjusted < 1:
        raise price_floor()
    o["status"] = "CLOSED"
    touch(o)
    pa = ledger_fields()
    pa.update({
        "production_order_id": o["id"],
        "variant_applied": o["pricing_variant"],
        "base_index_value": Decimal(str(base_index)),
        "applied_index_value": Decimal(str(applied)),
        "adjusted_piece_price_cents": adjusted,
    })
    db.price_adjustments[pa["id"]] = pa
    return success_object(ser_order(o))


def _maybe_revert_order(order_id):
    """If the order is IN_PROGRESS and no run remains SCHEDULED or RUNNING, revert to RELEASED."""
    o = db.production_orders.get(order_id)
    if not o or o["status"] != "IN_PROGRESS":
        return
    active = any(r for r in db.production_runs.values()
                 if r["production_order_id"] == order_id and r["status"] in ("SCHEDULED", "RUNNING"))
    if not active:
        o["status"] = "RELEASED"
        touch(o)


@app.post("/api/production-orders/<oid>/cancel")
def order_cancel(oid):
    require_role("ProductionPlanner")
    o = get_or_404(db.production_orders, oid)
    if o["status"] not in ("OPEN", "RELEASED"):
        raise invalid_state("Order must be OPEN or RELEASED to cancel")
    for r in db.production_runs.values():
        if r["production_order_id"] == o["id"] and r["status"] == "RUNNING":
            raise invalid_state("Order has a RUNNING production run")
    for r in db.production_runs.values():
        if r["production_order_id"] == o["id"] and r["status"] == "SCHEDULED":
            r["status"] = "ABORTED"
            touch(r)
    o["status"] = "CANCELLED"
    touch(o)
    return success_object(ser_order(o))


@app.get("/api/production-orders/<oid>/production-runs")
def order_runs(oid):
    require_role("PlantAdmin", "ProductionPlanner", "PressOperator")
    get_or_404(db.production_orders, oid)
    limit, offset = get_pagination()
    items = [r for r in db.production_runs.values() if r["production_order_id"] == oid]
    from flask import request as _req
    if "status" in _req.args:
        v = _req.args.get("status")
        items = [r for r in items if r["status"] == v]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_run(r) for r in page], limit, offset, total)


@app.get("/api/production-orders/<oid>/price-adjustments")
def order_price_adjustments(oid):
    require_role("PlantAdmin", "ProductionPlanner", "CostAnalyst")
    get_or_404(db.production_orders, oid)
    limit, offset = get_pagination()
    items = [a for a in db.price_adjustments.values() if a["production_order_id"] == oid]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_price_adjustment(a) for a in page], limit, offset, total)


@app.get("/api/production-orders/<oid>/outside-processing-orders")
def order_outside(oid):
    require_role("PlantAdmin", "ProductionPlanner", "ShippingClerk")
    get_or_404(db.production_orders, oid)
    limit, offset = get_pagination()
    items = [x for x in db.outside_processing_orders.values() if x["production_order_id"] == oid]
    from flask import request as _req
    if "status" in _req.args:
        v = _req.args.get("status")
        items = [x for x in items if x["status"] == v]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_outside(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Die change events
# ---------------------------------------------------------------------------

def _overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@app.post("/api/die-change-events")
def change_event_create():
    require_role("SetupLead")
    body = get_body()
    require_fields(body, ["press_id", "to_die_id", "planned_start", "planned_end", "smed_target_minutes"])
    press = get_or_404(db.presses, as_str(body.get("press_id"), "press_id"))
    from_die_id = body.get("from_die_id")
    if from_die_id is not None:
        from_die = get_or_404(db.dies, as_str(from_die_id, "from_die_id"))
    else:
        from_die = None
    to_die = get_or_404(db.dies, as_str(body.get("to_die_id"), "to_die_id"))
    ps = parse_dt(body.get("planned_start"), "planned_start")
    pe = parse_dt(body.get("planned_end"), "planned_end")
    if pe <= ps:
        raise invalid_request("planned_end must be after planned_start")
    smed = as_int(body.get("smed_target_minutes"), "smed_target_minutes", minimum=0)
    # Changeover conflict: [planned_start, planned_end + 30min) vs other changeovers and runs
    ext_end = pe + timedelta(minutes=30)
    for e in db.die_change_events.values():
        if e["press_id"] != press["id"] or e["status"] not in ("PLANNED", "IN_PROGRESS"):
            continue
        e_start = e["_planned_start_dt"]
        e_end = e["_planned_end_dt"] + timedelta(minutes=30)
        if _overlap(ps, ext_end, e_start, e_end):
            raise changeover_conflict()
    for r in db.production_runs.values():
        if r["press_id"] != press["id"] or r["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if _overlap(ps, ext_end, r["_scheduled_start_dt"], r["_scheduled_end_dt"]):
            raise changeover_conflict()
    rec = common_fields()
    rec.update({
        "press_id": press["id"],
        "from_die_id": (from_die["id"] if from_die else None),
        "to_die_id": to_die["id"],
        "planned_start": format_ts(ps),
        "planned_end": format_ts(pe),
        "actual_start": None,
        "actual_end": None,
        "smed_target_minutes": smed,
        "status": "PLANNED",
        "variance_minutes": None,
        "_planned_start_dt": ps,
        "_planned_end_dt": pe,
    })
    db.die_change_events[rec["id"]] = rec
    return success_object(ser_change_event(rec), 201)


@app.get("/api/die-change-events")
def change_event_list():
    require_role("PlantAdmin", "SetupLead", "ProductionPlanner")
    limit, offset = get_pagination()
    items = list(db.die_change_events.values())
    from flask import request as _req
    for key in ("press_id", "from_die_id", "to_die_id", "status"):
        if key in _req.args:
            v = _req.args.get(key)
            items = [e for e in items if e[key] == v]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_change_event(e) for e in page], limit, offset, total)


@app.get("/api/die-change-events/<eid>")
def change_event_get(eid):
    require_role("PlantAdmin", "SetupLead", "ProductionPlanner")
    e = get_or_404(db.die_change_events, eid)
    return success_object(ser_change_event(e))


@app.post("/api/die-change-events/<eid>/start")
def change_event_start(eid):
    require_role("SetupLead")
    e = get_or_404(db.die_change_events, eid)
    if e["status"] != "PLANNED":
        raise invalid_state("Changeover must be PLANNED to start")
    press = db.presses[e["press_id"]]
    to_die = db.dies[e["to_die_id"]]
    if press["status"] not in ("IDLE", "RUNNING"):
        raise invalid_state("Press must be IDLE or RUNNING to start a changeover")
    for other in db.die_change_events.values():
        if other["press_id"] == press["id"] and other["status"] == "IN_PROGRESS" and other["id"] != e["id"]:
            raise invalid_state("Another changeover is already IN_PROGRESS on this press")
    # Quality gate: die over threshold
    if to_die["status"] != "AVAILABLE":
        raise invalid_state("to_die must be AVAILABLE")
    if to_die["shots_since_repair"] >= to_die["repair_threshold_shots"]:
        raise quality_hold("Die has reached its repair threshold")
    # Physical fit
    if press["tonnage"] < to_die["rated_tonnage"] or press["bed_width_mm"] < to_die["min_bed_width_mm"]:
        raise capacity()
    # Side effects
    press["status"] = "IN_SETUP"
    touch(press)
    to_die["status"] = "ASSIGNED"
    touch(to_die)
    e["actual_start"] = iso_now()
    e["_actual_start_dt"] = now()
    e["status"] = "IN_PROGRESS"
    touch(e)
    return success_object(ser_change_event(e))


@app.post("/api/die-change-events/<eid>/complete")
def change_event_complete(eid):
    require_role("SetupLead")
    e = get_or_404(db.die_change_events, eid)
    if e["status"] != "IN_PROGRESS":
        raise invalid_state("Changeover must be IN_PROGRESS to complete")
    press = db.presses[e["press_id"]]
    end_dt = now()
    e["actual_end"] = iso_now()
    e["_actual_end_dt"] = end_dt
    start_dt = e.get("_actual_start_dt") or parse_dt(e["actual_start"])
    elapsed_seconds = (end_dt - start_dt).total_seconds()
    actual_minutes = int(elapsed_seconds // 60)
    e["variance_minutes"] = actual_minutes - e["smed_target_minutes"]
    press["status"] = "IDLE"
    touch(press)
    if e["from_die_id"]:
        from_die = db.dies.get(e["from_die_id"])
        if from_die is not None and from_die["status"] == "ASSIGNED":
            from_die["status"] = "AVAILABLE"
            touch(from_die)
    e["status"] = "COMPLETED"
    touch(e)
    return success_object(ser_change_event(e))


@app.post("/api/die-change-events/<eid>/cancel")
def change_event_cancel(eid):
    require_role("SetupLead")
    e = get_or_404(db.die_change_events, eid)
    if e["status"] != "PLANNED":
        raise invalid_state("Changeover must be PLANNED to cancel")
    e["status"] = "CANCELLED"
    touch(e)
    return success_object(ser_change_event(e))


# ---------------------------------------------------------------------------
# Production runs
# ---------------------------------------------------------------------------

def _estimated_consumption(order, part):
    """Estimated steel consumption: planned good-part quantity * steel_content_kg."""
    remaining = order["quantity_ordered"] - order["quantity_produced_good"]
    if remaining < 0:
        remaining = 0
    planned = remaining if remaining > 0 else order["quantity_ordered"]
    return round3(Decimal(planned) * Decimal(str(part["steel_content_kg"])))


@app.post("/api/production-runs")
def run_create():
    require_role("ProductionPlanner")
    body = get_body()
    require_fields(body, ["production_order_id", "press_id", "die_id", "coil_id",
                          "scheduled_start", "scheduled_end"])
    order = get_or_404(db.production_orders, as_str(body.get("production_order_id"), "production_order_id"))
    press = get_or_404(db.presses, as_str(body.get("press_id"), "press_id"))
    die = get_or_404(db.dies, as_str(body.get("die_id"), "die_id"))
    coil = get_or_404(db.steel_coils, as_str(body.get("coil_id"), "coil_id"))
    ss = parse_dt(body.get("scheduled_start"), "scheduled_start")
    se = parse_dt(body.get("scheduled_end"), "scheduled_end")
    if se <= ss:
        raise invalid_request("scheduled_end must be after scheduled_start")
    part = db.parts.get(order["part_id"])
    # Physical fit (check 7)
    if press["tonnage"] < die["rated_tonnage"] or press["bed_width_mm"] < die["min_bed_width_mm"]:
        raise capacity()
    # Material compatibility (check 8)
    if coil["material_spec"] != part["material_spec"] or coil["thickness_mm"] != part["thickness_mm"]:
        raise material_mismatch()
    # Coil weight sufficiency (check 13)
    est = _estimated_consumption(order, part)
    if coil["remaining_weight_kg"] < est:
        raise coil_weight()
    # Run-window overlap (check 9) — half-open
    for r in db.production_runs.values():
        if r["press_id"] != press["id"] or r["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if _overlap(ss, se, r["_scheduled_start_dt"], r["_scheduled_end_dt"]):
            raise schedule_conflict()
    rec = common_fields()
    rec.update({
        "production_order_id": order["id"],
        "press_id": press["id"],
        "die_id": die["id"],
        "coil_id": coil["id"],
        "scheduled_start": format_ts(ss),
        "scheduled_end": format_ts(se),
        "status": "SCHEDULED",
        "shots_recorded": 0,
        "good_count": 0,
        "reject_count": 0,
        "steel_consumed_kg": None,
        "standard_scrap_rate": None,
        "actual_scrap_rate": None,
        "scrap_variance": None,
        "_scheduled_start_dt": ss,
        "_scheduled_end_dt": se,
    })
    db.production_runs[rec["id"]] = rec
    return success_object(ser_run(rec), 201)


@app.get("/api/production-runs")
def run_list():
    require_role("PlantAdmin", "ProductionPlanner", "PressOperator", "QualityEngineer")
    limit, offset = get_pagination()
    items = list(db.production_runs.values())
    from flask import request as _req
    for key in ("production_order_id", "press_id", "die_id", "coil_id", "status"):
        if key in _req.args:
            v = _req.args.get(key)
            items = [r for r in items if r[key] == v]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_run(r) for r in page], limit, offset, total)


@app.get("/api/production-runs/<rid>")
def run_get(rid):
    require_role("PlantAdmin", "ProductionPlanner", "PressOperator", "QualityEngineer")
    r = get_or_404(db.production_runs, rid)
    return success_object(ser_run(r))


@app.post("/api/production-runs/<rid>/start")
def run_start(rid):
    require_role("PressOperator")
    r = get_or_404(db.production_runs, rid)
    if r["status"] != "SCHEDULED":
        raise invalid_state("Run must be SCHEDULED to start")
    order = db.production_orders[r["production_order_id"]]
    press = db.presses[r["press_id"]]
    die = db.dies[r["die_id"]]
    coil = db.steel_coils[r["coil_id"]]
    part = db.parts[order["part_id"]]
    if order["status"] not in ("RELEASED", "IN_PROGRESS"):
        raise invalid_state("Order must be RELEASED or IN_PROGRESS to start a run")
    if press["status"] != "IDLE":
        raise invalid_state("Press must be IDLE to start a run")
    if die["status"] != "ASSIGNED":
        raise invalid_state("Die must be ASSIGNED (installed) to start a run")
    # Quality gates (check 5)
    if coil["status"] in ("QUARANTINED", "ON_HOLD", "REJECTED"):
        raise quality_hold("Coil is not approved for production")
    if coil["status"] != "APPROVED":
        raise invalid_state("Coil must be APPROVED to start a run")
    if die["shots_since_repair"] >= die["repair_threshold_shots"]:
        raise quality_hold("Die has reached its repair threshold")
    # Material compatibility (check 8, re-verified)
    if coil["material_spec"] != part["material_spec"] or coil["thickness_mm"] != part["thickness_mm"]:
        raise material_mismatch()
    # Coil sufficiency (check 13, re-verified)
    est = _estimated_consumption(order, part)
    if coil["remaining_weight_kg"] < est:
        raise coil_weight()
    # Side effects
    press["status"] = "RUNNING"
    touch(press)
    if order["status"] == "RELEASED":
        order["status"] = "IN_PROGRESS"
        touch(order)
    r["status"] = "RUNNING"
    # Capture standard scrap rate from the layout APPROVED at run start
    approved_layout = None
    for l in db.strip_layouts.values():
        if l["part_id"] == part["id"] and l["status"] == "APPROVED":
            approved_layout = l
            break
    if approved_layout is not None:
        gross = Decimal(str(approved_layout["gross_weight_per_part_kg"]))
        net = Decimal(str(part["net_weight_kg"]))
        if gross > 0:
            std = (gross - net) / gross
            r["standard_scrap_rate"] = round6(std)
    touch(r)
    return success_object(ser_run(r))


@app.post("/api/production-runs/<rid>/complete")
def run_complete(rid):
    require_role("PressOperator")
    r = get_or_404(db.production_runs, rid)
    if r["status"] != "RUNNING":
        raise invalid_state("Run must be RUNNING to complete")
    body = get_body()
    require_fields(body, ["shots_recorded", "expected_coil_version"])
    shots = body.get("shots_recorded")
    if isinstance(shots, bool) or not isinstance(shots, int):
        raise invalid_request("shots_recorded must be an integer")
    if shots < 0:
        raise invalid_request("shots_recorded must be >= 0")
    expected_coil_v = body.get("expected_coil_version")
    if isinstance(expected_coil_v, bool) or not isinstance(expected_coil_v, int):
        raise invalid_request("expected_coil_version must be an integer")
    if shots == 0:
        raise no_shots()
    order = db.production_orders[r["production_order_id"]]
    press = db.presses[r["press_id"]]
    die = db.dies[r["die_id"]]
    coil = db.steel_coils[r["coil_id"]]
    part = db.parts[order["part_id"]]
    reject_total = sum(e["quantity"] for e in db.reject_events.values() if e["production_run_id"] == r["id"])
    if reject_total > shots:
        raise rejects_exceed()
    # OCC check on coil
    if coil["version"] != expected_coil_v:
        raise stale_version("expected_coil_version does not match current coil version")
    good = shots - reject_total
    steel = round3(Decimal(good) * Decimal(str(part["steel_content_kg"])))
    new_remaining = round3(coil["remaining_weight_kg"] - steel)
    if new_remaining < 0:
        raise coil_weight()
    # ---- Commit all side effects ----
    r["shots_recorded"] = shots
    r["reject_count"] = reject_total
    r["good_count"] = good
    r["steel_consumed_kg"] = steel
    # scrap rates
    gross = Decimal(str(part["steel_content_kg"]))
    if gross > 0:
        net = Decimal(str(part["net_weight_kg"]))
        std = (gross - net) / gross
        r["standard_scrap_rate"] = round6(std)
    actual = Decimal(reject_total) / Decimal(shots)
    r["actual_scrap_rate"] = round6(actual)
    if r["standard_scrap_rate"] is not None:
        r["scrap_variance"] = round6(Decimal(str(r["actual_scrap_rate"])) - Decimal(str(r["standard_scrap_rate"])))
    coil["remaining_weight_kg"] = new_remaining
    touch(coil)
    if new_remaining == 0 and coil["status"] == "APPROVED":
        coil["status"] = "DEPLETED"
        coil["updated_at"] = iso_now()
    press["status"] = "IDLE"
    touch(press)
    order["quantity_produced_good"] += good
    order["quantity_scrapped"] += reject_total
    touch(order)
    die["total_shots_lifetime"] += shots
    die["shots_since_repair"] += shots
    touch(die)
    r["status"] = "COMPLETED"
    touch(r)
    return success_object(ser_run(r))


def _abort_run(r, was_running):
    if was_running:
        press = db.presses.get(r["press_id"])
        if press is not None and press["status"] == "RUNNING":
            press["status"] = "IDLE"
            touch(press)
    r["status"] = "ABORTED"
    touch(r)
    _maybe_revert_order(r["production_order_id"])


@app.post("/api/production-runs/<rid>/abort")
def run_abort(rid):
    require_role("PressOperator")
    r = get_or_404(db.production_runs, rid)
    if r["status"] not in ("SCHEDULED", "RUNNING"):
        raise invalid_state("Run must be SCHEDULED or RUNNING to abort")
    was_running = r["status"] == "RUNNING"
    _abort_run(r, was_running)
    return success_object(ser_run(r))


@app.get("/api/production-runs/<rid>/reject-events")
def run_reject_list(rid):
    require_role("PlantAdmin", "PressOperator", "QualityEngineer")
    get_or_404(db.production_runs, rid)
    limit, offset = get_pagination()
    items = [e for e in db.reject_events.values() if e["production_run_id"] == rid]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_reject_event(e) for e in page], limit, offset, total)


@app.post("/api/production-runs/<rid>/reject-events")
def run_reject_create(rid):
    require_role("PressOperator")
    r = get_or_404(db.production_runs, rid)
    if r["status"] != "RUNNING":
        raise invalid_state("Reject events can only be recorded on a RUNNING run")
    body = get_body()
    require_fields(body, ["station_number", "sensor_code", "quantity", "sensed_at"])
    station = as_int(body.get("station_number"), "station_number", minimum=1)
    sensor = as_enum(body.get("sensor_code"), "sensor_code",
                     {"MISFEED", "SHORT_FEED", "PART_EJECT_FAIL", "DOUBLE_BLANK", "SLUG_DETECT"})
    qty = as_int(body.get("quantity"), "quantity", minimum=1)
    sensed_dt = parse_dt(body.get("sensed_at"), "sensed_at")
    rec = ledger_fields()
    rec.update({
        "production_run_id": r["id"],
        "station_number": station,
        "sensor_code": sensor,
        "quantity": qty,
        "sensed_at": format_ts(sensed_dt),
    })
    db.reject_events[rec["id"]] = rec
    r["reject_count"] = sum(e["quantity"] for e in db.reject_events.values() if e["production_run_id"] == r["id"])
    touch(r)
    return success_object(ser_reject_event(rec), 201)


# ---------------------------------------------------------------------------
# Outside processing orders
# ---------------------------------------------------------------------------

@app.post("/api/outside-processing-orders")
def outside_create():
    require_role("ShippingClerk")
    body = get_body()
    require_fields(body, ["production_order_id", "operation_type", "quantity_sent"])
    order = get_or_404(db.production_orders, as_str(body.get("production_order_id"), "production_order_id"))
    op_type = as_enum(body.get("operation_type"), "operation_type", {"PLATING", "HEAT_TREAT", "E_COAT", "DEBURR"})
    qty = as_int(body.get("quantity_sent"), "quantity_sent", minimum=1)
    rec = common_fields()
    rec.update({
        "production_order_id": order["id"],
        "operation_type": op_type,
        "quantity_sent": qty,
        "quantity_returned_good": 0,
        "quantity_returned_scrap": 0,
        "status": "SENT",
    })
    db.outside_processing_orders[rec["id"]] = rec
    return success_object(ser_outside(rec), 201)


@app.get("/api/outside-processing-orders/<oid>")
def outside_get(oid):
    require_role("PlantAdmin", "ShippingClerk", "ProductionPlanner")
    o = get_or_404(db.outside_processing_orders, oid)
    return success_object(ser_outside(o))


@app.post("/api/outside-processing-orders/<oid>/receive-return")
def outside_receive(oid):
    require_role("ShippingClerk")
    o = get_or_404(db.outside_processing_orders, oid)
    if o["status"] not in ("SENT", "PARTIAL_RETURN"):
        raise invalid_state("Outside processing order must be SENT or PARTIAL_RETURN to receive a return")
    body = get_body()
    require_fields(body, ["quantity_returned_good", "quantity_returned_scrap"])
    good = as_int(body.get("quantity_returned_good"), "quantity_returned_good", minimum=0)
    scrap = as_int(body.get("quantity_returned_scrap"), "quantity_returned_scrap", minimum=0)
    new_good = o["quantity_returned_good"] + good
    new_scrap = o["quantity_returned_scrap"] + scrap
    if new_good + new_scrap > o["quantity_sent"]:
        raise return_exceeded()
    o["quantity_returned_good"] = new_good
    o["quantity_returned_scrap"] = new_scrap
    if new_good + new_scrap == o["quantity_sent"]:
        o["status"] = "CLOSED"
    else:
        o["status"] = "PARTIAL_RETURN"
    touch(o)
    return success_object(ser_outside(o))


@app.post("/api/outside-processing-orders/<oid>/close-short")
def outside_close_short(oid):
    require_role("ShippingClerk")
    o = get_or_404(db.outside_processing_orders, oid)
    if o["status"] not in ("SENT", "PARTIAL_RETURN"):
        raise invalid_state("Outside processing order must be SENT or PARTIAL_RETURN to close short")
    body = get_body()
    require_fields(body, ["shortage_acknowledgment"])
    ack = body.get("shortage_acknowledgment")
    if not isinstance(ack, str) or ack == "":
        raise invalid_request("shortage_acknowledgment must be a non-empty string")
    parent = db.production_orders.get(o["production_order_id"])
    if parent is None or parent["status"] != "COMPLETED":
        raise order_not_completed()
    shortage = o["quantity_sent"] - o["quantity_returned_good"] - o["quantity_returned_scrap"]
    o["status"] = "CLOSED"
    touch(o)
    parent["quantity_scrapped"] += shortage
    touch(parent)
    return success_object(ser_outside(o))


# ---------------------------------------------------------------------------
# PPAP submissions
# ---------------------------------------------------------------------------

@app.post("/api/ppap-submissions")
def ppap_create():
    user_id, _ = require_role("ProcessEngineer")
    body = get_body()
    require_fields(body, ["part_id", "level", "control_plan_attached"])
    part = get_or_404(db.parts, as_str(body.get("part_id"), "part_id"))
    level = as_int(body.get("level"), "level")
    cp = body.get("control_plan_attached")
    if not isinstance(cp, bool):
        raise invalid_request("control_plan_attached must be a boolean")
    # PPAP level match (check 11)
    if level != part["ppap_required_level"]:
        raise ppap_level_mismatch("Submission level must equal the part's ppap_required_level")
    if level >= 2 and not cp:
        raise ppap_level_mismatch("A control plan must be attached for level >= 2")
    # Resubmission rule: only if no prior submissions, or the previous one is REJECTED
    prior = [s for s in db.ppap_submissions.values() if s["part_id"] == part["id"]]
    if prior:
        max_rev = max(s["submission_revision"] for s in prior)
        latest = [s for s in prior if s["submission_revision"] == max_rev][0]
        if latest["status"] != "REJECTED":
            raise invalid_state("A new submission is accepted only while the previous submission is REJECTED")
        revision = max_rev + 1
    else:
        revision = 1
    rec = common_fields()
    rec.update({
        "part_id": part["id"],
        "level": level,
        "submission_revision": revision,
        "control_plan_attached": cp,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "_created_by": user_id,
    })
    db.ppap_submissions[rec["id"]] = rec
    return success_object(ser_ppap(rec), 201)


@app.get("/api/ppap-submissions/<sid>")
def ppap_get(sid):
    require_role("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    s = get_or_404(db.ppap_submissions, sid)
    return success_object(ser_ppap(s))


@app.post("/api/ppap-submissions/<sid>/begin-review")
def ppap_begin_review(sid):
    require_role("QualityEngineer")
    s = get_or_404(db.ppap_submissions, sid)
    if s["status"] != "SUBMITTED":
        raise invalid_state("Submission must be SUBMITTED to begin review")
    s["status"] = "UNDER_REVIEW"
    touch(s)
    return success_object(ser_ppap(s))


@app.post("/api/ppap-submissions/<sid>/approve")
def ppap_approve(sid):
    user_id, _ = require_role("QualityEngineer")
    s = get_or_404(db.ppap_submissions, sid)
    if s["status"] != "UNDER_REVIEW":
        raise invalid_state("Submission must be UNDER_REVIEW to approve")
    if s.get("_created_by") == user_id:
        raise segregation()
    s["status"] = "APPROVED"
    touch(s)
    # Qualify all part-die assignments for the part
    for a in db.part_die_assignments.values():
        if a["part_id"] == s["part_id"]:
            if not a["qualified"]:
                a["qualified"] = True
                touch(a)
    return success_object(ser_ppap(s))


@app.post("/api/ppap-submissions/<sid>/reject")
def ppap_reject(sid):
    user_id, _ = require_role("QualityEngineer")
    s = get_or_404(db.ppap_submissions, sid)
    if s["status"] != "UNDER_REVIEW":
        raise invalid_state("Submission must be UNDER_REVIEW to reject")
    if s.get("_created_by") == user_id:
        raise segregation()
    body = get_body()
    reason = body.get("rejection_reason")
    if not isinstance(reason, str) or reason == "":
        raise invalid_request("rejection_reason is required")
    s["status"] = "REJECTED"
    s["rejection_reason"] = reason
    touch(s)
    return success_object(ser_ppap(s))


# ---------------------------------------------------------------------------
# Layered audits
# ---------------------------------------------------------------------------

@app.post("/api/layered-audits")
def audit_create():
    user_id, _ = require_role("QualityEngineer")
    body = get_body()
    require_fields(body, ["press_id", "audit_tier", "scheduled_date"])
    press = get_or_404(db.presses, as_str(body.get("press_id"), "press_id"))
    tier = as_int(body.get("audit_tier"), "audit_tier")
    if tier not in (1, 2, 3):
        raise invalid_request("audit_tier must be 1, 2, or 3")
    sched_dt = parse_dt(body.get("scheduled_date"), "scheduled_date")
    rec = common_fields()
    rec.update({
        "press_id": press["id"],
        "audit_tier": tier,
        "scheduled_date": format_ts(sched_dt),
        "executed_at": None,
        "result": "PENDING",
        "findings_count": 0,
        "escalated_from_id": None,
        "_created_by": user_id,
    })
    db.layered_audits[rec["id"]] = rec
    return success_object(ser_audit(rec), 201)


@app.get("/api/layered-audits")
def audit_list():
    require_role("PlantAdmin", "QualityEngineer")
    limit, offset = get_pagination()
    items = list(db.layered_audits.values())
    from flask import request as _req
    for key in ("press_id", "escalated_from_id", "result"):
        if key in _req.args:
            v = _req.args.get(key)
            items = [a for a in items if a[key] == v]
    if "audit_tier" in _req.args:
        try:
            vt = int(_req.args.get("audit_tier"))
        except (ValueError, TypeError):
            raise invalid_request("audit_tier must be an integer")
        items = [a for a in items if a["audit_tier"] == vt]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_audit(a) for a in page], limit, offset, total)


@app.get("/api/layered-audits/<aid>")
def audit_get(aid):
    require_role("PlantAdmin", "QualityEngineer")
    a = get_or_404(db.layered_audits, aid)
    return success_object(ser_audit(a))


def _quarantine_cascade(heat_lots):
    """Quarantine every APPROVED coil sharing an implicated heat lot; abort runs; revert orders."""
    quarantined_coil_ids = set()
    for c in db.steel_coils.values():
        if c["heat_lot_number"] in heat_lots and c["status"] == "APPROVED":
            c["status"] = "QUARANTINED"
            touch(c)
            quarantined_coil_ids.add(c["id"])
    # Also include coils already QUARANTINED (they still abort their runs)
    for c in db.steel_coils.values():
        if c["heat_lot_number"] in heat_lots and c["status"] == "QUARANTINED":
            quarantined_coil_ids.add(c["id"])
    for r in db.production_runs.values():
        if r["coil_id"] in quarantined_coil_ids and r["status"] in ("SCHEDULED", "RUNNING"):
            was_running = r["status"] == "RUNNING"
            _abort_run(r, was_running)


@app.post("/api/layered-audits/<aid>/record")
def audit_record(aid):
    user_id, _ = require_role("QualityEngineer")
    a = get_or_404(db.layered_audits, aid)
    if a["result"] != "PENDING":
        raise invalid_state("Audit must be PENDING to record a result")
    if a.get("_created_by") == user_id:
        raise segregation()
    body = get_body()
    require_fields(body, ["result", "findings_count"])
    result = as_enum(body.get("result"), "result", {"PASS", "FAIL"})
    findings = as_int(body.get("findings_count"), "findings_count", minimum=0)
    if result == "FAIL" and findings < 1:
        raise audit_findings()
    a["result"] = result
    a["findings_count"] = findings
    a["executed_at"] = iso_now()
    touch(a)
    if result == "FAIL":
        if a["audit_tier"] < 3:
            # Escalate: create a new audit at tier+1
            rec = common_fields()
            rec.update({
                "press_id": a["press_id"],
                "audit_tier": a["audit_tier"] + 1,
                "scheduled_date": iso_now(),
                "executed_at": None,
                "result": "PENDING",
                "findings_count": 0,
                "escalated_from_id": a["id"],
                "_created_by": None,  # system-created; no segregation conflict
            })
            db.layered_audits[rec["id"]] = rec
        else:
            # Tier-3 FAIL: heat-lot quarantine cascade
            press_id = a["press_id"]
            heat_lots = set()
            for r in db.production_runs.values():
                if r["press_id"] != press_id:
                    continue
                if r["status"] not in ("COMPLETED", "RUNNING"):
                    continue
                coil = db.steel_coils.get(r["coil_id"])
                if coil:
                    heat_lots.add(coil["heat_lot_number"])
            if heat_lots:
                _quarantine_cascade(heat_lots)
    return success_object(ser_audit(a))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
