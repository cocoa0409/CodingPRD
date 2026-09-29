"""Writes refused because of state that lives on an entity the request never names.

In each scenario nothing about the refused request itself is wrong: it was legal
when it was raised, and it becomes legal again once the third entity moves back.
The pair of attempts either side of that move is what proves where the gate lives.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    TEST_USERS,
    make_brewer_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

AGREEMENT = {
    "per_fill_rate_cents": 2200,
    "replenishment_threshold_pct": 20,
}


def _allocate(order_id, agreement_id):
    """Allocate against the agreement's version as it stands right now."""
    return api_client.allocate_issuance_order(
        order_id,
        {"expected_agreement_version": fixtures.agreement_version(agreement_id)},
        OPERATOR,
    )


def _two_orders_raised_while_the_pool_was_still_open():
    """A four-keg pool with two orders already on the books, one for the whole
    fleet and one for a single keg.

    Neither order is defective; allocating the first is what empties the pool and
    makes the second impossible.
    """
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=4,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["pool_before"] = fixtures.read_pool(ctx["pool"]["id"])
    ctx["first_order"] = validate_success(
        api_client.create_issuance_order(
            factories.create_issuance_order_payload(ctx["agreement"]["id"], 4),
            OPERATOR,
        ),
        201,
    )
    ctx["second_order"] = validate_success(
        api_client.create_issuance_order(
            factories.create_issuance_order_payload(ctx["agreement"]["id"], 1),
            OPERATOR,
        ),
        201,
    )
    return ctx


def test_both_orders_are_admissible_while_the_pool_is_open():
    """With every keg on the floor the pool is `OPEN` at 100.00 percent, so a
    four-keg request and a one-keg request are both accepted and both sit in
    `REQUESTED`.

    PRD: "The pool's `posture` is not `FROZEN` — `ERR_POOL_FROZEN` (409), on order
    creation and order allocation."

    Design: Difficulty/cross_entity_state_dependency/order_allocate_blocked_by_frozen_pool_state
    """
    ctx = _two_orders_raised_while_the_pool_was_still_open()

    assert ctx["pool_before"]["kegs_total"] == 4
    assert ctx["pool_before"]["kegs_available"] == 4
    assert ctx["pool_before"]["available_pct"] == 100.00
    assert ctx["pool_before"]["posture"] == "OPEN"

    assert ctx["first_order"]["status"] == "REQUESTED"
    assert ctx["first_order"]["requested_keg_count"] == 4
    assert ctx["first_order"]["allocated_keg_count"] == 0
    assert ctx["second_order"]["status"] == "REQUESTED"
    assert ctx["second_order"]["requested_keg_count"] == 1


def test_allocating_the_whole_fleet_freezes_the_pool_and_suspends_the_agreement():
    """Drawing all four kegs leaves nothing on the floor, so `available_pct` falls
    to 0.00, the pool freezes, and the agreement on that pool is recomputed to
    `SUSPENDED` in the same request.

    PRD: "The cascade then fires once, after all kegs have moved: the pool's
    `kegs_available` falls and `kegs_circulating` rises by the number allocated,
    `available_pct` and `posture` are recomputed and the pool's `version`
    advances, and every `ACTIVE` agreement on that pool recomputes
    `float_posture`, each advancing its own `version`."

    PRD: "The agreement is `SUSPENDED` whenever the pool's `posture` is `FROZEN`
    **or** the brewer's `status` is `PROBATION` or `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_allocate_blocked_by_frozen_pool_state
    """
    ctx = _two_orders_raised_while_the_pool_was_still_open()
    agreement_id = ctx["agreement"]["id"]

    allocated = validate_success(_allocate(ctx["first_order"]["id"], agreement_id), 200)
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_keg_count"] == 4
    assert allocated["allocation_shortfall"] == 0

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_available"] == 0
    assert pool["kegs_circulating"] == 4
    assert pool["available_pct"] == 0.00
    assert pool["posture"] == "FROZEN"

    agreement = fixtures.read_agreement(agreement_id)
    assert agreement["status"] == "ACTIVE"
    assert agreement["float_posture"] == "SUSPENDED"
    assert agreement["kegs_at_brewer_count"] == 4


