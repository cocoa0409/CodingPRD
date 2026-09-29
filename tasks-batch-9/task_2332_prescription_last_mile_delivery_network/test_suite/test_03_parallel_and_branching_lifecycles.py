"""Two shapes of non-linear lifecycle.

A delivery carries two independent status dimensions on one row, so reaching a
terminal value on one says nothing about the other. An exception case instead
forks: one disposition moves money and creates nothing, the other creates a bag
and commits money, and both re-join at the same terminus.
"""

import pytest

from test_helpers import (
    CLOCK_DOORSTEP_DAY3,
    TEST_USERS,
    Z1_STANDARD_LINES,
    Z1_STANDARD_SUBTOTAL_CENTS,
    adjudicate,
    advance_to_assigned,
    advance_to_out_for_delivery,
    advance_to_picked_up,
    allocations_for,
    assert_delivery_state,
    assert_grant_ledger,
    assert_window_occupancy,
    build_queued_delivery,
    deliver,
    exhaust_attempt_ladder,
    factories,
    find_by,
    read_case,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    settle,
    start_review,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 2,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}


@pytest.fixture
def delivered_but_unsettled(api):
    """A standard bag whose custody dimension is already terminal."""
    scn = build_queued_delivery(
        api,
        order_kwargs=STANDARD_ORDER,
        window_kwargs={"capacity_slots": 2},
    )
    advance_to_assigned(api, scn)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=utc_ts(3, 14, 10))
    deliver(api, scn, id_verification_method="DOB_MATCH", signature_captured=False)
    return scn


