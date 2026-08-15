"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "GEOGRAPHY_NAME": "Main Campus",
    "GEOGRAPHY_CATEGORY": "ON_CAMPUS",
    "CSA_FULL_NAME": "Test Authority",
    "CSA_EMAIL": "csa@example.edu",
    "CSA_DEPARTMENT": "Student Affairs",
    "CSA_CATEGORY": "DEAN",
    "INCIDENT_REPORTED_AT": "2026-06-01T10:00:00Z",
    "INCIDENT_OCCURRED_AT": "2026-06-01T09:00:00Z",
    "INCIDENT_NARRATIVE": "Incident narrative",
    "TRAINING_COMPLETED_AT": "2026-06-01T10:00:00Z",
    "TRAINING_SCORE": 90,
    "FIRE_OCCURRED_AT": "2026-05-01T02:00:00Z",
    "FIRE_CAUSE": "COOKING",
    "FIRE_ESTIMATE": 100.00,
    "REPORT_YEAR": 2026,
    "REVIEW_START": 2024,
    "REVIEW_END": 2025,
    "ACTION_DUE_DATE": "2026-09-01",
}


def create_geography_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GEOGRAPHY_NAME"],
        "category": DEFAULTS["GEOGRAPHY_CATEGORY"],
        "is_residential_facility": False,
    }
    defaults.update(overrides)
    return defaults


def create_csa_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CSA_FULL_NAME"],
        "email": DEFAULTS["CSA_EMAIL"],
        "department": DEFAULTS["CSA_DEPARTMENT"],
        "csa_category": DEFAULTS["CSA_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "completed_at": DEFAULTS["TRAINING_COMPLETED_AT"],
        "score": DEFAULTS["TRAINING_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(geography_id, **overrides) -> dict:
    defaults = {
        "occurred_at": DEFAULTS["INCIDENT_OCCURRED_AT"],
        "geography_id": geography_id,
        "offense_suspicion": "BURGLARY",
        "narrative": "Referral narrative",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(geography_id, **overrides) -> dict:
    defaults = {
        "reported_at": DEFAULTS["INCIDENT_REPORTED_AT"],
        "occurred_at": DEFAULTS["INCIDENT_OCCURRED_AT"],
        "geography_id": geography_id,
        "source": "POLICE_DIRECT",
        "narrative": DEFAULTS["INCIDENT_NARRATIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_offense_count_payload(**overrides) -> dict:
    defaults = {
        "offense_type": "BURGLARY",
        "victim_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_classify_payload(geography_id, expected_incident_version, offense_counts=None, **overrides) -> dict:
    defaults = {
        "geography_id": geography_id,
        "offense_counts": offense_counts if offense_counts is not None else [create_offense_count_payload()],
        "expected_incident_version": expected_incident_version,
    }
    defaults.update(overrides)
    return defaults


def create_safety_alert_payload(**overrides) -> dict:
    defaults = {"alert_type": "TIMELY_WARNING"}
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {"decision": "ISSUE", "decision_rationale": "Continuing threat"}
    defaults.update(overrides)
    return defaults


def create_inspection_request_payload(**overrides) -> dict:
    defaults = {
        "requester_name": "Pat Public",
        "requester_contact": "pat@example.com",
        "from_date": "2026-06-01",
        "to_date": "2026-06-02",
    }
    defaults.update(overrides)
    return defaults


def create_asr_payload(**overrides) -> dict:
    defaults = {"report_year": DEFAULTS["REPORT_YEAR"]}
    defaults.update(overrides)
    return defaults


def create_compile_payload(expected_report_version, variant="FINAL", **overrides) -> dict:
    defaults = {"variant": variant, "expected_report_version": expected_report_version}
    defaults.update(overrides)
    return defaults


def create_fire_incident_payload(geography_id, **overrides) -> dict:
    defaults = {
        "geography_id": geography_id,
        "occurred_at": DEFAULTS["FIRE_OCCURRED_AT"],
        "cause_category": DEFAULTS["FIRE_CAUSE"],
        "injuries": 0,
        "deaths": 0,
        "estimated_damage_dollars": DEFAULTS["FIRE_ESTIMATE"],
    }
    defaults.update(overrides)
    return defaults


def create_fire_report_payload(**overrides) -> dict:
    defaults = {"report_year": DEFAULTS["REPORT_YEAR"]}
    defaults.update(overrides)
    return defaults


def create_program_review_payload(**overrides) -> dict:
    defaults = {
        "scope_year_start": DEFAULTS["REVIEW_START"],
        "scope_year_end": DEFAULTS["REVIEW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_corrective_action_payload(**overrides) -> dict:
    defaults = {
        "finding_code": "FND-001",
        "severity": "MEDIUM",
        "description": "Finding description",
        "due_date": DEFAULTS["ACTION_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults
