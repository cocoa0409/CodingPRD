"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "BENEFICIARY_NAME": "Beneficiary One",
    "CONTACT_EMAIL": "one@ben.example",
    "LOAN_REFERENCE": "LN-1",
    "BORROWER_NAME": "Borrower One",
    "PROPERTY_ADDRESS": "1 Default Way",
    "COUNTY_CODE": "CC01",
    "UNPAID_PRINCIPAL_CENTS": 40_000_000,
    "MONTHLY_PAYMENT_CENTS": 250_000,
    "MONTHS_IN_ARREARS": 4,
    "LATE_FEE_PER_MONTH_CENTS": 12_500,
    "NOTE_RATE_PCT": 7.2,
    "LAST_INTEREST_PAID_DATE": "2026-07-01",
    "DISTRIBUTION_METHOD": "STATUTORY_PRIORITY",
    "INSTRUMENT_NUMBER": "INST-1",
    "NOD_RECORDING_DATE": "2026-08-01",
    "NEWSPAPER_NAME": "Daily Journal",
    "VENUE_NAME": "VEN-1",
    "SALE_START": "2026-11-23T10:00:00Z",
    "OPENING_BID_CENTS": 42_000_000,
    "MAX_BID_CENTS": 43_000_000,
    "STRATEGY": "UP_TO_MAX",
    "BIDDER_NAME": "Bidder One",
    "BIDDER_EMAIL": "bidder1@bid.example",
    "DEPOSIT_CENTS": 1_000_000,
    "CLAIMANT_NAME": "Lien One",
    "CLAIMANT_TYPE": "JUNIOR_LIENHOLDER",
    "PRIORITY_RANK": 1,
    "ADVANCE_CATEGORY": "PUBLICATION",
}


def create_beneficiary_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BENEFICIARY_NAME"],
        "reference_code": "BEN-1",
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(beneficiary_id: str, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "loan_reference": DEFAULTS["LOAN_REFERENCE"],
        "borrower_name": DEFAULTS["BORROWER_NAME"],
        "property_address": DEFAULTS["PROPERTY_ADDRESS"],
        "county_code": DEFAULTS["COUNTY_CODE"],
        "unpaid_principal_balance_cents": DEFAULTS["UNPAID_PRINCIPAL_CENTS"],
        "monthly_payment_cents": DEFAULTS["MONTHLY_PAYMENT_CENTS"],
        "months_in_arrears": DEFAULTS["MONTHS_IN_ARREARS"],
        "late_fee_per_month_cents": DEFAULTS["LATE_FEE_PER_MONTH_CENTS"],
        "note_rate_pct": DEFAULTS["NOTE_RATE_PCT"],
        "last_interest_paid_date": DEFAULTS["LAST_INTEREST_PAID_DATE"],
        "distribution_method": DEFAULTS["DISTRIBUTION_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_nod_payload(**overrides) -> dict:
    defaults = {
        "recording_date": DEFAULTS["NOD_RECORDING_DATE"],
        "instrument_number": DEFAULTS["INSTRUMENT_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_nots_payload(recording_date: str, **overrides) -> dict:
    defaults = {
        "recording_date": recording_date,
        "instrument_number": DEFAULTS["INSTRUMENT_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_publication_payload(run_date: str, **overrides) -> dict:
    defaults = {
        "run_date": run_date,
        "newspaper_name": DEFAULTS["NEWSPAPER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def schedule_sale_payload(**overrides) -> dict:
    defaults = {
        "venue_name": DEFAULTS["VENUE_NAME"],
        "scheduled_sale_start_at": DEFAULTS["SALE_START"],
    }
    defaults.update(overrides)
    return defaults


def create_cost_advance_payload(**overrides) -> dict:
    defaults = {
        "category": DEFAULTS["ADVANCE_CATEGORY"],
        "amount_cents": 35_000,
        "incurred_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(quote_type: str, good_through_date: str,
                         expected_foreclosure_case_version: int) -> dict:
    return {
        "quote_type": quote_type,
        "good_through_date": good_through_date,
        "expected_foreclosure_case_version": expected_foreclosure_case_version,
    }


def create_stay_order_payload(**overrides) -> dict:
    defaults = {
        "stay_type": "LITIGATION_HOLD",
        "court_case_number": "CV-26-0001",
        "filed_at": "2026-07-31T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bidding_instruction_payload(expected_foreclosure_case_version: int,
                                       **overrides) -> dict:
    defaults = {
        "opening_bid_cents": DEFAULTS["OPENING_BID_CENTS"],
        "max_bid_cents": DEFAULTS["MAX_BID_CENTS"],
        "strategy": DEFAULTS["STRATEGY"],
        "expected_foreclosure_case_version": expected_foreclosure_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_postponement_payload(new_sale_start_at: str,
                                expected_auction_sale_version: int,
                                **overrides) -> dict:
    defaults = {
        "new_sale_start_at": new_sale_start_at,
        "reason": "TRUSTEE_DISCRETION",
        "announced_via": "ADVANCE",
        "expected_auction_sale_version": expected_auction_sale_version,
    }
    defaults.update(overrides)
    return defaults


def create_bidder_registration_payload(**overrides) -> dict:
    defaults = {
        "bidder_name": DEFAULTS["BIDDER_NAME"],
        "bidder_email": DEFAULTS["BIDDER_EMAIL"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(bidder_registration_id: str, amount_cents: int) -> dict:
    return {
        "bidder_registration_id": bidder_registration_id,
        "amount_cents": amount_cents,
    }


def create_surplus_claim_payload(**overrides) -> dict:
    defaults = {
        "claimant_name": DEFAULTS["CLAIMANT_NAME"],
        "claimant_type": DEFAULTS["CLAIMANT_TYPE"],
        "priority_rank": DEFAULTS["PRIORITY_RANK"],
        "claimed_amount_cents": 100_000,
        "filed_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults
