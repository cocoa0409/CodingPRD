"""Shared lookups, disposition guards and derived projections."""

from db import db, order_key, sorted_records
from errors import ApiError
from services import calc
from util import dt_of


# --------------------------------------------------------------------------
# existence
# --------------------------------------------------------------------------

def find(collection, record_id, error_id):
    if not isinstance(record_id, str):
        raise ApiError(error_id)
    record = getattr(db, collection).get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def part_spec_or_404(record_id):
    return find("part_specs", record_id, "ERR_PART_SPEC_NOT_FOUND")


def steel_heat_or_404(record_id):
    return find("steel_heats", record_id, "ERR_STEEL_HEAT_NOT_FOUND")


def wire_lot_or_404(record_id):
    return find("wire_lots", record_id, "ERR_WIRE_LOT_NOT_FOUND")


def heading_tool_or_404(record_id):
    return find("heading_tools", record_id, "ERR_HEADING_TOOL_NOT_FOUND")


def furnace_or_404(record_id):
    return find("furnaces", record_id, "ERR_FURNACE_NOT_FOUND")


def production_lot_or_404(record_id):
    return find("production_lots", record_id, "ERR_PRODUCTION_LOT_NOT_FOUND")


def secondary_op_or_404(record_id):
    return find("secondary_operations", record_id, "ERR_SECONDARY_OPERATION_NOT_FOUND")


def heat_treat_run_or_404(record_id):
    return find("heat_treat_runs", record_id, "ERR_HEAT_TREAT_RUN_NOT_FOUND")


def plating_run_or_404(record_id):
    return find("plating_runs", record_id, "ERR_PLATING_RUN_NOT_FOUND")


def lot_test_or_404(record_id):
    return find("lot_tests", record_id, "ERR_LOT_TEST_NOT_FOUND")


def cert_doc_or_404(record_id):
    return find("certification_documents", record_id, "ERR_CERT_DOCUMENT_NOT_FOUND")


def pack_unit_or_404(record_id):
    return find("pack_units", record_id, "ERR_PACK_UNIT_NOT_FOUND")


# --------------------------------------------------------------------------
# uniqueness
# --------------------------------------------------------------------------

def require_unique(collection, field, value, error_id="ERR_DUPLICATE_IDENTIFIER",
                   exclude_id=None, scope=None):
    for record in getattr(db, collection).values():
        if exclude_id is not None and record["id"] == exclude_id:
            continue
        if scope:
            if any(record.get(k) != v for k, v in scope.items()):
                continue
        if record.get(field) == value:
            raise ApiError(error_id)


# --------------------------------------------------------------------------
# pinned part specification
# --------------------------------------------------------------------------

def snapshot_part_spec(spec):
    db.part_spec_snapshots[(spec["id"], spec["version"])] = dict(spec)


def spec_for_lot(lot):
    """The PartSpec version pinned on the lot, never the live specification."""
    key = (lot["part_spec_id"], lot.get("pinned_part_spec_version"))
    snapshot = db.part_spec_snapshots.get(key)
    if snapshot is not None:
        return snapshot
    return db.part_specs[lot["part_spec_id"]]


# --------------------------------------------------------------------------
# children
# --------------------------------------------------------------------------

def children(collection, field, value):
    return sorted_records(
        [r for r in getattr(db, collection).values() if r.get(field) == value]
    )


def lot_secondary_ops(lot_id):
    return children("secondary_operations", "production_lot_id", lot_id)


def lot_heat_treat_runs(lot_id):
    return children("heat_treat_runs", "production_lot_id", lot_id)


def lot_plating_runs(lot_id):
    return children("plating_runs", "production_lot_id", lot_id)


def lot_tests(lot_id):
    return children("lot_tests", "production_lot_id", lot_id)


def lot_certificates(lot_id):
    return children("certification_documents", "production_lot_id", lot_id)


def lot_pack_units(lot_id):
    return children("pack_units", "production_lot_id", lot_id)


def cert_pack_units(cert_id):
    return children("pack_units", "certification_document_id", cert_id)


# --------------------------------------------------------------------------
# disposition guards (ladder tiers 8 and 9)
# --------------------------------------------------------------------------

