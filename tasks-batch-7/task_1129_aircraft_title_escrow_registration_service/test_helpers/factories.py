"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "N_NUMBER": "N100TS",
    "SERIAL_NUMBER": "SN-1000",
    "MAKE_MODEL": "Cessna 172",
    "YEAR": 2010,
    "LEGAL_NAME": "Test Party LLC",
    "PURCHASE_PRICE_CENTS": 10_000_000,
    "ANNUAL_REGISTRATION_FEE_CENTS": 0,
    "PRORATION_METHOD": "DAILY",
    "EXPECTED_CLOSE_DATE": "2026-06-30",
    "BENEFICIARY_NAME": "Beneficiary LLC",
    "BENEFICIARY_CITIZENSHIP": "NON_US_CITIZEN",
    "EFFECTIVE_DATE": "2026-01-01",
    "EXPIRY_DATE": "2026-12-31",
    "GOOD_THROUGH_DATE": "2026-06-30",
    "CLOCK_TO": "2026-06-01T00:00:00Z",
}


def create_aircraft_payload(**overrides) -> dict:
    payload = {
        "n_number": DEFAULTS["N_NUMBER"],
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "make_model": DEFAULTS["MAKE_MODEL"],
        "year": DEFAULTS["YEAR"],
    }
    payload.update(overrides)
    return payload


def create_party_payload(party_type="BUYER", legal_name=None, **overrides) -> dict:
    payload = {
        "party_type": party_type,
        "legal_name": legal_name or DEFAULTS["LEGAL_NAME"],
    }
    payload.update(overrides)
    return payload


def create_escrow_file_payload(aircraft_id, buyer_party_id, seller_party_id, **overrides) -> dict:
    payload = {
        "aircraft_id": aircraft_id,
        "buyer_party_id": buyer_party_id,
        "seller_party_id": seller_party_id,
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "annual_registration_fee_cents": DEFAULTS["ANNUAL_REGISTRATION_FEE_CENTS"],
        "proration_method": DEFAULTS["PRORATION_METHOD"],
        "expected_close_date": DEFAULTS["EXPECTED_CLOSE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_trust_agreement_payload(aircraft_id, trustee_party_id, **overrides) -> dict:
    payload = {
        "aircraft_id": aircraft_id,
        "trustee_party_id": trustee_party_id,
        "beneficiary_name": DEFAULTS["BENEFICIARY_NAME"],
        "beneficiary_citizenship": DEFAULTS["BENEFICIARY_CITIZENSHIP"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(payer_party_id, amount_cents, expected_escrow_file_version,
                           purpose="BUYER_FUNDS", **overrides) -> dict:
    payload = {
        "payer_party_id": payer_party_id,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "expected_escrow_file_version": expected_escrow_file_version,
    }
    payload.update(overrides)
    return payload


def create_disbursement_payload(payee_party_id, amount_cents, purpose,
                                expected_escrow_file_version, **overrides) -> dict:
    payload = {
        "payee_party_id": payee_party_id,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "expected_escrow_file_version": expected_escrow_file_version,
    }
    payload.update(overrides)
    return payload


def create_filing_payload(filing_type="BILL_OF_SALE", **overrides) -> dict:
    payload = {"filing_type": filing_type}
    payload.update(overrides)
    return payload


def create_document_payload(doc_type="PURCHASE_AGREEMENT", required_signer_party_ids=(),
                            **overrides) -> dict:
    payload = {
        "doc_type": doc_type,
        "required_signer_party_ids": list(required_signer_party_ids),
    }
    payload.update(overrides)
    return payload


def create_finding_payload(lienor_party_id, amount_cents, lien_type="FAA_RECORDED",
                           lienor_name="Lender Co", filed_at="2025-01-10",
                           **overrides) -> dict:
    payload = {
        "lienor_party_id": lienor_party_id,
        "lienor_name": lienor_name,
        "amount_cents": amount_cents,
        "lien_type": lien_type,
        "filed_at": filed_at,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(payoff_basis, quoted_payoff_cents,
                         good_through_date=None, **overrides) -> dict:
    payload = {
        "payoff_basis": payoff_basis,
        "quoted_payoff_cents": quoted_payoff_cents,
        "good_through_date": good_through_date or DEFAULTS["GOOD_THROUGH_DATE"],
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601=None) -> dict:
    return {"to_iso8601": to_iso8601 or DEFAULTS["CLOCK_TO"]}
