"""WaterTestResult endpoints (record/confirm/void, trending lists) and the
CorrectiveAction workflow (approve/apply/decline) with the escalation cascade,
segregation of duties, OCC, and the inventory-depletion auto-draft."""

from flask import Blueprint, g

import errors
import calc
from calc import (lsi_provisional, lsi_finalized, classify_lsi, recompute_posture,
                  recompute_station, accepted_design_of, depletion_alert,
                  ESCALATION_THRESHOLD, round_places)
from db import db, create_entity, touch
from helpers import list_response, account_of_result, account_of_action, query_filter
from response import success_object, success_list
from serializers import water_test_result as ser_result, corrective_action as ser_action
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership, paginate)
from routes_routes import maybe_complete_route

bp = Blueprint("results", __name__)


def target_station_of(asset_id):
    """The corrective-action target station: the asset's first-created station."""
    stations = [s for s in db["feed_stations"].values() if s["asset_id"] == asset_id]
    if not stations:
        return None
    stations.sort(key=lambda s: s["_seq"])
    return stations[0]


def _range_status(asset, vals):
    design = accepted_design_of(asset["id"])
    if design is None:
        return "IN_RANGE"
    if not (design["ph_min"] <= vals["ph"] <= design["ph_max"]):
        return "OUT_OF_RANGE"
    if vals["conductivity_umhos"] > design["conductivity_max_umhos"]:
        return "OUT_OF_RANGE"
    if vals["inhibitor_residual_ppm"] < design["inhibitor_target_ppm"]:
        return "OUT_OF_RANGE"
    return "IN_RANGE"


@bp.route("/wt/route-stops/<stopId>/water-test-results", methods=["POST"])
def record_result(stopId):
    stop = resolve("route_stops", stopId)
    body = get_body()
    # Tier 4: body FK asset_id resolves (after the path stop).
    asset = resolve_body_fk(body, "asset_id", "assets")
    vals = validate_shape(body, [
        ("asset_id", "str", True),
        ("ph", "num", True),
        ("conductivity_umhos", "int", True),
        ("calcium_ppm", "num", True),
        ("alkalinity_ppm", "num", True),
        ("temperature_f", "num", True),
        ("inhibitor_residual_ppm", "num", True),
    ])
    # Tier 6: stop must be ARRIVED.
    if stop["status"] != "ARRIVED":
        raise errors.invalid_state("Stop must be ARRIVED to record a result")
    # Tier 7 cross-entity gates: asset IN_SERVICE, then posture not FROZEN.
    if asset["status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_ASSET_NOT_IN_SERVICE, 409,
                              "Recording a result requires the asset to be IN_SERVICE")
    if asset["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_ASSET_FROZEN, 409,
                              "Asset posture FROZEN gates result recording")
    # Tier 10 field constraints.
    if not (0 <= vals["ph"] <= 14):
        raise errors.field_constraint("ph must lie between 0 and 14 inclusive")
    if vals["conductivity_umhos"] <= 0:
        raise errors.field_constraint("conductivity_umhos must be a positive whole number")
    if vals["calcium_ppm"] <= 0:
        raise errors.field_constraint("calcium_ppm must be > 0")
    if vals["alkalinity_ppm"] <= 0:
        raise errors.field_constraint("alkalinity_ppm must be > 0")
    if not (32 < vals["temperature_f"] < 212):
        raise errors.field_constraint("temperature_f must lie strictly between 32 and 212")
    if vals["inhibitor_residual_ppm"] < 0:
        raise errors.field_constraint("inhibitor_residual_ppm must be >= 0")
    # Tier 13 referential integrity: payload asset must equal the stop's asset.
    if vals["asset_id"] != stop["asset_id"]:
        raise errors.ApiError(errors.ERR_ASSET_MISMATCH, 409,
                              "Result asset_id must equal the stop's asset_id")

    lsi = lsi_provisional(vals["ph"], vals["conductivity_umhos"], vals["calcium_ppm"],
                          vals["alkalinity_ppm"], vals["temperature_f"])
    range_status = _range_status(asset, vals)
    ent = create_entity("water_test_results", {
        "stop_id": stop["id"],
        "asset_id": asset["id"],
        "ph": vals["ph"],
        "conductivity_umhos": vals["conductivity_umhos"],
        "calcium_ppm": vals["calcium_ppm"],
        "alkalinity_ppm": vals["alkalinity_ppm"],
        "temperature_f": vals["temperature_f"],
        "inhibitor_residual_ppm": vals["inhibitor_residual_ppm"],
        "lab_tds_ppm": None,
        "lsi_provisional": lsi,
        "lsi_final": None,
        "classification": classify_lsi(lsi),
        "range_status": range_status,
        "status": "RECORDED",
    }, common=False)

    # Stop advances ARRIVED -> SAMPLED; route may auto-complete.
    stop["status"] = "SAMPLED"
    touch(stop)
    maybe_complete_route(db["test_routes"][stop["route_id"]])

    # Escalation cascade.
    if range_status == "OUT_OF_RANGE":
        asset["consecutive_out_of_range_count"] += 1
        touch(asset)
        if asset["consecutive_out_of_range_count"] >= ESCALATION_THRESHOLD:
            create_entity("corrective_actions", {
                "asset_id": asset["id"],
                "triggering_result_id": ent["id"],
                "recorded_by_user_id": g.user_id,
                "setpoint_delta_ml_per_min": None,
                "rationale": None,
                "status": "PENDING",
            })
        recompute_posture(asset)
    else:
        if asset["consecutive_out_of_range_count"] != 0:
            asset["consecutive_out_of_range_count"] = 0
            touch(asset)
        recompute_posture(asset)
    return success_object(ser_result(ent), 201)


