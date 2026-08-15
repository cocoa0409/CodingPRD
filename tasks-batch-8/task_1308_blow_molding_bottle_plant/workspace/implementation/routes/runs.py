from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_PRODUCTION_RUN_NOT_FOUND, \
    ERR_PRODUCTION_ORDER_NOT_FOUND, ERR_MACHINE_LINE_NOT_FOUND, \
    ERR_MOLD_NOT_FOUND, ERR_MATERIAL_LOT_NOT_FOUND, ERR_INVALID_STATE, \
    ERR_ALREADY_TERMINAL, ERR_ORDER_NOT_RELEASED, ERR_NO_ACTIVE_SLOT, \
    ERR_MOLD_NOT_INSTALLED, ERR_LINE_BUSY, ERR_MATERIAL_LOT_NOT_RELEASED, \
    ERR_QUALITY_HOLD_BLOCKOUT, ERR_RESIN_INCOMPATIBLE, \
    ERR_INSUFFICIENT_CAVITATION, ERR_SPEC_REVISION_STALE, \
    ERR_COUNT_EXCEEDS_PRODUCTION, ERR_INSUFFICIENT_MATERIAL, \
    ERR_INVALID_REQUEST
from calc import reconciliation, purge_kg_for, aql_for
from services import stamp_new, touch, ser_production_run, sorted_rows, \
    mold_effective_cavities, waterfall_debit, reverse_debits, \
    recompute_line_color, occupying_order_id
from util import new_id, logical_now
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("production_runs", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "ProductionScheduler"]
RUN_STATUSES = {"OPEN", "CLOSED", "VOIDED"}
HOLD_REASONS = ("QUALITY_HOLD", "CONTAMINATION_HOLD")


def get_run_or_404(run_id):
    run = store.production_runs.get(run_id)
    if run is None:
        raise_err(ERR_PRODUCTION_RUN_NOT_FOUND,
                  "ProductionRun id does not resolve")
    return run


