"""Level readings, quality reports, scale calibrations."""
from decimal import Decimal
from flask import Blueprint

import errors
from db import store, new_id, now_iso
from middleware import require_auth, require_role
from response import success_object, success_list
from services import serialize, domain
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_string, as_number, as_int, as_enum, as_iso8601,
                               check_range, parse_pagination)

bp = Blueprint("measurements", __name__)


# ---------------------------------------------------------------------------
# Level readings
# ---------------------------------------------------------------------------

@bp.route("/level-readings", methods=["POST"])
def create_level_reading():
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"vessel_id", "measured_at", "level_pct", "source"})
    require_fields(body, ["vessel_id", "measured_at", "level_pct"])
    vessel_id = as_string(body["vessel_id"], "vessel_id")
    measured_at = as_iso8601(body["measured_at"], "measured_at")
    level_pct = as_number(body["level_pct"], "level_pct")
    check_range(level_pct, "level_pct", 0, 100)
    source = "MANUAL"
    if "source" in body:
        source = as_enum(body["source"], "source", {"MANUAL", "SENSOR"})

    require_role(ctx, {"PlantOperator", "Technician"})

    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")

    # PlantOperator may only post for vessels of its own site.
    if ctx.role == "PlantOperator" and ctx.user_id != v["site_id"]:
        raise errors.forbidden("PlantOperator may only post readings for its own site")

    ts = now_iso()
    reading = {
        "id": new_id(),
        "vessel_id": vessel_id,
        "measured_at": measured_at,
        "level_pct": level_pct,
        "source": source,
        "created_at": ts,
    }
    store.level_readings[reading["id"]] = reading

    # Side effects: vessel version bump, reorder evaluation, posture cascade.
    v["updated_at"] = ts
    v["version"] = v["version"] + 1

    _maybe_trigger_reorder(v, reading)

    return success_object(serialize.serialize_level_reading(reading), status=201)


def _maybe_trigger_reorder(vessel: dict, reading: dict):
    """Auto-create a TRIGGERED ReplenishmentOrder when the reading breaches the
    reorder point and no open order exists."""
    open_order = any(
        o["status"] in ("TRIGGERED", "DISPATCHED")
        for o in store.replenishment_orders.values()
        if o["vessel_id"] == vessel["id"]
    )
    if open_order:
        return
    from decimal import Decimal as D
    if D(str(reading["level_pct"])) > D(str(vessel["reorder_point_pct"])):
        return

    # Compute order quantity per policy
    current_inv = domain.compute_current_inventory_tons(vessel)
    capacity = D(str(vessel["capacity_tons"]))
    policy = vessel.get("replenishment_policy", "TARGET_FILL")
    if policy == "TARGET_FILL":
        qty = D(str(vessel.get("target_fill_pct", 90))) / D(100) * capacity - current_inv
    else:  # DAYS_OF_COVER
        usage = domain.compute_avg_daily_usage_tons(vessel)
        qty = D(str(vessel.get("cover_days", 7))) * usage - current_inv
    if qty < 0:
        qty = D(0)
    qty = domain.round_half_up(qty, 1)

    ts = now_iso()
    order = {
        "id": new_id(),
        "vessel_id": vessel["id"],
        "trigger_reading_id": reading["id"],
        "policy_used": policy,
        "order_quantity_tons": qty,
        "status": "TRIGGERED",
        "delivered_tons": None,
        "received_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.replenishment_orders[order["id"]] = order


@bp.route("/vessels/<vessel_id>/level-readings", methods=["GET"])
def list_level_readings(vessel_id):
    require_auth()
    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")
    limit, offset = parse_pagination()
    readings = [r for r in store.level_readings.values() if r["vessel_id"] == vessel_id]
    from db import parse_iso
    # newest measured_at first; ties by created_at desc
    readings.sort(key=lambda r: (parse_iso(r["measured_at"]), parse_iso(r["created_at"])), reverse=True)
    total = len(readings)
    page = readings[offset:offset + limit]
    return success_list([serialize.serialize_level_reading(r) for r in page],
                        limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# Quality reports
# ---------------------------------------------------------------------------

@bp.route("/quality-reports", methods=["POST"])
def create_quality_report():
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"vessel_id", "sampled_at", "moisture_pct", "caking_index"})
    require_fields(body, ["vessel_id", "sampled_at", "moisture_pct", "caking_index"])
    vessel_id = as_string(body["vessel_id"], "vessel_id")
    sampled_at = as_iso8601(body["sampled_at"], "sampled_at")
    moisture_pct = as_number(body["moisture_pct"], "moisture_pct")
    check_range(moisture_pct, "moisture_pct", 0, 100)
    caking_index = as_int(body["caking_index"], "caking_index")
    if caking_index < 1 or caking_index > 5:
        raise errors.validation("caking_index must be between 1 and 5")

    require_role(ctx, {"Technician"})

    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")

    # Compute flowability_grade (POOR > MARGINAL > GOOD)
    from decimal import Decimal as D
    limit = D(str(v["moisture_limit_pct"]))
    if D(str(moisture_pct)) > limit or caking_index >= 4:
        grade = "POOR"
    elif D(str(moisture_pct)) > (limit - D(2)) or caking_index == 3:
        grade = "MARGINAL"
    else:
        grade = "GOOD"

    prev_posture = domain.compute_flow_posture(v)

    ts = now_iso()
    report = {
        "id": new_id(),
        "vessel_id": vessel_id,
        "sampled_at": sampled_at,
        "moisture_pct": moisture_pct,
        "caking_index": caking_index,
        "flowability_grade": grade,
        "created_at": ts,
    }
    store.quality_reports[report["id"]] = report

    v["updated_at"] = ts
    v["version"] = v["version"] + 1

    # Safety cascade: on becoming FLOW_IMPAIRED, auto-void DRAFT/ISSUED permits.
    new_posture = domain.compute_flow_posture(v)
    if new_posture == "FLOW_IMPAIRED" and prev_posture != "FLOW_IMPAIRED":
        domain.auto_void_permits_on_impaired(vessel_id)

    return success_object(serialize.serialize_quality_report(report), status=201)


