"""Payload factories — one per creatable entity, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_court_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"CT-{n}",
        "name": f"Test Court {n}",
        "jurisdiction_type": "FEDERAL",
        "appeal_deadline_days": 30,
        "reply_brief_window_days": 14,
        "uses_word_count": True,
        "max_words_opening": 14000,
        "max_pages_opening": 0,
        "max_words_reply": 7000,
        "max_pages_reply": 0,
        "efiling_required": False,
        "weekend_holiday_rollforward": False,
    }
    defaults.update(overrides)
    return defaults


def create_attorney_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "bar_number": f"BAR-{n:05d}",
        "full_name": f"Test Attorney {n}",
        "email": f"attorney{n}@example.com",
        "admitted_court_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(court_id: str, lead_attorney_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "court_id": court_id,
        "docket_number": f"26-{n:04d}",
        "caption": f"Test Caption {n} v. Appellee",
        "lead_attorney_id": lead_attorney_id,
        "appellant_side": "APPELLANT",
        "judgment_entered_at": TEST_DEFAULTS["JUDGMENT_ENTERED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(event_type: str, occurred_at: str, **overrides) -> dict:
    defaults = {
        "event_type": event_type,
        "occurred_at": occurred_at,
        "notes": "",
    }
    defaults.update(overrides)
    return defaults


def create_transcript_order_payload(**overrides) -> dict:
    defaults = {
        "hearing_date": TEST_DEFAULTS["HEARING_DATE"],
        "court_reporter": "Reliable Reporting LLC",
        "estimated_pages": TEST_DEFAULTS["ESTIMATED_PAGES"],
    }
    defaults.update(overrides)
    return defaults


def deliver_transcript_payload(**overrides) -> dict:
    defaults = {"actual_pages": TEST_DEFAULTS["ESTIMATED_PAGES"]}
    defaults.update(overrides)
    return defaults


def create_brief_payload(schedule_id: str, author_attorney_id: str, **overrides) -> dict:
    defaults = {
        "schedule_id": schedule_id,
        "brief_type": "OPENING",
        "author_attorney_id": author_attorney_id,
        "page_count": TEST_DEFAULTS["BRIEF_PAGE_COUNT"],
        "word_count": TEST_DEFAULTS["BRIEF_WORD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "raw_text": f"Test Authority v. Case {n}, 1 U.S. {100 + n}",
        "authority_type": "CASE",
    }
    defaults.update(overrides)
    return defaults


def create_extension_motion_payload(schedule_id: str, **overrides) -> dict:
    defaults = {
        "schedule_id": schedule_id,
        "target": "OPENING",
        "requested_days": 7,
        "reason": "good cause shown",
    }
    defaults.update(overrides)
    return defaults


def grant_motion_payload(granted_days: int, expected_schedule_version: int) -> dict:
    return {
        "granted_days": granted_days,
        "expected_schedule_version": expected_schedule_version,
    }


def create_filing_payload(filing_type: str, **overrides) -> dict:
    defaults = {
        "filing_type": filing_type,
        "method": "EFILE",
        "served_party_emails": list(TEST_DEFAULTS["SERVED_EMAILS"]),
    }
    defaults.update(overrides)
    return defaults


def create_oral_argument_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-09-01T14:00:00Z",
        "duration_minutes": 30,
        "panel_judges": ["Judge One", "Judge Two", "Judge Three"],
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {
        "outcome": "AFFIRMED",
        "issued_at": "2026-08-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_petition_payload(basis_decision_id: str, **overrides) -> dict:
    defaults = {
        "petition_type": "REHEARING",
        "basis_decision_id": basis_decision_id,
    }
    defaults.update(overrides)
    return defaults
