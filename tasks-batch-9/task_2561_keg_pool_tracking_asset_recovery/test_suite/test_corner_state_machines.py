"""Declared transitions, refused transitions and terminal-state lockdown.

Each scenario drives one lifecycle edge of the contract — an activation, a
termination, a dispatch, a booking, a release, a hold or a claim response — and
reads back every row the edge is declared to touch, together with the rows it
is declared to leave alone.  Refusals are always followed by the identical call
made legal, so a 409 is never mistaken for a broken payload.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_census
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_brewer_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
TECHNICIAN = make_technician_headers(TECHNICIAN_USER_ID)
SECOND_TECHNICIAN = make_technician_headers(SECOND_TECHNICIAN_USER_ID)
ANALYST = make_analyst_headers(ANALYST_USER_ID)

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}

EMPTY_POOL = {
    "pool_code": "HB-30L",
    "size_liters": 30,
    "stainless_weight_kg": 9.5,
    "replacement_cost_cents": 19000,
    "region_code": "CO",
}

RATE = 2200


def _two_drafted_agreements_one_stocked_one_empty():
    """One brewer holding two drafted agreements: one on a two-keg pool that
    reads `OPEN`, one on a pool with no kegs at all, which therefore reads
    `FROZEN`.  Both floats are four kegs at the default 20 percent threshold.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    stocked_pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(stocked_pool["id"], ["K-0001", "K-0002"])
    empty_pool = fixtures.create_pool(**EMPTY_POOL)
    stocked_agreement = fixtures.create_agreement(
        brewer["id"], stocked_pool["id"], 4, per_fill_rate_cents=RATE
    )
    empty_agreement = fixtures.create_agreement(
        brewer["id"], empty_pool["id"], 4, per_fill_rate_cents=1900
    )
    return {
        "index": index,
        "brewer": brewer,
        "stocked_pool": stocked_pool,
        "empty_pool": empty_pool,
        "kegs": kegs,
        "drafted_on_stocked": stocked_agreement,
        "drafted_on_empty": empty_agreement,
        "activated_on_stocked": fixtures.activate_agreement(
            stocked_agreement["id"], "2026-08-01"
        ),
        "activated_on_empty": fixtures.activate_agreement(
            empty_agreement["id"], "2026-08-01"
        ),
    }


def test_activation_prices_the_first_posture_as_tight_on_an_empty_brewer_shelf():
    """The float opens `ACTIVE` at the supplied date and computes its posture for
    the very first time: nothing is at the brewer yet, and 0 is at or below the
    floored ceiling of four kegs at 20 percent, so the agreement reads `TIGHT`
    with all four kegs signalled for replenishment.

    PRD: "On success the agreement moves `DRAFT → ACTIVE`, records the
    `effective_date`, computes `float_posture` for the first time, and advances
    its `version`."

    PRD: "Otherwise, letting the thin-float ceiling be `float_size_kegs`
    multiplied by `replenishment_threshold_pct`, divided by 100 and floored to a
    whole number of kegs, the agreement is `TIGHT` when `kegs_at_brewer_count`
    is less than or equal to that ceiling, and `HEALTHY` otherwise."

    PRD: "While the posture is `TIGHT` it is the float size minus
    `kegs_at_brewer_count`, or 0 if that difference would be negative."

    Design: Corner/state_machines/float_agreement_activation_sets_active_and_computes_the_first_posture
    """
    ctx = _two_drafted_agreements_one_stocked_one_empty()

    drafted = ctx["drafted_on_stocked"]
    assert drafted["status"] == "DRAFT"
    assert drafted["version"] == 1
    assert drafted["effective_date"] is None
    assert drafted["replenishment_threshold_pct"] == 20

    activated = ctx["activated_on_stocked"]
    assert activated["status"] == "ACTIVE"
    assert activated["effective_date"] == "2026-08-01"
    assert activated["version"] == 2
    assert activated["float_posture"] == "TIGHT"
    assert activated["kegs_at_brewer_count"] == 0
    assert activated["kegs_issued_count"] == 0
    assert activated["pending_replenishment_kegs"] == 4

    pool = fixtures.read_pool(ctx["stocked_pool"]["id"])
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


def test_activation_on_a_pool_with_no_kegs_lands_straight_in_suspended():
    """The identical activation against a pool that holds no kegs is accepted as
    a contract and immediately suspended as a float: the pool is `FROZEN`, the
    cross-entity gate wins over the ceiling, and the replenishment signal is 0
    rather than the four kegs the ceiling alone would ask for.

    PRD: "The agreement is `SUSPENDED` whenever the pool's `posture` is `FROZEN`
    **or** the brewer's `status` is `PROBATION` or `SUSPENDED`."

    PRD: "While the posture is `HEALTHY` or `SUSPENDED` it is 0."

    PRD: "A newly created pool therefore opens with every counter at 0,
    `available_pct` at 0.00 and `posture` at `FROZEN`: an empty pool cannot issue
    float."

    Design: Corner/state_machines/float_agreement_activation_sets_active_and_computes_the_first_posture
    """
    ctx = _two_drafted_agreements_one_stocked_one_empty()

    empty_pool = fixtures.read_pool(ctx["empty_pool"]["id"])
    assert empty_pool["kegs_total"] == 0
    assert empty_pool["available_pct"] == 0.00
    assert empty_pool["posture"] == "FROZEN"

    activated = ctx["activated_on_empty"]
    assert activated["status"] == "ACTIVE"
    assert activated["effective_date"] == "2026-08-01"
    assert activated["float_posture"] == "SUSPENDED"
    assert activated["pending_replenishment_kegs"] == 0
    assert activated["kegs_at_brewer_count"] == 0

    # Activation is a write on the agreement alone.
    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["status"] == "ACTIVE"
    assert brewer["version"] == 1


def _one_activated_agreement_on_a_two_keg_pool(float_size_kegs=2, keg_tags=None):
    """A brewer, a pool stocked with kegs, and one agreement already activated
    effective the logical day.  Returned with the kegs in import order, which is
    also allocation rank order for freshly imported kegs.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(pool["id"], keg_tags or ["K-0001", "K-0002"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], float_size_kegs,
        effective_date="2026-08-01",
        per_fill_rate_cents=RATE,
    )
    return {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "kegs": kegs,
        "agreement": agreement,
    }


def test_reactivating_the_same_agreement_is_a_state_refusal_not_a_uniqueness_one():
    """The second activation of an already `ACTIVE` agreement is refused on the
    state precondition, not on the one-active-agreement-per-pair rule: that rule
    speaks of *another* agreement, and there is no second row here.

    PRD: "Activation requires the agreement to be in `DRAFT`, requires the
    brewer's `status` not to be `SUSPENDED` — refused with `ERR_BREWER_SUSPENDED`
    otherwise — and requires that no other agreement for the same brewer and pool
    is already `ACTIVE`, refused with `ERR_AGREEMENT_ALREADY_ACTIVE`."

    PRD: "The target resource sits in a state from which the requested transition
    is declared: order `status` for allocate, dispatch and cancel; cycle `stage`
    for step recording and release; `assessment_status` for dispute and resolve;
    `chargeback_status` for chargeback resolution; claim `status` for a response;
    investigation `status` for a status change; keg `custody_state` being
    `IN_FLOAT` or `IN_SERVICE` for a service-cycle booking; and, on a fill scan,
    the keg's governing issuance order being `DISPATCHED`. Failure is
    `ERR_INVALID_STATE` (409)."

    PRD: "At most one `ACTIVE` float agreement per brewer-and-pool pair —
    `ERR_AGREEMENT_ALREADY_ACTIVE` (409), on activation."

    Design: Corner/state_machines/repeat_activation_of_an_active_agreement_returns_invalid_state
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    agreement_id = ctx["agreement"]["id"]

    refused = api_client.activate_float_agreement(
        agreement_id, {"effective_date": "2026-08-01"}, OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)

    agreement = fixtures.read_agreement(agreement_id)
    assert agreement["status"] == "ACTIVE"
    assert agreement["version"] == 2
    assert agreement["effective_date"] == "2026-08-01"
    assert agreement["float_posture"] == "TIGHT"


