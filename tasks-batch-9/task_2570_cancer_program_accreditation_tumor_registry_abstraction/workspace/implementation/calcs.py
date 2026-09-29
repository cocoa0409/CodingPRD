"""Pure calculation rules (PRD 2.10 and the section 3 workflows)."""

from decimal import Decimal, ROUND_HALF_UP

import spec


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return d.quantize(quant, rounding=ROUND_HALF_UP)


def pct(numerator, denominator, places=1):
    """numerator/denominator * 100 rounded half up; float result."""
    value = Decimal(numerator) / Decimal(denominator) * Decimal(100)
    return float(rhu(value, places))


def clamp_pct(value):
    if value < 0.0:
        return 0.0
    if value > 100.0:
        return 100.0
    return value


# --------------------------------------------------------------- reportability

def class_of_case(diagnosed_at_facility, first_treatment_at_facility,
                  referral_lag_days):
    if diagnosed_at_facility and first_treatment_at_facility:
        return "CLASS_10"
    if diagnosed_at_facility and not first_treatment_at_facility:
        return "CLASS_00"
    if (not diagnosed_at_facility) and first_treatment_at_facility:
        if referral_lag_days <= spec.CLASS_20_MAX_LAG_DAYS:
            return "CLASS_20"
        return "CLASS_31"
    return "CLASS_40"


def analytic_flag(class_code):
    return class_code in ("CLASS_00", "CLASS_10", "CLASS_20")


def reportability_suggestion(diagnosis_date, reference_year, behavior_code,
                             primary_site_code, histology_code):
    if diagnosis_date.year < reference_year:
        return "NON_REPORTABLE", "BEFORE_REFERENCE_YEAR"
    site = primary_site_code or ""
    histology = histology_code or ""
    if (behavior_code == "MALIGNANT_3"
            and site.startswith(spec.SKIN_SITE_PREFIX)
            and histology in spec.EXCLUDED_SKIN_HISTOLOGIES):
        return "NON_REPORTABLE", "SKIN_SQUAMOUS_BASAL_EXCLUDED"
    if behavior_code == "IN_SITU_2" and site == spec.CERVIX_SITE:
        return "NON_REPORTABLE", "CERVIX_IN_SITU_EXCLUDED"
    if behavior_code in ("MALIGNANT_3", "IN_SITU_2"):
        return "REPORTABLE", "SEER_REPORTABLE_BEHAVIOR"
    if behavior_code in ("BENIGN_0", "BORDERLINE_1") and site in spec.CNS_SITES:
        return "REPORTABLE", "CNS_BENIGN_REPORTABLE"
    return "NON_REPORTABLE", "BENIGN_NON_CNS"


# ----------------------------------------------------------------- timeliness

def timeliness(case, due_date, clock_day):
    """Return (timeliness_status, days_to_due) for a case row."""
    state = case["case_state"]
    if state == "COMPLETED" and case.get("completed_on"):
        from db import parse_date
        completed = parse_date(case["completed_on"])
        status = "ON_TIME" if completed <= due_date else "LATE"
        return status, (due_date - completed).days
    if state == "VOIDED":
        return "ON_TIME", (due_date - clock_day).days
    days = (due_date - clock_day).days
    if days < 0:
        return "LATE", days
    if days <= 30:
        return "AT_RISK", days
    return "ON_TIME", days


# --------------------------------------------------------------- completeness

_BASE_REQUIRED = ("stage_group", "stage_source", "first_treatment_date",
                  "treatment_modalities", "outcome_status", "last_contact_date")


