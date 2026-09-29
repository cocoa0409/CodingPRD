"""Pinned constants, the eleven calculations, derived-field recomputation and
per-entity serialisation."""
from decimal import ROUND_HALF_UP, Decimal

from store import (
    by_created,
    clock_date,
    date_in_month,
    days_in_month,
    month_bounds,
    order_key,
    parse_date,
    store,
)

# ------------------------------------------------------------- constants ----
CARE_LEVELS = ("NURSING", "DOMICILIARY", "ADULT_DAY_HEALTH")
PER_DIEM_RATE_CENTS = {"NURSING": 11857, "DOMICILIARY": 5502, "ADULT_DAY_HEALTH": 4230}
BED_HOLD_RATE_BPS = 5000
BED_HOLD_PAYABLE_DAYS_PER_MONTH = 10
BED_HOLD_MAX_DAYS = 30

COUNTABLE_RATE_BPS = {
    "SSA": 10000,
    "VA_PENSION": 0,
    "VA_COMPENSATION": 8000,
    "MILITARY_RETIREMENT": 10000,
    "OTHER": 10000,
}
INCOME_TYPES = tuple(COUNTABLE_RATE_BPS.keys())
COST_SHARE_TIER_BOUNDS_CENTS = [100000, 250000]
COST_SHARE_TIER_BPS = [4000, 5500, 7000]
MEDICAL_CAP_BY_TIER_CENTS = {"TIER_1": 5000, "TIER_2": 15000, "TIER_3": 30000}
FEDERAL_OFFSET_SHARE_BPS = 500
FEDERAL_OFFSET_CAP_BPS = 3000

CLASS_BASE_POINTS = {"CLASS_1": 1000, "CLASS_2": 700, "CLASS_3": 400, "CLASS_4": 100}
CLASS_1_DISABILITY_PCT_THRESHOLD = 70
CLASS_2_RESIDENCY_YEARS_THRESHOLD = 5
CLASS_3_RESIDENCY_YEARS_THRESHOLD = 2
DISABILITY_POINTS_PER_PCT = 3
RESIDENCY_POINTS_PER_YEAR = 5
RESIDENCY_POINTS_CAP_YEARS = 20
ADL_POINTS_PER_DEPENDENCY = 20
COGNITIVE_IMPAIRMENT_POINTS = 40
BEHAVIORAL_RISK_POINTS = -30
TENURE_POINTS_PER_DAY = 1
TENURE_POINTS_CAP_DAYS = 365
DECLINED_OFFER_PENALTY_POINTS = 25

SCOPE_WEIGHT = {"ISOLATED": 1, "PATTERN": 2, "WIDESPREAD": 4}
SEVERITY_WEIGHT = {"MINIMAL": 1, "MINIMAL_HARM": 3, "ACTUAL_HARM": 8, "IMMEDIATE_JEOPARDY": 20}
CERTIFICATION_CONDITIONAL_THRESHOLD = 1
CERTIFICATION_DECERTIFY_THRESHOLD = 25

OFFER_WINDOW_DAYS = 7
MAX_DECLINED_OFFERS = 3
MAX_REDETERMINATIONS = 2
CARE_PLAN_REVIEW_DAYS = 90

DISCHARGE_CHARACTERS = (
    "HONORABLE",
    "GENERAL",
    "OTHER_THAN_HONORABLE",
    "BAD_CONDUCT",
    "DISHONORABLE",
)
QUALIFYING_DISCHARGES = ("HONORABLE", "GENERAL")
MIN_SERVICE_DAYS = 90
MIN_RESIDENCY_YEARS = 1
NURSING_MIN_SKILLED_HOURS = 2.00


