"""Reference layer: payers, grant pools, sites, zones, recipients, couriers, windows."""

from flask import Blueprint

import middleware
import response
import serializers
import validation as v
from constants import (
    CONSENT_STATUSES,
    COURIER_MODES,
    COURIER_TARGET_STATUSES,
    LICENSE_TIERS,
    PAYER_TYPES,
)
from db import db, new_row, touch
from errors import api_error
from middleware import (
    ROLE_COURIER,
    ROLE_OPS,
    ROLE_PATIENT,
    ROLE_PHARMACY,
    ROLE_PLAN,
    require_roles,
)
from services import couriers as courier_service
from services import derive
from services import hipaa
from services import windows as window_service

bp = Blueprint("reference", __name__)


# --------------------------------------------------------------------------
# health plans
# --------------------------------------------------------------------------
@bp.post("/health-plans")
@require_roles(ROLE_OPS)
def create_health_plan():
    body = v.json_body()
    name = v.string_field(body, "name", min_len=1, max_len=120)
    payer_type = v.enum_field(body, "payer_type", PAYER_TYPES)
    pct = v.decimal_field(body, "member_cost_share_pct", minimum=0, maximum=1,
                          max_places=2)

    row = new_row()
    row["name"] = name
    row["payer_type"] = payer_type
    row["member_cost_share_pct"] = pct
    db.health_plans[row["id"]] = row
    return response.single(serializers.health_plan(row), 201)


# --------------------------------------------------------------------------
# grant pools
# --------------------------------------------------------------------------
@bp.post("/plan-grants")
@require_roles(ROLE_PLAN, ROLE_OPS)
def create_plan_grant():
    # Rung 6 runs on the claimed owner before the body is strictly validated.
    claimed = v.soft_body().get("health_plan_id")
    if isinstance(claimed, str):
        middleware.guard_plan_scope(claimed)

    body = v.json_body()
    health_plan_id = v.string_field(body, "health_plan_id")
    benefit_year = v.int_field(body, "benefit_year", minimum=2026, maximum=2030)
    budget = v.int_field(body, "grant_budget_cents", minimum=1)
    cap = v.int_field(body, "per_delivery_cap_cents", minimum=0)

    if health_plan_id not in db.health_plans:
        raise api_error("ERR_REFERENCE_NOT_FOUND", "The referenced health plan does not exist.")

    row = new_row()
    row["health_plan_id"] = health_plan_id
    row["benefit_year"] = benefit_year
    row["grant_budget_cents"] = budget
    row["per_delivery_cap_cents"] = cap
    db.plan_grants[row["id"]] = row
    return response.single(serializers.plan_grant(row), 201)


# --------------------------------------------------------------------------
# dispensing sites
# --------------------------------------------------------------------------
@bp.post("/pharmacies")
@require_roles(ROLE_OPS)
def create_pharmacy():
    body = v.json_body()
    name = v.string_field(body, "name", min_len=1, max_len=120)
    state_code = v.string_field(body, "state_code", min_len=2, max_len=2)
    if not v.STATE_RE.match(state_code):
        raise v.invalid("Field 'state_code' must be two uppercase letters.")
    cold = v.bool_field(body, "cold_chain_certified", default=False)
    tier = v.enum_field(body, "controlled_license_tier", LICENSE_TIERS,
                        required=False, default="NONE")
    return_minutes = v.int_field(body, "return_window_minutes", required=False,
                                 default=240, minimum=60, maximum=1440)

    row = new_row()
    row["name"] = name
    row["state_code"] = state_code
    row["cold_chain_certified"] = cold
    row["controlled_license_tier"] = tier
    row["return_window_minutes"] = return_minutes
    db.pharmacies[row["id"]] = row
    return response.single(serializers.pharmacy(row), 201)


