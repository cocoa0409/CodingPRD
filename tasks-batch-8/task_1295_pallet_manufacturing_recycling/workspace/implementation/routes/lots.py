"""InventoryLot and HeatTreatmentRun endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, now, iso, next_ht_mark_seq
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, as_str, as_int, as_enum,
)
from response import success
from services.calc import new_build_unit_cost_cents, HT_MIN_DURATION_HOURS
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404, ref_or_404,
)

bp = Blueprint("lots", __name__)

ORIGIN_TYPES = ("NEW_BUILD", "RECYCLED_REPAIR")
QUALITY_GRADES = ("NEW", "A", "B")
SPECIES = ("PINE", "OAK", "MIXED")


@bp.post("/pallet-ops/inventory-lots")
def create_lot():
    require_roles("PlantManager")
    body = get_json_body()
    spec_id = as_str(req_field(body, "spec_id"), "spec_id")
    spec = ref_or_404(db.specs, spec_id, "spec_id")
    origin_type = as_enum(req_field(body, "origin_type"), "origin_type", ORIGIN_TYPES)
    quantity_total = as_int(req_field(body, "quantity_total"), "quantity_total", minimum=1)
    quality_grade = body.get("quality_grade")
    if quality_grade is not None:
        quality_grade = as_enum(quality_grade, "quality_grade", QUALITY_GRADES)

    created_at = now()
    if origin_type == "NEW_BUILD":
        grade = quality_grade if quality_grade is not None else "NEW"
        # Raises ERR_PRICE_INDEX_MISSING when no lumber index covers created_at.
        unit_cost = new_build_unit_cost_cents(spec, quantity_total, created_at)
    else:
        # Directly-created recycled lots: no batch/work-order context, so no
        # lumber index and no overhead tier; cost comes from supplied parts
        # only (zero when absent). Recycled lots normally arise from repair.
        grade = quality_grade if quality_grade is not None else "A"
        unit_cost = 0

    lot = {
        "spec_id": spec_id,
        "origin_type": origin_type,
        "quantity_total": quantity_total,
        "quantity_available": quantity_total,
        "quality_grade": grade,
        "heat_treat_status": (
            "PENDING_HT" if spec["requires_heat_treatment_default"] else "NOT_REQUIRED"
        ),
        "ispm15_mark_id": None,
        "unit_cost_cents": unit_cost,
        "status": "AVAILABLE",
    }
    init_common(lot)
    db.inventory_lots[lot["id"]] = lot
    return success(serialize(lot), status=201)


@bp.get("/pallet-ops/inventory-lots")
def list_lots():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.inventory_lots.values())
    spec_id = request.args.get("spec_id")
    if spec_id is not None:
        items = [l for l in items if l["spec_id"] == spec_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    grade = request.args.get("quality_grade")
    if grade is not None:
        items = [l for l in items if l["quality_grade"] == grade]
    hts = request.args.get("heat_treat_status")
    if hts is not None:
        items = [l for l in items if l["heat_treat_status"] == hts]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/inventory-lots/<lid>")
def get_lot(lid):
    require_roles()
    lot = get_or_404(db.inventory_lots, lid, "InventoryLot")
    return success(serialize(lot))


@bp.post("/pallet-ops/inventory-lots/<lid>/quarantine")
def quarantine_lot(lid):
    require_roles("PlantManager")
    lot = get_or_404(db.inventory_lots, lid, "InventoryLot")
    if lot["status"] != "AVAILABLE":
        raise_err("ERR_LOT_NOT_AVAILABLE", "quarantine requires lot AVAILABLE")
    if any(
        line.get("allocated_lot_id") == lid and line["status"] == "ALLOCATED"
        for line in db.order_lines.values()
    ):
        raise_err("ERR_LOT_HAS_ALLOCATIONS", "quarantine blocked by ALLOCATED order lines")
    lot["status"] = "QUARANTINED"
    touch(lot)
    return success(serialize(lot))


# --- HeatTreatmentRun ---------------------------------------------------------

@bp.post("/pallet-ops/ht-runs")
def create_ht_run():
    require_roles("HeatTreatOperator")
    body = get_json_body()
    chamber_code = as_str(req_field(body, "chamber_code"), "chamber_code")
    species_profile = as_enum(req_field(body, "species_profile"), "species_profile", SPECIES)
    capacity = as_int(req_field(body, "capacity_pallets"), "capacity_pallets", minimum=1)

    run = {
        "chamber_code": chamber_code,
        "species_profile": species_profile,
        "capacity_pallets": capacity,
        "loaded_pallets": 0,
        "started_at": None,
        "completed_at": None,
        "ispm15_mark_id": None,
        "status": "STAGING",
        "_assigned_lot_ids": [],
        "_started_at_dt": None,
    }
    init_common(run)
    db.ht_runs[run["id"]] = run
    return success(serialize(run), status=201)


@bp.get("/pallet-ops/ht-runs")
def list_ht_runs():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.ht_runs.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    chamber = request.args.get("chamber_code")
    if chamber is not None:
        items = [r for r in items if r["chamber_code"] == chamber]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/ht-runs/<rid>")
def get_ht_run(rid):
    require_roles()
    run = get_or_404(db.ht_runs, rid, "HeatTreatmentRun")
    return success(serialize(run))


@bp.post("/pallet-ops/ht-runs/<rid>/assign-lot")
def assign_lot(rid):
    require_roles("HeatTreatOperator")
    run = get_or_404(db.ht_runs, rid, "HeatTreatmentRun")
    body = get_json_body()
    lot_id = as_str(req_field(body, "lot_id"), "lot_id")
    lot = ref_or_404(db.inventory_lots, lot_id, "lot_id")

    if run["status"] != "STAGING":
        raise_err("ERR_HT_NOT_STAGING", "assign-lot requires run STAGING")
    if lot["heat_treat_status"] != "PENDING_HT":
        raise_err(
            "ERR_INVALID_STATE",
            "assign-lot requires lot heat_treat_status == PENDING_HT",
        )
    if lot["status"] != "AVAILABLE":
        raise_err("ERR_INVALID_STATE", "assign-lot requires lot AVAILABLE")
    # A lot already bound to a live (STAGING/RUNNING) run cannot join another.
    for other in db.ht_runs.values():
        if (
            other["status"] in ("STAGING", "RUNNING")
            and lot_id in other["_assigned_lot_ids"]
        ):
            raise_err(
                "ERR_INVALID_STATE",
                "Lot is already assigned to run %s" % other["id"],
            )
    spec = db.specs.get(lot["spec_id"])
    lot_species = spec["lumber_species"] if spec is not None else None
    if lot_species != run["species_profile"]:
        raise_err(
            "ERR_HT_SPECIES_MISMATCH",
            "Lot's spec species differs from run species_profile",
        )
    if run["loaded_pallets"] + lot["quantity_total"] > run["capacity_pallets"]:
        raise_err(
            "ERR_HT_CAPACITY_EXCEEDED",
            "assign-lot would push loaded_pallets beyond capacity_pallets",
        )

    run["loaded_pallets"] += lot["quantity_total"]
    run["_assigned_lot_ids"].append(lot_id)
    touch(run)
    return success(serialize(run))


@bp.post("/pallet-ops/ht-runs/<rid>/start")
def start_ht_run(rid):
    require_roles("HeatTreatOperator")
    run = get_or_404(db.ht_runs, rid, "HeatTreatmentRun")
    if run["status"] != "STAGING":
        raise_err("ERR_HT_NOT_STAGING", "start requires run STAGING")
    if run["loaded_pallets"] < 1:
        raise_err("ERR_HT_EMPTY", "start requires at least one assigned pallet")
    for other in db.ht_runs.values():
        if (
            other["id"] != rid
            and other["chamber_code"] == run["chamber_code"]
            and other["status"] == "RUNNING"
        ):
            raise_err(
                "ERR_CHAMBER_OCCUPIED",
                "Another RUNNING run occupies the same chamber_code",
            )
    run["started_at"] = iso(now())
    run["_started_at_dt"] = now()
    run["status"] = "RUNNING"
    touch(run)
    return success(serialize(run))


@bp.post("/pallet-ops/ht-runs/<rid>/complete")
def complete_ht_run(rid):
    require_roles("HeatTreatOperator")
    run = get_or_404(db.ht_runs, rid, "HeatTreatmentRun")
    if run["status"] != "RUNNING":
        raise_err("ERR_HT_NOT_RUNNING", "complete requires run RUNNING")
    started = run["_started_at_dt"]
    if now() - started < timedelta(hours=HT_MIN_DURATION_HOURS):
        raise_err("ERR_HT_DWELL_SHORT", "complete before 6h dwell from started_at")

    completed_at = now()
    run["completed_at"] = iso(completed_at)
    mark = "HT-%s-%s-%d" % (
        run["chamber_code"],
        completed_at.strftime("%Y%m%d"),
        next_ht_mark_seq(),
    )
    run["ispm15_mark_id"] = mark
    run["status"] = "COMPLETED"
    touch(run)

    for lot_id in run["_assigned_lot_ids"]:
        lot = db.inventory_lots.get(lot_id)
        if lot is not None and lot["heat_treat_status"] == "PENDING_HT":
            lot["heat_treat_status"] = "HT_CERTIFIED"
            lot["ispm15_mark_id"] = mark
            touch(lot)
    run["_assigned_lot_ids"] = []
    return success(serialize(run))


@bp.post("/pallet-ops/ht-runs/<rid>/fail")
def fail_ht_run(rid):
    require_roles("HeatTreatOperator")
    run = get_or_404(db.ht_runs, rid, "HeatTreatmentRun")
    if run["status"] != "RUNNING":
        raise_err("ERR_HT_NOT_RUNNING", "fail requires run RUNNING")
    # Assigned lots remain PENDING_HT and are unassigned (free to rejoin).
    run["_assigned_lot_ids"] = []
    run["status"] = "FAILED"
    touch(run)
    return success(serialize(run))
