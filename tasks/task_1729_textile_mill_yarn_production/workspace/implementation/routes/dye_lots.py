"""DyeLot + QualityTest endpoints.

Validation cascade on dye-lot create (PRD §2.10, §3.4):
  auth -> FK existence -> yarn lot state GREIGE (ERR_INVALID_STATE) ->
  quality gate: recipe must be APPROVED (ERR_QUALITY_GATE_FAILED) ->
  vat cooldown (ERR_WINDOW_CONFLICT) -> capacity (ERR_INSUFFICIENT_CAPACITY).

Approval from SHADE_PENDING requires a quality test graded FIRST_QUALITY or
SECOND_QUALITY; grade REJECTED -> ERR_QUALITY_GATE_FAILED.
"""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_insufficient_capacity,
    err_invalid_state,
    err_not_found,
    err_quality_gate,
    err_reference_not_found,
    err_window_conflict,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_dye_lot, serialize_quality_test
from services.calculations import compute_grade, delta_e
from services.workflows import (
    latest_grade,
    latest_quality_test,
    parse_instant,
    quality_tests_of_dye_lot,
    touch,
    vat_buffer_conflict,
)
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    opt_decimal,
    req_decimal,
    req_int,
    req_string,
    round2,
    sort_and_paginate,
)

bp = Blueprint("dye_lots", __name__)

READ_ROLES = ("DyeHouseOperator", "QualityInspector", "CustomerServiceRep", "MillPlanner")


def _get_dye_lot_or_404(did):
    record = db.dye_lots.get(did)
    if record is None:
        raise err_not_found("Dye lot not found")
    return record


@bp.post("/mill/dye-lots")
def create_dye_lot():
    require_roles("DyeHouseOperator")
    body = get_json_body()
    yarn_lot_id = req_string(body, "yarn_lot_id")
    shade_band_id = req_string(body, "shade_band_id")
    vat_id = req_string(body, "vat_id")
    scheduled_at_raw = req_string(body, "scheduled_at")
    requested_yards = req_decimal(body, "requested_yards", min_value=0, min_exclusive=True)

    # Reference existence (priority 4)
    yarn_lot = db.yarn_lots.get(yarn_lot_id)
    if yarn_lot is None:
        raise err_reference_not_found("yarn_lot_id does not resolve to an existing yarn lot")
    shade_band = db.shade_bands.get(shade_band_id)
    if shade_band is None:
        raise err_reference_not_found("shade_band_id does not resolve to an existing shade band")

    try:
        scheduled_at = parse_instant(scheduled_at_raw)
    except ValueError:
        from errors import err_invalid_request
        raise err_invalid_request("scheduled_at must be an ISO-8601 datetime")

    # State legality (priority 5)
    if yarn_lot["status"] != "GREIGE":
        raise err_invalid_state("Yarn lot must be GREIGE to be submitted for dyeing")

    # Quality gate (priority 6): recipe must still be APPROVED
    recipe = db.blend_recipes.get(yarn_lot["recipe_id"])
    if recipe is None or recipe["status"] != "APPROVED":
        raise err_quality_gate("Yarn lot's blend recipe is not APPROVED")

    # Temporal guard (priority 8): vat cooldown
    if vat_buffer_conflict(vat_id, scheduled_at):
        raise err_window_conflict("Vat schedule violates the 30-minute cooldown between batches")

    # Capacity (priority 10)
    if yarn_lot["greige_yards_available"] < requested_yards:
        raise err_insufficient_capacity("Yarn lot lacks greige yards for this dye lot")

    ts = now_iso()
    record = {
        "id": new_id(),
        "yarn_lot_id": yarn_lot["id"],
        "shade_band_id": shade_band["id"],
        "vat_id": vat_id,
        "scheduled_at": scheduled_at_raw,
        "requested_yards": round2(requested_yards),
        "status": "SUBMITTED",
        "measured_delta_e": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.dye_lots[record["id"]] = record

    # Cascade: yarn lot GREIGE -> DYEING, debit greige yards, bump version
    yarn_lot["status"] = "DYEING"
    yarn_lot["greige_yards_available"] = round2(yarn_lot["greige_yards_available"] - record["requested_yards"])
    touch(yarn_lot)

    return success_object(serialize_dye_lot(record), 201)


@bp.get("/mill/dye-lots")
def list_dye_lots():
    require_roles(*READ_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.dye_lots.values()),
        {
            "yarn_lot_id": request.args.get("yarn_lot_id"),
            "shade_band_id": request.args.get("shade_band_id"),
            "status": request.args.get("status"),
            "vat_id": request.args.get("vat_id"),
        },
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_dye_lot(r) for r in page], limit, offset, total)


@bp.get("/mill/dye-lots/<did>")
def get_dye_lot(did):
    require_roles(*READ_ROLES)
    return success_object(serialize_dye_lot(_get_dye_lot_or_404(did)))


@bp.post("/mill/dye-lots/<did>/start")
def start_dye_lot(did):
    require_roles("DyeHouseOperator")
    record = _get_dye_lot_or_404(did)
    if record["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED dye lot can be started")
    yarn_lot = db.yarn_lots.get(record["yarn_lot_id"])
    if yarn_lot is None or yarn_lot["status"] != "DYEING":
        raise err_invalid_state("Parent yarn lot must be DYEING to start the batch")
    record["status"] = "DYEING"
    touch(record)
    return success_object(serialize_dye_lot(record))


