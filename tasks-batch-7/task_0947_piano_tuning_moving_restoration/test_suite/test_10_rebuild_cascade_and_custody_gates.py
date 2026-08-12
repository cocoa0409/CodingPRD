"""Cascade B — the rebuild supersession — and the rebuild-start custody gate."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_quote,
    assert_contracted_value_conservation,
    make_client_headers,
    read_client,
    read_instrument,
    read_ledger,
    read_milestones,
    read_service_order,
    set_custody,
    setup_rebuild_order_pending,
    setup_rebuild_quote_over_voice_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]
COORDINATOR = TEST_USERS["move_coordinator_headers"]


def test_approving_a_rebuild_quote_voids_the_in_flight_order_and_its_milestones(api):
    """PRD 2.11: "Hop 1: the quote moves from `ISSUED` to `APPROVED`. Hop 2: *because* a
    rebuild quote for this instrument was approved, every service order of the same
    instrument whose `service_type` is `TUNE`, `PITCH_RAISE`, `REGULATE` or `VOICE` and
    whose status is `PENDING`, `IN_PROGRESS` or `ON_HOLD` moves to `VOIDED_BY_REBUILD`,
    processed in order `created_at` ascending. Hop 3: *because* an order was voided,
    every milestone of that order whose status is `PENDING`, `READY` or `RELEASED` moves
    to `CANCELLED`, processed in `sequence_index` ascending order."
    PRD 3.5: "Approving a `REBUILD` quote additionally drives the instrument's condition
    axis to `REBUILD_REQUIRED` and fires Cascade B in full."

    Design: Difficulty/transitive_cascade/cascade_b_rebuild_approval_supersedes_depth_five
    """
    ctx = setup_rebuild_quote_over_voice_order()

    approved = validate_success(
        api.approve_quote(
            ctx["rebuild_quote"]["id"], make_client_headers(ctx["client"]["id"])
        )
    )
    assert approved["status"] == "APPROVED"

    instrument = read_instrument(ctx["instrument"]["id"])
    assert instrument["condition_status"] == "REBUILD_REQUIRED"

    order = read_service_order(ctx["order"]["id"])
    assert order["status"] == "VOIDED_BY_REBUILD"

    milestones = read_milestones(order["id"])
    assert [m["status"] for m in milestones] == ["CANCELLED"] * len(milestones)
    assert len(milestones) == 2

    voice_quote = validate_success(api.get_quote(ctx["voice_quote"]["id"], MANAGER))
    assert voice_quote["status"] == "APPROVED", (
        "the cascade voids the order, not the quote that produced it"
    )


def test_the_voided_order_refunds_its_unapplied_deposit(api):
    """PRD 2.11: "Hop 4: *because* the last non-terminal milestone of the order reached
    `CANCELLED`, a `DEPOSIT_REFUND` ledger row is appended for `deposit_held_cents` minus
    `deposit_applied_cents`, and `deposit_refunded_cents` is set to that amount. Hop 5:
    *because* the ledger changed, the client's balance is recomputed and the client's
    `version` is incremented by 1."
    PRD 2.10: "**Client money.** For every client, `account_credit_cents` equals the
    plain sum of `amount_cents` over **every** ledger row carrying that client's
    `client_id`, with no status filter of any kind."

    Design: Difficulty/transitive_cascade/cascade_b_rebuild_approval_supersedes_depth_five
    """
    ctx = setup_rebuild_quote_over_voice_order()
    client_id = ctx["client"]["id"]
    assert read_client(client_id)["account_credit_cents"] == 175000

    approve_quote(ctx["rebuild_quote"]["id"], client_id)

    order = read_service_order(ctx["order"]["id"])
    assert order["deposit_held_cents"] == 25000
    assert order["deposit_applied_cents"] == 0
    assert order["deposit_refunded_cents"] == 25000

    refunds = [
        row for row in read_ledger(client_id)
        if row["entry_type"] == "DEPOSIT_REFUND"
    ]
    assert [row["amount_cents"] for row in refunds] == [25000]
    assert read_client(client_id)["account_credit_cents"] == 200000


def test_rebuild_cannot_start_while_the_instrument_is_at_the_client_site(api):
    """PRD 2.8: "**Rebuild custody.** A `REBUILD` service order may only be started
    while its instrument's `custody_status` is `IN_SHOP`. Otherwise
    `ERR_INVALID_CUSTODY_STATE` (409). Applies to `POST /service-orders/{id}/start`."
    PRD 3.6: "Work starts when a technician starts the order. This requires status
    `PENDING`, requires `assigned_technician_id` to have been set, and — for a `REBUILD`
    only — requires the instrument's `custody_status` to be `IN_SHOP`, a gate that
    answers with `ERR_INVALID_CUSTODY_STATE`."
    PRD 3.3: "Anything above 35.0 is `TIER_3`, which has no upper bound."

    Design: Difficulty/cross_entity_state_dependency/rebuild_start_requires_instrument_custody_in_shop
    """
    ctx = setup_rebuild_order_pending(deviation=48.0)
    instrument = read_instrument(ctx["instrument"]["id"])
    assert instrument["custody_status"] == "AT_CLIENT_SITE"
    assert instrument["pitch_raise_tier"] == "TIER_3"
    assert instrument["planned_visit_count"] == 2

    response = api.start_service_order(ctx["order"]["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_CUSTODY_STATE.value)

    order = read_service_order(ctx["order"]["id"])
    assert order["status"] == "PENDING"
    for milestone in read_milestones(order["id"]):
        assert milestone["status"] == "PENDING"


def test_the_same_rebuild_start_succeeds_once_the_instrument_reaches_the_shop(api):
    """PRD 3.6: "Starting stamps `started_at` from the logical clock, bumps the order's
    `version` by 1, and moves **every** milestone of the order from `PENDING` to `READY`
    in one step, processed in `sequence_index` ascending order."
    PRD 3.6: "The contract total is divided by that count and rounded **down** to whole
    cents to give a share; every milestone except the last receives exactly that share,
    and the milestone with the **highest** `sequence_index` receives the contract total
    less the share multiplied by one fewer than the count — so the remainder always
    lands on the final stage."
    PRD 3.2: "From `IN_TRANSIT` the instrument reaches either `IN_SHOP` or
    `AT_CLIENT_SITE`; on both of those edges, when a job is quoted, the job advances
    `IN_TRANSIT → DELIVERED` and the instrument's `current_location_id` is set to that
    job's `destination_location_id`."

    Design: Difficulty/cross_entity_state_dependency/rebuild_start_requires_instrument_custody_in_shop
    """
    ctx = setup_rebuild_order_pending(deviation=48.0)

    set_custody(ctx["instrument"]["id"], "IN_TRANSIT")
    set_custody(ctx["instrument"]["id"], "IN_SHOP")

    started = validate_success(api.start_service_order(ctx["order"]["id"], MANAGER))
    assert started["status"] == "IN_PROGRESS"

    milestones = sorted(
        read_milestones(ctx["order"]["id"]), key=lambda m: m["sequence_index"]
    )
    assert [m["status"] for m in milestones] == ["READY"] * 4
    assert [m["amount_cents"] for m in milestones] == [340750, 340750, 340750, 340750]

    order = read_service_order(ctx["order"]["id"])
    assert order["contract_total_cents"] == 1363000
    assert order["deposit_held_cents"] == 545200
    assert_contracted_value_conservation(order, milestones)
