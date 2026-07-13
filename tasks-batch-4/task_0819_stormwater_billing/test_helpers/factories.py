"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _unique_parcel_number(prefix: str = "P") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_account_payload(**overrides) -> dict:
    """POST /accounts inputs (PRD §3.1). billing_method and mailing_address optional."""
    defaults = {
        "owner_name": "Acme",
        "contact_email": "a@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(account_id, **overrides) -> dict:
    """POST /parcels inputs (PRD §3.1)."""
    defaults = {
        "account_id": account_id,
        "parcel_number": _unique_parcel_number(),
        "land_use": "COMMERCIAL",
    }
    defaults.update(overrides)
    return defaults


def create_measurement_payload(parcel_id, expected_parcel_version, **overrides) -> dict:
    """POST /impervious-measurements inputs (PRD §3.2). source optional (default ROUTINE)."""
    defaults = {
        "parcel_id": parcel_id,
        "measured_sqft": 18000,
        "method": "GIS",
        "expected_parcel_version": expected_parcel_version,
    }
    defaults.update(overrides)
    return defaults


def create_exemption_payload(parcel_id, **overrides) -> dict:
    """POST /exemptions inputs (PRD §3.3). decision_note optional."""
    defaults = {
        "parcel_id": parcel_id,
        "category": "GOVERNMENT",
        "requested_pct": 0.25,
    }
    defaults.update(overrides)
    return defaults


def create_bmp_credit_payload(parcel_id, **overrides) -> dict:
    """POST /bmp-credits inputs (PRD §3.4)."""
    defaults = {
        "parcel_id": parcel_id,
        "bmp_type": "RAIN_GARDEN",
        "self_reported_score": 90,
        "effective_date": "2026-01-01T00:00:00Z",
        "expiry_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(bmp_credit_id, **overrides) -> dict:
    """POST /credit-inspections inputs (PRD §3.4). inspector_note optional."""
    defaults = {
        "bmp_credit_id": bmp_credit_id,
        "scheduled_date": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(**overrides) -> dict:
    """POST /credit-inspections/{id}/complete inputs (PRD §3.4)."""
    defaults = {
        "result": "PASS",
        "observed_score": 70,
    }
    defaults.update(overrides)
    return defaults


def create_bill_payload(parcel_id, account_id, **overrides) -> dict:
    """POST /bills inputs (PRD §3.5). fee_variant optional (default MARGINAL)."""
    defaults = {
        "parcel_id": parcel_id,
        "account_id": account_id,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-03-31T00:00:00Z",
        "due_date": "2026-04-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(parcel_id, account_id, **overrides) -> dict:
    """POST /appeals inputs (PRD §3.7). bill_id optional."""
    defaults = {
        "parcel_id": parcel_id,
        "account_id": account_id,
        "grounds": "MEASUREMENT_ERROR",
        "narrative": "disputed measurement",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(bill_id, account_id, amount_cents, **overrides) -> dict:
    """POST /payments inputs (PRD §3.6)."""
    defaults = {
        "bill_id": bill_id,
        "account_id": account_id,
        "amount_cents": amount_cents,
        "method": "ACH",
    }
    defaults.update(overrides)
    return defaults