def _a_float_recalled_from_the_brewer_before_termination():
    """One keg of a two-keg float issued to the brewer, then a termination
    attempted, then the order cancelled to bring the keg home, then the identical
    termination attempted again.  Every intermediate read is captured.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    agreement_id = ctx["agreement"]["id"]
    order = fixtures.create_order(agreement_id, 1)
    fixtures.allocate_order(order["id"], agreement_id)

    reason = "brewer closing the account"
    ctx["premature"] = api_client.terminate_float_agreement(
        agreement_id, {"terminated_reason": reason}, OPERATOR
    )
    ctx["after_refusal"] = fixtures.read_agreement(agreement_id)
    ctx["cancelled_order"] = fixtures.cancel_order(
        order["id"], cancel_reason="float recall before termination"
    )
    ctx["after_cancel"] = fixtures.read_agreement(agreement_id)
    ctx["terminated"] = validate_success(
        api_client.terminate_float_agreement(
            agreement_id, {"terminated_reason": reason}, OPERATOR
        )
    )
    ctx["order"] = order
    ctx["terminated_reason"] = reason
    return ctx


def test_terminating_while_one_keg_is_still_at_the_brewer_is_refused():
    """With one keg `ISSUED_TO_BREWER` the contract cannot be closed, and the
    refusal leaves the agreement exactly as it stood — still `ACTIVE`, still on
    the version the allocation left it at, with no reason recorded.

    PRD: "From `ACTIVE`, termination is only permitted once all float has come
    home: `kegs_at_brewer_count` must be 0 and no order of the agreement may sit
    in `REQUESTED`, `ALLOCATED` or `PARTIALLY_ALLOCATED`."

    PRD: "An agreement may only be terminated when its `kegs_at_brewer_count` is
    0 and no order of the agreement sits in `REQUESTED`, `ALLOCATED` or
    `PARTIALLY_ALLOCATED` — `ERR_AGREEMENT_FLOAT_OUTSTANDING` (409)."

    Design: Corner/state_machines/agreement_termination_with_outstanding_float_rejected
    """
    ctx = _a_float_recalled_from_the_brewer_before_termination()

    validate_error(
        ctx["premature"], ApiErrorId.ERR_AGREEMENT_FLOAT_OUTSTANDING.value, 409
    )

    refused_state = ctx["after_refusal"]
    assert refused_state["status"] == "ACTIVE"
    assert refused_state["version"] == 3
    assert refused_state["terminated_reason"] is None
    assert refused_state["kegs_at_brewer_count"] == 1
    assert refused_state["float_posture"] == "HEALTHY"


def test_recalling_the_keg_lets_the_identical_termination_through():
    """Cancelling the order returns the keg, empties the brewer's shelf and moves
    the posture back to `TIGHT`; the same termination call then succeeds, and the
    posture it froze at is the one the recall left behind.

    PRD: "Cancelling an allocated or partially allocated order returns exactly
    the kegs named in `allocated_keg_ids` — that is, `allocated_keg_count` kegs,
    not `requested_keg_count` — each moving `ISSUED_TO_BREWER → IN_FLOAT` while
    clearing `current_brewer_id`, `issuance_order_id` and `dwell_started_at`,
    resetting `dwell_flag` to `WITHIN_LIMIT`, and advancing its own `version`."

    PRD: "On termination the agreement moves to `TERMINATED`, records the reason,
    advances its `version`, and leaves any still-open orders exactly as they are
    — those orders simply can never be allocated or dispatched again."

    PRD: "A `TERMINATED` agreement keeps whatever `float_posture` it last held,
    frozen, and gates nothing thereafter; an `ACTIVE` agreement can cycle
    `HEALTHY → TIGHT → SUSPENDED → TIGHT` any number of times without its
    `status` ever moving."

    Design: Corner/state_machines/agreement_termination_with_outstanding_float_rejected
    """
    ctx = _a_float_recalled_from_the_brewer_before_termination()

    recalled_keg = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert recalled_keg["custody_state"] == "IN_FLOAT"
    assert recalled_keg["current_brewer_id"] is None
    assert recalled_keg["issuance_order_id"] is None
    assert recalled_keg["dwell_started_at"] is None

    after_cancel = ctx["after_cancel"]
    assert after_cancel["kegs_at_brewer_count"] == 0
    assert after_cancel["float_posture"] == "TIGHT"
    assert after_cancel["pending_replenishment_kegs"] == 2
    assert after_cancel["version"] == 4

    terminated = ctx["terminated"]
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_reason"] == ctx["terminated_reason"]
    assert terminated["version"] == 5
    assert terminated["float_posture"] == "TIGHT"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_available"] == 2
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


def _a_requested_order_dispatched_before_and_after_allocation():
    """One order for a single keg left in `REQUESTED`, dispatched once too early,
    then allocated and dispatched with the identical payload.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    agreement_id = ctx["agreement"]["id"]
    order = fixtures.create_order(agreement_id, 1)

    ctx["premature_dispatch"] = api_client.dispatch_issuance_order(
        order["id"], {"dispatched_at": "2026-08-01T01:00:00Z"}, OPERATOR
    )
    ctx["order_after_refusal"] = fixtures.read_order(order["id"])
    ctx["pool_after_refusal"] = fixtures.read_pool(ctx["pool"]["id"])
    ctx["keg_after_refusal"] = fixtures.read_keg(ctx["kegs"][0]["id"])
    ctx["allocated"] = fixtures.allocate_order(order["id"], agreement_id)
    ctx["dispatched"] = fixtures.dispatch_order(
        order["id"], "2026-08-01T01:00:00Z"
    )
    ctx["order"] = order
    return ctx


def test_dispatching_a_requested_order_is_refused_and_moves_nothing():
    """There is no `REQUESTED → DISPATCHED` edge, so the truck cannot leave before
    the kegs are committed: the order keeps its opening shape and the pool census
    has not moved a keg.

    PRD: "Dispatch is permitted from `ALLOCATED` and from `PARTIALLY_ALLOCATED`,
    with identical effects in both cases, and requires the agreement still to be
    `ACTIVE`."

    PRD: "The order records `brewer_id` denormalised from the agreement at
    creation and never re-derived thereafter, opens in `status` `REQUESTED` with
    `allocated_keg_count` at 0, `allocated_keg_ids` as an empty array,
    `allocation_shortfall` at 0 and `per_fill_price_cents_pinned`, `dispatched_at`
    and `cancel_reason` all unset."

    PRD: "Creating an order touches no keg and moves no census counter."

    Design: Corner/state_machines/dispatch_on_a_requested_order_returns_invalid_state
    """
    ctx = _a_requested_order_dispatched_before_and_after_allocation()

    validate_error(ctx["premature_dispatch"], ApiErrorId.ERR_INVALID_STATE.value, 409)

    order = ctx["order_after_refusal"]
    assert order["status"] == "REQUESTED"
    assert order["dispatched_at"] is None
    assert order["allocated_keg_count"] == 0
    assert order["allocated_keg_ids"] == []
    assert order["allocation_shortfall"] == 0

    pool = ctx["pool_after_refusal"]
    assert pool["kegs_available"] == 2
    assert pool["available_pct"] == 100.00
    assert ctx["keg_after_refusal"]["custody_state"] == "IN_FLOAT"


