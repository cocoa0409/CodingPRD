"""Augment orders: acceptance windows, crew collisions, completion and reversal."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AUGMENT_WINDOW_COLLISION,
    ERR_INSTALLED_TRUNKS_INVALID,
    ERR_INVALID_AUGMENT_ORDER_STATE,
    ERR_INVALID_COMMITTED_DUE_DATE,
    ERR_INVALID_MEASUREMENT_PERIOD,
)
from test_helpers.assertions import assert_trunk_group_statuses
from test_helpers.constants import T_2026_08_01, T_2026_09_15
from test_helpers.factories import (
    accept_augment_payload,
    complete_augment_payload,
    measurement_payload,
    reject_augment_payload,
    reverse_augment_payload,
)
from test_helpers.fixtures import (
    latest_pending_order,
    read_agreement,
    read_augment_order,
    read_trunk_group,
    record_measurement,
    setup_accepted_augment_order,
    setup_completed_augment_order,
    setup_effective_agreement,
    setup_effective_agreement_with_in_service_trunks,
    setup_in_service_trunk_group,
    setup_pending_augment_order,
)

DUE_2026_09_22 = "2026-09-22T00:00:00.000Z"
DUE_2026_09_23 = "2026-09-23T00:00:00.000Z"
WINDOW_START_FIRST = "2026-09-10T00:00:00.000Z"
WINDOW_START_SECOND = "2026-09-18T00:00:00.000Z"


def test_augment_acceptance_with_a_past_due_date_is_refused(api):
    """A committed due date behind the logical clock is refused and fixes no window.

    PRD 3.4: "**Accepting** it moves the order `PENDING → ACCEPTED` and requires a `committed_due_date` strictly after the logical clock — a due date at or before the current instant is refused with `ERR_INVALID_COMMITTED_DUE_DATE`."
    PRD 3.4: "Acceptance fixes the installation window: `install_window_start` is the committed due date less **five days**, and `install_window_end` is the committed due date itself."

    Design: Corner/errors/augment_acceptance_with_a_past_due_date_is_refused
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    _, order = setup_pending_augment_order(api, state["trunk_group_id"])

    response = api.accept_augment_order(
        order["id"],
        accept_augment_payload("2026-07-20T00:00:00.000Z"),
        state["rep_headers"],
    )
    validate_error(response, ERR_INVALID_COMMITTED_DUE_DATE, expected_status=422)

    unchanged = read_augment_order(api, order["id"])
    assert unchanged["status"] == "PENDING"
    assert unchanged["committed_due_date"] is None
    assert unchanged["install_window_start"] is None
    assert unchanged["install_window_end"] is None

    trunk_group = read_trunk_group(api, state["trunk_group_id"])
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "AUGMENT_ORDERED")
    assert trunk_group["open_augment_order_count"] == 1


