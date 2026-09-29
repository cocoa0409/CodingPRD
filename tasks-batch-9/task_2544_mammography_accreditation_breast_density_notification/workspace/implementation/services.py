"""Domain services: derived calculations, cascades and the compliance checkpoint."""

from common import (
    DB, cents_half_up, dsum, fail, new_entity, plus_days, round2, touch,
)

from datetime import timedelta

# ---------------------------------------------------------------------------
# constants (calculations)
# ---------------------------------------------------------------------------
PHANTOM_MIN = 6.0
MGD_MAX = 3.00
MAX_REMEDIATION_ATTEMPTS = 2
MAX_SURVEY_WINDOW_DAYS = 396

APPLICATION_FEE_CENTS = 250000
MAX_ATTEMPTS = 3
ACCREDITATION_TERM_DAYS = 1095
REACCREDITATION_LEAD_DAYS = 180
SUSPENSION_GRACE_DAYS = 30

REPEAT_RATE_THRESHOLD_PCT = 5.00
DELIVERY_ASSUMPTION_DAYS = 14

CORRECTIVE_ACTION_DAYS = {"LEVEL_2": 30, "LEVEL_1": 15}

FEE_SCHEDULE_CENTS = {"ULTRASOUND": 28500, "MRI": 120000, "CEM": 60000}
ADMIN_FEE_CENTS = 3000
TIER_1_MAX_CENTS = 31500
TIER_2_MAX_CENTS = 63000
TIER_RATES = {"TIER_1": "0.615", "TIER_2": "0.775", "TIER_3": "0.90"}

SLOT_MINUTES = {"ULTRASOUND": 30, "MRI": 45, "CEM": 30}
TURNOVER_MINUTES = 15

DENSE_CATEGORIES = ("C", "D")
URGENT_BIRADS = (0, 4, 5)
FEDERAL_LAY_SUMMARY_CODE = "FDA-LAY-SUMMARY"
FEDERAL_DENSE_CODE = "FDA-DENSE"
FEDERAL_NOT_DENSE_CODE = "FDA-NOT-DENSE"
FEDERAL_URGENT_CODE = "FDA-URGENT-FINDING"
# The density *statement* enum uses underscores; the notice *code* uses hyphens.
DENSITY_STATEMENT_DENSE = "FDA_DENSE"
DENSITY_STATEMENT_NOT_DENSE = "FDA_NOT_DENSE"
FEDERAL_MAX_READING_GRADE = 8
FEDERAL_MAX_DEADLINE_DAYS = 30
FEDERAL_URGENT_DEADLINE_DAYS = 7

CE_LOOKBACK_DAYS = 1095
VOLUME_LOOKBACK_DAYS = 730
CE_THRESHOLDS = {
    "INTERPRETING_PHYSICIAN": {
        "initial_hours": 60, "initial_volume": 240,
        "ce_hours": 15, "volume": 960,
    },
    "TECHNOLOGIST": {
        "initial_hours": 40, "initial_volume": 25,
        "ce_hours": 15, "volume": 200,
    },
    "MEDICAL_PHYSICIST": {
        "initial_hours": 20, "initial_volume": 1,
        "ce_hours": 15, "volume": 2,
    },
}

RECALL_RATE_LOW = 5.00
RECALL_RATE_HIGH = 12.00
SCORED_PATHOLOGY = ("BENIGN", "MALIGNANT")

ORDER_TERMINAL = ("COMPLETED", "REFERRED_OUT")
ORDER_OPEN_FOR_REFERRAL = ("RECOMMENDED", "COVERAGE_DETERMINED")
NOTICE_OPEN_STATUSES = ("PENDING", "GENERATED", "SENT")


# ---------------------------------------------------------------------------
# navigation helpers
# ---------------------------------------------------------------------------
def facility_of_unit(unit):
    return DB.get("facility", unit["facility_id"])


def facility_of_exam(exam):
    unit = DB.get("unit", exam["unit_id"])
    return facility_of_unit(unit) if unit else None


def units_of_facility(facility_id):
    return [u for u in DB.all("unit") if u["facility_id"] == facility_id]


def personnel_of_facility(facility_id):
    return [p for p in DB.all("personnel") if p["facility_id"] == facility_id]


def inspections_of_facility(facility_id):
    return [i for i in DB.all("inspection") if i["facility_id"] == facility_id]


def exams_of_unit(unit_id):
    return [e for e in DB.all("exam") if e["unit_id"] == unit_id]


