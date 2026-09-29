"""Contention over a shared assembly station and over a utility's rebate calendar.

A station's occupation window is a closed interval extended by its changeover
buffer, while two rebate windows of the same utility and program class must be
separated by at least one full clear day.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    PLANT_MANAGER,
    make_technician_headers,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp so two instants compare exactly."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _two_units_on_one_drum_station(api):
    """A single drum cell of capacity 1 with a 30 minute changeover buffer, two
    certified drum technicians and two units waiting on the floor."""
    env = fx.make_certified_model(api)
    station = fx.make_station(
        api,
        station_code="DRUM-01",
        station_type="DRUM_FAB",
        parallel_capacity=1,
        changeover_buffer_minutes=30,
    )
    first_technician = fx.make_certified_technician(
        api,
        ["DRUM_FAB"],
        employee_code="T-100",
        full_name="Ann Ito",
        employer="FACTORY",
    )
    second_technician = fx.make_certified_technician(
        api,
        ["DRUM_FAB"],
        employee_code="T-101",
        full_name="Bo Reyes",
        employer="FACTORY",
    )
    first_build = fx.make_build_order(
        api, env["model"]["id"], serial_number="SN-0001"
    )
    fx.release_build(api, first_build["id"])
    second_build = fx.make_build_order(
        api,
        env["model"]["id"],
        serial_number="SN-0002",
        planned_start_at="2026-08-01T09:00:00Z",
    )
    fx.release_build(api, second_build["id"])
    return {
        "station": station,
        "first_technician": first_technician,
        "second_technician": second_technician,
        "first_build": first_build,
        "second_build": second_build,
    }


class TestStationOccupationWindowIncludesTheChangeoverBuffer:
    """A one-hour drum operation finishing at 09:00 owns the cell until 09:30."""

    def test_01_a_start_inside_the_buffered_window_is_refused(self, api):
        """A second unit starting at 09:15, while the changeover buffer of the
        first operation still runs, exhausts the cell's single parallel slot.

        PRD: "The number of existing station-log occupation windows at the same station that overlap the new occupation window — closed intervals, changeover buffer included — is strictly fewer than the station's `parallel_capacity`."
        Design: Difficulty/resource_temporal_overlap/station_capacity_conflict_with_changeover_buffer
        """
        floor = _two_units_on_one_drum_station(api)

        first_log = fx.log_station_pass(
            api,
            floor["first_build"]["id"],
            floor["station"],
            floor["first_technician"]["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T09:00:00Z",
        )
        assert _instant(first_log["occupation_from"]) == _instant(
            "2026-08-01T08:00:00Z"
        )
        assert _instant(first_log["occupation_to"]) == _instant("2026-08-01T09:30:00Z")
        assert first_log["labor_minutes"] == 60

        payload = f.station_log_payload(
            floor["station"]["id"],
            "DRUM_FAB",
            "2026-08-01T09:15:00Z",
            "2026-08-01T10:00:00Z",
            "PASS",
        )
        response = api.create_station_log(
            floor["second_build"]["id"],
            payload,
            make_technician_headers(floor["second_technician"]["id"]),
        )
        validate_error(response, E.ERR_STATION_CAPACITY_CONFLICT, expected_status=409)

    def test_02_a_start_one_minute_past_the_buffered_window_is_accepted(self, api):
        """A second unit starting at 09:31, a minute clear of the buffered window,
        takes the cell and books 44 whole minutes of labour.

        PRD: "Because both ends are closed, a new operation beginning at exactly the instant an existing occupation window ends still conflicts — with a thirty-minute changeover buffer on a one-hour operation ending at nine o'clock, the window runs to half past nine and a new operation at half past nine is refused, while one starting a minute later is accepted."
        Design: Difficulty/resource_temporal_overlap/station_capacity_conflict_with_changeover_buffer
        """
        floor = _two_units_on_one_drum_station(api)

        fx.log_station_pass(
            api,
            floor["first_build"]["id"],
            floor["station"],
            floor["first_technician"]["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T09:00:00Z",
        )

        payload = f.station_log_payload(
            floor["station"]["id"],
            "DRUM_FAB",
            "2026-08-01T09:31:00Z",
            "2026-08-01T10:15:00Z",
            "PASS",
        )
        second_log = validate_success(
            api.create_station_log(
                floor["second_build"]["id"],
                payload,
                make_technician_headers(floor["second_technician"]["id"]),
            ),
            expected_status=201,
        )
        assert _instant(second_log["occupation_from"]) == _instant(
            "2026-08-01T09:31:00Z"
        )
        assert _instant(second_log["occupation_to"]) == _instant("2026-08-01T10:45:00Z")
        assert second_log["labor_minutes"] == 44

        after = validate_success(
            api.get_build_order(floor["second_build"]["id"], PLANT_MANAGER),
            expected_status=200,
        )
        a.assert_build_state(after, "DRUM_DONE")
        assert after["labor_minutes_total"] == 44

        rows, _ = validate_paginated(
            api.list_station_logs(PLANT_MANAGER, station_id=floor["station"]["id"])
        )
        assert len(rows) == 2


class TestRebateWindowsNeedOneFullClearDay:
    """Back-to-back windows on one utility and program class are illegal."""

    def test_01_a_window_opening_the_next_day_conflicts(self, api):
        """A combined-class program for UTIL-A starting 2027-01-01, the day right
        after an existing window closes on 2026-12-31, leaves no clear day.

        PRD: "The practical effect is that back-to-back windows are illegal: a program ending on the last day of June and another beginning on the first day of July collide, because there is no clear day between them, and the second must begin on the second of July or later."
        Design: Difficulty/resource_temporal_overlap/rebate_program_window_requires_one_day_gap
        """
        fx.make_rebate_program(api)

        payload = f.rebate_program_payload(
            program_code="UTIL-A-W2",
            eligible_product_lines=["ON_PREMISES"],
            max_water_gal_per_cwt=1.00,
            max_kwh_per_cwt=0.40,
            rebate_base_cents=50000,
            capacity_bonus_cents_per_10lb=4000,
            rebate_cap_cents=80000,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2027-06-30T00:00:00Z",
        )
        response = api.create_rebate_program(payload, COMPLIANCE_OFFICER)
        validate_error(response, E.ERR_PROGRAM_WINDOW_CONFLICT, expected_status=409)

    def test_02_a_window_opening_two_days_later_is_accepted(self, api):
        """Moving the same program's start to 2027-01-02 leaves 2027-01-01 clear,
        so the utility's calendar accepts the second window.

        PRD: "For a given pairing of `utility_code` and `program_class`, a new window must be separated from the window of every existing program that is not yet retired by **at least one full clear day**."
        Design: Difficulty/resource_temporal_overlap/rebate_program_window_requires_one_day_gap
        """
        first = fx.make_rebate_program(api)

        payload = f.rebate_program_payload(
            program_code="UTIL-A-W3",
            eligible_product_lines=["ON_PREMISES"],
            max_water_gal_per_cwt=1.00,
            max_kwh_per_cwt=0.40,
            rebate_base_cents=50000,
            capacity_bonus_cents_per_10lb=4000,
            rebate_cap_cents=80000,
            effective_from="2027-01-02T00:00:00Z",
            effective_to="2027-06-30T00:00:00Z",
        )
        created = validate_success(
            api.create_rebate_program(payload, COMPLIANCE_OFFICER), expected_status=201
        )
        assert _instant(created["effective_from"]) == _instant("2027-01-02T00:00:00Z")
        assert created["program_state"] == "ACTIVE"

        first_after = validate_success(
            api.get_rebate_program(first["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert first_after["program_state"] == "ACTIVE"

        rows, _ = validate_paginated(
            api.list_rebate_programs(COMPLIANCE_OFFICER, utility_code="UTIL-A")
        )
        assert len(rows) == 2