# --------------------------------------------------------------------------
# zones
# --------------------------------------------------------------------------
@bp.post("/delivery-zones")
@require_roles(ROLE_OPS)
def create_delivery_zone():
    body = v.json_body()
    zone_code = v.string_field(body, "zone_code", min_len=2, max_len=12)
    distance = v.decimal_field(body, "distance_band_miles", minimum="0.1",
                               maximum="60.0", max_places=1)
    base_fee = v.int_field(body, "base_fee_cents", minimum=0)
    per_mile = v.int_field(body, "per_mile_cents", minimum=0)
    cold_pack = v.int_field(body, "cold_pack_fee_cents", minimum=0)
    controlled_fee = v.int_field(body, "controlled_handling_fee_cents", minimum=0)
    after_hours = v.int_field(body, "after_hours_fee_cents", minimum=0)
    cold_supported = v.bool_field(body, "cold_chain_supported", default=True)
    controlled_allowed = v.bool_field(body, "controlled_delivery_allowed", default=True)

    if any(z["zone_code"] == zone_code for z in db.delivery_zones.values()):
        raise v.invalid("Field 'zone_code' must be unique across all zones.")

    row = new_row()
    row["zone_code"] = zone_code
    row["distance_band_miles"] = distance
    row["base_fee_cents"] = base_fee
    row["per_mile_cents"] = per_mile
    row["cold_pack_fee_cents"] = cold_pack
    row["controlled_handling_fee_cents"] = controlled_fee
    row["after_hours_fee_cents"] = after_hours
    row["cold_chain_supported"] = cold_supported
    row["controlled_delivery_allowed"] = controlled_allowed
    db.delivery_zones[row["id"]] = row
    return response.single(serializers.delivery_zone(row), 201)


def zone_by_code(zone_code):
    for zone in db.delivery_zones.values():
        if zone["zone_code"] == zone_code:
            return zone
    return None


# --------------------------------------------------------------------------
# recipients
# --------------------------------------------------------------------------
@bp.post("/patients")
@require_roles(ROLE_PHARMACY, ROLE_OPS)
def create_patient():
    body = v.json_body()
    full_name = v.string_field(body, "full_name", min_len=1, max_len=120)
    dob = v.date_field(body, "date_of_birth")
    phone_last4 = v.string_field(body, "phone_last4", min_len=4, max_len=4)
    if not v.DIGITS4_RE.match(phone_last4):
        raise v.invalid("Field 'phone_last4' must be exactly four digits.")
    address_line = v.string_field(body, "address_line", min_len=1, max_len=200)
    zone_code = v.string_field(body, "zone_code", min_len=2, max_len=12)
    consent = v.enum_field(body, "hipaa_consent_status", CONSENT_STATUSES,
                           required=False, default="GRANTED")

    if zone_by_code(zone_code) is None:
        raise api_error("ERR_REFERENCE_NOT_FOUND", "The referenced delivery zone does not exist.")

    row = new_row()
    row["full_name"] = full_name
    row["date_of_birth"] = dob
    row["phone_last4"] = phone_last4
    row["address_line"] = address_line
    row["zone_code"] = zone_code
    row["hipaa_consent_status"] = consent
    row["masked_name"] = hipaa.masked_name(full_name)
    db.patients[row["id"]] = row
    return response.single(serializers.patient(row), 201)


@bp.post("/patients/<patient_id>/consent")
@require_roles(ROLE_PATIENT, ROLE_PHARMACY)
def record_consent(patient_id):
    if middleware.actor_role() == ROLE_PATIENT and patient_id != middleware.actor_id():
        raise api_error("ERR_PATIENT_SCOPE_VIOLATION")
    patient = db.patients.get(patient_id)
    if patient is None:
        raise api_error("ERR_PATIENT_NOT_FOUND")

    body = v.json_body()
    status = v.enum_field(body, "hipaa_consent_status", CONSENT_STATUSES)

    patient["hipaa_consent_status"] = status
    touch(patient)
    return response.single(serializers.patient(patient), 200)