def exams_of_facility(facility_id):
    unit_ids = set(u["id"] for u in units_of_facility(facility_id))
    return [e for e in DB.all("exam") if e["unit_id"] in unit_ids]


def surveys_of_unit(unit_id):
    return [s for s in DB.all("survey") if s["unit_id"] == unit_id]


def letters_of_exam(exam_id):
    return [l for l in DB.all("letter") if l["exam_id"] == exam_id]


def orders_of_exam(exam_id):
    return [o for o in DB.all("order") if o["exam_id"] == exam_id]


def repeats_of_exam(exam_id):
    return [r for r in DB.all("repeat") if r["exam_id"] == exam_id]


def submissions_of_unit(unit_id):
    return [s for s in DB.all("submission") if s["unit_id"] == unit_id]


def failures_of_unit(unit_id):
    return [f for f in DB.all("failure") if f["unit_id"] == unit_id]


def in_order(rows, *keys):
    def sort_key(row):
        out = []
        for key in keys:
            out.append(row.get(key))
        out.append(row["_seq"])
        return tuple(out)

    return sorted(rows, key=sort_key)


# ---------------------------------------------------------------------------
# calculation: governing policy resolution
# ---------------------------------------------------------------------------
def policy_by_state_code(code):
    for policy in DB.all("state_policy"):
        if policy["state_code"] == code:
            return policy
    return None


def home_policy(facility):
    return DB.get("state_policy", facility["state_policy_id"])


def governing_policy_for_exam(exam):
    """Patient-state policy when one is registered, otherwise the facility home
    policy.  Never falls back to federal defaults."""
    policy = policy_by_state_code(exam.get("patient_state_code"))
    if policy is not None:
        return policy
    facility = facility_of_exam(exam)
    return home_policy(facility) if facility else None


def governing_policy_for_personnel(person):
    facility = DB.get("facility", person["facility_id"])
    return home_policy(facility) if facility else None


# ---------------------------------------------------------------------------
# calculation: survey pass determination
# ---------------------------------------------------------------------------
def survey_passes(phantom_score, mgd, critical_codes):
    return (
        phantom_score >= PHANTOM_MIN
        and mgd <= MGD_MAX
        and len(critical_codes or []) == 0
    )


# ---------------------------------------------------------------------------
# calculation: survey window exclusivity
# ---------------------------------------------------------------------------
SURVEY_BLOCKING_STATUSES = ("DRAFT", "PASSED", "FAILED_ACTION_REQUIRED")


def check_survey_window(unit_id, survey_type, start, end, exclude_id=None):
    if end <= start:
        fail("ERR_SURVEY_WINDOW_INVALID", "effective_end must be after effective_start")
    if (end - start) > timedelta(days=MAX_SURVEY_WINDOW_DAYS):
        fail("ERR_SURVEY_WINDOW_INVALID",
             "survey window may not span more than %d days" % MAX_SURVEY_WINDOW_DAYS)
    for peer in surveys_of_unit(unit_id):
        if peer["id"] == exclude_id:
            continue
        if peer["survey_type"] != survey_type:
            continue
        if peer["status"] not in SURVEY_BLOCKING_STATUSES:
            continue
        if peer["effective_start"] < end and start < peer["effective_end"]:
            fail("ERR_SURVEY_WINDOW_OVERLAP",
                 "an active %s survey window already covers this range" % survey_type)


# ---------------------------------------------------------------------------
# calculation: facility compliance posture (first match wins)
# ---------------------------------------------------------------------------
def compute_posture(facility):
    units = units_of_facility(facility["id"])
    inspections = inspections_of_facility(facility["id"])
    staff = personnel_of_facility(facility["id"])

    for unit in units:
        if unit["accreditation_status"] == "SUSPENDED":
            return "SUSPENDED"
    for unit in units:
        if unit["operational_state"] == "OUT_OF_SERVICE" and \
                unit["accreditation_status"] in ("PROBATION", "SUSPENDED"):
            return "SUSPENDED"
    for inspection in inspections:
        if inspection["inspector_findings_level"] == "LEVEL_1" and \
                inspection["status"] == "CORRECTIVE_ACTION_REQUIRED":
            return "SUSPENDED"
    if units and all(u["operational_state"] == "OUT_OF_SERVICE" for u in units):
        return "SUSPENDED"

    for unit in units:
        if unit["accreditation_status"] in ("PROBATION", "REACCREDITATION_DUE"):
            return "CONDITIONAL"
    for unit in units:
        if unit["survey_compliance"] in ("OVERDUE", "FAILED"):
            return "CONDITIONAL"
    for unit in units:
        if unit["operational_state"] == "OUT_OF_SERVICE":
            return "CONDITIONAL"
    for inspection in inspections:
        if inspection["inspector_findings_level"] == "LEVEL_2" and \
                inspection["status"] == "CORRECTIVE_ACTION_REQUIRED":
            return "CONDITIONAL"
    for person in staff:
        if person["ce_status"] == "DEFICIENT" or person["qualification_status"] == "LAPSED":
            return "CONDITIONAL"

    return "COMPLIANT"


