"""Two boundaries: the last cent of a policy's scheduling allowance, and the
empty eligible set at package generation."""
from test_helpers import (
    ApiErrorId,
    add_asset,
    add_cataloged_item,
    add_item,
    add_package,
    add_policy,
    add_room,
    assert_policy_ledger_invariant,
    bootstrap_household,
    read_household_version,
    read_policy_version,
    schedule_item,
    validate_error,
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


def _setup_policy_with_400000_remaining():
    """A 1000000-cent scheduling allowance with 600000 already consumed by the
    first item, leaving exactly 400000."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Vault Room", floor_label="0")
    policy = add_policy(
        ctx,
        policy_number="NW-9009",
        deductible_cents=50000,
        scheduled_allowance_cents=1000000,
    )
    item_one = add_cataloged_item(
        ctx, room["id"], 600000, photo_bytes=20000, name="Item One",
        acquired_at="2025-01-01T00:00:00Z", quantity=1,
    )
    item_two = add_cataloged_item(
        ctx, room["id"], 400000, photo_bytes=20000, name="Item Two",
        acquired_at="2025-01-02T00:00:00Z", quantity=1,
    )
    item_three = add_cataloged_item(
        ctx, room["id"], 100000, photo_bytes=20000, name="Item Three",
        acquired_at="2025-01-03T00:00:00Z", quantity=1,
    )
    schedule_item(ctx, item_one["id"], policy["id"], 600000)
    ctx.update(
        {
            "room": room,
            "policy": policy,
            "item_one": item_one,
            "item_two": item_two,
            "item_three": item_three,
        }
    )
    return ctx


def test_scheduling_exactly_the_remaining_allowance_succeeds(api):
    """PRD 3.5: "The requested amount must not exceed the policy's
    `scheduled_remaining_cents`: a request strictly greater is refused with
    `ERR_ALLOWANCE_EXCEEDED`, while a request for exactly the remaining amount
    succeeds and drives `scheduled_remaining_cents` to precisely 0."
    PRD 3.5: "On success the item's `coverage_mode` becomes `SCHEDULED`, its
    `scheduled_policy_id` names the policy and its `scheduled_value_cents` records
    the amount; the policy's `scheduled_consumed_cents` rises by that amount,
    `scheduled_remaining_cents` falls by the same amount, and `coverage_gap_cents`
    is recomputed."

    Design: Difficulty/boundary_precision_check/scheduling_exactly_the_remaining_allowance_succeeds_one_cent_more_fails
    """
    ctx = _setup_policy_with_400000_remaining()

    response = api.schedule_item(
        ctx["item_two"]["id"],
        {
            "policy_id": ctx["policy"]["id"],
            "scheduled_value_cents": 400000,
            "expected_policy_version": read_policy_version(ctx, ctx["policy"]["id"]),
        },
        ctx["owner_headers"],
    )
    validate_success(response, 200)

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["scheduled_consumed_cents"] == 1000000
    assert policy["scheduled_remaining_cents"] == 0
    assert_policy_ledger_invariant(policy)

    item_two = validate_success(api.get_item(ctx["item_two"]["id"], ctx["owner_headers"]))
    assert item_two["coverage_mode"] == "SCHEDULED"
    assert item_two["scheduled_value_cents"] == 400000


def test_scheduling_one_cent_past_the_remaining_allowance_is_refused(api):
    """PRD 2.8 rung 36: "**`ERR_ALLOWANCE_EXCEEDED` (409)** — the requested
    `scheduled_value_cents` is strictly greater than the policy's
    `scheduled_remaining_cents`. A request for exactly the remaining amount
    succeeds. Applies to item scheduling."

    Design: Difficulty/boundary_precision_check/scheduling_exactly_the_remaining_allowance_succeeds_one_cent_more_fails
    """
    ctx = _setup_policy_with_400000_remaining()
    schedule_item(ctx, ctx["item_two"]["id"], ctx["policy"]["id"], 400000)

    response = api.schedule_item(
        ctx["item_three"]["id"],
        {
            "policy_id": ctx["policy"]["id"],
            "scheduled_value_cents": 1,
            "expected_policy_version": read_policy_version(ctx, ctx["policy"]["id"]),
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ALLOWANCE_EXCEEDED.value, 409)

    item_three = validate_success(
        api.get_item(ctx["item_three"]["id"], ctx["owner_headers"])
    )
    assert item_three["coverage_mode"] == "BLANKET"
    assert item_three["scheduled_value_cents"] == 0

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["scheduled_consumed_cents"] == 1000000
    assert policy["scheduled_remaining_cents"] == 0


def _setup_household_whose_only_item_is_still_draft():
    """One item photographed but never valued, so it is still DRAFT and cannot be
    eligible for a package."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Attic", floor_label="3")
    item = add_item(
        ctx,
        room["id"],
        name="Unvalued Trunk",
        category="GENERAL",
        acquired_at="2025-01-01T00:00:00Z",
        quantity=1,
    )
    add_asset(ctx, item["id"], asset_kind="PHOTO", byte_size=15000, checksum="sha-l1")
    policy = add_policy(
        ctx, policy_number="NW-1010", deductible_cents=50000, scheduled_allowance_cents=0
    )
    package = add_package(ctx, policy["id"])
    ctx.update({"room": room, "item": item, "policy": policy, "package": package})
    return ctx


def test_generation_with_an_empty_eligible_set_is_refused(api):
    """PRD 3.6: "at least one eligible item must exist, or the request is refused
    with `ERR_PACKAGE_EMPTY`."
    PRD 3.6: "An item is **eligible** when all three of these hold: its
    `lifecycle_state` is `CATALOGED` or `FROZEN`; its `evidence_tier` ranks at or
    above `PHOTO_ONLY`; and its `valuation_state` is not `APPRAISAL_REQUIRED`."

    Design: Difficulty/boundary_precision_check/package_generation_with_empty_eligible_set_is_rejected
    """
    ctx = _setup_household_whose_only_item_is_still_draft()

    response = api.generate_package(
        ctx["package"]["id"],
        {"expected_household_version": read_household_version(ctx)},
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PACKAGE_EMPTY.value, 422)

    package = validate_success(api.get_package(ctx["package"]["id"], ctx["owner_headers"]))
    assert package["status"] == "DRAFT"
    assert package["line_count"] == 0


def test_a_photographed_but_unvalued_item_never_leaves_draft(api):
    """PRD 3.3: "An item moves `DRAFT → CATALOGED` automatically, never by a
    dedicated call. The predicate is evaluated at the end of every asset upload and
    every value declaration, and it holds when the item's `evidence_tier` is
    anything other than `NONE` **and** its `declared_value_cents` is strictly
    greater than zero — whichever of the two calls completes the pair is the one
    that flips the item."
    PRD 3.3: "Uploading the first `PHOTO` to an item that has no other stored asset
    and no `serial_number` moves it `NONE → PHOTO_ONLY`; the household's
    `asset_count` and `asset_bytes_used` rise."

    Design: Difficulty/boundary_precision_check/package_generation_with_empty_eligible_set_is_rejected
    """
    ctx = _setup_household_whose_only_item_is_still_draft()

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["lifecycle_state"] == "DRAFT"
    assert item["evidence_tier"] == "PHOTO_ONLY"
    assert item["declared_value_cents"] == 0

    api.generate_package(
        ctx["package"]["id"],
        {"expected_household_version": read_household_version(ctx)},
        ctx["owner_headers"],
    )

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["packages_used_this_period"] == 0, (
        "a refused generation must not burn a package entitlement"
    )
