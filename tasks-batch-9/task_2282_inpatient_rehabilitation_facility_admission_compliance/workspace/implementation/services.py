"""Domain services: derived fields, state cascades, calculations.

Every rule here traces to PRD §2.6-§2.11 and §3.1-§3.9.
"""

from datetime import timedelta
from decimal import Decimal

from db import store
from errors import ApiError
from util import (add_days, cents, date_of, dt_of, iso, midnight, num2,
                  parse_date, pct2, round_half_up)

# ------------------------------------------------------------------ constants ---
CREDENTIALS = ("REHAB_PHYSICIAN", "NURSE", "THERAPIST_PT", "THERAPIST_OT", "THERAPIST_SLP", "CODER")
COMORBIDITY_TIERS = ("NONE", "TIER_3", "TIER_2", "TIER_1")
DISCIPLINES = ("PT", "OT", "SLP")
MODALITIES = ("INDIVIDUAL", "CONCURRENT", "GROUP")
DISCHARGE_DESTINATIONS = ("COMMUNITY", "SNF", "ACUTE_CARE", "LTCH", "ANOTHER_IRF", "EXPIRED",
                          "AGAINST_MEDICAL_ADVICE")
THREE_HOUR_MODES = ("DAILY_3HR", "WEEKLY_15HR")
ASSESSMENT_TYPES = ("ADMISSION", "DISCHARGE")
REVIEW_METHODS = ("PRESUMPTIVE", "MEDICAL_REVIEW")

DISCIPLINE_CREDENTIAL = {"PT": "THERAPIST_PT", "OT": "THERAPIST_OT", "SLP": "THERAPIST_SLP"}

# three-hour rule (PRD §3.6)
DAILY_MIN_MINUTES = 180
REQUIRED_QUALIFYING_DAYS = 5
WEEKLY_MIN_MINUTES = 900
CONCURRENT_DIVISOR = 2

# screening / plan windows (PRD §3.3, §3.5)
SCREENING_WINDOW_HOURS = 48
POC_SIGNATURE_DEADLINE_HOURS = 96

# posture (PRD §2.8)
POSTURE_MIN_COHORT = 2
FREEZE_MARGIN_PCT = Decimal("20.00")

# pricing (PRD §3.8)
CMG_TIER_BY_IGC = {"0008": "TIER_B", "0110": "TIER_C", "0704": "TIER_A", "1101": "TIER_A"}
CMG_TIER_DEFAULT = "TIER_A"
CMG_BASE_CENTS = {"TIER_A": 1800000, "TIER_B": 2450000, "TIER_C": 3120000}
AVG_LOS_DAYS = {"TIER_A": 9, "TIER_B": 12, "TIER_C": 15}
COMORBIDITY_UPLIFT = {"NONE": Decimal("0.00"), "TIER_3": Decimal("0.03"),
                      "TIER_2": Decimal("0.06"), "TIER_1": Decimal("0.12")}
SHORT_STAY_MAX_DAYS = 3
SHORT_STAY_FACTOR = Decimal("0.35")
TRANSFER_DESTINATIONS = ("SNF", "ACUTE_CARE", "LTCH", "ANOTHER_IRF")
INTERRUPTION_MAX_GAP_DAYS = 3

# presumptive compliance (PRD §3.9)
PRESUMPTIVE_IGC_SET = ("0008", "0110", "0704", "1101")
PRESUMPTIVE_DX_SET = ("I63.9", "S72.001A")

# quality reporting (PRD §3.9)
COMPLETENESS_THRESHOLD_PCT = Decimal("95.00")
QRP_PENALTY_PCT = 2.00

# assessment deadlines (PRD §3.9)
ADMISSION_REFERENCE_OFFSET_DAYS = 3
ADMISSION_COMPLETION_OFFSET_DAYS = 4
DISCHARGE_COMPLETION_OFFSET_DAYS = 5
TRANSMISSION_OFFSET_DAYS = 17
MISSED_GRACE_DAYS = 30


# ------------------------------------------------------------------ plumbing ---
def now():
    return store.clock


def stamp_new(entity):
    """Attach the four common system properties (PRD §2.4)."""
    entity["id"] = store.new_id()
    entity["created_at"] = iso(store.clock)
    entity["updated_at"] = iso(store.clock)
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    return entity


def touch(entity):
    entity["updated_at"] = iso(store.clock)
    entity["version"] = entity["version"] + 1
    return entity


