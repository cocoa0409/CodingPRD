"""Calculation rules (scaffold section 1.3 / PRD section 3).

All money is integer cents; all rounding is Decimal ROUND_HALF_UP. Never float
for money.
"""

from datetime import date, timedelta

import db
from clock import CLOCK
from util import D, rhu, rhu_int, num2, num4

# --- constants (scaffold calculations[].constants) --------------------------

SLA_DAYS = {"CRITICAL": 7, "HIGH": 14, "MEDIUM": 30, "LOW": 60}

HAZARD_CLASS_MULT = {"LOW": D("1.0"), "MODERATE": D("1.2"), "HIGH": D("1.5")}
TIME_MULT_ON_TIME = D("1.25")

EVENT_BASE_POINTS = {
    "OBSERVATION_VALIDATED": 10,
    "NEAR_MISS_VALIDATED": 20,
    "CONTROL_VERIFIED": 15,
    "ACTION_VERIFIED": 10,
    "MEETING_ATTENDED": 5,
    "CLAIMS_FREE_BONUS": 50,
}

TIER_VALUE_CENTS = {"BRONZE": 150, "SILVER": 200, "GOLD": 250, "PLATINUM": 300}

HOURS_NORMALIZATION = 200000

SPLIT_POINT_CENTS = 1500000
ERA_MEDICAL_ONLY_FACTOR = D("0.3")
EXCESS_RATIO = D("0.55")
BALLAST_RATE = D("0.10")
W_FLOOR = D("0.05")
W_CAP = D("0.75")
W_OFFSET_DOLLARS = D("20000")
W_SPAN_DOLLARS = D("180000")

EMR_BENCHMARK = D("1.25")
TRIR_BENCHMARK = D("8.0")


# --- hazard risk (calculations.hazard_risk_score) ----------------------------

def risk_assessment(severity, probability, assessed_at):
    score = severity * probability
    if score <= 4:
        band = "LOW"
    elif score <= 9:
        band = "MEDIUM"
    elif score <= 15:
        band = "HIGH"
    else:
        band = "CRITICAL"
    sla_due = assessed_at + timedelta(days=SLA_DAYS[band])
    return score, band, sla_due


# --- incentive points & awards (calculations.incentive_event_points,
#     calculations.award_payout) ----------------------------------------------

def class_multiplier_for_employee(emp):
    role = db.DB["job_roles"].get(emp["job_role_id"]) if emp else None
    return HAZARD_CLASS_MULT.get(role["hazard_class"], D("1.0")) if role else D("1.0")


def points_awarded(points_base, hazard_class_multiplier, timeliness_multiplier):
    return rhu_int(D(points_base) * D(hazard_class_multiplier) * D(timeliness_multiplier))


def tier_for_points(points):
    if points >= 200:
        return "PLATINUM"
    if points >= 100:
        return "GOLD"
    if points >= 50:
        return "SILVER"
    return "BRONZE"


def payout_for_points(points, tier):
    """Whole-dollar rounding per employee BEFORE any aggregation."""
    return rhu_int(D(points) * D(TIER_VALUE_CENTS[tier]) / D(100)) * 100


# --- leading indicators & integrity (calculations.leading_indicator_rates) ---

def leading_indicators(program):
    pid = program["id"]
    triaged = [o for o in db.DB["observations"].values()
               if o["program_id"] == pid
               and o["status"] in ("LINKED", "NO_ACTION", "CLOSED")]
    total = len(triaged)
    nm = sum(1 for o in triaged if o["kind"] == "NEAR_MISS")
    exposure = program["exposure_hours"]
    if exposure and exposure > 0:
        rate = rhu(D(total) * D(HOURS_NORMALIZATION) / D(exposure), 2)
    else:
        rate = D("0")
    ratio_unrounded = (D(nm) / D(total)) if total else D("0")
    ratio = rhu(ratio_unrounded, 4) if total else D("0")
    target_met = rate >= D(program["observation_target_rate"])
    accepted = sum(1 for c in db.DB["claims"].values()
                   if c["program_id"] == pid and c["status"] in ("ACCEPTED", "CLOSED"))
    # The integrity comparison uses the UNROUNDED ratio (PRD 2.7 / 3.4).
    integrity = accepted > 0 and ratio_unrounded < D(program["near_miss_floor_ratio"])
    return {
        "observation_count": total,
        "near_miss_count": nm,
        "exposure_hours": exposure,
        "observation_rate": float(rate),
        "near_miss_ratio": float(ratio),
        "target_met": target_met,
        "integrity_flag": integrity,
    }


def compute_integrity_flag(program):
    return leading_indicators(program)["integrity_flag"]


# --- program posture (calculations.program_posture) --------------------------

def posture_for(overdue_control_count, sla_breach_count, integrity_flag,
                overdue_lcr_count):
    if overdue_control_count >= 3 or sla_breach_count >= 1:
        return "RESTRICTED"
    if overdue_control_count >= 1 or integrity_flag or overdue_lcr_count >= 1:
        return "WATCH"
    return "NORMAL"


