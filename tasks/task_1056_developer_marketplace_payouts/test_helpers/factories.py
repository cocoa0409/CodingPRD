"""Payload factories - one per resource, input fields only."""

_SEQ = {"n": 0}


def next_ref(prefix: str = "ORD") -> str:
    """Unique storefront/network reference for a single test run."""
    _SEQ["n"] += 1
    return f"{prefix}-{_SEQ['n']}"


def create_tax_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "country_code": "US",
        "vat_rate_bps": 0,
        "marketplace_facilitator": True,
    }
    payload.update(overrides)
    return payload


def create_revenue_share_tier_payload(**overrides) -> dict:
    payload = {
        "label": "BASE",
        "min_cumulative_base_cents": 0,
        "developer_share_bps": 7000,
    }
    payload.update(overrides)
    return payload


def create_developer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Test Studios LLC",
        "email": "dev@example.test",
        "country_code": "US",
        "tax_id_provided": True,
    }
    payload.update(overrides)
    return payload


def create_app_payload(developer_id: str, **overrides) -> dict:
    payload = {
        "developer_id": developer_id,
        "name": "Test Listing",
        "category": "PRODUCTIVITY",
        "listed_countries": ["US"],
    }
    payload.update(overrides)
    return payload


def create_pricing_plan_payload(expected_app_version: int, **overrides) -> dict:
    payload = {
        "kind": "ONE_TIME",
        "price_cents": 10000,
        "currency": "USD",
        "country_code": "US",
        "effective_from": "2026-07-01T00:00:00Z",
        "effective_to": "2027-07-01T00:00:00Z",
        "expected_app_version": expected_app_version,
    }
    payload.update(overrides)
    return payload


def create_purchase_payload(app_id: str, pricing_plan_id: str, **overrides) -> dict:
    payload = {
        "app_id": app_id,
        "pricing_plan_id": pricing_plan_id,
        "buyer_country_code": "US",
        "external_order_ref": next_ref("ORD"),
        "line_items": [{"sku": "base", "unit_price_cents": 10000, "quantity": 1}],
    }
    payload.update(overrides)
    return payload


def create_refund_payload(**overrides) -> dict:
    payload = {"amount_cents": 1000, "reason": "BUYER_REQUEST"}
    payload.update(overrides)
    return payload


def create_chargeback_payload(**overrides) -> dict:
    payload = {"network_case_ref": next_ref("CB"), "amount_cents": 10000}
    payload.update(overrides)
    return payload


def create_policy_case_payload(app_id: str, **overrides) -> dict:
    payload = {"app_id": app_id, "category": "CONTENT", "severity": "MEDIUM"}
    payload.update(overrides)
    return payload


def create_payout_batch_payload(**overrides) -> dict:
    payload = {
        "payout_currency": "USD",
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_tax_form_payload(developer_id: str, **overrides) -> dict:
    payload = {"developer_id": developer_id, "tax_year": 2026}
    payload.update(overrides)
    return payload
