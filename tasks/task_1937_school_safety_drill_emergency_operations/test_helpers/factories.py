"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SITE_NAME": "Ridgeview Elementary",
    "ENROLLMENT_COUNT": 500,
    "YEAR_START": "2026-08-01",
    "YEAR_END": "2027-06-30",
    "DRILL_TYPE": "FIRE",
    "REQUIRED_PER_YEAR": 2,
    "MIN_SPACING_DAYS": 20,
    "TARGET_EVAC_SECONDS": 300,
    "EOP_TITLE": "EOP 2026",
    "EOP_VERSION_LABEL": "v1",
    "EOP_CONTENT_SUMMARY": "Evacuation and lockdown procedures",
    "EOP_REVIEW_DUE": "2027-08-01",
    "SITE_PLAN_TITLE": "Floor Plan 2026",
    "SITE_PLAN_ISSUED_ON": "2026-07-01",
    "SITE_PLAN_REVIEW_BY": "2027-01-15",
    "COVERAGE_TAGS": ["FLOOR_PLANS", "ACCESS_POINTS"],
    "AGENCY": "FIRE",
    "WALKTHROUGH_DATE": "2026-07-20",
    "FINDINGS_SUMMARY": "Exits and assembly areas verified",
    "RECOMMENDATIONS_COUNT": 0,
    "DRILL_DATE": "2026-09-15",
    "DRILL_START_TIME": "09:00",
    "DURATION_MINUTES": 30,
    "ANNOUNCEMENT_MODE": "ANNOUNCED",
    "STUDENT_REF": "stu-1",
    "REVIEW_FINDINGS": "Evacuation orderly",
    "OVERALL_RATING": "MEETS",
    "EVACUATION_ASSESSMENT": "MET_STANDARD",
    "CA_DESCRIPTION": "Replace gate signage",
    "CA_PRIORITY": "HIGH",
    "CA_DUE_DATE": "2026-10-15",
    "CA_ASSIGNEE": "Facilities Lead",
    "NEED_TYPE": "MOBILITY",
    "ACCOMMODATION_INSTRUCTIONS": "Staff-assisted evacuation via ramp route",
    "ACCOMMODATION_REVIEW_BY": "2027-01-15",
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2027-06-30",
    "GUARDIAN_NAME": "Jane Doe",
}


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "enrollment_count": DEFAULTS["ENROLLMENT_COUNT"],
        "academic_year_start": DEFAULTS["YEAR_START"],
        "academic_year_end": DEFAULTS["YEAR_END"],
    }
    defaults.update(overrides)
    return defaults


def create_requirement_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "drill_type": DEFAULTS["DRILL_TYPE"],
        "required_per_year": DEFAULTS["REQUIRED_PER_YEAR"],
        "min_spacing_days": DEFAULTS["MIN_SPACING_DAYS"],
        "target_evac_seconds": DEFAULTS["TARGET_EVAC_SECONDS"],
    }
    defaults.update(overrides)
    if defaults.get("notes") is None:
        defaults.pop("notes", None)
    return defaults


def create_eop_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "title": DEFAULTS["EOP_TITLE"],
        "plan_version_label": DEFAULTS["EOP_VERSION_LABEL"],
        "content_summary": DEFAULTS["EOP_CONTENT_SUMMARY"],
        "review_due_date": DEFAULTS["EOP_REVIEW_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_site_plan_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "document_title": DEFAULTS["SITE_PLAN_TITLE"],
        "issued_on": DEFAULTS["SITE_PLAN_ISSUED_ON"],
        "review_by_date": DEFAULTS["SITE_PLAN_REVIEW_BY"],
        "coverage_tags": list(DEFAULTS["COVERAGE_TAGS"]),
    }
    defaults.update(overrides)
    return defaults


def create_walkthrough_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "agency": DEFAULTS["AGENCY"],
        "scheduled_date": DEFAULTS["WALKTHROUGH_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_walkthrough_completion_payload(**overrides) -> dict:
    defaults = {
        "completed_date": DEFAULTS["WALKTHROUGH_DATE"],
        "findings_summary": DEFAULTS["FINDINGS_SUMMARY"],
        "recommendations_count": DEFAULTS["RECOMMENDATIONS_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_drill_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "drill_type": DEFAULTS["DRILL_TYPE"],
        "scheduled_date": DEFAULTS["DRILL_DATE"],
        "scheduled_start_time": DEFAULTS["DRILL_START_TIME"],
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
        "announcement_mode": DEFAULTS["ANNOUNCEMENT_MODE"],
    }
    defaults.update(overrides)
    return defaults


def create_roster_entry_payload(**overrides) -> dict:
    defaults = {
        "student_ref": DEFAULTS["STUDENT_REF"],
        "accommodation_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    defaults = {
        "guardian_name": DEFAULTS["GUARDIAN_NAME"],
        "released_to_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_aar_payload(**overrides) -> dict:
    defaults = {
        "findings_summary": DEFAULTS["REVIEW_FINDINGS"],
        "overall_rating": DEFAULTS["OVERALL_RATING"],
        "evacuation_assessment": DEFAULTS["EVACUATION_ASSESSMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["CA_DESCRIPTION"],
        "priority": DEFAULTS["CA_PRIORITY"],
        "due_date": DEFAULTS["CA_DUE_DATE"],
        "assignee_name": DEFAULTS["CA_ASSIGNEE"],
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_plan_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "student_ref": DEFAULTS["STUDENT_REF"],
        "need_type": DEFAULTS["NEED_TYPE"],
        "instructions": DEFAULTS["ACCOMMODATION_INSTRUCTIONS"],
        "review_by_date": DEFAULTS["ACCOMMODATION_REVIEW_BY"],
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


__all__ = [
    "DEFAULTS",
    "create_site_payload", "create_requirement_payload", "create_eop_payload",
    "create_site_plan_payload", "create_walkthrough_payload",
    "create_walkthrough_completion_payload", "create_drill_payload",
    "create_roster_entry_payload", "create_release_payload", "create_aar_payload",
    "create_corrective_action_payload", "create_accommodation_plan_payload",
    "create_compliance_report_payload",
]
