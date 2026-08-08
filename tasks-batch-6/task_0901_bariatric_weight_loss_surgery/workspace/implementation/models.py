"""In-memory store, constants, calculations, and serializers.

All state lives in module-level dicts. Every process start (start.sh re-invocation)
imports this module fresh, so the store begins empty on every boot. No seeding.
"""
import uuid
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SEXES = {"MALE", "FEMALE"}
PAYMENT_PATHWAYS = {"INSURANCE", "SELF_PAY"}
COMORBIDITIES = {"TYPE_2_DIABETES", "HYPERTENSION", "OSA", "NAFLD",
                 "DYSLIPIDEMIA", "GERD", "OSTEOARTHRITIS"}
PROCEDURES = {"SLEEVE_GASTRECTOMY", "GASTRIC_BYPASS", "ADJUSTABLE_BAND"}
ROOM_STATUSES = {"OPEN", "CLOSED"}
NUTRITION_DECISIONS = {"CLEARED", "NOT_CLEARED"}
MILESTONE_CODES = {"NUTRITION_CLASS", "EXERCISE_ORIENTATION",
                   "SURGERY_RISKS_CONSENT", "POST_OP_DIET_EDUCATION"}
PSYCH_DECISIONS = {"CLEARED", "DEFERRED"}
COMPLICATION_TYPES = {"LEAK", "BLEEDING", "STRICTURE", "INFECTION", "DVT", "OTHER"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
BASE_CENTS = {"SLEEVE_GASTRECTOMY": 1800000,
              "GASTRIC_BYPASS": 2500000,
              "ADJUSTABLE_BAND": 1500000}
STANDARD_OR_MINUTES = {"SLEEVE_GASTRECTOMY": 90,
                       "GASTRIC_BYPASS": 150,
                       "ADJUSTABLE_BAND": 60}
OVERTIME_RATE_CENTS_PER_MIN = 25000
CANCELLATION_FEE_CENTS = 100000

DEFAULT_BMI_FLOOR_NO_COMORBIDITY = 40.0
DEFAULT_BMI_FLOOR_WITH_COMORBIDITY = 35.0
DEFAULT_QUALIFYING_COMORBIDITIES = {"TYPE_2_DIABETES", "HYPERTENSION", "OSA",
                                    "NAFLD", "DYSLIPIDEMIA"}

REQUIRED_MILESTONES = {"NUTRITION_CLASS", "EXERCISE_ORIENTATION",
                       "SURGERY_RISKS_CONSENT", "POST_OP_DIET_EDUCATION"}

INTERVAL_ORDER = ["WEEK_2", "WEEK_6", "MONTH_3", "MONTH_6", "MONTH_12"]
INTERVAL_OFFSET_DAYS = {"WEEK_2": 14, "WEEK_6": 42, "MONTH_3": 90,
                        "MONTH_6": 180, "MONTH_12": 365}

MALE_BASE_KG = Decimal("50.0")
FEMALE_BASE_KG = Decimal("45.5")
KG_PER_INCH_OVER_60 = Decimal("2.3")
REFERENCE_BMI = Decimal("25.0")

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
patients = {}
insurance_plans = {}
operating_rooms = {}
surgeons = {}
programs = {}
diet_visits = {}
psych_evaluations = {}
nutrition_clearances = {}
milestones = {}
surgery_cases = {}
complications = {}
follow_up_visits = {}
financing_plans = {}

_seq_counter = itertools.count(1)

# Logical clock: startup default, never falls back to wall-clock.
_clock = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _fmt(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return _fmt(datetime.now(UTC))


def next_seq():
    return next(_seq_counter)


def base_fields():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def touch(entity):
    """Bump version + updated_at on a mutation."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def parse_dt(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def rhu(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def rhu_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def calc_baseline_bmi(height_cm, weight_kg):
    height_m = Decimal(str(height_cm)) / Decimal("100")
    bmi = Decimal(str(weight_kg)) / (height_m * height_m)
    return rhu(bmi, 1)


def calc_ideal_body_weight(height_cm, sex):
    inches_over_60 = Decimal(str(height_cm)) / Decimal("2.54") - Decimal("60")
    base = MALE_BASE_KG if sex == "MALE" else FEMALE_BASE_KG
    ibw = base + KG_PER_INCH_OVER_60 * inches_over_60
    return rhu(ibw, 3)


def bundle_estimate_cents(procedure_type, baseline_bmi):
    base = BASE_CENTS[procedure_type]
    if baseline_bmi >= 50:
        surcharge = Decimal("0.15")
    elif baseline_bmi >= 40:
        surcharge = Decimal("0.08")
    else:
        surcharge = Decimal("0")
    return rhu_int(Decimal(base) * (Decimal("1") + surcharge))


def bundle_final_cents(procedure_type, baseline_bmi, actual_or_minutes):
    estimate = bundle_estimate_cents(procedure_type, baseline_bmi)
    overtime = max(0, actual_or_minutes - STANDARD_OR_MINUTES[procedure_type])
    return estimate + overtime * OVERTIME_RATE_CENTS_PER_MIN


def financing_schedule(bundle_price, down_payment, apr_bps, term_months):
    principal = bundle_price - down_payment
    interest = rhu_int(Decimal(principal) * Decimal(apr_bps) / Decimal("10000")
                       * Decimal(term_months) / Decimal("12"))
    financed_total = principal + interest
    installment = financed_total // term_months
    final_installment = financed_total - installment * (term_months - 1)
    return interest, installment, final_installment


def weight_loss_outcome(baseline_weight, recorded_weight, ideal_body_weight, height_cm):
    B = Decimal(str(baseline_weight))
    W = Decimal(str(recorded_weight))
    ibw = Decimal(str(ideal_body_weight))
    height_m = Decimal(str(height_cm)) / Decimal("100")
    weight_bmi25 = REFERENCE_BMI * (height_m * height_m)
    numerator = B - W
    ewl_ibw = float(rhu(numerator / (B - ibw) * Decimal("100"), 1))
    ewl_bmi25 = float(rhu(numerator / (B - weight_bmi25) * Decimal("100"), 1))
    return ewl_ibw, ewl_bmi25


def cancellation_refund(collected):
    forfeited = min(collected, CANCELLATION_FEE_CENTS)
    refunded = collected - forfeited
    return forfeited, refunded


# ---------------------------------------------------------------------------
# Derived clearance calculations (read program's child artifacts)
# ---------------------------------------------------------------------------
def diet_requirement_met(program):
    if program["payment_pathway"] == "SELF_PAY":
        return True
    plan = insurance_plans.get(program["insurance_plan_id"])
    required = plan["required_supervised_diet_months"] if plan else 0
    if required <= 0:
        return True
    qualifying = set()
    for v in diet_visits.values():
        if (v["program_id"] == program["id"] and v["attended"]
                and 1 <= v["month_index"] <= required):
            qualifying.add(v["month_index"])
    return len(qualifying) >= required


def clearances_complete(program):
    pid = program["id"]
    psych_ok = any(p["program_id"] == pid and p["status"] == "CLEARED"
                   for p in psych_evaluations.values())
    nutr_ok = any(n["program_id"] == pid and n["decision"] == "CLEARED"
                  for n in nutrition_clearances.values())
    have = {m["milestone_code"] for m in milestones.values()
            if m["program_id"] == pid and m["completed"]}
    miles_ok = REQUIRED_MILESTONES.issubset(have)
    diet_ok = diet_requirement_met(program)
    return bool(psych_ok and nutr_ok and miles_ok and diet_ok)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(entity, extra):
    out = {"id": entity["id"]}
    out.update(extra)
    out["created_at"] = entity["created_at"]
    out["updated_at"] = entity["updated_at"]
    out["version"] = entity["version"]
    return out


def ser_patient(p):
    return _common(p, {
        "mrn": p["mrn"], "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"], "sex": p["sex"],
        "height_cm": p["height_cm"], "baseline_weight_kg": p["baseline_weight_kg"],
    })


def ser_insurance_plan(x):
    return _common(x, {
        "plan_name": x["plan_name"], "payer_code": x["payer_code"],
        "required_supervised_diet_months": x["required_supervised_diet_months"],
        "requires_psych_clearance": x["requires_psych_clearance"],
        "requires_nutrition_clearance": x["requires_nutrition_clearance"],
        "bmi_floor_no_comorbidity": x["bmi_floor_no_comorbidity"],
        "bmi_floor_with_comorbidity": x["bmi_floor_with_comorbidity"],
        "qualifying_comorbidities": x["qualifying_comorbidities"],
    })


def ser_operating_room(x):
    return _common(x, {
        "room_code": x["room_code"],
        "turnover_buffer_minutes": x["turnover_buffer_minutes"],
        "status": x["status"],
    })


def ser_surgeon(x):
    return _common(x, {
        "full_name": x["full_name"], "npi": x["npi"],
        "credentialed_procedures": x["credentialed_procedures"],
    })


def ser_program(p):
    return _common(p, {
        "patient_id": p["patient_id"],
        "payment_pathway": p["payment_pathway"],
        "insurance_plan_id": p["insurance_plan_id"],
        "comorbidities": p["comorbidities"],
        "baseline_bmi": p["baseline_bmi"],
        "baseline_weight_kg": p["baseline_weight_kg"],
        "ideal_body_weight_kg": p["ideal_body_weight_kg"],
        "candidacy_status": p["candidacy_status"],
        "qualifying_reason": p["qualifying_reason"],
        "status": p["status"],
        "clearances_complete": clearances_complete(p),
        "readmission_count": p["readmission_count"],
        "active_complication_count": p["active_complication_count"],
        "amount_collected_cents": p["amount_collected_cents"],
        "amount_refunded_cents": p["amount_refunded_cents"],
        "amount_forfeited_cents": p["amount_forfeited_cents"],
    })


def ser_diet_visit(x):
    return _common(x, {
        "program_id": x["program_id"], "month_index": x["month_index"],
        "visit_date": x["visit_date"], "weight_kg": x["weight_kg"],
        "attended": x["attended"],
    })


def ser_psych(x):
    return _common(x, {
        "program_id": x["program_id"], "clinician_note": x["clinician_note"],
        "status": x["status"], "deferral_reason": x["deferral_reason"],
        "reevaluation_count": x["reevaluation_count"],
    })


def ser_nutrition(x):
    return _common(x, {
        "program_id": x["program_id"], "decision": x["decision"],
        "diet_readiness_score": x["diet_readiness_score"],
    })


def ser_milestone(x):
    return _common(x, {
        "program_id": x["program_id"], "milestone_code": x["milestone_code"],
        "completed": x["completed"], "completed_date": x["completed_date"],
    })


def ser_surgery_case(x):
    return _common(x, {
        "program_id": x["program_id"],
        "operating_room_id": x["operating_room_id"],
        "surgeon_id": x["surgeon_id"],
        "procedure_type": x["procedure_type"],
        "scheduled_start": x["scheduled_start"],
        "scheduled_end": x["scheduled_end"],
        "status": x["status"],
        "estimated_bundle_cents": x["estimated_bundle_cents"],
        "actual_or_minutes": x["actual_or_minutes"],
        "final_bundle_cents": x["final_bundle_cents"],
        "cancellation_reason": x["cancellation_reason"],
    })


def ser_complication(x):
    return _common(x, {
        "surgery_case_id": x["surgery_case_id"],
        "complication_type": x["complication_type"],
        "severity": x["severity"],
        "requires_readmission": x["requires_readmission"],
        "onset_date": x["onset_date"],
        "status": x["status"],
    })


def ser_follow_up(x):
    return _common(x, {
        "program_id": x["program_id"],
        "interval_code": x["interval_code"],
        "scheduled_date": x["scheduled_date"],
        "status": x["status"],
        "recorded_weight_kg": x["recorded_weight_kg"],
        "ewl_pct_ibw": x["ewl_pct_ibw"],
        "ewl_pct_bmi25": x["ewl_pct_bmi25"],
    })


def ser_financing(x):
    return _common(x, {
        "program_id": x["program_id"],
        "procedure_type": x["procedure_type"],
        "down_payment_cents": x["down_payment_cents"],
        "term_months": x["term_months"],
        "apr_bps": x["apr_bps"],
        "bundle_price_cents": x["bundle_price_cents"],
        "interest_cents": x["interest_cents"],
        "installment_cents": x["installment_cents"],
        "final_installment_cents": x["final_installment_cents"],
        "status": x["status"],
    })