def round_half_up(numerator, denominator):
    """Integer cents from numerator/denominator, rounded half up."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount, bps):
    return round_half_up(Decimal(amount) * Decimal(bps), 10000)


# ------------------------------------------------- care unit derivations ----
def unit_residents(unit_id):
    return [r for r in store.residents.values() if r["care_unit_id"] == unit_id]


def occupied_bed_count(unit):
    return sum(
        1
        for r in store.residents.values()
        if r["care_unit_id"] == unit["id"] and r["occupancy_status"] == "ADMITTED"
    )


def held_bed_count(unit):
    return sum(
        1
        for r in store.residents.values()
        if r["care_unit_id"] == unit["id"]
        and r["occupancy_status"] == "HOSPITALIZED"
        and r["bed_hold_days_used"] < BED_HOLD_MAX_DAYS
    )


def available_bed_count(unit):
    return (
        unit["licensed_bed_count"]
        - unit["out_of_service_bed_count"]
        - occupied_bed_count(unit)
        - held_bed_count(unit)
    )


def waitlist_active_count(unit):
    return sum(
        1
        for w in store.waitlist_entries.values()
        if w["care_unit_id"] == unit["id"] and w["status"] in ("ACTIVE", "OFFERED")
    )


def operational_posture(unit):
    if unit["certification_status"] == "DECERTIFIED":
        return "FROZEN"
    if unit["certification_status"] == "CONDITIONAL":
        return "RESTRICTED"
    if available_bed_count(unit) <= 0:
        return "RESTRICTED"
    return "OPEN"


# ------------------------------------------------------ home derivations ----
def home_units(home_id):
    return [u for u in store.care_units.values() if u["veterans_home_id"] == home_id]


def active_resident_count(home):
    unit_ids = set(u["id"] for u in home_units(home["id"]))
    return sum(
        1
        for r in store.residents.values()
        if r["care_unit_id"] in unit_ids and r["occupancy_status"] in ("ADMITTED", "HOSPITALIZED")
    )


def decertified_unit_count(home):
    return sum(1 for u in home_units(home["id"]) if u["certification_status"] == "DECERTIFIED")


def recognition_suspended_reason(home):
    return "UNIT_DECERTIFIED" if home["recognition_status"] == "SUSPENDED" else None


def home_of_unit(unit):
    return store.homes.get(unit["veterans_home_id"])


def home_of_resident(resident):
    unit = store.care_units.get(resident["care_unit_id"])
    return home_of_unit(unit) if unit else None


# --------------------------------------------------- applicant priority ----
def compute_priority_class(applicant):
    if (
        applicant["service_connected_disability_pct"] >= CLASS_1_DISABILITY_PCT_THRESHOLD
        or applicant["nursing_care_for_service_connected"]
    ):
        return "CLASS_1"
    if (
        applicant["wartime_service"]
        and applicant["state_residency_years"] >= CLASS_2_RESIDENCY_YEARS_THRESHOLD
    ):
        return "CLASS_2"
    if applicant["state_residency_years"] >= CLASS_3_RESIDENCY_YEARS_THRESHOLD:
        return "CLASS_3"
    return "CLASS_4"


def compute_acuity_points(assessment):
    points = min(assessment["adl_dependency_count"], 6) * ADL_POINTS_PER_DEPENDENCY
    if assessment["cognitive_impairment"]:
        points += COGNITIVE_IMPAIRMENT_POINTS
    if assessment["behavioral_risk_flag"]:
        points += BEHAVIORAL_RISK_POINTS
    return points


def acuity_assessment(applicant_id):
    """The applicant's SUBMITTED/ACCEPTED assessment with the greatest created_at."""
    rows = [
        a
        for a in store.assessments.values()
        if a["applicant_id"] == applicant_id and a["status"] in ("SUBMITTED", "ACCEPTED")
    ]
    if not rows:
        return None
    return max(rows, key=order_key)


def compute_priority_score(applicant):
    priority_class = applicant.get("priority_class")
    if priority_class is None:
        return 0
    base = CLASS_BASE_POINTS[priority_class]
    disability_pts = min(applicant["service_connected_disability_pct"], 100) * DISABILITY_POINTS_PER_PCT
    residency_pts = (
        min(applicant["state_residency_years"], RESIDENCY_POINTS_CAP_YEARS) * RESIDENCY_POINTS_PER_YEAR
    )
    assessment = acuity_assessment(applicant["id"])
    acuity_pts = compute_acuity_points(assessment) if assessment else 0
    received = parse_date(applicant["application_received_date"])
    tenure_days = (clock_date() - received).days
    tenure_pts = min(max(tenure_days, 0), TENURE_POINTS_CAP_DAYS) * TENURE_POINTS_PER_DAY
    penalty = applicant["declined_offer_count"] * DECLINED_OFFER_PENALTY_POINTS
    raw = base + disability_pts + residency_pts + acuity_pts + tenure_pts - penalty
    return max(base, raw)


