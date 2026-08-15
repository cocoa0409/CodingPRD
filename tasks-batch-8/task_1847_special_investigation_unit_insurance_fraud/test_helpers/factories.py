"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _uniq(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_adjuster_payload(**overrides) -> dict:
    n = _uniq("adj")
    defaults = {
        "full_name": f"Adjuster {n}",
        "email": f"{n}@example.com",
        "state_licenses": ["CA"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(adjuster_id: str, **overrides) -> dict:
    defaults = {
        "policy_number": _uniq("POL"),
        "state_code": "CA",
        "adjuster_id": adjuster_id,
        "claimed_amount_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(claim_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "submitted_by_role": "ADJUSTER",
        "red_flag_codes": ["UNWITNESSED_LOSS"],
        "narrative": "Suspicious indicators observed",
    }
    defaults.update(overrides)
    return defaults


def create_investigator_payload(**overrides) -> dict:
    n = _uniq("inv")
    defaults = {
        "full_name": f"Investigator {n}",
        "email": f"{n}@example.com",
        "badge_number": _uniq("B").upper(),
        "state_certifications": ["CA"],
        "max_active_cases": 5,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(investigator_id: str, expected_case_version: int, **overrides) -> dict:
    defaults = {
        "investigator_id": investigator_id,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "RECORDS",
        "collected_at": "2026-08-10T00:00:00Z",
        "custodian": "Custodian One",
        "materiality": "SUPPORTING",
        "fraud_amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_euo_session_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start_at": "2026-08-20T10:00:00Z",
        "scheduled_end_at": "2026-08-20T12:00:00Z",
        "location": "Office",
        "insured_attendee_name": "Insured Person",
    }
    defaults.update(overrides)
    return defaults


def create_provider_pattern_payload(**overrides) -> dict:
    n = _uniq("npi")
    defaults = {
        "provider_npi": n.upper(),
        "provider_name": f"Provider {n}",
        "ring_signature": _uniq("SIG").upper(),
    }
    defaults.update(overrides)
    return defaults


def create_ledger_payload(**overrides) -> dict:
    defaults = {
        "target_amount_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100_000,
        "received_at": "2026-08-12T00:00:00Z",
        "method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "course_code": "SIU-ANNUAL-2026",
        "completed_at": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "credit_hours": 4,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_start_at": "2026-08-01T00:00:00Z",
        "period_end_at": "2026-08-31T00:00:00Z",
        "state_code": "CA",
        "report_type": "QUARTERLY_SIU_ACTIVITY",
    }
    defaults.update(overrides)
    return defaults
