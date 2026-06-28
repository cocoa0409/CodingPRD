"""Entity creation, defaults, system fields, input validation, and listing.

Covers corner queue B section: entities.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_active_catalog, setup_active_pledge, create_campaign, create_pledge,
    assert_campaign, assert_seller, assert_pledge,
    MISSING_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]


def test_create_campaign_returns_201_with_defaults(api, admin_headers):
    """PRD §3.1: "A campaign comes to life in `DRAFT` posture with `version` 1
    and all of its computed money fields — `gross_collected_cents`,
    `forecast_gross_cents`, `school_profit_cents`, and `vendor_payable_cents`
    — sitting at zero, and `reconciled_at` null."

    Design: Corner/entities/create_campaign_returns_201_with_all_fields_and_defaults
    """
    res = api.create_campaign({
        "name": "C", "campaign_type": "CATALOG", "goal_cents": 100000,
        "profit_split_pct": 0.50, "vendor_name": "V",
        "starts_at": "2026-04-01T00:00:00Z", "ends_at": "2026-05-01T00:00:00Z",
    }, admin_headers)
    camp = validate_success(res, 201)
    assert_campaign(camp)
    assert camp["posture"] == "DRAFT"
    assert camp["version"] == 1
    assert camp["gross_collected_cents"] == 0
    assert camp["forecast_gross_cents"] == 0
    assert camp["school_profit_cents"] == 0
    assert camp["vendor_payable_cents"] == 0
    assert camp["reconciled_at"] is None


def test_get_nonexistent_campaign_returns_not_found(api, admin_headers):
    """PRD §2.6: "Existence of path resources is checked third: when a campaign,
    order, pledge, seller, product, shift, volunteer, prize-tier, or
    disbursement named in the URL path does not exist, the request is rejected
    with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_campaign_nonexistent_returns_not_found
    """
    res = api.get_campaign(MISSING_UUID, admin_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_campaign_missing_required_field_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "A create or update request must present a well-formed body or
    be rejected with `ERR_INVALID_REQUEST` (HTTP 422). All required fields
    must be present, every enumerated field must carry a legal value, and
    every cents-denominated amount must be non-negative."

    Design: Corner/entities/create_campaign_missing_required_field_returns_invalid_request
    """
    res = api.create_campaign({
        "name": "C", "goal_cents": 100000, "profit_split_pct": 0.50,
        "vendor_name": "V", "starts_at": "2026-04-01T00:00:00Z",
        "ends_at": "2026-05-01T00:00:00Z",
    }, admin_headers)  # campaign_type omitted
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_campaign_ends_before_starts_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "its `ends_at` must be strictly after its `starts_at`."

    Design: Corner/entities/create_campaign_ends_before_starts_returns_invalid_request
    """
    res = api.create_campaign({
        "name": "C", "campaign_type": "CATALOG", "goal_cents": 100000,
        "profit_split_pct": 0.50, "vendor_name": "V",
        "starts_at": "2026-05-01T00:00:00Z", "ends_at": "2026-04-01T00:00:00Z",
    }, admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_campaign_profit_split_out_of_range_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "its `profit_split_pct` must be greater than 0 and at most 1,
    expressed to two decimal places"

    Design: Corner/entities/create_campaign_profit_split_out_of_range_returns_invalid_request
    """
    res = api.create_campaign({
        "name": "C", "campaign_type": "CATALOG", "goal_cents": 100000,
        "profit_split_pct": 0, "vendor_name": "V",
        "starts_at": "2026-04-01T00:00:00Z", "ends_at": "2026-05-01T00:00:00Z",
    }, admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_order_empty_lines_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "An order's `lines` array must be non-empty, and every line's
    quantity must be at least 1."

    Design: Corner/entities/create_order_empty_lines_returns_invalid_request
    """
    camp, seller, product = setup_active_catalog()
    res = api.create_order({
        "campaign_id": camp["id"], "seller_id": seller["id"],
        "buyer_name": "B", "buyer_email": "b@x.com", "lines": [],
    }, admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_pledge_default_flat_and_cap_applied_when_omitted(api, admin_headers):
    """PRD §3.5: "an optional `flat_cents` flat amount that defaults to 0, and an
    optional `cap_cents` ceiling that defaults to 0."

    PRD §3.5: "At creation, with `units_recorded` at 0, this evaluates to the
    flat amount (capped if a cap applies)."

    Design: Corner/entities/pledge_default_flat_and_cap_applied_when_omitted
    """
    camp, seller = setup_active_pledge()
    pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=100)
    assert pledge["flat_cents"] == 0
    assert pledge["cap_cents"] == 0
    assert pledge["pledged_amount_cents"] == 0


def test_system_fields_minted_on_seller_create(api, admin_headers):
    """PRD §3.3: "On creation the server mints an opaque `share_slug` — a
    sharing-link token guaranteed unique across all sellers in the system —
    and the seller starts in `ACTIVE` status."

    Design: Corner/entities/system_fields_minted_and_input_ignored_on_seller_create
    """
    camp = create_campaign(campaign_type="CATALOG")
    res = api.create_seller({
        "campaign_id": camp["id"], "display_name": "S", "guardian_email": "g@x.com",
    }, admin_headers)
    seller = validate_success(res, 201)
    assert_seller(seller)
    assert seller["status"] == "ACTIVE"
    assert isinstance(seller["share_slug"], str) and len(seller["share_slug"]) > 0


def test_pledge_cap_clamps_amount(api, admin_headers):
    """PRD §3.5: "otherwise `pledged_amount_cents` is the lesser of the raw
    amount and `cap_cents` — the cap is applied only after the
    flat-plus-per-unit sum, never to either term in isolation."

    Design: Corner/entities/pledge_cap_clamps_amount
    """
    camp, seller = setup_active_pledge()
    pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=250,
                           flat_cents=1000, cap_cents=5000)
    recorded = validate_success(
        api.record_pledge(pledge["id"], {"units_recorded": 30}, admin_headers), 200)
    # raw = 1000 + 250*30 = 8500; clamps to cap 5000.
    assert recorded["pledged_amount_cents"] == 5000, \
        f"raw 8500 must clamp to cap 5000, got {recorded['pledged_amount_cents']}"


def test_list_campaigns_pagination_envelope(api, admin_headers, school_official_headers):
    """PRD §2.3: "Each list response includes four pagination fields inside the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_campaigns_pagination_envelope
    """
    create_campaign(campaign_type="CATALOG", name="C1")
    create_campaign(campaign_type="PLEDGE", name="C2", profit_split_pct=1.0)
    data, meta = validate_paginated(
        api.list_campaigns(school_official_headers, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
