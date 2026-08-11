"""Validation-rung claims: serial rules, quantity bounds, share windows, the
estate-plan guards, the allowance floor, storage quotas, the package entitlement,
the restricted gate, enum routing and the claim-line evidence bar."""
from test_helpers import (
    ApiErrorId,
    add_appraiser,
    add_asset,
    add_cataloged_item,
    add_estate_plan,
    add_generated_package,
    add_item,
    add_member_to_household,
    add_package,
    add_policy,
    add_room,
    allocate,
    add_claim_line,
    bootstrap_household,
    make_estate_executor_headers,
    make_insurance_agent_headers,
    open_claim,
    propose_plan,
    read_household_version,
    read_policy_version,
    read_subscription_version,
    register_owner,
    make_homeowner_headers,
    schedule_item,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

AGENT_HEADERS = make_insurance_agent_headers()

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}

ELECTRONICS_SCHEDULE = {
    "category": "ELECTRONICS",
    "useful_life_months": 60,
    "annual_depreciation_pct": 20.0,
    "salvage_floor_pct": 10.0,
    "blanket_sublimit_cents": 500000,
    "appraisal_scope": "ELECTRONICS",
    "serial_required": True,
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


def test_serial_number_uniqueness_is_scoped_to_the_household(api):
    """PRD 3.3: "And a `serial_number` must be unique within the household among
    items whose `lifecycle_state` is `DRAFT`, `CATALOGED` or `FROZEN`; a collision
    fails with `ERR_DUPLICATE_SERIAL`."
    PRD 2.8 rung 23: "**`ERR_DUPLICATE_SERIAL` (409)** — another item in the same
    household already carries this `serial_number` and its `lifecycle_state` is
    `DRAFT`, `CATALOGED` or `FROZEN`. Applies to item creation, item patch and item
    replacement."

    Design: Corner/validations/duplicate_serial_number_within_a_household_is_rejected
    """
    ctx_a = bootstrap_household(
        tier="PLUS", activate=False, clock=None, categories=[GENERAL_SCHEDULE]
    )
    room_a = add_room(ctx_a, name="Room 26A", floor_label="1")
    add_item(
        ctx_a,
        room_a["id"],
        name="Original",
        acquired_at="2025-01-01T00:00:00Z",
        serial_number="GN-DUP",
    )

    ctx_b = bootstrap_household(tier="PLUS", activate=False, clock=None, categories=[])
    room_b = add_room(ctx_b, name="Room 26B", floor_label="1")

    collision = api.create_item(
        {
            "household_id": ctx_a["household_id"],
            "room_id": room_a["id"],
            "name": "Clone",
            "category": "GENERAL",
            "acquired_at": "2025-01-02T00:00:00Z",
            "serial_number": "GN-DUP",
        },
        ctx_a["owner_headers"],
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_SERIAL.value, 409)

    other_household = api.create_item(
        {
            "household_id": ctx_b["household_id"],
            "room_id": room_b["id"],
            "name": "Other House Same Serial",
            "category": "GENERAL",
            "acquired_at": "2025-01-03T00:00:00Z",
            "serial_number": "GN-DUP",
        },
        ctx_b["owner_headers"],
    )
    accepted = validate_success(other_household, 201)
    assert accepted["serial_number"] == "GN-DUP"

    household_a = validate_success(
        api.get_household(ctx_a["household_id"], ctx_a["owner_headers"])
    )
    assert household_a["item_count"] == 1


def test_a_serial_required_category_refuses_an_item_without_a_serial(api):
    """PRD 3.3: "When the category schedule governing the submitted `category` has
    `serial_required` true and no `serial_number` is supplied, the request fails with
    `ERR_SERIAL_REQUIRED`."
    PRD 2.8 rung 22: "**`ERR_SERIAL_REQUIRED` (422)** — the `CategorySchedule` for
    the submitted `category` has `serial_required` true and the submitted
    `serial_number` is null or empty. Applies to item creation, item patch and item
    replacement."

    Design: Corner/validations/missing_serial_for_a_serial_required_category_is_rejected
    """
    ctx = bootstrap_household(
        tier="PLUS",
        activate=False,
        clock=None,
        categories=[ELECTRONICS_SCHEDULE, GENERAL_SCHEDULE],
    )
    room = add_room(ctx, name="Office", floor_label="1")

    refused = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "Nameless Laptop",
            "category": "ELECTRONICS",
            "acquired_at": "2025-01-01T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SERIAL_REQUIRED.value, 422)

    accepted = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "Plain Box",
            "category": "GENERAL",
            "acquired_at": "2025-01-01T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    item = validate_success(accepted, 201)
    assert item["serial_number"] is None

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["item_count"] == 1


def test_item_quantity_zero_is_refused_and_the_maximum_is_accepted(api):
    """PRD 2.6: "Item quantities are bounded: `MIN_ITEM_QUANTITY` is 1 and
    `MAX_ITEM_QUANTITY` is 999, so an item's `quantity` must be at least 1 and at
    most 999."
    PRD 2.8 rung 24: "**`ERR_INVALID_QUANTITY` (422)** — an item `quantity` outside 1
    through 999 inclusive, an allocation `quantity` below 1, or a `claimed_quantity`
    outside 1 through the item's `quantity` inclusive."

    Design: Corner/validations/item_quantity_zero_is_rejected_and_999_is_accepted
    """
    ctx = bootstrap_household(
        tier="PLUS", activate=False, clock=None, categories=[GENERAL_SCHEDULE]
    )
    room = add_room(ctx, name="Shed", floor_label="0")

    refused = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "Zero Box",
            "category": "GENERAL",
            "acquired_at": "2025-01-01T00:00:00Z",
            "quantity": 0,
        },
        ctx["owner_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_QUANTITY.value, 422)

    accepted = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "Max Box",
            "category": "GENERAL",
            "acquired_at": "2025-01-01T00:00:00Z",
            "quantity": 999,
        },
        ctx["owner_headers"],
    )
    item = validate_success(accepted, 201)
    assert item["quantity"] == 999

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["item_count"] == 1


