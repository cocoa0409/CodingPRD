"""The eleven calculations of the scaffold, implemented literally."""
from datetime import timedelta
from decimal import Decimal

from core import (
    add_days,
    add_months,
    db,
    dec,
    money,
    now,
    num2,
    num4,
    parse_date,
    parse_instant,
    round_half_up,
)

# ---- constants -----------------------------------------------------------
MAX_OPEN_ACCESS_ASA_CLASS = 3
SCREENING_START_AGE_YEARS = 45
SCREENING_END_AGE_YEARS = 75
HIGH_RISK_START_AGE_YEARS = 40
ADULT_AGE_YEARS = 18

EPISODE_DUE_DAYS_STANDARD = 180
EPISODE_DUE_DAYS_DIAGNOSTIC_FOLLOWUP = 90
EPISODE_DUE_DAYS_HIGH_PRIORITY = 30
NAVIGATION_HIGH_PRIORITY_EPISODES = 2

CHANNEL_WEIGHT = {"PHONE": "3.0", "SMS": "2.0", "PORTAL": "1.5", "MAIL": "1.0"}
ACK_MULTIPLIER_ACKED = Decimal("1.0")
ACK_MULTIPLIER_UNACKED = Decimal("0.4")
DECAY_PER_DAY = Decimal("0.05")
DECAY_FLOOR = Decimal("0.25")
ATTESTATION_BONUS_COMPLETED = Decimal("2.50")
ATTESTATION_BONUS_NOT_COMPLETED = Decimal("-1.00")
SCORE_MIN = Decimal("0.00")
SCORE_MAX = Decimal("10.00")
PREP_AT_RISK_THRESHOLD = Decimal("3.00")
PREP_CONFIRMED_THRESHOLD = Decimal("5.00")

RISK_TIER_CAP_MONTHS = {"AVERAGE": 120, "INCREASED": 60, "HIGH": 24}
POOR_PREP_CAP_MONTHS = 12
POOR_PREP_BBPS_MAX = 5
MIN_INTERVAL_MONTHS = 6
MAX_OVERRIDE_INTERVAL_MONTHS = 120
MAX_OVERRIDE_DELTA_MONTHS = 48

FACILITY_BASE_CENTS = 78000
FACILITY_PER_MINUTE_CENTS = 950
PROF_BASE_CENTS = 41500
POLYPECTOMY_ADDON_CENTS = 13750
ANESTHESIA_BASE_CENTS = 22000
ANESTHESIA_PER_MINUTE_CENTS = 410
OUTLIER_TIER_2_FLOOR_CENTS = 150000
OUTLIER_TIER_3_FLOOR_CENTS = 250000
OUTLIER_TIER_2_ADDON_CENTS = 8500
OUTLIER_TIER_3_ADDON_CENTS = 19000
ABORT_TECHNICAL_FEE_CENTS = 30000

MIN_SCREENING_VOLUME = 1
PREPROCEDURE_MAX_UNSCREENED_ASA_CLASS = 3

SCREENING_INDICATIONS = ("SCREENING_AVERAGE_RISK", "SCREENING_HIGH_RISK")
OPEN_CLINICAL_STATUSES = ("OPEN", "PROCEDURE_SCHEDULED", "PATHOLOGY_PENDING")
CLOSED_CLINICAL_STATUSES = ("CLOSED_SURVEILLANCE_SET", "CLOSED_DECLINED", "CLOSED_SUPERSEDED")
OCCUPYING_BOOKING_STATUSES = (
    "BOOKED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", "ABORTED_INADEQUATE_PREP",
)


# ---- 1. patient_risk_stratification -------------------------------------
def patient_risk_tier(ibd_diagnosis, prior_crc_history, family_history_crc):
    if ibd_diagnosis or prior_crc_history:
        return "HIGH"
    if family_history_crc:
        return "INCREASED"
    return "AVERAGE"


# ---- 2. open_access_risk_screen ------------------------------------------
def open_access_risk_screen(referral):
    if (
        referral["asa_class_reported"] <= MAX_OPEN_ACCESS_ASA_CLASS
        and referral["anticoagulant_reported"] is False
        and referral["reason"] != "SYMPTOMATIC_BLEEDING"
    ):
        return "CLEARED_OPEN_ACCESS"
    return "OFFICE_VISIT_REQUIRED"


