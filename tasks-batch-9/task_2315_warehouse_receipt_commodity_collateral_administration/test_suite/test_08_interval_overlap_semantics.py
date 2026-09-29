"""
Two different interval conventions in one system: buffered closed fill windows
on a bin, and half-open loadout appointments across a lane pool.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal


class TestBinFillWindowBuffer:
    @pytest.fixture
    def bin_with_weighed_window(
        self, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        """One WEIGHED load occupying 09:00-11:00 on bin B1."""
        from test_helpers.test_users import make_warehouse_operator_headers

        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        weighed_ticket(warehouse["id"], agreement["id"], storage_bin["id"])
        return {
            "agreement_id": agreement["id"],
            "bin_id": storage_bin["id"],
            "headers": make_warehouse_operator_headers(warehouse["id"]),
        }

    @staticmethod
    def _weigh_at(api, scenario, start_at):
        return api.create_deposit_ticket(
            f.deposit_ticket_payload(
                scenario["agreement_id"],
                scenario["bin_id"],
                gross_bushels=800,
                moisture_pct=13.0,
                dockage_pct=0.0,
                fill_start_at=start_at,
                fill_end_at="2026-08-05T16:00:00Z",
            ),
            scenario["headers"],
        )

    def test_a_window_starting_exactly_on_the_buffered_end_still_conflicts(
        self, api, bin_with_weighed_window
    ):
        """
        The standing window ends at 11:00 and the settling buffer carries it to
        15:00; a new load starting at exactly 15:00:00Z is "at or before" that
        inflated end, so it is refused.

        PRD: "A proposed window conflicts with an existing ticket's window on the
        same bin, over tickets in `ticket_state` `WEIGHED` or `ACCEPTED`, when the
        new start is at or before the existing end advanced by 240 minutes **and**
        the existing start is at or before the new end advanced by 240 minutes."

        Design: Difficulty/resource_temporal_overlap/bin_fill_window_buffered_closed_interval_conflict
        """
        response = self._weigh_at(api, bin_with_weighed_window, "2026-08-05T15:00:00Z")

        validate_error(response, E.ERR_BIN_WINDOW_CONFLICT, 409)

    def test_one_second_past_the_buffered_end_is_admitted(
        self, api, bin_with_weighed_window
    ):
        """
        A start of 15:00:01Z clears the buffered interval, so the load is weighed
        in: 800 gross bushels at zero dockage and 13.0 percent moisture (under the
        14.0 ceiling, so no shrink) net 800, and the bin now carries both
        reservations, 949 + 800 = 1749.

        PRD: "Fill windows are treated as **closed** intervals inflated by a
        four-hour settling buffer, because grain needs time to stop moving before
        the next load goes on top of it."

        Design: Difficulty/resource_temporal_overlap/bin_fill_window_buffered_closed_interval_conflict
        """
        self._weigh_at(api, bin_with_weighed_window, "2026-08-05T15:00:00Z")

        ticket = get_success_data(
            self._weigh_at(api, bin_with_weighed_window, "2026-08-05T15:00:01Z"), 201
        )
        assert_fields_equal(ticket, {"ticket_state": "WEIGHED", "net_bushels": 800})

        storage_bin = get_success_data(
            api.get_bin(
                bin_with_weighed_window["bin_id"], bin_with_weighed_window["headers"]
            ),
            200,
        )
        assert storage_bin["scheduled_inbound_bushels"] == 1749

        tickets, _meta = validate_paginated(
            api.list_deposit_tickets(
                {"bin_id": bin_with_weighed_window["bin_id"]},
                bin_with_weighed_window["headers"],
            )
        )
        assert len(tickets) == 2


class TestLoadoutLaneAggregateCapacity:
    @staticmethod
    def _book(api, scenario, bushels, start_at, end_at):
        return api.create_delivery_order(
            f.delivery_order_payload(scenario["receipt_id"], bushels, start_at, end_at),
            scenario["depositor_headers"],
        )

    def test_a_third_mutually_overlapping_appointment_exhausts_both_lanes(
        self, api, base_full
    ):
        """
        10:00-12:00 takes lane 0 and 11:00-13:00 takes lane 1; a third
        appointment at 11:30-12:30 overlaps both, and with only two lanes there
        is no lane left to assign.

        PRD: "`lane_index` is assigned as the lowest integer from zero up to but
        excluding the warehouse's `loadout_lane_count` that no overlapping order
        already occupies; when every lane is taken, the booking is refused with
        `ERR_LOADOUT_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/loadout_lane_half_open_aggregate_capacity_conflict
        """
        first = get_success_data(
            self._book(
                api, base_full, 300, "2026-09-14T10:00:00Z", "2026-09-14T12:00:00Z"
            ),
            201,
        )
        second = get_success_data(
            self._book(
                api, base_full, 300, "2026-09-14T11:00:00Z", "2026-09-14T13:00:00Z"
            ),
            201,
        )
        assert first["lane_index"] == 0
        assert second["lane_index"] == 1

        response = self._book(
            api, base_full, 100, "2026-09-14T11:30:00Z", "2026-09-14T12:30:00Z"
        )
        validate_error(response, E.ERR_LOADOUT_CAPACITY_EXCEEDED, 409)

    def test_an_appointment_starting_at_another_end_reuses_the_freed_lane(
        self, api, base_full
    ):
        """
        Appointments are half-open, so 12:00-13:00 does not overlap 10:00-12:00
        and inherits its lane 0. Only the three admitted orders hold grain —
        300 + 300 + 100 = 700 bushels — and the refused one placed no hold.

        PRD: "Appointments are **half-open** intervals: a new appointment
        overlaps an existing one when the new start is strictly before the
        existing end and the existing start is strictly before the new end,
        considered over orders in `delivery_state` `REQUESTED` or `LOADED`."

        Design: Difficulty/resource_temporal_overlap/loadout_lane_half_open_aggregate_capacity_conflict
        """
        get_success_data(
            self._book(
                api, base_full, 300, "2026-09-14T10:00:00Z", "2026-09-14T12:00:00Z"
            ),
            201,
        )
        get_success_data(
            self._book(
                api, base_full, 300, "2026-09-14T11:00:00Z", "2026-09-14T13:00:00Z"
            ),
            201,
        )
        self._book(api, base_full, 100, "2026-09-14T11:30:00Z", "2026-09-14T12:30:00Z")

        fourth = get_success_data(
            self._book(
                api, base_full, 100, "2026-09-14T12:00:00Z", "2026-09-14T13:00:00Z"
            ),
            201,
        )
        assert fourth["lane_index"] == 0

        storage_bin = get_success_data(
            api.get_bin(base_full["bin_id"], base_full["operator_headers"]), 200
        )
        assert storage_bin["held_bushels"] == 700

        orders, _meta = validate_paginated(
            api.list_delivery_orders(
                {"receipt_id": base_full["receipt_id"]}, base_full["operator_headers"]
            )
        )
        assert len(orders) == 3