def recompute_posture(facility):
    """Recompute posture; a fresh entry into SUSPENDED fires the referral cascade."""
    if facility is None:
        return None
    previous = facility["compliance_posture"]
    current = compute_posture(facility)
    if current != previous:
        facility["compliance_posture"] = current
        touch(facility)
        if current == "SUSPENDED":
            refer_open_orders_out(facility)
    return current


def refer_open_orders_out(facility):
    """One-way referral cascade: every still-open supplemental order at a facility
    that has just gone SUSPENDED is referred out, and its exam moves to
    PENDING_EXTERNAL."""
    exams = dict((e["id"], e) for e in exams_of_facility(facility["id"]))
    pending = [o for o in DB.all("order")
               if o["exam_id"] in exams and o["status"] in ORDER_OPEN_FOR_REFERRAL]
    pending.sort(key=lambda o: (exams[o["exam_id"]]["performed_at"],
                                o["created_at"], o["_seq"]))
    for order in pending:
        order["status"] = "REFERRED_OUT"
        order["external_referral_note"] = (
            "Referred to an external facility: home facility compliance posture is SUSPENDED."
        )
        touch(order)
        exam = exams[order["exam_id"]]
        if exam["follow_up_status"] == "PENDING":
            exam["follow_up_status"] = "PENDING_EXTERNAL"
            touch(exam)


# ---------------------------------------------------------------------------
# calculation: fee escrow ledger
# ---------------------------------------------------------------------------
def ledger_deposit(facility, amount_cents):
    facility["total_funded_cents"] += amount_cents
    facility["prepaid_credit_cents"] += amount_cents
    touch(facility)


def require_prepaid_credit(facility):
    """Ladder priority 81 — money is always the final word."""
    if facility["prepaid_credit_cents"] < APPLICATION_FEE_CENTS:
        fail("ERR_INSUFFICIENT_PREPAID_CREDIT",
             "prepaid credit is below the %d cent application fee" % APPLICATION_FEE_CENTS)


def ledger_escrow(facility, submission):
    if facility["prepaid_credit_cents"] < APPLICATION_FEE_CENTS:
        fail("ERR_INSUFFICIENT_PREPAID_CREDIT",
             "prepaid credit is below the %d cent application fee" % APPLICATION_FEE_CENTS)
    facility["prepaid_credit_cents"] -= APPLICATION_FEE_CENTS
    facility["fee_held_cents"] += APPLICATION_FEE_CENTS
    submission["fee_held_cents"] = APPLICATION_FEE_CENTS
    touch(facility)


def ledger_release(facility, submission):
    facility["fee_held_cents"] -= APPLICATION_FEE_CENTS
    facility["prepaid_credit_cents"] += APPLICATION_FEE_CENTS
    submission["fee_held_cents"] = 0
    touch(facility)


def ledger_consume(facility, submission):
    facility["fee_held_cents"] -= APPLICATION_FEE_CENTS
    facility["fee_consumed_cents"] += APPLICATION_FEE_CENTS
    submission["fee_held_cents"] = 0
    touch(facility)


