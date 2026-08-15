"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TIER_THRESHOLDS, TIMES, TEST_DEFAULTS


def create_playbook_payload(**overrides) -> dict:
    defaults = {"name": "Test Playbook"}
    defaults.update(overrides)
    return defaults


def create_clause_payload(**overrides) -> dict:
    defaults = {
        "clause_key": "STANDARD_CLAUSE",
        "category": "OPERATIONAL",
        "standard_text": "Standard clause text",
        "fallback_positions": [],
        "approver_role_required": "LEGAL_COUNSEL",
        "deviation_severity_cap": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_contract_type_payload(business_owner_id, legal_counsel_id, **overrides) -> dict:
    defaults = {
        "code": "NDA",
        "display_name": "Non-Disclosure Agreement",
        "low_value_threshold_cents": TIER_THRESHOLDS["LOW_MAX_CENTS"],
        "mid_value_threshold_cents": TIER_THRESHOLDS["MID_MAX_CENTS"],
        "high_value_threshold_cents": TIER_THRESHOLDS["HIGH_MAX_CENTS"],
        "auto_approve_below_cents": TIER_THRESHOLDS["AUTO_APPROVE_BELOW_CENTS"],
        "requires_chief_counsel_above_cents": TIER_THRESHOLDS["REQUIRES_CHIEF_COUNSEL_ABOVE_CENTS"],
        "default_business_owner_id": business_owner_id,
        "default_legal_counsel_id": legal_counsel_id,
    }
    defaults.update(overrides)
    return defaults


def create_counterparty_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme Corporation",
        "jurisdiction": "US-DE",
    }
    defaults.update(overrides)
    return defaults


def create_user_payload(email, display_name, primary_role, **overrides) -> dict:
    payload = {
        "email": email,
        "display_name": display_name,
        "primary_role": primary_role,
    }
    payload.update(overrides)
    return payload


def create_intake_request_payload(submitted_by_user_id, contract_type_id, counterparty_id,
                                  contract_value_cents=TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
                                  effective_date=TIMES["EFFECTIVE_DATE"], **overrides) -> dict:
    payload = {
        "submitted_by_user_id": submitted_by_user_id,
        "contract_type_id": contract_type_id,
        "counterparty_id": counterparty_id,
        "contract_value_cents": contract_value_cents,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def create_open_negotiation_payload(playbook_id, drafter_user_id, expected_intake_request_version,
                                    **overrides) -> dict:
    payload = {
        "playbook_id": playbook_id,
        "drafter_user_id": drafter_user_id,
        "expected_intake_request_version": expected_intake_request_version,
    }
    payload.update(overrides)
    return payload


def create_round_payload(**overrides) -> dict:
    defaults = {"change_summary": "Round opened"}
    defaults.update(overrides)
    return defaults


def create_deviation_payload(clause_template_id, proposed_text="Counterparty proposed text",
                             fallback_index=-1, **overrides) -> dict:
    payload = {
        "clause_template_id": clause_template_id,
        "proposed_text": proposed_text,
        "fallback_index": fallback_index,
    }
    payload.update(overrides)
    return payload


def create_decision_payload(decision, expected_negotiation_version, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_negotiation_version": expected_negotiation_version,
    }
    payload.update(overrides)
    return payload


def create_signature_packet_payload(signatories, expected_negotiation_version,
                                    opens_at=TIMES["WINDOW_OPENS"],
                                    closes_at=TIMES["WINDOW_CLOSES"], **overrides) -> dict:
    payload = {
        "signatories": signatories,
        "signature_window_opens_at": opens_at,
        "signature_window_closes_at": closes_at,
        "expected_negotiation_version": expected_negotiation_version,
    }
    payload.update(overrides)
    return payload


def signatory_entry(user_id, order_index, authority_cap_cents=TEST_DEFAULTS["SIGNATORY_AUTHORITY_CENTS"]) -> dict:
    return {
        "user_id": user_id,
        "order_index": order_index,
        "authority_cap_cents": authority_cap_cents,
    }
