"""Payload factories — one per entity, input fields only (Locksmith & Lockout Dispatch)."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "SERVICE_ADDRESS": "1 Test St",
    "REQUESTED_AT_MINUTE": 600,   # daytime — no after-hours surcharge
    "BASE_TRAVEL_MINUTES": 20,
}


def create_service_job_payload(
    customer_user_id="cust-default", service_type="REKEY", **overrides
) -> dict:
    """Intake payload. requested_at_minute defaults to a daytime value (no surcharge)."""
    payload = {
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "customer_user_id": customer_user_id,
        "service_type": service_type,
        "service_address": DEFAULTS["SERVICE_ADDRESS"],
        "requested_at_minute": DEFAULTS["REQUESTED_AT_MINUTE"],
    }
    payload.update(overrides)
    return payload


def create_technician_payload(
    full_name="Test Tech", certified_for=None, base_travel_minutes=None, **overrides
) -> dict:
    payload = {
        "full_name": full_name,
        "certified_for": certified_for if certified_for is not None else ["REKEY"],
        "base_travel_minutes": (
            base_travel_minutes
            if base_travel_minutes is not None
            else DEFAULTS["BASE_TRAVEL_MINUTES"]
        ),
    }
    payload.update(overrides)
    return payload


def create_job_bay_payload(bay_name="Test Bench", **overrides) -> dict:
    payload = {"bay_name": bay_name}
    payload.update(overrides)
    return payload


def create_dispatch_payload(technician_id, eta_start_minute, eta_end_minute, **overrides) -> dict:
    payload = {
        "technician_id": technician_id,
        "eta_start_minute": eta_start_minute,
        "eta_end_minute": eta_end_minute,
    }
    payload.update(overrides)
    return payload


def create_bay_booking_payload(
    service_job_id, job_bay_id, slot_start_minute, slot_end_minute, **overrides
) -> dict:
    payload = {
        "service_job_id": service_job_id,
        "job_bay_id": job_bay_id,
        "slot_start_minute": slot_start_minute,
        "slot_end_minute": slot_end_minute,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(labor_hours=1.0, part_lines=None, **overrides) -> dict:
    payload = {
        "labor_hours": labor_hours,
        "part_lines": part_lines if part_lines is not None else [],
    }
    payload.update(overrides)
    return payload


def create_lock_part_payload(sku="SKU-TEST", units_total=5, **overrides) -> dict:
    payload = {"sku": sku, "units_total": units_total}
    payload.update(overrides)
    return payload


def create_part_reservation_payload(
    on_site_quote_id, lock_part_id, quantity, expected_lockpart_version, **overrides
) -> dict:
    payload = {
        "on_site_quote_id": on_site_quote_id,
        "lock_part_id": lock_part_id,
        "quantity": quantity,
        "expected_lockpart_version": expected_lockpart_version,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(captured_amount_cents, **overrides) -> dict:
    payload = {"captured_amount_cents": captured_amount_cents}
    payload.update(overrides)
    return payload


def create_key_authorization_payload(
    auth_kind="KEY_DUPLICATION", authorizing_party="Owner", id_document_ref="DL-1", **overrides
) -> dict:
    payload = {
        "auth_kind": auth_kind,
        "authorizing_party": authorizing_party,
        "id_document_ref": id_document_ref,
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(
    filed_at_minute=700, days_since_close=3, reason="defect", refund_amount_cents=8000, **overrides
) -> dict:
    payload = {
        "filed_at_minute": filed_at_minute,
        "days_since_close": days_since_close,
        "reason": reason,
        "refund_amount_cents": refund_amount_cents,
    }
    payload.update(overrides)
    return payload