# ---------------------------------------------------------------------------
# calculation: unit repeat rate
# ---------------------------------------------------------------------------
def recompute_unit_repeat_rate(unit):
    exams = exams_of_unit(unit["id"])
    total_images = 0
    repeat_images = 0
    exams_with_repeat = 0
    for exam in exams:
        counted = sum(r["repeat_image_count"] for r in repeats_of_exam(exam["id"])
                      if not r["retracted"])
        if exam["repeat_image_count"] != counted:
            exam["repeat_image_count"] = counted
            touch(exam)
        repeat_images += counted
        total_images += exam["original_image_count"] + counted
        if counted > 0:
            exams_with_repeat += 1

    image_based = round2(repeat_images, total_images) if total_images > 0 else None
    patient_based = round2(exams_with_repeat, len(exams)) if exams else None
    flag = image_based is not None and image_based > REPEAT_RATE_THRESHOLD_PCT

    changed = (
        unit["total_images_acquired"] != total_images
        or unit["repeat_images_acquired"] != repeat_images
        or unit["image_based_repeat_rate_pct"] != image_based
        or unit["patient_based_repeat_rate_pct"] != patient_based
        or unit["repeat_rate_flag"] != flag
    )
    unit["total_images_acquired"] = total_images
    unit["repeat_images_acquired"] = repeat_images
    unit["image_based_repeat_rate_pct"] = image_based
    unit["patient_based_repeat_rate_pct"] = patient_based
    unit["repeat_rate_flag"] = flag
    if changed:
        touch(unit)


# ---------------------------------------------------------------------------
# calculation: notice obligation counter
# ---------------------------------------------------------------------------
def recompute_open_notices(facility):
    if facility is None:
        return
    count = len([e for e in exams_of_facility(facility["id"])
                 if e["notification_status"] in NOTICE_OPEN_STATUSES])
    if facility["open_notice_obligations"] != count:
        facility["open_notice_obligations"] = count
        touch(facility)


# ---------------------------------------------------------------------------
# calculation: notification requirement selection
# ---------------------------------------------------------------------------
def notification_requirements(exam, policy):
    dense = exam.get("density_category") in DENSE_CATEGORIES
    urgent = exam.get("birads_assessment") in URGENT_BIRADS
    density_statement_code = (DENSITY_STATEMENT_DENSE if dense
                              else DENSITY_STATEMENT_NOT_DENSE)

    rule = policy["density_notice_rule"]
    state_notice_applies = rule == "STATE_ENHANCED_ALL" or (
        rule == "STATE_DENSE_ONLY" and dense
    )
    letter_type = "COMBINED" if state_notice_applies else "LAY_SUMMARY"
    reading_grade_level = min(policy["lay_summary_max_reading_grade"],
                             FEDERAL_MAX_READING_GRADE)
    deadline_days = min(policy["lay_summary_deadline_days"], FEDERAL_MAX_DEADLINE_DAYS)
    if urgent:
        deadline_days = min(deadline_days, FEDERAL_URGENT_DEADLINE_DAYS)

    codes = [FEDERAL_LAY_SUMMARY_CODE,
             FEDERAL_DENSE_CODE if dense else FEDERAL_NOT_DENSE_CODE]
    if urgent:
        codes.append(FEDERAL_URGENT_CODE)
    if state_notice_applies:
        codes.extend(policy.get("required_notice_codes") or [])
    deduped = []
    for code in codes:
        if code not in deduped:
            deduped.append(code)

    return {
        "letter_type": letter_type,
        "density_statement_code": density_statement_code,
        "reading_grade_level": reading_grade_level,
        "deadline_days": deadline_days,
        "required_notice_codes": deduped,
        "governing_state_code": policy["state_code"],
    }


# ---------------------------------------------------------------------------
# calculation: supplemental coverage determination
# ---------------------------------------------------------------------------
def determine_coverage(exam, order, policy):
    bare_fee = FEE_SCHEDULE_CENTS[order["modality"]]
    mandate = policy["supplemental_coverage_mandate"]

    if mandate == "NONE":
        return {
            "coverage_outcome": "PATIENT_RESPONSIBILITY",
            "allowed_amount_cents": bare_fee,
            "covered_amount_cents": 0,
            "patient_responsibility_cents": bare_fee,
            "coverage_tier": None,
        }

    if exam.get("density_category") not in DENSE_CATEGORIES:
        return {
            "coverage_outcome": "DENIED",
            "allowed_amount_cents": bare_fee,
            "covered_amount_cents": 0,
            "patient_responsibility_cents": bare_fee,
            "coverage_tier": None,
        }

    allowed = bare_fee + ADMIN_FEE_CENTS
    if allowed <= TIER_1_MAX_CENTS:
        tier = "TIER_1"
    elif allowed <= TIER_2_MAX_CENTS:
        tier = "TIER_2"
    else:
        tier = "TIER_3"

    covered = cents_half_up(allowed, TIER_RATES[tier])
    responsibility = allowed - covered

    if mandate == "COVERAGE_NO_COST_SHARING":
        return {
            "coverage_outcome": "COVERED_NO_COST_SHARE",
            "allowed_amount_cents": allowed,
            "covered_amount_cents": allowed,
            "patient_responsibility_cents": 0,
            "coverage_tier": tier,
        }

    threshold = policy["supplemental_cost_share_waiver_threshold_cents"]
    if responsibility <= threshold:
        return {
            "coverage_outcome": "COVERED_NO_COST_SHARE",
            "allowed_amount_cents": allowed,
            "covered_amount_cents": allowed,
            "patient_responsibility_cents": 0,
            "coverage_tier": tier,
        }

    return {
        "coverage_outcome": "COVERED_WITH_COST_SHARE",
        "allowed_amount_cents": allowed,
        "covered_amount_cents": covered,
        "patient_responsibility_cents": responsibility,
        "coverage_tier": tier,
    }