def guard_quarantined(lot):
    if lot["disposition"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED")


def guard_on_hold(lot):
    if lot["disposition"] == "HOLD":
        raise ApiError("ERR_LOT_ON_HOLD")


def guard_disposition(lot):
    guard_quarantined(lot)
    guard_on_hold(lot)


# --------------------------------------------------------------------------
# secondary operation completeness
# --------------------------------------------------------------------------

def stage_required_op_types(spec, lot):
    required = list(spec.get("required_secondary_ops") or [])
    if spec.get("thread_timing") == "AFTER_HEAT_TREAT" and not lot.get("heat_treat_completed"):
        return [op for op in required if op != "THREAD_ROLL"]
    return required


def required_ops_satisfied(lot, spec):
    ops = lot_secondary_ops(lot["id"])
    if any(op["status"] == "PENDING" for op in ops):
        return False
    done = {op["op_type"] for op in ops if op["status"] == "DONE"}
    return all(op_type in done for op_type in stage_required_op_types(spec, lot))


# --------------------------------------------------------------------------
# governing runs
# --------------------------------------------------------------------------

def governing_heat_treat_run(lot):
    """COMPLETED and PASS, greatest window_end_at, earliest created_at breaks ties."""
    best = None
    best_key = None
    for run in lot_heat_treat_runs(lot["id"]):
        if run["status"] != "COMPLETED" or run["result"] != "PASS":
            continue
        end = dt_of(run, "window_end_at")
        key = (end, order_key(run))
        if best is None or end > best_key[0] or (end == best_key[0] and key[1] < best_key[1]):
            best, best_key = run, key
    return best


def newest_active_plating_run(lot):
    """The newest plating run that is not SUPERSEDED."""
    best = None
    for run in lot_plating_runs(lot["id"]):
        if run["status"] == "SUPERSEDED":
            continue
        if best is None or order_key(run) > order_key(best):
            best = run
    return best


def chain_plating_run(lot):
    """BAKE_COMPLETE, greatest bake_started_at, earliest created_at breaks ties."""
    best = None
    best_key = None
    for run in lot_plating_runs(lot["id"]):
        if run["status"] != "BAKE_COMPLETE":
            continue
        started = dt_of(run, "bake_started_at")
        sort_value = started if started is not None else None
        key = (sort_value, order_key(run))
        if best is None:
            best, best_key = run, key
            continue
        if best_key[0] is None and sort_value is not None:
            best, best_key = run, key
        elif sort_value is not None and best_key[0] is not None:
            if sort_value > best_key[0] or (sort_value == best_key[0] and key[1] < best_key[1]):
                best, best_key = run, key
        elif sort_value is None and best_key[0] is None:
            if key[1] < best_key[1]:
                best, best_key = run, key
    return best


# --------------------------------------------------------------------------
# risk scoring (pass one)
# --------------------------------------------------------------------------

def compute_pre_test_risk(lot):
    spec = spec_for_lot(lot)
    heat = db.steel_heats.get(lot.get("traceability_heat_id"))
    heat_status = heat["cert_status"] if heat else None
    run = governing_heat_treat_run(lot)
    total_decarb = run["total_decarb_depth_mm"] if run else None
    plating = newest_active_plating_run(lot)
    delay = plating["bake_delay_hours"] if plating else None
    return calc.risk_score_pre_test(
        heat_status,
        lot.get("tool_utilization_pct"),
        bool(spec.get("he_bake_required")),
        delay,
        total_decarb,
        spec.get("max_decarb_depth_mm"),
    )


# --------------------------------------------------------------------------
# traceability projection
# --------------------------------------------------------------------------

def project_traceability(lot):
    spec = spec_for_lot(lot)
    heat = db.steel_heats.get(lot.get("traceability_heat_id"))
    wire = db.wire_lots.get(lot.get("wire_lot_id"))
    tool = db.heading_tools.get(lot.get("heading_tool_id"))
    run = governing_heat_treat_run(lot)
    plating = None
    if spec.get("plating_spec") != "NONE":
        plating = chain_plating_run(lot)
    return {
        "heat_number": heat["heat_number"] if heat else None,
        "mill_code": heat["mill_code"] if heat else None,
        "mill_cert_serial": heat["mill_cert_serial"] if heat else None,
        "cert_status": heat["cert_status"] if heat else None,
        "wire_lot_reduction_pct": wire["reduction_pct"] if wire else None,
        "lubricant_coating": wire["lubricant_coating"] if wire else None,
        "tool_code": tool["tool_code"] if tool else None,
        "tool_regrind_count": tool["regrind_count"] if tool else None,
        "tool_utilization_pct": lot.get("tool_utilization_pct"),
        "austenitize_temp_c": run["austenitize_temp_c"] if run else None,
        "core_hardness_hv": run["core_hardness_hv"] if run else None,
        "total_decarb_depth_mm": run["total_decarb_depth_mm"] if run else None,
        "bake_delay_hours": plating["bake_delay_hours"] if plating else None,
        "bake_duration_min": plating["bake_duration_min"] if plating else None,
        "pinned_part_spec_version": lot.get("pinned_part_spec_version"),
    }
