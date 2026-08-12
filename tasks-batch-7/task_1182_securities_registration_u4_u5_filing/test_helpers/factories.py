"""Payload factories — one per creatable resource, input fields only.

Counters make every generated identifier unique within a test run so
uniqueness constraints (PRD Section 2.10 step 4) never fire by accident.
"""
import itertools

_ctr = itertools.count(1)


def _n() -> int:
    return next(_ctr)


def make_firm_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "crd_number": str(900000 + (i % 99999)),
        "legal_name": f"Test Firm {i}",
    }
    defaults.update(overrides)
    return defaults


def make_applicant_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "crd_number": str(800000 + (i % 99999)),
        "full_name": f"Test Applicant {i}",
        "date_of_birth": "1985-01-15",
    }
    defaults.update(overrides)
    return defaults


def make_registration_request_payload(applicant_id, firm_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "firm_id": firm_id,
        "registration_category": "RR",
    }
    defaults.update(overrides)
    return defaults


def make_jurisdiction_selection_payload(registration_request_id, **overrides) -> dict:
    defaults = {
        "registration_request_id": registration_request_id,
        "jurisdiction_code": "CA",
        "jurisdiction_type": "STATE",
    }
    defaults.update(overrides)
    return defaults


def make_fingerprint_submission_payload(registration_request_id, **overrides) -> dict:
    defaults = {
        "registration_request_id": registration_request_id,
        "submission_channel": "ELECTRONIC",
    }
    defaults.update(overrides)
    return defaults


def make_background_disclosure_payload(registration_request_id, **overrides) -> dict:
    defaults = {
        "registration_request_id": registration_request_id,
        "question_code": "CRIMINAL",
        "answer": False,
    }
    defaults.update(overrides)
    return defaults


def make_exam_requirement_payload(registration_request_id, **overrides) -> dict:
    defaults = {
        "registration_request_id": registration_request_id,
        "exam_code": "SIE",
    }
    defaults.update(overrides)
    return defaults


def make_exam_window_payload(exam_requirement_id, **overrides) -> dict:
    defaults = {
        "exam_requirement_id": exam_requirement_id,
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def make_disclosure_event_payload(applicant_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "event_type": "BANKRUPTCY",
        "event_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def make_amendment_filing_payload(disclosure_event_id, **overrides) -> dict:
    defaults = {
        "disclosure_event_id": disclosure_event_id,
        "narrative_text": "Amendment narrative with sufficient detail length.",
    }
    defaults.update(overrides)
    return defaults


def make_termination_filing_payload(registration_request_id, **overrides) -> dict:
    defaults = {
        "registration_request_id": registration_request_id,
        "termination_reason": "VOLUNTARY",
        "termination_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def make_u5_comment_payload(termination_filing_id, **overrides) -> dict:
    defaults = {
        "termination_filing_id": termination_filing_id,
        "comment_text": "Commentary on the U5 filing.",
    }
    defaults.update(overrides)
    return defaults


def make_affiliation_request_payload(
    applicant_id, second_firm_id, first_registration_request_id, **overrides
) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "second_firm_id": second_firm_id,
        "first_registration_request_id": first_registration_request_id,
    }
    defaults.update(overrides)
    return defaults


def make_renewal_invoice_payload(registration_request_id, **overrides) -> dict:
    defaults = {
        "registration_request_id": registration_request_id,
        "cycle_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def make_regulatory_inquiry_payload(subject_filing_type, subject_filing_id, **overrides) -> dict:
    defaults = {
        "subject_filing_type": subject_filing_type,
        "subject_filing_id": subject_filing_id,
        "inquiry_text": "Regulator inquiry text of sufficient length.",
    }
    defaults.update(overrides)
    return defaults
