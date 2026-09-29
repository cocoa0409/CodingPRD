"""The eleven calculation rules (PRD 3 / SCAFFOLD calculations).

Every quantity that has a declared precision is computed with Decimal and
rounded exactly where the specification says to round -- never earlier and
never later.
"""
import math
from datetime import timedelta
from decimal import Decimal

from core import (
    add_days,
    add_months,
    days_in_month,
    db,
    dec,
    money,
    now,
    order_key,
    parse_date_value,
    parse_datetime,
    round_half_up,
    today,
)

GRACE_DAYS = 15
DOC_SCORE_PASS = Decimal("85.00")
HOLD_THRESHOLD = Decimal("70.00")

# ---------------------------------------------------------------- 1. groups
SHORT_VALIDITY_TYPES = ("RESTING_ROOM_AIR", "EXERCISE")


def qualifying_group_determination(test_type, spo2, pao2, desat_minutes,
                                  cor_pulmonale, tested_at):
    validity_days = 30 if test_type in SHORT_VALIDITY_TYPES else 90
    tested = parse_datetime(tested_at) if isinstance(tested_at, str) else tested_at
    expires_at = tested + timedelta(days=validity_days)

    group_i_threshold = (spo2 is not None and spo2 <= 88) or (
        pao2 is not None and pao2 <= 55
    )
    if test_type == "NOCTURNAL_OVERNIGHT_OXIMETRY":
        group_i = group_i_threshold and (desat_minutes or 0) >= 5
    else:
        group_i = group_i_threshold

    if group_i:
        group = "GROUP_I"
    else:
        borderline = (spo2 is not None and spo2 == 89) or (
            pao2 is not None and 56 <= pao2 <= 59
        )
        if borderline and bool(cor_pulmonale):
            group = "GROUP_II"
        else:
            group = "NON_QUALIFYING"
    return group, validity_days, expires_at


def test_is_stale(test):
    """True when the study's validity plus the 15 day grace has lapsed."""
    limit = add_days(test["test_validity_expires_at"], GRACE_DAYS)
    return now() > limit


# ------------------------------------------------- 2. documentation scoring
GROUP_COMPONENT = {"GROUP_I": Decimal(30), "GROUP_II": Decimal(24)}


def documentation_score(cmn, test, patient):
    group = test["qualifying_group"] if test else "NON_QUALIFYING"
    c_group = GROUP_COMPONENT.get(group, Decimal(0))

    expires = test["test_validity_expires_at"] if test else None
    clock = now()
    if expires is not None and clock <= expires:
        c_currency = Decimal(20)
    elif expires is not None and clock <= add_days(expires, GRACE_DAYS):
        c_currency = Decimal(10)
    else:
        c_currency = Decimal(0)

    hours = min(int(cmn["hours_per_day"]), 24)
    c_usage = Decimal(15) * Decimal(hours) / Decimal(24)

    c_narrative = Decimal(20) * Decimal(int(cmn["narrative_element_count"])) / Decimal(3)

    if cmn["portable_prescribed"] and patient["mobility_profile"] == "HOMEBOUND":
        c_portable = Decimal(0)
    else:
        c_portable = Decimal(10)

    c_duration = Decimal(5) if int(cmn["length_of_need_months"]) >= 12 else Decimal(0)

    total = c_group + c_currency + c_usage + c_narrative + c_portable + c_duration
    return round_half_up(total, 2)


# --------------------------------------------------- 11. recertification due
RECERT_INTERVAL = {"GROUP_I": 12, "GROUP_II": 3}


def recert_due_date(initial_date, qualifying_group, length_of_need_months):
    interval = RECERT_INTERVAL.get(qualifying_group, 12)
    months = min(interval, int(length_of_need_months))
    return add_months(initial_date, months)