@bp.route("/wt/route-stops/<stopId>/water-test-results", methods=["GET"])
def list_results_of_stop(stopId):
    stop = db["route_stops"].get(stopId)
    if stop is not None:
        check_cc_ownership(g.user_id, g.role, account_of_stop_result_parent(stop))
    stop = resolve("route_stops", stopId)
    items = [r for r in db["water_test_results"].values() if r["stop_id"] == stop["id"]]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([ser_result(r) for r in page], limit, offset, total)


def account_of_stop_result_parent(stop):
    route = db["test_routes"].get(stop["route_id"])
    return route["account_id"] if route else None


@bp.route("/wt/water-test-results", methods=["GET"])
def list_results():
    user = (g.role, g.user_id)
    items = list(db["water_test_results"].values())
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [r for r in items if r["asset_id"] == asset_id]
    range_status = query_filter("range_status")
    if range_status is not None:
        items = [r for r in items if r["range_status"] == range_status]
    return list_response(items, ser_result, account_of_result, user)


@bp.route("/wt/water-test-results/<resultId>", methods=["GET"])
def get_result(resultId):
    ent = db["water_test_results"].get(resultId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, account_of_result(ent))
    ent = resolve("water_test_results", resultId)
    return success_object(ser_result(ent), 200)


@bp.route("/wt/water-test-results/<resultId>/confirm", methods=["POST"])
def confirm_result(resultId):
    ent = resolve("water_test_results", resultId)
    body = get_body()
    if "lab_tds_ppm" not in body or body["lab_tds_ppm"] is None:
        raise errors.ApiError(errors.ERR_LAB_TDS_REQUIRED, 422,
                              "Confirm requires lab_tds_ppm")
    vals = validate_shape(body, [("lab_tds_ppm", "num", True)])
    if ent["status"] != "RECORDED":
        raise errors.invalid_state("Result must be RECORDED to confirm")
    lsi = lsi_finalized(ent["ph"], vals["lab_tds_ppm"], ent["calcium_ppm"],
                        ent["alkalinity_ppm"], ent["temperature_f"])
    ent["lab_tds_ppm"] = vals["lab_tds_ppm"]
    ent["lsi_final"] = lsi
    ent["classification"] = classify_lsi(lsi)
    ent["status"] = "CONFIRMED"
    return success_object(ser_result(ent), 200)


@bp.route("/wt/water-test-results/<resultId>/void", methods=["POST"])
def void_result(resultId):
    ent = resolve("water_test_results", resultId)
    get_body()
    if ent["status"] != "RECORDED":
        raise errors.invalid_state("Result must be RECORDED to void")
    ent["status"] = "VOIDED"
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None and ent["range_status"] == "OUT_OF_RANGE":
        asset["consecutive_out_of_range_count"] = max(0, asset["consecutive_out_of_range_count"] - 1)
        touch(asset)
        recompute_posture(asset)
    for action in db["corrective_actions"].values():
        if action["triggering_result_id"] == ent["id"] and action["status"] == "PENDING":
            action["status"] = "DECLINED"
            touch(action)
    return success_object(ser_result(ent), 200)


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------

