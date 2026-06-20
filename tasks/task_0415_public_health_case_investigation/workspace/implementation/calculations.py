"""Calculation rules: infectious window, priority score, quarantine end,
isolation end, completeness score, outbreak cluster membership."""
from db import db
from helpers import parse_dt, to_iso, add_days, day_diff


def find_condition(program_id, condition_code):
    for c in db.conditions.values():
        if c["program_id"] == program_id and c["condition_code"] == condition_code:
            return c
    return None


# ---------------------------------------------------------------------------
# infectious_period_window
# ---------------------------------------------------------------------------
def compute_infectious_window(case):
    cond = find_condition(case["program_id"], case["condition_code"])
    if cond is None:
        return None, None
    if case["is_symptomatic"]:
        anchor = parse_dt(case.get("symptom_onset_date"))
    else:
        anchor = parse_dt(case.get("specimen_collection_date"))
    if anchor is None:
        return None, None
    start = add_days(anchor, -cond["presymptomatic_days"])
    end = add_days(anchor, cond["infectious_tail_days"])
    return to_iso(start), to_iso(end)


# ---------------------------------------------------------------------------
# contact_priority_score
# ---------------------------------------------------------------------------
_BASE = {"HOUSEHOLD": 50, "HEALTHCARE": 40, "WORKPLACE": 25, "SOCIAL": 15, "COMMUNITY": 10}


def compute_priority(exposure_setting, proximity_meters, cumulative_exposure_minutes, is_high_risk):
    base = _BASE[exposure_setting]
    if proximity_meters < 1:
        prox = 20
    elif proximity_meters <= 2:
        prox = 10
    else:
        prox = 0
    if cumulative_exposure_minutes >= 15:
        dur = 15
    elif cumulative_exposure_minutes >= 5:
        dur = 5
    else:
        dur = 0
    vuln = 20 if is_high_risk else 0
    raw = base + prox + dur + vuln
    score = max(0, min(100, raw))
    band = "HIGH" if score >= 70 else ("MEDIUM" if score >= 40 else "LOW")
    return score, band


# ---------------------------------------------------------------------------
# quarantine_end_date
# ---------------------------------------------------------------------------
def compute_quarantine(contact, condition):
    last_exposure = parse_dt(contact.get("last_exposure_date"))
    if last_exposure is None or condition is None:
        return "STANDARD", None
    if contact.get("has_qualifying_negative_test"):
        basis = "TEST_BASED"
        end = add_days(last_exposure, condition["test_based_release_days"])
    else:
        basis = "STANDARD"
        end = add_days(last_exposure, condition["quarantine_days"])
    return basis, to_iso(end)


def earliest_qualifying_date(contact, condition):
    last_exposure = parse_dt(contact.get("last_exposure_date"))
    if last_exposure is None or condition is None:
        return None
    return add_days(last_exposure, condition["test_release_earliest_offset_days"])


# ---------------------------------------------------------------------------
# isolation_end_date
# ---------------------------------------------------------------------------
def compute_isolation_end(case, condition):
    if condition is None:
        return None
    if case["is_symptomatic"]:
        anchor = parse_dt(case.get("symptom_onset_date"))
        if anchor is None:
            return None
        min_end = add_days(anchor, condition["isolation_min_days"])
        last_sympt = parse_dt(case.get("last_symptomatic_date"))
        if last_sympt is not None:
            symptom_end = add_days(last_sympt, condition["fever_free_days"])
        else:
            symptom_end = min_end
        end = max(min_end, symptom_end)
        return to_iso(end)
    else:
        anchor = parse_dt(case.get("specimen_collection_date"))
        if anchor is None:
            return None
        return to_iso(add_days(anchor, condition["isolation_min_days"]))


# ---------------------------------------------------------------------------
# case_completeness_score
# ---------------------------------------------------------------------------
def compute_completeness(case):
    score = 0
    if case.get("interview_completed"):
        score += 40
    if case.get("infectious_start_date") and case.get("infectious_end_date"):
        score += 20
    if case.get("contact_count", 0) >= 1:
        score += 20
    linked_count = sum(
        1 for l in db.lab_results.values()
        if l.get("status") == "LINKED" and l.get("linked_case_id") == case["id"]
    )
    if case.get("linked_positive_count", 0) >= 1 or linked_count >= 1:
        score += 20
    return score


def recompute_linked_positive(case):
    case["linked_positive_count"] = sum(
        1 for l in db.lab_results.values()
        if l.get("status") == "LINKED"
        and l.get("linked_case_id") == case["id"]
        and l.get("result_value") == "POSITIVE"
    )
