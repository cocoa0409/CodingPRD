"""Two shared resources booked over time: one hoist rig whose occupancy is
exclusive, and one laboratory whose chambers are counted per instant."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


class TestNestedAndEnclosingHoistWindows:
    """Containment conflicts in both directions, and cancellation is what frees
    the rig."""

    @staticmethod
    def _rig_holding_a_full_day():
        ctx = fx.new_project()
        fx.add_zone_a(ctx)
        fx.add_zone_b(ctx)
        fx.create_rig(ctx, changeover_buffer_minutes=45)
        first = fx.create_reservation(
            ctx,
            ctx["zone_ids"][0],
            "2026-08-10T06:00:00Z",
            "2026-08-10T18:00:00Z",
            planned_panel_count=36,
        )
        return ctx, first

    @staticmethod
    def _request(ctx, window_start, window_end):
        return api_client.create_hoist_reservation(
            f.create_hoist_reservation_payload(
                ctx["rig_id"],
                ctx["zone_ids"][1],
                window_start,
                window_end,
                planned_panel_count=20,
            ),
            SUPERINTENDENT,
        )

    def test_a_nested_window_and_an_enclosing_window_are_both_refused(self):
        """A request wholly inside the blocked interval and a request wholly
        containing it both intersect it, so overlap detection is symmetric in
        containment.

        PRD: "Occupancy is exclusive: the **requested raw window**, from `window_start` up to but not including `window_end`, must not intersect the stored interval from `blocked_from` up to but not including `blocked_until` of any reservation on the same rig whose `status` is `RESERVED` or `CONSUMED`."

        Design: Difficulty/resource_temporal_overlap/nested_and_enclosing_hoist_windows_conflict_until_cancellation_frees_the_rig
        """
        ctx, first = self._rig_holding_a_full_day()
        assert first["blocked_from"] == "2026-08-10T05:15:00.000Z"
        assert first["blocked_until"] == "2026-08-10T18:45:00.000Z"

        nested = self._request(ctx, "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
        validate_error(
            nested, ApiErrorId.ERR_HOIST_WINDOW_CONFLICT.value, expected_status=409
        )

        enclosing = self._request(ctx, "2026-08-10T04:00:00Z", "2026-08-10T20:00:00Z")
        validate_error(
            enclosing, ApiErrorId.ERR_HOIST_WINDOW_CONFLICT.value, expected_status=409
        )

        held = get_success_data(api_client.list_rig_reservations(ctx["rig_id"], PM))
        assert len(held) == 1
        assert held[0]["status"] == "RESERVED"

    def test_cancelling_the_incumbent_admits_the_previously_nested_request(self):
        """The cancelled reservation keeps its row and its stored interval but
        stops obstructing, so the byte-identical nested request is now accepted
        and a second cancellation of the same row is terminal.

        PRD: "Cancelling a reservation moves it `RESERVED` → `CANCELLED`, stores the free-text `cancelled_reason`, and stops its blocked interval from obstructing new bookings — a previously conflicting reservation becomes bookable immediately."

        Design: Difficulty/resource_temporal_overlap/nested_and_enclosing_hoist_windows_conflict_until_cancellation_frees_the_rig
        """
        ctx, first = self._rig_holding_a_full_day()
        self._request(ctx, "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")

        cancelled = validate_success(
            api_client.cancel_hoist_reservation(
                first["id"], f.cancel_reservation_payload("rig re-sequenced"), SUPERINTENDENT
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_reason"] == "rig re-sequenced"
        assert cancelled["blocked_from"] == "2026-08-10T05:15:00.000Z"
        assert cancelled["blocked_until"] == "2026-08-10T18:45:00.000Z"

        second = validate_success(
            self._request(ctx, "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z"),
            expected_status=201,
        )
        assert second["status"] == "RESERVED"
        assert second["blocked_from"] == "2026-08-10T08:15:00.000Z"
        assert second["blocked_until"] == "2026-08-10T11:45:00.000Z"

        rows = get_success_data(api_client.list_rig_reservations(ctx["rig_id"], PM))
        assert sorted(row["status"] for row in rows) == ["CANCELLED", "RESERVED"]

        again = api_client.cancel_hoist_reservation(
            first["id"], f.cancel_reservation_payload("duplicate cancellation"), SUPERINTENDENT
        )
        validate_error(again, ApiErrorId.ERR_TERMINAL_STATE.value, expected_status=409)


class TestLabChamberCapacityOverIntersectingWindows:
    """Chamber demand is summed only over scheduled, intersecting bookings."""

    @staticmethod
    def _lab_filled_to_capacity_over_the_afternoon():
        ctx = fx.setup_lab_with_capacity(chamber_capacity=2)
        first = fx.book_mockup(
            ctx,
            window_start="2026-08-05T06:00:00Z",
            window_end="2026-08-05T20:00:00Z",
            chambers_required=1,
        )
        second = fx.book_mockup(
            ctx,
            window_start="2026-08-05T12:00:00Z",
            window_end="2026-08-05T18:00:00Z",
            chambers_required=1,
        )
        return ctx, first, second

    @staticmethod
    def _book(ctx, window_start, window_end, chambers_required):
        return api_client.create_mockup_test(
            f.create_mockup_test_payload(
                ctx["package_id"],
                ctx["lab_id"],
                window_start=window_start,
                window_end=window_end,
                chambers_required=chambers_required,
            ),
            PM,
        )

    def test_only_scheduled_rows_hold_chambers_so_a_pass_frees_the_refused_window(self):
        """Two scheduled bookings commit both chambers across the afternoon, so a
        third is refused; recording a passing result on one of them releases its
        chamber and the identical request is then accepted.

        PRD: "Sum `chambers_required` over every mockup test of that laboratory whose state is `SCHEDULED` and whose own half-open window from `window_start` up to but not including `window_end` intersects the requested window; add the newly requested `chambers_required`; and if the total exceeds the laboratory's `chamber_capacity`, refuse the booking with `ERR_LAB_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/lab_chamber_capacity_over_intersecting_scheduled_windows_only
        """
        ctx, first, second = self._lab_filled_to_capacity_over_the_afternoon()
        assert first["state"] == "SCHEDULED"
        assert second["state"] == "SCHEDULED"

        refused = self._book(ctx, "2026-08-05T14:00:00Z", "2026-08-05T16:00:00Z", 1)
        validate_error(
            refused, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED.value, expected_status=409
        )

        passed = fx.record_mockup_result(ctx, first["id"])
        assert passed["state"] == "PASSED"

        accepted = validate_success(
            self._book(ctx, "2026-08-05T14:00:00Z", "2026-08-05T16:00:00Z", 1),
            expected_status=201,
        )
        assert accepted["state"] == "SCHEDULED"
        assert accepted["chamber_hours"] == 2
        assert accepted["invoice_subtotal_cents"] == 523000
        assert accepted["surcharge_cents"] == 0
        assert accepted["invoice_cents"] == 523000

        package = fx.refresh_package(ctx)
        assert package["mockup_qualified"] is True
        assert package["state"] == "MOCKUP_QUALIFIED"

    def test_a_window_starting_exactly_when_another_ends_does_not_intersect_it(self):
        """A two-chamber booking that begins at the instant the fourteen-hour
        booking closes is admitted in full and priced on its own twenty
        chamber-hours.

        PRD: "Two windows that merely touch at an endpoint do not intersect, so a test ending at noon and a test starting at noon can both be booked against a single-chamber laboratory."

        Design: Difficulty/resource_temporal_overlap/lab_chamber_capacity_over_intersecting_scheduled_windows_only
        """
        ctx, first, second = self._lab_filled_to_capacity_over_the_afternoon()
        assert first["chamber_hours"] == 14
        assert first["invoice_cents"] == 781000
        assert first["surcharge_cents"] == 0
        assert second["chamber_hours"] == 6
        assert second["invoice_cents"] == 609000
        assert second["surcharge_cents"] == 0

        touching = validate_success(
            self._book(ctx, "2026-08-05T20:00:00Z", "2026-08-06T06:00:00Z", 2),
            expected_status=201,
        )
        assert touching["state"] == "SCHEDULED"
        assert touching["chambers_required"] == 2
        assert touching["chamber_hours"] == 20
        assert touching["invoice_subtotal_cents"] == 910000
        assert touching["surcharge_cents"] == 0
        assert touching["invoice_cents"] == 910000
