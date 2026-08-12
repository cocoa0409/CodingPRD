"""Two writes refused because of state that lives on a different aggregate: an
item mutation gated by the household's subscription, and an estate allocation
gated by a loss claim."""
from test_helpers import (
    ApiErrorId,
    add_cataloged_item,
    add_estate_plan,
    add_generated_package,
    add_member_to_household,
    add_policy,
    add_room,
    bootstrap_household,
    create_claim_payload,
    drive_subscription_to_lapsed,
    make_estate_executor_headers,
    open_claim,
    read_plan_version,
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


def _setup_lapsed_household_with_a_generated_package():
    """A PLUS household driven ACTIVE -> PAST_DUE -> LAPSED, holding one
    CATALOGED item in room A and a package generated while it was still ACTIVE.

    Input deviation: the item carries `serial_number` "GN-M1" so that the
    RECEIPT upload under test lands the evidence tier on DOCUMENTED, which is the
    outcome the instance asserts.  The claim about the write gate being
    endpoint-selective is unchanged.
    """
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room_a = add_room(ctx, name="Room A", floor_label="1")
    room_b = add_room(ctx, name="Room B", floor_label="1")
    item = add_cataloged_item(
        ctx,
        room_a["id"],
        250000,
        photo_bytes=25000,
        name="Console Table",
        category="GENERAL",
        acquired_at="2025-02-01T00:00:00Z",
        quantity=1,
        serial_number="GN-M1",
    )
    policy = add_policy(
        ctx, policy_number="NW-1111", deductible_cents=50000, scheduled_allowance_cents=0
    )
    package = add_generated_package(ctx, policy["id"])
    drive_subscription_to_lapsed(ctx, "2026-05-12T00:00:00Z")
    ctx.update(
        {"room_a": room_a, "room_b": room_b, "item": item, "policy": policy, "package": package}
    )
    return ctx


def test_read_only_vault_blocks_asset_upload_but_not_claim_intake(api):
    """PRD 2.7: "While a household is `READ_ONLY`, every mutating endpoint under
    `/vault` is rejected with `ERR_VAULT_READ_ONLY` (HTTP 403) at ladder rung 10,
    except for the endpoints on the exclusion list below, which remain callable"
    PRD 3.7: "Claim opening is on the write-gate exclusion list, so even a lapsed
    household may run a claim to completion."

    Design: Difficulty/cross_entity_state_dependency/item_asset_upload_gated_by_subscription_status_but_claim_intake_is_not
    """
    ctx = _setup_lapsed_household_with_a_generated_package()

    blocked = api.upload_asset(
        ctx["item"]["id"],
        {
            "asset_kind": "RECEIPT",
            "byte_size": 12000,
            "checksum": "sha-m2",
            "captured_at": "2026-05-12T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(blocked, ApiErrorId.ERR_VAULT_READ_ONLY.value, 403)

    allowed = api.create_claim(
        create_claim_payload(
            ctx["household_id"],
            ctx["package"]["id"],
            ctx["policy"]["id"],
            [ctx["room_b"]["id"]],
            loss_date="2026-05-12T00:00:00Z",
            peril="FIRE",
            settlement_basis="ACV",
            deductible_mode="PRO_RATA",
        ),
        ctx["owner_headers"],
    )
    claim = validate_success(allowed, 201)
    assert claim["status"] == "OPEN"
    assert claim["frozen_item_count"] == 0, (
        "room B holds no items, so the freeze cascade finds nothing"
    )


def test_reinstatement_reopens_the_gate_for_the_same_asset_upload(api):
    """PRD 3.2: "Reinstatement is the homeowner's own path back. It moves `LAPSED →
    ACTIVE` and is allowed only while the household's usage still fits the tier it
    holds"
    PRD 3.2: "The household then becomes `RESTRICTED` if its `refresh_state` is
    `OVERDUE` and `OPEN` otherwise."
    PRD 3.3: "The tier is `DOCUMENTED` when all three hold; otherwise `PHOTO_SERIAL`
    when the photo and serial predicates hold; otherwise `PHOTO_ONLY` when the photo
    predicate holds; otherwise `NONE`."

    Design: Difficulty/cross_entity_state_dependency/item_asset_upload_gated_by_subscription_status_but_claim_intake_is_not
    """
    ctx = _setup_lapsed_household_with_a_generated_package()

    reinstated = validate_success(
        api.reinstate_subscription(ctx["subscription_id"], {}, ctx["owner_headers"])
    )
    assert reinstated["status"] == "ACTIVE"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["write_gate_state"] == "OPEN"

    response = api.upload_asset(
        ctx["item"]["id"],
        {
            "asset_kind": "RECEIPT",
            "byte_size": 12000,
            "checksum": "sha-m3",
            "captured_at": "2026-05-12T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_success(response, 201)

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["evidence_tier"] == "DOCUMENTED", (
        "photo, serial and document predicates all hold once the receipt lands"
    )


def _setup_draft_plan_over_a_frozen_item():
    """A DRAFT estate plan whose household holds exactly one item, and that item
    is FROZEN by an OPEN loss claim over its room."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    executor = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "EXECUTOR", full_name="Executor N"
    )
    executor_headers = make_estate_executor_headers(executor["id"])
    room = add_room(ctx, name="Room R", floor_label="1")
    item = add_cataloged_item(
        ctx,
        room["id"],
        400000,
        photo_bytes=22000,
        name="Grandfather Clock",
        category="GENERAL",
        acquired_at="2020-01-01T00:00:00Z",
        quantity=1,
    )
    policy = add_policy(
        ctx, policy_number="NW-1212", deductible_cents=50000, scheduled_allowance_cents=0
    )
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="WATER",
        settlement_basis="ACV",
        deductible_mode="PRO_RATA",
    )
    plan = add_estate_plan(ctx, executor["id"], valuation_mode="GROSS")
    ctx.update(
        {
            "executor": executor,
            "executor_headers": executor_headers,
            "room": room,
            "item": item,
            "policy": policy,
            "package": package,
            "claim": claim,
            "plan": plan,
        }
    )
    return ctx


def test_allocation_of_a_frozen_item_is_refused_as_not_disposable(api):
    """PRD 3.8: "And the item must be dispositionable: an item whose
    `lifecycle_state` is `FROZEN`, or which carries an appraisal in status
    `REQUESTED`, is refused with `ERR_ITEM_NOT_DISPOSABLE`."
    PRD 2.8 rung 26: "**`ERR_ITEM_NOT_DISPOSABLE` (409)** — the item being allocated
    is not dispositionable: its `lifecycle_state` is `FROZEN`, or an appraisal on it
    sits in status `REQUESTED`. Applies to allocation creation."

    Design: Difficulty/cross_entity_state_dependency/allocation_refused_while_item_is_frozen_by_an_open_claim
    """
    ctx = _setup_draft_plan_over_a_frozen_item()

    response = api.create_allocation(
        ctx["plan"]["id"],
        {
            "item_id": ctx["item"]["id"],
            "disposition": "KEEP",
            "quantity": 1,
            "heir_member_id": ctx["executor"]["id"],
            "expected_estate_plan_version": read_plan_version(
                ctx["plan"]["id"], ctx["executor_headers"]
            ),
        },
        ctx["executor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_DISPOSABLE.value, 409)

    plan = validate_success(
        api.get_estate_plan(ctx["plan"]["id"], ctx["executor_headers"])
    )
    assert plan["status"] == "DRAFT"

    rows, meta = validate_paginated(
        api.list_allocations(
            ctx["executor_headers"], params={"estate_plan_id": ctx["plan"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_frozen_item_keeps_its_claim_pointer_and_zero_allocated_units(api):
    """PRD 2.12: "A household's `frozen_item_count` always equals the number of its
    items whose `lifecycle_state` is `FROZEN`; every such item carries a non-null
    `frozen_by_claim_id` pointing at a loss claim whose status is `OPEN`,
    `SUBMITTED`, `UNDER_REVIEW` or `SUPPLEMENT_REQUESTED`"
    PRD 2.12: "For every `CATALOGED` item of a plan's household,
    `allocated_quantity` equals the sum of `quantity` over that item's allocations
    under the plan, and never exceeds the item's own `quantity`"

    Design: Difficulty/cross_entity_state_dependency/allocation_refused_while_item_is_frozen_by_an_open_claim
    """
    ctx = _setup_draft_plan_over_a_frozen_item()

    api.create_allocation(
        ctx["plan"]["id"],
        {
            "item_id": ctx["item"]["id"],
            "disposition": "KEEP",
            "quantity": 1,
            "heir_member_id": ctx["executor"]["id"],
            "expected_estate_plan_version": read_plan_version(
                ctx["plan"]["id"], ctx["executor_headers"]
            ),
        },
        ctx["executor_headers"],
    )

    item = validate_success(api.get_item(ctx["item"]["id"], ctx["owner_headers"]))
    assert item["lifecycle_state"] == "FROZEN"
    assert item["frozen_by_claim_id"] == ctx["claim"]["id"]
    assert item["allocated_quantity"] == 0