def test_augment_completion_with_a_partial_ds1_and_a_zero_length_measurement_are_refused(
    api, planner_headers
):
    """Twelve installed trunks and an equal-instant study period are both refused.

    PRD 3.4: "**Completion** is the `NetworkPlanner`'s to record against an `ACCEPTED` order, supplying `installed_trunks`. That quantity must be a positive multiple of 24 and must not exceed the order's `requested_additional_trunks`; a violation of either condition is refused with `ERR_INSTALLED_TRUNKS_INVALID`."
    PRD 3.4: "The period end must fall strictly after the period start; equal or inverted instants are refused with `ERR_INVALID_MEASUREMENT_PERIOD`."

    Design: Corner/errors/augment_completion_with_a_partial_ds1_and_a_zero_length_measurement_are_refused
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]
    _, order = setup_accepted_augment_order(
        api, trunk_group_id, state["rep_headers"], committed_due_date=T_2026_09_15
    )

    partial = api.complete_augment_order(
        order["id"], complete_augment_payload(12), planner_headers
    )
    validate_error(partial, ERR_INSTALLED_TRUNKS_INVALID, expected_status=422)

    zero_length = api.create_traffic_measurement(
        trunk_group_id,
        measurement_payload(
            measurement_period_start="2026-07-31T00:00:00.000Z",
            measurement_period_end="2026-07-31T00:00:00.000Z",
            offered_calls=5000,
            blocked_calls=10,
            busy_hour_ccs=1500.00,
        ),
        planner_headers,
    )
    validate_error(zero_length, ERR_INVALID_MEASUREMENT_PERIOD, expected_status=422)

    unchanged = read_augment_order(api, order["id"])
    assert unchanged["status"] == "ACCEPTED"
    assert unchanged["installed_trunks"] is None

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert trunk_group["provisioned_trunks"] == 48
    assert trunk_group["augment_status"] == "AUGMENT_ORDERED"

    _, meta = validate_paginated(
        api.list_trunk_group_measurements(trunk_group_id, planner_headers)
    )
    assert meta["total_count"] == 1, "the refused study must not be persisted"


def test_rejected_augment_order_accepts_no_further_transition(api):
    """A REJECTED order is terminal, so a later acceptance conflicts.

    PRD 3.4: "**Rejecting** the order instead moves it `PENDING → REJECTED` with a supplied `rejection_reason`, and that refusal propagates: the trunk group's `augment_status` moves `AUGMENT_ORDERED → AUGMENT_BLOCKED` and its `open_augment_order_count` decrements by 1; the agreement's `poi_augment_pending_count` decrements by 1 and its `capacity_posture` is recomputed to `BLOCKED`; and the order's, the trunk group's and the agreement's `version` each increment by 1."
    PRD 3.4: "Accepting or rejecting an order that is not in `PENDING` is refused with `ERR_INVALID_AUGMENT_ORDER_STATE`."

    Design: Corner/state_machines/rejected_augment_order_accepts_no_further_transition
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]
    _, order = setup_pending_augment_order(api, trunk_group_id)
    rejected = validate_success(
        api.reject_augment_order(
            order["id"], reject_augment_payload(), state["rep_headers"]
        ),
        expected_status=200,
    )
    assert rejected["status"] == "REJECTED"

    response = api.accept_augment_order(
        order["id"], accept_augment_payload(T_2026_09_15), state["rep_headers"]
    )
    validate_error(response, ERR_INVALID_AUGMENT_ORDER_STATE, expected_status=409)

    unchanged = read_augment_order(api, order["id"])
    assert unchanged["status"] == "REJECTED"
    assert unchanged["committed_due_date"] is None
    assert unchanged["install_window_start"] is None

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "AUGMENT_BLOCKED")
    assert trunk_group["open_augment_order_count"] == 0
    assert trunk_group["provisioned_trunks"] == 48
    assert trunk_group["required_trunks"] == 68

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["poi_augment_pending_count"] == 0
    assert agreement["capacity_posture"] == "BLOCKED"


def _two_pending_orders_one_accepted(api):
    """Two same-POI trunk groups, each with an order; the first accepted for 2026-09-15."""
    state = setup_effective_agreement(api)
    first_group = setup_in_service_trunk_group(api, state["agreement_id"], 48)
    second_group = setup_in_service_trunk_group(
        api,
        state["agreement_id"],
        48,
        trunk_group_serial="TG-DLLS-OUT-002",
        direction="ONE_WAY_OUTBOUND",
    )
    record_measurement(api, first_group["id"])
    record_measurement(api, second_group["id"])
    first_order = latest_pending_order(api, first_group["id"])
    second_order = latest_pending_order(api, second_group["id"])
    accepted = validate_success(
        api.accept_augment_order(
            first_order["id"],
            accept_augment_payload(T_2026_09_15),
            state["rep_headers"],
        ),
        expected_status=200,
    )
    assert accepted["install_window_start"] == WINDOW_START_FIRST
    assert accepted["install_window_end"] == T_2026_09_15
    return state, accepted, second_order