# ------------------------------------------------------ 3. monthly allowable
CLASS_BASE_CENTS = {
    "STATIONARY_CONCENTRATOR": Decimal(7752),
    "PORTABLE_CONCENTRATOR": Decimal(7340),
    "LIQUID_RESERVOIR": Decimal(9315),
    "LIQUID_PORTABLE": Decimal(8420),
    "COMPRESSED_CYLINDER": Decimal(2520),
}
ROLE_FACTOR = {
    "PRIMARY_STATIONARY": Decimal("1.00"),
    "PORTABLE": Decimal("0.25"),
    "BACKUP": Decimal("0.10"),
}
BASIS_FACTOR = {
    "COMPETITIVE_BID_SINGLE_PAYMENT": Decimal("0.7358"),
    "FEE_SCHEDULE_ADJUSTED": Decimal("0.9050"),
    "CASH": Decimal("1.0000"),
}
SEQUESTRATION = Decimal("0.98")


def contract_placements(contract_id):
    return [p for p in db.placements.values() if p["contract_id"] == contract_id]


def monthly_allowable_cents(contract):
    """Round every placement line to whole cents, then sum the integers."""
    total = 0
    lines = sorted(
        [p for p in contract_placements(contract["id"]) if p["status"] == "PLACED"],
        key=order_key,
    )
    for placement in lines:
        unit = db.equipment_units.get(placement["equipment_unit_id"])
        if unit is None:
            continue
        base = CLASS_BASE_CENTS.get(unit["equipment_class"], Decimal(0))
        role_factor = ROLE_FACTOR.get(placement["role"], Decimal(0))
        basis_factor = BASIS_FACTOR.get(contract["pricing_basis"], Decimal(0))
        line = base * role_factor * basis_factor * SEQUESTRATION
        total += money(line)
    return total


def prorated_amount_cents(contract, year, month):
    total_days = days_in_month(year, month)
    days = total_days
    from core import month_str

    if contract.get("first_service_month") == month_str(year, month):
        started = contract.get("_service_started_at")
        if started is not None:
            days = total_days - started.day + 1
    if days < 0:
        days = 0
    allowable = dec(contract["monthly_allowable_cents"])
    amount = money(allowable * Decimal(days) / Decimal(total_days))
    return amount, days, total_days


# ----------------------------------------------------- 4. cap month position
SERVICE_BASIS_PRICING = ("COMPETITIVE_BID_SINGLE_PAYMENT",)


def cap_positions(contract, candidate_month, posted_months=None):
    """Return (service_basis, paid_basis, effective, months_remaining)."""
    if posted_months is None:
        posted_months = contract["posted_months"]
    first = contract.get("first_service_month")
    if candidate_month is None or first is None:
        service_basis = 0
    else:
        c_year, c_month = int(candidate_month[:4]), int(candidate_month[5:7])
        f_year, f_month = int(first[:4]), int(first[5:7])
        service_basis = 12 * (c_year - f_year) + (c_month - f_month) + 1
    if candidate_month is None:
        paid_basis = 0
    else:
        earlier = [
            m for m in posted_months if m["service_month"] < candidate_month
        ]
        paid_basis = len(earlier) + 1
    if contract["pricing_basis"] in SERVICE_BASIS_PRICING:
        effective = service_basis
    else:
        effective = paid_basis
    remaining = max(0, int(contract["cap_month_limit"]) - effective)
    return service_basis, paid_basis, effective, remaining


def cap_candidate_month(contract):
    if contract.get("last_posted_service_month"):
        return contract["last_posted_service_month"]
    return contract.get("first_service_month")


# ------------------------------------------------------- 5. safety risk score
def patient_contracts(patient_id):
    return [c for c in db.contracts.values() if c["patient_id"] == patient_id]


def reference_setup_stop(patient_id):
    contract_ids = set(c["id"] for c in patient_contracts(patient_id))
    candidates = [
        s
        for s in db.route_stops.values()
        if s["stop_type"] == "SETUP_DELIVERY"
        and s["status"] == "COMPLETED"
        and s["contract_id"] in contract_ids
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda s: (
            -(s["completed_at"].timestamp() if s.get("completed_at") else 0),
            s["created_at"],
            s["_seq"],
        )
    )
    return candidates[0]


def active_cmn(patient_id):
    for cmn in db.cmns.values():
        if cmn["patient_id"] == patient_id and cmn["status"] == "ACTIVE":
            return cmn
    return None


