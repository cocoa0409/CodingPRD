"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "POLICY_NAME": "CHEP Blue",
    "CURRENCY": "USD",
    "ASSET_TYPE_CODE": "PALLET_STD",
    "ASSET_TYPE_NAME": "Standard Pallet",
    "BASE_DAILY_RATE_CENTS": 500,
    "REPLACEMENT_COST_CENTS": 3000,
    "USEFUL_LIFE_DAYS": 1825,
    "LEGAL_NAME": "Acme Mfg",
    "ROLE_TYPE": "MANUFACTURER",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "LOCATION_NAME": "L1",
    "SERIAL": "S1",
    "IN_SERVICE_AT": "2026-01-01T00:00:00Z",
}


def create_pool_policy_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["POLICY_NAME"],
        "currency": DEFAULTS["CURRENCY"],
    }
    payload.update(overrides)
    return payload


def create_asset_type_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["ASSET_TYPE_CODE"],
        "name": DEFAULTS["ASSET_TYPE_NAME"],
        "base_daily_rate_cents": DEFAULTS["BASE_DAILY_RATE_CENTS"],
        "replacement_cost_cents": DEFAULTS["REPLACEMENT_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_account_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "role_type": DEFAULTS["ROLE_TYPE"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_location_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "name": DEFAULTS["LOCATION_NAME"],
    }
    payload.update(overrides)
    return payload


def create_asset_payload(asset_type_id, current_location_id, **overrides) -> dict:
    payload = {
        "asset_type_id": asset_type_id,
        "serial": DEFAULTS["SERIAL"],
        "in_service_at": DEFAULTS["IN_SERVICE_AT"],
        "current_location_id": current_location_id,
    }
    payload.update(overrides)
    return payload


def create_transfer_order_payload(
    from_location_id, to_location_id, kind, asset_ids, **overrides
) -> dict:
    payload = {
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "kind": kind,
        "asset_ids": asset_ids,
    }
    payload.update(overrides)
    return payload


def create_hire_payload(
    account_id, location_id, asset_type_id, asset_ids, expected_location_version,
    **overrides
) -> dict:
    payload = {
        "account_id": account_id,
        "location_id": location_id,
        "asset_type_id": asset_type_id,
        "asset_ids": asset_ids,
        "expected_location_version": expected_location_version,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(
    location_id, window_start, window_end, counted_physical, **overrides
) -> dict:
    payload = {
        "location_id": location_id,
        "window_start": window_start,
        "window_end": window_end,
        "counted_physical": counted_physical,
    }
    payload.update(overrides)
    return payload


def create_voucher_payload(
    from_location_id, to_account_id, asset_type_id, quantity,
    expected_from_location_version, **overrides
) -> dict:
    payload = {
        "from_location_id": from_location_id,
        "to_account_id": to_account_id,
        "asset_type_id": asset_type_id,
        "quantity": quantity,
        "expected_from_location_version": expected_from_location_version,
    }
    payload.update(overrides)
    return payload


def create_collection_request_payload(location_id, asset_ids, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "asset_ids": asset_ids,
    }
    payload.update(overrides)
    return payload


def create_repair_job_payload(
    collection_request_id, asset_ids, repair_cost_cents, **overrides
) -> dict:
    payload = {
        "collection_request_id": collection_request_id,
        "asset_ids": asset_ids,
        "repair_cost_cents": repair_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(account_id, **overrides) -> dict:
    payload = {"account_id": account_id}
    payload.update(overrides)
    return payload


def create_invoice_line_payload(kind, amount_cents, **overrides) -> dict:
    payload = {"kind": kind, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_demand_forecast_payload(
    location_id, asset_type_id, horizon_days, **overrides
) -> dict:
    payload = {
        "location_id": location_id,
        "asset_type_id": asset_type_id,
        "horizon_days": horizon_days,
    }
    payload.update(overrides)
    return payload
