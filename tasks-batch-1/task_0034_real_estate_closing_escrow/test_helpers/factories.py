"""Payload factories — one per endpoint with input fields (PRD §3, §4)."""


def create_user_payload(full_name: str = "Test User", role: str = "EscrowOfficer", **overrides) -> dict:
    payload = {"full_name": full_name, "role": role}
    payload.update(overrides)
    return payload


def create_purchase_agreement_payload(
    buyer_name: str = "Test Buyer",
    seller_name: str = "Test Seller",
    property_address: str = "1 Test Lane",
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    scheduled_closing_date: str = "2026-08-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "property_address": property_address,
        "purchase_price_cents": purchase_price_cents,
        "earnest_money_required_cents": earnest_money_required_cents,
        "scheduled_closing_date": scheduled_closing_date,
    }
    payload.update(overrides)
    return payload


def create_earnest_money_deposit_payload(
    escrow_account_id: str,
    amount_cents: int = 1_000_000,
    depositor_role: str = "BUYER",
    **overrides,
) -> dict:
    payload = {
        "escrow_account_id": escrow_account_id,
        "amount_cents": amount_cents,
        "depositor_role": depositor_role,
    }
    payload.update(overrides)
    return payload


def confirm_deposit_payload(confirmation_reference: str = "BANK-REF-001", **overrides) -> dict:
    payload = {"confirmation_reference": confirmation_reference}
    payload.update(overrides)
    return payload


def create_title_search_payload(agreement_id: str, **overrides) -> dict:
    payload = {"agreement_id": agreement_id}
    payload.update(overrides)
    return payload


def complete_title_search_payload(defects: list = None, **overrides) -> dict:
    payload = {"defects": defects if defects is not None else []}
    payload.update(overrides)
    return payload


def resolve_title_search_payload(**overrides) -> dict:
    return dict(overrides)


def create_title_insurance_policy_payload(
    title_search_id: str, expected_title_search_version: int, **overrides
) -> dict:
    payload = {
        "title_search_id": title_search_id,
        "expected_title_search_version": expected_title_search_version,
    }
    payload.update(overrides)
    return payload


def create_ccr_review_payload(
    agreement_id: str,
    hoa_name: str = "Test HOA",
    restrictions_summary: str = "Standard CC&Rs reviewed.",
    buyer_acknowledged: bool = True,
    **overrides,
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "hoa_name": hoa_name,
        "restrictions_summary": restrictions_summary,
        "buyer_acknowledged": buyer_acknowledged,
    }
    payload.update(overrides)
    return payload


def create_closing_disclosure_payload(
    agreement_id: str,
    expected_agreement_version: int,
    cd_apr_bps: int = 600,
    cd_total_loan_amount_cents: int = 40_000_000,
    cd_monthly_payment_cents: int = 250_000,
    cd_product_type: str = "FIXED",
    cd_prepayment_penalty: bool = False,
    **overrides,
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "expected_agreement_version": expected_agreement_version,
        "cd_apr_bps": cd_apr_bps,
        "cd_total_loan_amount_cents": cd_total_loan_amount_cents,
        "cd_monthly_payment_cents": cd_monthly_payment_cents,
        "cd_product_type": cd_product_type,
        "cd_prepayment_penalty": cd_prepayment_penalty,
    }
    payload.update(overrides)
    return payload


def reissue_closing_disclosure_payload(**overrides) -> dict:
    """All fields optional per PRD §3.4 — cd_apr_bps, cd_product_type, cd_prepayment_penalty."""
    return dict(overrides)


def create_wire_instruction_payload(
    agreement_id: str,
    party: str = "BUYER",
    beneficiary_bank_name: str = "Acme Bank",
    beneficiary_account_last4: str = "1234",
    routing_number: str = "021000021",
    **overrides,
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "party": party,
        "beneficiary_bank_name": beneficiary_bank_name,
        "beneficiary_account_last4": beneficiary_account_last4,
        "routing_number": routing_number,
    }
    payload.update(overrides)
    return payload


def callback_verify_wire_payload(
    verifier_id: str,
    voice_callback_reference: str = "VC-001",
    **overrides,
) -> dict:
    payload = {
        "verifier_id": verifier_id,
        "voice_callback_reference": voice_callback_reference,
    }
    payload.update(overrides)
    return payload


def create_disbursement_payload(
    escrow_account_id: str,
    wire_instruction_id: str,
    purpose: str = "SELLER_PROCEEDS",
    amount_cents: int = 10_000_000,
    **overrides,
) -> dict:
    payload = {
        "escrow_account_id": escrow_account_id,
        "wire_instruction_id": wire_instruction_id,
        "purpose": purpose,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_exchange_account_payload(
    taxpayer_name: str = "Test Taxpayer",
    qualified_intermediary_name: str = "Acme QI",
    relinquished_closing_date: str = "2026-06-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "taxpayer_name": taxpayer_name,
        "qualified_intermediary_name": qualified_intermediary_name,
        "relinquished_closing_date": relinquished_closing_date,
    }
    payload.update(overrides)
    return payload


def identify_exchange_account_payload(
    replacement_property_address: str = "999 Replacement Ave", **overrides
) -> dict:
    payload = {"replacement_property_address": replacement_property_address}
    payload.update(overrides)
    return payload


def terminate_purchase_agreement_payload(
    terminated_reason: str = "Test termination.", **overrides
) -> dict:
    payload = {"terminated_reason": terminated_reason}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def advance_clock_payload(seconds: int) -> dict:
    return {"seconds": seconds}
