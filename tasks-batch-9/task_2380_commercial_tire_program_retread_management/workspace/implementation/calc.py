"""The calculation engine (SCAFFOLD §1.3 / PRD §2.7, §3.x). Rounding order is pinned."""

from decimal import Decimal

import derive
from db import db
from util import add_months, dec, floor_int, round_half_up, round_half_up_int, utc_date

# ---- casing_credit_accrual
DEFAULT_CASING_CREDIT_CENTS = 12000
GRADE_FACTOR = {"A": Decimal("1.00"), "B": Decimal("0.70"), "C": Decimal("0.40"), "REJECT": Decimal("0")}
RETREAD_DECAY_PCT = Decimal("0.15")
MIN_CREDIT_FACTOR = Decimal("0.25")
PRODUCTION_VERIFIED_UPLIFT_PCT = Decimal("0.10")

# ---- road_service_response_and_pricing
BASE_SERVICE_CALL_CENTS = 9500
LABOR_RATE_CENTS_PER_HOUR = 11000
MILEAGE_CENTS_PER_MILE = 285
EMERGENCY_MULTIPLIER = Decimal("1.75")
AFTER_HOURS_MULTIPLIER = Decimal("1.35")
MAX_EMERGENCY_SURCHARGE_CENTS = 40000
SLA_MISS_CREDIT_PCT = Decimal("0.20")
NORMAL_PRIORITY_GRACE_MINUTES = 60

# ---- cross_location_invoice_rollup
CREDIT_CAP_PCT = Decimal("0.25")

# ---- retread_slot_feasibility
MIN_JOB_MINUTES = 60
MAX_JOB_MINUTES = 480

# ---- retread_warranty
WARRANTY_MONTHS = {"A": 36, "B": 24, "C": 12}
RETREAD_COUNT_PENALTY_MONTHS = 6
MIN_WARRANTY_MONTHS = 6

# ---- technician_dispatch_selector
CERT_RANK = {"TIA_CERTIFIED": 3, "LEVEL_2": 2, "LEVEL_1": 1}


# ================================================================ credit accrual

def _base_credit_rate(fleet_account_id, anchor_date):
    agreement = derive.active_agreement_on(fleet_account_id, anchor_date)
    if agreement is not None:
        return agreement["casing_credit_rate_cents"]
    return DEFAULT_CASING_CREDIT_CENTS


def _raw_credit(base_cents, grade, retread_count):
    grade_factor = GRADE_FACTOR.get(grade, Decimal("0"))
    decay_factor = max(MIN_CREDIT_FACTOR, Decimal(1) - RETREAD_DECAY_PCT * dec(retread_count))
    return dec(base_cents) * grade_factor * decay_factor


def credit_provisional_cents(fleet_account_id, grade, retread_count, anchor_date):
    """Variant GRADE_PROVISIONAL: one round_half_up on the final product."""
    base = _base_credit_rate(fleet_account_id, anchor_date)
    return round_half_up_int(_raw_credit(base, grade, retread_count))


def credit_production_verified_cents(fleet_account_id, grade, retread_count, anchor_date):
    base = _base_credit_rate(fleet_account_id, anchor_date)
    raw = _raw_credit(base, grade, retread_count)
    return round_half_up_int(raw * (Decimal(1) + PRODUCTION_VERIFIED_UPLIFT_PCT))


def credit_adjustment_delta_cents(fleet_account_id, grade, retread_count, anchor_date):
    """The ADJUSTMENT posted at retread completion is the DELTA, never the gross."""
    verified = credit_production_verified_cents(fleet_account_id, grade, retread_count, anchor_date)
    provisional = credit_provisional_cents(fleet_account_id, grade, retread_count, anchor_date)
    return verified - provisional


# ================================================================ survey finding

def survey_finding(pressure_psi, tread_depth_32nds, policy):
    deviation = round_half_up(
        abs(dec(pressure_psi) - dec(policy["target_pressure_psi"])) / dec(policy["target_pressure_psi"]),
        4,
    )
    if tread_depth_32nds < policy["min_tread_depth_32nds"]:
        code = "TREAD_BELOW_MIN"
    elif tread_depth_32nds <= policy["pull_point_32nds"]:
        code = "TREAD_AT_PULL_POINT"
    elif deviation >= dec(policy["pressure_tolerance_pct"]):
        code = "PRESSURE_DEVIATION"
    else:
        code = "COMPLIANT"
    return deviation, code, code in ("TREAD_BELOW_MIN", "TREAD_AT_PULL_POINT")


