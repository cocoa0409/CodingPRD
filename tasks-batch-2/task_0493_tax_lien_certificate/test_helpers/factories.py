"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COUNTY_NAME": "Test County",
    "STATE_CODE": "AZ",
    "MAX_INTEREST_RATE_BPS": 1600,
    "BID_DOWN_INCREMENT_BPS": 100,
    "REDEMPTION_PERIOD_DAYS": 365,
    "SUB_TAX_INTEREST_RATE_BPS": 1600,
    "PARCEL_ASSESSED_VALUE_CENTS": 5_000_000,
    "PARCEL_BASE_TAX_DUE_CENTS": 100_000,
}


def create_county_payload(**overrides) -> dict:
    """Input fields for POST /counties. Optional fields (penalty_rate_bps,
    premium_bidding_enabled, premium_earns_interest, day_count_basis) are
    omitted by default so server defaults apply unless overridden."""
    defaults = {
        "name": DEFAULTS["COUNTY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "max_interest_rate_bps": DEFAULTS["MAX_INTEREST_RATE_BPS"],
        "bid_down_increment_bps": DEFAULTS["BID_DOWN_INCREMENT_BPS"],
        "redemption_period_days": DEFAULTS["REDEMPTION_PERIOD_DAYS"],
        "sub_tax_interest_rate_bps": DEFAULTS["SUB_TAX_INTEREST_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    """Input fields for POST /counties/{id}/parcels."""
    defaults = {
        "apn": "APN-1",
        "owner_name": "Test Owner",
        "assessed_value_cents": DEFAULTS["PARCEL_ASSESSED_VALUE_CENTS"],
        "base_tax_due_cents": DEFAULTS["PARCEL_BASE_TAX_DUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_investor_payload(**overrides) -> dict:
    """Input fields for POST /investors."""
    defaults = {
        "legal_name": "Test Investor",
        "tax_id": "TIN-1",
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents, **overrides) -> dict:
    """Input fields for POST /investors/{id}/deposits."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_sale_payload(**overrides) -> dict:
    """Input fields for POST /counties/{id}/sales."""
    defaults = {
        "sale_name": "Test Sale",
        "scheduled_at": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(parcel_id, **overrides) -> dict:
    """Input fields for POST /counties/{id}/sales/{id}/listings."""
    defaults = {"parcel_id": parcel_id}
    defaults.update(overrides)
    return defaults


def create_bid_payload(investor_id, expected_listing_version, **overrides) -> dict:
    """Input fields for POST .../bids. Pass rate_bps for RATE_BID_DOWN or
    premium_cents for PREMIUM via overrides."""
    defaults = {
        "investor_id": investor_id,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


def create_sub_tax_payload(investor_id, tax_year, principal_cents,
                           expected_certificate_version, **overrides) -> dict:
    """Input fields for POST .../sub-taxes."""
    defaults = {
        "investor_id": investor_id,
        "tax_year": tax_year,
        "principal_cents": principal_cents,
        "expected_certificate_version": expected_certificate_version,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(from_investor_id, to_investor_id, consideration_cents,
                              expected_certificate_version, **overrides) -> dict:
    """Input fields for POST .../assignments."""
    defaults = {
        "from_investor_id": from_investor_id,
        "to_investor_id": to_investor_id,
        "consideration_cents": consideration_cents,
        "expected_certificate_version": expected_certificate_version,
    }
    defaults.update(overrides)
    return defaults


def create_deed_application_payload(applicant_investor_id, deed_cost_cents,
                                    **overrides) -> dict:
    """Input fields for POST .../deed-applications."""
    defaults = {
        "applicant_investor_id": applicant_investor_id,
        "deed_cost_cents": deed_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def award_deed_payload(sale_price_cents, **overrides) -> dict:
    """Input fields for POST .../deed-applications/{id}/award."""
    defaults = {"sale_price_cents": sale_price_cents}
    defaults.update(overrides)
    return defaults
