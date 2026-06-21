"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults for required fields and accepts
**overrides for the values tests need to control.
"""

DEFAULTS = {
    "BUSINESS_NAME": "Test Business",
    "BILLING_EMAIL": "b@x.com",
    "COMPLIANCE_REGIME": "STANDARD",
    "LOCATION_LABEL": "HQ",
    "LOCATION_ADDRESS": "1 Main",
    "SLOT_START": "2026-07-01T09:00:00Z",
    "SLOT_END": "2026-07-01T10:00:00Z",
}


def create_account_payload(**overrides) -> dict:
    payload = {
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "compliance_regime": DEFAULTS["COMPLIANCE_REGIME"],
        "billing_email": DEFAULTS["BILLING_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_location_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "label": DEFAULTS["LOCATION_LABEL"],
        "address": DEFAULTS["LOCATION_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def create_rate_card_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "scheduled_purge_rate_cents_per_kg": 5,
        "onetime_purge_rate_cents_per_kg": 8,
        "onsite_trip_fee_cents": 2500,
        "console_swap_fee_cents": 1000,
        "storage_rate_cents_per_box_per_period": 300,
        "retrieval_fee_cents": 4000,
    }
    payload.update(overrides)
    return payload


def create_container_payload(account_id, location_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "location_id": location_id,
        "container_type": "CONSOLE",
        "capacity_kg": 50,
        "tare_weight_kg": 8.0,
    }
    payload.update(overrides)
    return payload


def create_order_payload(account_id, location_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "location_id": location_id,
        "service_mode": "ON_SITE",
        "cadence": "SCHEDULED",
        "scheduled_slot_start": DEFAULTS["SLOT_START"],
        "scheduled_slot_end": DEFAULTS["SLOT_END"],
    }
    payload.update(overrides)
    return payload


def weigh_in_payload(gross_weight_kg, **overrides) -> dict:
    payload = {"gross_weight_kg": gross_weight_kg}
    payload.update(overrides)
    return payload


def reschedule_payload(expected_serviceorder_version, scheduled_slot_start,
                       scheduled_slot_end, **overrides) -> dict:
    payload = {
        "expected_serviceorder_version": expected_serviceorder_version,
        "scheduled_slot_start": scheduled_slot_start,
        "scheduled_slot_end": scheduled_slot_end,
    }
    payload.update(overrides)
    return payload


def destroy_payload(witnessed_by, **overrides) -> dict:
    payload = {"witnessed_by": witnessed_by}
    payload.update(overrides)
    return payload


def create_retention_box_payload(account_id, location_id, barcode, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "location_id": location_id,
        "barcode": barcode,
    }
    payload.update(overrides)
    return payload


def create_retrieval_request_payload(box_id, account_id, **overrides) -> dict:
    payload = {
        "box_id": box_id,
        "account_id": account_id,
        "priority": "STANDARD",
        "requested_by": "mgr-1",
    }
    payload.update(overrides)
    return payload


def create_compliance_hold_payload(account_id, subject_type, subject_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": "LITIGATION_HOLD",
    }
    payload.update(overrides)
    return payload


def credit_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
