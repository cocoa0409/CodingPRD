"""Cross-cutting claims: the three optimistic-concurrency parents, the
soft-delete axis on an evidence blob, and the immediacy of the claim cascade."""
from test_helpers import (
    ApiErrorId,
    add_asset,
    add_cataloged_item,
    add_estate_plan,
    add_generated_package,
    add_item,
    add_member_to_household,
    add_package,
    add_policy,
    add_room,
    add_share_grant,
    allocate,
    assert_household_freeze_invariant,
    assert_same_instant,
    bootstrap_household,
    create_claim_payload,
    declare_value,
    make_estate_executor_headers,
    read_household_version,
    read_plan_version,
    read_subscription_version,
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


def test_a_stale_household_version_blocks_package_generation(api):
    """PRD 2.10: "**Package generation** requires `expected_household_version`,
    carrying the client's last observed `version` of the `Household`. A mismatch is
    rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412). Generation freezes a
    snapshot of the household and supersedes the prior delivered package, so a client
    working from a stale household version would freeze a picture that no longer
    exists."
    PRD 2.9: "| Share-grant creation | The `Household`; the `ShareGrant` is created
    at version 1 |"

    Design: Corner/cross_cutting_complexity_layers/stale_household_version_on_package_generate_returns_412
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Gallery", floor_label="1")
    add_cataloged_item(
        ctx, room["id"], 110000, photo_bytes=5000, name="Etching",
        acquired_at="2025-01-01T00:00:00Z",
    )
    policy = add_policy(ctx, policy_number="NW-C44")
    package = add_package(ctx, policy["id"])

    stale_version = read_household_version(ctx)
    add_share_grant(
        ctx,
        scope_kind="HOUSEHOLD",
        recipient_ref="bump@carrier.example",
        redaction_level="VALUES_HIDDEN",
        starts_at="2026-05-01T00:00:00Z",
        expires_at="2026-06-01T00:00:00Z",
        access_cap=1,
    )

    response = api.generate_package(
        package["id"],
        {"expected_household_version": stale_version},
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_HOUSEHOLD_VERSION.value, 412)

    stored_package = validate_success(api.get_package(package["id"], ctx["owner_headers"]))
    assert stored_package["status"] == "DRAFT"
    assert stored_package["line_count"] == 0

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["packages_used_this_period"] == 0

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 1


def test_a_stale_plan_version_blocks_a_second_allocation(api):
    """PRD 2.10: "**Allocation creation** requires `expected_estate_plan_version`,
    carrying the client's last observed `version` of the `EstatePlan`. A mismatch is
    rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). Every allocation consumes
    units out of the plan-wide conservation budget, so a writer holding a stale plan
    version is sizing its `quantity` against an unallocated remainder another
    allocation already claimed."
    PRD 2.9: "| Allocation creation | The `EstatePlan` and the `Item`; the
    `Allocation` is created at version 1 |"

    Design: Corner/cross_cutting_complexity_layers/stale_estate_plan_version_on_allocation_create_returns_412
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    executor = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "EXECUTOR", full_name="Exec 45"
    )
    heir = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "HEIR", full_name="Heir 45"
    )
    executor_headers = make_estate_executor_headers(executor["id"])
    room = add_room(ctx, name="Dining", floor_label="1")
    item = add_cataloged_item(
        ctx, room["id"], 200000, photo_bytes=5000, name="Chair Pair",
        acquired_at="2024-01-01T00:00:00Z", quantity=2,
    )
    plan = add_estate_plan(ctx, executor["id"], valuation_mode="GROSS")

    stale_version = read_plan_version(plan["id"], executor_headers)
    first = api.create_allocation(
        plan["id"],
        {
            "item_id": item["id"],
            "disposition": "KEEP",
            "quantity": 1,
            "heir_member_id": heir["id"],
            "expected_estate_plan_version": stale_version,
        },
        executor_headers,
    )
    validate_success(first, 201)

    second = api.create_allocation(
        plan["id"],
        {
            "item_id": item["id"],
            "disposition": "KEEP",
            "quantity": 1,
            "heir_member_id": heir["id"],
            "expected_estate_plan_version": stale_version,
        },
        executor_headers,
    )
    validate_error(second, ApiErrorId.ERR_STALE_PLAN_VERSION.value, 412)

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["allocated_quantity"] == 1

    stored_plan = validate_success(api.get_estate_plan(plan["id"], executor_headers))
    assert stored_plan["unallocated_item_count"] == 1

    rows, meta = validate_paginated(
        api.list_allocations(executor_headers, params={"estate_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_a_stale_subscription_version_blocks_a_tier_change(api):
    """PRD 2.10: "**Tier change** requires `expected_subscription_version`, carrying
    the client's last observed `version` of the `Subscription`. A mismatch is
    rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."
    PRD 3.2: "Attesting the refresh is the homeowner's act and is legal from every
    band, including `CURRENT`, where it is an early attestation that simply pushes
    the window forward — that self-loop is what makes this axis cyclic."

    Design: Corner/cross_cutting_complexity_layers/stale_subscription_version_on_change_tier_returns_412
    """
    ctx = bootstrap_household(tier="PLUS", activate=True)

    stale_version = read_subscription_version(ctx)
    validate_success(
        api.attest_refresh(
            ctx["subscription_id"],
            {"attestation_note": "early attestation"},
            ctx["owner_headers"],
        )
    )

    response = api.change_tier(
        ctx["subscription_id"],
        {
            "tier": "ESTATE",
            "proration_mode": "DAILY",
            "expected_subscription_version": stale_version,
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value, 412)

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["tier"] == "PLUS"
    assert subscription["monthly_fee_cents"] == 2900
    assert subscription["last_proration_charge_cents"] == 0
    assert subscription["refresh_state"] == "CURRENT"
    assert_same_instant(
        subscription["last_attested_at"],
        "2026-05-01T00:00:00Z",
        "Subscription.last_attested_at",
    )


def test_a_soft_deleted_asset_leaves_the_counters_but_stays_readable(api):
    """PRD 3.3: "An asset lives in `status` `STORED` until it is soft-deleted, at
    which point its `status` becomes `DELETED`; deleted assets leave the household's
    `asset_count` and `asset_bytes_used` and stop contributing to any evidence
    computation, but the row itself remains readable."
    PRD 3.3: "Deleting the last stored `RECEIPT` or `PROVENANCE_DOC` moves the item
    `DOCUMENTED → PHOTO_SERIAL` and lowers `asset_count` and `asset_bytes_used`."

    Deviation: the design instance also asserts that the unfiltered asset list omits
    the deleted row, which the PRD does not state — a list with no `status` filter
    matches every row, and the PRD explicitly keeps the deleted row readable.  The
    two states are separated with explicit `status` filters instead; the soft-delete
    claim itself is unchanged.

    Design: Corner/cross_cutting_complexity_layers/soft_deleted_asset_is_excluded_from_the_default_asset_list
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Kitchen", floor_label="1")
    item = add_item(
        ctx,
        room["id"],
        name="Mixer",
        acquired_at="2025-01-01T00:00:00Z",
        serial_number="GN-47",
    )
    photo = add_asset(
        ctx, item["id"], asset_kind="PHOTO", byte_size=6000, checksum="sha-c47a"
    )
    receipt = add_asset(
        ctx, item["id"], asset_kind="RECEIPT", byte_size=4000, checksum="sha-c47b"
    )
    declare_value(ctx, item["id"], 70000)

    before = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert before["evidence_tier"] == "DOCUMENTED"

    validate_success(api.delete_asset(receipt["id"], ctx["owner_headers"]), 200)

    stored_rows, stored_meta = validate_paginated(
        api.list_assets(
            ctx["owner_headers"], params={"item_id": item["id"], "status": "STORED"}
        )
    )
    assert stored_meta["total_count"] == 1
    assert stored_rows[0]["asset_kind"] == "PHOTO"
    assert stored_rows[0]["id"] == photo["id"]

    deleted_rows, deleted_meta = validate_paginated(
        api.list_assets(
            ctx["owner_headers"], params={"item_id": item["id"], "status": "DELETED"}
        )
    )
    assert deleted_meta["total_count"] == 1
    assert deleted_rows[0]["id"] == receipt["id"]

    stored_asset = validate_success(api.get_asset(receipt["id"], ctx["owner_headers"]))
    assert stored_asset["status"] == "DELETED"

    after = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert after["evidence_tier"] == "PHOTO_SERIAL"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["asset_count"] == 1
    assert household["asset_bytes_used"] == 6000


def test_the_claim_creation_response_already_reports_its_freeze_cascade(api):
    """PRD 3.7: "Opening a claim runs the records-freeze cascade. Every item of the
    household whose `lifecycle_state` is `CATALOGED` **and** whose `room_id` appears
    in `affected_room_ids` moves `CATALOGED → FROZEN` with `frozen_by_claim_id` set
    to the new claim's id; the household's `frozen_item_count` rises by the number
    frozen, `records_freeze_active` becomes true, and the claim's own
    `frozen_item_count` records exactly how many rows it froze."
    PRD 2.4: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/claim_creation_response_already_carries_its_cascade_results
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Bedroom", floor_label="2")
    item = add_cataloged_item(
        ctx, room["id"], 130000, photo_bytes=5000, name="Headboard",
        acquired_at="2025-01-01T00:00:00Z",
    )
    policy = add_policy(ctx, policy_number="NW-C48")
    package = add_generated_package(ctx, policy["id"])

    response = api.create_claim(
        create_claim_payload(
            ctx["household_id"],
            package["id"],
            policy["id"],
            [room["id"]],
            loss_date="2026-05-01T00:00:00Z",
            peril="WATER",
            settlement_basis="ACV",
        ),
        ctx["owner_headers"],
    )
    claim = validate_success(response, 201)
    assert claim["frozen_item_count"] == 1, (
        "the creating response body itself must already carry the cascade result"
    )
    assert claim["status"] == "OPEN"

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["lifecycle_state"] == "FROZEN"
    assert stored_item["frozen_by_claim_id"] == claim["id"]

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["frozen_item_count"] == 1
    assert household["records_freeze_active"] is True
    assert_household_freeze_invariant(household)
