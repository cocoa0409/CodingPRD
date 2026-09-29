"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def bond_issue_payload(**overrides) -> dict:
    payload = {
        "issuer_program_code": TEST_DEFAULTS["ISSUER_PROGRAM_CODE"],
        "series_designation": TEST_DEFAULTS["SERIES_DESIGNATION"],
        "security_type": "REVENUE",
        "dated_date": "2026-04-01",
        "final_maturity_date": "2056-04-01",
        "original_par_amount_cents": TEST_DEFAULTS["ORIGINAL_PAR_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def undertaking_payload(issue_id, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "fiscal_year_end_month_day": TEST_DEFAULTS["FISCAL_YEAR_END_MONTH_DAY"],
    }
    payload.update(overrides)
    return payload


def content_requirement_payload(undertaking_id, **overrides) -> dict:
    payload = {
        "undertaking_id": undertaking_id,
        "kind": "AUDITED_FINANCIALS",
        "label": "Audited Financial Statements",
        "weight_bp": 10000,
    }
    payload.update(overrides)
    return payload


def annual_report_cycle_payload(undertaking_id, **overrides) -> dict:
    payload = {
        "undertaking_id": undertaking_id,
        "fiscal_year_label": "FY2026",
        "period_start_date": "2025-07-01",
        "period_end_date": "2026-06-30",
    }
    payload.update(overrides)
    return payload


def content_item_progress_payload(**overrides) -> dict:
    payload = {
        "source_document_ref": "DOC-CAFR-2026",
        "data_as_of_date": "2026-06-30",
    }
    payload.update(overrides)
    return payload


def material_event_notice_payload(issue_id, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "event_type": "TRUSTEE_SUBSTITUTION",
        "occurrence_date": "2026-07-20",
    }
    payload.update(overrides)
    return payload


def rating_action_payload(expected_issue_version, **overrides) -> dict:
    payload = {
        "rating_agency": "MOODYS",
        "prior_rating": "Aa2",
        "new_rating": "Aa3",
        "occurrence_date": "2026-07-20",
        "expected_issue_version": expected_issue_version,
    }
    payload.update(overrides)
    return payload


def defease_payload(**overrides) -> dict:
    payload = {
        "defeasance_type": "ECONOMIC",
        "escrow_deposit_cents": 1,
        "occurrence_date": "2026-07-20",
    }
    payload.update(overrides)
    return payload


def filing_payload(issue_id, filing_type, expected_issue_version, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "filing_type": filing_type,
        "expected_issue_version": expected_issue_version,
    }
    payload.update(overrides)
    return payload


def direct_placement_payload(issue_id, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "lender_name": "First Municipal Bank",
        "principal_amount_cents": 5000000,
        "execution_date": "2026-07-20",
        "review_window_start_date": "2026-07-20",
        "review_window_end_date": "2026-07-31",
        "disclosure_practice": "VOLUNTARY",
    }
    payload.update(overrides)
    return payload


def official_statement_payload(issue_id, **overrides) -> dict:
    payload = {
        "issue_id": issue_id,
        "dated_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def engagement_payload(undertaking_id, expected_undertaking_version, **overrides) -> dict:
    payload = {
        "undertaking_id": undertaking_id,
        "agent_name": "Municipal Disclosure Partners",
        "effective_date": "2026-07-01",
        "expiration_date": "2027-06-30",
        "retainer_cents": TEST_DEFAULTS["RETAINER_CENTS"],
        "expected_undertaking_version": expected_undertaking_version,
    }
    payload.update(overrides)
    return payload
