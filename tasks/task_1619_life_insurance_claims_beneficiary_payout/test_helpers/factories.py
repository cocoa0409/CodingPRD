"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import uuid

from .constants import IL_STATUTE


def _unique_policy_number() -> str:
    return f"P-{uuid.uuid4().hex[:12].upper()}"


def create_statute_payload(**overrides) -> dict:
    defaults = dict(IL_STATUTE)
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_number": _unique_policy_number(),
        "insured_name": "Amy Doe",
        "insured_dob": "1970-07-07",
        "state_code": "IL",
        "face_amount_cents": 5000000,
        "issue_date": "2024-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_designation_payload(**overrides) -> dict:
    defaults = {
        "beneficiary_name": "Alice Doe",
        "beneficiary_type": "PRIMARY",
        "share_percent": 100,
        "effective_date": "2024-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "policy_id": None,
        "date_of_death": "2026-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {"doc_type": "CERTIFIED_DEATH_CERTIFICATE"}
    defaults.update(overrides)
    return defaults


def create_beneficiary_claim_payload(**overrides) -> dict:
    defaults = {
        "claimant_name": "Alice Doe",
        "claimant_type": "NAMED_BENEFICIARY",
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(**overrides) -> dict:
    defaults = {
        "option": "LUMP_SUM",
        "expected_claim_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_dmf_match_payload(**overrides) -> dict:
    defaults = {
        "deceased_name": "Jane Doe",
        "deceased_dob": "1960-01-01",
        "deceased_death_date": "2026-05-20",
    }
    defaults.update(overrides)
    return defaults