# ---------------------------------------------------------------------------
# calculation: supplemental appointment occupancy
# ---------------------------------------------------------------------------
def check_appointment_capacity(facility, order, start, end):
    exams = dict((e["id"], e) for e in exams_of_facility(facility["id"]))
    occupied_end = end + timedelta(minutes=TURNOVER_MINUTES)
    collisions = 0
    for peer in DB.all("order"):
        if peer["id"] == order["id"]:
            continue
        if peer["status"] != "SCHEDULED":
            continue
        if peer["exam_id"] not in exams:
            continue
        if peer["appointment_start"] is None or peer["appointment_end"] is None:
            continue
        peer_end = peer["appointment_end"] + timedelta(minutes=TURNOVER_MINUTES)
        if start <= peer_end and peer["appointment_start"] <= occupied_end:
            collisions += 1
    if collisions >= facility["supplemental_concurrent_capacity"]:
        fail("ERR_SUPPLEMENTAL_CAPACITY_CONFLICT",
             "the facility has no free supplemental screening slot in that window")


# ---------------------------------------------------------------------------
# calculation: continuing education and read volume compliance
# ---------------------------------------------------------------------------
def evaluate_ce(person, policy):
    """Returns 'grace', 'deficient' or None describing the ce_status transition."""
    clock = DB.clock
    thresholds = CE_THRESHOLDS[person["role_type"]]
    ce_floor = clock - timedelta(days=CE_LOOKBACK_DAYS)
    volume_floor = clock - timedelta(days=VOLUME_LOOKBACK_DAYS)

    ce_hours = []
    volume = 0
    for credit in DB.all("credit"):
        if credit["personnel_id"] != person["id"]:
            continue
        awarded = credit["awarded_on"]
        if credit["credit_type"] == "CATEGORY_1_CE":
            if ce_floor <= awarded <= clock:
                ce_hours.append(credit["ce_hours"])
        elif credit["credit_type"] == "READ_VOLUME":
            if volume_floor <= awarded <= clock:
                volume += credit["exam_count"]

    ce_total = dsum(ce_hours)
    before_ce_status = person["ce_status"]
    before = (person["ce_hours_36mo"], person["volume_credit_24mo"],
              person["ce_status"], person["qualification_status"],
              person["ce_deadline_at"], person["last_qualification_review_at"])
    person["ce_hours_36mo"] = ce_total
    person["volume_credit_24mo"] = volume

    shortfall = ce_total < thresholds["ce_hours"] or volume < thresholds["volume"]
    initial_ok = (
        person["initial_training_hours"] >= thresholds["initial_hours"]
        and person["initial_read_volume"] >= thresholds["initial_volume"]
    )

    transition = None
    if not shortfall:
        person["ce_status"] = "COMPLIANT"
        person["ce_deadline_at"] = None
        if person["qualification_status"] == "LAPSED":
            person["qualification_status"] = "QUALIFIED"
        elif person["qualification_status"] == "PROVISIONAL" and initial_ok:
            person["qualification_status"] = "QUALIFIED"
    elif before_ce_status == "COMPLIANT":
        person["ce_status"] = "GRACE"
        person["ce_deadline_at"] = plus_days(clock, policy["ce_grace_days"])
        transition = "grace"
    elif before_ce_status == "GRACE" and person["ce_deadline_at"] is not None \
            and clock > person["ce_deadline_at"]:
        person["ce_status"] = "DEFICIENT"
        if person["qualification_status"] == "QUALIFIED":
            person["qualification_status"] = "LAPSED"
        transition = "deficient"
    elif before_ce_status == "GRACE":
        pass
    else:
        if person["qualification_status"] == "QUALIFIED":
            person["qualification_status"] = "LAPSED"

    person["last_qualification_review_at"] = clock
    after = (person["ce_hours_36mo"], person["volume_credit_24mo"],
             person["ce_status"], person["qualification_status"],
             person["ce_deadline_at"], person["last_qualification_review_at"])
    if before != after:
        touch(person)
    return transition


