"""Storage periods that must keep a day apart, and capacity weeks that may touch."""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_capacity_block,
    create_capacity_block_payload,
    create_sit_payload,
    create_tsp,
    get_success_data,
    read_capacity_block,
    read_shipment,
    set_clock,
    setup_sit_authorized_shipment,
    validate_error,
    validate_success,
)

WEEK_ONE = "2026-10-05T00:00:00Z"
WEEK_TWO = "2026-10-12T00:00:00Z"


def _shipment_in_storage():
    """A picked-up shipment holding one authorized origin period, 16 to 26 September."""
    return setup_sit_authorized_shipment(
        entry_date="2026-09-16T00:00:00Z",
        requested_days=10,
        sit_type="ORIGIN",
        weigh_date="2026-08-17T00:00:00Z",
        actual_pickup_date="2026-08-17T00:00:00Z",
    )


def _request_storage(scenario, entry_date):
    """Ask for a further five-day destination period starting on the given day."""
    return api_client.create_sit_authorization(
        scenario["shipment"]["id"],
        create_sit_payload(entry_date, requested_days=5, sit_type="DESTINATION"),
        scenario["tsp_headers"],
    )


def _list_storage(scenario):
    return get_success_data(
        api_client.list_shipment_sit_authorizations(
            scenario["shipment"]["id"], scenario["tsp_headers"]
        )
    )


def _provider_with_one_published_week():
    """A provider serving two markets, with the first October week published for MKT-BWI."""
    set_clock()
    tsp = create_tsp(markets=["MKT-BWI", "MKT-DEN"])
    block = create_capacity_block(
        tsp["id"],
        market_code="MKT-BWI",
        week_start_date=WEEK_ONE,
        total_capacity_lbs=9000,
        short_notice_reserve_pct=0.15,
    )
    return tsp, block


def _publish_week(tsp_id, market_code, week_start_date, total_capacity_lbs):
    return api_client.create_capacity_block(
        create_capacity_block_payload(
            tsp_id,
            market_code=market_code,
            week_start_date=week_start_date,
            total_capacity_lbs=total_capacity_lbs,
            short_notice_reserve_pct=0.15,
        ),
        ADMIN,
    )


class TestStoragePeriodsNeedAOneDayGap:
    """The stored range is inclusive at both ends and a touching range is still a clash."""

    def test_the_authorized_period_puts_the_shipment_into_storage(self):
        """Ten authorized days from 16 September move the goods into the warehouse.

        "Authorizing storage is a counselor or program-office action that moves the
        authorization `REQUESTED → AUTHORIZED` and, in the same breath, the shipment
        `PICKED_UP → IN_SIT`."

        Design: Difficulty/resource_temporal_overlap/sit_periods_are_inclusive_and_need_a_one_day_gap
        """
        scenario = _shipment_in_storage()

        assert scenario["sit"]["entry_date"] == "2026-09-16T00:00:00Z"
        assert scenario["sit"]["requested_days"] == 10
        assert scenario["sit"]["total_authorized_days"] == 10
        assert scenario["sit"]["status"] == "AUTHORIZED"
        assert scenario["shipment"]["movement_status"] == "IN_SIT"

    def test_a_period_starting_on_the_inclusive_end_day_overlaps(self):
        """26 September is the last day of the first period, so it is already taken.

        "treating a requested period as the inclusive day range from `entry_date` through
        `entry_date` plus `requested_days`, that range may neither overlap nor so much as
        touch the range of any existing storage authorization of the same shipment that has
        not been released"

        Design: Difficulty/resource_temporal_overlap/sit_periods_are_inclusive_and_need_a_one_day_gap
        """
        scenario = _shipment_in_storage()

        validate_error(
            _request_storage(scenario, "2026-09-26T00:00:00Z"),
            ApiErrorId.ERR_SIT_PERIOD_OVERLAP.value,
            409,
        )

    def test_a_period_that_merely_touches_is_refused_as_well(self):
        """Starting the day after the first period ends leaves no gap at all.

        "a mandatory one-day gap is required between consecutive periods, and a violation
        is refused with `ERR_SIT_PERIOD_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/sit_periods_are_inclusive_and_need_a_one_day_gap
        """
        scenario = _shipment_in_storage()

        validate_error(
            _request_storage(scenario, "2026-09-27T00:00:00Z"),
            ApiErrorId.ERR_SIT_PERIOD_OVERLAP.value,
            409,
        )

    def test_one_clear_day_between_the_periods_is_enough(self):
        """28 September clears the gap and the second period is merely requested.

        "A new request is `REQUESTED` with `authorized_days` 0, `extension_days` 0,
        `total_authorized_days` 0, `release_date` null, and every cost figure at 0.00."

        Design: Difficulty/resource_temporal_overlap/sit_periods_are_inclusive_and_need_a_one_day_gap
        """
        scenario = _shipment_in_storage()
        _request_storage(scenario, "2026-09-26T00:00:00Z")
        _request_storage(scenario, "2026-09-27T00:00:00Z")

        second = validate_success(_request_storage(scenario, "2026-09-28T00:00:00Z"), 201)
        assert second["entry_date"] == "2026-09-28T00:00:00Z"
        assert second["status"] == "REQUESTED"
        assert second["total_authorized_days"] == 0

        assert len(_list_storage(scenario)) == 2
        assert read_shipment(scenario["shipment"]["id"])["movement_status"] == "IN_SIT"


