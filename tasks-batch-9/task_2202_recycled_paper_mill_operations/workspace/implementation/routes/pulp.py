from decimal import Decimal

from flask import Blueprint

import auth
import calc
import common
import response
import shape
import store
from errors import err
from shape import D, q

bp = Blueprint("pulp", __name__)
ZERO = Decimal("0")
BLEND_LIMIT = Decimal("3.500")
REJECT_FRACTION_LIMIT = Decimal("0.40")


def _validate_furnish(data):
    entries = shape.get_list(data, "furnish_lines", 1, 6)
    seen = set()
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise err("ERR_VALIDATION", "furnish_lines[%d] must be an object" % i)
        lot_id = shape.get_str(e, "inventory_lot_id", min_len=1)
        if lot_id in seen:
            raise err("ERR_VALIDATION", "inventory_lot_id must be unique within the batch")
        seen.add(lot_id)
        out.append({
            "inventory_lot_id": lot_id,
            "tons_charged": shape.get_num(e, "tons_charged", exclusive_min=0, places=3),
        })
    return out


@bp.post("/pulp-batches")
def create_batch():
    auth.require_roles("MachineOperator")
    data = shape.body()
    shape.reject_unexpected_version(data)
    line = shape.get_enum(data, "pulper_line", ["OCC_LINE", "DIP_LINE"])
    product = shape.get_str(data, "target_product_code")
    lines = _validate_furnish(data)
    common.need_spec(product)
    for ln in lines:
        if store.get("fiber_inventory_lots", ln["inventory_lot_id"]) is None:
            raise err("ERR_FURNISH_REFERENCE_NOT_FOUND", "inventory_lot_id does not resolve")
    row = {
        "pulper_line": line,
        "target_product_code": product,
        "furnish_lines": lines,
        "charged_tons": None,
        "blend_contamination_pct": None,
        "provisional_accepted_tons": None,
        "measured_reject_tons": None,
        "final_accepted_tons": None,
        "yield_variance_tons": None,
        "consumed_tons": 0.0,
        "available_tons": 0.0,
        "caustic_kg": 0,
        "peroxide_kg": 0,
        "surfactant_kg": 0,
        "deink_pass_count": 0,
        "brightness_iso": None,
        "cumulative_chemical_cost": 0.0,
        "status": "QUEUED",
        "_reserved": False,
    }
    store.insert("pulp_batches", row)
    return response.ok(common.view(row), 201)


@bp.get("/pulp-batches/<bid>")
def get_batch(bid):
    auth.require_roles("MachineOperator", "QualityLab", "MillPlanner")
    return response.ok(common.view(common.need("pulp_batches", bid, "ERR_PULP_BATCH_NOT_FOUND")))


@bp.get("/pulp-batches")
def list_batches():
    auth.require_roles("MachineOperator", "QualityLab", "MillPlanner")
    limit, offset = shape.pagination()
    from flask import request
    lot_filter = request.args.get("inventory_lot_id")

    def extra(b):
        if lot_filter is None:
            return True
        return any(ln["inventory_lot_id"] == lot_filter for ln in b["furnish_lines"])

    rows = common.filtered("pulp_batches", {
        "status": "status",
        "target_product_code": "target_product_code",
        "pulper_line": "pulper_line",
    }, extra=extra)
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


def _need_batch(bid):
    return common.need("pulp_batches", bid, "ERR_PULP_BATCH_NOT_FOUND")


