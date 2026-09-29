"""Calculation rules (scaffold §1.3 / PRD §3).

Every algorithm here is pinned to the PRD prose: acuity scoring and tiering, the
two hold-deadline variants, the two monitoring-compliance variants, per-episode
observation staffing ceilings, the four-step unit posture computation, the
deterministic bed selector, the queued-admission promotion ranking, the business
hours response deadline and the follow-up guarantee window.
"""

import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from store import db, sort_key
from timeutil import business_hours_deadline, roll_to_court_window

# --------------------------------------------------------------------------- #
# acuity_score_and_tier
# --------------------------------------------------------------------------- #
WEIGHT_DANGER_SELF = 4
WEIGHT_DANGER_OTHERS = 5
WEIGHT_GRAVE_DISABILITY = 3
WEIGHT_PER_PRIOR_ADMISSION = 2
PRIOR_ADMISSION_CAP = 3
WEIGHT_CAPACITY_ABSENT = 3
TIER_HIGH_MIN = 12
TIER_MODERATE_MIN = 7
RECENCY_WINDOW_DAYS = 30

PRIOR_ADMISSION_STATES = ("PLACED", "DISCHARGE_READY", "DISCHARGED")


def prior_admission_count_30d(patient_id, evaluation_started_at):
    lower = evaluation_started_at - timedelta(days=RECENCY_WINDOW_DAYS)
    count = 0
    for adm in db.admissions.values():
        if adm["patient_id"] != patient_id:
            continue
        if adm["placement_status"] not in PRIOR_ADMISSION_STATES:
            continue
        admitted_at = adm.get("admitted_at")
        if admitted_at is None:
            continue
        if admitted_at >= lower and admitted_at < evaluation_started_at:
            count += 1
    return count


def acuity_score_and_tier(danger_to_self, danger_to_others, grave_disability,
                          capacity_present, prior_count):
    score = 0
    if danger_to_self:
        score += WEIGHT_DANGER_SELF
    if danger_to_others:
        score += WEIGHT_DANGER_OTHERS
    if grave_disability:
        score += WEIGHT_GRAVE_DISABILITY
    score += WEIGHT_PER_PRIOR_ADMISSION * min(PRIOR_ADMISSION_CAP, prior_count)
    if not capacity_present:
        score += WEIGHT_CAPACITY_ABSENT

    if score >= TIER_HIGH_MIN:
        tier = "HIGH"
    elif score >= TIER_MODERATE_MIN:
        tier = "MODERATE"
    else:
        tier = "LOW"

    any_criterion = bool(danger_to_self or danger_to_others or grave_disability)
    if not any_criterion:
        recommended = "NO_ADMISSION"
    elif capacity_present:
        recommended = "VOLUNTARY"
    else:
        recommended = "INVOLUNTARY_HOLD"
    return score, tier, recommended


# --------------------------------------------------------------------------- #
# hold_deadline_pair
# --------------------------------------------------------------------------- #
EMERGENCY_HOURS = 72
EXTENSION_HOURS = 336
CERTIFICATION_WINDOW_HOURS = 4


def statutory_hours_for(hold_type):
    return EMERGENCY_HOURS if hold_type == "EMERGENCY_72H" else EXTENSION_HOURS


def hold_deadlines(clock_started_at, statutory_hours):
    """Returns (certification_deadline_at, release_deadline_at, petition_filing_deadline_at)."""
    certification_deadline_at = clock_started_at + timedelta(hours=CERTIFICATION_WINDOW_HOURS)
    # variant calendar_clock — pure wall clock, no rolling.
    release_deadline_at = clock_started_at + timedelta(hours=statutory_hours)
    # variant judicial_day_clock — same anchor and offset, rolled onto the court calendar.
    petition_filing_deadline_at = roll_to_court_window(release_deadline_at)
    return certification_deadline_at, release_deadline_at, petition_filing_deadline_at


# --------------------------------------------------------------------------- #
# monitoring_compliance_pair
# --------------------------------------------------------------------------- #
INTERVAL_PHYSICAL_HOLD_MIN = 5
INTERVAL_OTHER_MIN = 15


def monitoring_interval_minutes(intervention_type):
    return INTERVAL_PHYSICAL_HOLD_MIN if intervention_type == "PHYSICAL_HOLD" else INTERVAL_OTHER_MIN


def _round_half_up_1(numerator, denominator):
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return float(value)


def monitoring_compliance(episode, actual_duration_minutes):
    """Compute required_check_count and both compliance variants."""
    interval = episode["monitoring_interval_minutes"]
    required = math.ceil(actual_duration_minutes / interval) if actual_duration_minutes > 0 else 0
    log = episode.get("monitoring_check_log") or []
    if required == 0:
        return 0, 0, 100.0, 100.0

    started_at = episode["started_at"]
    satisfied = 0
    for k in range(1, required + 1):
        slot_start = started_at + timedelta(minutes=interval * (k - 1))
        slot_end = started_at + timedelta(minutes=interval * k)
        for entry in log:
            recorded_at = entry["recorded_at"]
            if slot_start <= recorded_at < slot_end:
                satisfied += 1
                break
    grid_pct = _round_half_up_1(100 * satisfied, required)
    raw_pct = _round_half_up_1(100 * min(required, len(log)), required)
    return required, satisfied, grid_pct, raw_pct