@bp.route("/vessels/<vessel_id>/quality-reports", methods=["GET"])
def list_quality_reports(vessel_id):
    require_auth()
    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")
    limit, offset = parse_pagination()
    reports = [r for r in store.quality_reports.values() if r["vessel_id"] == vessel_id]
    reports.sort(key=lambda r: r["created_at"])
    total = len(reports)
    page = reports[offset:offset + limit]
    return success_list([serialize.serialize_quality_report(r) for r in page],
                        limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# Scale calibrations
# ---------------------------------------------------------------------------

@bp.route("/scale-calibrations", methods=["POST"])
def create_scale_calibration():
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"vessel_id", "tested_at", "test_weight_tons",
                                 "indicated_tons", "tolerance_pct"})
    require_fields(body, ["vessel_id", "tested_at", "test_weight_tons", "indicated_tons"])
    vessel_id = as_string(body["vessel_id"], "vessel_id")
    tested_at = as_iso8601(body["tested_at"], "tested_at")
    test_weight = as_number(body["test_weight_tons"], "test_weight_tons")
    check_range(test_weight, "test_weight_tons", 0, None, min_exclusive=True)
    indicated = as_number(body["indicated_tons"], "indicated_tons")
    check_range(indicated, "indicated_tons", 0, None)
    tolerance = 0.25
    if "tolerance_pct" in body:
        tolerance = as_number(body["tolerance_pct"], "tolerance_pct")
        check_range(tolerance, "tolerance_pct", 0, None, min_exclusive=True)

    require_role(ctx, {"Technician"})

    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")

    basis, error_pct, result = domain.compute_calibration(v, test_weight, indicated, tolerance)

    ts = now_iso()
    cal = {
        "id": new_id(),
        "vessel_id": vessel_id,
        "tested_at": tested_at,
        "test_weight_tons": test_weight,
        "indicated_tons": indicated,
        "tolerance_pct": tolerance,
        "error_basis_used": basis,
        "error_pct": error_pct,
        "result": result,
        "created_at": ts,
    }
    store.scale_calibrations[cal["id"]] = cal

    v["scale_status"] = "IN_TOLERANCE" if result == "PASS" else "OUT_OF_TOLERANCE"
    v["updated_at"] = ts
    v["version"] = v["version"] + 1

    return success_object(serialize.serialize_scale_calibration(cal), status=201)


@bp.route("/vessels/<vessel_id>/scale-calibrations", methods=["GET"])
def list_scale_calibrations(vessel_id):
    require_auth()
    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")
    limit, offset = parse_pagination()
    cals = [c for c in store.scale_calibrations.values() if c["vessel_id"] == vessel_id]
    cals.sort(key=lambda c: c["created_at"])
    total = len(cals)
    page = cals[offset:offset + limit]
    return success_list([serialize.serialize_scale_calibration(c) for c in page],
                        limit=limit, offset=offset, total_count=total)
