"""Access-control claims: the authorised-role list, appraiser identity binding,
tenant isolation and the authentication rung."""
from test_helpers import (
    NO_AUTH_HEADERS,
    ApiErrorId,
    add_appraiser,
    add_cataloged_item,
    add_item,
    add_policy,
    add_room,
    bootstrap_household,
    make_appraiser_headers,
    make_limited_member,
    read_policy_version,
    request_appraisal,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}

JEWELRY_SCHEDULE = {
    "category": "JEWELRY",
    "useful_life_months": 240,
    "annual_depreciation_pct": 4.0,
    "salvage_floor_pct": 40.0,
    "blanket_sublimit_cents": 300000,
    "appraisal_scope": "JEWELRY",
    "serial_required": False,
}


def test_household_member_may_upload_evidence_but_not_schedule_coverage(api):
    """PRD 2.1: "When the headers are well-formed but the named role does not appear
    in the called endpoint's authorised-role list in §4, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 4: "| POST | `/vault/items/{item_id}/schedule` | Individually schedules the
    item on a policy, consuming scheduled allowance | Homeowner |"
    PRD 4: "| POST | `/vault/items/{item_id}/assets` | Uploads one evidence blob and
    re-derives the item's evidence tier | Homeowner, HouseholdMember |"

    Design: Corner/rbac/household_member_cannot_schedule_coverage_or_open_a_claim
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    limited = make_limited_member(ctx)
    room = add_room(ctx, name="Utility", floor_label="0")
    policy = add_policy(
        ctx, policy_number="NW-C40", scheduled_allowance_cents=1000000
    )
    item = add_item(ctx, room["id"], name="Toolbox", acquired_at="2025-01-01T00:00:00Z")
    policy_version = read_policy_version(ctx, policy["id"])

    refused = api.schedule_item(
        item["id"],
        {
            "policy_id": policy["id"],
            "scheduled_value_cents": 100000,
            "expected_policy_version": policy_version,
        },
        limited["headers"],
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    accepted = api.upload_asset(
        item["id"],
        {
            "asset_kind": "PHOTO",
            "byte_size": 5000,
            "checksum": "sha-c40",
            "captured_at": "2026-05-01T00:00:00Z",
        },
        limited["headers"],
    )
    validate_success(accepted, 201)

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["coverage_mode"] == "BLANKET"
    assert stored_item["evidence_tier"] == "PHOTO_ONLY"

    stored_policy = validate_success(api.get_policy(policy["id"], ctx["owner_headers"]))
    assert stored_policy["scheduled_consumed_cents"] == 0


def test_only_the_named_appraiser_may_certify_that_appraisal(api):
    """PRD 2.1: "Household scoping is enforced as a single check. For `Homeowner`,
    `HouseholdMember` and `EstateExecutor`, the acting `Member`'s `household_id` must
    equal the target resource's `household_id`; for `Appraiser`, `X-User-ID` must
    equal the target `Appraisal`'s `appraiser_id`."
    PRD 2.1: "Any of these failures produces `ERR_HOUSEHOLD_SCOPE_VIOLATION` (HTTP
    403)."
    PRD 3.4: "The appraiser — and only the appraiser named on the row — certifies by
    submitting an `appraised_value_cents`."
    PRD 3.4: "Hop 2, caused by hop 1, re-runs the valuation resolution on the item so
    that `effective_value_cents` and `effective_value_basis` move to the certified
    figure and `APPRAISAL`, and `valuation_state` becomes `CERTIFIED`."

    Design: Corner/rbac/appraiser_cannot_certify_an_appraisal_assigned_to_another_appraiser
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Study", floor_label="1")
    appraiser_one = add_appraiser(
        display_name="First Appraiser",
        credential_id="CRED-JW-41A",
        scope_categories=["JEWELRY"],
    )
    appraiser_two = add_appraiser(
        display_name="Second Appraiser",
        credential_id="CRED-JW-41B",
        scope_categories=["JEWELRY"],
    )
    item = add_cataloged_item(
        ctx,
        room["id"],
        300000,
        photo_bytes=5000,
        name="Jade Cameo",
        category="JEWELRY",
        acquired_at="2024-01-01T00:00:00Z",
        serial_number="JW-41",
    )
    appraisal = request_appraisal(
        ctx,
        item["id"],
        appraiser_one["id"],
        inspection_start_at="2026-05-03T09:00:00Z",
        inspection_end_at="2026-05-03T17:00:00Z",
    )
    set_clock("2026-05-04T00:00:00Z")

    refused = api.certify_appraisal(
        appraisal["id"],
        {"appraised_value_cents": 700000},
        make_appraiser_headers(appraiser_two["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_HOUSEHOLD_SCOPE_VIOLATION.value, 403)

    accepted = api.certify_appraisal(
        appraisal["id"],
        {"appraised_value_cents": 700000},
        make_appraiser_headers(appraiser_one["id"]),
    )
    certified = validate_success(accepted, 200)
    assert certified["status"] == "CERTIFIED"
    assert certified["appraised_value_cents"] == 700000

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["effective_value_basis"] == "APPRAISAL"
    assert stored_item["effective_value_cents"] == 700000


def test_a_homeowner_cannot_read_another_households_item(api):
    """PRD 2.1: "Household scoping is enforced as a single check. For `Homeowner`,
    `HouseholdMember` and `EstateExecutor`, the acting `Member`'s `household_id` must
    equal the target resource's `household_id`"
    PRD 2.8 rung 8: "**`ERR_HOUSEHOLD_SCOPE_VIOLATION` (403)** — the
    household-scoping and role-standing check described in §2.1. Applies to every
    `/vault` endpoint acted on by a role whose identity is backed by an entity."

    Design: Corner/rbac/homeowner_cannot_read_an_item_belonging_to_another_household
    """
    ctx_a = bootstrap_household(
        tier="PLUS", activate=False, clock=None, categories=[GENERAL_SCHEDULE]
    )
    room_a = add_room(ctx_a, name="Room 42A", floor_label="1")
    item_a = add_item(
        ctx_a, room_a["id"], name="Private Item", acquired_at="2025-01-01T00:00:00Z"
    )

    ctx_b = bootstrap_household(tier="PLUS", activate=False, clock=None, categories=[])

    response = api.get_item(item_a["id"], ctx_b["owner_headers"])
    validate_error(response, ApiErrorId.ERR_HOUSEHOLD_SCOPE_VIOLATION.value, 403)

    rows, meta = validate_paginated(
        api.list_items(
            ctx_b["owner_headers"], params={"household_id": ctx_b["household_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_request_with_no_auth_headers_is_unauthenticated(api):
    """PRD 2.1: "A request that omits `X-User-Role`, or whose `X-User-Role` is not
    one of the eight role names below, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401); the same error is returned when `X-User-ID` is missing or empty for any
    role other than `Anonymous`."
    PRD 2.8 rung 1: "**`ERR_UNAUTHENTICATED` (401)** — `X-User-Role` is missing or
    names no declared role, or `X-User-ID` is missing or empty for any role other
    than `Anonymous`. Applies to every endpoint."

    Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, clock=None, categories=[])

    response = api.create_room(
        {
            "household_id": ctx["household_id"],
            "name": "Ghost Room",
            "floor_label": "1",
        },
        dict(NO_AUTH_HEADERS),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    rows, meta = validate_paginated(
        api.list_rooms(
            ctx["owner_headers"], params={"household_id": ctx["household_id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
