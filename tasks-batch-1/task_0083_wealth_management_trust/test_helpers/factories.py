"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
- Grantor: full_name required; generation_level, gst_exemption_total_cents optional.
- Trustee: full_name required; is_corporate optional.
- Beneficiary: full_name, grantor_id, generation_level required.
- Trust: name, grantor_id, trust_type required; is_grantor_trust, capital_gains_to_income optional.
- TrusteeAppointment: trustee_id, term_start, term_end required.
- TrustAccount: tax_year, period_start, period_end required.
- Receipt: amount_cents, receipt_kind required.
- Disbursement: amount_cents, expense_kind required.
- Distribution: beneficiary_id, amount_cents, distribution_kind, proposer_trustee_id required.
- TaxFiling: supersedes_filing_id optional.
- GstExemptionAllocation: grantor_id, amount_cents, expected_trust_version required.
"""
from .constants import TERM_START, TERM_END, PERIOD_START, PERIOD_END


def create_grantor_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Grantor", "generation_level": 0}
    defaults.update(overrides)
    return defaults


def create_trustee_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Trustee"}
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(grantor_id: str, generation_level: int = 1, **overrides) -> dict:
    defaults = {
        "full_name": "Test Beneficiary",
        "grantor_id": grantor_id,
        "generation_level": generation_level,
    }
    defaults.update(overrides)
    return defaults


def create_trust_payload(grantor_id: str, trust_type: str = "IRREVOCABLE", **overrides) -> dict:
    defaults = {
        "name": "Test Trust",
        "grantor_id": grantor_id,
        "trust_type": trust_type,
    }
    defaults.update(overrides)
    return defaults


def create_trustee_appointment_payload(trustee_id: str, **overrides) -> dict:
    defaults = {
        "trustee_id": trustee_id,
        "term_start": TERM_START,
        "term_end": TERM_END,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(tax_year: int = 2025, **overrides) -> dict:
    defaults = {
        "tax_year": tax_year,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def create_receipt_payload(amount_cents: int, receipt_kind: str, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "receipt_kind": receipt_kind}
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(amount_cents: int, expense_kind: str, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "expense_kind": expense_kind}
    defaults.update(overrides)
    return defaults


def create_distribution_payload(beneficiary_id: str, amount_cents: int,
                                 proposer_trustee_id: str,
                                 distribution_kind: str = "MANDATORY", **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "amount_cents": amount_cents,
        "distribution_kind": distribution_kind,
        "proposer_trustee_id": proposer_trustee_id,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(**overrides) -> dict:
    """TaxFiling create takes only an optional supersedes_filing_id."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_gst_exemption_allocation_payload(grantor_id: str, amount_cents: int,
                                             expected_trust_version: int, **overrides) -> dict:
    defaults = {
        "grantor_id": grantor_id,
        "amount_cents": amount_cents,
        "expected_trust_version": expected_trust_version,
    }
    defaults.update(overrides)
    return defaults
