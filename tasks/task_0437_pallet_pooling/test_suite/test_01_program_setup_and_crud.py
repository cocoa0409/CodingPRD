"""Program setup, entity CRUD, computed/default fields, and listing.

Translates Corner queue (B) instances from sections `entities`, `endpoints`,
and the listing-oriented validation instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_account,
    assert_location,
    assert_asset_type,
    assert_invoice_line,
    make_pool_admin_headers,
    make_pool_operator_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


def test_create_account_returns_201_with_system_fields(api):
    """PRD §3.1: "A new account starts ACTIVE with outstanding_charge_cents of 0."
    PRD §2.4: "a version, an integer that starts at the resource's creation and
    increments by one on every mutation."

    Design: Corner/entities/create_account_returns_201_with_system_fields
    """
    H.create_policy()
    resp = api.create_account(
        {"legal_name": "Acme", "role_type": "MANUFACTURER", "credit_limit_cents": 500000},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["outstanding_charge_cents"] == 0
    assert data["version"] == 1


def test_get_account_not_found_returns_404(api):
    """PRD §2.7: "The first identifier that does not resolve to an existing
    resource causes the request to be rejected with ERR_NOT_FOUND before any
    later identifier or business rule is evaluated."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_asset_missing_required_serial_returns_invalid_request(api):
    """PRD §3.2: "A pooled asset is minted by a PoolAdmin or PoolOperator with an
    asset_type_id, a serial that must be unique within that asset type ... an
    in_service_at datetime ... and a current_location_id at which it first lands."
    PRD §2.10: "request-body well-formedness — required fields present, types
    valid, enum values in range, and quantities or amounts meeting their declared
    minimums (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_asset_missing_required_serial_returns_invalid_request
    """
    ctx = H.bootstrap_program()
    resp = api.create_asset(
        {
            "asset_type_id": ctx["asset_type"]["id"],
            "in_service_at": "2026-01-01T00:00:00Z",
            "current_location_id": ctx["location"]["id"],
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_create_account_invalid_enum_role_type_returns_invalid_request(api):
    """PRD §3.1: "A PoolAdmin registers each account with a legal_name, a
    role_type (one of MANUFACTURER, DISTRIBUTOR, or RETAILER), and a
    credit_limit_cents".
    PRD §2.10: "request-body well-formedness — required fields present, types
    valid, enum values in range, and quantities or amounts meeting their declared
    minimums (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_account_invalid_enum_role_type_returns_invalid_request
    """
    H.create_policy()
    resp = api.create_account(
        {"legal_name": "Bad", "role_type": "WHOLESALER", "credit_limit_cents": 100000},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_create_asset_type_default_useful_life_days_applied(api):
    """PRD §3.1: "an optional useful_life_days (the straight-line depreciation
    horizon, defaulting to 1825 days and required to be at least 1)."

    Design: Corner/entities/create_asset_type_default_useful_life_days_applied
    """
    H.create_policy()
    resp = api.create_asset_type(
        {
            "code": "PALLET_STD",
            "name": "Std",
            "base_daily_rate_cents": 500,
            "replacement_cost_cents": 3000,
        },
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_asset_type(data)
    assert data["useful_life_days"] == 1825


def test_location_physical_and_equity_computed_zero_on_create(api):
    """PRD §3.1: "It opens with status OPEN and both physical_balance and
    equity_balance at 0."
    PRD §2.5: "The location is SHORT when its equity_balance is at or above the
    policy's equity_warn_threshold; it is SURPLUS when its equity_balance is
    strictly less than zero; otherwise it is BALANCED."

    Design: Corner/entities/location_physical_and_equity_computed_zero_on_create
    """
    H.create_policy()
    account = H.create_account()
    resp = api.create_location({"account_id": account["id"], "name": "L1"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_location(data)
    assert data["physical_balance"] == 0
    assert data["equity_balance"] == 0
    assert data["equity_status"] == "BALANCED"


def test_invoice_line_listed_under_invoice(api):
    """PRD §3.9: "Each line is created with an invoice_id (its parent invoice), a
    kind, and an amount_cents". PRD §3.9: "An invoice's lines can be listed under
    the invoice, an individual line fetched on its own".

    Design: Corner/entities/invoice_line_immutable_no_version_field
    """
    H.create_policy()
    account = H.create_account(role_type="RETAILER")
    inv = H.create_invoice(account["id"])
    H.add_invoice_line(inv["id"], "HIRE", 1234)
    resp = api.list_invoice_lines(inv["id"], OPERATOR)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 line, got {len(data)}"
    assert data[0]["amount_cents"] == 1234
    assert_invoice_line(data[0])


def test_list_locations_pagination_envelope(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping in the
    envelope's meta object, namely limit, offset, total_count, and has_more."

    Design: Corner/entities/list_locations_pagination_envelope
    """
    H.create_policy()
    account = H.create_account()
    H.create_location(account["id"], name="L1")
    H.create_location(account["id"], name="L2")
    resp = api.list_locations(OPERATOR)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2, f"expected >= 2, got {meta['total_count']}"
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"meta missing {key}"


def test_list_hires_filtered_by_account(api):
    """PRD §3.4: "Hires can be listed and filtered by account_id, location_id,
    asset_type_id, lifecycle_status, and settlement_status".

    Design: Corner/endpoints/list_hires_filtered_by_account
    """
    ctx = H.setup_open_hire()
    resp = api.list_hires(OPERATOR, params={"account_id": ctx["account"]["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 hire, got {len(data)}"
    assert data[0]["account_id"] == ctx["account"]["id"]


def test_duplicate_asset_type_code_rejected(api):
    """PRD §3.1: "The code must be unique across all asset types regardless of
    status; a duplicate code is rejected with ERR_DUPLICATE_RESOURCE."

    Design: Corner/validations/duplicate_asset_type_code_rejected
    """
    H.create_policy()
    H.create_asset_type(code="PALLET_STD")
    resp = api.create_asset_type(
        {
            "code": "PALLET_STD",
            "name": "Dup",
            "base_daily_rate_cents": 600,
            "replacement_cost_cents": 4000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, expected_status=409)


def test_asset_type_discontinued_blocks_new_asset(api):
    """PRD §3.1: "Once discontinued, no new asset may be minted of that type; an
    attempt is rejected with ERR_ASSET_TYPE_DISCONTINUED."

    Design: Corner/validations/asset_type_discontinued_blocks_new_asset
    """
    H.create_policy()
    asset_type = H.create_asset_type()
    account = H.create_account()
    location = H.create_location(account["id"])
    H.get_success_data(api.discontinue_asset_type(asset_type["id"], ADMIN))
    resp = api.create_asset(
        {
            "asset_type_id": asset_type["id"],
            "serial": "S1",
            "in_service_at": "2026-01-01T00:00:00Z",
            "current_location_id": location["id"],
        },
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_TYPE_DISCONTINUED.value, expected_status=409)