@bp.route("/wt/corrective-actions", methods=["GET"])
def list_actions():
    user = (g.role, g.user_id)
    items = list(db["corrective_actions"].values())
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [a for a in items if a["asset_id"] == asset_id]
    status = query_filter("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    trig = query_filter("triggering_result_id")
    if trig is not None:
        items = [a for a in items if a["triggering_result_id"] == trig]
    return list_response(items, ser_action, account_of_action, user)


@bp.route("/wt/corrective-actions/<actionId>", methods=["GET"])
def get_action(actionId):
    ent = db["corrective_actions"].get(actionId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, account_of_action(ent))
    ent = resolve("corrective_actions", actionId)
    return success_object(ser_action(ent), 200)


@bp.route("/wt/corrective-actions/<actionId>/approve", methods=["POST"])
def approve_action(actionId):
    ent = resolve("corrective_actions", actionId)
    body = get_body()
    vals = validate_shape(body, [
        ("setpoint_delta_ml_per_min", "num", True),
        ("rationale", "str", True),
        ("expected_feed_station_version", "int", True),
    ])
    # Tier 6: transition legality.
    if ent["status"] != "PENDING":
        raise errors.invalid_state("Action must be PENDING to approve")
    asset = db["assets"].get(ent["asset_id"])
    # Tier 7: posture FROZEN gate.
    if asset is not None and asset["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_ASSET_FROZEN, 409,
                              "Asset posture FROZEN gates corrective approval")
    # Tier 8: Legionella safety gate.
    if any(p["asset_id"] == ent["asset_id"] and p["status"] == "SUSPENDED"
           for p in db["legionella_plans"].values()):
        raise errors.ApiError(errors.ERR_LEGIONELLA_PLAN_SUSPENDED, 409,
                              "Asset's Legionella plan is SUSPENDED")
    # Tier 9: segregation of duties.
    if g.user_id == ent["recorded_by_user_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Approver must differ from the recording chemist")
    # Tier 15: OCC on the target feed station.
    station = target_station_of(ent["asset_id"])
    if station is None:
        raise errors.not_found("No feed station exists for this asset")
    if vals["expected_feed_station_version"] != station["version"]:
        raise errors.stale_version()
    ent["setpoint_delta_ml_per_min"] = vals["setpoint_delta_ml_per_min"]
    ent["rationale"] = vals["rationale"]
    ent["status"] = "APPROVED"
    touch(ent)
    return success_object(ser_action(ent), 200)


@bp.route("/wt/corrective-actions/<actionId>/apply", methods=["POST"])
def apply_action(actionId):
    ent = resolve("corrective_actions", actionId)
    get_body()
    if ent["status"] != "APPROVED":
        raise errors.invalid_state("Action must be APPROVED to apply")
    station = target_station_of(ent["asset_id"])
    if station is None:
        raise errors.not_found("No feed station exists for this asset")
    asset = db["assets"].get(ent["asset_id"])
    # Clamp: min(capacity_cap, max(0, setpoint + delta)), stored 4dp half-up.
    new_setpoint = round_places(
        min(station["capacity_cap_ml_per_min"],
            max(0.0, station["setpoint_ml_per_min"] + ent["setpoint_delta_ml_per_min"])), 4)
    if station["setpoint_ml_per_min"] != new_setpoint:
        station["setpoint_ml_per_min"] = new_setpoint
        touch(station)
    recompute_station(station)
    if asset is not None:
        if asset["consecutive_out_of_range_count"] != 0:
            asset["consecutive_out_of_range_count"] = 0
            touch(asset)
        recompute_posture(asset)
    ent["status"] = "APPLIED"
    touch(ent)
    # Depletion alert: projection within 14 days (inclusive) auto-drafts a
    # replenishment order for exactly one container.
    if depletion_alert(station):
        product = db["products"].get(station["product_id"])
        if product is not None and asset is not None:
            create_entity("delivery_orders", {
                "account_id": asset["account_id"],
                "station_id": station["id"],
                "quantity_gal": product["container_size_gal"],
                "scheduled_for": None,
                "delivered_gal": None,
                "returned_residual_gal": None,
                "auto_drafted": True,
                "status": "DRAFT",
            })
    return success_object(ser_action(ent), 200)


@bp.route("/wt/corrective-actions/<actionId>/decline", methods=["POST"])
def decline_action(actionId):
    ent = resolve("corrective_actions", actionId)
    get_body()
    if ent["status"] != "PENDING":
        raise errors.invalid_state("Action must be PENDING to decline")
    if g.user_id == ent["recorded_by_user_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Decliner must differ from the recording chemist")
    ent["status"] = "DECLINED"
    touch(ent)
    return success_object(ser_action(ent), 200)
