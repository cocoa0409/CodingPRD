"""Asset registry: creation, fetch, listing, retirement, and access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_asset,
    create_asset_payload, create_work_order_payload,
    TEST_USERS, ANON_HEADERS,
)

SUP = TEST_USERS["supervisor_headers"]
DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]


def test_asset_create_returns_all_fields(api):
    """PRD §3.1: "A newly registered asset begins life in `status` `ACTIVE`."
    PRD §3.1: "`pci_score`, `condition_state`, and `last_inspection_at` are initially null, while both cost ledgers start at 0."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by one on every mutation of that resource."

    Design: Corner/entities/asset_create_returns_all_fields
    """
    payload = create_asset_payload(
        asset_class="SIGNAL", gis_segment_id="SEG-A1", location_desc="Signal 1",
        install_date="2022-01-01T00:00:00Z", replacement_value_cents=300000,
    )
    data = validate_success(api.create_asset(payload, SUP), expected_status=201)
    assert_asset(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["pci_score"] is None, f"expected null pci_score, got {data['pci_score']}"
    assert data["condition_state"] is None, f"expected null condition_state, got {data['condition_state']}"


def test_asset_get_unknown_id_returns_not_found(api):
    """PRD §2.6: "Existence — every path `id` and every foreign-key `id` in the body exists ... a miss yields the resource-specific not-found error (see §5) at HTTP 404."
    PRD §5 lists `ERR_ASSET_NOT_FOUND` at HTTP 404.

    Design: Corner/entities/asset_get_not_found_returns_404
    """
    resp = api.get_asset("00000000-0000-0000-0000-0000000000aa", SUP)
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_FOUND)


def test_asset_list_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response includes `limit`, `offset`, `total_count` (the number of records matching the filters before pagination), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/asset_list_pagination_envelope
    """
    validate_success(api.create_asset(create_asset_payload(gis_segment_id="SEG-A4"), SUP), expected_status=201)
    validate_success(api.create_asset(create_asset_payload(asset_class="SIGN", gis_segment_id="SEG-A5"), SUP), expected_status=201)
    data, meta = validate_paginated(api.list_assets(SUP, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"expected one row for limit=1, got {len(data)}"


def test_asset_retire_twice_returns_already_terminal(api):
    """PRD §2.10: "Each entity has a set of terminal states from which no further transition is allowed; attempting any action on a terminal resource returns `ERR_ALREADY_TERMINAL`."
    PRD §3.1: "attempting to retire one that is already `RETIRED` is `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/asset_retire_twice_returns_already_terminal
    """
    asset = validate_success(api.create_asset(create_asset_payload(asset_class="SIGN", gis_segment_id="SEG-A9"), SUP), expected_status=201)
    validate_success(api.retire_asset(asset["id"], SUP))
    resp = api.retire_asset(asset["id"], SUP)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_asset_retire_with_open_workorder_rejected(api):
    """PRD §3.1: "Retirement is refused if any work order in a non-terminal status (`DRAFT`, `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD`) still references the asset, in which case the request fails with `ERR_ASSET_HAS_OPEN_WORKORDER`."

    Design: Corner/validations/asset_retire_with_open_workorder_rejected
    """
    asset = validate_success(api.create_asset(create_asset_payload(gis_segment_id="SEG-B7"), SUP), expected_status=201)
    validate_success(api.create_work_order(create_work_order_payload(asset_id=asset["id"]), DISP), expected_status=201)
    resp = api.retire_asset(asset["id"], SUP)
    validate_error(resp, ApiErrorId.ERR_ASSET_HAS_OPEN_WORKORDER)


def test_inspector_cannot_create_asset(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes `POST /assets` for `Supervisor` only.

    Design: Corner/rbac/inspector_cannot_create_asset
    """
    resp = api.create_asset(create_asset_payload(gis_segment_id="SEG-C2"), INSP)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    resp = api.create_asset(create_asset_payload(gis_segment_id="SEG-B5"), ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