# ---------------------------------------------------------------------------
# calculation: radiologist audit metrics
# ---------------------------------------------------------------------------
def audit_metrics(cycle, variant):
    radiologist_id = cycle["radiologist_id"]
    start = cycle["period_start"]
    end = cycle["period_end"]
    window = timedelta(days=cycle["followup_window_days"])

    scope = []
    for exam in DB.all("exam"):
        if exam["interpreting_physician_id"] != radiologist_id:
            continue
        if exam["exam_type"] != "SCREENING":
            continue
        if exam["report_status"] not in ("INTERPRETED_FINAL", "AMENDED"):
            continue
        if not (start <= exam["performed_at"] < end):
            continue
        scope.append(exam)

    screening_exam_count = len(scope)
    recall_count = len([e for e in scope if e["recall_flag"]])
    recall_rate_pct = None
    if screening_exam_count > 0:
        recall_rate_pct = round2(recall_count, screening_exam_count)

    if variant == "PPV3_BIOPSY_ALL":
        candidates = [e for e in scope if e["biopsy_performed"]]
        scored = [e for e in candidates if e["pathology_result"] in SCORED_PATHOLOGY]
    else:
        candidates = [e for e in scope if e["recall_flag"] and e["biopsy_performed"]]
        scored = []
        for exam in candidates:
            if exam["pathology_result"] not in SCORED_PATHOLOGY:
                continue
            if exam["outcome_recorded_at"] is None:
                continue
            if exam["outcome_recorded_at"] < exam["performed_at"] + window:
                scored.append(exam)

    biopsy_count = len(scored)
    cancer_count = len([e for e in scored if e["pathology_result"] == "MALIGNANT"])
    excluded_exam_count = len(candidates) - len(scored)
    ppv_pct = None
    if biopsy_count > 0:
        ppv_pct = round2(cancer_count, biopsy_count)

    abnormal = recall_rate_pct is not None and not (
        RECALL_RATE_LOW <= recall_rate_pct <= RECALL_RATE_HIGH
    )

    return {
        "variant": variant,
        "screening_exam_count": screening_exam_count,
        "recall_count": recall_count,
        "biopsy_count": biopsy_count,
        "cancer_count": cancer_count,
        "excluded_exam_count": excluded_exam_count,
        "recall_rate_pct": recall_rate_pct,
        "ppv_pct": ppv_pct,
        "abnormal_interpretation_flag": abnormal,
    }


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def survey_failure_cascade(unit, critical_codes):
    """Five-level cascade fired by a failing survey decision."""
    changed = False
    if unit["survey_compliance"] != "FAILED":
        unit["survey_compliance"] = "FAILED"
        changed = True
    if unit["accreditation_status"] in ("ACCREDITED", "PROVISIONAL", "REACCREDITATION_DUE"):
        unit["accreditation_status"] = "PROBATION"
        changed = True
    if critical_codes and unit["operational_state"] != "OUT_OF_SERVICE":
        unit["operational_state"] = "OUT_OF_SERVICE"
        changed = True
    if changed:
        touch(unit)
    recompute_posture(facility_of_unit(unit))


def mark_survey_currency_on_pass(unit, survey):
    """A passing survey stamps the newest window and refreshes currency only when
    that window actually covers the clock."""
    changed = False
    if unit["last_passed_survey_end"] != survey["effective_end"]:
        unit["last_passed_survey_end"] = survey["effective_end"]
        changed = True
    if survey["effective_start"] <= DB.clock < survey["effective_end"]:
        if unit["survey_compliance"] != "CURRENT":
            unit["survey_compliance"] = "CURRENT"
            changed = True
    if changed:
        touch(unit)
    recompute_posture(facility_of_unit(unit))


def latest_passed_survey(unit_id):
    passed = [s for s in surveys_of_unit(unit_id) if s["status"] == "PASSED"]
    if not passed:
        return None
    passed.sort(key=lambda s: (s["effective_end"], s["_seq"]))
    return passed[-1]


