"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "STUDENT_EXTERNAL_REF": "S1000",
    "STUDENT_FULL_NAME": "Test Student",
    "STAFF_FULL_NAME": "Test Staff",
    "STAFF_OFFICE": "BIT_OFFICE",
    "REPORT_CATEGORY": "WELLBEING_GENERAL",
    "REPORT_NARRATIVE": "Observed concerning behavior",
    "REPORT_OBSERVED_AT": "2026-07-31T10:00:00Z",
    "SCORING_RATIONALE": "rubric assessment",
    "PLAN_OBJECTIVE": "weekly check-in",
    "PLAN_SUCCESS_CRITERIA": "sustained stability",
    "ASSESSMENT_RATIONALE": "clinical judgment required",
    "ASSESSMENT_DUE_AT": "2026-08-10T00:00:00Z",
    "LEAVE_RATIONALE": "safety determination",
    "PETITION_SUMMARY": "readiness evidence attached",
    "REENTRY_RATIONALE": "decision rationale",
    "GRANT_PURPOSE": "need-to-know coordination",
    "GRANT_EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "GRANT_EXPIRES_AT": "2026-09-01T00:00:00Z",
    "TREND_TERM_CODE": "2026-FALL",
    "TREND_WINDOW_START": "2026-08-01T00:00:00Z",
    "TREND_WINDOW_END": "2026-08-31T23:59:59Z",
    "CHECKIN_NOTE": "check-in completed",
    "FINDINGS_SUMMARY": "evaluation findings",
    "REVISION_NOTE": "please revise",
    "DENY_RATIONALE": "denied",
}

_student_seq = {"n": 1000}


def next_external_ref() -> str:
    _student_seq["n"] += 1
    return f"S{_student_seq['n']}"


def create_student_payload(**overrides) -> dict:
    defaults = {
        "external_ref": next_external_ref(),
        "full_name": DEFAULTS["STUDENT_FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STAFF_FULL_NAME"],
        "office": DEFAULTS["STAFF_OFFICE"],
    }
    defaults.update(overrides)
    return defaults


def create_concern_report_payload(**overrides) -> dict:
    defaults = {
        "student_id": None,
        "category": DEFAULTS["REPORT_CATEGORY"],
        "narrative": DEFAULTS["REPORT_NARRATIVE"],
        "observed_at": DEFAULTS["REPORT_OBSERVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_risk_scoring_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "mode": "INITIAL",
        "harm_to_self": 0,
        "harm_to_others": 0,
        "academic_disruption": 0,
        "substance_involvement": 0,
        "rationale": DEFAULTS["SCORING_RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_intervention_plan_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "expected_case_version": None,
        "objectives": [DEFAULTS["PLAN_OBJECTIVE"]],
        "success_criteria": DEFAULTS["PLAN_SUCCESS_CRITERIA"],
    }
    defaults.update(overrides)
    return defaults


def create_mandated_assessment_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "evaluator_id": None,
        "due_at": DEFAULTS["ASSESSMENT_DUE_AT"],
        "rationale": DEFAULTS["ASSESSMENT_RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_leave_decide_payload(**overrides) -> dict:
    defaults = {
        "decision": "GRANT_LEAVE",
        "rationale": DEFAULTS["LEAVE_RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_reentry_evaluation_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "expected_case_version": None,
        "petition_summary": DEFAULTS["PETITION_SUMMARY"],
    }
    defaults.update(overrides)
    return defaults


def create_reentry_decide_payload(**overrides) -> dict:
    defaults = {
        "outcome": "APPROVED_WITH_CONDITIONS",
        "conditions": ["weekly counseling session"],
        "rationale": DEFAULTS["REENTRY_RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_checkin_complete_payload(**overrides) -> dict:
    defaults = {
        "outcome": "STABLE",
        "note": DEFAULTS["CHECKIN_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_grant_payload(**overrides) -> dict:
    defaults = {
        "case_id": None,
        "to_office": "RESIDENCE_LIFE",
        "scope": "SUMMARY_ONLY",
        "effective_from": DEFAULTS["GRANT_EFFECTIVE_FROM"],
        "expires_at": DEFAULTS["GRANT_EXPIRES_AT"],
        "purpose": DEFAULTS["GRANT_PURPOSE"],
    }
    defaults.update(overrides)
    return defaults


def create_trend_report_payload(**overrides) -> dict:
    defaults = {
        "term_code": DEFAULTS["TREND_TERM_CODE"],
        "window_start": DEFAULTS["TREND_WINDOW_START"],
        "window_end": DEFAULTS["TREND_WINDOW_END"],
        "variant": "ENTRY_COHORT",
    }
    defaults.update(overrides)
    return defaults