# --- contractor prequalification (calculations.prequal_score) -----------------

def prequal_score(emr, trir, safety_audit_pct, insurance_cert_expires_on,
                  logical_today):
    emr_component = min(max((EMR_BENCHMARK - D(emr)) / EMR_BENCHMARK, D(0)), D(1)) * 100
    trir_component = min(max((TRIR_BENCHMARK - D(trir)) / TRIR_BENCHMARK, D(0)), D(1)) * 100
    days_to_expiry = (insurance_cert_expires_on - logical_today).days
    if days_to_expiry >= 90:
        insurance_component = D(100)
    elif days_to_expiry >= 30:
        insurance_component = D(50)
    else:
        insurance_component = D(0)
    score = rhu(D("0.40") * emr_component
                + D("0.30") * trir_component
                + D("0.20") * D(safety_audit_pct)
                + D("0.10") * insurance_component, 2)
    # Band comparison uses the ROUNDED 2dp score.
    if score >= D("80.00"):
        decision = "APPROVE"
    elif score >= D("65.00"):
        decision = "CONDITIONAL"
    else:
        decision = "REJECT"
    return score, decision


# --- claims ERA effective cost -----------------------------------------------

def effective_incurred(claim_kind, incurred_cents):
    if claim_kind == "MEDICAL_ONLY":
        return rhu_int(D(incurred_cents) * ERA_MEDICAL_ONLY_FACTOR)
    return incurred_cents


# --- EMR forecast (calculations.emr_forecast) ---------------------------------

def _class_map(entries, key):
    out = {}
    for e in entries or []:
        out[e.get("hazard_class")] = e.get(key)
    return out


def emr_snapshot(program, as_of):
    """Compute both PROVISIONAL and FINAL bases. Returns a dict of fields."""
    year = program["program_year"]
    jan1 = date(year, 1, 1)
    days_elapsed = (as_of.date() - jan1).days
    if as_of.date() > date(year, 12, 31):
        payroll_factor = 1.0
    else:
        payroll_factor = 365.0 / max(days_elapsed, 30)
    fD = D(repr(payroll_factor))

    payroll = _class_map(program["payroll_by_class"], "payroll_cents")
    elr = _class_map(program["elr_by_class"], "elr")

    # Per-class expected losses rounded half-up to the cent BEFORE summation.
    e_prov = 0
    e_fin = 0
    for cls in ("LOW", "MODERATE", "HIGH"):
        p = D(payroll.get(cls, 0) or 0)
        e = D(elr.get(cls, 0) or 0)
        e_prov += rhu_int(p * fD * e / D(100))
        e_fin += rhu_int(p * e / D(100))

    w = rhu(min(max((D(e_fin) / D(100) - W_OFFSET_DOLLARS) / W_SPAN_DOLLARS,
                    W_FLOOR), W_CAP), 4)

    b_prov = rhu_int(BALLAST_RATE * D(e_prov))
    b_fin = rhu_int(BALLAST_RATE * D(e_fin))
    ee_prov = rhu_int(EXCESS_RATIO * D(e_prov))
    ee_fin = rhu_int(EXCESS_RATIO * D(e_fin))

    pid = program["id"]
    claims = [c for c in db.DB["claims"].values() if c["program_id"] == pid]
    prov_set = [c for c in claims if c["status"] in ("REPORTED", "ACCEPTED", "CLOSED")]
    fin_set = [c for c in claims if c["status"] in ("ACCEPTED", "CLOSED")]

    def split_sums(rows):
        ap = sum(min(c["effective_incurred_cents"], SPLIT_POINT_CENTS) for c in rows)
        ae = sum(max(0, c["effective_incurred_cents"] - SPLIT_POINT_CENTS) for c in rows)
        return ap, ae

    ap_prov, ae_prov = split_sums(prov_set)
    ap_fin, ae_fin = split_sums(fin_set)

    emr_prov = rhu((D(ap_prov) + w * D(ae_prov) + (D(1) - w) * D(ee_prov) + D(b_prov))
                   / D(e_prov + b_prov), 2)
    emr_fin = rhu((D(ap_fin) + w * D(ae_fin) + (D(1) - w) * D(ee_fin) + D(b_fin))
                  / D(e_fin + b_fin), 2)

    return {
        "payroll_factor": payroll_factor,
        "expected_losses_provisional_cents": e_prov,
        "expected_losses_final_cents": e_fin,
        "weighting_w": float(w),
        "ballast_provisional_cents": b_prov,
        "ballast_final_cents": b_fin,
        "actual_primary_provisional_cents": ap_prov,
        "actual_excess_provisional_cents": ae_prov,
        "actual_primary_final_cents": ap_fin,
        "actual_excess_final_cents": ae_fin,
        "emr_provisional": float(emr_prov),
        "emr_final": float(emr_fin),
    }
