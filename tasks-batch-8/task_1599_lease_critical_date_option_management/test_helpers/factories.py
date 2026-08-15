"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PORTFOLIO_NAME": "Test Portfolio",
    "PORTFOLIO_REGION": "WEST",
    "LADDER_MAX_PCT": 40,
    "PREMISES_LABEL": "HQ-1",
    "RSF": 5000,
    "BASE_RENT": 4000,
    "COMMENCEMENT": "2026-01-01T00:00:00Z",
    "EXPIRATION": "2027-12-31T00:00:00Z",
    "TIER1_PCT": 150,
    "TIER2_PCT": 200,
    "WINDOW_OPEN": "2026-08-01T00:00:00Z",
    "WINDOW_CLOSE": "2026-12-31T00:00:00Z",
    "TARGET_COMMENCEMENT": "2028-01-01T00:00:00Z",
    "EXTENSION_YEARS": 5,
    "FIXED_RENT": 4200,
    "AMENDMENT_NEW_EXPIRATION": "2032-12-31T00:00:00Z",
    "AMENDMENT_NEW_RENT": 5500,
}


def create_portfolio_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PORTFOLIO_NAME"],
        "region": DEFAULTS["PORTFOLIO_REGION"],
        "laddering_max_pct_per_year": DEFAULTS["LADDER_MAX_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_contact_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Contact",
        "email": "contact@example.com",
        "contact_kind": "ASSET_MANAGER",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "premises_label": DEFAULTS["PREMISES_LABEL"],
        "rentable_square_feet": DEFAULTS["RSF"],
        "base_rent_cents_per_rsf_year": DEFAULTS["BASE_RENT"],
        "commencement_date": DEFAULTS["COMMENCEMENT"],
        "expiration_date": DEFAULTS["EXPIRATION"],
        "holdover_tier1_pct": DEFAULTS["TIER1_PCT"],
        "holdover_tier2_pct": DEFAULTS["TIER2_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_option_payload(**overrides) -> dict:
    defaults = {
        "option_type": "RENEWAL",
        "notice_window_open_date": DEFAULTS["WINDOW_OPEN"],
        "notice_window_close_date": DEFAULTS["WINDOW_CLOSE"],
        "target_commencement_date": DEFAULTS["TARGET_COMMENCEMENT"],
        "rate_determination": "FIXED",
        "fixed_rent_cents_per_rsf_year": DEFAULTS["FIXED_RENT"],
    }
    defaults.update(overrides)
    # PRD §3.3 coherence: a RENEWAL option's extension_years sets the renewal
    # term length (1-10), so the default RENEWAL payload must carry it.
    if defaults["option_type"] == "RENEWAL" and "extension_years" not in overrides:
        defaults["extension_years"] = DEFAULTS["EXTENSION_YEARS"]
    # PRD §3.3 coherence: "a FAIR_MARKET option must not carry
    # [fixed_rent_cents_per_rsf_year] at all" — drop the FIXED-oriented default
    # unless the caller explicitly passes one (e.g. the incoherence test).
    if (defaults["rate_determination"] == "FAIR_MARKET"
            and "fixed_rent_cents_per_rsf_year" not in overrides):
        defaults.pop("fixed_rent_cents_per_rsf_year", None)
    return defaults


def create_notice_payload(expected_lease_version, **overrides) -> dict:
    defaults = {
        "delivery_method": "COURIER",
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults


def create_comparable_assessment_payload(expected_option_version, **overrides) -> dict:
    defaults = {
        "method": "COMPARABLE_AVERAGE",
        "comparable_rents_cents": [5000, 5001, 5002],
        "expected_option_version": expected_option_version,
    }
    defaults.update(overrides)
    return defaults


def create_regression_assessment_payload(expected_option_version, **overrides) -> dict:
    defaults = {
        "method": "PSF_REGRESSION",
        "regression_base_cents": 4800,
        "regression_adjustments": [],
        "expected_option_version": expected_option_version,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "landlord_rent_cents": 6000,
        "tenant_rent_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {
        "panel_guidance_rent_cents": 5500,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "kind": "RENEWAL_TERM",
        "new_expiration_date": DEFAULTS["AMENDMENT_NEW_EXPIRATION"],
        "new_base_rent_cents_per_rsf_year": DEFAULTS["AMENDMENT_NEW_RENT"],
    }
    defaults.update(overrides)
    return defaults


def withdraw_option_payload(expected_lease_version) -> dict:
    return {"expected_lease_version": expected_lease_version}


def propose_amendment_payload(expected_lease_version) -> dict:
    return {"expected_lease_version": expected_lease_version}


def execute_amendment_payload(expected_lease_version, **overrides) -> dict:
    defaults = {"expected_lease_version": expected_lease_version}
    defaults.update(overrides)
    return defaults


def reject_notice_payload(rejection_reason="refused") -> dict:
    return {"rejection_reason": rejection_reason}


def counter_amendment_payload(new_base_rent_cents_per_rsf_year) -> dict:
    return {"new_base_rent_cents_per_rsf_year": new_base_rent_cents_per_rsf_year}
