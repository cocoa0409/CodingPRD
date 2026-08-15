"""Payload factories — one per creatable entity, input fields only."""
from typing import List, Optional

from .constants import TEST_DEFAULTS

_party_seq = {"n": 0}
_attorney_seq = {"n": 0}


def create_party_payload(**overrides) -> dict:
    """Party create payload (PRD section 3.1): legal_name + party_type required;
    aliases and affiliate_of_id optional."""
    _party_seq["n"] += 1
    defaults = {
        "legal_name": f"Test Party {_party_seq['n']} Inc",
        "party_type": TEST_DEFAULTS["PARTY_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_attorney_payload(**overrides) -> dict:
    """Attorney create payload (PRD section 3.2): full_name, bar_number,
    practice_group required; hire_type defaults to INTERNAL. LATERAL hires also
    require lateral_employed_from / lateral_employed_to / prior_client_names."""
    _attorney_seq["n"] += 1
    defaults = {
        "full_name": f"Test Attorney {_attorney_seq['n']}",
        "bar_number": f"BAR{_attorney_seq['n']:03d}",
        "practice_group": TEST_DEFAULTS["PRACTICE_GROUP"],
        "hire_type": "INTERNAL",
    }
    defaults.update(overrides)
    return defaults


def create_matter_payload(client_party_id: str, responsible_attorney_id: str,
                          **overrides) -> dict:
    """Matter create payload (PRD section 3.3): client_party_id,
    responsible_attorney_id, practice_group required; matter_title optional."""
    defaults = {
        "client_party_id": client_party_id,
        "responsible_attorney_id": responsible_attorney_id,
        "practice_group": TEST_DEFAULTS["PRACTICE_GROUP"],
        "matter_title": "Test Matter",
    }
    defaults.update(overrides)
    return defaults


def add_matter_party_payload(party_id: str, role_in_matter: str = "ADVERSE",
                             **overrides) -> dict:
    """Roster-add payload (PRD section 3.3)."""
    defaults = {"party_id": party_id, "role_in_matter": role_in_matter}
    defaults.update(overrides)
    return defaults


def create_conflict_check_payload(search_variant: str = "STRICT",
                                  match_threshold: Optional[int] = None,
                                  **overrides) -> dict:
    """Conflict-check payload (PRD section 3.4): search_variant required;
    match_threshold optional (server default 60 when omitted)."""
    defaults = {"search_variant": search_variant}
    if match_threshold is not None:
        defaults["match_threshold"] = match_threshold
    defaults.update(overrides)
    return defaults


def review_hit_payload(decision: str = "CONFIRMED",
                       note: Optional[str] = None, **overrides) -> dict:
    """Hit review payload (PRD section 3.4)."""
    defaults = {"decision": decision}
    if note is not None:
        defaults["note"] = note
    defaults.update(overrides)
    return defaults


def create_ethical_wall_payload(reason: str = "CLIENT_REQUEST",
                                excluded_attorney_ids: Optional[List[str]] = None,
                                memo: Optional[str] = None, **overrides) -> dict:
    """Ethical-wall create payload (PRD section 3.5): reason +
    non-empty excluded_attorney_ids required; memo optional."""
    defaults = {
        "reason": reason,
        "excluded_attorney_ids": list(excluded_attorney_ids or []),
    }
    if memo is not None:
        defaults["memo"] = memo
    defaults.update(overrides)
    return defaults


def transition_wall_payload(action: str,
                            attorney_id: Optional[str] = None,
                            **overrides) -> dict:
    """Wall transition payload (PRD section 3.5): EXCLUDE/RELEASE carry
    attorney_id; LIFT does not."""
    defaults = {"action": action}
    if attorney_id is not None:
        defaults["attorney_id"] = attorney_id
    defaults.update(overrides)
    return defaults


def create_waiver_request_payload(conflict_hit_id: str,
                                  proposed_terms: str = "waiver terms",
                                  **overrides) -> dict:
    """Waiver draft payload (PRD section 3.6)."""
    defaults = {
        "conflict_hit_id": conflict_hit_id,
        "proposed_terms": proposed_terms,
    }
    defaults.update(overrides)
    return defaults


def transition_waiver_payload(action: str, **overrides) -> dict:
    """Waiver transition payload (PRD section 3.6). Extra keys such as
    consent_document_ref / decline_reason / proposed_terms / note pass through."""
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def standard_fee_lines(hours: float = None, rate_cents: int = None,
                       description: str = "fees") -> List[dict]:
    """A single-line fee_lines list. Defaults produce the canonical 2,000,000-cent
    estimate (100.0 hours x 20000 cents) used across the countersign fixtures."""
    return [{
        "description": description,
        "hours": TEST_DEFAULTS["STANDARD_HOURS"] if hours is None else hours,
        "rate_cents": (
            TEST_DEFAULTS["STANDARD_RATE_CENTS"] if rate_cents is None else rate_cents
        ),
    }]


def create_engagement_letter_payload(expected_matter_version,
                                     fee_lines: Optional[List[dict]] = None,
                                     scope_text: str = "Scope",
                                     **overrides) -> dict:
    """Engagement-letter create payload (PRD section 3.7): scope_text,
    fee_lines (>= 1 line, hours > 0, rate_cents > 0), and the OCC token
    expected_matter_version are required."""
    defaults = {
        "scope_text": scope_text,
        "fee_lines": fee_lines if fee_lines is not None else standard_fee_lines(),
        "expected_matter_version": expected_matter_version,
    }
    defaults.update(overrides)
    return defaults


def transition_letter_payload(action: str, **overrides) -> dict:
    """Letter transition payload (PRD section 3.7): ISSUE / COUNTERSIGN / VOID."""
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_credit_assessment_payload(score: int = None, **overrides) -> dict:
    """Credit-assessment payload (PRD section 3.8): score in 300..850."""
    defaults = {
        "score": TEST_DEFAULTS["PRIME_SCORE"] if score is None else score,
    }
    defaults.update(overrides)
    return defaults


def transition_deposit_payload(action: str, amount_cents: int, **overrides) -> dict:
    """Retainer FUND/REFUND payload (PRD section 3.8)."""
    defaults = {"action": action, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    """Clock-set payload (PRD section 2.5)."""
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
