"""ServiceItem catalogue and Customer profile workflows (PRD §3.3).
"""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    assert_customer,
    assert_service_item,
    assert_version_incremented,
    create_customer_payload,
    create_service_item,
    create_service_item_payload,
    patch_service_item_payload,
    validate_error,
    validate_success,
)


def test_create_service_item_defaults_active_true(api):
    """PRD §3.3: "an `active` flag (default true)."

    Claim: a freshly created ServiceItem without explicit `active` has
    active=true.
    """
    payload = create_service_item_payload()
    payload.pop("active", None)
    res = api.create_service_item(payload, OPERATOR_HEADERS)
    body = validate_success(res, expected_status=201)
    assert_service_item(body)
    assert body["active"] is True


def test_patch_service_item_active_false_sticks(api):
    """PRD §3.3: "Operators can later patch base_price_cents, service_areas,
    or active on an existing item; an inactive item rejects new orders but
    does not affect existing ones."

    Claim: PATCHing active=false flips the persisted flag.
    """
    item = create_service_item()
    res = api.patch_service_item(
        item["id"], patch_service_item_payload(active=False), OPERATOR_HEADERS
    )
    after = validate_success(res)
    assert after["active"] is False
    assert_version_incremented(item, after)


def test_patch_service_item_with_correct_version(api):
    """PRD §2.5: "Any PATCH endpoint that mutates an entity carrying a
    version field accepts an optional version in its request body. When
    version is supplied, it must equal the entity's currently persisted
    version; a mismatch is rejected with ERR_VERSION_CONFLICT."

    Claim: PATCH with version equal to current version succeeds.
    """
    item = create_service_item()
    res = api.patch_service_item(
        item["id"],
        patch_service_item_payload(base_price_cents=15000, version=item["version"]),
        OPERATOR_HEADERS,
    )
    after = validate_success(res)
    assert after["base_price_cents"] == 15000
    assert_version_incremented(item, after)


def test_patch_service_item_version_conflict(api):
    """PRD §2.5: "a mismatch is rejected with ERR_VERSION_CONFLICT (HTTP 409)."

    Claim: PATCH with a stale version → ERR_VERSION_CONFLICT 409.
    """
    item = create_service_item()
    bad_version = item["version"] + 7
    res = api.patch_service_item(
        item["id"],
        patch_service_item_payload(base_price_cents=15000, version=bad_version),
        OPERATOR_HEADERS,
    )
    validate_error(res, "ERR_VERSION_CONFLICT", expected_status=409)


def test_create_customer_default_preferences_null(api):
    """PRD §3.3: "A null preference is treated as 'no preference' and is
    silently skipped during eligibility filtering."

    Claim: a Customer created without pref_* values stores them as null.
    """
    res = api.create_customer(create_customer_payload(), OPERATOR_HEADERS)
    body = validate_success(res, expected_status=201)
    assert_customer(body)
    assert body.get("pref_gender") is None
    assert body.get("pref_min_age") is None
    assert body.get("pref_max_age") is None
    assert body.get("pref_language") is None


def test_customer_wallet_credit_starts_zero(api):
    """PRD §3.3: "The wallet_credit_cents balance tracks the customer's
    refundable credit in integer cents; it is incremented when a cancellation
    or refund posts a credit and decremented only when redeemed against a
    future order."

    Claim: a freshly created Customer has wallet_credit_cents=0.
    """
    res = api.create_customer(create_customer_payload(), OPERATOR_HEADERS)
    body = validate_success(res, expected_status=201)
    assert body["wallet_credit_cents"] == 0


def test_list_service_items_filter_area_code(api):
    """PRD §3.3: "The catalogue listing accepts area_code and active filters."

    Claim: listing with area_code returns only items whose service_areas
    contains that code.
    """
    create_service_item(name="In-area", service_areas=["CN-11-001"])
    create_service_item(name="Out-of-area", service_areas=["CN-99-999"])
    res = api.list_service_items(
        OPERATOR_HEADERS, params={"area_code": "CN-99-999", "limit": 100}
    )
    body = res.json()
    rows = body["data"]
    if isinstance(rows, dict):
        rows = rows.get("entries", [])
    for row in rows:
        assert "CN-99-999" in row["service_areas"]
