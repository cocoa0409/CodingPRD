"""Multi-level cascades out of approval, out of execution, and back again."""
from test_helpers import (
    CLOCK_PLUS_181,
    TEST_DEFAULTS,
    approve_request,
    assert_inventory_conserved,
    assert_sweep_report,
    create_eligible_carrier,
    create_rate_center,
    create_submitted_filing,
    execute_order,
    file_allocation_request,
    list_orders,
    load_held_blocks,
    load_pool_blocks,
    read_block,
    read_carrier,
    read_npa,
    read_order,
    read_rate_center,
    read_request,
    run_sweep,
    set_clock,
    setup_npa_with_rate_center,
    surrender_order,
)


def _five_block_pool_with_a_sibling_rate_center():
    """NPA 614 holding five available blocks in COLUMBUS and none in DUBLIN."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    sibling = create_rate_center(npa, name=TEST_DEFAULTS["SIBLING_RATE_CENTER_NAME"])
    pool_blocks = load_pool_blocks(npa, rate_center, 5, nxx_code="556")
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[3000, 2000, 1000, 500],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one growth block",
    )
    return carrier, npa, rate_center, sibling, pool_blocks, request


class TestApprovalCascadesIntoJeopardy:
    """One approval walks from the request down to the area code's posture."""

    def test_the_reservation_walks_through_every_counter_into_jeopardy(self):
        """Approving a single block moves the block, the rate center, the carrier and
        finally the area code, which crosses the four-block line.

        Step two moves each drawn block from `POOL_AVAILABLE` to `RESERVED`, setting its
        `holder_carrier_id` to the request's `carrier_id`, its `assigned_at` to the logical
        clock, its `activation_due_at` to 180 days after the logical clock

        A code with at most four available blocks becomes `JEOPARDY` — the comparison is
        inclusive, so exactly four available blocks is `JEOPARDY` while five is not.

        Design: Difficulty/transitive_cascade/approval_reserves_block_and_drives_npa_into_jeopardy
        """
        carrier, npa, rate_center, _sibling, pool_blocks, request = (
            _five_block_pool_with_a_sibling_rate_center()
        )
        assert read_npa(npa["id"])["status"] == "ACTIVE"
        assert read_npa(npa["id"])["available_block_count"] == 5

        approve_request(request)

        decided = read_request(request["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
        assert decided["assigned_block_ids"] == [pool_blocks[0]["id"]]

        drawn = read_block(pool_blocks[0]["id"])
        assert drawn["allocation_status"] == "RESERVED"
        assert drawn["holder_carrier_id"] == carrier["id"]
        assert drawn["activation_due_at"] == "2027-01-28T00:00:00Z"

        after = read_rate_center(rate_center["id"])
        assert after["available_block_count"] == 4
        assert after["assigned_block_count"] == 1
        assert read_carrier(carrier["id"])["blocks_held_count"] == 1

        code = read_npa(npa["id"])
        assert code["available_block_count"] == 4
        assert code["status"] == "JEOPARDY"

    def test_the_jeopardy_flag_reaches_the_rate_center_that_lost_nothing(self):
        """DUBLIN never held a block and never saw the request, yet it stops accepting
        initial demand because the cascade is code-wide.

        every rate center under the code has `jeopardy_flag` set to true, which flips each
        one's computed `accepts_initial_requests` to false

        Step five, if that move fired, sets `jeopardy_flag` to true on every rate center
        under the code, which turns each of their computed `accepts_initial_requests` values
        false.

        Design: Difficulty/transitive_cascade/approval_reserves_block_and_drives_npa_into_jeopardy
        """
        _carrier, npa, rate_center, sibling, _pool_blocks, request = (
            _five_block_pool_with_a_sibling_rate_center()
        )
        assert read_rate_center(sibling["id"])["jeopardy_flag"] is False
        assert read_rate_center(sibling["id"])["accepts_initial_requests"] is True

        approve_request(request)

        assert read_npa(npa["id"])["status"] == "JEOPARDY"
        touched = read_rate_center(rate_center["id"])
        assert touched["jeopardy_flag"] is True
        assert touched["accepts_initial_requests"] is False

        untouched = read_rate_center(sibling["id"])
        assert untouched["jeopardy_flag"] is True
        assert untouched["accepts_initial_requests"] is False
        assert untouched["available_block_count"] == 0
        assert untouched["assigned_block_count"] == 0


def _two_surrendered_orders_against_one_carrier():
    """Both of carrier A's unactivated blocks are swept and surrendered, ready to execute."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    blocks = load_held_blocks(
        npa, rate_center, carrier, 2, nxx_code="555", first_thousands_digit=0,
        mark_activated=False,
    )
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[3000, 2000, 1000, 500],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one growth block pending review",
    )
    set_clock(CLOCK_PLUS_181)
    sweep = run_sweep(rate_center_id=rate_center["id"])
    orders = [list_orders(number_block_id=block["id"])[0] for block in blocks]
    for order in orders:
        surrender_order(order, carrier)
    return carrier, rate_center, blocks, request, orders, sweep


class TestReclamationExecutionCascadesIntoProbation:
    """The second strike is the one that reaches the carrier's pending queue."""

    def test_the_first_execution_costs_one_strike_and_disturbs_nothing_else(self):
        """A single strike is below the two-strike line, so eligibility and the request
        in the queue are both left exactly as they were.

        Step one drives the block from `RECLAMATION_PENDING` to `AGING`, stamping
        `aging_release_at` 90 days after the logical clock and clearing `holder_carrier_id`,
        `assigned_at`, `activation_due_at` and `activated_at`.

        Step two recomputes the former holder's `blocks_held_count`, because the block has
        left it, and increments that carrier's `reclamation_strike_count` by 1.

        Design: Difficulty/transitive_cascade/reclamation_execution_strikes_carrier_into_probation_and_stalls_request
        """
        carrier, _rate_center, blocks, request, orders, sweep = (
            _two_surrendered_orders_against_one_carrier()
        )
        assert_sweep_report(sweep, 2, 0, 0, CLOCK_PLUS_181)

        execute_order(orders[0])

        struck = read_carrier(carrier["id"])
        assert struck["reclamation_strike_count"] == 1
        assert struck["eligibility_status"] == "ELIGIBLE"
        assert struck["probation_until"] is None
        assert struck["blocks_held_count"] == 1
        assert read_request(request["id"])["status"] == "PENDING_REVIEW"

        aged = read_block(blocks[0]["id"])
        assert aged["allocation_status"] == "AGING"
        assert aged["aging_release_at"] == "2027-04-29T00:00:00Z"
        assert aged["holder_carrier_id"] is None
        assert aged["assigned_at"] is None
        assert aged["activation_due_at"] is None
        assert aged["activated_at"] is None

    def test_the_second_execution_drives_probation_and_stalls_the_queued_request(self):
        """Reaching two strikes moves the carrier onto probation, and probation reaches
        across into the growth request nobody has reviewed yet.

        Step three fires when `reclamation_strike_count` reaches two: the carrier's
        `eligibility_status` becomes `PROBATION` and `probation_until` is stamped 180 days
        after the logical clock.

        Step four fires because the carrier entered probation: each of that carrier's
        allocation requests in `PENDING_REVIEW` whose `request_type` is `GROWTH` or
        `POOL_REPLENISH` moves to `INFO_REQUESTED` with `info_request_count` incremented by 1

        Design: Difficulty/transitive_cascade/reclamation_execution_strikes_carrier_into_probation_and_stalls_request
        """
        carrier, rate_center, blocks, request, orders, _sweep = (
            _two_surrendered_orders_against_one_carrier()
        )

        execute_order(orders[0])
        execute_order(orders[1])

        closed = read_order(orders[1]["id"])
        assert closed["status"] == "EXECUTED"
        assert closed["strike_applied"] is True
        assert closed["executed_at"] == CLOCK_PLUS_181

        second_block = read_block(blocks[1]["id"])
        assert second_block["allocation_status"] == "AGING"
        assert second_block["aging_release_at"] == "2027-04-29T00:00:00Z"
        assert second_block["holder_carrier_id"] is None

        punished = read_carrier(carrier["id"])
        assert punished["blocks_held_count"] == 0
        assert punished["reclamation_strike_count"] == 2
        assert punished["eligibility_status"] == "PROBATION"
        assert punished["probation_until"] == "2027-07-28T00:00:00Z"

        stalled = read_request(request["id"])
        assert stalled["status"] == "INFO_REQUESTED"
        assert stalled["info_request_count"] == 1
        assert stalled["reviewer_user_id"] is None
        # An AGING block is nobody's, but it is not available inventory either.
        assert read_rate_center(rate_center["id"])["available_block_count"] == 0


AGING_RELEASE_INSTANT = "2027-04-29T00:00:00Z"


def _approved_block_that_is_never_activated():
    """One of five pool blocks is reserved by approval and then simply forgotten."""
    carrier, npa, rate_center, sibling, pool_blocks, request = (
        _five_block_pool_with_a_sibling_rate_center()
    )
    approve_request(request)
    return carrier, npa, rate_center, sibling, pool_blocks[0], request


class TestInventoryIsConservedAcrossReclamation:
    """Everything the reclamation moved comes back; the penalty does not."""

    def test_the_reclaim_holds_the_block_outside_available_inventory(self):
        """Between the sweep and the aging release the block belongs to nobody and is
        still not assignable, so the available count stays down at four.

        A block whose `allocation_status` is `RESERVED`, whose `activated_at` is still null, and
        whose activation deadline has passed moves to `RECLAMATION_PENDING` and receives a
        new order.

        Step one drives the block from `RECLAMATION_PENDING` to `AGING`, stamping
        `aging_release_at` 90 days after the logical clock and clearing `holder_carrier_id`,
        `assigned_at`, `activation_due_at` and `activated_at`.

        Design: Difficulty/compensating_invariant/block_inventory_conserved_across_approve_reclaim_and_aging_release
        """
        carrier, npa, rate_center, _sibling, block, _request = (
            _approved_block_that_is_never_activated()
        )

        set_clock(CLOCK_PLUS_181)
        sweep = run_sweep(rate_center_id=rate_center["id"])
        assert_sweep_report(sweep, 1, 0, 0, CLOCK_PLUS_181)
        assert read_block(block["id"])["allocation_status"] == "RECLAMATION_PENDING"

        order = list_orders(number_block_id=block["id"])[0]
        assert order["reason"] == "ACTIVATION_DEADLINE_MISSED"
        surrender_order(order, carrier)
        execute_order(order)

        aged = read_block(block["id"])
        assert aged["allocation_status"] == "AGING"
        assert aged["aging_release_at"] == AGING_RELEASE_INSTANT
        assert read_rate_center(rate_center["id"])["available_block_count"] == 4
        code = read_npa(npa["id"])
        assert code["available_block_count"] == 4
        assert code["status"] == "JEOPARDY"

    def test_the_aging_release_restores_every_counter_but_never_the_strike(self):
        """Once aging elapses the pool, the rate center, the area code and the block are
        all back where they started, while the carrier keeps its strike and the approval
        keeps its record.

        A block whose `allocation_status` is `AGING` and whose `aging_release_at` is at or before
        the sweep instant returns to `POOL_AVAILABLE` with `aging_release_at` cleared.

        Recovering `JEOPARDY → ACTIVE` — which happens when the available count rises strictly above
        four — sets `status` to `ACTIVE`, clears `jeopardy_declared_at` back to null

        which is what guarantees at most one strike per order however many times the surrounding
        cascade is recomputed

        Design: Difficulty/compensating_invariant/block_inventory_conserved_across_approve_reclaim_and_aging_release
        """
        carrier, npa, rate_center, sibling, block, request = (
            _approved_block_that_is_never_activated()
        )
        set_clock(CLOCK_PLUS_181)
        run_sweep(rate_center_id=rate_center["id"])
        order = list_orders(number_block_id=block["id"])[0]
        surrender_order(order, carrier)
        execute_order(order)

        set_clock(AGING_RELEASE_INSTANT)
        second_sweep = run_sweep(rate_center_id=rate_center["id"])
        assert_sweep_report(second_sweep, 0, 1, 0, AGING_RELEASE_INSTANT)

        restored_rate_center = read_rate_center(rate_center["id"])
        assert restored_rate_center["available_block_count"] == 5
        assert restored_rate_center["assigned_block_count"] == 0
        assert restored_rate_center["jeopardy_flag"] is False
        restored_code = read_npa(npa["id"])
        assert restored_code["available_block_count"] == 5
        assert restored_code["status"] == "ACTIVE"
        assert restored_code["jeopardy_declared_at"] is None
        assert_inventory_conserved(
            restored_code, [restored_rate_center, read_rate_center(sibling["id"])]
        )

        released = read_block(block["id"])
        assert released["allocation_status"] == "POOL_AVAILABLE"
        assert released["holder_carrier_id"] is None
        assert released["assigned_at"] is None
        assert released["activation_due_at"] is None
        assert released["aging_release_at"] is None

        # The compensation stops at inventory: the penalty and the decision both stand.
        uncompensated = read_carrier(carrier["id"])
        assert uncompensated["blocks_held_count"] == 0
        assert uncompensated["reclamation_strike_count"] == 1
        decided = read_request(request["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
