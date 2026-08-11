"""Service orders, the milestone schedule, releases, acceptances and rejections."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_milestone,
    assert_contracted_value_conservation,
    assert_service_order,
    fund_client,
    make_client_headers,
    make_shop_manager_headers,
    read_client,
    read_ledger,
    read_milestones,
    read_service_order,
    release_milestone,
    setup_approved_quote_without_order,
    setup_order,
    setup_rebuild_order_pending,
    setup_voice_order_in_progress,
    setup_voice_order_on_hold_after_no_show,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


def test_milestone_waterfall_lands_the_remainder_on_the_highest_index(api):
    """PRD 3.6: "The number of milestones is fixed by the service class: 1 for a `TUNE`,
    1 for a `PITCH_RAISE`, 2 for a `REGULATE`, 2 for a `VOICE` and 4 for a `REBUILD`.
    The contract total is divided by that count and rounded **down** to whole cents to
    give a share; every milestone except the last receives exactly that share, and the
    milestone with the **highest** `sequence_index` receives the contract total less the
    share multiplied by one fewer than the count — so the remainder always lands on the
    final stage. `sequence_index` is 1-based."
    PRD 3.6: "It copies `instrument_id`, `client_id` and `service_type` from the quote,
    copies `contract_total_cents` from the quote's `total_cents` — a figure that is
    never re-derived afterwards, no matter what happens to prices — and copies
    `deposit_held_cents` from the quote's `deposit_required_cents`."
    PRD 3.6: "If the base figure so obtained is **strictly greater** than 300 minutes,
    `visit_plan_variant` is `SPLIT_VISIT` and `estimated_minutes` is that base plus
    another 35 minutes, because a second visit repeats the setup pass; otherwise
    `visit_plan_variant` is `SINGLE_VISIT` and `estimated_minutes` equals the base
    exactly."

    Design: Corner/calculations/milestone_waterfall_remainder_lands_on_the_last_index
    """
    ctx = setup_rebuild_order_pending(client_type="DEALER", deviation=55.0)
    quote, order = ctx["quote"], ctx["order"]

    assert quote["subtotal_cents"] == 1189000
    assert quote["loyalty_discount_cents"] == 35670

    assert_service_order(order)
    assert order["contract_total_cents"] == 1153330
    assert order["deposit_held_cents"] == 461332
    assert order["visit_plan_variant"] == "SPLIT_VISIT"
    assert order["estimated_minutes"] == 2435

    milestones = read_milestones(order["id"])
    amounts = [m["amount_cents"] for m in sorted(milestones, key=lambda m: m["sequence_index"])]
    assert amounts == [288332, 288332, 288332, 288334]
    assert sum(amounts) == order["contract_total_cents"]
    assert_contracted_value_conservation(order, milestones)


def test_completion_is_refused_while_a_milestone_is_unaccepted(api):
    """PRD 2.8: "**Completion gate.** A service order may only be completed when every
    one of its milestones has status `ACCEPTED`. Otherwise `ERR_INVALID_STATE` (409).
    Applies to `POST /service-orders/{id}/complete`."
    PRD 3.6: "The applied portion is the smaller of the milestone's `amount_cents` and
    that unapplied deposit; the residual is the milestone amount less the applied
    portion."
    PRD 3.9: "Completing a service order mints a warranty automatically; there is no
    operation that creates one directly."

    Design: Corner/state_machines/service_order_complete_with_unaccepted_milestone_returns_invalid_state
    """
    ctx = setup_voice_order_in_progress(funding=200000)
    order, milestones = ctx["order"], ctx["milestones"]
    first = min(milestones, key=lambda m: m["sequence_index"])
    release_milestone(first["id"], "mgr-completion-gate")
    accept_milestone(first["id"], ctx["client"]["id"])

    response = api.complete_service_order(order["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_service_order(order["id"])
    assert after["status"] == "IN_PROGRESS"
    assert after["billed_cents"] == 21000
    assert after["unbilled_cents"] == 21000
    assert after["deposit_applied_cents"] == 21000, (
        "the 25000 deposit covered the whole milestone, so nothing was charged"
    )

    warranties, _ = validate_paginated(
        api.list_warranties(MANAGER, params={"service_order_id": order["id"]})
    )
    assert warranties == [], "no warranty is minted until the order completes"


def test_apprentice_cannot_be_assigned_a_voice_service_order(api):
    """PRD 3.7: "Each service class demands a minimum rank — 1 for a `TUNE`, 2 for a
    `PITCH_RAISE`, 2 for a `REGULATE`, 2 for a `VOICE` and 3 for a `REBUILD` — and the
    technician's rank must be at least that minimum. The gate is checked in three
    places: when a service order is created with an assigned technician, when an
    appointment is booked onto a technician's day, and when a route day is dispatched.
    Every failure answers `ERR_TECH_CERT_INSUFFICIENT`."
    PRD 3.7: "Certification is ranked and compared numerically: an `APPRENTICE` ranks 1,
    a `JOURNEYMAN` ranks 2 and a `MASTER` ranks 3."

    Design: Corner/validations/apprentice_technician_cannot_take_a_voice_service_order
    """
    ctx = setup_approved_quote_without_order(
        service_type="VOICE", certification_level="APPRENTICE"
    )

    response = api.create_service_order(
        {
            "quote_id": ctx["quote"]["id"],
            "assigned_technician_id": ctx["technician"]["id"],
        },
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_TECH_CERT_INSUFFICIENT.value)

    rows, _ = validate_paginated(
        api.list_service_orders(MANAGER, params={"quote_id": ctx["quote"]["id"]})
    )
    assert rows == [], "no order exists after the certification refusal"


def test_milestone_acceptance_without_enough_credit_is_refused(api):
    """PRD 2.8: "**Credit sufficiency.** Accepting a milestone requires the client's
    `account_credit_cents` plus the order's unapplied deposit — `deposit_held_cents`
    less `deposit_applied_cents`, less `deposit_refunded_cents`, less
    `deposit_forfeited_cents` — to be at least the milestone's `amount_cents`. Otherwise
    `ERR_INSUFFICIENT_CREDIT` (402). Applies to `POST /milestones/{id}/accept`."
    PRD 3.6: "When the residual is greater than 0, a `MILESTONE_CHARGE` ledger row is
    appended for the negated residual and the client's balance is recomputed."

    Design: Corner/validations/milestone_accept_without_enough_credit_is_rejected
    """
    ctx = setup_order(
        service_type="VOICE", funding=25000, condition="SERVICEABLE", start=True
    )
    client = ctx["client"]
    ordered = sorted(ctx["milestones"], key=lambda m: m["sequence_index"])
    first, second = ordered[0], ordered[1]

    release_milestone(first["id"], "mgr-thin-credit")
    accept_milestone(first["id"], client["id"])
    release_milestone(second["id"], "mgr-thin-credit")

    response = api.accept_milestone(second["id"], make_client_headers(client["id"]))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value)

    order = read_service_order(ctx["order"]["id"])
    assert order["billed_cents"] == 21000
    assert order["deposit_applied_cents"] == 21000
    assert read_client(client["id"])["account_credit_cents"] == 0

    fund_client(client["id"], 17000, "top up")
    accepted = validate_success(
        api.accept_milestone(second["id"], make_client_headers(client["id"]))
    )
    assert accepted["status"] == "ACCEPTED"
    charges = [
        row for row in read_ledger(client["id"])
        if row["entry_type"] == "MILESTONE_CHARGE"
    ]
    assert [row["amount_cents"] for row in charges] == [-17000]


def test_third_milestone_rejection_is_refused_by_the_retry_cap(api):
    """PRD 3.6: "A third rejection is refused with `ERR_ATTEMPT_LIMIT_EXCEEDED`, since
    `rejection_count` must be below 2 to reject again."
    PRD 2.8: "**Capped retries.** `reschedule_count` must be below 2, `rejection_count`
    must be below 2, and `claim_count` must be below 2. Otherwise
    `ERR_ATTEMPT_LIMIT_EXCEEDED` (409)."

    Design: Difficulty/non_linear_state_machine/milestone_capped_rejection_loop_on_third_attempt
    """
    ctx = setup_voice_order_in_progress(funding=200000)
    client = ctx["client"]
    first = min(ctx["milestones"], key=lambda m: m["sequence_index"])
    releaser = "mgr-release-loop"
    client_hdrs = make_client_headers(client["id"])

    for reason in ("hammer voicing uneven", "still uneven"):
        release_milestone(first["id"], releaser)
        validate_success(api.reject_milestone(first["id"], {"reason": reason}, client_hdrs))
    release_milestone(first["id"], releaser)

    response = api.reject_milestone(
        first["id"], {"reason": "third complaint"}, client_hdrs
    )
    validate_error(response, ApiErrorId.ERR_ATTEMPT_LIMIT_EXCEEDED.value)

    milestone = next(
        m for m in read_milestones(ctx["order"]["id"]) if m["id"] == first["id"]
    )
    assert milestone["status"] == "RELEASED", "the refused rejection left the third release standing"
    assert milestone["rejection_count"] == 2
    assert milestone["released_by_user_id"] == releaser
    assert read_service_order(ctx["order"]["id"])["billed_cents"] == 0


def test_milestone_rejection_returns_it_to_ready_and_clears_the_releaser(api):
    """PRD 3.6: "**Rejection** carries an optional `reason`, increments
    `rejection_count` by 1, clears `released_by_user_id` and `released_at` back to null,
    and returns the milestone to `READY` — the intermediate `REJECTED` value is a
    waypoint within the same request and is never the persisted result."
    PRD 3.6: "A `ShopManager` releases a `READY` milestone for client acceptance while
    the order is `IN_PROGRESS`, which stamps `released_by_user_id` with the acting
    `X-User-ID` and `released_at` from the clock and bumps the milestone's `version` by
    1."

    Design: Difficulty/non_linear_state_machine/milestone_capped_rejection_loop_on_third_attempt
    """
    ctx = setup_voice_order_in_progress(funding=200000)
    first = min(ctx["milestones"], key=lambda m: m["sequence_index"])

    released = release_milestone(first["id"], "mgr-release-loop-2")
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "mgr-release-loop-2"

    rejected = validate_success(
        api.reject_milestone(
            first["id"], {"reason": "hammer voicing uneven"},
            make_client_headers(ctx["client"]["id"]),
        )
    )
    assert rejected["status"] == "READY", "REJECTED is never the persisted result"
    assert rejected["rejection_count"] == 1
    assert rejected["released_by_user_id"] is None
    assert rejected["released_at"] is None


def test_milestone_sequence_rung_pre_empts_the_deposit_rung(api):
    """PRD 2.8: "**Milestone sequence.** A milestone may only be released when every
    milestone of the same order with a lower `sequence_index` has status `ACCEPTED`.
    Otherwise `ERR_MILESTONE_SEQUENCE` (409). Applies to `POST /milestones/{id}/release`."
    PRD 2.8: "The server evaluates every request against one ordered ladder and returns
    the **first** error it reaches; later rungs are never evaluated once an earlier one
    has failed."
    PRD 3.6: "Release is refused with `ERR_MILESTONE_SEQUENCE` while any lower
    `sequence_index` on the same order is not yet `ACCEPTED`, and refused with
    `ERR_DEPOSIT_NOT_SETTLED` when the milestone at `sequence_index` 1 is being released
    while the client's `account_credit_cents` is negative."

    Design: Difficulty/priority_pair_validation_conflict/milestone_sequence_beats_deposit_not_settled
    """
    ctx = setup_voice_order_in_progress(funding=None)
    ordered = sorted(ctx["milestones"], key=lambda m: m["sequence_index"])
    second = ordered[1]

    response = api.release_milestone(
        second["id"], make_shop_manager_headers("mgr-sequence-pair")
    )
    validate_error(response, ApiErrorId.ERR_MILESTONE_SEQUENCE.value)

    milestones = {m["id"]: m for m in read_milestones(ctx["order"]["id"])}
    assert milestones[second["id"]]["status"] == "READY"
    assert milestones[second["id"]]["released_by_user_id"] is None


def test_unfunded_deposit_charge_leaves_the_client_in_debit(api):
    """PRD 3.6: "When `deposit_held_cents` is greater than 0, a `DEPOSIT_CHARGE` ledger
    row is appended for the negated deposit and the client's balance is recomputed."
    PRD 2.10: "**Client money.** For every client, `account_credit_cents` equals the
    plain sum of `amount_cents` over **every** ledger row carrying that client's
    `client_id`, with no status filter of any kind."
    PRD 3.6: "Each milestone begins at status `PENDING` with `rejection_count` 0 and
    `released_by_user_id`, `released_at` and `accepted_at` all null."

    Design: Difficulty/priority_pair_validation_conflict/milestone_sequence_beats_deposit_not_settled
    """
    ctx = setup_voice_order_in_progress(funding=None)

    assert read_client(ctx["client"]["id"])["account_credit_cents"] == -25000
    charges = [
        row for row in read_ledger(ctx["client"]["id"])
        if row["entry_type"] == "DEPOSIT_CHARGE"
    ]
    assert [row["amount_cents"] for row in charges] == [-25000]

    for milestone in read_milestones(ctx["order"]["id"]):
        assert milestone["status"] == "READY"
        assert milestone["released_by_user_id"] is None


def test_milestone_release_is_refused_while_its_order_is_on_hold(api):
    """PRD 2.8: "**Cross-entity gate, first pair.** A milestone may only be released
    while its service order is `IN_PROGRESS`, and a parts allocation may only be
    consumed while its service order is `IN_PROGRESS` or `COMPLETED`. Otherwise
    `ERR_INVALID_STATE` (409). Applies to `POST /milestones/{id}/release` and
    `POST /parts-allocations/{id}/consume`."
    PRD 3.7: "A no-show at the door moves the stop `EN_ROUTE → NO_SHOW`, simultaneously
    drives `scheduling_status` to `CANCELLED`, assesses the dispatched-tier cancellation
    fee, appends the resulting ledger row, recomputes the day's committed minutes and
    stop count with a version bump, and puts any linked `IN_PROGRESS` order into
    `ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/milestone_release_requires_service_order_in_progress
    """
    ctx = setup_voice_order_on_hold_after_no_show()
    first = min(ctx["milestones"], key=lambda m: m["sequence_index"])

    assert ctx["order"]["status"] == "ON_HOLD"
    assert first["status"] == "READY", "the milestone's own state is perfectly valid"
    assert ctx["appointment"]["fulfillment_status"] == "NO_SHOW"
    assert ctx["appointment"]["scheduling_status"] == "CANCELLED"

    response = api.release_milestone(
        first["id"], make_shop_manager_headers("mgr-on-hold")
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


def test_resuming_the_order_unblocks_the_identical_milestone_release(api):
    """PRD 3.6: "The one producer of `ON_HOLD` is a no-show on a linked appointment; a
    `ShopManager` resumes a held order back to `IN_PROGRESS` provided the client is
    `ACTIVE`."
    PRD 3.6: "A `ShopManager` releases a `READY` milestone for client acceptance while
    the order is `IN_PROGRESS`, which stamps `released_by_user_id` with the acting
    `X-User-ID` and `released_at` from the clock and bumps the milestone's `version` by
    1."
    PRD 3.7: "Under the **dispatched tier**, selected when `fulfillment_status` is
    `EN_ROUTE` or `IN_PROGRESS`, the fee is 60 percent of `estimated_price_cents`
    rounded half up, or 15000 cents, whichever is larger — with no lead-time
    consideration at all, so a cancellation ten days out but after dispatch costs more
    than one an hour out before dispatch."

    Design: Difficulty/cross_entity_state_dependency/milestone_release_requires_service_order_in_progress
    """
    ctx = setup_voice_order_on_hold_after_no_show()
    first = min(ctx["milestones"], key=lambda m: m["sequence_index"])

    assert ctx["appointment"]["estimated_price_cents"] == 42000
    assert ctx["appointment"]["cancellation_fee_cents"] == 25200, (
        "60 percent of 42000 beats the 15000 floor"
    )

    resumed = validate_success(api.resume_service_order(ctx["order"]["id"], MANAGER))
    assert resumed["status"] == "IN_PROGRESS"

    released = validate_success(
        api.release_milestone(first["id"], make_shop_manager_headers("mgr-resumed"))
    )
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "mgr-resumed"
