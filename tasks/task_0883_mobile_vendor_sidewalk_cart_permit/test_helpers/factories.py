"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "VENDOR_NAME": "Test Vendor LLC",
    "VENDOR_EMAIL": "vendor@example.com",
    "COMMISSARY_NAME": "Base Commissary",
    "INSURANCE_EFFECTIVE": "2026-05-01T00:00:00Z",
    "INSURANCE_EXPIRES": "2027-05-01T00:00:00Z",
    "INSURANCE_COVERAGE": 100_000_000,
    "COMMISSARY_LICENSE_EXPIRES": "2027-01-01T00:00:00Z",
    "INSPECTION_EXPIRES": "2026-12-01T00:00:00Z",
}


def create_vendor_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["VENDOR_NAME"],
        "contact_email": DEFAULTS["VENDOR_EMAIL"],
        "seniority_years": 0,
    }
    payload.update(overrides)
    return payload


def insurance_payload(**overrides) -> dict:
    payload = {
        "insurance_effective_at": DEFAULTS["INSURANCE_EFFECTIVE"],
        "insurance_expires_at": DEFAULTS["INSURANCE_EXPIRES"],
        "insurance_coverage_cents": DEFAULTS["INSURANCE_COVERAGE"],
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_commissary_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["COMMISSARY_NAME"],
        "health_grade": "A",
        "license_expires_at": DEFAULTS["COMMISSARY_LICENSE_EXPIRES"],
    }
    payload.update(overrides)
    return payload


def create_cart_payload(vendor_id, commissary_id, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "commissary_id": commissary_id,
        "cart_type": "FOOD",
        "size_sqft": 30,
    }
    payload.update(overrides)
    return payload


def inspection_payload(result="PASS", **overrides) -> dict:
    payload = {
        "inspection_type": "HEALTH",
        "result": result,
        "score": 95,
    }
    if result == "PASS":
        payload["inspection_expires_at"] = DEFAULTS["INSPECTION_EXPIRES"]
    payload.update(overrides)
    return payload


def create_zone_payload(**overrides) -> dict:
    payload = {
        "name": "Test Zone",
        "zone_type": "STANDARD",
        "capacity_slots": 5,
        "spacing_min_feet": 20,
    }
    payload.update(overrides)
    return payload


def create_spot_payload(label="S1", position_feet=100, **overrides) -> dict:
    payload = {"label": label, "position_feet": position_feet}
    payload.update(overrides)
    return payload


def create_permit_payload(vendor_id, cart_id, zone_id, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "cart_id": cart_id,
        "zone_id": zone_id,
        "permit_type": "FOOD",
    }
    payload.update(overrides)
    return payload


def create_violation_payload(violation_type="MINOR", description="citation detail", **overrides) -> dict:
    payload = {"violation_type": violation_type, "description": description}
    payload.update(overrides)
    return payload


def create_complaint_payload(complaint_type="NOISE", description="complaint detail", **overrides) -> dict:
    payload = {"complaint_type": complaint_type, "description": description}
    payload.update(overrides)
    return payload


def adjudicate_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def resolve_complaint_payload(resolution_outcome, resolution=None, **overrides) -> dict:
    payload = {"resolution_outcome": resolution_outcome}
    if resolution is not None:
        payload["resolution"] = resolution
    payload.update(overrides)
    return payload


def create_impound_payload(reason="UNPERMITTED", impounded_at="2026-06-01T00:00:00Z", **overrides) -> dict:
    payload = {"reason": reason, "impounded_at": impounded_at}
    payload.update(overrides)
    return payload


def create_lottery_payload(zone_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "entry_fee_cents": 2_500,
        "term_start_at": "2026-07-01T09:00:00Z",
        "term_end_at": "2026-07-01T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_lottery_entry_payload(permit_id, preferred_spot_ids, **overrides) -> dict:
    payload = {"permit_id": permit_id, "preferred_spot_ids": list(preferred_spot_ids)}
    payload.update(overrides)
    return payload


def create_spot_assignment_payload(spot_id, start_at, end_at, expected_zone_version, **overrides) -> dict:
    payload = {
        "spot_id": spot_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_zone_version": expected_zone_version,
    }
    payload.update(overrides)
    return payload