def test_buffered_augment_install_windows_collide_when_they_touch(api):
    """A due date whose buffered window merely touches the peer's is a collision.

    PRD 3.4: "Because there is one installation crew per point of interconnection, accepted windows may not collide. For collision testing each window is padded by **twenty-four hours** on both edges: the buffered window runs from `install_window_start` less twenty-four hours to `install_window_end` plus twenty-four hours."
    PRD 3.4: "Two buffered windows collide when the peer's buffered start is at or before the candidate's buffered end **and** the candidate's buffered start is at or before the peer's buffered end; both comparisons are inclusive, so buffered windows that merely touch at a single instant do collide. A collision is refused with `ERR_AUGMENT_WINDOW_COLLISION`."
    PRD 3.4: "The candidate order's buffered window is compared against the buffered window of every other augment order whose trunk group shares the same agreement and `poi_clli_code` and whose `status` is `ACCEPTED`."

    Design: Difficulty/resource_temporal_overlap/buffered_augment_install_windows_collide_when_they_touch
    """
    state, first_order, second_order = _two_pending_orders_one_accepted(api)

    response = api.accept_augment_order(
        second_order["id"],
        accept_augment_payload(DUE_2026_09_22),
        state["rep_headers"],
    )
    validate_error(response, ERR_AUGMENT_WINDOW_COLLISION, expected_status=409)

    unchanged = read_augment_order(api, second_order["id"])
    assert unchanged["status"] == "PENDING"
    assert unchanged["committed_due_date"] is None
    assert unchanged["install_window_start"] is None
    assert unchanged["install_window_end"] is None

    peer = read_augment_order(api, first_order["id"])
    assert peer["status"] == "ACCEPTED"
    assert peer["install_window_end"] == T_2026_09_15


def test_augment_install_window_one_day_clear_of_the_peer_is_accepted(api):
    """One day further out the buffered windows part and the acceptance lands.

    PRD 3.4: "Acceptance fixes the installation window: `install_window_start` is the committed due date less **five days**, and `install_window_end` is the committed due date itself. That raw window is a **closed interval** — installation work may land on either edge."
    PRD 3.4: "Two buffered windows collide when the peer's buffered start is at or before the candidate's buffered end **and** the candidate's buffered start is at or before the peer's buffered end; both comparisons are inclusive, so buffered windows that merely touch at a single instant do collide. A collision is refused with `ERR_AUGMENT_WINDOW_COLLISION`."
    PRD 3.4: "On success the order's `version` increments by 1."

    Design: Difficulty/resource_temporal_overlap/buffered_augment_install_windows_collide_when_they_touch
    """
    state, first_order, second_order = _two_pending_orders_one_accepted(api)
    validate_error(
        api.accept_augment_order(
            second_order["id"],
            accept_augment_payload(DUE_2026_09_22),
            state["rep_headers"],
        ),
        ERR_AUGMENT_WINDOW_COLLISION,
        expected_status=409,
    )

    response = api.accept_augment_order(
        second_order["id"],
        accept_augment_payload(DUE_2026_09_23),
        state["rep_headers"],
    )
    accepted = validate_success(response, expected_status=200)

    assert accepted["status"] == "ACCEPTED"
    assert accepted["install_window_start"] == WINDOW_START_SECOND
    assert accepted["install_window_end"] == DUE_2026_09_23

    peer = read_augment_order(api, first_order["id"])
    assert peer["status"] == "ACCEPTED"
    assert peer["install_window_start"] == WINDOW_START_FIRST
    assert peer["install_window_end"] == T_2026_09_15

    assert read_agreement(api, state["agreement_id"])["poi_augment_pending_count"] == 2


