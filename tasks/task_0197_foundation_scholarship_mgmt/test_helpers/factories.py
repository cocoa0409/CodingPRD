"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only `source: input` fields appear here.
"""

DEFAULTS = {
    "FUND_NAME": "Test Scholarship Fund",
    "ENDOWMENT_CENTS": 5_000_000,
    "AWARD_TERM": "FALL",
    "MIN_GPA": 2.00,
    "REQUIRED_RESIDENCY_STATE": "ANY",
    "REQUIRED_FIELD_OF_STUDY": "ANY",
    "MAX_AWARD_CENTS": 1_000_000,
    "FULL_NAME": "Test Applicant",
    "EMAIL": "applicant@example.edu",
    "SELF_REPORTED_GPA": 3.50,
    "RESIDENCY_STATE": "CA",
    "FIELD_OF_STUDY": "CS",
    "INSTITUTION_ID": "INST-TEST",
    "REQUESTED_AMOUNT_CENTS": 500_000,
    "RECOMMENDER_NAME": "Prof. Reference",
    "DOCUMENT_URI": "s3://docs/test",
    "VERIFIED_GPA": 3.50,
    "MEMBER_NAME": "Test Reviewer",
    "MEMBER_EMAIL": "reviewer@example.edu",
    "EXPERTISE_FIELD": "CS",
    "ACADEMIC_SCORE": 90,
    "NEED_SCORE": 90,
    "ESSAY_SCORE": 90,
    "THANK_YOU_TEXT": "Thank you for the support!",
    "REPORTED_GPA": 3.50,
}


def create_fund_payload(**overrides) -> dict:
    payload = {
        "fund_name": DEFAULTS["FUND_NAME"],
        "endowment_cents": DEFAULTS["ENDOWMENT_CENTS"],
        "award_term": DEFAULTS["AWARD_TERM"],
    }
    payload.update(overrides)
    return payload


def create_criteria_payload(fund_id, **overrides) -> dict:
    payload = {
        "fund_id": fund_id,
        "min_gpa": DEFAULTS["MIN_GPA"],
        "required_residency_state": DEFAULTS["REQUIRED_RESIDENCY_STATE"],
        "required_field_of_study": DEFAULTS["REQUIRED_FIELD_OF_STUDY"],
        "max_award_cents": DEFAULTS["MAX_AWARD_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
        "self_reported_gpa": DEFAULTS["SELF_REPORTED_GPA"],
        "residency_state": DEFAULTS["RESIDENCY_STATE"],
        "field_of_study": DEFAULTS["FIELD_OF_STUDY"],
        "institution_id": DEFAULTS["INSTITUTION_ID"],
    }
    payload.update(overrides)
    return payload


def create_committee_member_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": DEFAULTS["MEMBER_EMAIL"],
        "expertise_field": DEFAULTS["EXPERTISE_FIELD"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(fund_id, applicant_id, **overrides) -> dict:
    payload = {
        "fund_id": fund_id,
        "applicant_id": applicant_id,
        "requested_amount_cents": DEFAULTS["REQUESTED_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_recommendation_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "recommender_name": DEFAULTS["RECOMMENDER_NAME"],
        "document_uri": DEFAULTS["DOCUMENT_URI"],
    }
    payload.update(overrides)
    return payload


def create_transcript_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "document_uri": DEFAULTS["DOCUMENT_URI"],
        "verified_gpa": DEFAULTS["VERIFIED_GPA"],
    }
    payload.update(overrides)
    return payload


def create_committee_assignment_payload(application_id, committee_member_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "committee_member_id": committee_member_id,
    }
    payload.update(overrides)
    return payload


def create_rubric_score_payload(application_id, committee_member_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "committee_member_id": committee_member_id,
        "academic_score": DEFAULTS["ACADEMIC_SCORE"],
        "need_score": DEFAULTS["NEED_SCORE"],
        "essay_score": DEFAULTS["ESSAY_SCORE"],
    }
    payload.update(overrides)
    return payload


def award_payload(expected_fund_version, **overrides) -> dict:
    payload = {"expected_fund_version": expected_fund_version}
    payload.update(overrides)
    return payload


def disburse_payload(institution_id=DEFAULTS["INSTITUTION_ID"], **overrides) -> dict:
    payload = {"institution_id": institution_id}
    payload.update(overrides)
    return payload


def create_renewal_review_payload(award_id, **overrides) -> dict:
    payload = {
        "award_id": award_id,
        "reported_gpa": DEFAULTS["REPORTED_GPA"],
    }
    payload.update(overrides)
    return payload


def create_stewardship_record_payload(award_id, **overrides) -> dict:
    payload = {
        "award_id": award_id,
        "thank_you_text": DEFAULTS["THANK_YOU_TEXT"],
    }
    payload.update(overrides)
    return payload