def _is_missing(value):
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def completeness(abstraction, case):
    required = set(_BASE_REQUIRED)
    modalities = abstraction.get("treatment_modalities") or []
    if abstraction.get("stage_source") == "PATHOLOGIC":
        required.update(("t_category", "n_category", "m_category"))
    if case.get("class_of_case_code") in ("CLASS_00", "CLASS_10"):
        required.add("diagnostic_confirmation_code")
    if "RADIATION" in modalities:
        required.add("radiation_start_date")
    if not case.get("analytic_flag"):
        required.discard("outcome_status")
        required.discard("last_contact_date")
    if "NO_TREATMENT" in modalities:
        required.discard("first_treatment_date")

    missing = sorted(name for name in required
                     if _is_missing(abstraction.get(name)))

    score = 100 - 12 * len(missing)
    if abstraction.get("stage_group") == "UNKNOWN":
        score -= 8
    if (abstraction.get("stage_source") == "CLINICAL"
            and case.get("class_of_case_code") == "CLASS_10"):
        score -= 6
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return missing, score


# ---------------------------------------------------------------------- audits

def weighted_error_score(minor, major, critical):
    return 5 * critical + 3 * major + 1 * minor


def audit_verdict(weighted, critical):
    if critical >= 1:
        return "CRITICAL_FAIL"
    if weighted <= 2:
        return "PASS"
    return "MINOR_FAIL"


# ------------------------------------------------------------------- capacity

def capacity_cap(target_per_day):
    return int(rhu(Decimal(str(target_per_day)) * spec.CAPACITY_MULTIPLIER, 0))


def productivity_rate(completed_cases_30d):
    return float(rhu(Decimal(completed_cases_30d)
                     / Decimal(spec.WORKING_DAYS_PER_30), 2))


# ----------------------------------------------------------------- conference

def prospective_ratio(prospective, presented):
    if not presented:
        return 0.0
    return float(rhu(Decimal(prospective) / Decimal(presented), 3))


def quorum_met(session):
    presented = session.get("cases_presented_count") or 0
    if presented <= 0:
        return False
    qualifying = set()
    for att in session.get("attendances") or []:
        if (att.get("attended_minutes") or 0) >= spec.CONFERENCE_QUALIFYING_MINUTES:
            qualifying.add(att.get("discipline"))
    for discipline in session.get("required_disciplines") or []:
        if discipline not in qualifying:
            return False
    ratio = prospective_ratio(session.get("prospective_case_count") or 0,
                              presented)
    return ratio >= spec.CONFERENCE_PROSPECTIVE_MIN_RATIO


# ----------------------------------------------------------------- assessment

def assessment(late_case_count, transmitted_late):
    record_component = spec.LATE_RECORD_FEE_CENTS * late_case_count
    batch_component = spec.LATE_BATCH_FEE_CENTS if transmitted_late else 0
    pre_relief = record_component + batch_component
    relief = Decimal("0.00")
    for threshold, value in spec.RELIEF_TIERS:
        if pre_relief >= threshold:
            relief = Decimal(value)
            break
    due = int(rhu(Decimal(pre_relief) * (Decimal(1) - relief), 0))
    return pre_relief, float(relief), due


# ------------------------------------------------------------ quality measure

def measure_rates(strata):
    """Return (surviving, included_count, performance_rate, pooled_rate)."""
    surviving = [s for s in strata if (s.get("eligible_case_count") or 0) > 0]
    if not surviving:
        return [], 0, None, None
    per_stratum = []
    for s in surviving:
        per_stratum.append(Decimal(str(pct(s["compliant_case_count"],
                                          s["eligible_case_count"]))))
    performance = float(rhu(sum(per_stratum) / Decimal(len(per_stratum)), 1))
    total_compliant = sum(s["compliant_case_count"] for s in surviving)
    total_eligible = sum(s["eligible_case_count"] for s in surviving)
    pooled = pct(total_compliant, total_eligible)
    return surviving, len(surviving), performance, pooled


def performance_state(basis_rate, threshold_pct):
    if basis_rate is None:
        return "NOT_EVALUATED"
    basis = Decimal(str(basis_rate))
    threshold = Decimal(str(threshold_pct))
    if basis >= threshold + Decimal("10.0"):
        return "EXCEEDS"
    if basis >= threshold:
        return "MEETS"
    return "UNDER_THRESHOLD"
