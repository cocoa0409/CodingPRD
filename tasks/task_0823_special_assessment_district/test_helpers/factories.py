"""Payload factories — one per write endpoint, input fields only."""


def create_district_payload(**overrides) -> dict:
    """POST /districts. Required: name, formation_method, total_project_cost_cents.
    Optional: incidental_cost_cents, protest_threshold_pct."""
    defaults = {
        "name": "Test District",
        "formation_method": "BENEFIT_UNITS",
        "total_project_cost_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    """POST /districts/{id}/parcels. Required: apn, owner_name.
    Optional weights: benefit_units, land_area_sqft, front_footage_ft."""
    defaults = {
        "apn": "APN-1",
        "owner_name": "Owner",
    }
    defaults.update(overrides)
    return defaults


def subdivide_payload(children) -> dict:
    """POST /parcels/{id}/subdivide. children: list of parcel-spec dicts."""
    return {"children": children}


def create_protest_payload(**overrides) -> dict:
    """POST /parcels/{id}/protests. Required: filed_by."""
    defaults = {"filed_by": "Owner"}
    defaults.update(overrides)
    return defaults


def create_roll_payload(**overrides) -> dict:
    """POST /districts/{id}/rolls. Optional: method (defaults to district's formation_method)."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_bond_payload(**overrides) -> dict:
    """POST /districts/{id}/bonds. Required: issuance_date.
    Optional: coupon_rate_bps, term_years, reserve_fund_pct, issuance_cost_cents,
    admin_fee_bps, prepayment_premium_pct."""
    defaults = {
        "issuance_date": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_installment_payload(**overrides) -> dict:
    """POST /parcels/{id}/installments. Required: bond_id, installment_year, due_date,
    principal_cents. Optional: interest_cents, admin_fee_cents."""
    defaults = {
        "installment_year": 1,
        "due_date": "2027-07-01T00:00:00Z",
        "principal_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    """POST /installments/{id}/payments. Required: amount_cents, payment_date, paid_by."""
    defaults = {
        "amount_cents": 0,
        "payment_date": "2027-07-01T00:00:00Z",
        "paid_by": "Owner",
    }
    defaults.update(overrides)
    return defaults


def create_payoff_quote_payload(**overrides) -> dict:
    """POST /parcels/{id}/payoff-quotes. Required: quote_mode, quote_date,
    expected_parcel_version."""
    defaults = {
        "quote_mode": "IMMEDIATE",
        "quote_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def advance_foreclosure_payload(to_status) -> dict:
    """POST /foreclosures/{id}/advance. Required: to_status."""
    return {"to_status": to_status}


def set_clock_payload(to_iso8601) -> dict:
    """POST /_clock/set_current_utc. Required: to_iso8601."""
    return {"to_iso8601": to_iso8601}