def test_share_window_of_exactly_ninety_days_is_accepted_and_ninety_one_is_not(api):
    """PRD 3.9: "Second, the window's length, `expires_at` minus `starts_at`, must
    not be strictly greater than the 90-day maximum share duration, or the request is
    refused with `ERR_SHARE_WINDOW_TOO_LONG`; a window of exactly 90 days is
    accepted."

    Design: Corner/validations/share_window_of_exactly_ninety_days_is_accepted_and_ninety_one_is_rejected
    """
    ctx = bootstrap_household(tier="PLUS", activate=False)

    accepted = api.create_share_grant(
        {
            "household_id": ctx["household_id"],
            "scope_kind": "HOUSEHOLD",
            "recipient_ref": "ninety@carrier.example",
            "redaction_level": "VALUES_HIDDEN",
            "starts_at": "2026-05-01T00:00:00Z",
            "expires_at": "2026-07-30T00:00:00Z",
            "access_cap": 3,
        },
        ctx["owner_headers"],
    )
    grant = validate_success(accepted, 201)
    assert grant["status"] == "ACTIVE"
    assert grant["access_cap"] == 3

    refused = api.create_share_grant(
        {
            "household_id": ctx["household_id"],
            "scope_kind": "HOUSEHOLD",
            "recipient_ref": "ninetyone@carrier.example",
            "redaction_level": "VALUES_HIDDEN",
            "starts_at": "2026-05-01T00:00:00Z",
            "expires_at": "2026-07-31T00:00:00Z",
            "access_cap": 3,
        },
        ctx["owner_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SHARE_WINDOW_TOO_LONG.value, 422)

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 1


def test_plan_proposal_and_executor_self_approval_are_both_refused(api):
    """PRD 3.8: "It requires `unallocated_item_count` to be exactly 0, meaning every
    unit of every `CATALOGED` item is allocated, or it is refused with
    `ERR_PLAN_NOT_FULLY_ALLOCATED`"
    PRD 3.8: "the caller's `X-User-ID` must not equal the plan's
    `executor_member_id`, because the executor may never approve their own plan, and
    a violation is refused with `ERR_SEGREGATION_OF_DUTIES`"
    PRD 3.8: "Approval moves the plan `PROPOSED → APPROVED`, stamps `approved_at` and
    writes `approved_by_member_id` from `X-User-ID`."

    The executor-self-approval leg accepts either 403 the PRD leaves open: the
    executor member's `member_role` is EXECUTOR rather than OWNER, and PRD 2.1's
    rung-8 clause "Operations reserved to the homeowner additionally require the
    acting member's `member_role` to be `OWNER`" never enumerates which operations
    those are, so a faithful reader may report either rung.

    Design: Corner/validations/propose_with_unallocated_items_and_approve_by_the_executor_are_both_refused
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    executor = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "EXECUTOR", full_name="Exec 30"
    )
    heir = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "HEIR", full_name="Heir 30"
    )
    executor_headers = make_estate_executor_headers(executor["id"])
    room = add_room(ctx, name="Parlour", floor_label="1")
    item_one = add_cataloged_item(
        ctx, room["id"], 100000, photo_bytes=5000, name="Vase A",
        acquired_at="2024-01-01T00:00:00Z", quantity=1,
    )
    item_two = add_cataloged_item(
        ctx, room["id"], 100000, photo_bytes=5000, name="Vase B",
        acquired_at="2024-01-02T00:00:00Z", quantity=1,
    )
    plan = add_estate_plan(ctx, executor["id"], valuation_mode="GROSS")
    allocate(plan["id"], executor_headers, item_one["id"], "KEEP", 1, heir_member_id=heir["id"])

    premature = api.propose_plan(plan["id"], {}, executor_headers)
    validate_error(premature, ApiErrorId.ERR_PLAN_NOT_FULLY_ALLOCATED.value, 422)

    allocate(plan["id"], executor_headers, item_two["id"], "KEEP", 1, heir_member_id=heir["id"])
    proposed = propose_plan(plan["id"], executor_headers)
    assert proposed["unallocated_item_count"] == 0
    assert proposed["status"] == "PROPOSED"
    assert proposed["balanced"] is True

    self_approval = api.approve_plan(
        plan["id"], {}, make_homeowner_headers(executor["id"])
    )
    error_id = validate_error_is_one_of(
        self_approval,
        [
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            ApiErrorId.ERR_HOUSEHOLD_SCOPE_VIOLATION.value,
        ],
    )
    assert self_approval.status_code == 403, (
        f"the executor's own approval must be refused with 403, got "
        f"{self_approval.status_code} / {error_id}"
    )

    approved = validate_success(api.approve_plan(plan["id"], {}, ctx["owner_headers"]))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_member_id"] == ctx["owner_id"]


def test_policy_allowance_cannot_be_patched_below_the_consumed_total(api):
    """PRD 3.5: "A patch that would set `scheduled_allowance_cents` strictly below
    the policy's current `scheduled_consumed_cents` is refused with
    `ERR_ALLOWANCE_BELOW_CONSUMED` — individually every existing rider is fine, but
    collectively they no longer fit. Any accepted patch recomputes
    `scheduled_remaining_cents` and `coverage_gap_cents`."

    Design: Corner/validations/policy_allowance_cannot_be_patched_below_the_consumed_total
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Studio", floor_label="1")
    policy = add_policy(
        ctx,
        policy_number="NW-C31",
        deductible_cents=50000,
        scheduled_allowance_cents=1000000,
    )
    item = add_cataloged_item(
        ctx, room["id"], 700000, photo_bytes=5000, name="Sculpture",
        acquired_at="2024-01-01T00:00:00Z",
    )
    schedule_item(ctx, item["id"], policy["id"], 600000)

    refused = api.patch_policy(
        policy["id"], {"scheduled_allowance_cents": 500000}, AGENT_HEADERS
    )
    validate_error(refused, ApiErrorId.ERR_ALLOWANCE_BELOW_CONSUMED.value, 409)

    accepted = api.patch_policy(
        policy["id"], {"scheduled_allowance_cents": 600000}, AGENT_HEADERS
    )
    patched = validate_success(accepted, 200)
    assert patched["scheduled_allowance_cents"] == 600000
    assert patched["scheduled_consumed_cents"] == 600000
    assert patched["scheduled_remaining_cents"] == 0


def test_asset_upload_past_the_tier_byte_allowance_is_refused(api):
    """PRD 3.2: "an asset upload is refused when asset usage plus one would exceed
    the asset allowance or when byte usage plus the new `byte_size` would exceed the
    byte allowance — all with `ERR_QUOTA_EXCEEDED`."
    PRD 3.2: "`BASIC` costs 900 cents a month and allows 50 items, 200 stored assets,
    2,000,000,000 stored bytes, 1 household, 0 included appraisal credits and 1
    documentation package per period; its tier rank is 1."

    Design: Corner/validations/asset_upload_beyond_the_tier_byte_quota_is_rejected
    """
    ctx = bootstrap_household(
        tier="BASIC", activate=False, clock=None, categories=[GENERAL_SCHEDULE]
    )
    room = add_room(ctx, name="Loft", floor_label="3")
    item = add_item(
        ctx, room["id"], name="Big Media Item", acquired_at="2025-01-01T00:00:00Z"
    )

    refused = api.upload_asset(
        item["id"],
        {
            "asset_kind": "PHOTO",
            "byte_size": 2000000001,
            "checksum": "sha-too-big",
            "captured_at": "2026-05-01T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_QUOTA_EXCEEDED.value, 402)

    accepted = api.upload_asset(
        item["id"],
        {
            "asset_kind": "PHOTO",
            "byte_size": 2000000000,
            "checksum": "sha-exact",
            "captured_at": "2026-05-01T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_success(accepted, 201)

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["asset_bytes_used"] == 2000000000
    assert household["asset_count"] == 1

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["evidence_tier"] == "PHOTO_ONLY"


def test_tier_downgrade_is_refused_while_stored_bytes_exceed_the_target(api):
    """PRD 3.2: "Changing to a tier whose item, asset or byte allowance is strictly
    below the household's current usage is rejected with
    `ERR_DOWNGRADE_BLOCKED_BY_USAGE`."
    PRD 2.8 rung 33: "**`ERR_DOWNGRADE_BLOCKED_BY_USAGE` (409)** — the target tier's
    `max_items`, `max_assets` or `max_asset_bytes` is strictly less than the
    household's current usage. Applies to tier change and to reinstatement."

    Design: Corner/validations/tier_downgrade_is_refused_while_stored_bytes_exceed_the_target_tier
    """
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Archive", floor_label="0")
    item = add_item(
        ctx, room["id"], name="Scan Bundle", acquired_at="2025-01-01T00:00:00Z"
    )
    add_asset(
        ctx, item["id"], asset_kind="PHOTO", byte_size=2500000000, checksum="sha-c33"
    )

    response = api.change_tier(
        ctx["subscription_id"],
        {
            "tier": "BASIC",
            "proration_mode": "DAILY",
            "expected_subscription_version": read_subscription_version(ctx),
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DOWNGRADE_BLOCKED_BY_USAGE.value, 409)

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["tier"] == "PLUS"
    assert subscription["monthly_fee_cents"] == 2900
    assert subscription["last_proration_charge_cents"] == 0

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["asset_bytes_used"] == 2500000000


def test_second_generation_in_a_period_exhausts_the_basic_package_entitlement(api):
    """PRD 3.6: "`packages_used_this_period` must still be below the tier's included
    package allowance, or the request is refused with `ERR_PACKAGE_QUOTA_EXCEEDED`"
    PRD 3.6: "Where hop 2 finds no delivered predecessor, hops 3 and 4 do not fire at
    all. Finally `packages_used_this_period` rises by one."

    Design: Corner/validations/second_package_generation_in_a_period_exhausts_the_basic_entitlement
    """
    ctx = bootstrap_household(tier="BASIC", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Nook", floor_label="1")
    add_cataloged_item(
        ctx, room["id"], 120000, photo_bytes=5000, name="Clock",
        acquired_at="2025-01-01T00:00:00Z",
    )
    policy = add_policy(ctx, policy_number="NW-C34")
    package_one = add_generated_package(ctx, policy["id"])
    package_two = add_package(ctx, policy["id"])

    response = api.generate_package(
        package_two["id"],
        {"expected_household_version": read_household_version(ctx)},
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PACKAGE_QUOTA_EXCEEDED.value, 402)

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["packages_used_this_period"] == 1

    first = validate_success(api.get_package(package_one["id"], ctx["owner_headers"]))
    assert first["status"] == "GENERATED"

    second = validate_success(api.get_package(package_two["id"], ctx["owner_headers"]))
    assert second["status"] == "DRAFT"
    assert second["line_count"] == 0


def test_restricted_household_blocks_generation_but_not_item_edits(api):
    """PRD 2.7: "While a household is `RESTRICTED` — that is, its subscription
    `refresh_state` is `OVERDUE` and its `status` is neither `LAPSED` nor `CLOSED` —
    exactly two endpoints are blocked with `ERR_REFRESH_OVERDUE` (HTTP 403) at ladder
    rung 11"
    PRD 2.7: "Every other write passes. A restricted household can still catalogue
    items, upload assets, declare values, schedule coverage, request appraisals, open
    and run claims, and build estate plans; it simply may not mint fresh evidence
    packages or fresh share links until someone attests the annual refresh."

    Design: Corner/validations/refresh_overdue_restricts_package_generation_but_leaves_item_edits_open
    """
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Snug", floor_label="1")
    item = add_cataloged_item(
        ctx, room["id"], 90000, photo_bytes=5000, name="Side Table",
        acquired_at="2025-01-01T00:00:00Z",
    )
    policy = add_policy(ctx, policy_number="NW-C35")
    package = add_package(ctx, policy["id"])

    set_clock("2027-06-01T00:00:00Z")

    blocked = api.generate_package(
        package["id"],
        {"expected_household_version": read_household_version(ctx)},
        ctx["owner_headers"],
    )
    validate_error(blocked, ApiErrorId.ERR_REFRESH_OVERDUE.value, 403)

    patched = validate_success(
        api.patch_item(item["id"], {"name": "Side Table Renamed"}, ctx["owner_headers"]),
        200,
    )
    assert patched["name"] == "Side Table Renamed"

    attested = validate_success(
        api.attest_refresh(
            ctx["subscription_id"],
            {"attestation_note": "walkthrough complete"},
            ctx["owner_headers"],
        )
    )
    assert attested["refresh_state"] == "CURRENT"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "OPEN"

    generated = validate_success(
        api.generate_package(
            package["id"],
            {"expected_household_version": household["version"]},
            ctx["owner_headers"],
        ),
        200,
    )
    assert generated["status"] == "GENERATED"
    assert generated["line_count"] == 1


def test_an_unknown_enum_member_routes_to_the_enum_rung(api):
    """PRD 2.8 rung 4: "**`ERR_INVALID_ENUM` (422)** — a value outside the declared
    member set of an enum-valued field. This rung is a **closed iff-list**. Exactly
    these fields route here: `Member.member_role`, `Subscription.tier`,
    `Item.category`, `Asset.asset_kind`, `CategorySchedule.category`,
    `CategorySchedule.appraisal_scope`, each member of `Appraiser.scope_categories`,
    `Appraisal.void_reason`, `LossClaim.peril`, `LossClaim.settlement_basis`,
    `LossClaim.deductible_mode`, `ClaimLine.denial_reason`,
    `EstatePlan.valuation_mode`, `Allocation.disposition`, `ShareGrant.scope_kind`,
    `ShareGrant.redaction_level`, the billing event's `outcome`, the adjudication's
    `decision`, the tier change's `proration_mode`, and the coverage-gap read's
    `basis`."

    Design: Corner/validations/unknown_enum_member_routes_to_invalid_enum_not_invalid_request
    """
    ctx = bootstrap_household(
        tier="PLUS", activate=False, clock=None, categories=[GENERAL_SCHEDULE]
    )
    room = add_room(ctx, name="Hangar", floor_label="0")

    response = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "Rocket",
            "category": "SPACESHIP",
            "acquired_at": "2025-01-01T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["item_count"] == 0


def test_an_appraiser_linked_to_the_declaring_member_cannot_be_engaged(api):
    """PRD 3.4: "The appraiser's `linked_member_id` must not equal the item's
    `declared_by_member_id` — the party who declared a value may not be the party who
    certifies it — or the request fails with `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.4: "Finally the subscription must have at least one credit:
    `appraisal_credits_remaining` is decremented by one and the appraisal's
    `credit_consumed` is set true"

    Design: Corner/validations/appraiser_linked_to_the_declaring_member_cannot_appraise_that_item
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Boudoir", floor_label="2")
    linked = add_appraiser(
        display_name="Linked Lou",
        credential_id="CRED-JW-37L",
        scope_categories=["JEWELRY"],
        linked_member_id=ctx["owner_id"],
    )
    unlinked = add_appraiser(
        display_name="Unlinked Uma",
        credential_id="CRED-JW-37U",
        scope_categories=["JEWELRY"],
    )
    item = add_cataloged_item(
        ctx,
        room["id"],
        400000,
        photo_bytes=5000,
        name="Amber Cuff",
        category="JEWELRY",
        acquired_at="2024-01-01T00:00:00Z",
        serial_number="JW-37",
    )

    refused = api.create_appraisal(
        {
            "item_id": item["id"],
            "appraiser_id": linked["id"],
            "inspection_start_at": "2026-06-20T09:00:00Z",
            "inspection_end_at": "2026-06-20T17:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    accepted = api.create_appraisal(
        {
            "item_id": item["id"],
            "appraiser_id": unlinked["id"],
            "inspection_start_at": "2026-06-20T09:00:00Z",
            "inspection_end_at": "2026-06-20T17:00:00Z",
        },
        ctx["owner_headers"],
    )
    appraisal = validate_success(accepted, 201)
    assert appraisal["status"] == "REQUESTED"
    assert appraisal["credit_consumed"] is True

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["declared_by_member_id"] == ctx["owner_id"]

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["appraisal_credits_remaining"] == 1


def test_a_second_claim_line_for_the_same_item_is_refused(api):
    """PRD 3.7: "and at most one line may exist per item per claim, a second attempt
    being refused with `ERR_DUPLICATE_CLAIM_LINE`."
    PRD 2.8 rung 29: "**`ERR_DUPLICATE_CLAIM_LINE` (409)** — a claim line for this
    claim and this `item_id` already exists. Applies to claim-line creation."

    Design: Corner/validations/duplicate_claim_line_for_the_same_item_is_rejected
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Hallway", floor_label="1")
    item = add_cataloged_item(
        ctx,
        room["id"],
        140000,
        photo_bytes=5000,
        name="Runner Rug",
        acquired_at="2025-01-01T00:00:00Z",
        serial_number="GN-38",
        replacement_cost_cents=150000,
    )
    policy = add_policy(ctx, policy_number="NW-C38")
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="THEFT",
        settlement_basis="RCV",
    )
    add_claim_line(ctx, claim["id"], item["id"])

    response = api.add_claim_line(
        claim["id"], {"item_id": item["id"], "claimed_quantity": 1}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM_LINE.value, 409)

    stored_claim = validate_success(api.get_claim(claim["id"], ctx["owner_headers"]))
    assert stored_claim["line_count"] == 1

    rows, meta = validate_paginated(
        api.list_claim_lines(ctx["owner_headers"], params={"claim_id": claim["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_a_claim_line_below_the_minimum_evidence_tier_is_refused(api):
    """PRD 3.7: "The item's `evidence_tier` must rank at or above `PHOTO_SERIAL`, or
    the line is refused with `ERR_EVIDENCE_TIER_INSUFFICIENT`"
    PRD 2.8 rung 20: "**`ERR_EVIDENCE_TIER_INSUFFICIENT` (422)** — the item's
    `evidence_tier` ranks below `CLAIM_MIN_EVIDENCE_TIER`, which is `PHOTO_SERIAL`
    (rank 2). Applies to claim-line creation."

    Design: Corner/validations/claim_line_below_the_minimum_evidence_tier_is_rejected
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Porch", floor_label="0")
    item = add_cataloged_item(
        ctx, room["id"], 60000, photo_bytes=5000, name="Wicker Set",
        acquired_at="2025-01-01T00:00:00Z",
    )
    policy = add_policy(ctx, policy_number="NW-C39")
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="STORM",
        settlement_basis="ACV",
    )

    response = api.add_claim_line(
        claim["id"], {"item_id": item["id"], "claimed_quantity": 1}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_TIER_INSUFFICIENT.value, 422)

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["evidence_tier"] == "PHOTO_ONLY"
    assert stored_item["lifecycle_state"] == "FROZEN"

    stored_claim = validate_success(api.get_claim(claim["id"], ctx["owner_headers"]))
    assert stored_claim["line_count"] == 0

    stored_package = validate_success(api.get_package(package["id"], ctx["owner_headers"]))
    assert stored_package["line_count"] == 1