# ----------------------------------------------------- trust fund ledger ----
def resident_transactions(resident_id):
    rows = [t for t in store.transactions.values() if t["resident_id"] == resident_id]
    return sorted(rows, key=lambda t: (t["effective_date"], t["created_at"], t["_seq"]))


def balance_map(resident_id):
    """{txn_id: balance_after_cents} replayed in (effective_date, created_at) order."""
    running = 0
    out = {}
    for txn in resident_transactions(resident_id):
        running += txn["signed_amount_cents"]
        out[txn["id"]] = running
    return out


def trust_fund_balance(resident_id):
    running = 0
    for txn in resident_transactions(resident_id):
        running += txn["signed_amount_cents"]
    return running


def is_reversed(txn):
    return any(
        other["reverses_transaction_id"] == txn["id"] for other in store.transactions.values()
    )


# ------------------------------------------------ cost share derivations ----
def resident_determinations(resident_id):
    return [d for d in store.determinations.values() if d["resident_id"] == resident_id]


def governing_determination(resident_id, month):
    candidates = [d for d in resident_determinations(resident_id) if d["effective_month"] == month]
    if not candidates:
        return None
    finals = [d for d in candidates if d["variant"] == "FINAL"]
    pool = finals if finals else candidates
    return max(pool, key=order_key)


def mirrored_cost_share(resident):
    """Governing cost share for the clock month, else the most recent earlier month."""
    target = "%04d-%02d" % (clock_date().year, clock_date().month)
    governing = governing_determination(resident["id"], target)
    if governing is not None:
        return governing["monthly_cost_share_cents"]
    earlier = [
        d["effective_month"]
        for d in resident_determinations(resident["id"])
        if d["effective_month"] < target
    ]
    if not earlier:
        return 0
    governing = governing_determination(resident["id"], max(earlier))
    return governing["monthly_cost_share_cents"] if governing else 0


def bed_hold_active(resident):
    return (
        resident["occupancy_status"] == "HOSPITALIZED"
        and resident["bed_hold_days_used"] < BED_HOLD_MAX_DAYS
    )


# -------------------------------------------------- census / claim rates ----
def payable_rate_for(care_level, census_class):
    rate = PER_DIEM_RATE_CENTS[care_level]
    if census_class == "RESIDENT_DAY":
        return rate
    if census_class == "BED_HOLD_DAY":
        return apply_bps(rate, BED_HOLD_RATE_BPS)
    return 0


def census_day_claimed(day):
    claim_id = day.get("per_diem_claim_id")
    if not claim_id:
        return False
    claim = store.claims.get(claim_id)
    return bool(claim) and claim["status"] in ("SUBMITTED", "PAID")


def survey_compliance_score(deficiencies):
    return sum(
        SCOPE_WEIGHT[d["scope"]] * SEVERITY_WEIGHT[d["severity"]] for d in deficiencies
    )


def survey_outcome(deficiencies, current_status):
    score = survey_compliance_score(deficiencies)
    if any(d["severity"] == "IMMEDIATE_JEOPARDY" for d in deficiencies):
        return score, "DECERTIFIED"
    if score >= CERTIFICATION_DECERTIFY_THRESHOLD:
        return score, "DECERTIFIED"
    if score >= CERTIFICATION_CONDITIONAL_THRESHOLD:
        return score, "CONDITIONAL"
    return score, "CONDITIONAL" if current_status == "DECERTIFIED" else "CERTIFIED"


# ------------------------------------------------------------ serialisers ----
def _common(rec, out, versioned=True):
    out["id"] = rec["id"]
    out["created_at"] = rec["created_at"]
    if versioned:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def home_out(home):
    out = {
        "name": home["name"],
        "state_code": home["state_code"],
        "recognition_status": home["recognition_status"],
        "recognition_effective_date": home["recognition_effective_date"],
        "personal_needs_allowance_monthly_cents": home["personal_needs_allowance_monthly_cents"],
        "last_survey_date": home["last_survey_date"],
        "active_resident_count": active_resident_count(home),
        "decertified_unit_count": decertified_unit_count(home),
        "recognition_suspended_reason": recognition_suspended_reason(home),
    }
    return _common(home, out)


