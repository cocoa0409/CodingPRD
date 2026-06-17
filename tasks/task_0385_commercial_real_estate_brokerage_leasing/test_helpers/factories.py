"""Payload factories — one per entity, input fields only."""


def create_brokerage_payload(**overrides) -> dict:
    """Input fields for POST /brokerages. default_commission_pct is optional."""
    defaults = {
        "name": "Test Brokerage",
        "side": "DUAL",
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    """Input fields for POST /brokers."""
    defaults = {
        "brokerage_id": None,
        "full_name": "Test Broker",
        "license_no": "L-0001",
        "role": "LISTING_BROKER",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    """Input fields for POST /properties."""
    defaults = {
        "listing_broker_id": None,
        "name": "Test Property",
        "market": "SOMA-SF",
        "asset_class": "OFFICE",
        "total_sf": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_space_payload(**overrides) -> dict:
    """Input fields for POST /spaces. free_rent_months and ti_allowance_psf are optional."""
    defaults = {
        "property_id": None,
        "suite_no": "100",
        "rentable_sf": 3000,
        "asking_rent_psf_yr": 50,
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(**overrides) -> dict:
    """Input fields for POST /listings. annual_escalation_pct and co_broke_offered_pct optional."""
    defaults = {
        "space_id": None,
        "listing_broker_id": None,
        "term_months": 60,
    }
    defaults.update(overrides)
    return defaults


def create_requirement_payload(**overrides) -> dict:
    """Input fields for POST /requirements."""
    defaults = {
        "tenant_broker_id": None,
        "tenant_name": "Test Tenant",
        "market": "SOMA-SF",
        "asset_class": "OFFICE",
        "min_sf": 1000,
        "max_sf": 6000,
        "max_rent_psf_yr": 70,
    }
    defaults.update(overrides)
    return defaults


def create_tour_payload(**overrides) -> dict:
    """Input fields for POST /tours."""
    defaults = {
        "requirement_id": None,
        "tenant_broker_id": None,
        "space_id": None,
        "window_start": "2026-07-01T10:00:00Z",
        "window_end": "2026-07-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(**overrides) -> dict:
    """Input fields for POST /deals."""
    defaults = {
        "listing_id": None,
        "requirement_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(**overrides) -> dict:
    """Input fields for POST /deals/{id}/proposals.
    free_rent_months, ti_allowance_psf, annual_escalation_pct are optional."""
    defaults = {
        "from_side": "LISTING",
        "base_rent_psf_yr": 50,
        "term_months": 60,
        "expected_deal_version": 1,
    }
    defaults.update(overrides)
    return defaults