def test_the_same_dispatch_succeeds_once_allocated_and_rebases_the_dwell_clock():
    """The refusal was about state alone: the identical call goes through after
    allocation, and the keg's dwell clock is moved off the allocation instant and
    onto the operator-supplied departure instant.

    PRD: "Each allocated keg moves `IN_FLOAT → ISSUED_TO_BREWER`, records
    `current_brewer_id` from the agreement and `issuance_order_id` from the order,
    sets `dwell_started_at` to the logical clock, sets `dwell_flag` to
    `WITHIN_LIMIT`, and advances its own `version`."

    PRD: "Critically, every allocated keg's `dwell_started_at` is re-based to that
    same supplied `dispatched_at`, so the brewer's dwell clock starts when the
    truck left rather than when the operator got round to typing it in."

    PRD: "The order moves to `DISPATCHED`, records `dispatched_at`, advances its
    `version`, and refreshes the agreement's `kegs_issued_count`."

    Design: Corner/state_machines/dispatch_on_a_requested_order_returns_invalid_state
    """
    ctx = _a_requested_order_dispatched_before_and_after_allocation()
    keg_id = ctx["kegs"][0]["id"]

    allocated = ctx["allocated"]
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_keg_ids"] == [keg_id]
    assert allocated["allocation_shortfall"] == 0

    dispatched = ctx["dispatched"]
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatched_at"] == "2026-08-01T01:00:00Z"

    keg = fixtures.read_keg(keg_id)
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert keg["dwell_started_at"] == "2026-08-01T01:00:00Z"
    assert keg["dwell_started_at"] != CLOCK
    assert keg["dwell_flag"] == "WITHIN_LIMIT"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["kegs_issued_count"] == 1
    assert agreement["kegs_at_brewer_count"] == 1


def _a_dispatched_order_someone_tries_to_take_back():
    """A dispatched single-keg order, then a cancel and a second dispatch on the
    same row, both of which must bounce off the terminal state.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    ctx["order_before"] = fixtures.read_order(order["id"])
    ctx["cancel_attempt"] = api_client.cancel_issuance_order(
        order["id"], {"cancel_reason": "brewer changed their mind"}, OPERATOR
    )
    ctx["redispatch_attempt"] = api_client.dispatch_issuance_order(
        order["id"], {"dispatched_at": "2026-08-01T04:00:00Z"}, OPERATOR
    )
    ctx["order"] = order
    return ctx


def test_a_dispatched_order_can_be_neither_cancelled_nor_dispatched_again():
    """`DISPATCHED` is terminal even though it is the successful outcome, so both
    the recall and the replay are refused as terminal rather than as invalid
    state, and neither refusal bumps the row.

    PRD: "The dimension being moved is not already in one of its terminal states:
    order `CANCELLED` or `DISPATCHED`, claim `AGREED`, `REJECTED` or `WITHDRAWN`,
    assessment `UPHELD`, `WAIVED` or `SUPERSEDED`, investigation
    `CLOSED_RECOVERED` or `CLOSED_WRITTEN_OFF`, keg custody `LOST`, `STOLEN` or
    `SCRAPPED`, agreement `TERMINATED`. Failure is `ERR_ALREADY_TERMINAL` (409)."

    PRD: "`DISPATCHED` is terminal for an order, and only a dispatched order's
    kegs may be filled."

    Design: Corner/state_machines/dispatched_order_cannot_be_cancelled_or_redispatched
    """
    ctx = _a_dispatched_order_someone_tries_to_take_back()

    validate_error(ctx["cancel_attempt"], ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)
    validate_error(ctx["redispatch_attempt"], ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)

    order = fixtures.read_order(ctx["order"]["id"])
    assert order["status"] == "DISPATCHED"
    assert order["cancel_reason"] is None
    assert order["dispatched_at"] == "2026-08-01T01:00:00Z"
    assert order["version"] == ctx["order_before"]["version"]

    keg = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert keg["current_brewer_id"] == ctx["brewer"]["id"]
    assert keg["dwell_started_at"] == "2026-08-01T01:00:00Z"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_available"] == 1
    assert pool["kegs_circulating"] == 1
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["kegs_at_brewer_count"] == 1
    assert agreement["float_posture"] == "HEALTHY"


def _fill_attempted_before_and_after_the_truck_leaves():
    """A keg allocated but not yet dispatched, scanned as filled, then dispatched
    and scanned with the identical payload.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    agreement_id = ctx["agreement"]["id"]
    keg_id = ctx["kegs"][0]["id"]
    order = fixtures.create_order(agreement_id, 1)
    fixtures.allocate_order(order["id"], agreement_id)

    payload = factories.fill_scan_payload(
        ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG"
    )
    headers = make_brewer_headers(ctx["brewer"]["id"])
    ctx["early_fill"] = api_client.scan_keg(keg_id, payload, headers)
    ctx["keg_after_refusal"] = fixtures.read_keg(keg_id)
    ctx["agreement_after_refusal"] = fixtures.read_agreement(agreement_id)
    ctx["brewer_after_refusal"] = fixtures.read_brewer(ctx["brewer"]["id"])
    fixtures.dispatch_order(order["id"], "2026-08-01T01:00:00Z")
    ctx["accepted_fill"] = validate_success(
        api_client.scan_keg(keg_id, payload, headers), 201
    )
    ctx["order"] = order
    ctx["keg_id"] = keg_id
    return ctx


def test_a_fill_on_an_undispatched_order_is_refused_before_any_money_moves():
    """The keg is already `ISSUED_TO_BREWER`, so the custody sequence itself is
    legal; what refuses the scan is the state of another row — the governing order
    is not yet `DISPATCHED` — and nothing is appended and nothing is billed.

    PRD: "The target resource sits in a state from which the requested transition
    is declared: order `status` for allocate, dispatch and cancel; cycle `stage`
    for step recording and release; `assessment_status` for dispute and resolve;
    `chargeback_status` for chargeback resolution; claim `status` for a response;
    investigation `status` for a status change; keg `custody_state` being
    `IN_FLOAT` or `IN_SERVICE` for a service-cycle booking; and, on a fill scan,
    the keg's governing issuance order being `DISPATCHED`. Failure is
    `ERR_INVALID_STATE` (409)."

    PRD: "Every accepted scan raises the keg's `scan_count` by one, adds the newly
    closed `dwell_days_closed` into the keg's `cumulative_dwell_days`, and
    advances the keg's `version`."

    PRD: "Rejected scans leave the ledger untouched."

    Design: Corner/state_machines/fill_scan_before_dispatch_returns_invalid_state
    """
    ctx = _fill_attempted_before_and_after_the_truck_leaves()

    validate_error(ctx["early_fill"], ApiErrorId.ERR_INVALID_STATE.value, 409)

    keg = ctx["keg_after_refusal"]
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert keg["fill_count"] == 0
    assert keg["scan_count"] == 0
    assert keg["last_scanned_at"] is None
    assert keg["filled_brand_code"] is None

    agreement = ctx["agreement_after_refusal"]
    assert agreement["billed_amount_cents"] == 0
    assert agreement["billed_fills_count"] == 0
    assert ctx["brewer_after_refusal"]["lifetime_fill_count"] == 0


def test_the_same_fill_after_dispatch_is_accepted_and_billed_at_the_base_rate():
    """Once the order is dispatched the identical scan is accepted, and with the
    dwell clock re-based to the departure instant there is no surcharge and the
    tier basis of 2200 earns no discount, so the fill is billed at the base rate
    exactly.

    PRD: "An accepted fill appends the scan, raises the keg's `fill_count` by one,
    records `filled_brand_code` from `brand_code_scanned` and `filling_brewer_id`
    from `brewer_id`, closes the open custody spell in the manner described above,
    resets `dwell_started_at` to `scanned_at`, and clears `misdelivery_open` —
    refilling a keg is what settles any unreconciled cross-brand history on it."

    PRD: "The base is the agreement's current `per_fill_rate_cents` — taken from
    the agreement, not from the order's `per_fill_price_cents_pinned`."

    PRD: "On the agreement's side, `billed_fills_count` rises by one,
    `billed_amount_cents` grows by the fill's net charge, and the agreement's
    `version` advances."

    Design: Corner/state_machines/fill_scan_before_dispatch_returns_invalid_state
    """
    ctx = _fill_attempted_before_and_after_the_truck_leaves()

    scan = ctx["accepted_fill"]
    assert scan["scan_point"] == "FILL"
    assert scan["custody_state_after"] == "FILLED"
    assert scan["fill_charge_net_cents"] == 2200
    assert scan["dwell_days_closed"] == 0

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "FILLED"
    assert keg["fill_count"] == 1
    assert keg["filled_brand_code"] == "RDG"
    assert keg["filling_brewer_id"] == ctx["brewer"]["id"]
    assert keg["dwell_started_at"] == "2026-08-01T02:00:00Z"
    assert keg["scan_count"] == 1

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_amount_cents"] == 2200
    assert agreement["billed_fills_count"] == 1


