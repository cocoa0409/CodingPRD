"""Trunk group provisioning and traffic measurement (PRD 3.3, 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (CARRIER_REPRESENTATIVE, INTERCONNECTION_MANAGER, NETWORK_PLANNER,
                  PLATFORM_ADMIN, authenticate, carrier_of_measurement,
                  carrier_of_trunk_group, scope_check, scope_filter)
from constants import (CLLI_PATTERN, DIRECTIONS, LATA_PATTERN, POI_TYPES,
                       TRAFFIC_TYPES)
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_agreement, get_measurement, get_trunk_group
from services.sizing import (evaluate_measurement, poi_provisioned_trunks,
                             recompute_posture)
from store import base_record, db, now, ordered, touch

bp = Blueprint("trunks", __name__)

ZERO2 = Decimal("0.00")


@bp.post("/trunk-groups")
def request_trunk_group():
    authenticate((NETWORK_PLANNER,))
    payload = v.body()
    agreement_id = v.string(payload, "agreement_id")
    serial = v.string(payload, "trunk_group_serial")
    clli = v.string(payload, "poi_clli_code", pattern=CLLI_PATTERN)
    lata = v.string(payload, "lata_code", pattern=LATA_PATTERN)
    poi_type = v.enum(payload, "poi_type", POI_TYPES)
    direction = v.enum(payload, "direction", DIRECTIONS)
    traffic_type = v.enum(payload, "traffic_type", TRAFFIC_TYPES)
    forecast = v.number(payload, "forecast_busy_hour_ccs", 2, gt=0)
    horizon = v.integer(payload, "forecast_horizon_quarters", ge=1, le=8)

    agreement = get_agreement(agreement_id)

    if traffic_type == "TRANSIT" and not agreement["transit_traffic_allowed"]:
        raise ApiError("ERR_TRANSIT_TRAFFIC_NOT_PERMITTED",
                       "the agreement does not permit transit traffic")

    for existing in db.trunk_groups.values():
        if (existing["agreement_id"] == agreement["id"]
                and existing["trunk_group_serial"] == serial):
            raise ApiError("ERR_DUPLICATE_TRUNK_GROUP_SERIAL",
                           "trunk_group_serial is already used on this agreement")

    trunk_group = base_record()
    trunk_group.update({
        "agreement_id": agreement["id"],
        "trunk_group_serial": serial,
        "poi_clli_code": clli,
        "lata_code": lata,
        "poi_type": poi_type,
        "direction": direction,
        "traffic_type": traffic_type,
        "service_status": "REQUESTED",
        "augment_status": "NONE",
        "provisioned_trunks": 0,
        "forecast_busy_hour_ccs": forecast,
        "forecast_horizon_quarters": horizon,
        "latest_blocking_pct": ZERO2,
        "required_trunks": 0,
        "open_augment_order_count": 0,
        "in_service_at": None,
    })
    db.trunk_groups[trunk_group["id"]] = trunk_group
    return object_response(trunk_group, 201)


@bp.get("/trunk-groups/<trunk_group_id>")
def read_trunk_group(trunk_group_id):
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, INTERCONNECTION_MANAGER,
                          CARRIER_REPRESENTATIVE))
    trunk_group = get_trunk_group(trunk_group_id)
    scope_check(actor, carrier_of_trunk_group(trunk_group))
    return object_response(trunk_group)


def _filter_trunk_groups(rows, args):
    agreement_id = args.get("agreement_id")
    if agreement_id:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    clli = args.get("poi_clli_code")
    if clli:
        rows = [r for r in rows if r["poi_clli_code"] == clli]
    service_status = args.get("service_status")
    if service_status:
        rows = [r for r in rows if r["service_status"] == service_status]
    augment_status = args.get("augment_status")
    if augment_status:
        rows = [r for r in rows if r["augment_status"] == augment_status]
    return rows


@bp.get("/trunk-groups")
def list_trunk_groups():
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, INTERCONNECTION_MANAGER,
                          CARRIER_REPRESENTATIVE))
    rows = _filter_trunk_groups(ordered(db.trunk_groups), request.args)
    rows = scope_filter(actor, rows, carrier_of_trunk_group)
    return paginate(rows, request.args, lambda r: r)


@bp.get("/agreements/<agreement_id>/trunk-groups")
def list_agreement_trunk_groups(agreement_id):
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, INTERCONNECTION_MANAGER,
                          CARRIER_REPRESENTATIVE))
    agreement = get_agreement(agreement_id)
    scope_check(actor, agreement["carrier_id"])
    rows = [tg for tg in ordered(db.trunk_groups)
            if tg["agreement_id"] == agreement["id"]]
    rows = _filter_trunk_groups(rows, request.args)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/trunk-groups/<trunk_group_id>/provision")
def provision_trunk_group(trunk_group_id):
    authenticate((NETWORK_PLANNER,))
    trunk_group = get_trunk_group(trunk_group_id)
    payload = v.body()
    quantity = v.integer(payload, "provisioned_trunks", gt=0, multiple_of=24)

    agreement = db.agreements.get(trunk_group["agreement_id"])
    if trunk_group["service_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_TRUNK_GROUP_STATE",
                       "only a REQUESTED trunk group may be provisioned")

    committed = poi_provisioned_trunks(agreement["id"], trunk_group["poi_clli_code"],
                                      exclude_id=trunk_group["id"])
    if committed + quantity > agreement["poi_facility_capacity_trunks"]:
        raise ApiError("ERR_POI_CAPACITY_EXCEEDED",
                       "the POI facility ceiling would be exceeded")

    trunk_group["provisioned_trunks"] = quantity
    trunk_group["service_status"] = "PROVISIONED"
    touch(trunk_group)
    return object_response(trunk_group)


@bp.post("/trunk-groups/<trunk_group_id>/activate")
def activate_trunk_group(trunk_group_id):
    authenticate((NETWORK_PLANNER,))
    trunk_group = get_trunk_group(trunk_group_id)
    agreement = db.agreements.get(trunk_group["agreement_id"])

    if trunk_group["service_status"] != "PROVISIONED":
        raise ApiError("ERR_INVALID_TRUNK_GROUP_STATE",
                       "only a PROVISIONED trunk group may be activated")
    if agreement["status"] != "EFFECTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_EFFECTIVE",
                       "the parent agreement is not EFFECTIVE")

    trunk_group["service_status"] = "IN_SERVICE"
    trunk_group["in_service_at"] = now()
    touch(trunk_group)
    agreement["total_in_service_trunks"] += trunk_group["provisioned_trunks"]
    touch(agreement)
    return object_response(trunk_group)


@bp.post("/trunk-groups/<trunk_group_id>/disconnect")
def disconnect_trunk_group(trunk_group_id):
    authenticate((NETWORK_PLANNER,))
    trunk_group = get_trunk_group(trunk_group_id)

    if trunk_group["service_status"] != "DISCONNECT_PENDING":
        raise ApiError("ERR_INVALID_TRUNK_GROUP_STATE",
                       "only a DISCONNECT_PENDING trunk group may be disconnected")
    if trunk_group["open_augment_order_count"] != 0:
        raise ApiError("ERR_INVALID_TRUNK_GROUP_STATE",
                       "augment work remains open on this trunk group")

    trunk_group["service_status"] = "DISCONNECTED"
    trunk_group["provisioned_trunks"] = 0
    touch(trunk_group)
    return object_response(trunk_group)


@bp.post("/trunk-groups/<trunk_group_id>/traffic-measurements")
def record_measurement(trunk_group_id):
    actor = authenticate((NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    trunk_group = get_trunk_group(trunk_group_id)
    payload = v.body()
    period_start = v.timestamp(payload, "measurement_period_start")
    period_end = v.timestamp(payload, "measurement_period_end")
    offered_calls = v.integer(payload, "offered_calls", ge=0)
    blocked_calls = v.integer(payload, "blocked_calls", ge=0)
    if blocked_calls > offered_calls:
        v.bad("blocked_calls must not exceed offered_calls")
    busy_hour_ccs = v.number(payload, "busy_hour_ccs", 2, ge=0)

    agreement = db.agreements.get(trunk_group["agreement_id"])
    scope_check(actor, agreement["carrier_id"])

    if trunk_group["service_status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_TRUNK_GROUP_STATE",
                       "traffic may only be measured on an IN_SERVICE trunk group")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_MEASUREMENT_PERIOD",
                       "measurement_period_end must be strictly after measurement_period_start")

    pct, required, outcome, requested = evaluate_measurement(
        trunk_group, agreement, offered_calls, blocked_calls, busy_hour_ccs)

    measurement = base_record(with_version=False)
    measurement.update({
        "trunk_group_id": trunk_group["id"],
        "measurement_period_start": period_start,
        "measurement_period_end": period_end,
        "offered_calls": offered_calls,
        "blocked_calls": blocked_calls,
        "busy_hour_ccs": busy_hour_ccs,
        "blocking_pct": pct,
        "required_trunks_at_measurement": required,
        "augment_triggered": outcome == "AUGMENT_ORDERED",
    })
    db.measurements[measurement["id"]] = measurement

    trunk_group["latest_blocking_pct"] = pct
    trunk_group["required_trunks"] = required

    agreement_changed = False
    if outcome == "GROOMING_REVIEW":
        trunk_group["augment_status"] = "GROOMING_REVIEW"
    elif outcome == "AUGMENT_BLOCKED":
        trunk_group["augment_status"] = "AUGMENT_BLOCKED"
        agreement_changed = recompute_posture(agreement) or agreement_changed
    elif outcome == "AUGMENT_ORDERED":
        order = base_record()
        order.update({
            "trunk_group_id": trunk_group["id"],
            "triggering_measurement_id": measurement["id"],
            "requested_additional_trunks": requested,
            "required_trunks_target": required,
            "status": "PENDING",
            "committed_due_date": None,
            "install_window_start": None,
            "install_window_end": None,
            "installed_trunks": None,
            "rejection_reason": None,
            "reversed_at": None,
        })
        db.augment_orders[order["id"]] = order
        trunk_group["augment_status"] = "AUGMENT_ORDERED"
        trunk_group["open_augment_order_count"] += 1
        agreement["poi_augment_pending_count"] += 1
        recompute_posture(agreement)
        agreement_changed = True

    touch(trunk_group)
    if agreement_changed:
        touch(agreement)
    return object_response(measurement, 201)


@bp.get("/trunk-groups/<trunk_group_id>/traffic-measurements")
def list_trunk_group_measurements(trunk_group_id):
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    trunk_group = get_trunk_group(trunk_group_id)
    scope_check(actor, carrier_of_trunk_group(trunk_group))
    rows = [m for m in ordered(db.measurements)
            if m["trunk_group_id"] == trunk_group["id"]]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/traffic-measurements/<measurement_id>")
def read_measurement(measurement_id):
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    measurement = get_measurement(measurement_id)
    scope_check(actor, carrier_of_measurement(measurement))
    return object_response(measurement)


@bp.get("/traffic-measurements")
def list_measurements():
    actor = authenticate((PLATFORM_ADMIN, NETWORK_PLANNER, CARRIER_REPRESENTATIVE))
    rows = ordered(db.measurements)
    trunk_group_id = request.args.get("trunk_group_id")
    if trunk_group_id:
        rows = [r for r in rows if r["trunk_group_id"] == trunk_group_id]
    triggered = v.query_bool(request.args, "augment_triggered")
    if triggered is not None:
        rows = [r for r in rows if r["augment_triggered"] is triggered]
    rows = scope_filter(actor, rows, carrier_of_measurement)
    return paginate(rows, request.args, lambda r: r)
