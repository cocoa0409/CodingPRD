"""State-machine claims: terminal lockdown, guarded transitions, replacement,
share-grant exhaustion, supersession, the evidence-downgrade cascade and the
estate plan's revision loop."""
from test_helpers import (
    ApiErrorId,
    add_appraiser,
    add_asset,
    add_cataloged_item,
    add_claim_line,
    add_estate_plan,
    add_generated_package,
    add_item,
    add_member_to_household,
    add_package,
    add_policy,
    add_room,
    add_share_grant,
    allocate,
    bootstrap_household,
    declare_value,
    deliver_package,
    generate_package,
    make_anonymous_headers,
    make_appraiser_headers,
    make_estate_executor_headers,
    open_claim,
    propose_plan,
    request_appraisal,
    set_clock,
    submit_claim,
    suspend_appraiser,
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


def test_withdrawing_an_already_withdrawn_claim_reports_the_terminal_state(api):
    """PRD 2.8 rung 13: "**`ERR_ALREADY_TERMINAL` (409)** — the target entity
    already sits in a terminal state of the axis the request would move. Applies to
    every state-transition endpoint."
    PRD 3.7: "`SETTLED`, `DENIED` and `WITHDRAWN` are the three terminal claim
    states."

    Design: Corner/state_machines/withdraw_an_already_withdrawn_claim_returns_already_terminal
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Room X", floor_label="1")
    add_cataloged_item(
        ctx, room["id"], 100000, name="Bureau", acquired_at="2025-01-01T00:00:00Z"
    )
    policy = add_policy(ctx, policy_number="NW-C11")
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="OTHER",
        settlement_basis="ACV",
    )
    validate_success(
        api.withdraw_claim(claim["id"], {"withdraw_reason": "first"}, ctx["owner_headers"])
    )

    response = api.withdraw_claim(
        claim["id"], {"withdraw_reason": "second"}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)

    final_claim = validate_success(api.get_claim(claim["id"], ctx["owner_headers"]))
    assert final_claim["status"] == "WITHDRAWN"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["frozen_item_count"] == 0


def test_delivering_a_draft_package_is_an_invalid_transition(api):
    """PRD 3.6: "The homeowner or the insurance agent delivers a `GENERATED` package
    to a `recipient_ref` — an opaque agent email or portal id."
    PRD 2.8 rung 14: "**`ERR_INVALID_STATE` (409)** — the target entity's current
    state is not a declared origin state for the requested transition, or a
    cross-entity precondition of that transition fails."

    Design: Corner/state_machines/deliver_a_draft_package_returns_invalid_state
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[])
    policy = add_policy(ctx, policy_number="NW-C12")
    package = add_package(ctx, policy["id"])

    response = api.deliver_package(
        package["id"], {"recipient_ref": "agent@carrier.example"}, ctx["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    stored = validate_success(api.get_package(package["id"], ctx["owner_headers"]))
    assert stored["status"] == "DRAFT"
    assert stored["delivered_at"] is None


def test_certification_by_a_suspended_appraiser_is_an_invalid_transition(api):
    """PRD 3.4: "An appraiser opens in `status` `ACTIVE` and may be suspended by the
    admin to `SUSPENDED`, after which any certification attempt fails with
    `ERR_INVALID_STATE`."
    PRD 3.4: "The appraisal must be in `REQUESTED`, the caller's `X-User-ID` must
    equal `appraiser_id`, the appraiser's own `status` must be `ACTIVE`, and the
    clock must have reached or passed `inspection_end_at`; certifying early or while
    suspended fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/certify_by_a_suspended_appraiser_returns_invalid_state
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[JEWELRY_SCHEDULE])
    room = add_room(ctx, name="Vault", floor_label="0")
    appraiser = add_appraiser(
        display_name="Susan Stone",
        credential_id="CRED-JW-13",
        scope_categories=["JEWELRY"],
    )
    item = add_cataloged_item(
        ctx,
        room["id"],
        250000,
        name="Topaz Ring",
        category="JEWELRY",
        acquired_at="2024-01-01T00:00:00Z",
        serial_number="JW-13",
    )
    appraisal = request_appraisal(
        ctx,
        item["id"],
        appraiser["id"],
        inspection_start_at="2026-05-05T09:00:00Z",
        inspection_end_at="2026-05-05T17:00:00Z",
    )
    set_clock("2026-05-06T00:00:00Z")
    suspend_appraiser(appraiser["id"])

    response = api.certify_appraisal(
        appraisal["id"], {"appraised_value_cents": 500000}, make_appraiser_headers(appraiser["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    stored_appraiser = validate_success(
        api.get_appraiser(appraiser["id"], ctx["owner_headers"])
    )
    assert stored_appraiser["status"] == "SUSPENDED"

    stored_appraisal = validate_success(
        api.get_appraisal(appraisal["id"], ctx["owner_headers"])
    )
    assert stored_appraisal["status"] == "REQUESTED"
    assert stored_appraisal["certified_at"] is None

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["effective_value_basis"] == "DECLARED"


def test_replacement_retires_the_predecessor_and_frees_its_serial(api):
    """PRD 3.3: "A new item row is created in `DRAFT` with `replaces_item_id`
    pointing at the predecessor and inheriting the predecessor's `household_id`,
    `room_id` and `category`. The new row's `serial_chain_intact` is true when the
    submitted `serial_number` equals the predecessor's `serial_number` and false
    otherwise — a broken provenance chain is recorded, not rejected."
    PRD 3.3: "Once the predecessor is `REPLACED` its `serial_number` is free for
    reuse."

    Deviation: the design instance also asserts the successor's `evidence_tier` is
    PHOTO_SERIAL, which the PRD's own tier formula contradicts — a fresh row owns no
    stored PHOTO, so the photo predicate cannot hold.  That assertion is omitted
    rather than asserted against the contract; the instance's replacement claim is
    unchanged.

    Design: Corner/state_machines/item_replace_moves_predecessor_to_replaced_and_frees_its_serial
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Garage", floor_label="0")
    predecessor = add_cataloged_item(
        ctx,
        room["id"],
        90000,
        name="Power Washer",
        acquired_at="2024-05-01T00:00:00Z",
        serial_number="GN-CHAIN",
    )

    response = api.replace_item(
        predecessor["id"],
        {
            "name": "Power Washer Mk2",
            "acquired_at": "2026-04-01T00:00:00Z",
            "serial_number": "GN-CHAIN",
        },
        ctx["owner_headers"],
    )
    successor = validate_success(response, 201)

    retired = validate_success(api.get_item(predecessor["id"], ctx["owner_headers"]))
    assert retired["lifecycle_state"] == "REPLACED"

    assert successor["replaces_item_id"] == predecessor["id"]
    assert successor["serial_chain_intact"] is True
    assert successor["lifecycle_state"] == "DRAFT"
    assert successor["category"] == "GENERAL"

    rows, meta = validate_paginated(
        api.list_items(ctx["owner_headers"], params={"replaces_item_id": predecessor["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_share_grant_exhausts_on_the_redemption_that_reaches_its_cap(api):
    """PRD 3.9: "Metering is applied **before** the response is rendered:
    `access_count` rises by one on every successful redemption, so the body carries
    the post-increment value. When that post-increment count equals `access_cap` the
    grant transitions `ACTIVE → EXHAUSTED` and the household's `active_share_count`
    falls — but **this** redemption still succeeds and returns its rows in full.
    Only the next attempt fails, with `ERR_SHARE_GRANT_INACTIVE`."

    Design: Corner/state_machines/share_grant_becomes_exhausted_on_the_redemption_that_reaches_the_cap
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Salon", floor_label="1")
    add_cataloged_item(
        ctx,
        room["id"],
        80000,
        name="Mirror",
        acquired_at="2025-01-01T00:00:00Z",
        serial_number="GN-15",
    )
    grant = add_share_grant(
        ctx,
        scope_kind="HOUSEHOLD",
        recipient_ref="adjuster@carrier.example",
        redaction_level="FULL",
        starts_at="2026-05-01T00:00:00Z",
        expires_at="2026-06-01T00:00:00Z",
        access_cap=2,
    )
    anon = make_anonymous_headers()

    first = validate_success(api.redeem_share(grant["share_token"], anon))
    assert first["access_count"] == 1

    second = validate_success(api.redeem_share(grant["share_token"], anon))
    assert second["access_count"] == 2

    third = api.redeem_share(grant["share_token"], anon)
    validate_error(third, ApiErrorId.ERR_SHARE_GRANT_INACTIVE.value, 403)

    stored = validate_success(api.get_share_grant(grant["id"], ctx["owner_headers"]))
    assert stored["status"] == "EXHAUSTED"
    assert stored["access_count"] == 2

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 0


def test_generating_a_second_package_supersedes_the_delivered_one_and_voids_its_share(api):
    """PRD 3.6: "Hop 2, caused by hop 1, moves any prior documentation package for
    the **same** `policy_id` whose `status` is `DELIVERED` along `DELIVERED →
    SUPERSEDED`, writing `superseded_by_package_id` with the new package's id"
    PRD 3.6: "Hop 3, caused by hop 2, moves every share grant with `status` `ACTIVE`
    whose `scope_package_id` names that superseded package to `VOIDED_BY_SCOPE` with
    `voided_reason` `SCOPE_SUPERSEDED`. Hop 4, caused by hop 3, recomputes the
    household's `active_share_count`."

    Design: Corner/state_machines/package_supersede_voids_the_package_scoped_share_grant
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Library", floor_label="1")
    add_cataloged_item(
        ctx, room["id"], 200000, name="First Edition", acquired_at="2025-01-01T00:00:00Z"
    )
    policy = add_policy(ctx, policy_number="NW-C16")
    package_one = add_generated_package(ctx, policy["id"])
    deliver_package(ctx, package_one["id"], "agent@carrier.example")
    grant = add_share_grant(
        ctx,
        scope_kind="PACKAGE",
        recipient_ref="agent@carrier.example",
        redaction_level="SERIALS_HIDDEN",
        starts_at="2026-05-01T00:00:00Z",
        expires_at="2026-06-01T00:00:00Z",
        scope_package_id=package_one["id"],
        access_cap=5,
    )
    package_two = add_package(ctx, policy["id"])

    generated = generate_package(ctx, package_two["id"])
    assert generated["status"] == "GENERATED"

    superseded = validate_success(api.get_package(package_one["id"], ctx["owner_headers"]))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_package_id"] == package_two["id"]
    assert superseded["snapshot_total_effective_cents"] == 200000

    voided = validate_success(api.get_share_grant(grant["id"], ctx["owner_headers"]))
    assert voided["status"] == "VOIDED_BY_SCOPE"
    assert voided["voided_reason"] == "SCOPE_SUPERSEDED"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["active_share_count"] == 0

    subscription = validate_success(
        api.get_subscription(ctx["subscription_id"], ctx["owner_headers"])
    )
    assert subscription["packages_used_this_period"] == 2


def test_deleting_the_last_serial_plate_denies_the_pending_claim_line(api):
    """PRD 3.3: "Hop 3, caused by hop 2, moves every claim line on this item that is
    still in status `PENDING` to `DENIED` with `denial_reason`
    `EVIDENCE_INSUFFICIENT`, because `PHOTO_ONLY` now ranks below the claim minimum;
    its `net_settlement_cents` is forced to 0."
    PRD 3.3: "Hop 4, caused by hop 3, recomputes each affected claim's
    `denied_line_count`, and where that count now equals the claim's `line_count`
    and the claim sits in `UNDER_REVIEW`, the claim itself moves `UNDER_REVIEW →
    DENIED`."
    PRD 3.7: "Crucially, the claimed item does **not** have to sit in one of the
    claim's `affected_room_ids`: only items in those rooms are records-frozen, so an
    item claimed from outside them stays editable and its evidence can still be
    deleted"

    Design: Corner/state_machines/evidence_downgrade_denies_the_pending_claim_line_and_updates_the_claim
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room_a = add_room(ctx, name="Room A", floor_label="1")
    room_b = add_room(ctx, name="Room B", floor_label="2")

    item_x = add_item(
        ctx,
        room_b["id"],
        name="Item X",
        category="GENERAL",
        acquired_at="2025-01-01T00:00:00Z",
        replacement_cost_cents=100000,
    )
    add_asset(ctx, item_x["id"], asset_kind="PHOTO", byte_size=9000, checksum="sha-x1")
    serial_asset = add_asset(
        ctx, item_x["id"], asset_kind="SERIAL_PLATE", byte_size=4000, checksum="sha-x2"
    )
    declare_value(ctx, item_x["id"], 90000)

    item_y = add_cataloged_item(
        ctx,
        room_a["id"],
        90000,
        name="Item Y",
        acquired_at="2025-01-02T00:00:00Z",
        serial_number="GN-Y",
        replacement_cost_cents=100000,
    )

    policy = add_policy(ctx, policy_number="NW-C17")
    package = add_generated_package(ctx, policy["id"])
    claim = open_claim(
        ctx,
        package["id"],
        policy["id"],
        [room_a["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="FIRE",
        settlement_basis="RCV",
    )
    line_x = add_claim_line(ctx, claim["id"], item_x["id"])
    line_y = add_claim_line(ctx, claim["id"], item_y["id"])
    submit_claim(ctx, claim["id"])

    validate_success(api.delete_asset(serial_asset["id"], ctx["owner_headers"]), 200)

    stored_x = validate_success(api.get_item(item_x["id"], ctx["owner_headers"]))
    assert stored_x["evidence_tier"] == "PHOTO_ONLY"
    assert stored_x["lifecycle_state"] == "CATALOGED"

    denied = validate_success(api.get_claim_line(line_x["id"], ctx["owner_headers"]))
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "EVIDENCE_INSUFFICIENT"
    assert denied["net_settlement_cents"] == 0

    untouched = validate_success(api.get_claim_line(line_y["id"], ctx["owner_headers"]))
    assert untouched["status"] == "PENDING"

    stored_claim = validate_success(api.get_claim(claim["id"], ctx["owner_headers"]))
    assert stored_claim["denied_line_count"] == 1
    assert stored_claim["status"] == "SUBMITTED"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["asset_count"] == 2


def test_deleting_an_allocation_drives_a_proposed_plan_back_to_draft(api):
    """PRD 3.8: "Deleting an allocation is the compensating action: the item's
    `allocated_quantity` falls by exactly that row's `quantity` and the plan's
    `unallocated_item_count` is recomputed. When the plan was `PROPOSED`, the
    deletion also drives it `PROPOSED → DRAFT`, setting `balance_spread_pct` back to
    null and `balanced` back to false while leaving `proposed_at` at its previous
    value. That is the revision loop."
    PRD 3.8: "The allocation's `allocated_value_cents` is fixed at creation as the
    item's `effective_value_cents` multiplied by this allocation's `quantity`,
    divided by the item's own `quantity`, rounded half up to whole cents."

    Design: Corner/state_machines/estate_plan_returns_to_draft_when_an_allocation_is_deleted
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    executor = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "EXECUTOR", full_name="Exec Eighteen"
    )
    heir = add_member_to_household(
        ctx["owner_headers"], ctx["household_id"], "HEIR", full_name="Heir Eighteen"
    )
    executor_headers = make_estate_executor_headers(executor["id"])
    room = add_room(ctx, name="Cellar", floor_label="0")
    item = add_cataloged_item(
        ctx,
        room["id"],
        200000,
        name="Candlestick Pair",
        acquired_at="2024-01-01T00:00:00Z",
        quantity=2,
    )
    plan = add_estate_plan(ctx, executor["id"], valuation_mode="GROSS")
    allocation_one = allocate(
        plan["id"], executor_headers, item["id"], "KEEP", 1, heir_member_id=heir["id"]
    )
    allocation_two = allocate(
        plan["id"], executor_headers, item["id"], "KEEP", 1, heir_member_id=heir["id"]
    )
    proposed = propose_plan(plan["id"], executor_headers)

    assert proposed["status"] == "PROPOSED"
    assert proposed["unallocated_item_count"] == 0
    assert proposed["heir_count"] == 1
    assert proposed["balance_spread_pct"] == 0.0
    assert proposed["balanced"] is True
    assert allocation_one["allocated_value_cents"] == 100000

    validate_success(
        api.delete_allocation(allocation_two["id"], executor_headers), 200
    )

    reverted = validate_success(api.get_estate_plan(plan["id"], executor_headers))
    assert reverted["status"] == "DRAFT"
    assert reverted["balance_spread_pct"] is None
    assert reverted["balanced"] is False
    assert reverted["unallocated_item_count"] == 1

    stored_item = validate_success(api.get_item(item["id"], ctx["owner_headers"]))
    assert stored_item["allocated_quantity"] == 1

    rows, meta = validate_paginated(
        api.list_allocations(executor_headers, params={"estate_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
