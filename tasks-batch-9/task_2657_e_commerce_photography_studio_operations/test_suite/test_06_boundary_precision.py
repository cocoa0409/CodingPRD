"""Boundaries decided by the smallest representable step.

An inclusive colour tolerance crossed by one hundredth, a return deadline
crossed by one second, and a station day crossed by one minute.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STATION_CAPACITY_EXCEEDED
from test_helpers.test_users import ADMIN, COORDINATOR, PRODUCER, make_photographer_headers


# ─── color_composite_exactly_at_tolerance_passes_while_one_hundredth_over_fails ──

def _two_still_life_sessions_shooting(api):
    """Two STILL_LIFE benches, one style each, both sessions SHOOTING at 09:00.

    Separate stations mean neither reading can serve as the other's drift
    baseline, so each verdict is decided by the tolerance comparison alone.
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(
        api, required_angles=["FRONT"], min_on_model_shots=0
    )
    st1 = fx.create_station(api, station_code="SL-1", station_type="STILL_LIFE")
    st2 = fx.create_station(api, station_code="SL-2", station_type="STILL_LIFE")
    provider = fx.create_provider(api)
    ph1 = fx.create_photographer(api)
    ph2 = fx.create_photographer(
        api, full_name="Tao Vek", hourly_rate_cents=11000, day_rate_cents=70000
    )

    world = {"ph1": ph1, "ph2": ph2, "sessions": []}
    for station, photographer, style_number, barcode in (
        (st1, ph1, "TOP1001", "SMP-1001"),
        (st2, ph2, "TOP1002", "SMP-1002"),
    ):
        style = fx.create_style(
            api,
            vendor["id"],
            profile["id"],
            style_number=style_number,
            priority_tier="C",
        )
        sample = fx.create_sample(
            api, vendor["id"], barcode=barcode, declared_style_number=style_number
        )
        fx.receive_sample(api, sample["id"])
        fx.match_sample(api, sample["id"], style["id"])
        fx.custody_move(api, sample["id"], "IN_STUDIO")
        item = fx.create_shot_item(
            api, style["id"], asset_kind="STILL_ANGLE", angle_code="FRONT"
        )
        session = fx.create_session(api, station["id"], provider["id"])
        fx.assign_item(api, item["id"], session["id"])
        booking = fx.create_booking(api, session["id"], photographer["id"])
        fx.confirm_booking(api, booking["id"])
        fx.lock_session(api, session["id"])
        world["sessions"].append(session)

    fx.set_clock(api, "2026-08-03T09:00:00Z")
    for session, photographer in zip(world["sessions"], (ph1, ph2)):
        fx.start_session(api, session["id"], photographer["id"])
    return world


def test_composite_landing_exactly_on_the_tolerance_passes(api):
    """Half of 2.5 plus half of 1.0 hits 2.00 against a 2.00 tolerance.

    PRD: "The verdict is then inclusive: `color_check_state` becomes `PASS` when the composite is less than or equal to the session's `color_tolerance_delta_e`, and `FAIL` only when it is strictly greater."

    Design: Difficulty/boundary_precision_check/color_composite_exactly_at_tolerance_passes_while_one_hundredth_over_fails
    """
    world = _two_still_life_sessions_shooting(api)
    session = world["sessions"][0]

    measured = validate_success(
        api.submit_color_measurement(
            session["id"],
            f.color_measurement_payload([2.5, 1.0, 1.0]),
            make_photographer_headers(world["ph1"]["id"]),
        ),
        200,
    )

    assert float(measured["color_composite_delta_e"]) == pytest.approx(2.00, abs=0.005)
    assert measured["color_check_state"] == "PASS"


