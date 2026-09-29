"""Payload factories -- one per resource family, client-supplied input fields only."""

from .constants import LONG_TERM_END, LONG_TERM_START


def board_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Reyes",
        "seat_number": 1,
        "term_start_date": LONG_TERM_START,
        "term_end_date": LONG_TERM_END,
        "employer_name": "Reyes Dental",
    }
    payload.update(overrides)
    return payload


def committee_payload(**overrides) -> dict:
    payload = {
        "name": "Policy Committee",
        "charter_type": "POLICY",
        "seat_capacity": 3,
        "quorum_size": 2,
    }
    payload.update(overrides)
    return payload


def committee_assignment_payload(committee_id: str, board_member_id: str, **overrides) -> dict:
    payload = {"committee_id": committee_id, "board_member_id": board_member_id}
    payload.update(overrides)
    return payload


def conflict_disclosure_payload(board_member_id: str, policy_id: str, **overrides) -> dict:
    payload = {
        "board_member_id": board_member_id,
        "policy_id": policy_id,
        "nature": "FINANCIAL",
        "narrative": "Spouse holds equity in the benefits vendor named in this policy.",
    }
    payload.update(overrides)
    return payload


def policy_payload(**overrides) -> dict:
    payload = {
        "code": "BP-4119",
        "title": "Employee Conflict of Interest",
        "category": "PERSONNEL",
        "legal_requirement_level": "REQUIRED_BY_LAW",
        "manual_section": "4000.19",
    }
    payload.update(overrides)
    return payload


def policy_version_payload(expected_policy_version: int, **overrides) -> dict:
    payload = {
        "body_text": "Version one text.",
        "summary_of_change": "Initial adoption draft",
        "expected_policy_version": expected_policy_version,
    }
    payload.update(overrides)
    return payload


def legal_mandate_payload(policy_id: str, **overrides) -> dict:
    payload = {
        "notice_code": "LUS-2026-014",
        "policy_id": policy_id,
        "citation": "EC 35291",
        "issued_on": "2026-08-01T00:00:00Z",
        "compliance_deadline": "2026-12-01T00:00:00Z",
        "required_action": "REVISE_EXISTING",
    }
    payload.update(overrides)
    return payload


def meeting_payload(**overrides) -> dict:
    payload = {
        "title": "September Regular Meeting",
        "scope": "FULL_BOARD",
        "meeting_type": "REGULAR",
        "scheduled_start_utc": "2026-09-10T18:00:00Z",
    }
    payload.update(overrides)
    return payload


def agenda_item_payload(meeting_id: str, expected_meeting_version: int, **overrides) -> dict:
    payload = {
        "meeting_id": meeting_id,
        "item_type": "CONSENT",
        "title": "Approve warrants",
        "expected_meeting_version": expected_meeting_version,
    }
    payload.update(overrides)
    return payload


def public_comment_payload(**overrides) -> dict:
    payload = {
        "speaker_name": "Faye Nunez",
        "speaker_affiliation": "PARENT",
        "requested_minutes": 3,
    }
    payload.update(overrides)
    return payload


def waiver_request_payload(policy_id: str, reviewing_committee_id: str, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "reviewing_committee_id": reviewing_committee_id,
        "requesting_school_code": "HS-01",
        "justification": "Block schedule pilot",
        "requested_start_date": "2026-10-01T00:00:00Z",
        "requested_end_date": "2026-11-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def superintendent_evaluation_payload(**overrides) -> dict:
    payload = {
        "cycle_year": 2027,
        "window_start_date": "2026-08-01T00:00:00Z",
        "window_end_date": "2027-06-30T00:00:00Z",
        "midyear_checkpoint_date": "2027-01-15T00:00:00Z",
        "goal_count": 4,
        "weight_instructional": 0.40,
        "weight_fiscal": 0.30,
        "weight_community": 0.20,
        "weight_governance": 0.10,
    }
    payload.update(overrides)
    return payload


def evaluation_rating_payload(evaluation_id: str, board_member_id: str, **overrides) -> dict:
    payload = {
        "evaluation_id": evaluation_id,
        "board_member_id": board_member_id,
        "domain": "INSTRUCTIONAL_LEADERSHIP",
        "score": 4,
    }
    payload.update(overrides)
    return payload


def manual_publication_payload(**overrides) -> dict:
    payload = {"publication_label": "2026-FALL", "as_of_date": "2026-08-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def vote_payload(yes_member_ids=None, no_member_ids=None, abstain_member_ids=None) -> dict:
    return {
        "yes_member_ids": list(yes_member_ids or []),
        "no_member_ids": list(no_member_ids or []),
        "abstain_member_ids": list(abstain_member_ids or []),
    }
