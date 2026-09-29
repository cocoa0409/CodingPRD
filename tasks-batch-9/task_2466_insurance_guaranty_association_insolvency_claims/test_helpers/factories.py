"""Payload factories — one per entity, request-body fields only."""

from .constants import PERSONAL_AUTO_CAPS


def coverage_profile_payload(**overrides) -> dict:
    """Statutory coverage configuration for the personal auto line."""
    payload = {
        "line_of_business": "PERSONAL_AUTO",
        "per_claim_cap_cents": PERSONAL_AUTO_CAPS["per_claim_cap_cents"],
        "per_policy_aggregate_cap_cents": PERSONAL_AUTO_CAPS["per_policy_aggregate_cap_cents"],
        "unearned_premium_cap_cents": PERSONAL_AUTO_CAPS["unearned_premium_cap_cents"],
        "refund_priority_class": PERSONAL_AUTO_CAPS["refund_priority_class"],
        "statutory_deductible_cents": PERSONAL_AUTO_CAPS["statutory_deductible_cents"],
    }
    payload.update(overrides)
    return payload


def insolvency_payload(**overrides) -> dict:
    payload = {
        "insurer_name": "Great Lakes Mutual Casualty",
        "naic_code": "10001",
        "domiciliary_state_code": "MI",
        "liquidation_order_date": "2026-03-01",
    }
    payload.update(overrides)
    return payload


def member_insurer_payload(**overrides) -> dict:
    payload = {
        "naic_code": "20001",
        "insurer_name": "Wolverine Mutual Insurance",
        "assessable_line": "PERSONAL_AUTO",
        "base_year": 2025,
        "direct_written_premium_cents": 100_000_000,
    }
    payload.update(overrides)
    return payload


def policy_payload(insolvency_id: str, **overrides) -> dict:
    payload = {
        "insolvency_id": insolvency_id,
        "policy_number": "PA-1001",
        "line_of_business": "PERSONAL_AUTO",
        "policyholder_name": "Marta Delgado",
        "policyholder_state_code": "MI",
        "effective_date": "2025-10-01",
        "expiration_date": "2026-10-01",
        "annual_premium_cents": 1_200_000,
    }
    payload.update(overrides)
    return payload


def claim_payload(insolvency_id: str, policy_id: str, **overrides) -> dict:
    payload = {
        "insolvency_id": insolvency_id,
        "policy_id": policy_id,
        "claim_number": "CL-5001",
        "claimant_name": "Nadia Okoro",
        "claimant_state_code": "MI",
        "loss_date": "2026-01-15",
        "gross_loss_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def screen_payload(decision: str = "COVERED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def other_insurance_payload(expected_claim_version: int, **overrides) -> dict:
    payload = {
        "carrier_name": "Northbridge Indemnity",
        "policy_number": "NB-7788",
        "coverage_type": "PRIMARY",
        "stated_limit_cents": 2_000_000,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def vendor_assignment_payload(**overrides) -> dict:
    payload = {
        "vendor_type": "ADJUSTER",
        "vendor_name": "Great Lakes Claims Services",
        "settlement_authority_cents": 3_000_000,
        "hourly_rate_cents": 18_000,
        "engagement_start": "2026-08-01",
        "engagement_end": "2026-08-31",
    }
    payload.update(overrides)
    return payload


def vendor_invoice_payload(hours: float = 10, invoice_ref: str = "INV-1", **overrides) -> dict:
    payload = {"hours": hours, "invoice_ref": invoice_ref}
    payload.update(overrides)
    return payload


def premium_refund_payload(refund_method: str, expected_policy_version: int, **overrides) -> dict:
    payload = {
        "refund_method": refund_method,
        "expected_policy_version": expected_policy_version,
    }
    payload.update(overrides)
    return payload


def poc_transfer_payload(receiver_batch_ref: str, records: list, **overrides) -> dict:
    payload = {"receiver_batch_ref": receiver_batch_ref, "records": records}
    payload.update(overrides)
    return payload


def poc_policy_record(**overrides) -> dict:
    record = {
        "record_type": "POLICY",
        "policy_number": "PA-2001",
        "line_of_business": "PERSONAL_AUTO",
        "policyholder_name": "Ivan Petrov",
        "policyholder_state_code": "MI",
        "policyholder_net_worth_cents": 0,
        "effective_date": "2025-10-01",
        "expiration_date": "2026-10-01",
        "annual_premium_cents": 1_200_000,
    }
    record.update(overrides)
    return record


def poc_claim_record(**overrides) -> dict:
    record = {
        "record_type": "CLAIM",
        "policy_number": "PA-2001",
        "claimant_name": "Ada Nwosu",
        "claimant_state_code": "MI",
        "loss_date": "2026-01-15",
        "gross_loss_cents": 1_000_000,
    }
    record.update(overrides)
    return record


def assessment_payload(insolvency_id: str, **overrides) -> dict:
    payload = {
        "insolvency_id": insolvency_id,
        "assessable_line": "PERSONAL_AUTO",
        "base_year": 2025,
        "needed_amount_cents": 1_400_000,
    }
    payload.update(overrides)
    return payload


def estate_remittance_payload(amount_cents: int, remittance_ref: str = "RM-1", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "remittance_ref": remittance_ref}
    payload.update(overrides)
    return payload


def distribution_payload(distribution_amount_cents: int, expected_insolvency_version: int, **overrides) -> dict:
    payload = {
        "distribution_amount_cents": distribution_amount_cents,
        "expected_insolvency_version": expected_insolvency_version,
    }
    payload.update(overrides)
    return payload


def referral_payload(target_state_code: str, basis: str, **overrides) -> dict:
    payload = {"target_state_code": target_state_code, "basis": basis}
    payload.update(overrides)
    return payload


def referral_response_payload(disposition: str, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def member_payment_payload(amount_cents: int, payment_ref: str = "PAY-1", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "payment_ref": payment_ref}
    payload.update(overrides)
    return payload


def surcharge_filing_payload(
    surcharge_rate_bps: int,
    surcharge_base_cents: int,
    filing_ref: str = "SF-1",
    **overrides,
) -> dict:
    payload = {
        "surcharge_rate_bps": surcharge_rate_bps,
        "surcharge_base_cents": surcharge_base_cents,
        "filing_ref": filing_ref,
    }
    payload.update(overrides)
    return payload


def recoupment_remittance_payload(proceeds_cents: int, remittance_ref: str = "RR-1", **overrides) -> dict:
    payload = {"proceeds_cents": proceeds_cents, "remittance_ref": remittance_ref}
    payload.update(overrides)
    return payload