# ---- 3. screening_eligibility -------------------------------------------
def whole_year_age(birth_date_str, index_date):
    birth = parse_date(birth_date_str)
    age = index_date.year - birth.year
    if (index_date.month, index_date.day) < (birth.month, birth.day):
        age -= 1
    return age


def screening_eligibility(indication, patient, index_date):
    age = whole_year_age(patient["birth_date"], index_date)
    if indication in SCREENING_INDICATIONS and patient["prior_crc_history"] is True:
        return "INELIGIBLE_PRIOR_CRC"
    if indication == "SCREENING_AVERAGE_RISK":
        if age < SCREENING_START_AGE_YEARS or age > SCREENING_END_AGE_YEARS:
            return "INELIGIBLE_AGE"
        return "ELIGIBLE"
    if indication == "SCREENING_HIGH_RISK":
        if age < HIGH_RISK_START_AGE_YEARS:
            return "INELIGIBLE_AGE"
        if patient["risk_tier"] not in ("INCREASED", "HIGH"):
            return "INELIGIBLE_RISK_MISMATCH"
        return "ELIGIBLE"
    return "ELIGIBLE" if age >= ADULT_AGE_YEARS else "INELIGIBLE_AGE"


# ---- 4. episode_due_date -------------------------------------------------
def episode_due_date(indication, index_date, navigation_priority=None):
    if indication == "DIAGNOSTIC_FOLLOWUP":
        days = EPISODE_DUE_DAYS_DIAGNOSTIC_FOLLOWUP
    else:
        days = EPISODE_DUE_DAYS_STANDARD
    due = add_days(index_date, days)
    if navigation_priority == "HIGH":
        due = add_days(index_date, EPISODE_DUE_DAYS_HIGH_PRIORITY)
    return due.isoformat()