# ================================================================ road service

def response_metrics(call, location, agreement):
    base_minutes = location["road_service_response_minutes_committed"]
    if call["priority"] == "EMERGENCY":
        if agreement is not None:
            committed = min(base_minutes, agreement["emergency_response_minutes"])
        else:
            committed = base_minutes
    else:
        committed = base_minutes + NORMAL_PRIORITY_GRACE_MINUTES
    seconds = (call["arrived_at_dt"] - call["reported_at_dt"]).total_seconds()
    actual = floor_int(dec(seconds) / dec(60))
    return committed, actual, actual <= committed


def call_pricing(call, agreement):
    if call["priority"] == "EMERGENCY" and agreement is not None:
        labor_rate = agreement["emergency_labor_rate_cents_per_hour"]
    else:
        labor_rate = LABOR_RATE_CENTS_PER_HOUR
    labor_cents = round_half_up_int(dec(labor_rate) * dec(call["labor_hours"]))
    mileage_cents = MILEAGE_CENTS_PER_MILE * call["dispatch_miles"]
    hour = call["dispatched_at_dt"].hour
    after_hours = hour < 6 or hour >= 18
    multiplier = max(
        EMERGENCY_MULTIPLIER if call["priority"] == "EMERGENCY" else Decimal("1.00"),
        AFTER_HOURS_MULTIPLIER if after_hours else Decimal("1.00"),
    )
    surcharge_cents = min(
        MAX_EMERGENCY_SURCHARGE_CENTS,
        round_half_up_int(
            (multiplier - Decimal("1.00"))
            * dec(BASE_SERVICE_CALL_CENTS + labor_cents + mileage_cents)
        ),
    )
    gross_cents = BASE_SERVICE_CALL_CENTS + labor_cents + mileage_cents + surcharge_cents
    if call["sla_met"] is False:
        sla_credit_cents = round_half_up_int(SLA_MISS_CREDIT_PCT * dec(gross_cents))
    else:
        sla_credit_cents = 0
    return gross_cents, sla_credit_cents, gross_cents - sla_credit_cents


# ================================================================ invoice rollup

def billable_lines(fleet_account_id, period_start, period_end):
    rows = [
        call for call in db.road_service_calls.values()
        if call["fleet_account_id"] == fleet_account_id
        and call["dispatch_status"] == "COMPLETED"
        and call["billing_status"] == "UNBILLED"
        and call["closed_at_dt"] is not None
        and period_start <= utc_date(call["closed_at_dt"]) <= period_end
    ]
    rows.sort(key=lambda c: (c["closed_at_dt"], c["created_at"], c["_seq"]))
    return rows


def rollup(lines, agreement, balance_cents):
    discount_pct = dec(agreement["tier_discount_pct"]) if agreement is not None else Decimal("0")
    subtotal_cents = 0
    discount_cents = 0
    for line in lines:
        subtotal_cents += line["invoice_total_cents"]
        discount_cents += round_half_up_int(dec(line["invoice_total_cents"]) * discount_pct)
    net_before_credit_cents = subtotal_cents - discount_cents
    credit_cap_cents = floor_int(CREDIT_CAP_PCT * dec(net_before_credit_cents))
    credit_applied_cents = min(balance_cents, credit_cap_cents)
    if credit_applied_cents < 0:
        credit_applied_cents = 0
    return {
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "net_before_credit_cents": net_before_credit_cents,
        "credit_applied_cents": credit_applied_cents,
        "total_cents": net_before_credit_cents - credit_applied_cents,
    }


# ================================================================ slot feasibility

def slot_conflict(line, start_dt, end_dt, exclude_job_id=None):
    cooldown_minutes = line["cure_cooldown_minutes"]
    for job in db.retread_jobs.values():
        if job["retread_line_id"] != line["id"]:
            continue
        if job["status"] not in derive.OCCUPYING_JOB_STATUSES:
            continue
        if exclude_job_id is not None and job["id"] == exclude_job_id:
            continue
        occupied_start = job["scheduled_start_at_dt"]
        occupied_end = job["scheduled_end_at_dt"] + _minutes(cooldown_minutes)
        if start_dt < occupied_end and occupied_start < end_dt:
            return True
    return False


def _minutes(count):
    from datetime import timedelta

    return timedelta(minutes=count)


# ================================================================ agreement windows