def unit_out(unit):
    out = {
        "veterans_home_id": unit["veterans_home_id"],
        "unit_name": unit["unit_name"],
        "care_level": unit["care_level"],
        "licensed_bed_count": unit["licensed_bed_count"],
        "out_of_service_bed_count": unit["out_of_service_bed_count"],
        "certification_status": unit["certification_status"],
        "last_survey_compliance_score": unit["last_survey_compliance_score"],
        "last_survey_date": unit["last_survey_date"],
        "occupied_bed_count": occupied_bed_count(unit),
        "held_bed_count": held_bed_count(unit),
        "available_bed_count": available_bed_count(unit),
        "waitlist_active_count": waitlist_active_count(unit),
        "operational_posture": operational_posture(unit),
        "per_diem_rate_cents": PER_DIEM_RATE_CENTS[unit["care_level"]],
    }
    return _common(unit, out)


def applicant_out(applicant):
    out = {
        "veterans_home_id": applicant["veterans_home_id"],
        "full_name": applicant["full_name"],
        "date_of_birth": applicant["date_of_birth"],
        "service_days": applicant["service_days"],
        "discharge_character": applicant["discharge_character"],
        "wartime_service": applicant["wartime_service"],
        "service_connected_disability_pct": applicant["service_connected_disability_pct"],
        "nursing_care_for_service_connected": applicant["nursing_care_for_service_connected"],
        "state_residency_years": applicant["state_residency_years"],
        "requested_care_level": applicant["requested_care_level"],
        "application_received_date": applicant["application_received_date"],
        "status": applicant["status"],
        "eligibility_reason_code": applicant["eligibility_reason_code"],
        "priority_class": applicant["priority_class"],
        "priority_score": applicant["priority_score"],
        "declined_offer_count": applicant["declined_offer_count"],
        "redetermination_count": applicant["redetermination_count"],
        "decided_by_user_id": applicant["decided_by_user_id"],
        "decision_note": applicant["decision_note"],
    }
    return _common(applicant, out)


def waitlist_out(entry):
    out = {
        "applicant_id": entry["applicant_id"],
        "care_unit_id": entry["care_unit_id"],
        "status": entry["status"],
        "listed_at": entry["listed_at"],
        "offer_expires_at": entry["offer_expires_at"],
        "priority_class_snapshot": entry["priority_class_snapshot"],
        "rank_score_snapshot": entry["rank_score_snapshot"],
        "queue_position": entry["queue_position"],
    }
    return _common(entry, out)


def assessment_out(assessment):
    out = {
        "applicant_id": assessment["applicant_id"],
        "assessed_care_level": assessment["assessed_care_level"],
        "adl_dependency_count": assessment["adl_dependency_count"],
        "cognitive_impairment": assessment["cognitive_impairment"],
        "behavioral_risk_flag": assessment["behavioral_risk_flag"],
        "skilled_nursing_hours_per_day": assessment["skilled_nursing_hours_per_day"],
        "assessment_date": assessment["assessment_date"],
        "assessor_user_id": assessment["assessor_user_id"],
        "status": assessment["status"],
        "acuity_points": assessment["acuity_points"],
        "rejection_reason": assessment["rejection_reason"],
    }
    return _common(assessment, out)


def resident_out(resident):
    out = {
        "applicant_id": resident["applicant_id"],
        "care_unit_id": resident["care_unit_id"],
        "admission_date": resident["admission_date"],
        "occupancy_status": resident["occupancy_status"],
        "billing_status": resident["billing_status"],
        "current_care_level": resident["current_care_level"],
        "bed_hold_days_used": resident["bed_hold_days_used"],
        "bed_hold_started_on": resident["bed_hold_started_on"],
        "bed_hold_active": bed_hold_active(resident),
        "last_hospitalization_end_date": resident["last_hospitalization_end_date"],
        "hospitalization_count": resident["hospitalization_count"],
        "readmission_count": resident["readmission_count"],
        "monthly_cost_share_cents": mirrored_cost_share(resident),
        "trust_fund_balance_cents": trust_fund_balance(resident["id"]),
        "last_census_date": resident["last_census_date"],
        "discharge_date": resident["discharge_date"],
        "discharge_reason": resident["discharge_reason"],
    }
    return _common(resident, out)


