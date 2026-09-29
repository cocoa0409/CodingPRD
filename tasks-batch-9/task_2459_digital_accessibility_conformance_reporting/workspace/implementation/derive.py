"""Derived fields and cascades (PRD 2.9, 3.1, 3.4, 3.8, 3.10)."""
from calc import (
    MIN_ATTEST_COVERAGE_PCT,
    POSTURE_INDEX_FLOOR,
    CORRECTION_WINDOW_DAYS,
    STALE_QUESTIONNAIRE_LIMIT,
    STALE_WINDOW_DAYS,
    component_coverage_pct,
    component_evidence_units,
    component_validated_categories,
    conformance_index,
    questionnaire_disclosure_debt,
)
from db import clock_date, clock_now, db, dt_plus_days, iso_plus_days, touch


def mark_stale(questionnaire):
    """CURRENT -> STALE with a fresh 30-day update deadline (PRD 3.10)."""
    questionnaire["accuracy_status"] = "STALE"
    questionnaire["update_due_at"] = iso_plus_days(STALE_WINDOW_DAYS)
    questionnaire["_update_due_dt"] = dt_plus_days(STALE_WINDOW_DAYS)
    touch(questionnaire)


def mark_correction_required(questionnaire):
    """CURRENT/STALE -> CORRECTION_REQUIRED with a 10-day deadline (PRD 3.10)."""
    questionnaire["accuracy_status"] = "CORRECTION_REQUIRED"
    questionnaire["correction_due_at"] = iso_plus_days(CORRECTION_WINDOW_DAYS)
    questionnaire["update_due_at"] = None
    questionnaire["_update_due_dt"] = None
    touch(questionnaire)


# --------------------------------------------------------- lookups ----------
def product_components(product_id):
    return [c for c in db.components.values() if c["product_id"] == product_id]


def product_questionnaires(product_id):
    return [q for q in db.questionnaires.values() if q["product_id"] == product_id]


def product_issues(product_id):
    return [i for i in db.issues.values() if i["product_id"] == product_id]


def product_complaints(product_id):
    return [c for c in db.complaints.values() if c["product_id"] == product_id]


def component_assessments(component_id):
    return [a for a in db.assessments.values() if a["component_id"] == component_id]


# ------------------------------------------------- component cascade --------
def flip_attested_assessments(component_id):
    """A component leaving COMPLETE invalidates its attested rows (PRD 3.5)."""
    for assessment in component_assessments(component_id):
        if assessment["attestation_state"] == "ATTESTED":
            assessment["attestation_state"] = "NEEDS_REVALIDATION"
            touch(assessment)


def flip_assessments_citing_run(run_id):
    for assessment in db.assessments.values():
        if (assessment.get("evidence_run_id") == run_id
                and assessment["attestation_state"] == "ATTESTED"):
            assessment["attestation_state"] = "NEEDS_REVALIDATION"
            touch(assessment)


def refresh_component_evidence(component):
    """Recompute evidence total, coverage, validated categories and the
    testing dimension.  Returns True when the component left COMPLETE."""
    component["evidence_units_total"] = component_evidence_units(component)
    coverage = component_coverage_pct(component)
    component["coverage_pct"] = coverage
    component["validated_disability_categories"] = component_validated_categories(
        component)

    reverted = False
    if component["assessment_state"] == "IN_TESTING":
        if coverage >= MIN_ATTEST_COVERAGE_PCT:
            component["assessment_state"] = "COMPLETE"
    elif component["assessment_state"] == "COMPLETE":
        if coverage < MIN_ATTEST_COVERAGE_PCT:
            component["assessment_state"] = "IN_TESTING"
            reverted = True
    return reverted


# ------------------------------------------------------ product counters ----
def refresh_component_counters(product):
    components = product_components(product["id"])
    in_scope = [c for c in components if c["in_scope"]]
    product["components_in_scope_count"] = len(in_scope)
    product["components_complete_count"] = sum(
        1 for c in in_scope if c["assessment_state"] == "COMPLETE")
    product["assessment_readiness"] = (
        "READY" if in_scope and len(in_scope) == product["components_complete_count"]
        else "NOT_READY")