def test_the_second_allocate_is_refused_for_the_pool_and_not_for_the_brewer():
    """The refusal names the frozen pool, an entity the allocate call never
    mentions, while the brewer it does mention is untouched and still `ACTIVE`.

    PRD: "The pool's `posture` is not `FROZEN` — `ERR_POOL_FROZEN` (409), on order
    creation and order allocation."

    PRD: "Allocation also re-checks the gates it shares with order creation: the
    agreement must be `ACTIVE`, its `float_posture` must not be `SUSPENDED`, the
    brewer must not be `SUSPENDED`, the brewer's `chargeback_balance_cents` must
    be strictly below its `credit_limit_cents`, the pool must not be `FROZEN`, and
    a `RESTRICTED` pool caps the request at `restricted_max_kegs_per_order`."

    Design: Difficulty/cross_entity_state_dependency/order_allocate_blocked_by_frozen_pool_state
    """
    ctx = _two_orders_raised_while_the_pool_was_still_open()
    agreement_id = ctx["agreement"]["id"]

    validate_success(_allocate(ctx["first_order"]["id"], agreement_id), 200)

    refused = _allocate(ctx["second_order"]["id"], agreement_id)
    validate_error(refused, ApiErrorId.ERR_POOL_FROZEN.value, 409)

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["status"] == "ACTIVE"
    assert brewer["status_reason"] is None

    order = fixtures.read_order(ctx["second_order"]["id"])
    assert order["status"] == "REQUESTED"
    assert order["allocated_keg_count"] == 0

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_available"] == 0
    assert fixtures.read_agreement(agreement_id)["kegs_at_brewer_count"] == 4


