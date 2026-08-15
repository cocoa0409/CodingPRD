from decimal import Decimal

from flask import Blueprint

from db import DB, stamp_new, touch
from errors import invalid_state, validation
from middleware import (
    as_array,
    as_enum,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.repair_orders import get_ro_or_404
from services.core import TOLERANCE_PCT, round_half_up_2dp

bp = Blueprint("test_runs", __name__)

TEST_TYPES = ["PERFORMANCE_CURVE", "HYDROSTATIC", "POP_TEST"]


@bp.route("/repair-orders/<rid>/test-runs", methods=["POST"])
def create_test_run(rid):
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["Technician"])
    ro = get_ro_or_404(rid)
    test_type = as_enum(body, "test_type", TEST_TYPES)
    measured_points = as_array(body, "measured_points")
    if len(measured_points) == 0:
        validation("measured_points must contain at least one point")
    for p in measured_points:
        if not isinstance(p, dict):
            validation("measured_points entries must be objects")
        duty = p.get("duty_pct")
        if isinstance(duty, bool) or not isinstance(duty, (int, float)) or duty <= 0 or duty > 150:
            validation("duty_pct must be in (0, 150]")
        mv = p.get("measured_value")
        rv = p.get("reference_value")
        if isinstance(mv, bool) or not isinstance(mv, (int, float)):
            validation("measured_value must be a number")
        if isinstance(rv, bool) or not isinstance(rv, (int, float)) or rv == 0:
            validation("reference_value must be a non-zero number")

    if ro["status"] != "IN_TEST":
        invalid_state("Repair order is not in IN_TEST")

    asset = DB.assets.get(ro["asset_id"])

    # Per-point deviations rounded half-up to 2dp; comparisons use rounded values.
    deviations: list[Decimal] = []
    duties: list[Decimal] = []
    for p in measured_points:
        dev = round_half_up_2dp(
            (Decimal(str(p["measured_value"])) - Decimal(str(p["reference_value"])))
            / Decimal(str(p["reference_value"]))
            * Decimal("100")
        )
        deviations.append(dev)
        duties.append(Decimal(str(p["duty_pct"])))

    max_deviation_pct = max(abs(d) for d in deviations)
    weighted_sum = sum(d * w for d, w in zip(deviations, duties))
    duty_total = sum(duties)
    weighted_deviation_pct = round_half_up_2dp(weighted_sum / duty_total)

    if asset and asset.get("test_standard") == "API_610_PER_POINT":
        verdict = "PASS" if max_deviation_pct <= TOLERANCE_PCT else "FAIL"
    else:
        verdict = "PASS" if abs(weighted_deviation_pct) <= TOLERANCE_PCT else "FAIL"

    run_number = (
        max(
            (t["run_number"] for t in DB.test_runs.values() if t["repair_order_id"] == ro["id"]),
            default=0,
        )
        + 1
    )

    run = stamp_new(
        {
            "repair_order_id": ro["id"],
            "run_number": run_number,
            "test_type": test_type,
            "measured_points": measured_points,
            "max_deviation_pct": float(max_deviation_pct),
            "weighted_deviation_pct": float(weighted_deviation_pct),
            "verdict": verdict,
            "tested_by_id": caller.user_id,
        }
    )
    DB.test_runs[run["id"]] = run

    # Verdict drives the order.
    if verdict == "FAIL":
        ro["status"] = "IN_REPAIR"
        ro["repair_round"] = int(ro.get("repair_round", 0)) + 1
    else:
        if ro["requires_certification"]:
            ro["status"] = "READY_FOR_CERT"
        else:
            ro["status"] = "COMPLETE"
    touch(ro)
    return success_object(run, status=201)


@bp.route("/repair-orders/<rid>/test-runs", methods=["GET"])
def list_test_runs(rid):
    caller = authenticate()
    ro = get_ro_or_404(rid)
    require_customer_ownership(caller, ro["customer_id"])
    items = sorted(
        (t for t in DB.test_runs.values() if t["repair_order_id"] == ro["id"]),
        key=lambda t: (t["run_number"], t["created_at"], t["id"]),
    )
    return success_list(items, limit=len(items) if items else 10, offset=0, total_count=len(items))
