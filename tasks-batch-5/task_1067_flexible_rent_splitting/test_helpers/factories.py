"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LANDLORD_NAME": "Ada Owner",
    "UNIT_LABEL": "Maple Court #4B",
    "FULL_RENT_CENTS": 120000,
    "RENT_DUE_DAY": 1,
    "REMITTANCE_ACCOUNT_REF": "acct_default",
    "PORTION_CENTS": 100000,
    "INCOME_CENTS": 300000,
    "SPLIT_COUNT": 2,
    "CYCLE_MONTH": "2026-07",
    "CYCLE_START": "2026-07-01T00:00:00Z",
}


def create_property_payload(**overrides) -> dict:
    """Input fields for POST /api/properties. integration_status optional (defaults PENDING server-side)."""
    payload = {
        "landlord_name": DEFAULTS["LANDLORD_NAME"],
        "unit_label": DEFAULTS["UNIT_LABEL"],
        "full_rent_cents": DEFAULTS["FULL_RENT_CENTS"],
        "rent_due_day": DEFAULTS["RENT_DUE_DAY"],
        "remittance_account_ref": DEFAULTS["REMITTANCE_ACCOUNT_REF"],
        "integration_status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_renter_payload(property_id, **overrides) -> dict:
    """Input fields for POST /api/renters."""
    payload = {
        "property_id": property_id,
        "email": "renter@example.com",
        "full_name": "Rey Renter",
        "portion_rent_cents": DEFAULTS["PORTION_CENTS"],
    }
    payload.update(overrides)
    return payload


def submit_application_payload(**overrides) -> dict:
    """Input fields for POST /api/renters/{id}/applications. prior_delinquency_count optional (defaults 0)."""
    payload = {
        "reported_monthly_income_cents": DEFAULTS["INCOME_CENTS"],
        "requested_split_count": DEFAULTS["SPLIT_COUNT"],
        "prior_delinquency_count": 0,
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(renter_id, **overrides) -> dict:
    """Input fields for POST /api/billing-cycles (SPLIT mode by default)."""
    payload = {
        "renter_id": renter_id,
        "cycle_month": DEFAULTS["CYCLE_MONTH"],
        "cycle_start_date": DEFAULTS["CYCLE_START"],
        "mode": "SPLIT",
        "split_count": DEFAULTS["SPLIT_COUNT"],
    }
    payload.update(overrides)
    return payload


def defer_cycle_payload(renter_id, deferred_amount_cents=60000, planned_defer_days=20,
                        **overrides) -> dict:
    """Input fields for POST /api/billing-cycles in DEFER mode."""
    payload = {
        "renter_id": renter_id,
        "cycle_month": DEFAULTS["CYCLE_MONTH"],
        "cycle_start_date": DEFAULTS["CYCLE_START"],
        "mode": "DEFER",
        "split_count": 2,
        "deferred_amount_cents": deferred_amount_cents,
        "planned_defer_days": planned_defer_days,
    }
    payload.update(overrides)
    return payload


def charge_payload(method="MANUAL", outcome="SUCCEED", **overrides) -> dict:
    """Input fields for POST /api/installments/{id}/charge."""
    payload = {"method": method}
    if outcome is not None:
        payload["outcome"] = outcome
    payload.update(overrides)
    return payload