def by_seq(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def lookup(collection, identifier):
    if identifier is None:
        return None
    return collection.get(identifier)


def require(collection, identifier):
    found = lookup(collection, identifier)
    if found is None:
        raise ApiError("ERR_NOT_FOUND")
    return found


# ------------------------------------------------------------ collection reads ---
def weeks_of(admission_id):
    return by_seq([w for w in store.weeks.values() if w["admission_id"] == admission_id])


def sessions_of_week(week_id):
    return by_seq([s for s in store.sessions.values() if s["therapy_week_id"] == week_id])


def sessions_of_admission(admission_id):
    return by_seq([s for s in store.sessions.values() if s["admission_id"] == admission_id])


def conferences_of_week(week_id):
    return by_seq([c for c in store.conferences.values() if c["therapy_week_id"] == week_id])


def plans_of(admission_id):
    return by_seq([p for p in store.plans.values() if p["admission_id"] == admission_id])


def active_plan(admission_id):
    for plan in plans_of(admission_id):
        if plan["status"] == "ACTIVE":
            return plan
    return None


def admissions_of_facility(facility_id):
    return by_seq([a for a in store.admissions.values() if a["facility_id"] == facility_id])


def screenings_of_facility(facility_id):
    result = []
    for screening in store.screenings.values():
        patient = store.patients.get(screening["patient_id"])
        if patient is not None and patient["facility_id"] == facility_id:
            result.append(screening)
    return by_seq(result)


def assessments_of_admission(admission_id):
    return by_seq([a for a in store.assessments.values() if a["admission_id"] == admission_id])


# ------------------------------------------------------- therapy week counters ---
def week_window_dates(week):
    """The seven inclusive calendar dates of the window (PRD §3.6)."""
    start = parse_date(week["week_start_date"])
    return [add_days(start, offset) for offset in range(7)]


def refresh_week_counters(week):
    """PRD §3.6 — seven inclusive dates, DELIVERED sessions only."""
    per_day = {}
    for session in sessions_of_week(week["id"]):
        if session["status"] != "DELIVERED":
            continue
        per_day[session["session_date"]] = per_day.get(session["session_date"], 0) + session["credited_minutes"]
    dates = [d.isoformat() for d in week_window_dates(week)]
    delivered = sum(per_day.get(d, 0) for d in dates)
    qualifying = sum(1 for d in dates if per_day.get(d, 0) >= DAILY_MIN_MINUTES)
    changed = (week["delivered_credited_minutes"] != delivered
               or week["qualifying_days_count"] != qualifying)
    week["delivered_credited_minutes"] = delivered
    week["qualifying_days_count"] = qualifying
    return changed


def week_verdict(week):
    if week["evaluation_mode"] == "WEEKLY_15HR":
        return "MET" if week["delivered_credited_minutes"] >= WEEKLY_MIN_MINUTES else "NOT_MET"
    return "MET" if week["qualifying_days_count"] >= REQUIRED_QUALIFYING_DAYS else "NOT_MET"


def credited_minutes_for(modality, raw_minutes, group_size):
    """PRD §2.6 / §3.6 — floor per session, never after summing."""
    if modality == "INDIVIDUAL":
        return raw_minutes
    if modality == "CONCURRENT":
        return raw_minutes // CONCURRENT_DIVISOR
    return raw_minutes // group_size


# ------------------------------------------------- admission derived fields ---
def poc_signed_within_deadline(admission):
    admitted_at = dt_of(admission.get("admitted_at"))
    if admitted_at is None:
        return False
    plans = plans_of(admission["id"])
    if not plans:
        return False
    earliest = plans[0]
    signed_at = dt_of(earliest["signed_at"])
    if signed_at is None:
        return False
    return signed_at <= admitted_at + timedelta(hours=POC_SIGNATURE_DEADLINE_HOURS)


def therapy_weeks_satisfied(admission):
    weeks = weeks_of(admission["id"])
    if not weeks:
        return False
    return all(w["status"] in ("MET", "EXCEPTION_GRANTED") for w in weeks)


def conference_compliant(admission):
    weeks = weeks_of(admission["id"])
    if not weeks:
        return False
    for week in weeks:
        if not any(c["status"] == "RECORDED" for c in conferences_of_week(week["id"])):
            return False
    return True


def compliance_class_of(admission):
    """PRD §3.8 — ordered ladder."""
    if admission["stay_status"] == "ADMISSION_DENIED":
        return "EXCLUDED"
    if admission["stay_status"] != "DISCHARGED":
        return "PENDING_EVALUATION"
    if admission["discharge_destination"] == "EXPIRED":
        return "EXCLUDED"
    if (admission["screening_compliant"] and admission["poc_signed_within_deadline"]
            and admission["therapy_weeks_satisfied"] and admission["conference_compliant"]):
        return "QUALIFYING"
    return "NON_QUALIFYING"


def total_credited_minutes(admission):
    return sum(w["delivered_credited_minutes"] for w in weeks_of(admission["id"]))


def recompute_admission_derived(admission):
    """Refresh every derived documentation field.  Returns True when anything moved."""
    before = (admission["therapy_weeks_satisfied"], admission["conference_compliant"],
              admission["poc_signed_within_deadline"], admission["total_credited_minutes"],
              admission["compliance_class"])
    admission["therapy_weeks_satisfied"] = therapy_weeks_satisfied(admission)
    admission["conference_compliant"] = conference_compliant(admission)
    admission["poc_signed_within_deadline"] = poc_signed_within_deadline(admission)
    admission["total_credited_minutes"] = total_credited_minutes(admission)
    admission["compliance_class"] = compliance_class_of(admission)
    after = (admission["therapy_weeks_satisfied"], admission["conference_compliant"],
             admission["poc_signed_within_deadline"], admission["total_credited_minutes"],
             admission["compliance_class"])
    return before != after


def propagate_admission(admission, force_admission_touch=False, force_facility_touch=False):
    """Recompute the admission's derived fields and lift the result to the facility.

    Implements the tail of the cascade chain of PRD §2.11 / §3.8 hops 2-4.
    """
    changed = recompute_admission_derived(admission)
    if changed or force_admission_touch:
        touch(admission)
    facility = store.facilities.get(admission["facility_id"])
    if facility is not None:
        recompute_facility(facility, force_touch=force_facility_touch)
    return changed


# --------------------------------------------------- facility cohort / posture ---
def provisional_cohort(facility):
    """PRD §3.8 hop 3 — bounded by the facility's own review period."""
    cohort = []
    for admission in admissions_of_facility(facility["id"]):
        if admission["stay_status"] != "DISCHARGED":
            continue
        if admission["compliance_class"] == "EXCLUDED":
            continue
        discharge_date = date_of(admission.get("discharged_at"))
        if discharge_date is None:
            continue
        if not (facility["review_period_start"] <= discharge_date.isoformat()
                <= facility["review_period_end"]):
            continue
        cohort.append(admission)
    return cohort


def latest_certified_review(facility):
    certified = [r for r in store.reviews.values()
                 if r["facility_id"] == facility["id"] and r["status"] == "CERTIFIED"]
    if not certified:
        return None
    return sorted(certified, key=lambda r: (r["certified_at"], r["created_at"], r["_seq"]))[-1]


def derive_posture(facility):
    """PRD §2.8 — ordered ladder; both percentage comparisons are strict."""
    review = latest_certified_review(facility)
    if review is not None and review["outcome"] == "FAIL":
        return "ADMISSION_FREEZE"
    threshold = Decimal(str(facility["compliance_threshold_pct"]))
    provisional = Decimal(str(facility["provisional_compliance_pct"]))
    if facility["cohort_total_count"] >= POSTURE_MIN_COHORT:
        if provisional < threshold - FREEZE_MARGIN_PCT:
            return "ADMISSION_FREEZE"
        if provisional < threshold:
            return "THRESHOLD_WATCH"
    return "OPEN"


def apply_posture_cascade(facility, previous_posture):
    """PRD §2.8 / §3.8 hop 4 — freeze or release SUBMITTED / ON_HOLD screenings."""
    new_posture = facility["posture"]
    if new_posture == previous_posture:
        return
    if new_posture == "ADMISSION_FREEZE":
        for screening in screenings_of_facility(facility["id"]):
            if screening["status"] == "SUBMITTED":
                screening["status"] = "ON_HOLD"
                touch(screening)
    elif previous_posture == "ADMISSION_FREEZE":
        for screening in screenings_of_facility(facility["id"]):
            if screening["status"] == "ON_HOLD":
                screening["status"] = "SUBMITTED"
                touch(screening)


def recompute_settled_payment(facility):
    total = 0
    for admission in admissions_of_facility(facility["id"]):
        if admission["payment_status"] == "PRICED":
            total += admission["total_payment_cents"]
    facility["settled_payment_cents"] = total


def recompute_facility(facility, force_touch=False, recompute_settled=False):
    """Recompute cohort figures, posture and (optionally) settled payment.

    Bumps the facility's version once when anything actually changed, or when the
    caller's endpoint contract declares an unconditional bump.
    """
    before = (facility["cohort_total_count"], facility["cohort_qualifying_count"],
              facility["provisional_compliance_pct"], facility["posture"],
              facility["settled_payment_cents"], facility["certified_compliance_pct"])
    previous_posture = facility["posture"]

    cohort = provisional_cohort(facility)
    facility["cohort_total_count"] = len(cohort)
    facility["cohort_qualifying_count"] = sum(1 for a in cohort if a["compliance_class"] == "QUALIFYING")
    facility["provisional_compliance_pct"] = pct2(facility["cohort_qualifying_count"],
                                                  facility["cohort_total_count"])
    if recompute_settled:
        recompute_settled_payment(facility)
    facility["posture"] = derive_posture(facility)
    apply_posture_cascade(facility, previous_posture)

    after = (facility["cohort_total_count"], facility["cohort_qualifying_count"],
             facility["provisional_compliance_pct"], facility["posture"],
             facility["settled_payment_cents"], facility["certified_compliance_pct"])
    if force_touch or before != after:
        touch(facility)


# ------------------------------------------------------- interrupted stay chain ---
def chain_head(admission):
    current = admission
    seen = set()
    while current.get("predecessor_admission_id"):
        if current["id"] in seen:
            break
        seen.add(current["id"])
        parent = store.admissions.get(current["predecessor_admission_id"])
        if parent is None:
            break
        current = parent
    return current


def chain_from_head(head):
    """[head] + continuations ordered by admitted_at ASC (PRD §3.8 step one)."""
    chain = [head]
    current = head
    while True:
        continuations = [a for a in store.admissions.values()
                         if a.get("predecessor_admission_id") == current["id"]]
        if not continuations:
            break
        continuations = sorted(continuations,
                               key=lambda a: (a.get("admitted_at") or "", a["_seq"]))
        current = continuations[0]
        chain.append(current)
    return chain


def price_chain(head):
    """The five-step waterfall of PRD §3.8.  Returns (effective_los_days, cents)."""
    chain = chain_from_head(head)
    last = chain[-1]

    head_admit_date = date_of(head["admitted_at"])
    last_discharge_date = date_of(last["discharged_at"])
    span_days = (last_discharge_date - head_admit_date).days + 1

    interruption_days = 0
    for previous, following in zip(chain, chain[1:]):
        interruption_days += (date_of(following["admitted_at"]) - date_of(previous["discharged_at"])).days
    effective_los_days = span_days - interruption_days

    tier = head["cmg_tier"] or CMG_TIER_DEFAULT
    patient = store.patients.get(head["patient_id"])
    comorbidity = patient["comorbidity_tier"] if patient else "NONE"

    # step 2 — base rate with comorbidity uplift, rounded first
    uplifted_base = cents(Decimal(CMG_BASE_CENTS[tier]) * (Decimal(1) + COMORBIDITY_UPLIFT[comorbidity]))

    # step 3 — short-stay factor
    los_factor = SHORT_STAY_FACTOR if effective_los_days <= SHORT_STAY_MAX_DAYS else Decimal("1.00")
    adjusted_base = cents(Decimal(uplifted_base) * los_factor)

    # step 4 — transfer per-diem cap
    average_los = AVG_LOS_DAYS[tier]
    transfer_applies = (last["discharge_destination"] in TRANSFER_DESTINATIONS
                        and effective_los_days < average_los)
    if transfer_applies:
        per_diem = cents(Decimal(adjusted_base) / Decimal(average_los))
        transfer_amount = cents(Decimal(per_diem) * (Decimal(effective_los_days) + Decimal("0.5")))
        gross = min(adjusted_base, transfer_amount)
    else:
        gross = adjusted_base

    # step 5 — quality-reporting reduction from the head's admit-time snapshot
    snapshot = Decimal(str(head["qrp_penalty_pct_snapshot"] or 0))
    total = cents(Decimal(gross) * (Decimal(1) - snapshot / Decimal(100)))
    return effective_los_days, total


def chain_fully_discharged(head):
    return all(a["stay_status"] == "DISCHARGED" for a in chain_from_head(head))


# ------------------------------------------------------------ compliance review ---
def review_cohort(review):
    """PRD §3.9 — discharged, in period, not EXCLUDED."""
    cohort = []
    for admission in admissions_of_facility(review["facility_id"]):
        if admission["stay_status"] != "DISCHARGED":
            continue
        if admission["compliance_class"] == "EXCLUDED":
            continue
        discharge_date = date_of(admission.get("discharged_at"))
        if discharge_date is None:
            continue
        if not (review["period_start"] <= discharge_date.isoformat() <= review["period_end"]):
            continue
        cohort.append(admission)
    return cohort


def qualifies_under(review, admission):
    if review["method"] == "PRESUMPTIVE":
        patient = store.patients.get(admission["patient_id"])
        if patient is None:
            return False
        if patient["impairment_group_code"] in PRESUMPTIVE_IGC_SET:
            return True
        return (patient["etiologic_diagnosis_code"] in PRESUMPTIVE_DX_SET
                and patient["comorbidity_tier"] in ("TIER_1", "TIER_2"))
    return admission["compliance_class"] == "QUALIFYING"


def invalidate_reviews_for(admission, reason):
    """PRD §3.4 — COMPUTED reviews whose cohort contains this admission go STALE."""
    facility = store.facilities.get(admission["facility_id"])
    if facility is None:
        return
    for review in by_seq([r for r in store.reviews.values()
                          if r["facility_id"] == facility["id"] and r["status"] == "COMPUTED"]):
        if any(member["id"] == admission["id"] for member in review_cohort(review)):
            review["status"] = "STALE"
            review["stale_reason"] = reason
            touch(review)
            if facility.get("_certified_source_review_id") == review["id"]:
                facility["certified_compliance_pct"] = None
                facility["_certified_source_review_id"] = None


# ------------------------------------------------------------- quality reporting ---
def qrp_metrics(qrp):
    cohort = []
    for admission in admissions_of_facility(qrp["facility_id"]):
        if admission["stay_status"] != "DISCHARGED":
            continue
        discharge_date = date_of(admission.get("discharged_at"))
        if discharge_date is None:
            continue
        if not (qrp["reporting_period_start"] <= discharge_date.isoformat()
                <= qrp["reporting_period_end"]):
            continue
        cohort.append(admission)

    timely = 0
    for admission in cohort:
        for assessment in assessments_of_admission(admission["id"]):
            if assessment["assessment_type"] == "DISCHARGE" and assessment["status"] == "TRANSMITTED":
                timely += 1
                break

    cohort_count = len(cohort)
    completeness = pct2(timely, cohort_count)
    penalty = 0.00 if Decimal(str(completeness)) >= COMPLETENESS_THRESHOLD_PCT else QRP_PENALTY_PCT
    return cohort_count, timely, num2(completeness), num2(penalty)


# ------------------------------------------------------------ assessment deadlines ---
def assessment_deadlines(admission, assessment_type):
    if assessment_type == "ADMISSION":
        reference = add_days(date_of(admission["admitted_at"]), ADMISSION_REFERENCE_OFFSET_DAYS)
        completion = midnight(add_days(reference, ADMISSION_COMPLETION_OFFSET_DAYS))
    else:
        reference = date_of(admission["discharged_at"])
        completion = midnight(add_days(reference, DISCHARGE_COMPLETION_OFFSET_DAYS))
    transmission = midnight(add_days(completion.date(), TRANSMISSION_OFFSET_DAYS))
    return reference.isoformat(), completion, transmission


# --------------------------------------------------------------- clock sweeps ---
def run_clock_sweeps():
    """PRD §3.2 and §3.9 — the two sweeps that run on every clock movement."""
    expired = 0
    for screening in by_seq(list(store.screenings.values())):
        if screening["status"] not in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "ON_HOLD"):
            continue
        conducted_at = dt_of(screening["conducted_at"])
        if conducted_at + timedelta(hours=SCREENING_WINDOW_HOURS) <= store.clock:
            screening["status"] = "EXPIRED"
            touch(screening)
            expired += 1

    missed = 0
    for assessment in by_seq(list(store.assessments.values())):
        if assessment["status"] not in ("DRAFT", "COMPLETED"):
            continue
        deadline = dt_of(assessment["transmission_deadline_at"])
        if deadline + timedelta(days=MISSED_GRACE_DAYS) <= store.clock:
            assessment["status"] = "MISSED"
            touch(assessment)
            missed += 1
    return expired, missed
