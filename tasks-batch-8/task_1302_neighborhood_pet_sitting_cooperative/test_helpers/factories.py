"""Payload factories — one per creatable entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_member_payload(**overrides) -> dict:
    """Membership application inputs (PRD §3.1). mediator_flag optional."""
    defaults = {
        "display_name": "Test Applicant",
        "email": "applicant@coop.test",
        "address_block": TEST_DEFAULTS["ADDRESS_BLOCK"],
        "phone": "+15550000",
    }
    defaults.update(overrides)
    return defaults


def create_reference_payload(referee_member_id: str, **overrides) -> dict:
    """Reference inputs (PRD §3.1): referee, years known (>= 1), attestation (>= 20 chars)."""
    defaults = {
        "referee_member_id": referee_member_id,
        "relationship_years": 2,
        "attestation_text": "Known neighbor for two years.",
    }
    defaults.update(overrides)
    return defaults


def create_pet_profile_payload(**overrides) -> dict:
    """Pet profile inputs (PRD §3.2); waiver accepted by default."""
    defaults = {
        "pet_name": "Biscuit",
        "species": "DOG",
        "routine_notes": "Feed twice daily, walk morning.",
        "medical_notes": "No medications.",
        "emergency_vet_name": TEST_DEFAULTS["VET_NAME"],
        "emergency_vet_phone": TEST_DEFAULTS["VET_PHONE"],
        "emergency_vet_address": TEST_DEFAULTS["VET_ADDRESS"],
        "liability_waiver_accepted": True,
    }
    defaults.update(overrides)
    return defaults


def create_holiday_window_payload(**overrides) -> dict:
    """Holiday window inputs (PRD §3.3); enabled optional, multiplier in [1.0, 3.0]."""
    defaults = {
        "name": "Holiday Window",
        "window_start": "2026-12-24T00:00:00Z",
        "window_end": "2026-12-26T00:00:00Z",
        "demand_multiplier": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_sitting_request_payload(pet_profile_id: str, **overrides) -> dict:
    """Sitting request inputs (PRD §3.3): pet, future window, instructions."""
    defaults = {
        "pet_profile_id": pet_profile_id,
        "start_at": TEST_DEFAULTS["SIT_START"],
        "end_at": TEST_DEFAULTS["SIT_END"],
        "instructions": "Canonical 4h sit",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    """Claim inputs (PRD §3.4): a short message pitch."""
    defaults = {"message": "Happy to sit"}
    defaults.update(overrides)
    return defaults


def create_accept_claim_payload(expected_sitting_request_version: int, **overrides) -> dict:
    """Claim-accept inputs (PRD §2.11): the OCC expected version field."""
    defaults = {"expected_sitting_request_version": expected_sitting_request_version}
    defaults.update(overrides)
    return defaults


def create_cancel_payload(**overrides) -> dict:
    defaults = {"cancelled_reason": "Plans changed"}
    defaults.update(overrides)
    return defaults


def create_entry_log_payload(event_type: str, occurred_at: str, **overrides) -> dict:
    """Entry-log inputs (PRD §3.5); notes required for INCIDENT_NOTE / MEDICATION_GIVEN."""
    defaults = {"event_type": event_type, "occurred_at": occurred_at}
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    """Incident inputs (PRD §3.7): severity, description (>= 30 chars), vet_involved."""
    defaults = {
        "severity": "MINOR",
        "description": "Something noteworthy happened during the sit.",
        "vet_involved": False,
    }
    defaults.update(overrides)
    return defaults


def create_resolve_incident_payload(outcome: str, **overrides) -> dict:
    """Incident-resolve inputs (PRD §3.7); at_fault_member_id required for AT_FAULT."""
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(respondent_member_id: str, **overrides) -> dict:
    """Dispute inputs (PRD §3.7): respondent, type, statement (>= 40 chars)."""
    defaults = {
        "respondent_member_id": respondent_member_id,
        "dispute_type": "BEHAVIOR",
        "statement": "A detailed account of the disagreement between members.",
    }
    defaults.update(overrides)
    return defaults


def create_assign_mediator_payload(mediator_member_id: str, **overrides) -> dict:
    defaults = {"mediator_member_id": mediator_member_id}
    defaults.update(overrides)
    return defaults


def create_resolve_dispute_payload(outcome: str, **overrides) -> dict:
    """Dispute-resolve inputs (PRD §3.7); resolution_notes required for UPHELD."""
    defaults = {
        "outcome": outcome,
        "resolution_notes": "Mediator findings and resolution notes.",
    }
    defaults.update(overrides)
    return defaults


def create_escalate_payload(**overrides) -> dict:
    defaults = {"resolution_notes": "Mediation failed; escalating to removal track."}
    defaults.update(overrides)
    return defaults


def create_handoff_update_payload(**overrides) -> dict:
    """Owner-recorded handoff details while PENDING (PRD §3.5)."""
    defaults = {
        "handoff_method": "LOCKBOX",
        "access_code_ciphertext": "ZW5jcnlwdGVkLWNvZGU=",
    }
    defaults.update(overrides)
    return defaults