def _a_filled_keg_handed_to_the_wholesaler():
    """A single keg dispatched, filled under its own collar, then taken into trade
    by a distributor scanning the same collar an hour later.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    distributor = fixtures.create_distributor(name="High Plains Distributing")
    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")

    ctx["distributor"] = distributor
    ctx["order"] = order
    ctx["keg_id"] = keg_id
    ctx["scan"] = fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-01T03:00:00Z", "RDG"
    )
    ctx["dwell"] = validate_success(
        api_client.get_keg_dwell(
            keg_id, TEST_USERS["pool_operator_headers"]
        )
    )
    return ctx


def test_the_distribution_scan_opens_the_accountability_clock_at_the_read_instant():
    """The wholesaler's spell starts at the instant the tag was read, while the
    server's own `recorded_at` is the logical clock — twenty hours later — and the
    matching collar means no misdelivery is detected.

    PRD: "The keg moves `FILLED → IN_TRADE`, records `current_distributor_id`, and
    opens a fresh distributor accountability spell by setting
    `distributor_custody_started_at` to the scan's `scanned_at`."

    PRD: "Alongside the supplied fields the server records `recorded_at`, the
    logical-clock instant at which the scan reached the server, which is always
    monotonic and differs from `scanned_at` for late arrivals."

    PRD: "Misdelivery detection then runs on those same three scan points: when
    `brand_code_scanned` differs from the keg's stored `filled_brand_code`, the
    scan records `misdelivery_detected` as true and the keg's `misdelivery_open`
    flag is raised."

    PRD: "A scan is flagged `is_late_arrival` when the keg's `last_scanned_at` is
    already set and this scan's `scanned_at` is strictly earlier than it."

    Design: Corner/state_machines/distribution_scan_opens_the_distributor_accountability_clock
    """
    ctx = _a_filled_keg_handed_to_the_wholesaler()

    scan = ctx["scan"]
    assert scan["scan_point"] == "DISTRIBUTION"
    assert scan["party_type"] == "DISTRIBUTOR"
    assert scan["distributor_id"] == ctx["distributor"]["id"]
    assert scan["custody_state_after"] == "IN_TRADE"
    assert scan["misdelivery_detected"] is False
    assert scan["is_late_arrival"] is False
    assert scan["scanned_at"] == "2026-08-01T03:00:00Z"
    assert scan["recorded_at"] == CLOCK

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "IN_TRADE"
    assert keg["current_distributor_id"] == ctx["distributor"]["id"]
    assert keg["distributor_custody_started_at"] == "2026-08-01T03:00:00Z"
    assert keg["last_scanned_at"] == "2026-08-01T03:00:00Z"
    assert keg["scan_count"] == 2
    assert keg["misdelivery_open"] is False
    assert keg["filled_brand_code"] == "RDG"


def test_the_trade_leg_reads_the_distributor_limits_and_moves_no_census_bucket():
    """`FILLED` and `IN_TRADE` are the same census bucket, so handing the keg over
    moves nothing in the pool; what changes is which clock and which limits the
    dwell read applies.

    PRD: "The applicable limit depends on the keg's `custody_state`: a keg in
    `ISSUED_TO_BREWER` or `FILLED` is measured on the brewer clock against a limit
    of 30 days with an approaching point at 24 days; a keg in `IN_TRADE` or
    `AT_RETAIL` is measured on the distributor clock against a limit of 45 days
    with an approaching point at 36 days."

    PRD: "The read is strictly read-only: the classification it returns is not
    persisted."

    Design: Corner/state_machines/distribution_scan_opens_the_distributor_accountability_clock
    """
    ctx = _a_filled_keg_handed_to_the_wholesaler()

    dwell = ctx["dwell"]
    assert dwell["keg_id"] == ctx["keg_id"]
    assert dwell["custody_state"] == "IN_TRADE"
    assert dwell["distributor_spell_days"] == 0
    assert dwell["limit_days"] == 45
    assert dwell["approaching_days"] == 36
    assert dwell["dwell_flag"] == "WITHIN_LIMIT"
    assert dwell["distributor_custody_started_at"] == "2026-08-01T03:00:00Z"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 1,
            "kegs_circulating": 1,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["dwell_flag"] == "WITHIN_LIMIT"


_STEP_FIELDS_A_CYCLE_HAS_NOT_REACHED_YET = (
    "cleaned_at",
    "caustic_cycle_minutes",
    "inspected_at",
    "inspection_result",
    "pressure_tested_at",
    "pressure_test_psi",
    "pressure_test_result",
    "pressure_test_performed_by_user_id",
    "released_at",
    "released_by_user_id",
    "quarantine_reason",
)


def _a_keg_booked_onto_the_wash_line():
    """A two-keg pool and a two-slot service centre, with the first keg booked in
    off the float at ten in the morning.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(pool["id"], ["K-0001", "K-0002"])
    center = fixtures.create_service_center(2, name="Denver Wash Bay")
    booking = api_client.create_service_cycle(
        factories.create_service_cycle_payload(
            kegs[0]["id"], center["id"], "2026-08-01T10:00:00Z"
        ),
        TECHNICIAN,
    )
    return {
        "index": index,
        "pool": pool,
        "kegs": kegs,
        "center": center,
        "cycle": validate_success(booking, 201),
    }


def test_a_booked_cycle_opens_at_received_with_every_later_field_unwritten():
    """The cycle is created at the only stage from which a `CLEAN` step can run,
    holds the received instant, and carries none of the values its later stages
    are declared to record.

    PRD: "Booking a keg onto a line creates a `ServiceCycle` from a `keg_id`, a
    `service_center_id` and a `received_at`."

    PRD: "- **`CLEAN`** requires `stage` `RECEIVED` and an `occurred_at` at or
    after the cycle's `received_at` and not after the logical clock. It records
    `caustic_cycle_minutes`, which must be at least 12 — a shorter caustic wash is
    refused with `ERR_CAUSTIC_CYCLE_TOO_SHORT` — sets `cleaned_at` and advances
    the stage to `CLEANED`."

    PRD: "A `ServiceCenter` is created with a `name`, a two-letter `region_code`,
    a `concurrent_cycle_capacity` between 1 and 50, and an `intake_buffer_hours`
    between 0 and 48 that defaults to 4; its `open_cycle_count` starts at 0 and is
    thereafter derived as the number of that centre's cycles whose `stage` is
    `RECEIVED`, `CLEANED`, `INSPECTED`, `PRESSURE_TESTED` or `QUARANTINED`."

    Design: Corner/state_machines/service_cycle_starts_in_received_stage
    """
    ctx = _a_keg_booked_onto_the_wash_line()
    cycle = ctx["cycle"]

    assert cycle["stage"] == "RECEIVED"
    assert cycle["received_at"] == "2026-08-01T10:00:00Z"
    assert cycle["keg_id"] == ctx["kegs"][0]["id"]
    assert cycle["service_center_id"] == ctx["center"]["id"]
    assert cycle["version"] == 1
    for field in _STEP_FIELDS_A_CYCLE_HAS_NOT_REACHED_YET:
        assert cycle[field] is None, f"a fresh cycle must not carry {field}"

    center = validate_success(
        api_client.get_service_center(ctx["center"]["id"], OPERATOR)
    )
    assert center["open_cycle_count"] == 1
    assert center["intake_buffer_hours"] == 4
    assert center["concurrent_cycle_capacity"] == 2