@bp.post("/mill/dye-lots/<did>/quality-tests")
def create_quality_test(did):
    require_roles("QualityInspector")
    dye_lot = _get_dye_lot_or_404(did)
    body = get_json_body()
    shrinkage_prov = req_decimal(body, "shrinkage_pct_provisional", min_value=0, max_value=100)
    shrinkage_final = opt_decimal(body, "shrinkage_pct_final", min_value=0, max_value=100, default=None)
    hand_score = req_int(body, "hand_score", min_value=1, max_value=5)
    measured_l = opt_decimal(body, "measured_l")
    measured_a = opt_decimal(body, "measured_a")
    measured_b = opt_decimal(body, "measured_b")

    prov = round2(shrinkage_prov)
    final = round2(shrinkage_final) if shrinkage_final is not None else None
    grade = compute_grade(prov, final, hand_score)

    ts = now_iso()
    record = {
        "id": new_id(),
        "dye_lot_id": dye_lot["id"],
        "shrinkage_pct_provisional": prov,
        "shrinkage_pct_final": final,
        "hand_score": hand_score,
        "grade": grade,
        "measured_l": measured_l,
        "measured_a": measured_a,
        "measured_b": measured_b,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.quality_tests[record["id"]] = record

    # Shade refresh: when the test records shade values, update DyeLot.measured_delta_e
    if measured_l is not None and measured_a is not None and measured_b is not None:
        band = db.shade_bands.get(dye_lot["shade_band_id"])
        if band is not None:
            dye_lot["measured_delta_e"] = delta_e(
                measured_l, measured_a, measured_b,
                band["centroid_l"], band["centroid_a"], band["centroid_b"],
            )
            touch(dye_lot)

    return success_object(serialize_quality_test(record), 201)


@bp.get("/mill/dye-lots/<did>/quality-tests")
def list_quality_tests(did):
    require_roles("DyeHouseOperator", "QualityInspector", "CustomerServiceRep")
    dye_lot = _get_dye_lot_or_404(did)
    tests = quality_tests_of_dye_lot(dye_lot["id"])
    return success_list([serialize_quality_test(t) for t in tests], len(tests), 0, len(tests))


@bp.post("/mill/dye-lots/<did>/submit-shade")
def submit_shade(did):
    require_roles("DyeHouseOperator")
    record = _get_dye_lot_or_404(did)
    if record["status"] != "DYEING":
        raise err_invalid_state("Only a DYEING dye lot can be submitted for shade review")
    test = latest_quality_test(record["id"])
    if test is None:
        raise err_invalid_state("At least one quality test must exist before shade submission")
    # Populate measured_delta_e from the latest quality test's shade values if recorded
    if test.get("measured_l") is not None and test.get("measured_a") is not None and test.get("measured_b") is not None:
        band = db.shade_bands.get(record["shade_band_id"])
        if band is not None:
            record["measured_delta_e"] = delta_e(
                test["measured_l"], test["measured_a"], test["measured_b"],
                band["centroid_l"], band["centroid_a"], band["centroid_b"],
            )
    record["status"] = "SHADE_PENDING"
    touch(record)
    return success_object(serialize_dye_lot(record))


@bp.post("/mill/dye-lots/<did>/approve")
def approve_dye_lot(did):
    require_roles("QualityInspector")
    record = _get_dye_lot_or_404(did)
    if record["status"] != "SHADE_PENDING":
        raise err_invalid_state("Only a SHADE_PENDING dye lot can be approved")
    grade = latest_grade(record["id"])
    if grade == "REJECTED":
        raise err_quality_gate("Dye lot cannot be approved while its quality test graded REJECTED")
    if grade not in ("FIRST_QUALITY", "SECOND_QUALITY"):
        raise err_quality_gate("Dye lot approval requires a FIRST_QUALITY or SECOND_QUALITY grade")

    record["status"] = "APPROVED"
    touch(record)

    # Cascade: yarn lot DYEING -> FINISHED
    yarn_lot = db.yarn_lots.get(record["yarn_lot_id"])
    if yarn_lot is not None and yarn_lot["status"] == "DYEING":
        yarn_lot["status"] = "FINISHED"
        touch(yarn_lot)

    return success_object(serialize_dye_lot(record))


@bp.post("/mill/dye-lots/<did>/reject")
def reject_dye_lot(did):
    require_roles("QualityInspector")
    record = _get_dye_lot_or_404(did)
    if record["status"] != "SHADE_PENDING":
        raise err_invalid_state("Only a SHADE_PENDING dye lot can be rejected")
    record["status"] = "REJECTED"
    touch(record)

    # Rework loop: yarn lot DYEING -> GREIGE, yards credited back
    yarn_lot = db.yarn_lots.get(record["yarn_lot_id"])
    if yarn_lot is not None and yarn_lot["status"] == "DYEING":
        yarn_lot["status"] = "GREIGE"
        yarn_lot["greige_yards_available"] = round2(yarn_lot["greige_yards_available"] + record["requested_yards"])
        touch(yarn_lot)

    return success_object(serialize_dye_lot(record))
