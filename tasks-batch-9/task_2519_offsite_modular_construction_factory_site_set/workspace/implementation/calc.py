"""The eleven calculation rules of §1.3, as pure functions.

Every money value is integer cents and every rounding step is ROUND_HALF_UP.
Aggregating derivations that need to walk the store live in services.py; this
module holds only arithmetic that can be expressed over its arguments.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---- module_envelope_class ------------------------------------------------
STANDARD_MAX_WIDTH_IN = 192
STANDARD_MAX_HEIGHT_IN = 162
STANDARD_MAX_WEIGHT_LB = 80000
OVERWIDTH_MAX_WIDTH_IN = 216
OVERWIDTH_MAX_HEIGHT_IN = 174
OVERWIDTH_MAX_WEIGHT_LB = 120000

# ---- line_slot_schedule ---------------------------------------------------
TAKT_CONGESTION_PENALTY_MINUTES = 5

# ---- crane_pick_feasibility ----------------------------------------------
MAX_UTILIZATION_PCT = 85
WIND_DERATE_GUST_MPH = 20
WIND_DERATE_FACTOR = Decimal("0.75")

# ---- shipment_permit_fee_and_escort --------------------------------------
BASE_STATE_PERMIT_FEE_CENTS = 25000
CLASS_MULTIPLIER = {"STANDARD": 0, "OVERWIDTH": 2, "SUPERLOAD": 5}
ENVELOPE_ORDER = {"STANDARD": 0, "OVERWIDTH": 1, "SUPERLOAD": 2}

# ---- defect_responsibility_allocation ------------------------------------
PHASE_PRESUMPTION = {
    "FACTORY": Decimal("100.00"),
    "TRANSIT": Decimal("50.00"),
    "SITE_SET": Decimal("25.00"),
    "POST_SET": Decimal("0.00"),
}
SEVERITY_EVIDENCE_THRESHOLD = 3

# ---- design_factory_compatibility_score ----------------------------------
CONFLICT_WEIGHT = 8
FIELD_SCOPE_WEIGHT = 5
SPLIT_MISMATCH_WEIGHT = 10
DETAIL_STATE_PENALTY = {
    "NOT_STARTED": 40,
    "FACTORY_DETAILED": 15,
    "FIELD_COORDINATED": 5,
    "COMPLETE": 0,
}
FREEZE_MIN_SCORE = 70

# ---- draw_certification_amount -------------------------------------------
DEPOSIT_PCT_DEFAULT = 0.20
RETAINAGE_PCT_DEFAULT = 0.05

# ---- module_exposure_hours -----------------------------------------------
EXPOSURE_LIMIT_HOURS_DEFAULT = 8.0

WEATHER_PRECIP_RELIEF_PCT = 40


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """ROUND_HALF_UP to `places` decimals; returns a Decimal."""
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """ROUND_HALF_UP to whole cents; returns an int."""
    return int(rhu(value, 0))


def envelope_class(width_in, height_in, gross_weight_lb):
    """Widest-first threshold ladder; comparisons are strict > the ceiling."""
    if (
        width_in > OVERWIDTH_MAX_WIDTH_IN
        or height_in > OVERWIDTH_MAX_HEIGHT_IN
        or gross_weight_lb > OVERWIDTH_MAX_WEIGHT_LB
    ):
        return "SUPERLOAD"
    if (
        width_in > STANDARD_MAX_WIDTH_IN
        or height_in > STANDARD_MAX_HEIGHT_IN
        or gross_weight_lb > STANDARD_MAX_WEIGHT_LB
    ):
        return "OVERWIDTH"
    return "STANDARD"


def wip_station_progress(module, factory):
    """The station_progress variant — the only variant persisted on the row."""
    if module["production_status"] not in ("SLOTTED", "IN_LINE", "LINE_COMPLETE"):
        return 0
    if module["qc_status"] == "HOLD":
        return 0
    stations = factory["station_count"]
    if stations <= 0:
        return 0
    return rhu_cents(
        dec(factory["wip_unit_value_cents"]) * dec(module["station_index"]) / dec(stations)
    )


def wip_milestone_delivered(module, factory):
    """The milestone_delivered variant — materialised only inside a draw basis."""
    if module["site_status"] in ("DELIVERED", "SET", "CONNECTED"):
        return int(factory["wip_unit_value_cents"])
    return 0


def effective_takt(base_takt_minutes, concurrent_at_start):
    return base_takt_minutes + TAKT_CONGESTION_PENALTY_MINUTES * concurrent_at_start


def compatibility_score(package, planned_module_count):
    penalty = (
        CONFLICT_WEIGHT * package["open_connection_conflicts"]
        + FIELD_SCOPE_WEIGHT * package["field_scope_items_open"]
        + DETAIL_STATE_PENALTY[package["connection_detail_state"]]
        + SPLIT_MISMATCH_WEIGHT
        * abs(package["module_split_count"] - planned_module_count)
    )
    return max(0, 100 - penalty)


def chart_capacity(chart, pick_radius_ft):
    """Smallest radius_ft entry that still covers the requested radius.
    Returns None when the radius is off the chart (or is missing entirely)."""
    if pick_radius_ft is None:
        return None
    best = None
    for entry in chart or []:
        if entry["radius_ft"] >= pick_radius_ft:
            if best is None or entry["radius_ft"] < best["radius_ft"]:
                best = entry
    if best is None:
        return None
    return best["capacity_lb"]


def derate(capacity_lb, forecast_wind_gust_mph):
    if dec(forecast_wind_gust_mph) >= dec(WIND_DERATE_GUST_MPH):
        # floor(capacity * 0.75) computed exactly in integers
        return (int(capacity_lb) * 3) // 4
    return int(capacity_lb)


def crane_check(capacity_lb, gross_weight_lb, rigging_weight_lb):
    """Returns (crane_utilization_pct as Decimal 2dp, infeasible bool).

    The gate is the exact integer cross-product, never the rounded display value.
    """
    total_lb = int(gross_weight_lb) + int(rigging_weight_lb or 0)
    if capacity_lb <= 0:
        return rhu(0, 2), True
    utilization = rhu(dec(total_lb) * dec(100) / dec(capacity_lb), 2)
    infeasible = (total_lb * 100) > (MAX_UTILIZATION_PCT * capacity_lb)
    return utilization, infeasible


def exposure_hours(module, clock_now):
    """Whole-minute difference divided by 60, ROUND_HALF_UP to 2 decimals."""
    site_status = module["site_status"]
    if site_status == "SET" and module["connected_at"] is None:
        if module["set_at"] is None:
            return rhu(0, 2)
        delta = clock_now - module["set_at"]
    elif site_status == "CONNECTED":
        if module["set_at"] is None or module["connected_at"] is None:
            return rhu(0, 2)
        delta = module["connected_at"] - module["set_at"]
    else:
        return rhu(0, 2)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 0:
        minutes = 0
    return rhu(dec(minutes) / dec(60), 2)


def widest_envelope(classes):
    worst = "STANDARD"
    for value in classes:
        if ENVELOPE_ORDER[value] > ENVELOPE_ORDER[worst]:
            worst = value
    return worst


def permit_fee_cents(max_envelope_class, route_state_count):
    return (
        BASE_STATE_PERMIT_FEE_CENTS
        * route_state_count
        * CLASS_MULTIPLIER[max_envelope_class]
    )


def escort_required(max_envelope_class, route_state_count):
    return max_envelope_class == "SUPERLOAD" or (
        max_envelope_class == "OVERWIDTH" and route_state_count >= 2
    )


def allocate_phase_presumption(claim):
    return PHASE_PRESUMPTION[claim["discovered_phase"]]


def allocate_evidence_weighted(claim, inspection, module, project):
    factory_score = 0
    field_score = 0
    if inspection is not None and inspection["result"] in ("FAIL", "CONDITIONAL"):
        factory_score += 6
    if inspection is not None and inspection["severity_max"] >= SEVERITY_EVIDENCE_THRESHOLD:
        factory_score += 3
    if module["defect_count_factory"] > module["defect_count_field"]:
        factory_score += 2
    if claim["discovered_phase"] in ("SITE_SET", "POST_SET"):
        field_score += 4
    if module["site_status"] in ("SET", "CONNECTED") and dec(
        module["exposure_open_hours"]
    ) > dec(project["weather_exposure_limit_hours"]):
        field_score += 3
    if module["connection_scope_owner"] == "FIELD":
        field_score += 2
    if factory_score + field_score == 0:
        return Decimal("50.00")
    return rhu(dec(factory_score) * dec(100) / dec(factory_score + field_score), 2)


def allocation_tail(claim, factory_share_pct):
    """Shared tail of both allocation variants (§1.3 defect_responsibility_allocation)."""
    field_share_pct = Decimal("100.00") - factory_share_pct
    repair = int(claim["repair_cost_cents"])
    factory_charge = rhu_cents(dec(repair) * factory_share_pct / dec(100))
    field_charge = repair - factory_charge
    if factory_share_pct == Decimal("100.00"):
        responsibility = "FACTORY"
    elif factory_share_pct == Decimal("0.00"):
        responsibility = "FIELD"
    else:
        responsibility = "SHARED"
    bucket = {
        "FACTORY": "FACTORY_WARRANTY",
        "FIELD": "FIELD_WARRANTY",
        "SHARED": "SPLIT",
    }[responsibility]
    return {
        "factory_share_pct": factory_share_pct,
        "field_share_pct": field_share_pct,
        "factory_charge_cents": factory_charge,
        "field_charge_cents": field_charge,
        "responsibility": responsibility,
        "warranty_bucket": bucket,
    }
