"""The routing ledger, the two block axes, and the porting lifecycle."""
from test_helpers import (
    ADMIN_HEADERS,
    DEFAULT_CLOCK,
    PORTING_HEADERS,
    ApiErrorId,
    api_client,
    approve_request,
    assert_single_open_routing_record,
    assert_sweep_report,
    confirm_activation,
    create_eligible_carrier,
    create_port_request_payload,
    create_submitted_filing,
    file_allocation_request,
    get_success_data,
    load_block,
    load_pool_blocks,
    make_carrier_representative_headers,
    port_transition,
    publish_routing_record,
    read_block,
    read_carrier,
    read_port_request,
    read_routing_records,
    run_sweep,
    set_clock,
    setup_concurred_port_request,
    setup_npa_with_rate_center,
    setup_routed_assigned_block,
    validate_error,
)

REHOME_INSTANT = "2026-09-01T00:00:00Z"


def _reserved_but_unrouted_block():
    """An approved block: RESERVED on the allocation axis, UNROUTED on the routing axis."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    pool_blocks = load_pool_blocks(npa, rate_center, 1, nxx_code="556")
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[3000, 2000, 1000, 500],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one block",
    )
    approve_request(request)
    block = read_block(pool_blocks[0]["id"])
    assert block["allocation_status"] == "RESERVED"
    assert block["routing_status"] == "UNROUTED"
    assert block["npac_db_version"] == 0
    return carrier, rate_center, block


class TestTheTwoBlockAxesAdvanceIndependently:
    """Routing publication and activation confirmation move different fields."""

    def test_publishing_routing_moves_only_the_routing_axis(self):
        """A block still waiting for its activation confirmation can be fully routed.

        From `UNROUTED`, an `effective_at` at or before the logical clock moves it to
        `LERG_PUBLISHED` with `current_lrn` set from the record

        The block's `npac_db_version` is incremented by 1 and stamped onto the new record,
        and the block's `version` is incremented by 1. `allocation_status` is never touched
        by a routing publication.

        Design: Difficulty/non_linear_state_machine/block_allocation_and_routing_axes_advance_independently
        """
        _carrier, _rate_center, block = _reserved_but_unrouted_block()

        record = publish_routing_record(block, lrn="6145560000", effective_at=DEFAULT_CLOCK)

        routed = read_block(block["id"])
        assert routed["allocation_status"] == "RESERVED"
        assert routed["routing_status"] == "LERG_PUBLISHED"
        assert routed["current_lrn"] == "6145560000"
        assert routed["npac_db_version"] == 1

        assert record["record_status"] == "PUBLISHED"
        assert record["end_at"] is None
        assert record["npac_db_version"] == 1

    def test_confirming_activation_moves_only_the_allocation_axis(self):
        """The confirmation carries the block to ASSIGNED and leaves every routing field
        exactly where the publication left it.

        Confirmation stamps `activated_at` at the logical clock, which moves the block to
        `ASSIGNED` and takes it out of the sweep's reach, leaves `routing_status` untouched,
        and increments the block's `version` by 1.

        Design: Difficulty/non_linear_state_machine/block_allocation_and_routing_axes_advance_independently
        """
        carrier, _rate_center, block = _reserved_but_unrouted_block()
        publish_routing_record(block, lrn="6145560000", effective_at=DEFAULT_CLOCK)

        confirm_activation(read_block(block["id"]), carrier, activated_number_count=700)

        activated = read_block(block["id"])
        assert activated["allocation_status"] == "ASSIGNED"
        assert activated["routing_status"] == "LERG_PUBLISHED"
        assert activated["npac_db_version"] == 1
        assert activated["current_lrn"] == "6145560000"
        assert activated["activated_at"] == DEFAULT_CLOCK
        assert activated["activation_due_at"] == "2027-01-28T00:00:00Z"
        assert len(read_routing_records(block["id"])) == 1


def _assigned_block_that_was_never_routed():
    """Carrier A holds 614-558-3 as ASSIGNED with an untouched routing axis."""
    set_clock()
    carrier_a = create_eligible_carrier("A")
    carrier_b = create_eligible_carrier("B")
    npa, rate_center = setup_npa_with_rate_center()
    block = load_block(
        npa, rate_center, nxx_code="558", thousands_digit=3, contaminated_count=0,
        holder_carrier_id=carrier_a["id"], mark_activated=True,
    )
    assert block["routing_status"] == "UNROUTED"
    return carrier_a, carrier_b, block


def _attempt_port(block, from_carrier, to_carrier, telephone_number):
    """The gaining carrier files a port request and we keep the raw response."""
    return api_client.create_port_request(
        create_port_request_payload(
            telephone_number, block["id"], from_carrier["id"], to_carrier["id"],
            requested_lrn="6145560000", desired_due_at="2026-08-15T00:00:00Z",
        ),
        make_carrier_representative_headers(to_carrier["id"]),
    )


class TestNumberMembershipOutranksRoutingPosture:
    """Two grounds are live at once and the number test is reported first."""

    def test_a_number_outside_the_block_is_reported_before_the_routing_posture(self):
        """The block is unrouted as well, yet the refusal names the number.

        and its seventh digit must equal the block's `thousands_digit`, otherwise
        `ERR_NUMBER_OUTSIDE_BLOCK`

        When a single request would fail several checks, exactly one error is returned, and
        which one is fixed by the following precedence.

        Design: Difficulty/priority_pair_validation_conflict/number_outside_block_beats_port_block_not_routed
        """
        carrier_a, carrier_b, block = _assigned_block_that_was_never_routed()

        error = validate_error(
            _attempt_port(block, carrier_a, carrier_b, "6145591000"),
            ApiErrorId.ERR_NUMBER_OUTSIDE_BLOCK,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_PORT_BLOCK_NOT_ROUTED.value
        assert read_block(block["id"])["routing_status"] == "UNROUTED"

    def test_a_number_inside_an_unrouted_block_then_reports_the_routing_posture(self):
        """Moving the number inside the block exposes the second ground, and neither
        attempt leaves a port request behind.

        The block must also be in service — `allocation_status` `ASSIGNED`, `routing_status`
        `LERG_PUBLISHED`, and `holder_carrier_id` equal to `from_carrier_id` — and any
        failure of that triple is `ERR_PORT_BLOCK_NOT_ROUTED`

        Design: Difficulty/priority_pair_validation_conflict/number_outside_block_beats_port_block_not_routed
        """
        carrier_a, carrier_b, block = _assigned_block_that_was_never_routed()
        validate_error(
            _attempt_port(block, carrier_a, carrier_b, "6145591000"),
            ApiErrorId.ERR_NUMBER_OUTSIDE_BLOCK,
            422,
        )

        validate_error(
            _attempt_port(block, carrier_a, carrier_b, "6145583000"),
            ApiErrorId.ERR_PORT_BLOCK_NOT_ROUTED,
            409,
        )

        rows = get_success_data(
            api_client.list_port_requests(ADMIN_HEADERS, params={"number_block_id": block["id"]})
        )
        assert rows == []


def _concurred_port_behind_a_future_dated_rehome():
    """A concurred port whose block has been re-homed to a date that has not arrived."""
    from_carrier, to_carrier, _npa, rate_center, block, port_request = (
        setup_concurred_port_request(lrn="6145560000")
    )
    create_submitted_filing(
        from_carrier, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[1200, 800, 600, 400],
    )
    publish_routing_record(block, lrn="6145580000", effective_at=REHOME_INSTANT)
    return from_carrier, to_carrier, rate_center, read_block(block["id"]), port_request


class TestPortActivationWaitsForTheSweepPromotion:
    """Activation reads the block's routing posture, which only the sweep can restore."""

    def test_a_future_dated_rehome_blocks_the_activation(self):
        """The re-home clears the live routing number, so the concurred port has nothing
        to activate over until the effective date arrives.

        From `LERG_PUBLISHED`, a re-home is only possible on a future date: the block moves
        to `ROUTING_PENDING`, the outgoing record is superseded, and `current_lrn` is

        `ACTIVATE` requires `status` `CONCURRED` and the block's `routing_status` to read
        `LERG_PUBLISHED`.

        Design: Difficulty/cross_entity_state_dependency/port_activation_requires_block_routing_promoted_by_sweep
        """
        _from_carrier, _to_carrier, _rate_center, block, port_request = (
            _concurred_port_behind_a_future_dated_rehome()
        )
        assert block["routing_status"] == "ROUTING_PENDING"
        assert block["current_lrn"] is None
        assert block["npac_db_version"] == 2

        validate_error(
            api_client.create_port_transition(
                port_request["id"], {"action": "ACTIVATE"}, PORTING_HEADERS
            ),
            ApiErrorId.ERR_PORT_BLOCK_NOT_ROUTED,
            409,
        )
        assert read_port_request(port_request["id"])["status"] == "CONCURRED"

    def test_the_sweep_promotion_unblocks_the_activation(self):
        """Once the sweep promotes the pending routing the same activation succeeds, and
        the promotion itself writes nothing to the portability database.

        A block whose `routing_status` is `ROUTING_PENDING` and whose open published routing
        record has an `effective_at` at or before the sweep instant moves to `LERG_PUBLISHED`
        with `current_lrn` set from that record.

        It supersedes the block's open published record, publishes a new one whose `lrn` is
        the port's `requested_lrn` and whose `effective_at` is the logical clock

        Design: Difficulty/cross_entity_state_dependency/port_activation_requires_block_routing_promoted_by_sweep
        """
        _from_carrier, _to_carrier, rate_center, block, port_request = (
            _concurred_port_behind_a_future_dated_rehome()
        )

        set_clock(REHOME_INSTANT)
        sweep = run_sweep(rate_center_id=rate_center["id"])
        assert_sweep_report(sweep, 0, 0, 1, REHOME_INSTANT)

        promoted = read_block(block["id"])
        assert promoted["routing_status"] == "LERG_PUBLISHED"
        assert promoted["current_lrn"] == "6145580000"
        assert promoted["npac_db_version"] == 2

        port_transition(port_request, "ACTIVATE", PORTING_HEADERS)

        ported = read_port_request(port_request["id"])
        assert ported["status"] == "ACTIVATED"
        assert ported["activated_at"] == REHOME_INSTANT
        assert ported["npac_db_version_at_activation"] == 3

        locked = read_block(block["id"])
        assert locked["routing_status"] == "PORT_LOCKED"
        assert locked["current_lrn"] == "6145570000"
        assert locked["npac_db_version"] == 3
        assert locked["allocation_status"] == "ASSIGNED"

        open_record = assert_single_open_routing_record(read_routing_records(block["id"]))
        assert open_record["lrn"] == "6145570000"


