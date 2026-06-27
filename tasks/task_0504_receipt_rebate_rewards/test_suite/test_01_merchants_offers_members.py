"""Merchant / Offer / Member creation, defaults, validation, and listing.

Translates corner-design instances from the `entities` and `state_machines`
(initial-state) sections, plus a pagination-bounds validation.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, TEST_USERS, make_member_headers,
    ApiErrorId, NON_EXISTENT_UUID,
    create_merchant_payload, create_offer_payload, create_member_payload,
    create_clickthrough_payload, create_reward_claim_payload,
    assert_merchant, assert_member, assert_clickthrough, assert_reward_claim,
)

_PA = TEST_USERS["platform_admin_headers"]


def test_create_merchant_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created merchant has `status` `ACTIVE`."
    PRD §3.1: "it must be at least 1 and defaults to 168 (one week)."
    PRD §3.1: "The `double_dip_allowed` flag defaults to false".

    Design: Corner/entities/create_merchant_returns_201_with_all_fields
    """
    resp = api.create_merchant(
        create_merchant_payload(name="Acme", online_rate_bps=500, instore_rate_bps=200), _PA)
    data = validate_success(resp, expected_status=201)
    assert_merchant(data)
    assert data["status"] == "ACTIVE"
    assert data["online_rate_bps"] == 500
    assert data["attribution_window_hours"] == 168
    assert data["double_dip_allowed"] is False


def test_get_merchant_not_found(api):
    """PRD §2.9: "the first missing one yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_merchant_not_found_returns_404
    """
    resp = api.get_merchant(NON_EXISTENT_UUID, _PA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_merchant_missing_required_field(api):
    """PRD §2.11: "body well-formedness is checked - required fields present ...
    yielding `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "A `PlatformAdmin` creates a merchant by supplying its `name`, its
    `online_rate_bps` ... and its `instore_rate_bps`".

    Design: Corner/entities/create_merchant_missing_required_field_returns_validation
    """
    resp = api.create_merchant({"name": "Acme", "instore_rate_bps": 200}, _PA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_list_merchants_pagination_envelope(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` block, where `total_count` is the number of matching
    records before pagination and `has_more` is true when records remain beyond
    the current page."

    Design: Corner/entities/list_merchants_pagination_envelope
    """
    validate_success(api.create_merchant(
        create_merchant_payload(name="A", online_rate_bps=100, instore_rate_bps=100), _PA), 201)
    validate_success(api.create_merchant(
        create_merchant_payload(name="B", online_rate_bps=200, instore_rate_bps=200), _PA), 201)
    resp = api.list_merchants(_PA, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "expected has_more true with limit=1 over 2 records"


def test_reward_claim_amount_is_computed_not_client_input(api):
    """PRD §3.3: "Finally, `amount_cents` is `purchase_amount_cents` multiplied by
    the capped rate in basis points, divided by 10,000, with the result floored to
    whole cents."
    PRD §3.3: "The created claim is fixed to `ONLINE` attribution".

    Design: Corner/entities/reward_claim_amount_is_computed_input_ignored
    """
    merchant = validate_success(api.create_merchant(
        create_merchant_payload(online_rate_bps=1000, instore_rate_bps=200), _PA), 201)
    member = validate_success(api.create_member(create_member_payload("ci@x.com"), _PA), 201)
    hdr = make_member_headers(member["id"])
    click = validate_success(api.create_clickthrough(
        create_clickthrough_payload(member["id"], merchant["id"]), hdr), 201)
    claim = validate_success(api.create_reward_claim(
        create_reward_claim_payload(member["id"], merchant["id"], click["id"], 5000), hdr), 201)
    assert claim["amount_cents"] == 500, f"5000 @ 1000bps must be 500, got {claim['amount_cents']}"
    assert claim["attribution"] == "ONLINE"


def test_clickthrough_is_append_only_no_version(api):
    """PRD §2.4: "Three entity types are append-only and therefore carry **only**
    `id` and `created_at` - they have neither an `updated_at` nor a `version`.
    These are the `ClickThrough` (an affiliate-click event), the `LedgerEntry`
    (an audit-log line), and the `ReturnEvent` (a reported return)."

    Design: Corner/entities/clickthrough_immutable_no_version_field
    """
    merchant = validate_success(api.create_merchant(create_merchant_payload(), _PA), 201)
    member = validate_success(api.create_member(create_member_payload("cc@x.com"), _PA), 201)
    hdr = make_member_headers(member["id"])
    resp = api.create_clickthrough(create_clickthrough_payload(member["id"], merchant["id"]), hdr)
    click = validate_success(resp, expected_status=201)
    assert_clickthrough(click)
    assert "version" not in click, "ClickThrough must not carry a version field"
    assert "updated_at" not in click, "ClickThrough must not carry an updated_at field"


def test_create_offer_invalid_enum_offer_type(api):
    """PRD §2.11: "body well-formedness is checked - required fields present, enum
    values valid, and integers non-negative where constrained - yielding
    `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "its `offer_type` is one of two kinds. A `LINKED` offer ... A
    `RECEIPT_REBATE` offer".

    Design: Corner/entities/create_offer_invalid_enum_offer_type_returns_validation
    """
    merchant = validate_success(api.create_merchant(create_merchant_payload(), _PA), 201)
    resp = api.create_offer(
        create_offer_payload(merchant["id"], "FOO"), _PA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_offer_unknown_merchant_reference_not_found(api):
    """PRD §2.9: "Foreign keys supplied in a request body - namely `merchant_id`,
    `offer_id`, `member_id`, `reward_claim_id`, `click_through_id`, and
    `receipt_scan_id` - must resolve to existing rows; an unresolvable body
    reference yields `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

    Design: Corner/entities/create_offer_unknown_merchant_returns_reference_not_found
    """
    resp = api.create_offer(create_offer_payload(NON_EXISTENT_UUID, "LINKED"), _PA)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_new_member_initial_states(api):
    """PRD §3.2: "A new member starts with `account_status` `ACTIVE`,
    `verification_status` `UNVERIFIED`, and all wallet balances at zero."

    Design: Corner/state_machines/new_member_initial_states
    """
    resp = api.create_member(create_member_payload("si@x.com"), _PA)
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["account_status"] == "ACTIVE"
    assert data["verification_status"] == "UNVERIFIED"
    assert data["pending_balance_cents"] == 0


def test_pagination_limit_out_of_bounds(api):
    """PRD §2.3: "A `limit` outside the inclusive range 1 through 100, or a negative
    `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_bounds_returns_400
    """
    resp = api.list_merchants(_PA, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION)