def test_composite_one_hundredth_over_the_tolerance_is_recorded_as_a_failure(api):
    """The same weighting on 2.52 rounds to 2.01 and the verdict flips.

    PRD: "On a `MANNEQUIN` or `STILL_LIFE` station the two contributions are weighted equally, one half each, likewise rounded half up to two decimals."

    Design: Difficulty/boundary_precision_check/color_composite_exactly_at_tolerance_passes_while_one_hundredth_over_fails
    """
    world = _two_still_life_sessions_shooting(api)
    session = world["sessions"][1]

    measured = validate_success(
        api.submit_color_measurement(
            session["id"],
            f.color_measurement_payload([2.52, 1.0, 1.0]),
            make_photographer_headers(world["ph2"]["id"]),
        ),
        200,
    )

    assert float(measured["color_composite_delta_e"]) == pytest.approx(2.01, abs=0.005)
    assert measured["color_check_state"] == "FAIL"


def test_each_accepted_reading_names_its_own_acting_photographer(api):
    """Two readings on two benches attribute to the two photographers who took them.

    PRD: "When the reading is accepted, `color_patch_deltas` records the submitted array verbatim, `color_composite_delta_e` records the composite, `color_check_state` records the verdict, `color_measured_at` is stamped from the logical clock, and `color_measured_by_talent_id` records the acting photographer."

    Design: Difficulty/boundary_precision_check/color_composite_exactly_at_tolerance_passes_while_one_hundredth_over_fails
    """
    world = _two_still_life_sessions_shooting(api)
    ses_a, ses_b = world["sessions"]

    a = fx.measure_colour(api, ses_a["id"], world["ph1"]["id"], [2.5, 1.0, 1.0])
    b = fx.measure_colour(api, ses_b["id"], world["ph2"]["id"], [2.52, 1.0, 1.0])

    assert a["color_measured_by_talent_id"] == world["ph1"]["id"]
    assert b["color_measured_by_talent_id"] == world["ph2"]["id"]


# ─── return_exactly_at_due_instant_is_not_late_but_one_second_past_is_one_day ────

def _two_samples_due_at_the_same_instant(api):
    """Two boxes received at midnight on a 14-day service level, both awaiting return."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    vendor = fx.create_vendor(api, sample_sla_days=14)
    samples = []
    for barcode, style_number in (("SMP-2001", "TOP1001"), ("SMP-2002", "TOP1002")):
        sample = fx.create_sample(
            api, vendor["id"], barcode=barcode, declared_style_number=style_number
        )
        fx.receive_sample(api, sample["id"])
        samples.append(fx.custody_move(api, sample["id"], "RETURN_PENDING"))
    return {"vendor": vendor, "samples": samples}


def test_return_at_precisely_the_due_instant_carries_no_lateness(api):
    """The box handed back on the stroke of the deadline owes nothing.

    PRD: "The boundary is deliberately generous by exactly one instant: returning at precisely `due_return_at` yields 0 days late, while returning one second later yields a full day late."

    Design: Difficulty/boundary_precision_check/return_exactly_at_due_instant_is_not_late_but_one_second_past_is_one_day
    """
    world = _two_samples_due_at_the_same_instant(api)
    sample = world["samples"][0]
    assert sample["due_return_at"] == "2026-08-15T00:00:00.000Z"

    fx.set_clock(api, "2026-08-15T00:00:00Z")
    returned = validate_success(
        api.return_sample(
            sample["id"], COORDINATOR, {"condition_note": "on time to the second"}
        )
    )

    assert returned["custody_state"] == "RETURNED"
    assert returned["return_days_late"] == 0


def test_return_one_second_past_due_rounds_up_to_a_whole_day(api):
    """A single second of overrun is ceilinged into one full day late.

    PRD: "Sample lateness, `return_days_late`, is a whole number of days obtained by rounding up any positive overrun."

    Design: Difficulty/boundary_precision_check/return_exactly_at_due_instant_is_not_late_but_one_second_past_is_one_day
    """
    world = _two_samples_due_at_the_same_instant(api)
    sample = world["samples"][1]
    assert sample["due_return_at"] == "2026-08-15T00:00:00.000Z"

    fx.set_clock(api, "2026-08-15T00:00:01Z")
    returned = validate_success(
        api.return_sample(
            sample["id"], COORDINATOR, {"condition_note": "one second past due"}
        )
    )

    assert returned["custody_state"] == "RETURNED"
    assert returned["return_days_late"] == 1


def test_only_the_late_side_of_the_line_costs_the_vendor_a_strike(api):
    """Two returns drain the outstanding count; only one of them is a strike.

    PRD: "The vendor's `outstanding_sample_count` then falls by one; if `return_days_late` is greater than 0 the vendor also takes a strike, raising `late_return_count` by one; and once `late_return_count` reaches 3 strikes the vendor's `coordination_hold` flips to true, which is what stops any further receipts from that vendor."

    Design: Difficulty/boundary_precision_check/return_exactly_at_due_instant_is_not_late_but_one_second_past_is_one_day
    """
    world = _two_samples_due_at_the_same_instant(api)
    smp_a, smp_b = world["samples"]
    assert validate_success(api.get_vendor(world["vendor"]["id"], ADMIN))[
        "outstanding_sample_count"
    ] == 2

    fx.set_clock(api, "2026-08-15T00:00:00Z")
    validate_success(api.return_sample(smp_a["id"], COORDINATOR))
    fx.set_clock(api, "2026-08-15T00:00:01Z")
    validate_success(api.return_sample(smp_b["id"], COORDINATOR))

    vendor = validate_success(api.get_vendor(world["vendor"]["id"], ADMIN))
    assert vendor["outstanding_sample_count"] == 0
    assert vendor["late_return_count"] == 1
    assert vendor["coordination_hold"] is False


# ─── station_day_capacity_accepts_the_exact_total_and_rejects_it_by_one_minute ───

def _station_day_filled_to_the_ceiling(api):
    """A 480-minute bench carrying two back-to-back 240-minute sessions."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(
        api,
        station_code="SL-1",
        station_type="STILL_LIFE",
        daily_capacity_minutes=480,
    )
    provider = fx.create_provider(api)
    first = validate_success(
        api.create_shoot_session(
            f.session_payload(
                station["id"],
                provider["id"],
                scheduled_start="2026-08-03T09:00:00Z",
                scheduled_end="2026-08-03T13:00:00Z",
            ),
            PRODUCER,
        ),
        201,
    )
    second = validate_success(
        api.create_shoot_session(
            f.session_payload(
                station["id"],
                provider["id"],
                scheduled_start="2026-08-03T13:00:00Z",
                scheduled_end="2026-08-03T17:00:00Z",
            ),
            PRODUCER,
        ),
        201,
    )
    return {"station": station, "provider": provider, "sessions": [first, second]}