def refresh_questionnaire_counters(product):
    rows = product_questionnaires(product["id"])
    product["stale_questionnaire_count"] = sum(
        1 for q in rows if q["accuracy_status"] == "STALE")
    product["correction_required_questionnaire_count"] = sum(
        1 for q in rows if q["accuracy_status"] == "CORRECTION_REQUIRED")


def refresh_issue_counters(product):
    today = clock_date()
    count = 0
    for issue in product_issues(product["id"]):
        if issue["severity"] != "BLOCKER":
            continue
        if issue["state"] != "PUBLISHED_COMMITTED":
            continue
        target = issue.get("_public_target_date")
        if target is not None and target < today:
            count += 1
    product["overdue_committed_blocker_count"] = count


def refresh_complaint_counters(product):
    product["accommodations_fulfilled_count"] = sum(
        1 for c in product_complaints(product["id"])
        if c.get("accommodation_fulfilled_at"))


def refresh_provisional_index(product):
    index, denominator, _ = conformance_index(product, "PROVISIONAL")
    product["conformance_index_provisional"] = index
    product["assessed_criteria_count"] = denominator


# --------------------------------------------------------------- posture ----
def derive_posture_value(product):
    if (product["overdue_committed_blocker_count"] >= 1
            or product["correction_required_questionnaire_count"] >= 1):
        return "FROZEN"
    index_breach = (product["assessed_criteria_count"] >= 1
                    and product["conformance_index_provisional"] < POSTURE_INDEX_FLOOR)
    if index_breach or product["stale_questionnaire_count"] >= STALE_QUESTIONNAIRE_LIMIT:
        return "RESTRICTED"
    return "OPEN"


def _cascade_restricted(product):
    for questionnaire in product_questionnaires(product["id"]):
        if questionnaire["accuracy_status"] == "CURRENT":
            mark_stale(questionnaire)


def _cascade_frozen(product):
    for questionnaire in product_questionnaires(product["id"]):
        if questionnaire["accuracy_status"] in ("CURRENT", "STALE"):
            mark_correction_required(questionnaire)


def rederive_posture(product):
    """Re-derive posture and run the one-directional questionnaire cascade.

    Writes made *by* the cascade never re-trigger this function (PRD 2.9/3.8).
    """
    previous = product["publication_posture"]
    current = derive_posture_value(product)
    product["publication_posture"] = current
    if current == previous:
        return current
    if current == "RESTRICTED" and previous == "OPEN":
        _cascade_restricted(product)
        refresh_questionnaire_counters(product)
    elif current == "FROZEN":
        _cascade_frozen(product)
        refresh_questionnaire_counters(product)
    return current


# ------------------------------------------------------ disclosure debt -----
def refresh_disclosure_debts(product_id):
    """Rebuild debt on every SUBMITTED or ATTESTED response of the product."""
    for questionnaire in product_questionnaires(product_id):
        if questionnaire["review_status"] in ("SUBMITTED", "ATTESTED"):
            debt, tier = questionnaire_disclosure_debt(questionnaire)
            if (questionnaire["disclosure_debt"] != debt
                    or questionnaire["disclosure_tier"] != tier):
                questionnaire["disclosure_debt"] = debt
                questionnaire["disclosure_tier"] = tier
                touch(questionnaire)


def refresh_questionnaire(questionnaire):
    debt, tier = questionnaire_disclosure_debt(questionnaire)
    questionnaire["disclosure_debt"] = debt
    questionnaire["disclosure_tier"] = tier


# ---------------------------------------------------- whole-product pass ----
def recompute_product(product, lapse_accuracy=False):
    """Rebuild every derived field of a product, then re-derive the posture."""
    refresh_component_counters(product)
    refresh_provisional_index(product)
    if lapse_accuracy:
        now = clock_now()
        for questionnaire in product_questionnaires(product["id"]):
            if questionnaire["accuracy_status"] != "CURRENT":
                continue
            due = questionnaire.get("_update_due_dt")
            if due is not None and due < now:
                mark_stale(questionnaire)
    refresh_questionnaire_counters(product)
    refresh_issue_counters(product)
    refresh_complaint_counters(product)
    return rederive_posture(product)
