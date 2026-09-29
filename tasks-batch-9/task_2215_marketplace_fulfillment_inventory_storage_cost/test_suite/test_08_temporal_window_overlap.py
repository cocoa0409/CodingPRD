"""Two contended time windows with deliberately different interval semantics: half-open
appointment windows at a centre, and closed removal windows on a lot."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    confirm_plan,
    create_plan,
    lot_version,
    newest_quota,
    read_fulfillment_center,
    read_lot,
    read_plan,
    read_removal_order,
    read_seller,
    request_removal,
    setup_baseline,
    setup_received_lot,
    validate_error,
    validate_paginated,
)


class TestAppointmentWindowCapacityIsHalfOpen:
    """A 1200-unit centre, four overlapping windows and one aggregate that overflows."""

    def _four_drafts_at_a_twelve_hundred_unit_centre(self) -> dict:
        ctx = setup_baseline(center={"receiving_capacity_units_per_window": 1200})
        windows = [
            ("2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z", 600),
            ("2026-08-11T00:00:00Z", "2026-08-13T00:00:00Z", 600),
            ("2026-08-12T00:00:00Z", "2026-08-14T00:00:00Z", 400),
            ("2026-08-11T12:00:00Z", "2026-08-12T12:00:00Z", 300),
        ]
        plans = []
        for start, end, units in windows:
            plan = create_plan(ctx["seller_id"], ctx["fc_id"], start, end)
            add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], units)
            plans.append(plan)
        ctx["plans"] = plans
        return ctx

    def test_the_second_plan_confirms_at_exactly_the_capacity_ceiling(self):
        """The two overlapping windows sum to exactly 1200 units against a 1200-unit
        centre, and equality is accepted.

        PRD 3.4: "Sum `declared_units` over every plan at the same destination centre whose
        `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED` and whose half-open
        appointment window intersects this plan's half-open window, then add this plan's own
        `declared_units`."
        PRD 3.4: "Equality passes; only a strict excess is rejected, with
        `ERR_FC_RECEIVING_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/fc_appointment_window_capacity_uses_half_open_intervals
        """
        ctx = self._four_drafts_at_a_twelve_hundred_unit_centre()
        first = confirm_plan(ctx["plans"][0]["id"], ctx["seller_id"])
        second = confirm_plan(ctx["plans"][1]["id"], ctx["seller_id"])
        assert first["status"] == "CONFIRMED"
        assert second["status"] == "CONFIRMED"
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 1200

    def test_a_window_that_only_touches_another_does_not_intersect_it(self):
        """The third plan starts exactly when the first plan's window ends, so it contends
        only with the second plan and confirms at 1000 of the 1200 units.

        PRD 3.4: "Because the windows are half-open, a plan ending exactly when another
        begins does not intersect it."
        PRD 3.3: "Appointment windows are half-open — inclusive of their start, exclusive of
        their end — and are validated twice: the end must be strictly after the start, or
        the request fails with `ERR_APPOINTMENT_WINDOW_INVALID`, and the start must not be
        strictly before the logical clock's current instant, or it fails with
        `ERR_APPOINTMENT_WINDOW_IN_PAST`."

        Design: Difficulty/resource_temporal_overlap/fc_appointment_window_capacity_uses_half_open_intervals
        """
        ctx = self._four_drafts_at_a_twelve_hundred_unit_centre()
        confirm_plan(ctx["plans"][0]["id"], ctx["seller_id"])
        confirm_plan(ctx["plans"][1]["id"], ctx["seller_id"])
        third = confirm_plan(ctx["plans"][2]["id"], ctx["seller_id"])
        assert third["status"] == "CONFIRMED"
        assert third["declared_units"] == 400
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 1600

    def test_a_plan_straddling_all_three_windows_overflows_the_aggregate(self):
        """The fourth plan intersects all three confirmed windows, so the aggregate reaches
        1900 units and the confirmation is refused with nothing booked.

        PRD 3.4: "That total must not exceed the centre's effective capacity, which is
        `receiving_capacity_units_per_window` when the centre's `receiving_status` is `OPEN`
        and the floor of half that figure when it is `THROTTLED`."
        PRD 2.6: "Destination-centre receiving-window capacity at confirmation —
        `ERR_FC_RECEIVING_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/fc_appointment_window_capacity_uses_half_open_intervals
        """
        ctx = self._four_drafts_at_a_twelve_hundred_unit_centre()
        for plan in ctx["plans"][:3]:
            confirm_plan(plan["id"], ctx["seller_id"])

        response = api_client.confirm_plan(
            ctx["plans"][3]["id"], {}, ctx["seller_headers"]
        )
        validate_error(response, ApiErrorId.ERR_FC_RECEIVING_CAPACITY_EXCEEDED.value)

        fourth = read_plan(ctx["plans"][3]["id"], ctx["seller_id"])
        assert fourth["status"] == "DRAFT"
        assert fourth["provisional_allocated_units"] == 300
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 1600
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 1600
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 1600


class TestRemovalWindowsAreClosedIntervals:
    """Two removal windows sharing a single instant collide; one second apart they do not."""

    def _lot_with_one_requested_removal(self) -> dict:
        ctx = setup_received_lot(units=100)
        ctx["version_before"] = lot_version(ctx["lot_id"], ctx["seller_id"])
        ctx["removal"] = request_removal(
            ctx["lot_id"], ctx["seller_id"], 10,
            removal_method="DISPOSAL", unit_pool="FULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-03T00:00:00Z",
        )
        return ctx

    def test_a_window_touching_the_first_at_one_endpoint_is_rejected(self):
        """The second request starts exactly when the first ends, which counts as an
        intersection because removal windows include both endpoints.

        PRD 3.6: "Removal windows are **closed** intervals — inclusive at both ends — and
        they occupy the lot exclusively: if the requested window intersects the window of
        another removal order on the same lot whose `status` is `REQUESTED`, including the
        case where the two windows merely touch at an endpoint, the request is rejected with
        `ERR_REMOVAL_WINDOW_CONFLICT`."
        PRD 3.6: "The lot's `version` increments by 1, and listing health and the seller's
        storage utilization are both recomputed — reserved units still count as stored, so
        utilization does not fall."

        Design: Difficulty/resource_temporal_overlap/removal_window_closed_interval_touching_endpoint_conflicts
        """
        ctx = self._lot_with_one_requested_removal()
        assert ctx["removal"]["status"] == "REQUESTED"
        current_version = lot_version(ctx["lot_id"], ctx["seller_id"])
        assert current_version == ctx["version_before"] + 1

        response = api_client.create_removal_order(
            {
                "inventory_lot_id": ctx["lot_id"],
                "removal_method": "DISPOSAL",
                "unit_pool": "FULFILLABLE",
                "requested_units": 10,
                "removal_window_start": "2026-09-03T00:00:00Z",
                "removal_window_end": "2026-09-05T00:00:00Z",
                "expected_inventory_lot_version": current_version,
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_REMOVAL_WINDOW_CONFLICT.value)

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_reserved_for_removal"] == 10
        assert lot["fulfillable_units"] == 90

    def test_starting_one_second_later_clears_the_conflict(self):
        """A start one second past the first window's end no longer intersects, so the
        second reservation lands and the lot holds 20 reserved units.

        PRD 3.6: "It reserves the units: `requested_units` is subtracted from whichever pool
        the `unit_pool` names and added to the lot's `units_reserved_for_removal`, leaving
        `units_received_total` unchanged."
        PRD 3.6: "A successful request opens at `status` of `REQUESTED` with
        `removal_fee_cents`, `liquidation_recovery_cents` and `net_settlement_cents` all at 0
        and `completed_at` null."

        Design: Difficulty/resource_temporal_overlap/removal_window_closed_interval_touching_endpoint_conflicts
        """
        ctx = self._lot_with_one_requested_removal()
        second = request_removal(
            ctx["lot_id"], ctx["seller_id"], 10,
            removal_method="DISPOSAL", unit_pool="FULFILLABLE",
            removal_window_start="2026-09-03T00:00:01Z",
            removal_window_end="2026-09-05T00:00:00Z",
        )
        assert second["status"] == "REQUESTED"
        assert second["removal_window_start"].startswith("2026-09-03T00:00:01")
        assert second["removal_fee_cents"] == 0
        assert second["net_settlement_cents"] == 0
        assert second["completed_at"] is None

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_reserved_for_removal"] == 20
        assert lot["fulfillable_units"] == 80
        assert lot["units_received_total"] == 100

        _rows, meta = validate_paginated(
            api_client.list_lot_removal_orders(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 2
        assert read_removal_order(ctx["removal"]["id"], ctx["seller_id"])["status"] == (
            "REQUESTED"
        )