def test_a_day_filled_exactly_to_the_ceiling_is_permitted(api):
    """Two hundred and forty plus two hundred and forty is accepted at equality.

    PRD: "Landing exactly on the ceiling is permitted; only a strictly greater total is refused, with `ERR_STATION_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/station_day_capacity_accepts_the_exact_total_and_rejects_it_by_one_minute
    """
    world = _station_day_filled_to_the_ceiling(api)

    assert world["sessions"][0]["planned_minutes"] == 240
    assert world["sessions"][1]["planned_minutes"] == 240
    assert validate_success(api.get_station(world["station"]["id"], ADMIN))[
        "committed_minutes_today"
    ] == 480


def test_one_further_minute_over_the_ceiling_is_refused_and_changes_nothing(api):
    """A sixty-second session pushes the day to 481 and is turned away.

    PRD: "The system sums `planned_minutes` over the station's sessions that are not cancelled and whose `scheduled_start` falls on the same UTC calendar date as the candidate's, adds the candidate's own `planned_minutes`, and requires the total to be no greater than the station's `daily_capacity_minutes`."

    Design: Difficulty/boundary_precision_check/station_day_capacity_accepts_the_exact_total_and_rejects_it_by_one_minute
    """
    world = _station_day_filled_to_the_ceiling(api)

    response = api.create_shoot_session(
        f.session_payload(
            world["station"]["id"],
            world["provider"]["id"],
            scheduled_start="2026-08-03T17:00:00Z",
            scheduled_end="2026-08-03T17:01:00Z",
        ),
        PRODUCER,
    )

    validate_error(response, ERR_STATION_CAPACITY_EXCEEDED, 409)
    assert validate_success(api.get_station(world["station"]["id"], ADMIN))[
        "committed_minutes_today"
    ] == 480
