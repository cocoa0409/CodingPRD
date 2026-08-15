"""Production runs: scheduling (PRD §3.5), execution and completion (§3.6).

Validation sequencing follows PRD §2.7: auth -> role -> existence/shape ->
state (window PUBLISHED, lot reworkable, OCC) -> structural (schedule
conflict) -> temporal (build corridor, rework expiry) -> capacity (packaging,
rework qty).
"""
from datetime import timedelta

from flask import Blueprint, request

from db import new_id, now, parse_dt, stamp_new, store, touch
from errors import ApiError
from middleware import (ALL_ROLES, auth, body, is_int, is_num, paginate,
                        require_fields)
from response import success_list, success_object
from serializers import run_json
from services.fefo import plan_fefo
from services.pricing import (ceil_div, defect_rate_pct, expected_rework_output,
                              gift_set_price)
from services.projection import recompute_window, recompute_window_of_lot
from routes.packaging import sync_available

runs_bp = Blueprint("runs", __name__)

RUN_TYPES = ("STANDARD", "GIFT_ASSEMBLY", "REWORK")
PIPELINE_STATUSES = ("PLANNED", "IN_PROGRESS", "ON_HOLD")


def get_run_or_404(rid):
    r = store.production_runs.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Production run not found: %s" % rid)
    return r


def _lot_is_reworkable(lot):
    """ACTIVE, or BLOCKED with a hold sitting in REWORK_PENDING."""
    if lot["status"] == "ACTIVE":
        return True
    if lot["status"] == "BLOCKED":
        return any(h["lot_id"] == lot["id"] and h["status"] == "REWORK_PENDING"
                   for h in store.quality_holds.values())
    return False