class TestParallelStatusDimensions:
    """"The delivery's `settlement_status` does **not** move — the bill is still
    `PROVISIONAL` and stays that way until settlement."
    """

    def test_custody_reaches_its_terminus_while_the_bill_is_still_provisional(
        self, api, delivered_but_unsettled
    ):
        """One row, two dimensions, only one of them finished.

        "The delivery's `settlement_status` does **not** move — the bill is
        still `PROVISIONAL` and stays that way until settlement."

        Design: Difficulty/non_linear_state_machine/delivery_custody_and_settlement_dimensions_advance_independently
        """
        scn = delivered_but_unsettled
        delivery = read_delivery(api, scn.delivery["id"])
        assert_delivery_state(delivery, "DELIVERED", "PROVISIONAL")

    def test_settlement_moves_the_money_dimension_and_leaves_custody_untouched(
        self, api, delivered_but_unsettled
    ):
        """The money dimension advances on its own clock.

        "The delivery's `settlement_status` moves `PROVISIONAL → FINALIZED`, its
        `fee_subtotal_cents` mirrors the final allocation's, and its
        `custody_status` does not move at all — it stays `DELIVERED` or
        `RETURNED`."

        Design: Difficulty/non_linear_state_machine/delivery_custody_and_settlement_dimensions_advance_independently
        """
        scn = delivered_but_unsettled
        settle(api, scn)

        assert_delivery_state(scn.delivery, "DELIVERED", "FINALIZED")
        assert scn.delivery["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS

        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]),
            committed_cents=0,
            consumed_cents=150,
        )

        rows = allocations_for(api, scn.delivery["id"])
        assert len(rows) == 2
        superseded = find_by(rows, variant="PROVISIONAL")
        assert superseded["status"] == "SUPERSEDED"
        final = find_by(rows, variant="FINAL")
        assert final["status"] == "ACTIVE"
        assert final["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS
        assert final["patient_payable_cents"] == 0

        assert read_order(api, scn.order["id"])["status"] == "CLOSED"

    def test_terminal_custody_still_refuses_a_further_door_step_run_after_settling(
        self, api, delivered_but_unsettled
    ):
        """A moving money dimension does not reopen the physical one.

        "`Delivery.custody_status` is in the operation's allowed from-set —
        otherwise `ERR_INVALID_CUSTODY_STATE`. Guards dispatching, pickup,
        departure, recording an attempt, cancelling, rescheduling, confirming a
        return, settling, and opening an exception case, and it is what locks
        down the terminal values `DELIVERED`, `RETURNED`, and `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/delivery_custody_and_settlement_dimensions_advance_independently
        """
        scn = delivered_but_unsettled
        settle(api, scn)

        response = api.record_attempt(
            scn.delivery["id"],
            factories.attempt_payload("DELIVERED", id_verification_method="DOB_MATCH"),
            headers=scn.courier_headers,
        )
        validate_error(response, "ERR_INVALID_CUSTODY_STATE", 409)
        assert_delivery_state(
            read_delivery(api, scn.delivery["id"]), "DELIVERED", "FINALIZED"
        )


@pytest.fixture
def case_under_review_after_exhausted_ladder(api):
    """Three no-answer runs, a system-opened case, taken up by the reviewer."""
    scn = build_queued_delivery(
        api,
        order_kwargs=STANDARD_ORDER,
        window_kwargs={"window_end": utc_ts(3, 22), "capacity_slots": 2},
    )
    advance_to_assigned(api, scn)
    advance_to_picked_up(api, scn)
    advance_to_out_for_delivery(api, scn, depart_clock=CLOCK_DOORSTEP_DAY3)
    exhaust_attempt_ladder(api, scn, first_attempt_clock=CLOCK_DOORSTEP_DAY3)
    scn.case = start_review(
        api, scn.case["id"], headers=TEST_USERS["ops_reviewer"]
    )
    return scn


class TestExceptionCaseBranching:
    """"**Branch B — `CREDIT`.** This is the exact mirror image: financially
    compensating and physically inert."
    """

    def test_credit_branch_records_the_voided_subtotal_and_creates_no_bag(
        self, api, case_under_review_after_exhausted_ladder
    ):
        """The financially compensating branch leaves nothing physical behind.

        "the case's `credit_cents` records the `fee_subtotal_cents` of the
        allocation that was just voided. No reship delivery is created and no
        window slot is reserved."

        Design: Difficulty/non_linear_state_machine/exception_case_credit_branch_diverges_from_reship_branch
        """
        scn = case_under_review_after_exhausted_ladder
        assert scn.case["exception_type"] == "ATTEMPTS_EXHAUSTED"
        assert scn.case["opened_by_ops_user_id"] is None

        version = read_delivery(api, scn.delivery["id"])["version"]
        case = adjudicate(
            api,
            scn.case["id"],
            "CREDIT",
            version,
            headers=TEST_USERS["ops_reviewer"],
            notes="Three no-answer runs; fee credited to the pharmacy.",
        )
        assert case["status"] == "CREDIT_ISSUED"
        assert case["disposition"] == "CREDIT"
        assert case["credit_cents"] == Z1_STANDARD_SUBTOTAL_CENTS
        assert case["reship_delivery_id"] is None

        _rows, meta = validate_paginated(
            api.list_deliveries(
                TEST_USERS["ops"], reship_of_delivery_id=scn.delivery["id"]
            )
        )
        assert meta["total_count"] == 0

    def test_credit_branch_waives_the_bill_and_releases_the_pool(
        self, api, case_under_review_after_exhausted_ladder
    ):
        """The reversal is recorded rather than erased, and the pool recovers.

        "The delivery's settlement moves `PROVISIONAL → WAIVED`, the `ACTIVE`
        allocation is set to `VOIDED`, the delivery's `fee_subtotal_cents` is
        zeroed, the voided `plan_grant_cents` is released from the pool's
        `committed_cents` with the pool returning `EXHAUSTED → ACTIVE` if
        `remaining_cents` rises above 0"

        Design: Difficulty/non_linear_state_machine/exception_case_credit_branch_diverges_from_reship_branch
        """
        scn = case_under_review_after_exhausted_ladder
        version = read_delivery(api, scn.delivery["id"])["version"]
        adjudicate(
            api,
            scn.case["id"],
            "CREDIT",
            version,
            headers=TEST_USERS["ops_reviewer"],
        )

        delivery = read_delivery(api, scn.delivery["id"])
        assert_delivery_state(delivery, "RETURN_PENDING", "WAIVED")
        assert delivery["fee_subtotal_cents"] == 0

        rows = allocations_for(api, scn.delivery["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "VOIDED"
        assert rows[0]["fee_subtotal_cents"] == sum(Z1_STANDARD_LINES)

        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]),
            committed_cents=0,
            remaining_cents=100000,
            status="ACTIVE",
        )
        assert_window_occupancy(
            read_window(api, scn.window["id"]), reserved_slots=0, available_slots=2
        )

    def test_the_credit_branch_rejoins_the_shared_closed_terminus(
        self, api, case_under_review_after_exhausted_ladder
    ):
        """Both branches converge on one terminal value.

        "All three branches re-join at a single terminus. A case whose `status`
        is `RESHIP_AUTHORIZED`, `CREDIT_ISSUED`, or `DENIED` is closed, moving it
        to `CLOSED` and bumping its `version`"

        Design: Difficulty/non_linear_state_machine/exception_case_credit_branch_diverges_from_reship_branch
        """
        scn = case_under_review_after_exhausted_ladder
        version = read_delivery(api, scn.delivery["id"])["version"]
        adjudicate(
            api,
            scn.case["id"],
            "CREDIT",
            version,
            headers=TEST_USERS["ops_reviewer"],
        )
        closed = validate_success(
            api.close_exception_case(scn.case["id"], headers=TEST_USERS["ops_reviewer"])
        )
        assert closed["status"] == "CLOSED"
        assert read_case(api, scn.case["id"])["status"] == "CLOSED"