@bp.post("/pulp-batches/<bid>/start")
def start_batch(bid):
    auth.require_roles("MachineOperator")
    batch = _need_batch(bid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    if batch["status"] != "QUEUED":
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch is not QUEUED")
    lots = {}
    for ln in batch["furnish_lines"]:
        lot = store.get("fiber_inventory_lots", ln["inventory_lot_id"])
        if lot is None:
            raise err("ERR_FURNISH_REFERENCE_NOT_FOUND", "inventory_lot_id does not resolve")
        lots[lot["id"]] = lot
    for ln in batch["furnish_lines"]:
        if lots[ln["inventory_lot_id"]]["status"] != "AVAILABLE":
            raise err("ERR_LOT_NOT_AVAILABLE", "furnish lot is not AVAILABLE")
    for ln in batch["furnish_lines"]:
        lot = lots[ln["inventory_lot_id"]]
        if D(ln["tons_charged"]) > D(lot["tons_available"]):
            raise err("ERR_INSUFFICIENT_FIBER", "furnish line exceeds the lot's available tonnage")
    charged = q(sum((D(ln["tons_charged"]) for ln in batch["furnish_lines"]), ZERO), 3)
    blend = calc.blend_contamination(batch["furnish_lines"], lots, charged)
    if D(blend) > BLEND_LIMIT:
        raise err("ERR_FURNISH_CONTAMINATION_EXCEEDED", "blend contamination above 3.500")
    spec = common.need_spec(batch["target_product_code"])
    if spec["requires_deink_pulp"] and batch["pulper_line"] != "DIP_LINE":
        raise err("ERR_WRONG_PULPER_LINE", "deink-required furnish must be charged on DIP_LINE")

    grades = {}
    for lot in lots.values():
        grades[lot["grade_code"]] = common.need_grade(lot["grade_code"])
    ordered = sorted(batch["furnish_lines"], key=lambda ln: (
        lots[ln["inventory_lot_id"]]["created_at"],
        grades[lots[ln["inventory_lot_id"]]["grade_code"]]["rank_order"],
    ))
    batch["charged_tons"] = float(charged)
    batch["blend_contamination_pct"] = blend
    batch["provisional_accepted_tons"] = calc.pulp_yield_provisional(ordered, lots, grades)
    batch["status"] = "PULPING"
    batch["_reserved"] = True
    store.touch("pulp_batches", batch)
    for lot in lots.values():
        common.recompute_lot(lot)
    return response.ok(common.view(batch))


@bp.post("/pulp-batches/<bid>/screen")
def screen_batch(bid):
    auth.require_roles("MachineOperator")
    batch = _need_batch(bid)
    shape.reject_unexpected_version(shape.body())
    if batch["status"] != "PULPING":
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch is not PULPING")
    batch["status"] = "SCREENED"
    store.touch("pulp_batches", batch)
    return response.ok(common.view(batch))


@bp.post("/pulp-batches/<bid>/clean")
def clean_batch(bid):
    auth.require_roles("MachineOperator")
    batch = _need_batch(bid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    reject = shape.get_num(data, "measured_reject_tons", minimum=0, places=3)
    if batch["status"] != "SCREENED":
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch is not SCREENED")
    if D(reject) > D(batch["charged_tons"]) * REJECT_FRACTION_LIMIT:
        raise err("ERR_REJECT_TONS_IMPLAUSIBLE", "measured_reject_tons above 40% of charged_tons")
    batch["measured_reject_tons"] = reject
    batch["status"] = "CLEANED"
    store.touch("pulp_batches", batch)
    common.append_reject("PULP_REJECT", batch["id"], reject)
    return response.ok(common.view(batch))


def _deink_sludge_total(batch_id):
    total = ZERO
    for r in store.all_rows("reject_streams"):
        if (r["source_kind"] == "DEINK_SLUDGE" and r["source_ref_id"] == batch_id
                and r["reversal_of_id"] is None):
            total += D(r["dry_solids_tons"])
    return total


def _strike_final_tonnage(batch):
    sludge = _deink_sludge_total(batch["id"])
    batch["final_accepted_tons"] = calc.pulp_yield_final(
        batch["charged_tons"], batch["measured_reject_tons"], sludge)
    batch["yield_variance_tons"] = float(q(
        D(batch["final_accepted_tons"]) - D(batch["provisional_accepted_tons"]), 3))


@bp.post("/pulp-batches/<bid>/deink")
def deink_batch(bid):
    auth.require_roles("MachineOperator")
    batch = _need_batch(bid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    caustic = shape.get_num(data, "caustic_kg", required=False, minimum=0, default=0)
    peroxide = shape.get_num(data, "peroxide_kg", required=False, minimum=0, default=0)
    surfactant = shape.get_num(data, "surfactant_kg", required=False, minimum=0, default=0)
    if batch["status"] not in ("CLEANED", "DEINK_HOLD"):
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch cannot enter a deink pass")
    if batch["status"] == "DEINK_HOLD" and int(batch["deink_pass_count"]) >= 3:
        raise err("ERR_DEINK_PASS_LIMIT", "deink pass limit reached")
    if batch["pulper_line"] != "DIP_LINE":
        raise err("ERR_WRONG_PULPER_LINE", "deink passes run only on DIP_LINE")
    batch["caustic_kg"] = caustic
    batch["peroxide_kg"] = peroxide
    batch["surfactant_kg"] = surfactant
    batch["status"] = "DEINKING"
    store.touch("pulp_batches", batch)
    return response.ok(common.view(batch))


@bp.post("/pulp-batches/<bid>/brightness")
def brightness_batch(bid):
    auth.require_roles("QualityLab")
    batch = _need_batch(bid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    brightness = shape.get_num(data, "brightness_iso", minimum=0, maximum=100, places=1)
    if batch["status"] != "DEINKING":
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch is not DEINKING")
    spec = common.need_spec(batch["target_product_code"])
    pass_index = int(batch["deink_pass_count"]) + 1
    res = calc.deink_pass(batch["caustic_kg"], batch["peroxide_kg"], batch["surfactant_kg"],
                          batch["charged_tons"], spec["family"], pass_index)
    batch["brightness_iso"] = brightness
    batch["deink_pass_count"] = pass_index
    batch["cumulative_chemical_cost"] = float(q(
        D(batch["cumulative_chemical_cost"]) + res["pass_cost"], 2))
    common.append_reject("DEINK_SLUDGE", batch["id"], res["sludge_tons"])
    min_b = spec.get("min_brightness_iso")
    passes = min_b is None or D(brightness) >= D(min_b)
    if passes:
        batch["status"] = "APPROVED"
        _strike_final_tonnage(batch)
        common.recompute_batch_available(batch)
    else:
        batch["status"] = "DEINK_HOLD"
    store.touch("pulp_batches", batch)
    return response.ok(common.view(batch))


@bp.post("/pulp-batches/<bid>/approve")
def approve_batch(bid):
    auth.require_roles("QualityLab")
    batch = _need_batch(bid)
    shape.reject_unexpected_version(shape.body())
    if batch["status"] != "CLEANED":
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch is not CLEANED")
    spec = common.need_spec(batch["target_product_code"])
    if spec["requires_deink_pulp"]:
        raise err("ERR_PULP_BATCH_INVALID_STATE",
                  "target product requires deinked pulp; the batch must run a deink pass")
    batch["status"] = "APPROVED"
    _strike_final_tonnage(batch)
    common.recompute_batch_available(batch)
    store.touch("pulp_batches", batch)
    return response.ok(common.view(batch))


@bp.post("/pulp-batches/<bid>/divert")
def divert_batch(bid):
    auth.require_roles("MillPlanner")
    batch = _need_batch(bid)
    shape.reject_unexpected_version(shape.body())
    if batch["status"] != "DEINK_HOLD":
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch is not DEINK_HOLD")
    batch["status"] = "DIVERTED"
    batch["final_accepted_tons"] = 0.0
    batch["available_tons"] = 0.0
    store.touch("pulp_batches", batch)
    for run in store.all_rows("production_runs"):
        if run.get("pulp_batch_id") == batch["id"] and run["run_status"] == "SCHEDULED":
            run["run_status"] = "ABORTED"
            run["quality_status"] = "CONDEMNED"
            store.touch("production_runs", run)
            common.deschedule_orders_of_run(run["id"])
    return response.ok(common.view(batch))


@bp.post("/pulp-batches/<bid>/cancel")
def cancel_batch(bid):
    auth.require_roles("MillPlanner")
    batch = _need_batch(bid)
    shape.reject_unexpected_version(shape.body())
    if batch["status"] not in ("QUEUED", "PULPING"):
        raise err("ERR_PULP_BATCH_INVALID_STATE", "pulp batch cannot be cancelled")
    was_pulping = batch["status"] == "PULPING"
    batch["status"] = "CANCELLED"
    batch["_reserved"] = False
    store.touch("pulp_batches", batch)
    if was_pulping:
        for ln in batch["furnish_lines"]:
            lot = store.get("fiber_inventory_lots", ln["inventory_lot_id"])
            if lot is not None:
                common.recompute_lot(lot)
    return response.ok(common.view(batch))
