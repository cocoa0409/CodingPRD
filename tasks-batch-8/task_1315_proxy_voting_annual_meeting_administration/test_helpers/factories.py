"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS, RECORD_DATE, MEETING_DATETIME


def create_meeting_payload(**overrides) -> dict:
    defaults = {
        "company_name": TEST_DEFAULTS["COMPANY_NAME"],
        "ticker": TEST_DEFAULTS["TICKER"],
        "meeting_type": TEST_DEFAULTS["MEETING_TYPE"],
        "record_date": RECORD_DATE,
        "meeting_datetime": MEETING_DATETIME,
        "meeting_mode": TEST_DEFAULTS["MEETING_MODE"],
        "quorum_threshold_pct": TEST_DEFAULTS["QUORUM_THRESHOLD_PCT"],
        "outstanding_shares": TEST_DEFAULTS["OUTSTANDING_SHARES"],
    }
    defaults.update(overrides)
    return defaults


def create_shareholder_account_payload(meeting_id, account_number="A-1001", **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "holder_name": "Holder One",
        "account_number": account_number,
        "share_class": "COMMON",
        "shares_held": TEST_DEFAULTS["SHARES_HELD"],
    }
    defaults.update(overrides)
    return defaults


def create_broker_search_payload(meeting_id, broker_code="BRK-1", **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "broker_code": broker_code,
        "broker_name": "First Broker",
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(meeting_id, proposal_number=1, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "proposal_number": proposal_number,
        "title": "Say on pay",
        "proposal_type": "SAY_ON_PAY",
        "vote_standard": "MAJORITY_OF_VOTES_CAST",
    }
    defaults.update(overrides)
    return defaults


def create_vote_instruction_payload(meeting_id, proposal_id, account_id, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "proposal_id": proposal_id,
        "account_id": account_id,
        "channel": "INTERNET",
        "choice": "FOR",
    }
    defaults.update(overrides)
    return defaults


def create_platform_session_payload(meeting_id, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "session_type": "LIVE",
        "start_at": "2026-09-15T14:00:00Z",
        "end_at": "2026-09-15T15:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_question_submission_payload(meeting_id, account_id, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "account_id": account_id,
        "question_text": "What is the comp plan?",
    }
    defaults.update(overrides)
    return defaults


def create_vote_challenge_payload(meeting_id, vote_instruction_id, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "vote_instruction_id": vote_instruction_id,
        "reason": "Beneficial ownership dispute",
    }
    defaults.update(overrides)
    return defaults


def create_solicitation_campaign_payload(meeting_id, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "soliciting_party": "dissident",
        "start_at": "2026-09-01T09:00:00Z",
        "end_at": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults
