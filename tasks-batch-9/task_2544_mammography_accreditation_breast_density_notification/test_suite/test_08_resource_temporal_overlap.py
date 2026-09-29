"""Two opposite interval conventions in one service: half-open and closed."""

import pytest

from test_helpers import (
    acquire_and_interpret,
    assert_instant_equals,
    create_draft_survey,
    determine_coverage,
    list_total_count,
    read_order,
    read_unit,
    recommend_order,
    survey_payload,
    validate_error,
    validate_success,
)


@pytest.fixture
def occupied_annual_window(core):
    """An annual survey window closed on the left and open on the right."""
    create_draft_survey(
        core,
        survey_type="ANNUAL",
        effective_start="2026-07-01T00:00:00Z",
        effective_end="2026-08-01T00:00:00Z",
    )
    return core


def test_a_window_starting_at_the_incumbents_exclusive_end_is_accepted(
    api, occupied_annual_window
):
    """Adjacency is not overlap, so back-to-back annual windows both stand.

    PRD: "An incoming window whose `effective_start` exactly equals an existing
    window's `effective_end` is therefore adjacent, not overlapping, and is
    allowed; a genuine overlap is refused with `ERR_SURVEY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/survey_windows_are_half_open_so_adjacent_windows_are_accepted
    """
    core = occupied_annual_window
    survey = validate_success(
        api.create_physicist_survey(
            core["unit_id"],
            survey_payload(
                effective_start="2026-08-01T00:00:00Z", effective_end="2027-07-01T00:00:00Z"
            ),
            core["phys_headers"],
        ),
        expected_status=201,
    )
    assert survey["status"] == "DRAFT"
    assert_instant_equals(survey["effective_start"], "2026-08-01T00:00:00Z", "effective_start")
    assert_instant_equals(survey["effective_end"], "2027-07-01T00:00:00Z", "effective_end")


def test_a_window_starting_one_day_before_the_incumbents_end_collides(
    api, occupied_annual_window
):
    """A well-formed window inside the 396-day cap can still be a genuine overlap.

    PRD: "The window is closed on the left and open on the right, so two windows
    overlap only when the existing window's `effective_start` is strictly before the
    new `effective_end` **and** the new `effective_start` is strictly before the
    existing `effective_end`."

    Design: Difficulty/resource_temporal_overlap/survey_windows_are_half_open_so_adjacent_windows_are_accepted
    """
    core = occupied_annual_window
    validate_success(
        api.create_physicist_survey(
            core["unit_id"],
            survey_payload(
                effective_start="2026-08-01T00:00:00Z", effective_end="2027-07-01T00:00:00Z"
            ),
            core["phys_headers"],
        ),
        expected_status=201,
    )
    response = api.create_physicist_survey(
        core["unit_id"],
        survey_payload(
            effective_start="2027-06-30T00:00:00Z", effective_end="2027-08-01T00:00:00Z"
        ),
        core["phys_headers"],
    )
    validate_error(response, "ERR_SURVEY_WINDOW_OVERLAP", expected_status=409)
    listed = api.list_unit_physicist_surveys(core["unit_id"], core["coord_headers"])
    assert list_total_count(listed) == 2
    assert read_unit(core["unit_id"])["survey_compliance"] == "OVERDUE"


@pytest.fixture
def three_determined_orders(core):
    """Three patients, three ultrasound orders, each already priced."""
    order_ids = []
    for ref in ("PT-9801", "PT-9802", "PT-9803"):
        exam = acquire_and_interpret(
            core,
            birads=0,
            density="C",
            patient_ref=ref,
            performed_at="2026-07-27T00:00:00Z",
        )
        order = recommend_order(
            core,
            exam["id"],
            "ULTRASOUND",
            headers=core["rad_headers"],
            recommendation_note="Dense tissue workup",
        )
        determine_coverage(core, order["id"])
        order_ids.append(order["id"])
        core.setdefault("cap_exam_ids", []).append(exam["id"])
    core["order_ids"] = order_ids
    return core


def _schedule(api, order_id, start, headers):
    return api.schedule_supplemental_order(order_id, {"appointment_start": start}, headers)


def test_a_second_overlapping_booking_fits_under_a_capacity_of_two(
    api, three_determined_orders, coordinator_headers
):
    """One collision is below the facility's concurrent capacity, so the booking stands.

    PRD: "When the number of colliding peers reaches or exceeds the facility's
    `supplemental_concurrent_capacity`, the request is refused with
    `ERR_SUPPLEMENTAL_CAPACITY_CONFLICT`; a facility with the default capacity of 2
    therefore admits a third overlapping booking only after one of the two existing
    ones leaves `SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/supplemental_appointments_use_closed_occupancy_against_facility_capacity
    """
    core = three_determined_orders
    first = validate_success(
        _schedule(api, core["order_ids"][0], "2026-08-10T09:00:00Z", coordinator_headers)
    )
    assert first["status"] == "SCHEDULED"
    assert_instant_equals(first["appointment_end"], "2026-08-10T09:30:00Z", "appointment_end")
    second = validate_success(
        _schedule(api, core["order_ids"][1], "2026-08-10T09:30:00Z", coordinator_headers)
    )
    assert second["status"] == "SCHEDULED"
    assert_instant_equals(second["appointment_end"], "2026-08-10T10:00:00Z", "appointment_end")


def test_a_start_touching_the_turnover_end_collides_but_one_minute_later_fits(
    api, three_determined_orders, coordinator_headers
):
    """Occupancy is closed on both ends, so 09:45 collides with a 09:00 booking.

    PRD: "Each scheduled order occupies an interval running from its
    `appointment_start` to its `appointment_end` plus 15 minutes of room turnover,
    and that occupancy interval is **closed on both ends**, so two intervals that
    merely touch at an endpoint do collide — a patient booked to start exactly when
    the previous slot's turnover ends is a collision, not a fit."

    Design: Difficulty/resource_temporal_overlap/supplemental_appointments_use_closed_occupancy_against_facility_capacity
    """
    core = three_determined_orders
    _schedule(api, core["order_ids"][0], "2026-08-10T09:00:00Z", coordinator_headers)
    _schedule(api, core["order_ids"][1], "2026-08-10T09:30:00Z", coordinator_headers)
    refused = _schedule(api, core["order_ids"][2], "2026-08-10T09:45:00Z", coordinator_headers)
    validate_error(refused, "ERR_SUPPLEMENTAL_CAPACITY_CONFLICT", expected_status=409)
    blocked = read_order(core["order_ids"][2])
    assert blocked["status"] == "COVERAGE_DETERMINED"
    assert blocked["appointment_start"] is None
    third = validate_success(
        _schedule(api, core["order_ids"][2], "2026-08-10T09:46:00Z", coordinator_headers)
    )
    assert third["status"] == "SCHEDULED"
    assert_instant_equals(
        third["appointment_start"], "2026-08-10T09:46:00Z", "appointment_start"
    )
    assert_instant_equals(third["appointment_end"], "2026-08-10T10:16:00Z", "appointment_end")
