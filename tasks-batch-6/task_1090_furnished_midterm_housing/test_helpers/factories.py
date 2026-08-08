"""Payload factories — one per input-bearing entity, input fields only."""

DEFAULTS = {
    "HOST_NAME": "Test Host",
    "HOST_EMAIL": "host@example.com",
    "TENANT_NAME": "Test Tenant",
    "TENANT_EMAIL": "tenant@example.com",
    "UNIT_TITLE": "Furnished Unit",
    "UNIT_ADDRESS": "1 Test Street",
    "MONTHLY_RATE_CENTS": 300000,
    "DOCUMENT_REF": "doc-ref-1",
}


def create_host_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["HOST_NAME"],
        "email": DEFAULTS["HOST_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["TENANT_NAME"],
        "email": DEFAULTS["TENANT_EMAIL"],
        "tenant_type": "TRAVEL_NURSE",
    }
    defaults.update(overrides)
    return defaults


def create_verification_payload(tenant_id, **overrides) -> dict:
    defaults = {
        "tenant_id": tenant_id,
        "doc_type": "GOVERNMENT_ID",
        "document_ref": DEFAULTS["DOCUMENT_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(host_id, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "title": DEFAULTS["UNIT_TITLE"],
        "address": DEFAULTS["UNIT_ADDRESS"],
        "monthly_rate_cents": DEFAULTS["MONTHLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(unit_id, tenant_id, start_date, end_date, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def create_extension_payload(booking_id, expected_booking_version, new_end_date, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "expected_booking_version": expected_booking_version,
        "new_end_date": new_end_date,
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(deposit_id, expected_deposit_version, claimed_cents, description="damage", **overrides) -> dict:
    defaults = {
        "deposit_id": deposit_id,
        "expected_deposit_version": expected_deposit_version,
        "claimed_cents": claimed_cents,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_coi_policy_payload(booking_id, coverage_cents, effective_start, effective_end, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "coverage_cents": coverage_cents,
        "effective_start": effective_start,
        "effective_end": effective_end,
    }
    defaults.update(overrides)
    return defaults
