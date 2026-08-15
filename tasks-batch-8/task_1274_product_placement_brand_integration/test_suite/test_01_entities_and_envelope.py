"""Entity creation defaults, system-field handling, computed fields on create,
and the response envelope (PRD §2.2, §2.4, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_brand,
    assert_brief,
    assert_continuity_record,
    create_brand_payload,
    create_brief_payload,
    create_continuity_record_payload,
    create_shipment,
    get_success_data,
    is_valid_uuid,
    make_brand_rep_headers,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_brand_returns_201_with_defaults(api, admin_headers):
    """PRD §3.1: "an optional `watchlist_flag` that defaults to false and later
    feeds the clearance risk score. A brand is born `ACTIVE`."
    PRD §2.4: "The `version` is an integer that the server increments by
    exactly 1 on every mutation of the resource"

    Design: Corner/entities/create_brand_returns_201_with_defaults
    """
    resp = api.create_brand(create_brand_payload(), admin_headers)
    data = validate_success(resp, expected_status=201)
    assert_brand(data)
    assert data["watchlist_flag"] is False, "watchlist_flag default must be false"
    assert data["status"] == "ACTIVE", f"brand must be born ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"freshly minted brand must carry version 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), "id must be a non-null UUID"


def test_create_brief_missing_required_budget_rejected(api, admin_headers):
    """PRD §2.8 stage 4: "Request shape: required fields are present, types
    match, and enum values are valid (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/create_brief_missing_required_budget_rejected
    """
    brand = get_success_data(api.create_brand(create_brand_payload(), admin_headers))
    rep = make_brand_rep_headers(brand["id"])
    resp = api.create_brief(brand["id"], {"title": "No budget", "objective": "test"}, rep)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    list_resp = api.list_brand_briefs(brand["id"], rep)
    rows, meta = validate_paginated(list_resp)
    assert meta["total_count"] == 0, f"no brief may be persisted, got {meta['total_count']}"
    assert rows == [], f"no brief may be persisted, got {rows}"


def test_get_nonexistent_episode_returns_not_found(api, admin_headers):
    """PRD §2.9: "a missing resource anywhere in the chain yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_episode_returns_not_found
    """
    resp = api.get_episode(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_brand_create_system_fields_ignored_input(api, admin_headers):
    """PRD §2.4: "Every persisted resource carries an `id`, minted by the
    server as a UUID with no type prefix" and "clients never set it directly".

    Design: Corner/entities/brand_create_system_fields_ignored_input
    """
    payload = create_brand_payload()
    payload["id"] = "00000000-0000-0000-0000-000000000000"
    payload["version"] = 99
    resp = api.create_brand(payload, admin_headers)
    data = validate_success(resp, expected_status=201)
    assert data["id"] != "00000000-0000-0000-0000-000000000000", (
        "server must mint its own id, ignoring the client-supplied one"
    )
    assert data["version"] == 1, (
        f"client-supplied version 99 must be ignored; got version {data['version']}"
    )


def test_continuity_record_immutable_shape(api):
    """PRD §2.4: "a `ContinuityRecord` carries only `id` and `created_at`;
    both `updated_at` and `version` are absent from it".
    PRD §3.6: "Records are born `LOGGED` and remain so until voided by a
    return flow or a termination cascade".

    Design: Corner/entities/continuity_record_immutable_shape
    """
    ctx = setup_active_contract()
    shipment = create_shipment(ctx["contract"]["id"])
    resp = api.create_continuity_record(
        ctx["contract"]["id"],
        create_continuity_record_payload(shipment["id"]),
        # ProductionRep logs continuity records (PRD §3.6)
        TEST_USERS["production_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert_continuity_record(data)
    assert data["status"] == "LOGGED", f"record must be born LOGGED, got {data['status']}"
    assert "version" not in data, "ContinuityRecord must not carry version"
    assert "updated_at" not in data, "ContinuityRecord must not carry updated_at"
    assert "id" in data and "created_at" in data


def test_brief_remaining_budget_computed_on_create(api, admin_headers):
    """PRD §3.1: "A new brief starts in `DRAFT`, and its computed
    `remaining_budget_cents` is initialized to the full `budget_cents`."

    Design: Corner/entities/brief_remaining_budget_computed_on_create
    """
    brand = get_success_data(api.create_brand(create_brand_payload(), admin_headers))
    rep = make_brand_rep_headers(brand["id"])
    resp = api.create_brief(
        brand["id"], create_brief_payload(budget_cents=500_000), rep
    )
    data = validate_success(resp, expected_status=201)
    assert_brief(data)
    assert data["remaining_budget_cents"] == 500_000, (
        f"remaining_budget_cents must initialize to budget_cents, got {data['remaining_budget_cents']}"
    )
