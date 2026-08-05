"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Computed and system
fields (ledger totals, statuses, risk scores, estimated_cost_cents, ...) are minted
by the server and never sent.
"""
import itertools

_npi_counter = itertools.count(1000000001)


def next_npi() -> str:
    return str(next(_npi_counter))


def create_family_payload(**overrides) -> dict:
    defaults = {"family_name": "Test Kindred", "outreach_budget_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_counselor_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Counselor", "npi": next_npi()}
    defaults.update(overrides)
    return defaults


def create_lab_payload(**overrides) -> dict:
    defaults = {"lab_name": "Test Lab", "max_concurrent_capacity": 5, "turnaround_days": 14}
    defaults.update(overrides)
    return defaults


def create_case_payload(family_id, counselor_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "assigned_counselor_id": counselor_id,
        "patient_name": "Test Patient",
        "patient_dob": "1980-01-01",
        "sex": "FEMALE",
        "ancestry": "EUROPEAN",
        "referral_reason": "Family history of cancer",
        "covered_sessions": 3,
    }
    defaults.update(overrides)
    return defaults


def create_pedigree_member_payload(case_id, **overrides) -> dict:
    defaults = {
        "counseling_case_id": case_id,
        "relationship": "SIBLING",
        "degree": 1,
        "affected": True,
        "age_of_onset": 45,
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(case_id, consent_type="TESTING", **overrides) -> dict:
    defaults = {"counseling_case_id": case_id, "consent_type": consent_type}
    defaults.update(overrides)
    return defaults


def create_session_payload(case_id, counselor_id, **overrides) -> dict:
    defaults = {
        "counseling_case_id": case_id,
        "counselor_id": counselor_id,
        "session_type": "PRE_TEST",
        "scheduled_start": "2026-06-01T10:00:00Z",
        "scheduled_end": "2026-06-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(case_id, lab_id, **overrides) -> dict:
    defaults = {
        "counseling_case_id": case_id,
        "lab_id": lab_id,
        "panel_name": "BRCA panel",
        "list_price_cents": 300000,
        "processing_start": "2026-05-02T09:00:00Z",
        "processing_end": "2026-05-16T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_result_payload(order_id, **overrides) -> dict:
    defaults = {
        "test_order_id": order_id,
        "gene": "BRCA1",
        "variant": "c.68del",
        "classification": "PATHOGENIC",
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(family_id, proband_case_id, member_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "proband_case_id": proband_case_id,
        "pedigree_member_id": member_id,
        "relative_name": "Test Relative",
        "relationship": "SIBLING",
        "degree": 1,
        "contact_method": "EMAIL",
        "expires_at": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(case_id, order_id, **overrides) -> dict:
    defaults = {
        "counseling_case_id": case_id,
        "test_order_id": order_id,
        "payer_name": "Test Payer",
        "member_number": "M123",
        "coverage_pct": 0.8,
        "estimated_allowed_rate": 0.7,
        "line_items": [{"cpt": "81162", "billed_cents": 300000}],
    }
    defaults.update(overrides)
    return defaults


def create_surveillance_plan_payload(case_id, expected_version, **overrides) -> dict:
    defaults = {
        "counseling_case_id": case_id,
        "modalities": ["BREAST_MRI"],
        "expected_counseling_case_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(case_id, **overrides) -> dict:
    defaults = {
        "counseling_case_id": case_id,
        "specialty": "BREAST_SURGERY",
        "reason": "Prophylactic consult",
    }
    defaults.update(overrides)
    return defaults