@bp.post("/production-runs")
def create_run():
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {
        "production_order_id": ("str", True),
        "machine_line_id": ("str", True),
        "mold_id": ("str", True),
        "material_lot_id": ("str", True),
        "colorant_lot_id": ("str", False),
    })
    # body FK resolution, left to right
    order = store.production_orders.get(body["production_order_id"])
    if order is None:
        raise_err(ERR_PRODUCTION_ORDER_NOT_FOUND,
                  "ProductionOrder id does not resolve")
    line = store.machine_lines.get(body["machine_line_id"])
    if line is None:
        raise_err(ERR_MACHINE_LINE_NOT_FOUND,
                  "MachineLine id does not resolve")
    mold = store.molds.get(body["mold_id"])
    if mold is None:
        raise_err(ERR_MOLD_NOT_FOUND, "Mold id does not resolve")
    lot = store.material_lots.get(body["material_lot_id"])
    if lot is None:
        raise_err(ERR_MATERIAL_LOT_NOT_FOUND,
                  "MaterialLot id does not resolve")
    colorant_lot = None
    if "colorant_lot_id" in body:
        colorant_lot = store.material_lots.get(body["colorant_lot_id"])
        if colorant_lot is None:
            raise_err(ERR_MATERIAL_LOT_NOT_FOUND,
                      "MaterialLot id does not resolve")
    spec = store.bottle_specs.get(order["bottle_spec_id"])
    # colorant lot is required whenever the spec is not CLEAR
    if spec is not None and spec["color_contrast_class"] != "CLEAR" \
            and colorant_lot is None:
        raise_err(ERR_INVALID_REQUEST,
                  "colorant_lot_id is required for non-CLEAR specs")

    # --- state rules (priority 5, in declared order) ---
    if order["status"] not in ("RELEASED", "RUNNING"):
        raise_err(ERR_ORDER_NOT_RELEASED,
                  "Run start requires the order RELEASED or RUNNING")
    now = logical_now()
    active_slot = None
    for s in sorted_rows(store.schedule_slots.values()):
        if (s["production_order_id"] == order["id"]
                and s["machine_line_id"] == line["id"]
                and s["status"] in ("CONFIRMED", "IN_PROGRESS")
                and s["planned_start"] <= now < s["planned_end"]):
            active_slot = s
            break
    if active_slot is None:
        raise_err(ERR_NO_ACTIVE_SLOT,
                  "No CONFIRMED/IN_PROGRESS slot for (order, line) contains "
                  "the current clock")
    if mold["status"] != "INSTALLED" or mold["installed_line_id"] != line["id"]:
        raise_err(ERR_MOLD_NOT_INSTALLED,
                  "Mold is not INSTALLED on this line")
    if line["status"] == "RUNNING":
        occupant = occupying_order_id(line)
        if occupant is not None and occupant != order["id"]:
            raise_err(ERR_LINE_BUSY, "Line is RUNNING a different order")
    if lot["status"] not in ("RELEASED", "IN_USE"):
        raise_err(ERR_MATERIAL_LOT_NOT_RELEASED,
                  "Material lot is not RELEASED or IN_USE")
    if colorant_lot is not None and \
            colorant_lot["status"] not in ("RELEASED", "IN_USE"):
        raise_err(ERR_MATERIAL_LOT_NOT_RELEASED,
                  "Colorant lot is not RELEASED or IN_USE")

    # --- business safety (priority 6) ---
    for b in store.cavity_blockouts.values():
        if (b["mold_id"] == mold["id"] and b["status"] == "OPEN"
                and b["reason"] in HOLD_REASONS):
            raise_err(ERR_QUALITY_HOLD_BLOCKOUT,
                      "An open QUALITY_HOLD/CONTAMINATION_HOLD blockout gates "
                      "production")
    if spec["resin_type"] not in mold["compatible_resins"]:
        raise_err(ERR_RESIN_INCOMPATIBLE,
                  "spec.resin_type is not in mold.compatible_resins")

    # --- business constraints (priority 8) ---
    eff = mold_effective_cavities(mold)
    if eff < spec["min_cavitation_required"]:
        raise_err(ERR_INSUFFICIENT_CAVITATION,
                  "mold.effective_cavities below spec.min_cavitation_required")

    # --- referential (priority 9) ---
    if order["spec_revision_baseline"] != spec["content_revision"]:
        raise_err(ERR_SPEC_REVISION_STALE,
                  "Order baseline no longer matches spec.content_revision")

    # ---- apply: open the run and ripple the first-run transitions ----
    run = {
        "production_order_id": order["id"],
        "machine_line_id": line["id"],
        "mold_id": mold["id"],
        "material_lot_id": lot["id"],
        "colorant_lot_id": colorant_lot["id"] if colorant_lot else None,
        "cavities_active_at_start": eff,
        "started_at": now,
        "ended_at": None,
        "cycles_completed": None,
        "good_count": None,
        "scrap_count": None,
        "actual_drawdown_kg": None,
        "provisional_consumption_kg": None,
        "consumption_variance_pct": None,
        "variance_alert": None,
        "purge_kg": None,
        "status": "OPEN",
        "_debits": [],
        "_color_class_at_close": None,
    }
    stamp_new(run, new_id())
    store.production_runs[run["id"]] = run
    if order["status"] == "RELEASED":
        order["status"] = "RUNNING"
        touch(order)
    if active_slot["status"] == "CONFIRMED":
        active_slot["status"] = "IN_PROGRESS"
        touch(active_slot)
    if line["status"] == "CHANGEOVER":
        line["status"] = "RUNNING"
        touch(line)
    return success_object(ser_production_run(run), 201)


@bp.get("/production-runs")
def list_runs():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    production_order_id = query_filter("production_order_id")
    machine_line_id = query_filter("machine_line_id")
    mold_id = query_filter("mold_id")
    material_lot_id = query_filter("material_lot_id")
    colorant_lot_id = query_filter("colorant_lot_id")
    status = query_filter("status", RUN_STATUSES)
    limit, offset = pagination_params()
    rows = list(store.production_runs.values())
    if production_order_id is not None:
        rows = [r for r in rows if r["production_order_id"] == production_order_id]
    if machine_line_id is not None:
        rows = [r for r in rows if r["machine_line_id"] == machine_line_id]
    if mold_id is not None:
        rows = [r for r in rows if r["mold_id"] == mold_id]
    if material_lot_id is not None:
        rows = [r for r in rows if r["material_lot_id"] == material_lot_id]
    if colorant_lot_id is not None:
        rows = [r for r in rows if r["colorant_lot_id"] == colorant_lot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_production_run(r) for r in page], limit, offset,
                        len(rows))


@bp.get("/production-runs/<rid>")
def get_run(rid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_production_run(get_run_or_404(rid)))


