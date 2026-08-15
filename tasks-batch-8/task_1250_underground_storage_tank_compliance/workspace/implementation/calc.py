"""Calculation rules (SCAFFOLD section 1.3), implemented exactly as pinned.

Constants and formulas are read from the scaffold: quote per-line half-up
rounding then sum plus mobilization; test outcome thresholds; CP survey dual
criteria; test-schedule projection; compliance posture weighted scoring;
deficiency deadlines; fund reimbursement dual variants; training validity;
monthly close timing; release report deadline.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from store_ops import touch
from timeutil import add_months

# --- constants (scaffold calculations[].constants) ---------------------------
MOBILIZATION_FLAT_CENTS = 15000

TIGHTNESS_PASS_GPH = Decimal("0.100")
SPILL_HOLD_MINUTES = 5
OVERFILL_MAX_PCT = Decimal("95.0")

INSTANT_OFF_THRESHOLD_MV = -850
POLARIZATION_SHIFT_MIN_MV = 100

TANK_STABILIZATION_HOURS = 8

ATG_TIGHTNESS_INTERVAL_MONTHS = 12
MANUAL_GAUGING_TIGHTNESS_INTERVAL_MONTHS = 60
LINE_TIGHTNESS_INTERVAL_MONTHS = 12
LLD_FUNCTION_INTERVAL_MONTHS = 12
CP_SURVEY_INTERVAL_MONTHS = 36
SPILL_OVERFILL_INTERVAL_MONTHS = 36

SEVERITY_WEIGHT = {"CRITICAL": 25, "MAJOR": 15, "MINOR": 5}
ESCALATED_EXTRA = 5
OPEN_RELEASE_WEIGHT = 10
LAPSED_OPERATOR_WEIGHT = 5
COMPLIANT_MIN = 85
DEFICIENT_MIN = 60

SEVERITY_DAYS = {"CRITICAL": 7, "MAJOR": 30, "MINOR": 90}

OCCURRENCE_DEDUCTIBLE_CENTS = 1000000
AGGREGATE_YEAR_DEDUCTIBLE_CENTS = 2000000
COINSURANCE_RATE = Decimal("0.90")
FUND_YEAR_CAP_CENTS = 100000000

VALIDITY_MONTHS = {"A": 36, "B": 36, "C": 12}

REPORT_WINDOW_HOURS = 24

ENDORSEMENT_FOR_SERVICE = {
    "TANK_TIGHTNESS": "TIGHTNESS_TESTER",
    "LINE_TIGHTNESS": "TIGHTNESS_TESTER",
    "LLD_FUNCTION": "LLD_TESTER",
    "CP_SURVEY": "CP_TESTER",
    "SPILL_OVERFILL_INSPECTION": "INSPECTOR",
}

# service types that target a component, and the component types they accept
COMPONENT_SERVICE_TYPES = {
    "CP_SURVEY": {"CATHODIC_PROTECTION"},
    "LLD_FUNCTION": {"LINE_LEAK_DETECTOR"},
    "SPILL_OVERFILL_INSPECTION": {"SPILL_BUCKET", "OVERFILL_DEVICE"},
}
TIGHTNESS_SERVICE_TYPES = {"TANK_TIGHTNESS", "LINE_TIGHTNESS"}

# deficiency statuses that count against the posture score (the "open set")
DEFICIENCY_OPEN_STATUSES = {"OPEN", "CORRECTION_ORDERED", "CORRECTED", "RE_TEST_SCHEDULED", "ESCALATED"}
RELEASE_OPEN_STATUSES = {"SUSPECTED", "CONFIRMED", "CLEANUP_IN_PROGRESS"}


def _dec(v):
    """Exact decimal view of a JSON number."""
    return Decimal(str(v))


# --- service_quote_total ------------------------------------------------------
def compute_quote_total(line_items):
    """Per-line round-half-up to whole cents FIRST, then sum, then add the
    flat mobilization charge (pinned order)."""
    subtotal = 0
    for line in line_items:
        line_cents = (_dec(line["qty"]) * Decimal(line["unit_price_cents"])) \
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        subtotal += int(line_cents)
    return subtotal + MOBILIZATION_FLAT_CENTS


# --- test_result_determination ------------------------------------------------
def determine_outcome(service_type, readings):
    """PASS | FAIL | INCONCLUSIVE per test_result_determination /
    cp_survey_determination."""
    if service_type in ("TANK_TIGHTNESS", "LINE_TIGHTNESS"):
        return "PASS" if _dec(readings["leak_rate_gph"]) <= TIGHTNESS_PASS_GPH else "FAIL"
    if service_type == "LLD_FUNCTION":
        return "PASS" if readings["detects_simulated_leak"] is True else "FAIL"
    if service_type == "SPILL_OVERFILL_INSPECTION":
        ok = (readings["visual_cracks_found"] is False
              and _dec(readings["drain_test_hold_minutes"]) >= Decimal(SPILL_HOLD_MINUTES)
              and _dec(readings["overfill_activates_pct"]) <= OVERFILL_MAX_PCT)
        return "PASS" if ok else "FAIL"
    # CP_SURVEY
    if readings["valid_contact"] is False:
        return "INCONCLUSIVE"
    if readings["criterion"] == "INSTANT_OFF":
        return "PASS" if readings["instant_off_mv"] <= INSTANT_OFF_THRESHOLD_MV else "FAIL"
    # POLARIZATION_SHIFT
    shift_mv = readings["native_mv"] - readings["polarized_mv"]
    return "PASS" if shift_mv >= POLARIZATION_SHIFT_MIN_MV else "FAIL"


# --- test_schedule_projection --------------------------------------------------
def project_test_schedule(tank):
    comps = [c for c in store.components.values() if c["tank_system_id"] == tank["id"]]
    ctypes = {c["component_type"] for c in comps}
    applicable = []
    if tank["release_detection_mode"] != "INTERSTITIAL_MONITORING":
        months = (ATG_TIGHTNESS_INTERVAL_MONTHS
                  if tank["release_detection_mode"] == "ATG_INVENTORY"
                  else MANUAL_GAUGING_TIGHTNESS_INTERVAL_MONTHS)
        applicable.append(("TANK_TIGHTNESS", months))
    if tank["piping_type"] == "PRESSURIZED":
        applicable.append(("LINE_TIGHTNESS", LINE_TIGHTNESS_INTERVAL_MONTHS))
    if "LINE_LEAK_DETECTOR" in ctypes:
        applicable.append(("LLD_FUNCTION", LLD_FUNCTION_INTERVAL_MONTHS))
    if "CATHODIC_PROTECTION" in ctypes:
        applicable.append(("CP_SURVEY", CP_SURVEY_INTERVAL_MONTHS))
    if ctypes & {"SPILL_BUCKET", "OVERFILL_DEVICE"}:
        applicable.append(("SPILL_OVERFILL_INSPECTION", SPILL_OVERFILL_INTERVAL_MONTHS))

    items = []
    for test_type, months in applicable:
        certified = [o for o in store.service_orders.values()
                     if o["tank_system_id"] == tank["id"]
                     and o["service_type"] == test_type
                     and o["status"] == "CERTIFIED"]
        if certified:
            # latest = last by window_end ASC, tie-break created_at ASC
            base = sorted(certified, key=lambda o: (o["window_end"], o["_seq"]))[-1]["window_end"]
        else:
            base = tank["installed_on"]
        items.append({"test_type": test_type, "due_at": add_months(base, months)})
    items.sort(key=lambda i: (i["due_at"], i["test_type"]))
    return items


# --- compliance_posture_score ---------------------------------------------------
def recompute_posture(fac):
    """Weighted scoring over the facility's open deficiencies, open releases,
    and lapsed operators; clamped to [0, 100]; tiered at 85/60. The facility
    record is touched only when a value actually changes."""
    score = 100
    for d in store.deficiencies.values():
        if d["facility_id"] == fac["id"] and d["status"] in DEFICIENCY_OPEN_STATUSES:
            score -= SEVERITY_WEIGHT[d["severity"]]
            if d["status"] == "ESCALATED":
                score -= ESCALATED_EXTRA
    for r in store.release_events.values():
        if r["facility_id"] == fac["id"] and r["status"] in RELEASE_OPEN_STATUSES:
            score -= OPEN_RELEASE_WEIGHT
    for o in store.operators.values():
        if o["facility_id"] == fac["id"] and o["status"] == "LAPSED":
            score -= LAPSED_OPERATOR_WEIGHT
    score = min(100, max(0, score))
    posture = ("COMPLIANT" if score >= COMPLIANT_MIN
               else "DEFICIENT" if score >= DEFICIENT_MIN
               else "NON_COMPLIANT")
    if fac["posture_score"] != score or fac["compliance_posture"] != posture:
        fac["posture_score"] = score
        fac["compliance_posture"] = posture
        touch(fac)


# --- fund_reimbursement_amount ---------------------------------------------------
def compute_claim_amounts(fac, expense_lines):
    """Dual-variant deductible/coinsurance. Returns
    (deductible_applied_cents, eligible_amount_cents, payable_amount_cents)."""
    total = sum(line["amount_cents"] for line in expense_lines)
    if fac["fund_program_election"] == "PER_OCCURRENCE":
        deductible = min(total, OCCURRENCE_DEDUCTIBLE_CENTS)
        eligible = max(0, total - deductible)
        payable = int((Decimal(eligible) * COINSURANCE_RATE)
                      .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # AGGREGATE
        deductible = min(total, fac["fund_year_deductible_remaining_cents"])
        eligible = total - deductible
        payable = eligible
    return deductible, eligible, payable


# --- training_certificate_expiry --------------------------------------------------
def latest_training_record(operator_id, course_class):
    """The valid record selector: max completed_at, tie-break max created_at
    (insertion sequence stands in for created_at under the logical clock)."""
    recs = [t for t in store.training_records.values()
            if t["operator_id"] == operator_id and t["course_class"] == course_class]
    if not recs:
        return None
    return sorted(recs, key=lambda t: (t["completed_at"], t["_seq"]))[-1]