# --------------------------------------------------------------------------- #
# observation_staffing_quarter_hours
# --------------------------------------------------------------------------- #
QUARTER_HOUR_MINUTES = 15
STAFFING_EPISODE_STATES = ("RELEASED", "DEBRIEFED", "EXPIRED_UNAUTHORIZED")


def observation_staffing_quarter_hours(admission_id):
    episodes = [
        e
        for e in db.restraints.values()
        if e["admission_id"] == admission_id
        and e["status"] in STAFFING_EPISODE_STATES
        and e.get("actual_duration_minutes") is not None
    ]
    episodes.sort(key=lambda e: (e["started_at"], e["created_at"], e["_seq"]))
    # Rounding order is pinned: ceiling PER EPISODE, then sum.
    return sum(math.ceil(e["actual_duration_minutes"] / QUARTER_HOUR_MINUTES) for e in episodes)


# --------------------------------------------------------------------------- #
# restraint_duration_ceiling
# --------------------------------------------------------------------------- #
def restraint_duration_ceiling(is_minor, intervention_type):
    if is_minor:
        return 30 if intervention_type == "PHYSICAL_HOLD" else 120
    return 60 if intervention_type == "PHYSICAL_HOLD" else 240


# --------------------------------------------------------------------------- #
# unit_posture_and_effective_availability
# --------------------------------------------------------------------------- #
PLACEMENT_BED_TYPES = ("STANDARD", "LIGATURE_RESISTANT_OBSERVATION")
RESTRICTED_FRACTION = 0.20


def unit_beds(unit_id):
    return [b for b in db.beds.values() if b["unit_id"] == unit_id]


def compute_unit_counters(unit):
    beds = unit_beds(unit["id"])
    placement_beds = [b for b in beds if b["bed_type"] in PLACEMENT_BED_TYPES]

    # STEP 1 — raw inventory from Bed.status only.
    licensed = len([b for b in placement_beds if b["status"] != "OUT_OF_SERVICE"])
    raw_available = len([b for b in placement_beds if b["status"] == "AVAILABLE"])

    # STEP 2 — posture from raw_available_bed_count ONLY.
    restricted_threshold = max(1, int(math.floor(licensed * RESTRICTED_FRACTION)))
    if raw_available == 0:
        posture = "CLOSED"
    elif raw_available <= restricted_threshold:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    # STEP 3 — reserve derived from posture.
    safety_reserve = 1 if posture == "RESTRICTED" else 0

    # STEP 4 — effective availability. Never feeds back into posture.
    effective = max(0, raw_available - safety_reserve)

    occupied = len([b for b in beds if b["status"] == "OCCUPIED"])

    unit["licensed_placement_bed_count"] = licensed
    unit["raw_available_bed_count"] = raw_available
    unit["posture"] = posture
    unit["effective_available_bed_count"] = effective
    unit["occupied_bed_count"] = occupied
    unit["active_seclusion_count"] = live_seclusion_count(unit["id"])
    unit["open_rights_violation_count"] = open_rights_violation_count(unit["id"])


def live_seclusion_count(unit_id):
    now = db.now()
    count = 0
    for episode in db.restraints.values():
        if episode["intervention_type"] != "SECLUSION":
            continue
        if episode["status"] not in ("ORDERED", "ACTIVE"):
            continue
        if episode["authorized_until_at"] is None or episode["authorized_until_at"] <= now:
            continue
        admission = db.admissions.get(episode["admission_id"])
        if admission is not None and admission["unit_id"] == unit_id:
            count += 1
    return count


def open_rights_violation_count(unit_id):
    return len(
        [
            a
            for a in db.admissions.values()
            if a["unit_id"] == unit_id
            and a.get("rights_violation_flag")
            and a["placement_status"] != "DISCHARGED"
        ]
    )


# --------------------------------------------------------------------------- #
# bed_placement_selector
# --------------------------------------------------------------------------- #
def placed_admissions_with_bed(unit_id):
    out = []
    for adm in db.admissions.values():
        if adm["placement_status"] != "PLACED":
            continue
        bed_id = adm.get("bed_id")
        if not bed_id:
            continue
        bed = db.beds.get(bed_id)
        if bed is None or bed["unit_id"] != unit_id:
            continue
        out.append((adm, bed))
    return out


def roommates(bed):
    return [
        adm
        for adm, other in placed_admissions_with_bed(bed["unit_id"])
        if other["room_number"] == bed["room_number"]
    ]


def wingmates(bed):
    return [
        adm
        for adm, other in placed_admissions_with_bed(bed["unit_id"])
        if other["wing_code"] == bed["wing_code"]
    ]