FIRST_INTERVAL_START = "2026-08-15T00:00:00Z"


def _block_with_one_future_dated_open_record():
    """A block whose only open routing interval starts on 2026-08-15."""
    carrier, _npa, _rate_center, block, record = setup_routed_assigned_block(
        lrn="6145560000", effective_at=FIRST_INTERVAL_START
    )
    assert block["routing_status"] == "ROUTING_PENDING"
    assert block["npac_db_version"] == 1
    return carrier, block, record


class TestRoutingIntervalBoundaryIsInclusive:
    """An interval may start where the open one started, but never before it."""

    def test_an_earlier_start_overlaps_the_open_interval_and_is_refused(self):
        """A start five days before the open record's own start would overlap it.

        The new interval must not overlap the open published record: the new `effective_at`
        must be at or after that record's `effective_at`, and a record starting exactly at
        the previous record's `end_at` is adjacent rather than overlapping and is allowed.

        Design: Difficulty/resource_temporal_overlap/routing_record_equal_start_allowed_earlier_start_rejected
        """
        _carrier, block, record = _block_with_one_future_dated_open_record()
        version_before = read_block(block["id"])["version"]

        validate_error(
            api_client.create_routing_record(
                block["id"],
                {
                    "lrn": "6145570000",
                    "switch_clli": "CLMBOH01DS0",
                    "effective_at": "2026-08-10T00:00:00Z",
                    "expected_block_version": version_before,
                },
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_ROUTING_INTERVAL_OVERLAP,
            409,
        )

        after = read_block(block["id"])
        assert after["npac_db_version"] == 1
        assert after["version"] == version_before
        records = read_routing_records(block["id"])
        assert len(records) == 1
        still_open = assert_single_open_routing_record(records)
        assert still_open["id"] == record["id"]
        assert still_open["end_at"] is None

    def test_an_equal_start_is_adjacent_enough_to_be_accepted(self):
        """A record starting on the very same instant is allowed, and it closes the
        outgoing row at the incoming record's own start.

        The block's open published record has its `end_at` stamped with the incoming
        record's `effective_at` and its `record_status` set to `SUPERSEDED`

        The new record is created with `record_status` `PUBLISHED`, `end_at` null and `ocn`
        copied from the holding carrier.

        Design: Difficulty/resource_temporal_overlap/routing_record_equal_start_allowed_earlier_start_rejected
        """
        _carrier, block, record = _block_with_one_future_dated_open_record()
        version_before = read_block(block["id"])["version"]

        successor = publish_routing_record(
            block, lrn="6145580000", effective_at=FIRST_INTERVAL_START,
            expected_block_version=version_before,
        )

        assert successor["record_status"] == "PUBLISHED"
        assert successor["effective_at"] == FIRST_INTERVAL_START
        assert successor["end_at"] is None
        assert successor["npac_db_version"] == 2
        assert read_block(block["id"])["npac_db_version"] == 2

        records = read_routing_records(block["id"])
        assert len(records) == 2
        superseded = [row for row in records if row["id"] == record["id"]][0]
        assert superseded["record_status"] == "SUPERSEDED"
        assert superseded["end_at"] == FIRST_INTERVAL_START
        assert assert_single_open_routing_record(records)["id"] == successor["id"]


def _activated_port_ready_to_snap_back():
    """A port that reached ACTIVATED, so the block is PORT_LOCKED on the gaining LRN."""
    from_carrier, to_carrier, _npa, _rate_center, block, port_request = (
        setup_concurred_port_request(lrn="6145560000", desired_due_at="2026-08-15T00:00:00Z")
    )
    port_transition(port_request, "ACTIVATE", PORTING_HEADERS)
    locked = read_block(block["id"])
    assert locked["routing_status"] == "PORT_LOCKED"
    assert locked["current_lrn"] == "6145570000"
    assert locked["npac_db_version"] == 2
    return from_carrier, to_carrier, locked, port_request


class TestSnapbackConservesTheSingleOpenRecord:
    """The snapback restores the routing that was, without rewriting history."""

    def test_the_snapback_returns_the_block_to_its_pre_port_routing(self):
        """Cancelling an activated port hands the original routing number back and leaves
        the allocation axis exactly where it was.

        the request moves to `SNAPPED_BACK` with `closed_at` stamped, the port's published
        record is superseded, and a new published record is written carrying the `lrn` of the
        record that the activation had superseded

        `current_lrn` is restored to that original value, the block returns from
        `PORT_LOCKED` to `LERG_PUBLISHED`

        Design: Difficulty/compensating_invariant/single_published_routing_record_conserved_across_port_activate_then_snapback
        """
        from_carrier, _to_carrier, block, port_request = _activated_port_ready_to_snap_back()

        port_transition(port_request, "CANCEL", PORTING_HEADERS)

        snapped = read_port_request(port_request["id"])
        assert snapped["status"] == "SNAPPED_BACK"
        assert snapped["closed_at"] == DEFAULT_CLOCK
        assert snapped["npac_db_version_at_activation"] == 2

        restored = read_block(block["id"])
        assert restored["routing_status"] == "LERG_PUBLISHED"
        assert restored["allocation_status"] == "ASSIGNED"
        assert restored["current_lrn"] == "6145560000"
        assert read_carrier(from_carrier["id"])["blocks_held_count"] == 1

    def test_the_ledger_keeps_one_open_row_and_the_counter_is_never_rolled_back(self):
        """Three rows accumulate and only one of them is open, while the portability
        counter climbs to three rather than returning to one.

        so that exactly one published record remains open

        the counter records every write to the portability database and is never rolled back
        or decremented

        Design: Difficulty/compensating_invariant/single_published_routing_record_conserved_across_port_activate_then_snapback
        """
        _from_carrier, _to_carrier, block, port_request = _activated_port_ready_to_snap_back()
        original = read_routing_records(block["id"])[0]

        port_transition(port_request, "CANCEL", PORTING_HEADERS)

        records = read_routing_records(block["id"])
        assert len(records) == 3
        assert len([row for row in records if row["record_status"] == "PUBLISHED"]) == 1
        open_row = assert_single_open_routing_record(records)
        assert open_row["lrn"] == "6145560000"
        assert open_row["end_at"] is None

        # The original row is superseded history; the snapback wrote a fresh row instead.
        stale = [row for row in records if row["id"] == original["id"]][0]
        assert stale["record_status"] == "SUPERSEDED"
        assert stale["id"] != open_row["id"]
        assert read_block(block["id"])["npac_db_version"] == 3