# ---- 5. prep_adherence_score --------------------------------------------
def prep_adherence_score(episode):
    raw = Decimal("0.00")
    clock = now()
    for entry in episode.get("outreach_log") or []:
        weight = dec(CHANNEL_WEIGHT[entry["channel"]])
        ack = ACK_MULTIPLIER_ACKED if entry.get("acknowledged") else ACK_MULTIPLIER_UNACKED
        occurred = parse_instant(entry["occurred_at"])
        elapsed = (clock - occurred).total_seconds()
        days_ago = int(elapsed // 86400)
        decay = Decimal("1.00") - DECAY_PER_DAY * Decimal(days_ago)
        if decay < DECAY_FLOOR:
            decay = DECAY_FLOOR
        if decay > Decimal("1.00"):
            decay = Decimal("1.00")
        raw += round_half_up(weight * ack * decay, 2)
    attestation = episode.get("prep_attestation")
    if attestation == "COMPLETED":
        bonus = ATTESTATION_BONUS_COMPLETED
    elif attestation == "NOT_COMPLETED":
        bonus = ATTESTATION_BONUS_NOT_COMPLETED
    else:
        bonus = Decimal("0.00")
    total = raw + bonus
    if total < SCORE_MIN:
        total = SCORE_MIN
    if total > SCORE_MAX:
        total = SCORE_MAX
    return num2(total)


# ---- 6. surveillance_interval_months ------------------------------------
def finalized_pathology_aggregate(booking_id):
    agg = {
        "adenoma_count": 0,
        "sessile_serrated_count": 0,
        "largest_adenoma_mm": 0,
        "villous_component": False,
        "high_grade_dysplasia": False,
        "adenocarcinoma_present": False,
    }
    for report in db.reports.values():
        if report["booking_id"] != booking_id or report["status"] != "FINALIZED":
            continue
        agg["adenoma_count"] += report["adenoma_count"]
        agg["sessile_serrated_count"] += report["sessile_serrated_count"]
        if report["largest_adenoma_mm"] > agg["largest_adenoma_mm"]:
            agg["largest_adenoma_mm"] = report["largest_adenoma_mm"]
        agg["villous_component"] = agg["villous_component"] or bool(report["villous_component"])
        agg["high_grade_dysplasia"] = agg["high_grade_dysplasia"] or bool(report["high_grade_dysplasia"])
        agg["adenocarcinoma_present"] = (
            agg["adenocarcinoma_present"] or bool(report["adenocarcinoma_present"])
        )
    return agg


def computed_interval_months(agg, risk_tier_snapshot, prep_quality_bbps):
    if agg["high_grade_dysplasia"] or agg["adenocarcinoma_present"]:
        base = 6
    elif agg["adenoma_count"] == 0 and agg["sessile_serrated_count"] == 0:
        base = 120
    elif agg["adenoma_count"] >= 10:
        base = 12
    elif (
        agg["adenoma_count"] >= 5
        or agg["largest_adenoma_mm"] >= 10
        or agg["villous_component"]
    ):
        base = 36
    elif agg["sessile_serrated_count"] >= 1:
        base = 60
    else:
        base = 84
    cap = RISK_TIER_CAP_MONTHS[risk_tier_snapshot]
    stage2 = min(base, cap)
    if prep_quality_bbps is not None and prep_quality_bbps <= POOR_PREP_BBPS_MAX:
        stage3 = min(stage2, POOR_PREP_CAP_MONTHS)
    else:
        stage3 = stage2
    return max(stage3, MIN_INTERVAL_MONTHS)


def next_due_date(booking, months):
    anchor = parse_instant(booking["slot_start_utc"]).date()
    return add_months(anchor, months).isoformat()


# ---- 7. claim_pricing ---------------------------------------------------
def provisional_classification(episode, plan):
    if episode["indication"] in ("SCREENING_AVERAGE_RISK", "SCREENING_HIGH_RISK", "SURVEILLANCE"):
        return "SCREENING_PREVENTIVE"
    if (
        episode["indication"] == "DIAGNOSTIC_FOLLOWUP"
        and episode["origin"] == "NONINVASIVE_POSITIVE"
        and plan["modifier_33_honored"] is True
    ):
        return "SCREENING_PREVENTIVE"
    return "DIAGNOSTIC"


def price_claim(variant, booking, session, episode, plan, patient):
    """Returns the money fields for the claim under `variant` (PROVISIONAL|FINAL)."""
    polyps = 0 if variant == "PROVISIONAL" else int(booking.get("polyps_removed_count") or 0)
    duration = booking["duration_minutes"]

    lines = [
        {"code": "FACILITY",
         "allowed_cents": FACILITY_BASE_CENTS + FACILITY_PER_MINUTE_CENTS * duration},
        {"code": "PROFESSIONAL",
         "allowed_cents": PROF_BASE_CENTS + POLYPECTOMY_ADDON_CENTS * polyps},
    ]
    if session["anesthesia_mode"] == "MAC":
        lines.append({
            "code": "ANESTHESIA",
            "allowed_cents": ANESTHESIA_BASE_CENTS + ANESTHESIA_PER_MINUTE_CENTS * duration,
        })
    if booking["status"] == "ABORTED_INADEQUATE_PREP":
        lines = [{"code": "ABORTED_TECHNICAL", "allowed_cents": ABORT_TECHNICAL_FEE_CENTS}]

    base_allowed_cents = sum(line["allowed_cents"] for line in lines)

    if base_allowed_cents >= OUTLIER_TIER_3_FLOOR_CENTS:
        complexity_tier = "TIER_3"
        addon = OUTLIER_TIER_3_ADDON_CENTS
    elif base_allowed_cents >= OUTLIER_TIER_2_FLOOR_CENTS:
        complexity_tier = "TIER_2"
        addon = OUTLIER_TIER_2_ADDON_CENTS
    else:
        complexity_tier = "TIER_1"
        addon = 0
    lines[0]["allowed_cents"] = lines[0]["allowed_cents"] + addon
    allowed_amount_cents = base_allowed_cents + addon

    classification = provisional_classification(episode, plan)
    if variant != "PROVISIONAL" and booking["status"] != "ABORTED_INADEQUATE_PREP":
        if int(booking.get("polyps_removed_count") or 0) >= 1 and \
                plan["polypectomy_carveout"] == "DIAGNOSTIC_CONVERTED":
            classification = "DIAGNOSTIC"

    deductible_remaining = max(0, plan["deductible_cents"] - patient["deductible_applied_cents"])
    patient_total = 0
    deductible_applied_cents = 0
    coinsurance_cents = 0
    preventive_pct = dec(plan["preventive_coverage_pct"])
    diagnostic_pct = dec(plan["diagnostic_coinsurance_pct"])
    for line in lines:
        allowed = line["allowed_cents"]
        if classification == "SCREENING_PREVENTIVE":
            if line["code"] == "ANESTHESIA" and plan["anesthesia_bundled"] is False:
                line_coins = money(dec(allowed) * diagnostic_pct)
            else:
                line_coins = money(dec(allowed) * (Decimal("1.00") - preventive_pct))
            line_ded = 0
        else:
            line_ded = min(allowed, deductible_remaining)
            deductible_remaining -= line_ded
            line_coins = money(dec(allowed - line_ded) * diagnostic_pct)
        deductible_applied_cents += line_ded
        coinsurance_cents += line_coins
        patient_total += line_ded + line_coins

    headroom = max(0, plan["out_of_pocket_max_cents"] - patient["oop_applied_cents"])
    patient_responsibility_cents = min(patient_total, headroom)
    plan_paid_cents = allowed_amount_cents - patient_responsibility_cents

    return {
        "classification": classification,
        "line_items": lines,
        "base_allowed_cents": base_allowed_cents,
        "complexity_tier": complexity_tier,
        "allowed_amount_cents": allowed_amount_cents,
        "deductible_applied_cents": deductible_applied_cents,
        "coinsurance_cents": coinsurance_cents,
        "patient_responsibility_cents": patient_responsibility_cents,
        "plan_paid_cents": plan_paid_cents,
    }


# ---- 8. adenoma_detection_rate ------------------------------------------
def adenoma_detection_rate(period):
    basis = period["attribution_basis"]
    denominator = []
    for booking in db.bookings.values():
        if booking["status"] != "COMPLETED":
            continue
        if booking["performing_endoscopist_id"] != period["endoscopist_id"]:
            continue
        episode = db.episodes.get(booking["episode_id"])
        if not episode or episode["indication"] not in SCREENING_INDICATIONS:
            continue
        finalized = [
            r for r in db.reports.values()
            if r["booking_id"] == booking["id"] and r["status"] == "FINALIZED"
        ]
        if basis == "PROCEDURE_DATE":
            attribution_date = booking["slot_start_utc"][:10]
        else:
            if not finalized:
                continue
            attribution_date = min(r["finalized_at"][:10] for r in finalized)
        if period["period_start_date"] <= attribution_date <= period["period_end_date"]:
            denominator.append((booking, finalized))

    screening_colonoscopy_count = len(denominator)
    adenoma_positive_count = sum(
        1 for _b, reports in denominator
        if any(r["adenoma_count"] >= 1 for r in reports)
    )
    if screening_colonoscopy_count == 0:
        adr_pct = None
    else:
        adr_pct = num4(dec(adenoma_positive_count) / dec(screening_colonoscopy_count))
    return screening_colonoscopy_count, adenoma_positive_count, adr_pct


# ---- 9. room_slot_feasibility (helpers) ---------------------------------
def occupancy_bounds(slot_start, duration_minutes, turnover_minutes):
    slot_end = slot_start + timedelta(minutes=duration_minutes)
    occupancy_end = slot_end + timedelta(minutes=turnover_minutes)
    return slot_end, occupancy_end


# ---- 10. anesthesia_overlap_load ---------------------------------------
def anesthesia_load(clinician_id, start, end):
    existing = [
        c for c in db.coverages.values()
        if c["anesthesia_clinician_id"] == clinician_id and c["status"] == "ACTIVE"
    ]
    spans = [(parse_instant(c["coverage_start_utc"]), parse_instant(c["coverage_end_utc"]))
             for c in existing]
    event_points = [start] + [s for s, _e in spans if start <= s < end]
    peak = 0
    for t in event_points:
        load = 1 + sum(1 for s, e in spans if s <= t < e)
        if load > peak:
            peak = load
    overlap_index = 1 + sum(1 for s, e in spans if s <= start < e)
    return peak, overlap_index


# ---- 11. session_capacity_ledger ---------------------------------------
def session_capacity_minutes(session):
    start = parse_instant(session["window_start_utc"])
    end = parse_instant(session["window_end_utc"])
    return int((end - start).total_seconds() // 60)


def recompute_session_ledger(session):
    capacity = session_capacity_minutes(session)
    booked = 0
    for booking in db.bookings.values():
        if booking["session_id"] != session["id"]:
            continue
        if booking["status"] in OCCUPYING_BOOKING_STATUSES:
            booked += booking["duration_minutes"] + session["turnover_minutes"]
    session["capacity_minutes"] = capacity
    session["booked_minutes"] = booked
    session["remaining_minutes"] = capacity - booked
