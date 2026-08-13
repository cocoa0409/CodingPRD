"""Payload factories — one per creatable resource, input fields only (PRD §3)."""


def create_practice_group_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Medical Group",
        "tax_id": "12-3456789",
        "group_npi": "1234567893",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": "1000000001",
        "full_name": "Dr. Jane Doe",
        "specialty": "Internal Medicine",
    }
    defaults.update(overrides)
    return defaults


def create_payer_payload(**overrides) -> dict:
    defaults = {
        "payer_code": "PAYER-A",
        "name": "Payer A",
        "is_medicare": False,
        "effective_date_policy": "APPROVAL_DATE",
        "claims_hold_enabled": True,
        "revalidation_interval_days": 200,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_application_payload(provider_id: str, payer_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "payer_id": payer_id,
        "enrollment_scope": "INDIVIDUAL",
        "requested_effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_delegation_agreement_payload(practice_group_id: str, payer_id: str, **overrides) -> dict:
    defaults = {
        "practice_group_id": practice_group_id,
        "payer_id": payer_id,
        "effective_date": "2026-01-01",
        "expiry_date": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def roster_add_line(provider_id: str, expected_effective_date: str = "2026-08-01",
                    enrollment_scope: str = "GROUP_LINK",
                    benefit_assignment: str = "GROUP") -> dict:
    """An ADD roster line (PRD §3.4: ADD lines carry scope and benefit)."""
    return {
        "provider_id": provider_id,
        "action": "ADD",
        "enrollment_scope": enrollment_scope,
        "benefit_assignment": benefit_assignment,
        "expected_effective_date": expected_effective_date,
    }


def roster_term_line(provider_id: str, expected_effective_date: str = "2026-08-01") -> dict:
    """A TERM roster line. PRD §3.4: enrollment_scope and benefit_assignment
    are ADD-only and meaningless on a removal, so they are omitted."""
    return {
        "provider_id": provider_id,
        "action": "TERM",
        "expected_effective_date": expected_effective_date,
    }


def create_roster_file_payload(agreement_id: str, expected_agreement_version: int,
                               lines: list) -> dict:
    return {
        "agreement_id": agreement_id,
        "expected_agreement_version": expected_agreement_version,
        "lines": lines,
    }


def create_claim_payload(provider_id: str, payer_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "payer_id": payer_id,
        "service_date": "2026-08-01",
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