# ---------------------------------------------------------------------------
# facility compliance checkpoint (five sweeps, then one posture recompute)
# ---------------------------------------------------------------------------
def run_compliance_checkpoint(facility):
    clock = DB.clock
    counters = {
        "units_marked_reaccreditation_due": 0,
        "units_survey_overdue": 0,
        "exams_marked_delayed": 0,
        "letters_marked_delivered": 0,
        "orders_marked_lost": 0,
        "personnel_moved_to_grace": 0,
        "personnel_moved_to_deficient": 0,
    }

    # sweep 1 -- unit survey currency and accreditation ageing
    for unit in in_order(units_of_facility(facility["id"]), "created_at"):
        changed = False
        if unit["survey_compliance"] != "FAILED":
            newest = latest_passed_survey(unit["id"])
            covered = newest is not None and \
                newest["effective_start"] <= clock < newest["effective_end"]
            desired = "CURRENT" if covered else "OVERDUE"
            if unit["survey_compliance"] != desired:
                unit["survey_compliance"] = desired
                changed = True
                if desired == "OVERDUE":
                    counters["units_survey_overdue"] += 1
        expires = unit["accreditation_expires_on"]
        if unit["accreditation_status"] == "ACCREDITED" and expires is not None:
            if clock >= expires - timedelta(days=REACCREDITATION_LEAD_DAYS):
                unit["accreditation_status"] = "REACCREDITATION_DUE"
                counters["units_marked_reaccreditation_due"] += 1
                changed = True
        if unit["accreditation_status"] == "REACCREDITATION_DUE" and expires is not None:
            if clock > expires + timedelta(days=SUSPENSION_GRACE_DAYS):
                unit["accreditation_status"] = "SUSPENDED"
                unit["operational_state"] = "OUT_OF_SERVICE"
                changed = True
        if changed:
            touch(unit)

    facility_exams = dict((e["id"], e) for e in exams_of_facility(facility["id"]))

    # sweep 2 -- overdue interpretations
    delayed = [e for e in facility_exams.values()
               if e["report_status"] == "AWAITING_INTERPRETATION"
               and e["report_due_at"] is not None and clock > e["report_due_at"]]
    for exam in in_order(delayed, "performed_at", "created_at"):
        exam["report_status"] = "DELAYED"
        touch(exam)
        counters["exams_marked_delayed"] += 1

    # sweep 3 -- assumed letter delivery
    letters = [l for l in DB.all("letter")
               if l["exam_id"] in facility_exams and l["status"] == "SENT"
               and l["sent_at"] is not None
               and clock >= l["sent_at"] + timedelta(days=DELIVERY_ASSUMPTION_DAYS)]
    for letter in in_order(letters, "sent_at", "created_at"):
        letter["status"] = "DELIVERED_ASSUMED"
        touch(letter)
        exam = facility_exams[letter["exam_id"]]
        if exam["notification_status"] != "COMPLETE":
            exam["notification_status"] = "COMPLETE"
            touch(exam)
        counters["letters_marked_delivered"] += 1

    # sweep 4 -- supplemental follow-up abandonment
    lost = [o for o in DB.all("order")
            if o["exam_id"] in facility_exams
            and o["status"] in ("RECOMMENDED", "COVERAGE_DETERMINED")
            and o["followup_due_at"] is not None and clock > o["followup_due_at"]]
    for order in in_order(lost, "recommended_at", "created_at"):
        order["status"] = "LOST_TO_FOLLOW_UP"
        touch(order)
        exam = facility_exams[order["exam_id"]]
        if exam["follow_up_status"] != "LOST_TO_FOLLOW_UP":
            exam["follow_up_status"] = "LOST_TO_FOLLOW_UP"
            touch(exam)
        counters["orders_marked_lost"] += 1

    # sweep 5 -- personnel continuing-education re-evaluation
    policy = home_policy(facility)
    for person in in_order(personnel_of_facility(facility["id"]), "created_at"):
        transition = evaluate_ce(person, policy)
        if transition == "grace":
            counters["personnel_moved_to_grace"] += 1
        elif transition == "deficient":
            counters["personnel_moved_to_deficient"] += 1

    recompute_open_notices(facility)
    recompute_posture(facility)
    facility["last_compliance_run_at"] = clock
    touch(facility)

    result = {"ran_at": clock}
    result.update(counters)
    result["compliance_posture"] = facility["compliance_posture"]
    return result