def test_the_booking_itself_pulls_the_keg_off_the_float_and_into_servicing():
    """Booking an `IN_FLOAT` keg is the write that moves it: the servicing bucket
    fills before any cleaning has happened, and the keg's certification standing is
    untouched by the move.

    PRD: "The two variants differ sharply in their effects: booking an `IN_FLOAT`
    keg moves it to `IN_SERVICE`, bumps its `version`, decrements `kegs_available`
    and increments `kegs_servicing`, and recomputes `available_pct`, `posture` and
    every `ACTIVE` agreement's `float_posture`, whereas booking a keg that is
    already `IN_SERVICE` touches neither the keg nor the census and does not bump
    the keg's `version` — the return scan already moved it out of
    `kegs_circulating`."

    Design: Corner/state_machines/service_cycle_starts_in_received_stage
    """
    ctx = _a_keg_booked_onto_the_wash_line()

    booked = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert booked["custody_state"] == "IN_SERVICE"
    assert booked["service_state"] == "SERVICE_OK"
    assert booked["version"] > ctx["kegs"][0]["version"]

    untouched = fixtures.read_keg(ctx["kegs"][1]["id"])
    assert untouched["custody_state"] == "IN_FLOAT"
    assert untouched["version"] == ctx["kegs"][1]["version"]

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 1,
            "kegs_circulating": 0,
            "kegs_servicing": 1,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


def _a_released_cycle_someone_signs_off_twice():
    """A full wash-line pass — clean, inspect, pressure test by one technician,
    release by another — followed by a replayed release an hour later.
    """
    ctx = _a_keg_booked_onto_the_wash_line()
    cycle_id = ctx["cycle"]["id"]
    fixtures.record_clean(cycle_id, "2026-08-01T11:00:00Z", caustic_cycle_minutes=15)
    fixtures.record_inspect(cycle_id, "2026-08-01T12:00:00Z", inspection_result="PASS")
    fixtures.record_pressure_test(
        cycle_id,
        "2026-08-01T13:00:00Z",
        pressure_test_psi=45,
        pressure_test_result="PASS",
    )
    ctx["released"] = fixtures.release_cycle(
        cycle_id, "2026-08-01T14:00:00Z", headers=SECOND_TECHNICIAN
    )
    ctx["replay"] = api_client.release_service_cycle(
        cycle_id, {"released_at": "2026-08-01T15:00:00Z"}, SECOND_TECHNICIAN
    )
    ctx["cycle_id"] = cycle_id
    return ctx


def test_replaying_a_release_is_refused_and_does_not_re_sign_the_certificate():
    """Release is declared only from `PRESSURE_TESTED`, so the second sign-off is
    refused at the state gate rather than replayed: the release instant is still the
    first one, the signer is still the technician who first signed, and the centre's
    occupancy stays at zero instead of going negative.

    PRD: "The target resource sits in a state from which the requested transition
    is declared: order `status` for allocate, dispatch and cancel; cycle `stage`
    for step recording and release; `assessment_status` for dispute and resolve;
    `chargeback_status` for chargeback resolution; claim `status` for a response;
    investigation `status` for a status change; keg `custody_state` being
    `IN_FLOAT` or `IN_SERVICE` for a service-cycle booking; and, on a fill scan,
    the keg's governing issuance order being `DISPATCHED`. Failure is
    `ERR_INVALID_STATE` (409)."

    PRD: "the cycle must be in `PRESSURE_TESTED` with `pressure_test_result`
    `PASS`"

    PRD: "Release sets `stage` to `RELEASED`, records `released_at` and
    `released_by_user_id`, and decrements the centre's `open_cycle_count`."

    PRD: "This second check is a count, not a pairwise comparison — each cycle is
    admissible on its own and only the collective breaches the limit — and because
    `RELEASED` cycles leave the count, releasing one cycle frees exactly one slot."

    PRD: "Every accepted step advances the cycle's `version`."

    Design: Corner/state_machines/second_release_on_a_released_cycle_does_not_double_move_the_keg
    """
    ctx = _a_released_cycle_someone_signs_off_twice()

    validate_error(ctx["replay"], ApiErrorId.ERR_INVALID_STATE.value, 409)

    cycle = fixtures.read_cycle(ctx["cycle_id"])
    assert cycle["stage"] == "RELEASED"
    assert cycle["released_at"] == "2026-08-01T14:00:00Z"
    assert cycle["released_by_user_id"] == SECOND_TECHNICIAN_USER_ID
    assert cycle["pressure_test_performed_by_user_id"] == TECHNICIAN_USER_ID
    assert cycle["version"] == ctx["released"]["version"]

    center = validate_success(
        api_client.get_service_center(ctx["center"]["id"], OPERATOR)
    )
    assert center["open_cycle_count"] == 0


def test_the_refused_replay_leaves_the_kegs_certification_stamped_once():
    """The keg keeps the single reset the first release gave it: certified at the
    instant the gauge was read, dwelling from the instant it was signed back in,
    and counted once — not twice — in the pool's available bucket.

    PRD: "On the keg it is a full reset: custody returns to `IN_FLOAT`,
    `service_state` becomes `SERVICE_OK`, `fills_at_last_pressure_test` is set to
    the current `fill_count`, `last_pressure_test_at` is set to the cycle's
    `pressure_tested_at` rather than to `released_at`, `current_brewer_id`,
    `current_distributor_id`, `issuance_order_id` and
    `distributor_custody_started_at` are all cleared, `dwell_started_at` is set to
    `released_at`, `dwell_flag` returns to `WITHIN_LIMIT`, and the keg's `version`
    advances."

    PRD: "The pool census, `available_pct` and `posture` are recomputed and every
    `ACTIVE` agreement on the pool recomputes `float_posture`."

    Design: Corner/state_machines/second_release_on_a_released_cycle_does_not_double_move_the_keg
    """
    ctx = _a_released_cycle_someone_signs_off_twice()

    keg = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert keg["custody_state"] == "IN_FLOAT"
    assert keg["service_state"] == "SERVICE_OK"
    assert keg["last_pressure_test_at"] == "2026-08-01T13:00:00Z"
    assert keg["fills_at_last_pressure_test"] == 0
    assert keg["fill_count"] == 0
    assert keg["dwell_started_at"] == "2026-08-01T14:00:00Z"
    assert keg["dwell_flag"] == "WITHIN_LIMIT"
    assert keg["current_brewer_id"] is None
    assert keg["current_distributor_id"] is None
    assert keg["issuance_order_id"] is None
    assert keg["distributor_custody_started_at"] is None

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 2,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