def _patient_of(admission):
    return db.patients.get(admission["patient_id"]) or {}


def room_cohort_ok(unit, bed, patient):
    policy = unit["gender_mixing_policy"]
    if policy == "MIXED_ALLOWED":
        return True
    if policy == "SEPARATE_BY_ROOM":
        peers = roommates(bed)
    else:  # SEPARATE_BY_WING
        peers = wingmates(bed)
    category = patient.get("gender_care_category")
    return all(_patient_of(p).get("gender_care_category") == category for p in peers)


def minor_cohort_ok(bed, patient):
    is_minor = patient.get("is_minor")
    return all(_patient_of(p).get("is_minor") == is_minor for p in roommates(bed))


def cohort_ok(unit, bed, patient):
    return room_cohort_ok(unit, bed, patient) and minor_cohort_ok(bed, patient)


def bed_type_ok(bed, admission):
    if bed["bed_type"] not in PLACEMENT_BED_TYPES:
        return False
    if admission["acuity_tier"] == "HIGH" and bed["bed_type"] != "LIGATURE_RESISTANT_OBSERVATION":
        return False
    return True


def exact_fit_type(admission):
    if admission["acuity_tier"] in ("HIGH", "MODERATE"):
        return "LIGATURE_RESISTANT_OBSERVATION"
    return "STANDARD"


def bed_rank(bed, admission):
    fit = exact_fit_type(admission)
    return (
        len(roommates(bed)),
        0 if bed["bed_type"] == fit else 1,
        bed["room_number"],
        bed["bed_label"],
        bed["created_at"],
        bed["_seq"],
    )


def bed_candidates(unit, admission, patient):
    candidates = []
    for bed in unit_beds(unit["id"]):
        if bed["status"] != "AVAILABLE":
            continue
        if not bed_type_ok(bed, admission):
            continue
        if not cohort_ok(unit, bed, patient):
            continue
        candidates.append(bed)
    candidates.sort(key=lambda b: bed_rank(b, admission))
    return candidates


def select_bed(unit, admission, patient):
    candidates = bed_candidates(unit, admission, patient)
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------- #
# queued_admission_promotion
# --------------------------------------------------------------------------- #
ACUITY_RANK = {"HIGH": 3, "MODERATE": 2, "LOW": 1}


def promotion_queue(unit_id):
    queue = [
        adm
        for adm in db.admissions.values()
        if adm["unit_id"] == unit_id
        and adm["placement_status"] == "PENDING_PLACEMENT"
        and adm["safety_search_status"] == "COMPLETED"
    ]
    queue.sort(
        key=lambda a: (
            -ACUITY_RANK.get(a["acuity_tier"], 0),
            a["created_at"],
            _patient_of(a).get("mrn") or "",
        )
    )
    return queue


# --------------------------------------------------------------------------- #
# discharge_request_response_deadline
# --------------------------------------------------------------------------- #
BUSINESS_HOURS_BUDGET = 24


def discharge_request_response_deadline(requested_at):
    return business_hours_deadline(requested_at, BUSINESS_HOURS_BUDGET)


# --------------------------------------------------------------------------- #
# follow_up_guarantee_window
# --------------------------------------------------------------------------- #
DAYS_INVOLUNTARY_HIGH = 7
DAYS_INVOLUNTARY_OTHER = 10
DAYS_VOLUNTARY = 14
MINOR_CEILING_DAYS = 5


def follow_up_guarantee_days(admission, patient):
    if admission["legal_status"] == "INVOLUNTARY":
        base = DAYS_INVOLUNTARY_HIGH if admission["acuity_tier"] == "HIGH" else DAYS_INVOLUNTARY_OTHER
    else:
        base = DAYS_VOLUNTARY
    if patient.get("is_minor"):
        return min(base, MINOR_CEILING_DAYS)
    return base


def follow_up_guarantee_deadline(now, days):
    return now + timedelta(hours=24 * days)


# --------------------------------------------------------------------------- #
# advocate docket
# --------------------------------------------------------------------------- #
DOCKET_BUFFER_MINUTES = 30


def booked_docket_minutes(clinician_id):
    return sum(
        h["duration_minutes"]
        for h in db.hearings.values()
        if h["advocate_clinician_id"] == clinician_id and h["status"] == "SCHEDULED"
    )


def docket_conflict(advocate_id, new_start, new_end):
    buffer_delta = timedelta(minutes=DOCKET_BUFFER_MINUTES)
    for hearing in sorted(db.hearings.values(), key=sort_key):
        if hearing["advocate_clinician_id"] != advocate_id:
            continue
        if hearing["status"] != "SCHEDULED":
            continue
        existing_start = hearing["scheduled_start_at"]
        existing_end = hearing["scheduled_end_at"]
        if (new_start - buffer_delta) < existing_end and existing_start < (new_end + buffer_delta):
            return True
    return False