def flow_factor(lpm):
    if lpm is None:
        return Decimal(0)
    value = dec(lpm)
    if value <= Decimal("2.0"):
        return Decimal(0)
    if value <= Decimal("4.0"):
        return Decimal(20)
    if value <= Decimal("6.0"):
        return Decimal(40)
    if value <= Decimal("9.0"):
        return Decimal(60)
    return Decimal(100)


def risk_factors(patient):
    stop = reference_setup_stop(patient["id"])
    if stop is None:
        factor_smoking = Decimal(0)
        factor_electrical = Decimal(0)
        factor_teachback = Decimal(0)
    else:
        factor_smoking = Decimal(100) if stop.get("smoking_in_home") else Decimal(0)
        factor_electrical = (
            Decimal(100) if stop.get("electrical_pass") is False else Decimal(0)
        )
        score = stop.get("patient_teachback_score")
        if score is None:
            factor_teachback = Decimal(0)
        else:
            factor_teachback = (Decimal(5) - Decimal(int(score))) * Decimal(20)

    cmn = active_cmn(patient["id"])
    factor_flow = flow_factor(cmn["prescribed_lpm"] if cmn else None)

    malfunctions = sum(
        int(c["malfunction_count"])
        for c in patient_contracts(patient["id"])
        if c["billing_status"] != "CLOSED"
    )
    factor_incident = min(Decimal(100), Decimal(30) * Decimal(malfunctions))

    return {
        "factor_smoking": factor_smoking,
        "factor_electrical": factor_electrical,
        "factor_teachback": factor_teachback,
        "factor_flow": factor_flow,
        "factor_incident": factor_incident,
    }


def initial_assessment_score(factors):
    total = (
        Decimal("0.30") * factors["factor_smoking"]
        + Decimal("0.15") * factors["factor_electrical"]
        + Decimal("0.15") * factors["factor_teachback"]
        + Decimal("0.30") * factors["factor_flow"]
        + Decimal("0.10") * factors["factor_incident"]
    )
    return round_half_up(total, 2)


def ongoing_surveillance_score(factors):
    values = [
        factors["factor_smoking"],
        factors["factor_electrical"],
        factors["factor_teachback"],
        factors["factor_flow"],
        factors["factor_incident"],
    ]
    highest = max(values)
    nonzero = len([v for v in values if v > 0])
    total = highest + Decimal(5) * Decimal(max(0, nonzero - 1))
    return round_half_up(min(Decimal("100.00"), total), 2)


# -------------------------------------------------------- 6. unit selection
REQUIRED_CLASSES = {
    "PRIMARY_STATIONARY": ("STATIONARY_CONCENTRATOR", "LIQUID_RESERVOIR"),
    "PORTABLE": ("PORTABLE_CONCENTRATOR", "LIQUID_PORTABLE", "COMPRESSED_CYLINDER"),
    "BACKUP": ("COMPRESSED_CYLINDER", "STATIONARY_CONCENTRATOR"),
}
LIQUID_CLASSES = ("LIQUID_RESERVOIR", "LIQUID_PORTABLE")


def model_under_recall(model_code):
    for notice in db.recall_notices.values():
        if notice["model_code"] == model_code and notice["status"] in (
            "OPEN",
            "IN_REMEDIATION",
        ):
            return True
    return False


def select_equipment_unit(branch, role, prescribed_lpm):
    prescribed = dec(prescribed_lpm)
    clock_date = today()
    eligible = []
    for unit in db.equipment_units.values():
        if unit["branch_id"] != branch["id"]:
            continue
        if unit["status"] != "IN_STOCK":
            continue
        if unit["equipment_class"] not in REQUIRED_CLASSES.get(role, ()):
            continue
        if dec(unit["max_continuous_lpm"]) < prescribed:
            continue
        pm_due = unit["next_pm_due_date"]
        if isinstance(pm_due, str):
            pm_due = parse_date_value(pm_due)
        if pm_due is None or pm_due < clock_date:
            continue
        if model_under_recall(unit["model_code"]):
            continue
        if unit["equipment_class"] in LIQUID_CLASSES and not branch[
            "liquid_oxygen_certified"
        ]:
            continue
        eligible.append((unit, pm_due))
    if not eligible:
        return None
    eligible.sort(
        key=lambda item: (
            dec(item[0]["max_continuous_lpm"]) - prescribed,
            -item[1].toordinal(),
            item[0]["created_at"],
            item[0]["_seq"],
        )
    )
    return eligible[0][0]


