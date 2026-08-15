"""Found-property intake, value-tier classification, and item reads (PRD §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_item,
    create_item,
    create_item_payload,
    create_location,
    create_policy,
    create_program,
    is_valid_uuid,
    make_intake_officer_headers,
    setup_program_policy_location,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_item_create_initial_state_and_recorded_officer(api, intake_officer_headers):
    """PRD §3.2: "The officer's `X-User-ID` is recorded as the item's
    `intake_officer_id`, and the new item begins life in `STORED` status with
    `unsold_count` at zero and `pending_disposal_method` unset."
    PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."

    Design: Corner/entities/item_create_success_initial_state
    """
    ctx = setup_program_policy_location()
    res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            declared_value_cents=5000),
        intake_officer_headers)
    item = validate_success(res, 201)
    assert_item(item)
    assert item["status"] == "STORED", "new item begins life in STORED status"
    assert item["unsold_count"] == 0, "unsold_count starts at zero"
    assert item.get("pending_disposal_method") is None, (
        "pending_disposal_method starts unset")
    assert item["is_identification"] is False, (
        "ELECTRONICS is not an identification category")
    assert item["intake_officer_id"] == "officer-intake-1", (
        "the officer's X-User-ID is recorded as intake_officer_id")
    assert is_valid_uuid(item["id"]), "id is server-minted UUID"
    assert item["value_tier"] == "LOW", "5000 cents is below 10,000 (LOW)"


def test_item_create_missing_category_rejected(api, intake_officer_headers):
    """PRD §2.7: "Requests that fail basic shape — a missing required field, a
    malformed value, or an enum value outside the declared set — are rejected
    with `ERR_INVALID_REQUEST` (HTTP 400) before any ordered business check runs."

    Design: Corner/entities/item_create_missing_required_category
    """
    ctx = setup_program_policy_location()
    payload = create_item_payload(ctx.program["id"], ctx.location["id"])
    del payload["category"]
    res = api.create_item(payload, intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_item_create_invalid_category_enum_rejected(api, intake_officer_headers):
    """PRD §2.7: "Requests that fail basic shape — a missing required field, a
    malformed value, or an enum value outside the declared set — are rejected
    with `ERR_INVALID_REQUEST` (HTTP 400) before any ordered business check runs."
    PRD §3.2: "The category is one of `ELECTRONICS`, `JEWELRY`, `ID_DOCUMENT`,
    `KEYS`, `CLOTHING`, `BAG`, `WALLET`, `BICYCLE`, `CASH`, or `OTHER`."

    Design: Corner/entities/item_create_invalid_enum_rejected
    """
    ctx = setup_program_policy_location()
    res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            category="ROCKET"),
        intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_item_create_ignores_client_supplied_value_tier(api, intake_officer_headers):
    """PRD §3.2: "A client may send `value_tier`, but the server ignores any
    client-sent tier and always computes its own."

    Design: Corner/entities/item_computed_value_tier_input_ignored
    """
    ctx = setup_program_policy_location(value_tier="HIGH", retention_days=90)
    res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            declared_value_cents=150000, value_tier="LOW"),
        intake_officer_headers)
    item = validate_success(res, 201)
    assert item["value_tier"] == "HIGH", (
        "150,000 cents computes HIGH; the client-sent LOW is ignored")


def test_item_get_not_found(api, intake_officer_headers):
    """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not correspond to an existing
    resource".

    Design: Corner/entities/item_get_not_found_returns_404
    """
    res = api.get_item(NON_EXISTENT_UUID, intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_item_create_without_role_header_unauthenticated(api):
    """PRD §2.1: "A missing or unrecognized role header, or a missing
    `X-User-ID` for a non-`PublicUser` role, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/item_create_missing_auth_header
    """
    payload = create_item_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                  declared_value_cents=100)
    res = api.create_item(payload, {"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_value_tier_boundary_10000_inclusive(api, intake_officer_headers):
    """PRD §3.2: "The boundaries are inclusive upward — exactly 10,000 cents is
    `MID`, exactly 100,000 cents is `HIGH`."

    Design: Corner/calculations/tier_low_mid_boundary
    """
    program = create_program("TRANSIT")
    create_policy(program["id"], value_tier="LOW", retention_days=10)
    create_policy(program["id"], value_tier="MID", retention_days=30)
    location = create_location(program["id"])

    at_boundary = validate_success(api.create_item(
        create_item_payload(program["id"], location["id"],
                            declared_value_cents=10000, description="at boundary"),
        intake_officer_headers), 201)
    one_below = validate_success(api.create_item(
        create_item_payload(program["id"], location["id"],
                            declared_value_cents=9999, description="one below"),
        intake_officer_headers), 201)
    assert at_boundary["value_tier"] == "MID", "exactly 10,000 cents is MID"
    assert one_below["value_tier"] == "LOW", "9,999 cents is below the boundary (LOW)"


def test_value_tier_boundary_100000_is_high(api, intake_officer_headers):
    """PRD §3.2: "a declared value of 100,000 cents or more is `HIGH`. The
    boundaries are inclusive upward — exactly 10,000 cents is `MID`, exactly
    100,000 cents is `HIGH`." PRD §3.2: "The server looks up the active
    retention policy matching the item's `program_id`, `category`, and computed
    `value_tier`".

    Design: Difficulty/boundary_precision_check/value_tier_boundary_inclusive
    """
    program = create_program("TRANSIT")
    create_policy(program["id"], value_tier="MID", retention_days=30)
    high_policy = create_policy(program["id"], value_tier="HIGH", retention_days=90)
    location = create_location(program["id"], supports_high_value=True)

    item = validate_success(api.create_item(
        create_item_payload(program["id"], location["id"],
                            declared_value_cents=100000, description="at boundary"),
        intake_officer_headers), 201)
    assert item["value_tier"] == "HIGH", "exactly 100,000 cents is HIGH (inclusive)"
    assert item["retention_policy_id"] == high_policy["id"], (
        "policy resolution follows the computed HIGH tier")


def test_value_tier_boundary_99999_is_mid(api, intake_officer_headers):
    """PRD §3.2: "a declared value of at least 10,000 cents but below 100,000
    cents is `MID`". PRD §3.2: "The matched policy's id is stored as
    `retention_policy_id`".

    Design: Difficulty/boundary_precision_check/value_tier_boundary_inclusive
    """
    program = create_program("TRANSIT")
    mid_policy = create_policy(program["id"], value_tier="MID", retention_days=30)
    create_policy(program["id"], value_tier="HIGH", retention_days=90)
    location = create_location(program["id"], supports_high_value=True)

    item = validate_success(api.create_item(
        create_item_payload(program["id"], location["id"],
                            declared_value_cents=99999, description="one cent below"),
        intake_officer_headers), 201)
    assert item["value_tier"] == "MID", "99,999 cents is below 100,000 (MID)"
    assert item["retention_policy_id"] == mid_policy["id"], (
        "policy resolution follows the computed MID tier")


def test_intake_without_matching_policy_rejected(api, intake_officer_headers):
    """PRD §3.2: "The server looks up the active retention policy matching the
    item's `program_id`, `category`, and computed `value_tier`; if no active
    policy exists for that triple, intake is refused with
    `ERR_NO_RETENTION_POLICY` (HTTP 422)."

    Design: Corner/errors/err_no_retention_policy_rejected
    """
    ctx = setup_program_policy_location(item_category="ELECTRONICS", value_tier="LOW")
    res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"],
                            category="KEYS", declared_value_cents=500,
                            description="key ring"),
        intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_NO_RETENTION_POLICY, expected_status=422)


def test_high_value_item_into_nonsecure_location_rejected(api, intake_officer_headers):
    """PRD §3.2: "a `HIGH`-tier item may only be placed in a location whose
    `supports_high_value` is true (`ERR_SECURE_STORAGE_REQUIRED`, HTTP 422)".

    Design: Corner/errors/err_secure_storage_required_rejected
    """
    program = create_program("TRANSIT")
    create_policy(program["id"], value_tier="HIGH", retention_days=90)
    open_shelf = create_location(program["id"], name="Open Shelf",
                                 supports_high_value=False)

    res = api.create_item(
        create_item_payload(program["id"], open_shelf["id"],
                            declared_value_cents=150000, description="laptop"),
        intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_SECURE_STORAGE_REQUIRED, expected_status=422)


def test_items_list_pagination_envelope(api, intake_officer_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return" and "The `offset` parameter specifies the number of items to skip
    and defaults to 0." PRD §2.3: "Paginated and non-paginated list-based
    responses include the following fields in the `meta` object of the response
    envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/items_list_pagination
    """
    ctx = setup_program_policy_location()
    for i in range(3):
        create_item(ctx.program["id"], ctx.location["id"],
                    declared_value_cents=5000, description=f"item {i}")

    page1, meta1 = validate_paginated(
        api.list_items(intake_officer_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2, "first page honors limit=2"
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_items(intake_officer_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1, "second page holds the remaining entry"
    assert meta2["total_count"] == 3 and meta2["has_more"] is False