def _an_investigation_over_two_of_four_kegs():
    """Four kegs sitting on the floor of one pool, two of them attached to a theft
    investigation, and the first of those two impounded at eight in the evening.

    Every stage is read back — the open, the hold and the resume — so the hold's
    reach can be measured against the kegs it never named.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(pool["id"], ["K-0001", "K-0002", "K-0003", "K-0004"])
    attached = [kegs[0]["id"], kegs[1]["id"]]
    investigation = fixtures.open_investigation(pool["id"], attached)
    ctx = {
        "index": index,
        "pool": pool,
        "kegs": kegs,
        "attached_keg_ids": attached,
        "opened": investigation,
        "pool_at_open": fixtures.read_pool(pool["id"]),
        "keg_at_open": fixtures.read_keg(kegs[0]["id"]),
    }
    ctx["hold"] = validate_success(
        api_client.set_investigation_status(
            investigation["id"],
            factories.investigation_status_payload(
                "EVIDENCE_HOLD",
                keg_ids=[kegs[0]["id"]],
                hold_started_at="2026-08-01T20:00:00Z",
            ),
            ANALYST,
        )
    )
    ctx["pool_on_hold"] = fixtures.read_pool(pool["id"])
    ctx["investigation_id"] = investigation["id"]
    return ctx


def test_attaching_kegs_stamps_them_without_moving_a_single_census_bucket():
    """The open attaches two kegs, prices the stainless exposure once per keg, and
    leaves all four kegs exactly where they were: nothing is held yet and the pool
    still reads fully available.

    PRD: "Opening the investigation sets `status` to `OPEN`, stamps
    `opened_by_user_id` with the acting `X-User-ID`, and writes
    `theft_investigation_id` onto each named keg."

    PRD: "That attachment alone removes the keg from allocation candidacy
    **without changing its `custody_state`** — a keg under investigation stays
    where it is in the census and simply stops being issuable."

    PRD: "`attached_keg_count` records how many kegs are attached,
    `held_keg_count` starts at 0, and `stainless_value_at_risk_cents` is computed
    as the aggregate scrap exposure of the attached kegs: for each attached keg,
    its pool's `stainless_weight_kg` multiplied by the stainless price in force
    multiplied by the 65 percent recovery factor, rounded half up **per keg**, and
    only then summed."

    Design: Corner/state_machines/evidence_hold_moves_only_the_named_kegs_out_of_their_buckets
    """
    ctx = _an_investigation_over_two_of_four_kegs()
    opened = ctx["opened"]

    assert opened["status"] == "OPEN"
    assert opened["opened_by_user_id"] == ANALYST_USER_ID
    assert opened["attached_keg_count"] == 2
    assert opened["held_keg_count"] == 0
    assert opened["stainless_value_at_risk_cents"] == 7800
    assert opened["commodity_index_id"] == ctx["index"]["id"]

    stamped = ctx["keg_at_open"]
    assert stamped["theft_investigation_id"] == opened["id"]
    assert stamped["custody_state"] == "IN_FLOAT"

    pool = ctx["pool_at_open"]
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 4,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


def test_the_hold_impounds_the_named_keg_and_leaves_its_neighbour_attached():
    """Only the keg named in the hold moves out of `kegs_available` and into
    `kegs_held`, recording where it came from; the second attached keg stays on the
    floor still attached, and the two unattached kegs are untouched.

    PRD: "Each named keg records its current custody state into
    `pre_hold_custody_state` and then moves to `EVIDENCE_HOLD`, which pulls it out
    of whichever census bucket it occupied and into `kegs_held`."

    PRD: "The investigation moves to `EVIDENCE_HOLD` and recomputes
    `hold_started_at`, `held_keg_count` and `stainless_value_at_risk_cents`."

    Design: Corner/state_machines/evidence_hold_moves_only_the_named_kegs_out_of_their_buckets
    """
    ctx = _an_investigation_over_two_of_four_kegs()
    held = ctx["hold"]

    assert held["status"] == "EVIDENCE_HOLD"
    assert held["hold_started_at"] == "2026-08-01T20:00:00Z"
    assert held["held_keg_count"] == 1
    assert held["attached_keg_count"] == 2
    assert held["stainless_value_at_risk_cents"] == 7800

    impounded = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert impounded["custody_state"] == "EVIDENCE_HOLD"
    assert impounded["pre_hold_custody_state"] == "IN_FLOAT"
    assert impounded["theft_investigation_id"] == ctx["investigation_id"]

    still_attached = fixtures.read_keg(ctx["kegs"][1]["id"])
    assert still_attached["custody_state"] == "IN_FLOAT"
    assert still_attached["theft_investigation_id"] == ctx["investigation_id"]
    assert still_attached["pre_hold_custody_state"] is None

    bystander = fixtures.read_keg(ctx["kegs"][2]["id"])
    assert bystander["custody_state"] == "IN_FLOAT"
    assert bystander["theft_investigation_id"] is None

    pool = ctx["pool_on_hold"]
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 3,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 1,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 75.00
    assert pool["posture"] == "OPEN"


def test_the_resume_puts_the_keg_back_in_the_bucket_it_came_from():
    """The resume is the exact inverse of the hold: the investigation returns to
    `OPEN` with no held kegs and no hold instant, the keg is restored to the state
    it recorded, and the census reads as it did before the impound — while the
    version keeps climbing, because a resume is still a write.

    PRD: "A **resume** requires `status` `EVIDENCE_HOLD` and is the exact inverse:
    each held keg's `custody_state` is restored from its `pre_hold_custody_state`,
    which returns every pool census counter to its pre-hold value, and the
    investigation returns to `OPEN` with `held_keg_count` back at 0 and
    `hold_started_at` cleared."

    PRD: "Every action recomputes the pool census, `available_pct`, `posture` and
    every `ACTIVE` agreement's `float_posture`, and advances the investigation's
    `version`."

    Design: Corner/state_machines/evidence_hold_moves_only_the_named_kegs_out_of_their_buckets
    """
    ctx = _an_investigation_over_two_of_four_kegs()
    resumed = validate_success(
        api_client.set_investigation_status(
            ctx["investigation_id"],
            factories.investigation_status_payload("RESUME"),
            ANALYST,
        )
    )

    assert resumed["status"] == "OPEN"
    assert resumed["held_keg_count"] == 0
    assert resumed["hold_started_at"] is None
    assert resumed["attached_keg_count"] == 2
    assert resumed["stainless_value_at_risk_cents"] == 7800
    assert resumed["version"] > ctx["hold"]["version"]

    restored = fixtures.read_keg(ctx["kegs"][0]["id"])
    assert restored["custody_state"] == "IN_FLOAT"
    assert restored["theft_investigation_id"] == ctx["investigation_id"]

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 4,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


def _two_orders_that_split_a_four_keg_float():
    """Two orders raised against one four-keg float before either is allocated:
    the first for two kegs, the second for three with partial fills allowed.

    Allocating them in that order gives the first a full set and the second the
    two kegs that are left, which drains the pool to zero available and so freezes
    it.  The second order is then cancelled.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer(credit_limit_cents=400000)
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(pool["id"], ["K-0001", "K-0002", "K-0003", "K-0004"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 4, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    first_order = fixtures.create_order(agreement["id"], 2)
    second_order = fixtures.create_order(agreement["id"], 3, allow_partial=True)

    ctx = {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "kegs": kegs,
        "agreement": agreement,
        "first_order_id": first_order["id"],
        "second_order_id": second_order["id"],
    }
    ctx["first_allocated"] = fixtures.allocate_order(first_order["id"], agreement["id"])
    ctx["second_allocated"] = fixtures.allocate_order(
        second_order["id"], agreement["id"]
    )
    ctx["pool_when_drained"] = fixtures.read_pool(pool["id"])
    ctx["agreement_when_drained"] = fixtures.read_agreement(agreement["id"])
    return ctx


def test_the_second_allocation_takes_only_what_is_left_and_freezes_the_pool():
    """The first order is fully met and the second is short by one, so the two
    orders hold disjoint keg sets; with every keg issued the pool reads 0.00
    available and `FROZEN`, which suspends the float that just drew on it.

    PRD: "The order lands in `ALLOCATED` when the count was fully met and in
    `PARTIALLY_ALLOCATED` when it was short — the two branches are otherwise
    identical, differing only in the non-zero shortfall and the smaller number of
    keg moves."

    PRD: "Otherwise — including whenever `kegs_total` is zero — the posture is
    `FROZEN`."

    PRD: "The agreement is `SUSPENDED` whenever the pool's `posture` is `FROZEN`
    **or** the brewer's `status` is `PROBATION` or `SUSPENDED`."

    Design: Corner/state_machines/order_cancel_returns_only_its_own_allocated_kegs
    """
    ctx = _two_orders_that_split_a_four_keg_float()
    first = ctx["first_allocated"]
    second = ctx["second_allocated"]

    assert first["status"] == "ALLOCATED"
    assert first["allocated_keg_count"] == 2
    assert first["allocation_shortfall"] == 0

    assert second["status"] == "PARTIALLY_ALLOCATED"
    assert second["allocated_keg_count"] == 2
    assert second["allocation_shortfall"] == 1
    assert set(second["allocated_keg_ids"]).isdisjoint(first["allocated_keg_ids"])
    assert len(set(first["allocated_keg_ids"]) | set(second["allocated_keg_ids"])) == 4

    pool = ctx["pool_when_drained"]
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 0,
            "kegs_circulating": 4,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 0.00
    assert pool["posture"] == "FROZEN"
    assert ctx["agreement_when_drained"]["float_posture"] == "SUSPENDED"


def test_cancelling_one_order_returns_that_orders_kegs_and_no_others():
    """The cancellation hands back exactly the two kegs named in the cancelled
    order, clearing their brewer, order and dwell fields, while the other order's
    two kegs stay issued with their own order id and their allocation-time dwell
    clock intact.

    PRD: "Cancelling an allocated or partially allocated order returns exactly the
    kegs named in `allocated_keg_ids` — that is, `allocated_keg_count` kegs, not
    `requested_keg_count` — each moving `ISSUED_TO_BREWER → IN_FLOAT` while
    clearing `current_brewer_id`, `issuance_order_id` and `dwell_started_at`,
    resetting `dwell_flag` to `WITHIN_LIMIT`, and advancing its own `version`."

    PRD: "Each allocated keg moves `IN_FLOAT → ISSUED_TO_BREWER`, records
    `current_brewer_id` from the agreement and `issuance_order_id` from the order,
    sets `dwell_started_at` to the logical clock, sets `dwell_flag` to
    `WITHIN_LIMIT`, and advances its own `version`."

    Design: Corner/state_machines/order_cancel_returns_only_its_own_allocated_kegs
    """
    ctx = _two_orders_that_split_a_four_keg_float()
    reason = "Brewer deferred the second delivery."
    cancelled = validate_success(
        api_client.cancel_issuance_order(
            ctx["second_order_id"], {"cancel_reason": reason}, OPERATOR
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == reason

    for keg_id in ctx["second_allocated"]["allocated_keg_ids"]:
        returned = fixtures.read_keg(keg_id)
        assert returned["custody_state"] == "IN_FLOAT"
        assert returned["current_brewer_id"] is None
        assert returned["issuance_order_id"] is None
        assert returned["dwell_started_at"] is None
        assert returned["dwell_flag"] == "WITHIN_LIMIT"

    for keg_id in ctx["first_allocated"]["allocated_keg_ids"]:
        kept = fixtures.read_keg(keg_id)
        assert kept["custody_state"] == "ISSUED_TO_BREWER"
        assert kept["current_brewer_id"] == ctx["brewer"]["id"]
        assert kept["issuance_order_id"] == ctx["first_order_id"]
        assert kept["dwell_started_at"] == CLOCK

    first = fixtures.read_order(ctx["first_order_id"])
    assert first["status"] == "ALLOCATED"
    assert first["allocated_keg_ids"] == ctx["first_allocated"]["allocated_keg_ids"]


def test_the_cancelled_order_keeps_its_history_and_the_pool_thaws_back_to_open():
    """`allocated_keg_ids` and the shortfall survive the cancellation as a
    historical record, and the census, availability and both postures return to
    exactly the values they held after the first allocation and before the second.

    PRD: "`allocated_keg_ids` is left in place as a historical record."

    PRD: "The pool census, `available_pct` and `posture` are then recomputed back
    to exactly their pre-allocation values, and the agreement's counters and
    `float_posture` are recomputed, with the agreement's `version` advancing."

    PRD: "While the posture is `HEALTHY` or `SUSPENDED` it is 0."

    Design: Corner/state_machines/order_cancel_returns_only_its_own_allocated_kegs
    """
    ctx = _two_orders_that_split_a_four_keg_float()
    fixtures.cancel_order(
        ctx["second_order_id"], cancel_reason="Brewer deferred the second delivery."
    )

    cancelled = fixtures.read_order(ctx["second_order_id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["allocated_keg_ids"] == ctx["second_allocated"]["allocated_keg_ids"]
    assert cancelled["allocated_keg_count"] == 2
    assert cancelled["allocation_shortfall"] == 1

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 2,
            "kegs_circulating": 2,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["kegs_at_brewer_count"] == 2
    assert agreement["kegs_issued_count"] == 2
    assert agreement["float_posture"] == "HEALTHY"
    assert agreement["pending_replenishment_kegs"] == 0


def _one_keg_walked_all_the_way_back_from_the_trade():
    """A single keg taken through the whole trade leg on one logical day —
    dispatched at one, filled at two, distributed at three and returned at four —
    for a `BRONZE` distributor whose base return rate is 250 cents.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    distributor = fixtures.create_distributor(
        name="High Plains Distributing", return_incentive_rate_cents_per_keg=250
    )
    fixtures.sign_cooperation_agreement(distributor["id"], "BRONZE", "2026-08-01")

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-01T03:00:00Z", "RDG"
    )
    returned = validate_success(
        api_client.scan_keg(
            keg_id,
            factories.return_scan_payload(
                distributor["id"], "2026-08-01T04:00:00Z", "RDG"
            ),
            OPERATOR,
        ),
        201,
    )
    rows, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": distributor["id"]}
        )
    )
    ctx["distributor"] = distributor
    ctx["order"] = order
    ctx["keg_id"] = keg_id
    ctx["return_scan"] = returned
    ctx["accruals"] = rows
    return ctx


def test_the_return_scan_closes_the_accountability_spell_and_mints_the_accrual():
    """The return moves the keg into servicing, clears the accountability clock,
    and mints exactly one `RETURN_DWELL` row priced at the full band and the
    `BRONZE` multiplier for a spell that closed inside an hour.

    PRD: "The keg moves `IN_TRADE → IN_SERVICE` or `AT_RETAIL → IN_SERVICE`, the
    custody spell closes, `dwell_started_at` resets to `scanned_at`, and
    `distributor_custody_started_at` is cleared."

    PRD: "That closed spell mints a `ReturnIncentiveAccrual` of `accrual_type`
    `RETURN_DWELL`, which records `distributor_id`, `keg_id`, the `dwell_days` it
    closed, the band factor `tier_pct_bp`, the tier factor
    `cooperation_multiplier_bp`, the resulting `incentive_cents`, and
    `triggering_scanned_at` set to the return scan's `scanned_at`; its `claim_id`
    is unset, its `status` opens at `ACCRUED`, and `paid_at` and `clawback_reason`
    are unset."

    PRD: "The dwell band factor is 10000 basis points when the accountability
    spell closed in 14 days or fewer, 6000 basis points from 15 through 29 days,
    2500 basis points from 30 through 44 days, and 0 basis points at 45 days or
    more — so a keg returned outside the 45-day distributor allowance earns
    nothing."

    PRD: "It also records four derived facts: `is_late_arrival`,
    `custody_state_after`, `dwell_days_closed`, and — for fill scans only —
    `fill_charge_net_cents`, which is null on every other scan point."

    Design: Corner/state_machines/return_scan_mints_the_accrual_and_advances_the_distributor_counters
    """
    ctx = _one_keg_walked_all_the_way_back_from_the_trade()
    scan = ctx["return_scan"]

    assert scan["scan_point"] == "RETURN"
    assert scan["party_type"] == "DISTRIBUTOR"
    assert scan["custody_state_after"] == "IN_SERVICE"
    assert scan["dwell_days_closed"] == 0
    assert scan["fill_charge_net_cents"] is None
    assert scan["misdelivery_detected"] is False
    assert scan["is_late_arrival"] is False

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "IN_SERVICE"
    # PRD names only `distributor_custody_started_at` as cleared by a return;
    # `current_distributor_id` is cleared at service release, not here.
    assert keg["distributor_custody_started_at"] is None
    assert keg["dwell_started_at"] == "2026-08-01T04:00:00Z"
    assert keg["scan_count"] == 3

    assert len(ctx["accruals"]) == 1
    accrual = ctx["accruals"][0]
    assert accrual["accrual_type"] == "RETURN_DWELL"
    assert accrual["distributor_id"] == ctx["distributor"]["id"]
    assert accrual["keg_id"] == ctx["keg_id"]
    assert accrual["claim_id"] is None
    assert accrual["dwell_days"] == 0
    assert accrual["tier_pct_bp"] == 10000
    assert accrual["cooperation_multiplier_bp"] == 10000
    assert accrual["incentive_cents"] == 250
    assert accrual["status"] == "ACCRUED"
    assert accrual["triggering_scanned_at"] == "2026-08-01T04:00:00Z"
    assert accrual["paid_at"] is None
    assert accrual["clawback_reason"] is None


def test_the_return_advances_the_service_history_without_promoting_the_tier():
    """One on-time return reads as a perfect record at a zero-day mean and puts
    250 cents in the ledger, but a single return is two short of the three a
    `SILVER` promotion needs, so the tier stands; downstream, the keg leaves
    circulation for the wash line and the float reads thin again.

    PRD: "The distributor's `total_returns_count`, `on_time_returns_count`,
    `on_time_return_pct`, `avg_dwell_days` and `incentive_accrual_cents` are then
    all recomputed and the distributor's `version` advances; the recomputed on-time
    percentage may in turn advance the `cooperation_tier` by one step, which
    re-rates every *later* accrual."

    PRD: "Third, at most **one** step up the ladder is applied and no step may be
    skipped: a `BRONZE` distributor becomes `SILVER` when its total is at least 3
    returns and its on-time percentage is at least 90.00, and a `SILVER`
    distributor becomes `GOLD` when its total is at least 5 returns and its on-time
    percentage is at least 96.00, recording `cooperation_effective_date` as the
    current logical date in either case."

    PRD: "Finally the pool's `kegs_circulating` falls by one and `kegs_servicing`
    rises by one, `posture` is recomputed, and every `ACTIVE` agreement on the pool
    recomputes `float_posture`."

    Design: Corner/state_machines/return_scan_mints_the_accrual_and_advances_the_distributor_counters
    """
    ctx = _one_keg_walked_all_the_way_back_from_the_trade()

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["total_returns_count"] == 1
    assert distributor["on_time_returns_count"] == 1
    assert distributor["on_time_return_pct"] == 100.00
    assert distributor["avg_dwell_days"] == 0.00
    assert distributor["incentive_accrual_cents"] == 250
    assert distributor["cooperation_tier"] == "BRONZE"
    assert distributor["cooperation_effective_date"] == "2026-08-01"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 1,
            "kegs_circulating": 0,
            "kegs_servicing": 1,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["kegs_at_brewer_count"] == 0
    assert agreement["float_posture"] == "TIGHT"
    assert agreement["pending_replenishment_kegs"] == 2
    assert agreement["billed_amount_cents"] == 2200
    assert agreement["billed_fills_count"] == 1


def _a_misdelivery_the_receiving_brewery_agrees_to_pay():
    """A keg filled under the `RDG` collar but handed to the trade under the `OAK`
    collar, claimed for 1200 cents by the distributor that carried it, and agreed
    by the brewery it was claimed against.

    The distributor has never signed a cooperation agreement, so it sits at tier
    `NONE` with an untouched service history — which is exactly what makes the
    offset's effect on the ledger readable in isolation.
    """
    ctx = _one_activated_agreement_on_a_two_keg_pool()
    other_brewer = fixtures.create_brewer(
        name="Oakline Ales", brand_code="OAK", credit_limit_cents=400000
    )
    distributor = fixtures.create_distributor(
        name="High Plains Distributing", return_incentive_rate_cents_per_keg=250
    )

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T01:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    ctx["misdelivery_scan"] = fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-01T03:00:00Z", "OAK"
    )
    claim = fixtures.file_claim(
        keg_id,
        distributor["id"],
        other_brewer["id"],
        1200,
        "2026-08-01T03:00:00Z",
    )
    ctx["agreed"] = validate_success(
        api_client.respond_reconciliation_claim(
            claim["id"],
            factories.claim_response_payload(
                "AGREE", fixtures.claim_version(claim["id"])
            ),
            make_brewer_headers(other_brewer["id"]),
        )
    )
    rows, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": distributor["id"]}
        )
    )
    ctx["other_brewer"] = other_brewer
    ctx["distributor"] = distributor
    ctx["keg_id"] = keg_id
    ctx["claim"] = claim
    ctx["accruals"] = rows
    return ctx


def test_agreeing_the_claim_fixes_the_offset_and_mints_the_reconciliation_row():
    """The brewery accepts the opening figure, so the agreed offset is the claimed
    1200 rather than any countered number, the claim closes on the logical clock,
    and one `RECONCILIATION_OFFSET` accrual is minted against the claim itself.

    PRD: "The claim moves to `AGREED`, `closed_at` is stamped with the logical
    clock, and `agreed_offset_cents` is fixed to whichever figure was outstanding:
    the `counter_offset_cents` when a counter had been made, and the original
    `claimed_offset_cents` when the brewer simply accepted the opening claim."

    PRD: "A `ReturnIncentiveAccrual` of `accrual_type` `RECONCILIATION_OFFSET` is
    then minted for the claimant with `claim_id` set to this claim,
    `incentive_cents` equal to `agreed_offset_cents`, and `status` `ACCRUED`; the
    distributor's `incentive_accrual_cents` grows by that amount."

    PRD: "Finally the keg's `misdelivery_open` flag is cleared and the keg's
    `version` advances."

    Design: Corner/state_machines/agreed_claim_offset_syncs_the_incentive_ledger_without_touching_return_statistics
    """
    ctx = _a_misdelivery_the_receiving_brewery_agrees_to_pay()
    agreed = ctx["agreed"]

    assert ctx["misdelivery_scan"]["misdelivery_detected"] is True
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_offset_cents"] == 1200
    assert agreed["counter_offset_cents"] is None
    assert agreed["closed_at"] == CLOCK
    assert agreed["claimant_distributor_id"] == ctx["distributor"]["id"]
    assert agreed["misdelivered_to_brewer_id"] == ctx["other_brewer"]["id"]
    assert agreed["owning_brewer_id"] == ctx["brewer"]["id"]

    assert len(ctx["accruals"]) == 1
    accrual = ctx["accruals"][0]
    assert accrual["accrual_type"] == "RECONCILIATION_OFFSET"
    assert accrual["claim_id"] == ctx["claim"]["id"]
    assert accrual["distributor_id"] == ctx["distributor"]["id"]
    assert accrual["keg_id"] == ctx["keg_id"]
    assert accrual["incentive_cents"] == 1200
    assert accrual["status"] == "ACCRUED"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["misdelivery_open"] is False
    assert keg["custody_state"] == "IN_TRADE"


def test_the_offset_moves_the_ledger_and_leaves_the_return_statistics_alone():
    """The 1200 cents lands in the ledger while every return figure stays at its
    opening value: no returns are counted, the mean dwell is still zero, and a
    distributor that has never returned a keg is still at tier `NONE` with no
    promotion evaluated.

    PRD: "Crucially, a reconciliation offset is **not** a return:
    `total_returns_count`, `on_time_returns_count`, `on_time_return_pct`,
    `avg_dwell_days` and `cooperation_tier` are all left exactly as they were, and
    no tier promotion is evaluated."

    PRD: "`RECONCILIATION_OFFSET` accruals are excluded from all four figures."

    PRD: "A distributor's `incentive_accrual_cents` is at all times the sum of
    `incentive_cents` over that distributor's accruals whose `status` is `ACCRUED`
    or `PAID`."

    Design: Corner/state_machines/agreed_claim_offset_syncs_the_incentive_ledger_without_touching_return_statistics
    """
    ctx = _a_misdelivery_the_receiving_brewery_agrees_to_pay()

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["incentive_accrual_cents"] == 1200
    assert distributor["total_returns_count"] == 0
    assert distributor["on_time_returns_count"] == 0
    assert distributor["on_time_return_pct"] == 0.00
    assert distributor["avg_dwell_days"] == 0.00
    assert distributor["cooperation_tier"] == "NONE"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 1,
            "kegs_circulating": 1,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"