def _one_keg_dispatched_to_a_brewer_the_desk_can_move():
    """An eight-keg pool with a single keg dispatched to the brewer, so the pool
    sits comfortably `OPEN` at 87.50 percent for the whole scenario and the only
    thing that moves is the brewer's standing."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=8,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    ctx["order"] = order
    ctx["keg_id"] = order["allocated_keg_ids"][0]
    ctx["agreement_before"] = fixtures.read_agreement(ctx["agreement"]["id"])
    ctx["pool_before"] = fixtures.read_pool(ctx["pool"]["id"])
    return ctx


def _set_brewer_status(brewer_id, status, status_reason):
    return api_client.set_brewer_status(
        brewer_id,
        factories.brewer_status_payload(status, status_reason=status_reason),
        OPERATOR,
    )


def _fill_attempt(keg_id, brewer_id):
    return api_client.scan_keg(
        keg_id,
        factories.fill_scan_payload(brewer_id, "2026-08-01T02:00:00Z", "RDG"),
        make_brewer_headers(brewer_id),
    )


def test_one_keg_against_a_ten_keg_float_reads_tight_and_not_suspended():
    """A float of ten at a twenty percent threshold has a thin-float ceiling of
    two, so one keg at the brewer is `TIGHT`, and the pool at 87.50 percent has
    nothing to do with it.

    PRD: "Otherwise, letting the thin-float ceiling be `float_size_kegs`
    multiplied by `replenishment_threshold_pct`, divided by 100 and floored to a
    whole number of kegs, the agreement is `TIGHT` when `kegs_at_brewer_count` is
    less than or equal to that ceiling, and `HEALTHY` otherwise."

    PRD: "Flooring matters: a float of 10 kegs with a 20 percent threshold gives a
    ceiling of 2, so 2 kegs at the brewer reads `TIGHT` while 3 reads `HEALTHY`."

    Design: Difficulty/cross_entity_state_dependency/fill_scan_blocked_by_suspended_float_posture_from_brewer_status
    """
    ctx = _one_keg_dispatched_to_a_brewer_the_desk_can_move()

    assert ctx["agreement_before"]["float_size_kegs"] == 10
    assert ctx["agreement_before"]["replenishment_threshold_pct"] == 20
    assert ctx["agreement_before"]["kegs_at_brewer_count"] == 1
    assert ctx["agreement_before"]["float_posture"] == "TIGHT"
    assert ctx["pool_before"]["available_pct"] == 87.50
    assert ctx["pool_before"]["posture"] == "OPEN"


def test_probation_suspends_the_float_and_the_fill_is_refused_for_the_posture():
    """Moving the brewer to probation suspends its agreement, and the fill is then
    refused for that posture rather than for the brewer's own standing, because
    probation is expressly permitted at the brewer gate.

    PRD: "Any such override immediately recomputes `float_posture` on every
    `ACTIVE` float agreement of that brewer — moving the brewer to `PROBATION` or
    `SUSPENDED` forces those agreements to `SUSPENDED`, while returning the brewer
    to `ACTIVE` releases them."

    PRD: "The governing agreement's `float_posture` is not `SUSPENDED` —
    `ERR_FLOAT_SUSPENDED` (409), on order allocation and a fill scan."

    PRD: "The brewer's `status` is not `SUSPENDED`; `PROBATION` is permitted here
    and is instead expressed through `float_posture`."

    Design: Difficulty/cross_entity_state_dependency/fill_scan_blocked_by_suspended_float_posture_from_brewer_status
    """
    ctx = _one_keg_dispatched_to_a_brewer_the_desk_can_move()
    brewer_id = ctx["brewer"]["id"]

    moved = validate_success(
        _set_brewer_status(brewer_id, "PROBATION", "Operator review of unreturned assets"),
        200,
    )
    assert moved["status"] == "PROBATION"
    assert fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "SUSPENDED"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["available_pct"] == 87.50
    assert pool["posture"] == "OPEN"

    refused = _fill_attempt(ctx["keg_id"], brewer_id)
    validate_error(refused, ApiErrorId.ERR_FLOAT_SUSPENDED.value, 409)

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert keg["fill_count"] == 0
    assert keg["scan_count"] == 0
    assert fixtures.read_agreement(ctx["agreement"]["id"])["billed_fills_count"] == 0


def test_restoring_the_brewer_reopens_the_byte_identical_fill():
    """Returning the brewer to `ACTIVE` releases the agreement back to `TIGHT`, and
    the very same fill request that was refused now posts a 2200-cent charge.

    PRD: "The suspension lifts by recompute as soon as the suspending condition
    clears — the pool leaves `FROZEN` or the brewer returns to `ACTIVE` — at which
    point the agreement lands on `TIGHT` or `HEALTHY` according to the same
    ceiling comparison."

    PRD: "The base is the agreement's current `per_fill_rate_cents` — taken from
    the agreement, not from the order's `per_fill_price_cents_pinned`."

    Design: Difficulty/cross_entity_state_dependency/fill_scan_blocked_by_suspended_float_posture_from_brewer_status
    """
    ctx = _one_keg_dispatched_to_a_brewer_the_desk_can_move()
    brewer_id = ctx["brewer"]["id"]
    agreement_id = ctx["agreement"]["id"]

    _set_brewer_status(brewer_id, "PROBATION", "Operator review of unreturned assets")
    validate_error(
        _fill_attempt(ctx["keg_id"], brewer_id),
        ApiErrorId.ERR_FLOAT_SUSPENDED.value,
        409,
    )

    restored = validate_success(
        _set_brewer_status(brewer_id, "ACTIVE", "Review closed"), 200
    )
    assert restored["status"] == "ACTIVE"
    assert fixtures.read_agreement(agreement_id)["float_posture"] == "TIGHT"

    scan = validate_success(_fill_attempt(ctx["keg_id"], brewer_id), 201)
    assert scan["scan_point"] == "FILL"
    assert scan["dwell_days_closed"] == 0
    assert scan["fill_charge_net_cents"] == 2200

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "FILLED"
    assert keg["fill_count"] == 1
    assert keg["filled_brand_code"] == "RDG"

    agreement = fixtures.read_agreement(agreement_id)
    assert agreement["billed_fills_count"] == 1
    assert agreement["billed_amount_cents"] == 2200

    brewer = fixtures.read_brewer(brewer_id)
    assert brewer["lifetime_fill_count"] == 1
    assert brewer["chargeback_balance_cents"] == 0
