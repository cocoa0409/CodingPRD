"""Population rules, matching runs, build records, affected rows, outreach."""
from flask import Blueprint, g, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import (base_record, clock_now, fmt_instant, parse_date, sorted_records,
                store, touch)
from errors import ApiError
from response import collection, single

bp = Blueprint("population", __name__)


# --------------------------------------------------------------------------
# population rules
# --------------------------------------------------------------------------
@bp.post("/recall-campaigns/<campaign_id>/population-rules")
@require_roles("SafetyEngineer")
def create_rule(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    inclusion_mode = v.req_enum(payload, "inclusion_mode", v.INCLUSION_MODES)
    plant_code = v.req_str(payload, "plant_code", min_len=1, max_len=8)
    model_code = v.req_str(payload, "model_code", min_len=1, max_len=8)
    model_year = v.req_int(payload, "model_year", minimum=1980, maximum=2100)
    start_raw, start_date = v.req_date_str(payload, "production_start_date")
    end_raw, end_date = v.req_date_str(payload, "production_end_date")
    low = v.req_int(payload, "part_number_low")
    high = v.req_int(payload, "part_number_high")

    h.assert_campaign_writable(campaign)

    if not start_date < end_date:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    if inclusion_mode == "INCLUDE":
        for other in calc.campaign_rules(campaign["id"], "INCLUDE"):
            if (other["plant_code"] != plant_code
                    or other["model_code"] != model_code
                    or other["model_year"] != model_year):
                continue
            o_start = parse_date(other["production_start_date"])
            o_end = parse_date(other["production_end_date"])
            if start_date < o_end and o_start < end_date:
                raise ApiError("ERR_POPULATION_RULE_OVERLAP")

    rule = base_record()
    rule.update({
        "campaign_id": campaign["id"],
        "inclusion_mode": inclusion_mode,
        "plant_code": plant_code,
        "model_code": model_code,
        "model_year": model_year,
        "production_start_date": start_raw,
        "production_end_date": end_raw,
        "part_number_low": low,
        "part_number_high": high,
    })
    store.population_rules[rule["id"]] = rule
    return single(h.rule_out(rule), 201)


@bp.get("/recall-campaigns/<campaign_id>/population-rules")
@require_roles(*ALL_ROLES)
def list_rules(campaign_id):
    campaign = h.get_campaign(campaign_id)
    inclusion_mode = v.query_enum("inclusion_mode", v.INCLUSION_MODES)
    rows = calc.campaign_rules(campaign["id"], inclusion_mode)
    return collection(rows, h.rule_out)


# --------------------------------------------------------------------------
# population run
# --------------------------------------------------------------------------
@bp.post("/recall-campaigns/<campaign_id>/population-runs")
@require_roles("SafetyEngineer", "RecallOperationsManager")
def population_run(campaign_id):
    campaign = h.get_campaign(campaign_id)
    h.assert_campaign_writable(campaign)

    include_rules = calc.include_rules_ordered(campaign["id"])
    exclude_rules = calc.campaign_rules(campaign["id"], "EXCLUDE")

    existing = {}
    for av in calc.campaign_avs(campaign["id"]):
        existing[av["vehicle_id"]] = av

    matched_count = 0
    excluded_count = 0
    removed_count = 0

    for vehicle in calc.vehicles_ordered():
        hit = None
        for rule in include_rules:
            if calc.rule_matches(rule, vehicle):
                hit = rule
                break
        if hit is None:
            continue
        if any(calc.rule_matches(x, vehicle) for x in exclude_rules):
            excluded_count += 1
            continue
        if vehicle["id"] in existing:
            continue
        removed = vehicle["sale_status"] in ("SCRAPPED", "EXPORTED")
        av = base_record()
        av.update({
            "campaign_id": campaign["id"],
            "vehicle_id": vehicle["id"],
            "matched_by_rule_id": hit["id"],
            "notification_wave_id": None,
            "dealer_id": None,
            "remedy_status": "REMOVED_FROM_POPULATION" if removed else "UNREPAIRED",
            "notice_count": 0,
            "last_notice_type": None,
            "last_notice_date": None,
            "scheduled_repair_date": None,
            "requires_renotification": False,
        })
        store.affected_vehicles[av["id"]] = av
        existing[vehicle["id"]] = av
        matched_count += 1
        if removed:
            removed_count += 1

    for av in sorted_records(calc.campaign_avs(campaign["id"])):
        if av["remedy_status"] == "REMOVED_FROM_POPULATION":
            continue
        vehicle = store.vehicles.get(av["vehicle_id"])
        if vehicle is None or not any(calc.rule_matches(r, vehicle) for r in include_rules):
            av["remedy_status"] = "REMOVED_FROM_POPULATION"
            touch(av)
            removed_count += 1

    touch(campaign)
    buckets = calc.population_buckets(campaign["id"])
    data = {
        "matched_count": matched_count,
        "excluded_count": excluded_count,
        "removed_count": removed_count,
        "affected_vehicle_count": buckets["total"],
        "recall_population_count": buckets["recall_population"],
    }
    return single(data, 201)


# --------------------------------------------------------------------------
# build records
# --------------------------------------------------------------------------
@bp.post("/vehicles")
@require_roles("RecallOperationsManager")
def create_vehicle():
    payload = v.body()
    vin = v.req_str(payload, "vin", min_len=17, max_len=17)
    plant_code = v.req_str(payload, "plant_code")
    model_code = v.req_str(payload, "model_code")
    model_year = v.req_int(payload, "model_year")
    production_raw, _ = v.req_date_str(payload, "production_date")
    suspect_part_number = v.req_int(payload, "suspect_part_number")
    region_code = v.req_enum(payload, "region_code", v.REGION_CODES)
    sale_status = v.opt_enum(payload, "sale_status", v.SALE_STATUSES, "SOLD")
    in_service_raw, _ = v.opt_date_str(payload, "in_service_date")
    owner_name = v.opt_str(payload, "owner_name")
    owner_address_valid = v.opt_bool(payload, "owner_address_valid", True)

    for row in store.vehicles.values():
        if row["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN")

    vehicle = base_record()
    vehicle.update({
        "vin": vin,
        "plant_code": plant_code,
        "model_code": model_code,
        "model_year": model_year,
        "production_date": production_raw,
        "suspect_part_number": suspect_part_number,
        "in_service_date": in_service_raw,
        "region_code": region_code,
        "sale_status": sale_status,
        "owner_name": owner_name,
        "owner_address_valid": owner_address_valid,
        "stop_sale_hold": False,
    })
    store.vehicles[vehicle["id"]] = vehicle
    return single(h.vehicle_out(vehicle), 201)


@bp.get("/vehicles/<vehicle_id>")
@require_roles(*ALL_ROLES)
def get_vehicle(vehicle_id):
    return single(h.vehicle_out(h.get_vehicle(vehicle_id)))


@bp.patch("/vehicles/<vehicle_id>")
@require_roles("RecallOperationsManager")
def patch_vehicle(vehicle_id):
    vehicle = h.get_vehicle(vehicle_id)
    payload = v.body()
    sale_status = v.opt_enum(payload, "sale_status", v.SALE_STATUSES)
    owner_name = v.opt_str(payload, "owner_name")
    owner_address_valid = v.opt_bool(payload, "owner_address_valid")
    region_code = v.opt_enum(payload, "region_code", v.REGION_CODES)

    if sale_status == "SOLD" and vehicle["stop_sale_hold"]:
        raise ApiError("ERR_STOP_SALE_ACTIVE")

    if sale_status is not None:
        vehicle["sale_status"] = sale_status
    if owner_name is not None:
        vehicle["owner_name"] = owner_name
    if owner_address_valid is not None:
        vehicle["owner_address_valid"] = owner_address_valid
    if region_code is not None:
        vehicle["region_code"] = region_code

    if sale_status in ("SCRAPPED", "EXPORTED"):
        for av in sorted_records([a for a in store.affected_vehicles.values()
                                  if a["vehicle_id"] == vehicle["id"]]):
            if av["remedy_status"] == "REMOVED_FROM_POPULATION":
                continue
            av["remedy_status"] = "REMOVED_FROM_POPULATION"
            touch(av)
            touch(store.campaigns.get(av["campaign_id"]))

    touch(vehicle)
    return single(h.vehicle_out(vehicle))


# --------------------------------------------------------------------------
# affected vehicles
# --------------------------------------------------------------------------
@bp.get("/affected-vehicles")
@require_roles(*ALL_ROLES)
def list_affected():
    remedy_status = v.query_enum("remedy_status", v.AV_REMEDY_STATUSES)
    filters = {
        "campaign_id": request.args.get("campaign_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "matched_by_rule_id": request.args.get("matched_by_rule_id"),
        "notification_wave_id": request.args.get("notification_wave_id"),
        "dealer_id": request.args.get("dealer_id"),
    }
    rows = list(store.affected_vehicles.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if remedy_status is not None:
        rows = [r for r in rows if r["remedy_status"] == remedy_status]
    return collection(sorted_records(rows), h.av_out)


@bp.get("/affected-vehicles/<av_id>")
@require_roles(*ALL_ROLES)
def get_affected(av_id):
    return single(h.av_out(h.get_av(av_id)))


@bp.post("/affected-vehicles/<av_id>/schedule")
@require_roles("DealerServiceManager")
def schedule_repair(av_id):
    av = h.get_av(av_id)
    payload = v.body()
    dealer_id = v.req_str(payload, "dealer_id")
    repair_raw, _ = v.req_date_str(payload, "scheduled_repair_date")

    dealer = h.get_dealer(dealer_id)

    if dealer_id != g.user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")
    if av["dealer_id"] is not None and av["dealer_id"] != g.user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")

    campaign = store.campaigns.get(av["campaign_id"])
    h.assert_campaign_writable(campaign)
    if av["remedy_status"] not in ("UNREPAIRED", "UNREACHABLE"):
        raise ApiError("ERR_VEHICLE_NOT_REPAIRABLE")
    vehicle = store.vehicles.get(av["vehicle_id"])
    if vehicle is not None and vehicle["sale_status"] in ("SCRAPPED", "EXPORTED"):
        raise ApiError("ERR_VEHICLE_NOT_REPAIRABLE")

    h.assert_remedy_available(campaign)

    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED")

    av["dealer_id"] = dealer_id
    av["scheduled_repair_date"] = repair_raw
    av["remedy_status"] = "SCHEDULED"
    touch(av)
    touch(campaign)
    return single(h.av_out(av))


# --------------------------------------------------------------------------
# outreach attempts
# --------------------------------------------------------------------------
_UNSUCCESSFUL = ("NO_RESPONSE", "BAD_ADDRESS", "OWNER_REFUSED")


@bp.post("/affected-vehicles/<av_id>/outreach-attempts")
@require_roles("RecallOperationsManager")
def create_outreach(av_id):
    av = h.get_av(av_id)
    payload = v.body()
    channel = v.req_enum(payload, "channel", v.OUTREACH_CHANNELS)
    outcome = v.req_enum(payload, "outcome", v.OUTREACH_OUTCOMES)
    note = v.opt_str(payload, "note")

    campaign = store.campaigns.get(av["campaign_id"])
    h.assert_campaign_writable(campaign)

    prior = calc.outreach_for(av["id"])
    attempt = base_record(with_version=False)
    attempt.update({
        "affected_vehicle_id": av["id"],
        "channel": channel,
        "outcome": outcome,
        "attempt_number": len(prior) + 1,
        "attempted_at": fmt_instant(clock_now()),
        "note": note,
    })
    store.outreach_attempts[attempt["id"]] = attempt

    attempts = prior + [attempt]
    status_before = av["remedy_status"]
    vehicle = store.vehicles.get(av["vehicle_id"])

    if outcome == "BAD_ADDRESS" and vehicle is not None and vehicle["owner_address_valid"]:
        vehicle["owner_address_valid"] = False
        touch(vehicle)

    if status_before == "UNREPAIRED":
        unreachable = outcome == "BAD_ADDRESS"
        if not unreachable and len(attempts) >= calc.UNREACHABLE_ATTEMPT_THRESHOLD:
            unreachable = all(a["outcome"] in _UNSUCCESSFUL for a in attempts)
        if unreachable:
            av["remedy_status"] = "UNREACHABLE"
    elif status_before == "SCHEDULED" and outcome == "OWNER_REFUSED":
        av["remedy_status"] = "UNREPAIRED"
        av["dealer_id"] = None
        av["scheduled_repair_date"] = None

    touch(av)
    touch(campaign)
    return single(h.outreach_out(attempt), 201)


@bp.get("/affected-vehicles/<av_id>/outreach-attempts")
@require_roles(*ALL_ROLES)
def list_outreach(av_id):
    av = h.get_av(av_id)
    outcome = v.query_enum("outcome", v.OUTREACH_OUTCOMES)
    rows = calc.outreach_for(av["id"])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return collection(rows, h.outreach_out)