class TestCapacityWeeksAreHalfOpen:
    """Adjacent weeks are legal, an identical week is not, and markets are independent."""

    def test_the_published_week_ends_seven_days_out_and_splits_its_pools(self):
        """A 9,000 pound non-peak week offers 7,650 pounds and reserves 1,350.

        "The server derives `week_end_date` as `week_start_date` advanced by seven days;
        the week is the half-open interval that includes its start instant and excludes its
        end instant."

        Design: Difficulty/resource_temporal_overlap/capacity_weeks_are_half_open_so_adjacent_weeks_are_legal
        """
        _, block = _provider_with_one_published_week()

        assert block["week_end_date"] == WEEK_TWO
        assert block["peak_season"] is False
        assert block["general_pool_lbs"] == 7650
        assert block["short_notice_pool_lbs"] == 1350
        assert block["effective_reserve_pct"] == pytest.approx(0.15, abs=0.0001)

    def test_a_week_starting_on_the_previous_weeks_end_instant_is_legal(self):
        """The following Monday is a fresh week, not an overlap.

        "because the interval is half-open, a block starting exactly on another's
        `week_end_date` is perfectly legal, while any genuine overlap is refused with
        `ERR_CAPACITY_BLOCK_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/capacity_weeks_are_half_open_so_adjacent_weeks_are_legal
        """
        tsp, _ = _provider_with_one_published_week()

        adjacent = validate_success(
            _publish_week(tsp["id"], "MKT-BWI", WEEK_TWO, 9000), 201
        )
        assert adjacent["week_start_date"] == WEEK_TWO
        assert adjacent["week_end_date"] == "2026-10-19T00:00:00Z"

    def test_republishing_the_same_week_is_refused_and_changes_nothing(self):
        """The duplicate week is turned away and the standing block keeps its 9,000 pounds.

        "Two blocks for the same `tsp_id` and `market_code` may not cover overlapping
        weeks"

        Design: Difficulty/resource_temporal_overlap/capacity_weeks_are_half_open_so_adjacent_weeks_are_legal
        """
        tsp, block = _provider_with_one_published_week()

        validate_error(
            _publish_week(tsp["id"], "MKT-BWI", WEEK_ONE, 4000),
            ApiErrorId.ERR_CAPACITY_BLOCK_OVERLAP.value,
            409,
        )
        assert read_capacity_block(block["id"])["total_capacity_lbs"] == 9000

    def test_the_same_week_in_another_served_market_is_accepted(self):
        """Denver and Baltimore are separate weeks of work for the same provider.

        "The block's `market_code` must also be one the owning provider serves; otherwise
        `ERR_MARKET_NOT_SERVED` applies."

        Design: Difficulty/resource_temporal_overlap/capacity_weeks_are_half_open_so_adjacent_weeks_are_legal
        """
        tsp, _ = _provider_with_one_published_week()
        _publish_week(tsp["id"], "MKT-BWI", WEEK_TWO, 9000)
        _publish_week(tsp["id"], "MKT-BWI", WEEK_ONE, 4000)

        denver = validate_success(
            _publish_week(tsp["id"], "MKT-DEN", WEEK_ONE, 4000), 201
        )
        assert denver["market_code"] == "MKT-DEN"

        blocks = get_success_data(api_client.list_tsp_capacity_blocks(tsp["id"], ADMIN))
        assert len(blocks) == 3