def agreement_window_conflict(agreement):
    for other in db.national_agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other["fleet_account_id"] != agreement["fleet_account_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if (
            agreement["effective_from_d"] <= other["effective_to_d"]
            and other["effective_from_d"] <= agreement["effective_to_d"]
        ):
            return True
    return False


# ================================================================ warranty

def warranty(grade, retread_count, completed_dt):
    base_months = WARRANTY_MONTHS.get(grade, WARRANTY_MONTHS["C"])
    months = max(MIN_WARRANTY_MONTHS, base_months - RETREAD_COUNT_PENALTY_MONTHS * retread_count)
    expires_on = add_months(utc_date(completed_dt), months)
    return months, expires_on.isoformat()


# ================================================================ dispatch selector

def select_technician(call):
    candidates = [
        tech for tech in db.technicians.values()
        if tech["service_location_id"] == call["service_location_id"]
        and tech["status"] == "AVAILABLE"
        and (call["priority"] != "EMERGENCY" or tech["certification_level"] == "TIA_CERTIFIED")
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda t: (
            -CERT_RANK[t["certification_level"]],
            derive.technician_completed_call_count(t["id"]),
            t["created_at"],
            t["_seq"],
        )
    )
    return candidates[0]


# ================================================================ cost per mile

def cost_per_mile(fleet_account_id, variant, brand=None, position=None, vehicle_type=None):
    excluded = 0
    groups = {}
    for asset in db.tire_assets.values():
        if asset["fleet_account_id"] != fleet_account_id:
            continue
        if asset["status"] not in derive.CPM_ASSET_STATUSES:
            continue
        if brand is not None and asset["brand"] != brand:
            continue
        if position is not None and asset["position"] != position:
            continue
        vehicle = db.vehicles.get(asset["vehicle_id"]) if asset["vehicle_id"] else None
        asset_vehicle_type = vehicle["vehicle_type"] if vehicle else None
        if vehicle_type is not None and asset_vehicle_type != vehicle_type:
            continue

        survey = derive.latest_survey(asset["id"])
        baseline = asset["tread_depth_at_mount_32nds"]
        if survey is None or baseline is None or asset["odometer_at_mount"] is None:
            excluded += 1
            continue
        miles_run = max(0, survey["odometer_miles"] - asset["odometer_at_mount"])
        tread_consumed = baseline - survey["tread_depth_32nds"]
        if miles_run == 0 or tread_consumed <= 0:
            excluded += 1
            continue

        denominator = miles_run
        projected = None
        if variant == "FORWARD_PROJECTED":
            policy = derive.find_policy(fleet_account_id, asset["position"])
            if policy is None:
                excluded += 1
                continue
            usable_32nds = baseline - policy["pull_point_32nds"]
            wear_rate = dec(tread_consumed) / dec(miles_run)
            projected = floor_int(dec(usable_32nds) / wear_rate)
            denominator = projected

        key = (asset["brand"], asset["position"], asset_vehicle_type)
        group = groups.setdefault(
            key,
            {
                "brand": asset["brand"],
                "position": asset["position"],
                "vehicle_type": asset_vehicle_type,
                "asset_count": 0,
                "cost_basis_cents": 0,
                "miles_run": 0,
                "projected_life_miles": 0,
            },
        )
        group["asset_count"] += 1
        group["cost_basis_cents"] += asset["cost_basis_cents"]
        group["miles_run"] += miles_run
        if projected is not None:
            group["projected_life_miles"] += projected
        group.setdefault("_denominator", 0)
        group["_denominator"] += denominator

    out = []
    for key in sorted(groups, key=lambda k: (k[0] or "", k[1] or "", k[2] or "")):
        group = groups[key]
        denominator = group.pop("_denominator", 0)
        if denominator <= 0:
            continue
        cpm = round_half_up(dec(group["cost_basis_cents"]) / dec(denominator), 4)
        cpm_out = float(cpm)
        row = {
            "brand": group["brand"],
            "position": group["position"],
            "vehicle_type": group["vehicle_type"],
            "asset_count": group["asset_count"],
            "cost_basis_cents": group["cost_basis_cents"],
            "total_cost_basis_cents": group["cost_basis_cents"],
            "miles_run": group["miles_run"],
            "total_miles_run": group["miles_run"],
            "projected_life_miles": group["projected_life_miles"],
            "total_projected_life_miles": group["projected_life_miles"],
            "cpm_cents": cpm_out,
            "cost_per_mile_cents": cpm_out,
        }
        out.append(row)

    return {
        "variant": variant,
        "group_count": len(out),
        "excluded_asset_count": excluded,
        "groups": out,
    }