@bp.post("/production-runs/<rid>/close")
def close_run(rid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {
        "cycles_completed": ("int", True),
        "good_count": ("int", True),
        "scrap_count": ("int", True),
        "actual_drawdown_kg": ("number", True),
    })
    run = get_run_or_404(rid)
    # PRD §3.6 declares only VOIDED terminal for runs (CLOSED → VOIDED exists),
    # so closing a CLOSED run is an undefined transition → ERR_INVALID_STATE,
    # while closing a VOIDED run is ERR_ALREADY_TERMINAL per §2.9.
    if run["status"] == "VOIDED":
        raise_err(ERR_ALREADY_TERMINAL, "Run is in a terminal state")
    if run["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN run can close")
    order = store.production_orders.get(run["production_order_id"])
    if order is None or order["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE,
                  "Only an OPEN run of a RUNNING order can close")
    spec = store.bottle_specs.get(order["bottle_spec_id"])
    line = store.machine_lines.get(run["machine_line_id"])

    # physical possibility (priority 8)
    if (body["good_count"] + body["scrap_count"]
            > body["cycles_completed"] * run["cavities_active_at_start"]):
        raise_err(ERR_COUNT_EXCEEDS_PRODUCTION,
                  "good_count + scrap_count exceeds cycles * cavities")

    # reconciliation + purge figures
    provisional, variance_pct, variance_alert = reconciliation(
        body["cycles_completed"], run["cavities_active_at_start"],
        order["planned_weight_g"], body["actual_drawdown_kg"])
    purge_kg = purge_kg_for(line["last_color_class"] if line else None,
                            spec["color_contrast_class"],
                            line["resident_volume_kg"] if line else 0)

    # material sufficiency (priority 10), all-or-nothing
    ledger, _total = waterfall_debit(spec, body["actual_drawdown_kg"], purge_kg)
    if ledger is None:
        raise_err(ERR_INSUFFICIENT_MATERIAL,
                  "Not enough RELEASED/IN_USE resin to cover drawdown + purge")

    run["cycles_completed"] = body["cycles_completed"]
    run["good_count"] = body["good_count"]
    run["scrap_count"] = body["scrap_count"]
    run["actual_drawdown_kg"] = body["actual_drawdown_kg"]
    run["provisional_consumption_kg"] = provisional
    run["consumption_variance_pct"] = variance_pct
    run["variance_alert"] = variance_alert
    run["purge_kg"] = purge_kg
    run["ended_at"] = logical_now()
    run["status"] = "CLOSED"
    run["_debits"] = ledger
    run["_color_class_at_close"] = spec["color_contrast_class"]
    touch(run)

    # line color memory
    if line is not None and line["last_color_class"] != spec["color_contrast_class"]:
        line["last_color_class"] = spec["color_contrast_class"]
        touch(line)

    # auto-create the quality test lot
    n, c_leak, c_drop = aql_for(body["good_count"])
    qlot = {
        "production_run_id": run["id"],
        "lot_size": body["good_count"],
        "sample_size_n": n,
        "accept_number_leak": c_leak,
        "accept_number_drop": c_drop,
        "leak_failures": None,
        "drop_failures": None,
        "retest_count": 0,
        "recorded_by_user_id": None,
        "dispositioned_by_user_id": None,
        "status": "PENDING",
    }
    stamp_new(qlot, new_id())
    store.quality_test_lots[qlot["id"]] = qlot
    return success_object(ser_production_run(run))


@bp.post("/production-runs/<rid>/void")
def void_run(rid):
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    check_fields(get_body(), {})
    run = get_run_or_404(rid)
    if run["status"] == "VOIDED":
        raise_err(ERR_ALREADY_TERMINAL, "Run is already VOIDED")
    if run["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, "Only a CLOSED run can be voided")
    qlot = None
    for l in store.quality_test_lots.values():
        if l["production_run_id"] == run["id"]:
            qlot = l
            break
    if qlot is not None and qlot["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE,
                  "The run's quality lot is no longer PENDING")
    reverse_debits(run)
    if qlot is not None:
        qlot["status"] = "VOIDED"
        touch(qlot)
    run["status"] = "VOIDED"
    touch(run)
    line = store.machine_lines.get(run["machine_line_id"])
    if line is not None:
        recompute_line_color(line)
    return success_object(ser_production_run(run))