def test_augment_reversal_restores_the_in_service_trunk_inventory(api, planner_headers):
    """Reversal removes exactly the trunks the completion added, on both rows.

    PRD 3.4: "On success the order moves `ACCEPTED → COMPLETED`; the trunk group's `provisioned_trunks` increases by `installed_trunks`, its `augment_status` moves `AUGMENT_ORDERED → NONE` and its `open_augment_order_count` decrements by 1; the agreement's `total_in_service_trunks` increases by `installed_trunks`, its `poi_augment_pending_count` decrements by 1 and its `capacity_posture` is recomputed; and all three rows' `version` values increment by 1."
    PRD 3.4: "The trunk group's `provisioned_trunks` decreases by exactly the `installed_trunks` the completion added, and its `augment_status` moves `NONE → GROOMING_REVIEW` so that the re-opened capacity gap is not silently lost."
    PRD 3.4: "The agreement's `total_in_service_trunks` decreases by the same `installed_trunks`, returning it to precisely its pre-completion value."

    Design: Difficulty/compensating_invariant/augment_reversal_restores_the_in_service_trunk_inventory
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]
    _, order = setup_completed_augment_order(
        api, trunk_group_id, state["rep_headers"], installed_trunks=24
    )
    assert order["status"] == "COMPLETED"
    assert read_trunk_group(api, trunk_group_id)["provisioned_trunks"] == 72
    assert read_agreement(api, state["agreement_id"])["total_in_service_trunks"] == 72

    response = api.reverse_augment_order(
        order["id"], reverse_augment_payload(), planner_headers
    )
    reversed_order = validate_success(response, expected_status=200)
    assert reversed_order["status"] == "REVERSED"

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert trunk_group["provisioned_trunks"] == 48, "exactly the pre-augment inventory"
    assert trunk_group["service_status"] == "IN_SERVICE"

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["total_in_service_trunks"] == 48, (
        "the agreement total returns to the sum over its IN_SERVICE trunk groups"
    )


def test_augment_reversal_keeps_the_installed_quantity_as_its_audit_record(
    api, planner_headers
):
    """The reversed order retains installed_trunks and reopens the grooming review.

    PRD 3.4: "**Reversal** exists for the case where the acceptance test fails after the fact, and it is a strict compensating action. A `NetworkPlanner` reverses a `COMPLETED` order with a `reversal_reason`, and the order's trunk group must still be in `PROVISIONED` or `IN_SERVICE`; the order moves `COMPLETED → REVERSED`, which is terminal, with `reversed_at` stamped from the logical clock."
    PRD 3.4: "The trunk group's `open_augment_order_count` is **unchanged**, because a reversed order is not an open order."
    PRD 3.4: "The agreement's `capacity_posture` is a derived summary with a fixed precedence. It is `BLOCKED` whenever any of the agreement's trunk groups has `augment_status` `AUGMENT_BLOCKED`; failing that, it is `CONSTRAINED` whenever `poi_augment_pending_count` is greater than zero; otherwise it is `NORMAL`."

    Design: Difficulty/compensating_invariant/augment_reversal_restores_the_in_service_trunk_inventory
    """
    state = setup_effective_agreement_with_in_service_trunks(api, provisioned_trunks=48)
    trunk_group_id = state["trunk_group_id"]
    _, order = setup_completed_augment_order(
        api, trunk_group_id, state["rep_headers"], installed_trunks=24
    )

    reversed_order = validate_success(
        api.reverse_augment_order(
            order["id"], reverse_augment_payload(), planner_headers
        ),
        expected_status=200,
    )

    assert reversed_order["status"] == "REVERSED"
    assert reversed_order["installed_trunks"] == 24, (
        "the installed quantity is retained as the audit record of what was undone"
    )
    assert reversed_order["reversed_at"] == T_2026_08_01

    trunk_group = read_trunk_group(api, trunk_group_id)
    assert_trunk_group_statuses(trunk_group, "IN_SERVICE", "GROOMING_REVIEW")
    assert trunk_group["open_augment_order_count"] == 0

    agreement = read_agreement(api, state["agreement_id"])
    assert agreement["poi_augment_pending_count"] == 0
    assert agreement["capacity_posture"] == "NORMAL"