def income_out(record):
    out = {
        "resident_id": record["resident_id"],
        "income_type": record["income_type"],
        "monthly_amount_cents": record["monthly_amount_cents"],
        "effective_month": record["effective_month"],
        "countable_rate_bps": record["countable_rate_bps"],
        "countable_amount_cents": record["countable_amount_cents"],
        "verification_status": record["verification_status"],
        "verified_by_user_id": record["verified_by_user_id"],
    }
    return _common(record, out)


def determination_out(det):
    out = {
        "resident_id": det["resident_id"],
        "variant": det["variant"],
        "effective_month": det["effective_month"],
        "declared_medical_expense_cents": det["declared_medical_expense_cents"],
        "gross_countable_income_cents": det["gross_countable_income_cents"],
        "pna_deduction_cents": det["pna_deduction_cents"],
        "income_tier": det["income_tier"],
        "allowed_medical_deduction_cents": det["allowed_medical_deduction_cents"],
        "tiered_share_cents": det["tiered_share_cents"],
        "resident_day_count": det["resident_day_count"],
        "federal_per_diem_offset_cents": det["federal_per_diem_offset_cents"],
        "monthly_cost_share_cents": det["monthly_cost_share_cents"],
        "delta_from_prior_cents": det["delta_from_prior_cents"],
        "determined_by_user_id": det["determined_by_user_id"],
    }
    return _common(det, out, versioned=False)


def care_plan_out(plan):
    out = {
        "resident_id": plan["resident_id"],
        "supersedes_care_plan_id": plan["supersedes_care_plan_id"],
        "care_level": plan["care_level"],
        "adl_support_level": plan["adl_support_level"],
        "plan_date": plan["plan_date"],
        "status": plan["status"],
        "review_due_date": plan["review_due_date"],
        "authored_by_user_id": plan["authored_by_user_id"],
        "activated_at": plan["activated_at"],
        "revision_number": plan["revision_number"],
    }
    return _common(plan, out)


def census_out(day):
    out = {
        "resident_id": day["resident_id"],
        "care_unit_id": day["care_unit_id"],
        "per_diem_claim_id": day["per_diem_claim_id"],
        "service_date": day["service_date"],
        "census_class": day["census_class"],
        "care_level": day["care_level"],
        "per_diem_eligible": day["per_diem_eligible"],
        "payable_rate_cents": day["payable_rate_cents"],
        "claimed": census_day_claimed(day),
    }
    return _common(day, out)


def claim_out(claim):
    out = {
        "veterans_home_id": claim["veterans_home_id"],
        "care_unit_id": claim["care_unit_id"],
        "corrects_claim_id": claim["corrects_claim_id"],
        "claim_month": claim["claim_month"],
        "basis": claim["basis"],
        "status": claim["status"],
        "resident_day_count": claim["resident_day_count"],
        "bed_hold_day_count": claim["bed_hold_day_count"],
        "billable_day_count": claim["billable_day_count"],
        "claim_amount_cents": claim["claim_amount_cents"],
        "census_reported_resident_count": claim["census_reported_resident_count"],
        "recognition_verified": claim["recognition_verified"],
        "correction_generation": claim["correction_generation"],
        "submitted_at": claim["submitted_at"],
        "adjudicated_at": claim["adjudicated_at"],
        "paid_amount_cents": claim["paid_amount_cents"],
        "rejection_code": claim["rejection_code"],
        "adjudication_note": claim["adjudication_note"],
    }
    return _common(claim, out)


def txn_out(txn):
    balances = balance_map(txn["resident_id"])
    out = {
        "resident_id": txn["resident_id"],
        "reverses_transaction_id": txn["reverses_transaction_id"],
        "txn_type": txn["txn_type"],
        "amount_cents": txn["amount_cents"],
        "signed_amount_cents": txn["signed_amount_cents"],
        "effective_date": txn["effective_date"],
        "balance_after_cents": balances.get(txn["id"], 0),
        "reversed": is_reversed(txn),
        "recorded_by_user_id": txn["recorded_by_user_id"],
        "memo": txn["memo"],
    }
    return _common(txn, out)
