"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools
import uuid

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def member_payload(**overrides) -> dict:
    """Input fields for POST /recovery/members (PRD §3.1)."""
    n = _seq()
    defaults = {
        "medicaid_id": f"M-{uuid.uuid4().hex[:8].upper()}-{n}",
        "full_name": f"Test Member {n}",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def case_payload(member_id, **overrides) -> dict:
    """Input fields for POST /recovery/cases (PRD §3.2)."""
    n = _seq()
    defaults = {
        "member_id": member_id,
        "attorney_name": f"Attorney {n}",
        "attorney_email": f"attorney{n}@example.com",
        "injury_date": "2026-01-01",
        "third_party_insurer": f"Insurer {n}",
    }
    defaults.update(overrides)
    return defaults


def expense_claim_payload(**overrides) -> dict:
    """Input fields for POST /recovery/cases/{caseId}/expense-claims (PRD §3.2)."""
    n = _seq()
    defaults = {
        "service_date": "2026-01-10",
        "paid_amount_cents": 200000,
        "claim_reference": f"CL-{n}",
    }
    defaults.update(overrides)
    return defaults


def settlement_payload(expected_case_version, **overrides) -> dict:
    """Input fields for POST /recovery/cases/{caseId}/settlements (PRD §3.4)."""
    defaults = {
        "gross_amount_cents": 1000000,
        "attorney_fee_pct": 0.25,
        "litigation_costs_cents": 100000,
        "offered_by": "INSURER",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def counter_payload(**overrides) -> dict:
    """Input fields for POST /recovery/settlements/{settlementId}/counter (PRD §3.4)."""
    defaults = {
        "gross_amount_cents": 600000,
        "attorney_fee_pct": 0.25,
        "litigation_costs_cents": 60000,
        "offered_by": "STATE",
    }
    defaults.update(overrides)
    return defaults


def amend_lien_payload(expected_lien_version, **overrides) -> dict:
    """Input fields for POST /recovery/liens/{lienId}/amend (PRD §3.3)."""
    defaults = {
        "new_amount_cents": 180000,
        "expected_lien_version": expected_lien_version,
    }
    defaults.update(overrides)
    return defaults


def posting_payload(**overrides) -> dict:
    """Input fields for POST /recovery/settlements/{settlementId}/postings (PRD §3.5)."""
    defaults = {
        "gross_recovery_cents": 200000,
        "contractor_code": "CTR-A",
    }
    defaults.update(overrides)
    return defaults


def mark_deceased_payload(**overrides) -> dict:
    """Input fields for POST /recovery/members/{memberId}/mark-deceased (PRD §3.6)."""
    defaults = {
        "date_of_death": "2026-02-01",
        "lifetime_paid_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def file_claim_payload(**overrides) -> dict:
    """Input fields for POST /recovery/estate-cases/{estateCaseId}/file-claim (PRD §3.6)."""
    n = _seq()
    defaults = {
        "probate_case_number": f"P-{n}",
        "exempt_services_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(**overrides) -> dict:
    """Input fields for POST /recovery/estate-cases/{estateCaseId}/record-payment (PRD §3.6)."""
    defaults = {"amount_cents": 100000}
    defaults.update(overrides)
    return defaults


def waiver_payload(**overrides) -> dict:
    """Input fields for POST /recovery/estate-cases/{estateCaseId}/waivers (PRD §3.7).

    `requested_reduction_cents` is included only for PARTIAL waivers (required
    exactly when the waiver_type is PARTIAL, ignored for FULL per PRD §3.7).
    """
    defaults = {
        "waiver_type": "FULL",
        "household_income_annual_cents": 1000000,
        "homestead_value_cents": 1000000,
    }
    defaults.update(overrides)
    if defaults.get("waiver_type") == "PARTIAL":
        defaults.setdefault("requested_reduction_cents", 100000)
    else:
        defaults.pop("requested_reduction_cents", None)
    return defaults
