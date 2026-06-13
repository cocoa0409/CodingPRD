"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional input fields are omitted from defaults
unless a test overrides them.
"""
from .constants import DEFAULT_FILING_FEE_CENTS, DEFAULT_APPEAL_WINDOW_DAYS


def create_court_payload(**overrides) -> dict:
    defaults = {
        "name": "Superior Court of CA, County of Test",
        "jurisdiction_code": "CA",
        "filing_fee_cents": DEFAULT_FILING_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(court_id, **overrides) -> dict:
    defaults = {
        "court_id": court_id,
        "caption": "Acme v Beta",
        "case_type": "CONTRACT",
    }
    defaults.update(overrides)
    return defaults


def create_party_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "display_name": "Test Party",
        "role": "PLAINTIFF",
        "attorney_user_id": "att_1",
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(case_id, filed_by_party_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "filed_by_party_id": filed_by_party_id,
        "document_type": "COMPLAINT",
        "title": "Test Filing",
    }
    defaults.update(overrides)
    return defaults


def create_service_of_process_payload(case_id, filing_id, served_party_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "filing_id": filing_id,
        "served_party_id": served_party_id,
        "method": "PERSONAL",
        "service_date": "2026-03-02T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_deadline_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "deadline_type": "DISCOVERY",
        "anchor_event": "MANUAL",
        "anchor_date": "2026-03-04T00:00:00.000Z",
        "interval_days": 10,
        "counting_mode": "CALENDAR",
    }
    defaults.update(overrides)
    return defaults


def create_motion_payload(case_id, filing_id, moving_party_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "filing_id": filing_id,
        "moving_party_id": moving_party_id,
        "motion_type": "DISMISS",
    }
    defaults.update(overrides)
    return defaults


def rule_motion_payload(ruling="GRANT", order_text="Order text", **overrides) -> dict:
    defaults = {"ruling": ruling, "order_text": order_text}
    defaults.update(overrides)
    return defaults


def create_fee_waiver_payload(case_id, filing_id, requesting_party_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "filing_id": filing_id,
        "requesting_party_id": requesting_party_id,
        "monthly_income_cents": 150000,
        "household_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(case_id, courtroom="A", judge_user_id="jdg_1",
                           start_at="2026-03-05T10:00:00.000Z",
                           end_at="2026-03-05T11:00:00.000Z", **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "courtroom": courtroom,
        "judge_user_id": judge_user_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_judgment_payload(case_id, expected_case_version, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "judgment_type": "TRIAL",
        "principal_cents": 0,
        "interest_rate_bps": 0,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(case_id, judgment_id, appellant_party_id, filed_on,
                          expected_case_version, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "judgment_id": judgment_id,
        "appellant_party_id": appellant_party_id,
        "filed_on": filed_on,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults
