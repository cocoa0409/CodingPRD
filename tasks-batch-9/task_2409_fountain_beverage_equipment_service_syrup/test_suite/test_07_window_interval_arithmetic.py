"""Two different interval conventions on two different resources.

Route delivery windows are half-open with no buffer, so touching windows coexist
while genuinely overlapping ones are refused. Van service windows are closed and
padded by 30 minutes, so a gap of exactly 30 minutes still clashes and 31 minutes
does not.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    activate_agreement,
    add_stop,
    ApiErrorId,
    create_agreement,
    create_call,
    create_outlet,
    create_route,
    create_route_stop_payload,
    create_unit,
    dispatch_call,
    dispatch_call_payload,
    pin_clock,
    read_call,
    read_route,
    read_stop,
    route_version,
    TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]


def _route_with_an_early_morning_stop():
    """Route RT-TO-1 out of depot R15 with one 08:00-10:00 stop and a spare outlet."""
    pin_clock("2026-08-01T00:00:00Z")
    first_outlet = create_outlet(
        name="Quick Lube Lounge",
        account_code="ACCT-TO-A",
        region_code="R15",
        throughput_tier="SMALL",
        water_hardness_gpg=10,
    )
    second_outlet = create_outlet(
        name="Feed Store Counter",
        account_code="ACCT-TO-B",
        region_code="R15",
        throughput_tier="SMALL",
        water_hardness_gpg=10,
    )
    route = create_route(
        route_code="RT-TO-1",
        depot_region_code="R15",
        service_date="2026-08-05T00:00:00Z",
        van_code="V-71",
        capacity_units=300,
    )
    first_stop = add_stop(
        route["id"], first_outlet["id"], 1,
        "2026-08-05T08:00:00Z", "2026-08-05T10:00:00Z",
    )
    return first_outlet, second_outlet, route, first_stop


def _van_with_a_morning_call():
    """Van V-99 already attending an ICE_FAULT call between 09:00 and 11:00."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Marina Snack Deck",
        account_code="ACCT-TO-C",
        region_code="R16",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"], agreement["id"], serial_number="SN-TO-C-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    morning = create_call(unit["id"], "ICE_FAULT", "2026-08-01T00:00:00Z")
    afternoon = create_call(unit["id"], "OFF_RATIO", "2026-08-01T00:00:00Z")
    morning = dispatch_call(
        morning["id"], "V-99", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", TECH
    )
    return morning, afternoon


class TestRouteStopWindowOverlap:
    def test_a_window_that_starts_where_the_previous_one_ends_is_accepted(self, api):
        """PRD §2.9: "Because both comparisons are strict, two windows that merely
        touch — one ending at exactly the instant the next begins — never conflict."

        Design: Difficulty/resource_temporal_overlap/route_stop_windows_half_open_touching_allowed_then_overlap_refused
        """
        _first_outlet, second_outlet, route, first_stop = _route_with_an_early_morning_stop()
        assert route_version(route["id"]) == 2
        assert read_stop(first_stop["id"])["status"] == "PENDING"

        touching = validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    second_outlet["id"], route_version(route["id"]), 2,
                    "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )
        assert touching["status"] == "PENDING"
        assert touching["sequence_index"] == 2
        assert touching["delivered_units"] == 0
        assert touching["version"] == 1
        assert route_version(route["id"]) == 3

    def test_a_window_that_straddles_an_existing_stop_is_refused(self, api):
        """PRD §3.7: "And the new window must not overlap another `PENDING` or
        `ARRIVED` stop of the same route under the half-open, zero-buffer arithmetic
        of §2.9, an overlap being `ERR_STOP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/route_stop_windows_half_open_touching_allowed_then_overlap_refused
        """
        first_outlet, second_outlet, route, first_stop = _route_with_an_early_morning_stop()
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    second_outlet["id"], route_version(route["id"]), 2,
                    "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )

        response = api.create_route_stop(
            route["id"],
            create_route_stop_payload(
                first_outlet["id"], route_version(route["id"]), 3,
                "2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z",
            ),
            PLANNER,
        )
        validate_error(response, ApiErrorId.ERR_STOP_WINDOW_OVERLAP.value, 409)

        rows, _meta = validate_paginated(
            api.list_route_stops(PLANNER, {"route_id": route["id"]})
        )
        assert len(rows) == 2
        assert all(row["status"] == "PENDING" for row in rows)

        after = read_route(route["id"])
        assert after["version"] == 3
        assert after["committed_units"] == 0
        assert after["status"] == "PLANNED"


class TestVanServiceWindowBuffer:
    def test_a_gap_of_exactly_thirty_minutes_still_clashes(self, api):
        """PRD §2.9: "The practical consequence is worth spelling out: a window that
        starts exactly 30 minutes after another one ends **does** conflict, while a
        window starting 31 minutes after does not."

        Design: Difficulty/resource_temporal_overlap/van_service_windows_closed_interval_thirty_minute_buffer
        """
        morning, afternoon = _van_with_a_morning_call()
        assert morning["status"] == "DISPATCHED"
        assert morning["severity_score"] == 25
        assert morning["severity"] == "ROUTINE"

        response = api.dispatch_service_call(
            afternoon["id"],
            dispatch_call_payload(
                "V-99", "2026-08-01T11:30:00Z", "2026-08-01T12:30:00Z"
            ),
            TECH_ALT,
        )
        validate_error(response, ApiErrorId.ERR_VAN_WINDOW_CONFLICT.value, 409)

        refused = read_call(afternoon["id"])
        assert refused["status"] == "OPEN"
        assert refused["van_code"] is None
        assert refused["scheduled_window_start"] is None
        assert refused["scheduled_window_end"] is None
        assert refused["assigned_tech_user_id"] is None
        assert refused["version"] == 1

    def test_one_minute_past_the_buffer_shares_the_van_cleanly(self, api):
        """PRD §2.9: "The dispatch then conflicts with any other service call —
        excluding the call being dispatched itself — that names the same `van_code`,
        sits in `DISPATCHED` or `ON_SITE` status, and whose own
        `scheduled_window_start` is at or before the padded upper bound while the
        padded lower bound is at or before that call's `scheduled_window_end`."

        Design: Difficulty/resource_temporal_overlap/van_service_windows_closed_interval_thirty_minute_buffer
        """
        morning, afternoon = _van_with_a_morning_call()
        api.dispatch_service_call(
            afternoon["id"],
            dispatch_call_payload(
                "V-99", "2026-08-01T11:30:00Z", "2026-08-01T12:30:00Z"
            ),
            TECH_ALT,
        )

        accepted = dispatch_call(
            afternoon["id"], "V-99",
            "2026-08-01T11:31:00Z", "2026-08-01T12:31:00Z", TECH_ALT,
        )
        assert accepted["status"] == "DISPATCHED"
        assert accepted["van_code"] == "V-99"
        assert accepted["assigned_tech_user_id"] == TECH_ALT["X-User-ID"]
        assert accepted["reserved_part_stock_id"] is None
        assert accepted["reserved_part_units"] == 0
        assert accepted["version"] == 2
        assert accepted["severity_score"] == 40
        assert accepted["severity"] == "ROUTINE"

        untouched = read_call(morning["id"])
        assert untouched["status"] == "DISPATCHED"
        assert untouched["scheduled_window_start"].startswith("2026-08-01T09:00:00")
        assert untouched["scheduled_window_end"].startswith("2026-08-01T11:00:00")
        assert untouched["assigned_tech_user_id"] == TECH["X-User-ID"]