@runs_bp.route("/production-runs", methods=["POST"])
def create_run():
    auth(("ProductionPlanner",))
    b = body()
    # --- Existence (ERR_NOT_FOUND): the four primary body FKs first.
    window = product = recipe = line = None
    for field, table in (("window_id", store.seasonal_windows),
                         ("product_id", store.products),
                         ("recipe_id", store.recipes),
                         ("line_id", store.production_lines)):
        v = b.get(field)
        if v is not None and v not in table:
            raise ApiError("ERR_NOT_FOUND", "%s references a non-existent resource." % field)
    window = store.seasonal_windows.get(b.get("window_id"))
    product = store.products.get(b.get("product_id"))
    recipe = store.recipes.get(b.get("recipe_id"))
    line = store.production_lines.get(b.get("line_id"))
    # --- Request shape (ERR_INVALID_REQUEST), enough to know the run type.
    require_fields(b, ["window_id", "product_id", "recipe_id", "line_id", "run_type",
                       "planned_units", "scheduled_start", "scheduled_end",
                       "expected_window_version"])
    if b["run_type"] not in RUN_TYPES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "run_type must be one of STANDARD, GIFT_ASSEMBLY, REWORK.")
    run_type = b["run_type"]
    # REWORK requires source_lot_id and rework_qty; the other types forbid them.
    source_lot = None
    if run_type == "REWORK":
        if b.get("source_lot_id") is None or b.get("rework_qty") is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "REWORK runs require source_lot_id and rework_qty.")
        source_lot = store.lots.get(b["source_lot_id"])
        if source_lot is None:
            raise ApiError("ERR_NOT_FOUND", "source_lot_id references a non-existent resource.")
    else:
        if b.get("source_lot_id") is not None or b.get("rework_qty") is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "source_lot_id and rework_qty are forbidden unless run_type is REWORK.")
    if not is_int(b["planned_units"]) or b["planned_units"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "planned_units must be an integer > 0.")
    if run_type == "REWORK" and (not is_int(b["rework_qty"]) or b["rework_qty"] <= 0):
        raise ApiError("ERR_INVALID_REQUEST", "rework_qty must be an integer > 0.")
    sched_start = parse_dt(b["scheduled_start"])
    sched_end = parse_dt(b["scheduled_end"])
    if sched_start is None or sched_end is None:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_start and scheduled_end must be ISO 8601 datetimes.")
    if not sched_start < sched_end:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_start must be strictly earlier than scheduled_end.")
    if not is_int(b["expected_window_version"]):
        raise ApiError("ERR_INVALID_REQUEST", "expected_window_version must be an integer.")
    # The recipe must belong to the product.
    if recipe["product_id"] != product["id"]:
        raise ApiError("ERR_INVALID_REQUEST", "The recipe does not belong to the product.")
    # GIFT_ASSEMBLY requires a GIFT_SET product.
    if run_type == "GIFT_ASSEMBLY" and product["product_type"] != "GIFT_SET":
        raise ApiError("ERR_INVALID_REQUEST", "GIFT_ASSEMBLY requires a GIFT_SET product.")
    # --- State gates: window must be PUBLISHED; REWORK source must be
    # reworkable; then the window OCC check.
    if window["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", "Runs may only be created against PUBLISHED windows.")
    if run_type == "REWORK" and not _lot_is_reworkable(source_lot):
        raise ApiError("ERR_LOT_NOT_REWORKABLE",
                       "The source lot must be ACTIVE, or BLOCKED with a hold in REWORK_PENDING.")
    if b["expected_window_version"] != window["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_window_version does not match the window's current version.")
    # --- Structural: the half-open [scheduled_start, scheduled_end) must not
    # intersect another pipeline run on the same line; touching at an endpoint
    # is allowed.
    for other in store.production_runs.values():
        if other["line_id"] != line["id"] or other["status"] not in PIPELINE_STATUSES:
            continue
        if sched_start < other["scheduled_end"] and other["scheduled_start"] < sched_end:
            raise ApiError("ERR_LINE_SCHEDULE_CONFLICT",
                           "The schedule intersects another run on the same line.")
    # --- Temporal: the schedule must sit inside the build corridor; the
    # REWORK source lot must not be expired.
    if sched_start < window["build_start"] or sched_end > window["build_end"]:
        raise ApiError("ERR_OUTSIDE_PRODUCTION_WINDOW",
                       "The schedule must satisfy build_start <= scheduled_start and scheduled_end <= build_end.")
    if run_type == "REWORK" and now() >= source_lot["expiry_date"]:
        raise ApiError("ERR_LOT_EXPIRED", "The REWORK source lot is expired.")
    # --- Capacity: packaging requirement must fit qty_available; rework_qty
    # must not exceed the source lot's on-hand units.
    component = store.packaging_components[product["packaging_component_id"]]
    required = ceil_div(b["planned_units"], component["units_per_component"])
    if required > component["qty_available"]:
        raise ApiError("ERR_PACKAGING_SHORTAGE",
                       "The packaging requirement exceeds the component's qty_available.")
    if run_type == "REWORK" and b["rework_qty"] > source_lot["qty_on_hand"]:
        raise ApiError("ERR_REWORK_QTY_EXCEEDS_LOT",
                       "rework_qty exceeds the source lot's qty_on_hand.")
    # === Side effects ===
    # Packaging reservation commits at scheduling time.
    component["qty_reserved"] += required
    sync_available(component)
    touch(component)
    run = {
        "id": new_id(),
        "window_id": window["id"],
        "product_id": product["id"],
        "recipe_id": recipe["id"],
        "line_id": line["id"],
        "run_type": run_type,
        "planned_units": b["planned_units"],
        "scheduled_start": sched_start,
        "scheduled_end": sched_end,
        "source_lot_id": b.get("source_lot_id") if run_type == "REWORK" else None,
        "rework_qty": b.get("rework_qty") if run_type == "REWORK" else None,
        "packaging_reserved_qty": required,
        "output_units": None,
        "expected_output_units": None,
        "created_lot_id": None,
        "status": "PLANNED",
    }
    stamp_new(run)
    store.production_runs[run["id"]] = run
    if run_type == "REWORK":
        # Earmark the source units out of free stock; the standard yield
        # variant projects expected_output_units.
        source_lot["qty_on_hand"] -= b["rework_qty"]
        source_lot["qty_reserved_rework"] += b["rework_qty"]
        touch(source_lot)
        run["expected_output_units"] = expected_rework_output(
            b["rework_qty"], recipe["standard_yield_pct"])
        # The source lot's qty_on_hand mutated: its own window recomputes.
        recompute_window_of_lot(source_lot)
    # The window's build projection recomputes — the pipeline term now
    # includes the new run — and its version increments.
    recompute_window(window)
    return success_object(run_json(run), 201)


