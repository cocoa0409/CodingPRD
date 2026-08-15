"""Payload factories — one per creatable resource, input fields only (PRD §4)."""

DEFAULTS = {
    "SYSTEM_NAME": "Test County Schools",
    "SYSTEM_TYPE": "SINGLE_SCHOOL",
    "CAMPUS_NAME": "Main Campus",
    "ENROLLMENT": 300,
    "STANDARD_CODE": "L1",
    "STANDARD_TITLE": "Leadership Standard 1",
    "STANDARD_DOMAIN": "LEADERSHIP",
    "WEIGHT_PCT": 100,
    "EVIDENCE_MIN_ITEMS": 0,
    "TERM_START": "2026-09-01T00:00:00Z",
    "TERM_LENGTH_YEARS": 5,
    "RATING": 3,
    "EVIDENCE_TITLE": "Policy Document",
    "ARTIFACT_URI": "s3://evidence/policy.pdf",
    "STAKEHOLDER_GROUP": "STAFF",
    "INSTRUMENT_TITLE": "Staff Survey",
    "MIN_PARTICIPATION_PCT": 50,
    "OPENS_AT": "2026-10-01T00:00:00Z",
    "CLOSES_AT": "2026-11-01T00:00:00Z",
    "ELIGIBLE_COUNT": 4,
    "GOAL_TITLE": "Raise proficiency",
    "BASELINE_VALUE": 50,
    "TARGET_VALUE": 80,
    "DIRECTION": "INCREASE",
    "MEASURED_AT": "2027-01-15T00:00:00Z",
    "INDICATOR_VALUE": 65,
    "REVIEWER_NAME": "Rita Reviewer",
    "REVIEWER_EMAIL": "rita@accreditor.org",
    "STARTS_ON": "2026-11-02T00:00:00Z",
    "ENDS_ON": "2026-11-04T00:00:00Z",
    "ROLE_ON_TEAM": "CHAIR",
    "SEVERITY": "COMMENDATION",
    "NARRATIVE": "Strong governance.",
    "REPORT_YEAR": 1,
    "REPORT_NARRATIVE": "Year one progress.",
    "BILLING_YEAR": 2026,
    "INVOICE_TYPE": "ANNUAL_FEE",
    "PAID_AT": "2026-08-02T00:00:00Z",
}


def create_system_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SYSTEM_NAME"],
        "system_type": DEFAULTS["SYSTEM_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_campus_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPUS_NAME"],
        "enrollment": DEFAULTS["ENROLLMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_standard_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["STANDARD_CODE"],
        "title": DEFAULTS["STANDARD_TITLE"],
        "domain": DEFAULTS["STANDARD_DOMAIN"],
        "weight_pct": DEFAULTS["WEIGHT_PCT"],
        "evidence_min_items": DEFAULTS["EVIDENCE_MIN_ITEMS"],
    }
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "term_start": DEFAULTS["TERM_START"],
        "term_length_years": DEFAULTS["TERM_LENGTH_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_rating_payload(term_id, campus_id, standard_id, expected_term_version,
                          **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "campus_id": campus_id,
        "standard_id": standard_id,
        "rating": DEFAULTS["RATING"],
        "expected_term_version": expected_term_version,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["EVIDENCE_TITLE"],
        "artifact_uri": DEFAULTS["ARTIFACT_URI"],
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = {
        "stakeholder_group": DEFAULTS["STAKEHOLDER_GROUP"],
        "title": DEFAULTS["INSTRUMENT_TITLE"],
        "min_participation_pct": DEFAULTS["MIN_PARTICIPATION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_window_payload(campus_id, instrument_id, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "instrument_id": instrument_id,
        "opens_at": DEFAULTS["OPENS_AT"],
        "closes_at": DEFAULTS["CLOSES_AT"],
        "eligible_count": DEFAULTS["ELIGIBLE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_response_payload(respondent_token, **overrides) -> dict:
    defaults = {"respondent_token": respondent_token}
    defaults.update(overrides)
    return defaults


def create_goal_payload(standard_id, **overrides) -> dict:
    defaults = {
        "standard_id": standard_id,
        "title": DEFAULTS["GOAL_TITLE"],
        "baseline_value": DEFAULTS["BASELINE_VALUE"],
        "target_value": DEFAULTS["TARGET_VALUE"],
        "direction": DEFAULTS["DIRECTION"],
    }
    defaults.update(overrides)
    return defaults


def create_indicator_payload(expected_goal_version, **overrides) -> dict:
    defaults = {
        "measured_at": DEFAULTS["MEASURED_AT"],
        "value": DEFAULTS["INDICATOR_VALUE"],
        "expected_goal_version": expected_goal_version,
    }
    defaults.update(overrides)
    return defaults


def create_reviewer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["REVIEWER_NAME"],
        "email": DEFAULTS["REVIEWER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(lead_reviewer_id, **overrides) -> dict:
    defaults = {
        "lead_reviewer_id": lead_reviewer_id,
        "starts_on": DEFAULTS["STARTS_ON"],
        "ends_on": DEFAULTS["ENDS_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(reviewer_id, **overrides) -> dict:
    defaults = {
        "reviewer_id": reviewer_id,
        "role_on_team": DEFAULTS["ROLE_ON_TEAM"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(standard_id, **overrides) -> dict:
    defaults = {
        "standard_id": standard_id,
        "severity": DEFAULTS["SEVERITY"],
        "narrative": DEFAULTS["NARRATIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_action_evidence_payload(**overrides) -> dict:
    defaults = {"narrative": "Follow-up evidence package."}
    defaults.update(overrides)
    return defaults


def create_interim_report_payload(**overrides) -> dict:
    defaults = {
        "report_year": DEFAULTS["REPORT_YEAR"],
        "narrative": DEFAULTS["REPORT_NARRATIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "effective_from": "2026-01-01T00:00:00Z",
        "base_system_fee_cents": 500000,
        "per_campus_fee_cents": 120000,
        "large_campus_fee_cents": 200000,
        "large_campus_threshold": 1000,
        "visit_day_rate_cents": 75000,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "billing_year": DEFAULTS["BILLING_YEAR"],
        "invoice_type": DEFAULTS["INVOICE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, expected_invoice_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "paid_at": DEFAULTS["PAID_AT"],
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults
