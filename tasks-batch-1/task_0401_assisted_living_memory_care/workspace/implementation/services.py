"""Business-logic services: calculations, recomputations, serializers."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from db import db, touch
from helpers import round_half_up

# ---------------------------------------------------------------------------
# Calculation constants (from SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
ADL_POINT_WEIGHT = 3
COGNITION_WEIGHT = 2
BEHAVIOR_WEIGHT = 5
BEHAVIOR_FLAG_CAP = 4

MEMORY_CARE_COGNITION_THRESHOLD = 7
LEVEL_2_MIN_POINTS = 30
LEVEL_3_MIN_POINTS = 55

BPS_SCALE = 10000

STANDARD_POC_WINDOW_DAYS = 10
IJ_POC_WINDOW_DAYS = 2


# ---------------------------------------------------------------------------
# care_points_total + care_level_assignment
# ---------------------------------------------------------------------------
def compute_care_points(a):
    adl_sum = (a["adl_bathing"] + a["adl_dressing"] + a["adl_toileting"]
               + a["adl_transferring"] + a["adl_eating"])
    base = adl_sum * ADL_POINT_WEIGHT
    cognition_component = a["cognition_score"] * COGNITION_WEIGHT
    behavior_component = min(a["behavior_flags"], BEHAVIOR_FLAG_CAP) * BEHAVIOR_WEIGHT
    return base + cognition_component + behavior_component


def compute_care_level(care_points_total, cognition_score):
    if cognition_score >= MEMORY_CARE_COGNITION_THRESHOLD:
        return "MEMORY_CARE"
    if care_points_total >= LEVEL_3_MIN_POINTS:
        return "LEVEL_3"
    if care_points_total >= LEVEL_2_MIN_POINTS:
        return "LEVEL_2"
    return "LEVEL_1"


# ---------------------------------------------------------------------------
# poc_due_date
# ---------------------------------------------------------------------------
def compute_poc_due_date(cited_at, scope_severity):
    window_days = IJ_POC_WINDOW_DAYS if scope_severity == "J_L_IMMEDIATE_JEOPARDY" else STANDARD_POC_WINDOW_DAYS
    cited_date = _parse_date_part(cited_at)
    due = cited_date + timedelta(days=window_days)
    return due.isoformat()


def _parse_date_part(value):
    """Extract the calendar date from an ISO date or datetime string."""
    s = value.strip()
    # take the part before 'T' if present
    date_part = s.split("T")[0]
    return date.fromisoformat(date_part)


# ---------------------------------------------------------------------------
# Facility occupancy recompute
# ---------------------------------------------------------------------------
def recompute_facility_occupancy(facility):
    fid = facility["id"]
    units = [u for u in db.units.values() if u["facility_id"] == fid]
    bed_count = sum(1 for u in units if u["status"] != "RETIRED")
    occupied_bed_count = sum(1 for u in units if u["status"] == "OCCUPIED")
    if bed_count == 0:
        occupancy_rate_bps = 0
    else:
        occupancy_rate_bps = round_half_up(Decimal(occupied_bed_count * BPS_SCALE) / Decimal(bed_count))
    facility["bed_count"] = bed_count
    facility["occupied_bed_count"] = occupied_bed_count
    facility["occupancy_rate_bps"] = occupancy_rate_bps


def recompute_facility_deficiencies(facility):
    fid = facility["id"]
    count = sum(1 for d in db.survey_deficiencies.values()
                if d["facility_id"] == fid and d["status"] != "CORRECTED")
    facility["open_deficiency_count"] = count


def touch_facility_metrics(facility, occupancy=False, deficiencies=False):
    """Recompute the named derived metrics, then count it as a mutation."""
    if occupancy:
        recompute_facility_occupancy(facility)
    if deficiencies:
        recompute_facility_deficiencies(facility)
    touch(facility)


# ---------------------------------------------------------------------------
# Resident open_balance recompute
# ---------------------------------------------------------------------------
def recompute_resident_balance(resident):
    rid = resident["id"]
    total = 0
    for s in db.billing_statements.values():
        if s["resident_id"] == rid and s["status"] in ("ISSUED", "PARTIALLY_PAID"):
            total += s["total_charge_cents"] - s["paid_cents"]
    resident["open_balance_cents"] = total
    touch(resident)


# ---------------------------------------------------------------------------
# monthly_charge (billing statement issue)
# ---------------------------------------------------------------------------
def compute_monthly_charge(statement, resident, agreement, facility):
    period_year = statement["period_year"]
    period_month = statement["period_month"]
    days_in_month = calendar.monthrange(period_year, period_month)[1]

    care_points_month_cents = resident["current_care_points"] * facility["care_point_rate_cents"]
    base_rent_month_cents = agreement["monthly_base_rent_cents"]

    if statement["is_first_statement"]:
        move_in_date = _parse_date_part(agreement["move_in_date"])
        billable_days = days_in_month - (move_in_date.day - 1)
        rent_charge_cents = round_half_up(
            Decimal(base_rent_month_cents * billable_days) / Decimal(days_in_month))
        care_points_charge_cents = round_half_up(
            Decimal(care_points_month_cents * billable_days) / Decimal(days_in_month))
        community_fee_charge_cents = agreement.get("community_fee_cents", 0)
    else:
        rent_charge_cents = base_rent_month_cents
        care_points_charge_cents = care_points_month_cents
        community_fee_charge_cents = 0

    total_charge_cents = rent_charge_cents + care_points_charge_cents + community_fee_charge_cents

    statement["rent_charge_cents"] = rent_charge_cents
    statement["care_points_charge_cents"] = care_points_charge_cents
    statement["community_fee_charge_cents"] = community_fee_charge_cents
    statement["total_charge_cents"] = total_charge_cents


# ---------------------------------------------------------------------------
# Lookup helpers for active agreement / care plans
# ---------------------------------------------------------------------------
def active_agreement_for_resident(resident_id):
    for a in db.move_in_agreements.values():
        if a["resident_id"] == resident_id and a["status"] == "ACTIVE":
            return a
    return None


def open_agreement_for_resident(resident_id):
    """An agreement in DRAFT or ACTIVE status (at most one allowed)."""
    for a in db.move_in_agreements.values():
        if a["resident_id"] == resident_id and a["status"] in ("DRAFT", "ACTIVE"):
            return a
    return None