@runs_bp.route("/production-runs", methods=["GET"])
def list_runs():
    auth(ALL_ROLES)
    items = list(store.production_runs.values())
    for f in ("window_id", "product_id", "recipe_id", "line_id", "source_lot_id",
              "created_lot_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items)
    return success_list([run_json(r) for r in page], meta)


@runs_bp.route("/production-runs/<rid>", methods=["GET"])
def get_run(rid):
    auth(ALL_ROLES)
    return success_object(run_json(get_run_or_404(rid)))


@runs_bp.route("/production-runs/<rid>/start", methods=["POST"])
def start_run(rid):
    auth(("LineOperator",))
    run = get_run_or_404(rid)
    # State gate, then line availability, then allergen clearance, then the
    # mold shape match.
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED run can be started.")
    line = store.production_lines[run["line_id"]]
    if line["status"] != "AVAILABLE":
        raise ApiError("ERR_LINE_NOT_AVAILABLE", "The line is not AVAILABLE.")
    recipe = store.recipes[run["recipe_id"]]
    if not set(recipe["allergens"]).issubset(set(line["cleared_allergens"])):
        raise ApiError("ERR_ALLERGEN_WASH_REQUIRED",
                       "The recipe declares allergens the line is not cleared for.")
    mold = store.molds.get(line["current_mold_id"]) if line["current_mold_id"] else None
    if mold is None or mold["shape_code"] != recipe["shape_code"]:
        raise ApiError("ERR_MOLD_SHAPE_MISMATCH",
                       "The line's installed mold does not carry the recipe's shape_code.")
    run["status"] = "IN_PROGRESS"
    touch(run)
    return success_object(run_json(run))


@runs_bp.route("/production-runs/<rid>/hold", methods=["POST"])
def hold_run(rid):
    auth(("LineOperator",))
    run = get_run_or_404(rid)
    if run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS run can be held.")
    run["status"] = "ON_HOLD"
    touch(run)
    return success_object(run_json(run))


@runs_bp.route("/production-runs/<rid>/resume", methods=["POST"])
def resume_run(rid):
    auth(("LineOperator",))
    run = get_run_or_404(rid)
    if run["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", "Only an ON_HOLD run can be resumed.")
    run["status"] = "IN_PROGRESS"
    touch(run)
    return success_object(run_json(run))


@runs_bp.route("/production-runs/<rid>/complete", methods=["POST"])
def complete_run(rid):
    auth(("LineOperator",))
    run = get_run_or_404(rid)
    b = body()
    require_fields(b, ["actual_cook_temp_c", "actual_temper_exit_c", "output_units"])
    if not is_num(b["actual_cook_temp_c"]) or not is_num(b["actual_temper_exit_c"]):
        raise ApiError("ERR_INVALID_REQUEST",
                       "actual_cook_temp_c and actual_temper_exit_c must be numbers.")
    if not is_int(b["output_units"]) or b["output_units"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", "output_units must be an integer >= 0.")
    if run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS run can be completed.")
    product = store.products[run["product_id"]]
    recipe = store.recipes[run["recipe_id"]]
    window = store.seasonal_windows[run["window_id"]]
    component = store.packaging_components[product["packaging_component_id"]]
    out = b["output_units"]

    # GIFT_ASSEMBLY precondition (capacity): the FEFO pool must cover every
    # component before anything is written — no partial deduction.
    fefo_plan = None
    if run["run_type"] == "GIFT_ASSEMBLY":
        fefo_plan = plan_fefo(run["product_id"], out)
        if fefo_plan is None:
            raise ApiError("ERR_INSUFFICIENT_COMPONENT_LOTS",
                           "The FEFO-eligible pool cannot cover every component of the gift set.")

    # 1. The run lands COMPLETED with the operator's counted output.
    run["output_units"] = out
    run["status"] = "COMPLETED"

    # 2. Packaging consumption: the reservation becomes physical consumption.
    component["qty_reserved"] -= run["packaging_reserved_qty"]
    component["qty_on_hand"] -= run["packaging_reserved_qty"]
    sync_available(component)
    touch(component)

    # 3. The lot is born. unit_price_cents is the product's base price —
    # except gift sets, priced from the bill of material.
    unit_price = (gift_set_price(product["id"]) if run["run_type"] == "GIFT_ASSEMBLY"
                  else product["base_price_cents"])
    mfg = now()
    lot = {
        "id": new_id(),
        "product_id": run["product_id"],
        "run_id": run["id"],
        "mfg_date": mfg,
        "expiry_date": mfg + timedelta(days=product["shelf_life_days"]),
        "qty_on_hand": out,
        "qty_reserved_rework": 0,
        "qty_scrapped": 0,
        "unit_price_cents": unit_price,
        "quality_status": "OK",
        "status": "ACTIVE",
    }
    stamp_new(lot)
    store.lots[lot["id"]] = lot
    run["created_lot_id"] = lot["id"]
    touch(run)

    # 4. Process-deviation cascade: out-of-band actuals make the lot SUSPECT,
    # the system opens a TEMPER_DEVIATION hold, the hold blocks the lot, and
    # the block re-triggers the window projection.
    deviated = (b["actual_cook_temp_c"] < recipe["cook_temp_min_c"]
                or b["actual_cook_temp_c"] > recipe["cook_temp_max_c"]
                or b["actual_temper_exit_c"] < recipe["temper_exit_min_c"]
                or b["actual_temper_exit_c"] > recipe["temper_exit_max_c"])
    if deviated:
        lot["quality_status"] = "SUSPECT"
        touch(lot)
        hold = {
            "id": new_id(),
            "lot_id": lot["id"],
            "defect_type": "TEMPER_DEVIATION",
            "affected_units": out,
            "lot_qty_at_open": lot["qty_on_hand"],
            "defect_rate_pct": defect_rate_pct(out, lot["qty_on_hand"]),
            "opened_by": "system",
            "disposition_by": None,
            "status": "OPEN",
        }
        stamp_new(hold)
        store.quality_holds[hold["id"]] = hold
        lot["status"] = "BLOCKED"
        touch(lot)
        recompute_window(window)

    # 5. GIFT_ASSEMBLY backflush: walk each component's FEFO pool; any lot
    # reaching zero transitions to DEPLETED, re-triggering its own window.
    if run["run_type"] == "GIFT_ASSEMBLY":
        for source, take in fefo_plan:
            source["qty_on_hand"] -= take
            if source["qty_on_hand"] == 0 and source["qty_reserved_rework"] == 0:
                source["status"] = "DEPLETED"
            touch(source)
            recompute_window_of_lot(source)

    # 6. REWORK settlement: release the earmark, deplete the source when both
    # counters reach zero, and close any REWORK_PENDING hold on the source.
    if run["run_type"] == "REWORK":
        source = store.lots[run["source_lot_id"]]
        source["qty_reserved_rework"] -= run["rework_qty"]
        depleted = False
        if source["qty_on_hand"] == 0 and source["qty_reserved_rework"] == 0:
            source["status"] = "DEPLETED"
            depleted = True
        touch(source)
        for h in store.quality_holds.values():
            if h["lot_id"] == source["id"] and h["status"] == "REWORK_PENDING":
                h["status"] = "CLOSED_REWORK"
                touch(h)
        if depleted:
            recompute_window_of_lot(source)

    # 7. Every completion ends by recomputing the run's window projection.
    recompute_window(window)
    return success_object(run_json(run))


@runs_bp.route("/production-runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    auth(("ProductionPlanner",))
    run = get_run_or_404(rid)
    if run["status"] not in ("PLANNED", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED or ON_HOLD run can be cancelled.")
    run["status"] = "CANCELLED"
    touch(run)
    # Release the packaging reservation — no consumption of qty_on_hand.
    product = store.products[run["product_id"]]
    component = store.packaging_components[product["packaging_component_id"]]
    component["qty_reserved"] -= run["packaging_reserved_qty"]
    sync_available(component)
    touch(component)
    if run["run_type"] == "REWORK":
        # Unit conservation is restored at the source.
        source = store.lots[run["source_lot_id"]]
        source["qty_reserved_rework"] -= run["rework_qty"]
        source["qty_on_hand"] += run["rework_qty"]
        touch(source)
        recompute_window_of_lot(source)
    recompute_window(store.seasonal_windows[run["window_id"]])
    return success_object(run_json(run))
