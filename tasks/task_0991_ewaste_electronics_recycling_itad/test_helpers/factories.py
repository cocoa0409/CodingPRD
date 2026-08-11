"""Payload factories — one per entity, input fields only (PRD §4)."""


def create_account_payload(company_name="Test Co", contact_email="contact@test.example", **overrides) -> dict:
    defaults = {"company_name": company_name, "contact_email": contact_email}
    defaults.update(overrides)
    return defaults


def create_recycler_payload(
    name="Rec Co",
    certification_standard="R2",
    certification_expires_at="2027-05-01T00:00:00Z",
    accepted_categories=None,
    daily_intake_capacity_kg=100000,
    violation_count=0,
    **overrides,
) -> dict:
    defaults = {
        "name": name,
        "certification_standard": certification_standard,
        "certification_expires_at": certification_expires_at,
        "accepted_categories": accepted_categories
        or ["LAPTOP", "DESKTOP", "SERVER", "PHONE", "TABLET", "MONITOR", "BATTERY", "OTHER"],
        "daily_intake_capacity_kg": daily_intake_capacity_kg,
        "violation_count": violation_count,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(
    standard="R2",
    sanitization_methods_allowed=None,
    export_allowed=True,
    resale_requires_verified_sanitization=True,
    is_active=True,
    weight_cert_freshness=0.5,
    weight_volume=0.2,
    weight_violations=0.3,
    **overrides,
) -> dict:
    defaults = {
        "standard": standard,
        "sanitization_methods_allowed": sanitization_methods_allowed
        or ["CRYPTO_ERASE", "NIST_CLEAR", "NIST_PURGE", "PHYSICAL_DESTROY"],
        "export_allowed": export_allowed,
        "resale_requires_verified_sanitization": resale_requires_verified_sanitization,
        "is_active": is_active,
        "weight_cert_freshness": weight_cert_freshness,
        "weight_volume": weight_volume,
        "weight_violations": weight_violations,
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(
    account_id,
    mode="DROPOFF",
    declared_item_count=1,
    scheduled_start="2026-06-01T09:00:00Z",
    scheduled_end="2026-06-01T11:00:00Z",
    pickup_route=None,
    **overrides,
) -> dict:
    # pickup_route is required exactly when mode is PICKUP and absent otherwise (PRD §3.3).
    defaults = {
        "account_id": account_id,
        "mode": mode,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "declared_item_count": declared_item_count,
    }
    if pickup_route is not None:
        defaults["pickup_route"] = pickup_route
    defaults.update(overrides)
    return defaults


def create_item_payload(
    serial_number="SN-1",
    category="LAPTOP",
    weight_kg=2.0,
    data_bearing=False,
    hazmat_flag=False,
    declared_grade="A",
    **overrides,
) -> dict:
    defaults = {
        "serial_number": serial_number,
        "category": category,
        "weight_kg": weight_kg,
        "data_bearing": data_bearing,
        "hazmat_flag": hazmat_flag,
        "declared_grade": declared_grade,
    }
    defaults.update(overrides)
    return defaults


def create_sanitization_payload(method="NIST_CLEAR", outcome="PASS", **overrides) -> dict:
    defaults = {"method": method, "outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_listing_payload(
    item_id,
    asking_price_cents=60000,
    floor_price_cents=50000,
    channel="RETAIL",
    **overrides,
) -> dict:
    defaults = {
        "item_id": item_id,
        "asking_price_cents": asking_price_cents,
        "floor_price_cents": floor_price_cents,
        "channel": channel,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(
    scheduled_delivery_date="2026-06-10T00:00:00Z",
    is_export=False,
    recycler_id=None,
    **overrides,
) -> dict:
    defaults = {"scheduled_delivery_date": scheduled_delivery_date, "is_export": is_export}
    if recycler_id is not None:
        defaults["recycler_id"] = recycler_id
    defaults.update(overrides)
    return defaults
