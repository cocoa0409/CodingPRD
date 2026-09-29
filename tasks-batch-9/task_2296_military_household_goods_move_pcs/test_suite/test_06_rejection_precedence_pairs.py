"""Rejection precedence: the earlier rung of the ladder answers before the later one."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    award_payload,
    capacity_block_version,
    create_capacity_block,
    pack_shipment,
    pickup_payload,
    read_capacity_block,
    read_shipment,
    setup_surveyed_shipment,
    validate_error,
)

OUT_OF_WINDOW_PICKUP = "2026-09-05T00:00:00Z"


def _surveyed_shipment_with_capacity():
    """A surveyed 5,286 pound shipment and a published block able to take it."""
    scenario = setup_surveyed_shipment()
    scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
    return scenario


def _attempt_pickup(scenario):
    return api_client.pickup_shipment(
        scenario["shipment"]["id"],
        pickup_payload(OUT_OF_WINDOW_PICKUP),
        scenario["tsp_headers"],
    )


def _award(scenario, block):
    return api_client.create_award(
        block["id"],
        award_payload(scenario["shipment"]["id"], capacity_block_version(block["id"])),
        ADMIN,
    )


def _two_unusable_blocks():
    """A shipment out of MKT-BWI facing a foreign-market block and an undersized one."""
    scenario = setup_surveyed_shipment(tsp_markets=["MKT-BWI", "MKT-DEN"])
    scenario["wrong_market_block"] = create_capacity_block(
        scenario["tsp"]["id"],
        market_code="MKT-DEN",
        week_start_date="2026-08-17T00:00:00Z",
        total_capacity_lbs=3000,
    )
    scenario["small_block"] = create_capacity_block(
        scenario["tsp"]["id"],
        market_code="MKT-BWI",
        week_start_date="2026-08-24T00:00:00Z",
        total_capacity_lbs=3000,
    )
    return scenario


class TestPickupStateOutranksTheSpreadWindow:
    """A movement-state failure answers before the pickup date is even examined."""

    def test_pickup_before_packing_reports_the_movement_state(self):
        """A surveyed shipment cannot be picked up, whatever date is offered.

        "Checks are evaluated in the following sequence, and the first failing check
        produces the response; later checks never mask an earlier one:"

        Design: Difficulty/priority_pair_validation_conflict/pickup_state_error_outranks_spread_window_error
        """
        scenario = _surveyed_shipment_with_capacity()

        response = _attempt_pickup(scenario)
        validate_error(
            response, ApiErrorId.ERR_INVALID_SHIPMENT_MOVEMENT_STATE.value, 409
        )

    def test_the_same_date_reports_the_spread_window_once_the_state_is_right(self):
        """With the goods packed, 5 September is refused for being outside the window.

        "34. Pickup inside the spread — `ERR_PICKUP_OUTSIDE_SPREAD`, on pickup."

        Design: Difficulty/priority_pair_validation_conflict/pickup_state_error_outranks_spread_window_error
        """
        scenario = _surveyed_shipment_with_capacity()
        _award(scenario, scenario["block"])
        pack_shipment(scenario, pack_date="2026-08-15T00:00:00Z")

        response = _attempt_pickup(scenario)
        validate_error(response, ApiErrorId.ERR_PICKUP_OUTSIDE_SPREAD.value, 422)

    def test_neither_refusal_moved_the_shipment_out_of_packed(self):
        """The peak-season spread runs 15 to 24 August and no pickup date was stored.

        "`spread_start_date` is `requested_pickup_date` moved back by the before-days and
        `spread_end_date` is `requested_pickup_date` moved forward by the after-days, the
        latter being an inclusive endpoint."

        Design: Difficulty/priority_pair_validation_conflict/pickup_state_error_outranks_spread_window_error
        """
        scenario = _surveyed_shipment_with_capacity()
        _attempt_pickup(scenario)
        _award(scenario, scenario["block"])
        pack_shipment(scenario, pack_date="2026-08-15T00:00:00Z")
        _attempt_pickup(scenario)

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["movement_status"] == "PACKED"
        assert shipment["actual_pickup_date"] is None
        assert shipment["spread_start_date"] == "2026-08-15T00:00:00Z"
        assert shipment["spread_end_date"] == "2026-08-24T00:00:00Z"


class TestAwardMarketOutranksCapacity:
    """A referential market failure answers before the pool arithmetic is reached."""

    def test_a_block_in_a_foreign_market_reports_the_market(self):
        """The Denver block is refused on its market, not on its 3,000 pound size.

        "the shipment's `origin_market_code` must appear in the provider's `markets` and
        must equal the block's `market_code`, or `ERR_MARKET_NOT_SERVED` applies"

        Design: Difficulty/priority_pair_validation_conflict/award_market_referential_error_outranks_capacity_fiscal_error
        """
        scenario = _two_unusable_blocks()

        response = _award(scenario, scenario["wrong_market_block"])
        validate_error(response, ApiErrorId.ERR_MARKET_NOT_SERVED.value, 409)

    def test_a_block_in_the_right_market_reports_the_capacity(self):
        """5,286 pounds do not fit a 3,000 pound week even by raiding the reserve.

        "with `ERR_CAPACITY_EXCEEDED` when they would not have fitted even then"

        Design: Difficulty/priority_pair_validation_conflict/award_market_referential_error_outranks_capacity_fiscal_error
        """
        scenario = _two_unusable_blocks()

        response = _award(scenario, scenario["small_block"])
        validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED.value, 409)

    def test_neither_refusal_committed_a_single_pound(self):
        """Both blocks stay empty and the shipment holds no weekly slot.

        "On acceptance the pounds are added to `committed_general_lbs`."

        Design: Difficulty/priority_pair_validation_conflict/award_market_referential_error_outranks_capacity_fiscal_error
        """
        scenario = _two_unusable_blocks()
        _award(scenario, scenario["wrong_market_block"])
        _award(scenario, scenario["small_block"])

        assert read_capacity_block(scenario["wrong_market_block"]["id"])["committed_lbs"] == 0
        assert read_capacity_block(scenario["small_block"]["id"])["committed_lbs"] == 0
        assert read_shipment(scenario["shipment"]["id"])["capacity_block_id"] is None
