"""Payload factories — one per entity, input fields only (PRD §3).

Only `source: input` fields appear here. Computed and system fields
(status, version, composite_eligibility_score, lre_general_ed_pct, ...)
are never sent by the client.
"""

DEFAULTS = {
    "STUDENT_NAME": "Test Student",
    "DOB": "2014-01-01",
    "GRADE_LEVEL": 6,
    "SCHOOL_DAY_MINUTES": 360,
    "ANNUAL_REVIEW_DUE": "2027-03-01",
    "POSTSECONDARY_GOAL": "Competitive employment",
    "SERVICES_SUMMARY": "Job coaching and DVR linkage",
}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "grade_level": DEFAULTS["GRADE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "eval_type": "INITIAL",
        "cognitive_score": 110,
        "academic_score": 70,
        "adaptive_score": 75,
        "proposed_category": "SLD",
    }
    defaults.update(overrides)
    return defaults


def decide_consent_payload(decision: str) -> dict:
    return {"decision": decision}


def create_iep_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "school_day_minutes": DEFAULTS["SCHOOL_DAY_MINUTES"],
        "annual_review_due_date": DEFAULTS["ANNUAL_REVIEW_DUE"],
    }
    defaults.update(overrides)
    return defaults


def open_amendment_payload(expected_iep_version: int) -> dict:
    return {"expected_iep_version": expected_iep_version}


def create_goal_payload(iep_id: str, **overrides) -> dict:
    defaults = {
        "iep_id": iep_id,
        "domain": "READING",
        "baseline_value": 0,
        "target_value": 100,
    }
    defaults.update(overrides)
    return defaults


def create_progress_report_payload(goal_id: str, **overrides) -> dict:
    defaults = {
        "goal_id": goal_id,
        "reporting_period": 1,
        "measured_value": 0,
    }
    defaults.update(overrides)
    return defaults


def create_related_service_payload(iep_id: str, expected_iep_version: int, **overrides) -> dict:
    defaults = {
        "iep_id": iep_id,
        "service_type": "SPEECH",
        "minutes_per_week": 150,
        "delivered_in_general_ed": False,
        "expected_iep_version": expected_iep_version,
    }
    defaults.update(overrides)
    return defaults


def discontinue_related_service_payload(expected_iep_version: int) -> dict:
    return {"expected_iep_version": expected_iep_version}


def create_transition_plan_payload(iep_id: str, **overrides) -> dict:
    defaults = {
        "iep_id": iep_id,
        "postsecondary_goal": DEFAULTS["POSTSECONDARY_GOAL"],
        "services_summary": DEFAULTS["SERVICES_SUMMARY"],
    }
    defaults.update(overrides)
    return defaults