# --------------------------------------------------------------------------
# couriers
# --------------------------------------------------------------------------
@bp.post("/couriers")
@require_roles(ROLE_OPS)
def create_courier():
    body = v.json_body()
    display_name = v.string_field(body, "display_name", min_len=1, max_len=80)
    mode = v.enum_field(body, "mode", COURIER_MODES)
    zone_codes = v.string_array_field(body, "served_zone_codes", min_items=1,
                                      min_len=2, max_len=12)
    cold = v.bool_field(body, "cold_chain_equipped", default=False)
    controlled = v.bool_field(body, "controlled_certified", default=False)

    for code in zone_codes:
        if zone_by_code(code) is None:
            raise api_error("ERR_REFERENCE_NOT_FOUND",
                            "The referenced delivery zone '%s' does not exist." % code)

    row = new_row()
    row["display_name"] = display_name
    row["mode"] = mode
    row["served_zone_codes"] = zone_codes
    row["cold_chain_equipped"] = cold
    row["controlled_certified"] = controlled
    row["status"] = "OFFLINE"
    db.couriers[row["id"]] = row
    return response.single(serializers.courier(row), 201)


@bp.post("/couriers/<courier_id>/status")
@require_roles(ROLE_COURIER, ROLE_OPS)
def change_courier_status(courier_id):
    middleware.guard_courier_scope(courier_id)
    courier = db.couriers.get(courier_id)
    if courier is None:
        raise api_error("ERR_COURIER_NOT_FOUND")

    body = v.json_body()
    target = v.enum_field(body, "target_status", COURIER_TARGET_STATUSES)

    current = courier["status"]
    role = middleware.actor_role()
    illegal = api_error("ERR_INVALID_COURIER_STATE",
                        "A courier may not move from %s to %s." % (current, target))

    if target == "AVAILABLE":
        if current == "OFFLINE":
            pass
        elif current == "SUSPENDED":
            # Only NetworkOps lifts a suspension.
            if role != ROLE_OPS:
                raise illegal
        else:
            raise illegal
    elif target == "OFFLINE":
        if current != "AVAILABLE":
            raise illegal
        if derive.active_delivery_count(courier) > 0:
            raise api_error("ERR_INVALID_COURIER_STATE",
                            "A courier holding accepted work may not go offline.")
    else:  # SUSPENDED
        if role != ROLE_OPS:
            raise illegal
        if current not in {"OFFLINE", "AVAILABLE", "ON_ROUTE"}:
            raise illegal

    courier["status"] = target
    touch(courier)
    return response.single(serializers.courier(courier), 200)


# --------------------------------------------------------------------------
# capacity windows
# --------------------------------------------------------------------------
@bp.post("/delivery-windows")
@require_roles(ROLE_OPS)
def create_delivery_window():
    body = v.json_body()
    zone_id = v.string_field(body, "zone_id")
    courier_mode = v.enum_field(body, "courier_mode", COURIER_MODES)
    window_start = v.datetime_field(body, "window_start")
    window_end = v.datetime_field(body, "window_end")
    capacity = v.int_field(body, "capacity_slots", minimum=1)

    if zone_id not in db.delivery_zones:
        raise api_error("ERR_REFERENCE_NOT_FOUND", "The referenced delivery zone does not exist.")

    if not window_start < window_end:
        raise api_error("ERR_WINDOW_INTERVAL_INVALID",
                        "window_start must be strictly earlier than window_end.")
    window_service.assert_no_overlap(zone_id, courier_mode, window_start, window_end)

    row = new_row()
    row["zone_id"] = zone_id
    row["courier_mode"] = courier_mode
    row["window_start"] = window_start
    row["window_end"] = window_end
    row["capacity_slots"] = capacity
    row["is_after_hours"] = window_service.is_after_hours(window_start)
    row["status"] = "OPEN"
    db.delivery_windows[row["id"]] = row
    return response.single(serializers.delivery_window(row), 201)


# Kept importable for the routing modules.
select_courier = courier_service.select_courier