# ------------------------------------------------- 7. travel supply waterfall
CYLINDER_CAPACITY_LITERS = 680
CYLINDER_SURCHARGE_THRESHOLD = 6
CYLINDER_AUTH_LIMIT = 12


def travel_supply(depart, ret, patient_altitude, destination_altitude,
                  prescribed_lpm, hours_per_day):
    trip_hours = int((ret - depart).total_seconds() // 3600)

    gain = max(0, int(destination_altitude) - int(patient_altitude))
    steps = int(math.ceil(gain / 1000.0))
    altitude_factor = round_half_up(Decimal(1) + Decimal("0.03") * Decimal(steps), 2)
    if altitude_factor > Decimal("1.30"):
        altitude_factor = Decimal("1.30")

    effective_lpm = round_half_up(dec(prescribed_lpm) * altitude_factor, 2)

    day_cap = int(hours_per_day) * int(math.ceil(trip_hours / 24.0))
    usable_hours = min(trip_hours, day_cap)
    base_liters = int(
        (effective_lpm * Decimal(60) * Decimal(usable_hours)).to_integral_value(
            rounding="ROUND_FLOOR"
        )
    )

    if trip_hours <= 24:
        reserve_pct = Decimal("0.20")
    elif trip_hours <= 72:
        reserve_pct = Decimal("0.35")
    else:
        reserve_pct = Decimal("0.50")
    reserve_liters = int(
        (Decimal(base_liters) * reserve_pct).to_integral_value(
            rounding="ROUND_FLOOR"
        )
    )

    required_liters = base_liters + reserve_liters
    cylinders_raw = int(
        math.ceil(required_liters / float(CYLINDER_CAPACITY_LITERS))
    )
    surcharge = 1 if cylinders_raw >= CYLINDER_SURCHARGE_THRESHOLD else 0
    authorized = cylinders_raw + surcharge

    return {
        "trip_hours": trip_hours,
        "altitude_factor": altitude_factor,
        "effective_lpm": effective_lpm,
        "base_liters": base_liters,
        "reserve_liters": reserve_liters,
        "required_liters": required_liters,
        "cylinders_raw": cylinders_raw,
        "handling_surcharge_cylinders": surcharge,
        "supply_cylinders_authorized": authorized,
    }


# --------------------------------------------------- 8. route litre commitment
PORTABLE_REFILL_LITERS = 1085


def stop_liters_committed(stop_type, cylinders_requested):
    if stop_type == "PORTABLE_REFILL":
        return PORTABLE_REFILL_LITERS
    if stop_type in ("SETUP_DELIVERY", "TANK_EXCHANGE", "MAINTENANCE_SWAP"):
        return int(cylinders_requested or 0) * CYLINDER_CAPACITY_LITERS
    return 0


# --------------------------------------------------- 9. recall remediation
RECALL_WINDOW_DAYS = {"CLASS_I": 5, "CLASS_II": 30, "CLASS_III": 90}


def recall_deadline(issued_at, severity):
    return issued_at + timedelta(days=RECALL_WINDOW_DAYS.get(severity, 90))


def remediated_unit_count(notice):
    count = 0
    for unit in db.equipment_units.values():
        if unit["model_code"] != notice["model_code"]:
            continue
        stamp = unit.get("recall_remediated_at")
        if stamp is None:
            continue
        if stamp >= notice["issued_at"]:
            count += 1
    return count


# --------------------------------------------------- 10. malfunction severity
TIER_1_SYMPTOMS = ("NO_FLOW", "LOW_PURITY")
TIER_2_SYMPTOMS = ("ALARM_CONTINUOUS", "POWER_FAILURE")


def malfunction_severity_tier(symptom, oxygen_gap_minutes):
    gap = int(oxygen_gap_minutes or 0)
    if symptom in TIER_1_SYMPTOMS or gap >= 60:
        return "TIER_1"
    if symptom in TIER_2_SYMPTOMS or gap >= 15:
        return "TIER_2"
    return "TIER_3"
