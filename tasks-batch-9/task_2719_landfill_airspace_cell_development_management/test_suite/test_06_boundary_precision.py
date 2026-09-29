"""Inclusive-versus-exclusive thresholds, exercised one unit either side of the line."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_cell_fill, assert_density
from test_helpers.test_users import TEST_USERS, make_site_operator_headers

CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]

BOUNDARY_CELL = {"design_airspace_cy": 200, "design_area_sf": 45001}
DAY_SHAPE = {"working_face_area_sf": 5000, "cover_material_type": "ALTERNATIVE_TARP"}


def _two_cells_either_side_of_the_full_fraction():
    """One 200 cy cell loaded with 166.60 certified tons, its twin with 166.50."""
    landfill = fixtures.create_landfill()
    first = fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides=dict(BOUNDARY_CELL, cell_code="C-2A",
                            construction_end_date="2026-07-20T00:00:00Z"),
    )["cell"]
    second = fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides=dict(BOUNDARY_CELL, cell_code="C-2B",
                            construction_end_date="2026-07-22T00:00:00Z"),
    )["cell"]
    estimate = fixtures.setup_funded_assurance(landfill["id"])
    for cell, reference in ((first, "AGY-2026-2A"), (second, "AGY-2026-2B")):
        fixtures.authorize_waste_placement(cell["id"], reference)
        fixtures.activate_cell(landfill["id"], cell["id"])
    fixtures.setup_executed_host_agreement(landfill["id"])

    first_day = fixtures.open_operating_day(
        landfill["id"], first["id"], operating_date="2026-08-05T00:00:00Z", **DAY_SHAPE
    )
    fixtures.place_certified_load(
        landfill["id"], first_day["id"], 166.60, hauler_ref="H-A", manifest_tons=166.6
    )
    second_day = fixtures.open_operating_day(
        landfill["id"], second["id"], operating_date="2026-08-06T00:00:00Z", **DAY_SHAPE
    )
    fixtures.place_certified_load(
        landfill["id"], second_day["id"], 166.50, hauler_ref="H-B", manifest_tons=166.5
    )
    return {
        "landfill": landfill,
        "first": first,
        "second": second,
        "estimate": estimate,
        "first_day": first_day,
        "second_day": second_day,
    }


def test_a_cell_at_exactly_ninety_eight_percent_is_full():
    """196.00 of 200 cubic yards is 98.00 percent, and the fraction is inclusive.

    PRD: "If the recomputed cell consumption has reached at least 98 percent of the cell's
    `design_airspace_cy` — that is, at or above the full-cell fraction of 0.98, with exact
    equality counting as full — the cell moves `ACTIVE → FULL` and its `version` is
    incremented by 1."

    Design: Difficulty/boundary_precision_check/cell_full_at_exactly_98_00_percent_and_not_at_97_94
    """
    world = _two_cells_either_side_of_the_full_fraction()

    closed = fixtures.close_operating_day(world["landfill"]["id"], world["first_day"]["id"])

    assert_amount(closed["airspace_consumed_cy"], 196.00, "day consumption")
    cell = get_success_data(api_client.get_cell(world["first"]["id"], AGENCY))
    assert_amount(cell["consumed_airspace_cy"], 196.00, "cell consumption")
    assert_amount(cell["fill_pct"], 98.00, "fill percentage")
    assert_cell_fill(cell)
    assert cell["status"] == "FULL"


def test_a_cell_one_tenth_of_a_ton_short_stays_active():
    """195.88 cubic yards is 97.94 percent, and the twin cell keeps taking waste.

    PRD: "`fill_pct` is one hundred times the consumed airspace divided by the cell's
    `design_airspace_cy`, rounded to 2 decimal places."

    Design: Difficulty/boundary_precision_check/cell_full_at_exactly_98_00_percent_and_not_at_97_94
    """
    world = _two_cells_either_side_of_the_full_fraction()

    closed = fixtures.close_operating_day(world["landfill"]["id"], world["second_day"]["id"])

    assert_amount(closed["airspace_consumed_cy"], 195.88, "day consumption")
    cell = get_success_data(api_client.get_cell(world["second"]["id"], AGENCY))
    assert_amount(cell["consumed_airspace_cy"], 195.88, "cell consumption")
    assert_amount(cell["fill_pct"], 97.94, "fill percentage")
    assert_cell_fill(cell)
    assert cell["status"] == "ACTIVE"


def test_one_cell_leaving_the_active_set_restricts_rather_than_suspends_the_site():
    """With one cell still active the posture reports a short life, not an outage.

    PRD: "The site's `active_cell_count` is recomputed and falls by one; if it reaches zero
    the site has nothing left to receive waste and its `operating_status` is set to
    `SUSPENDED_NO_AIRSPACE`."

    Design: Difficulty/boundary_precision_check/cell_full_at_exactly_98_00_percent_and_not_at_97_94
    """
    world = _two_cells_either_side_of_the_full_fraction()
    assert_amount(
        world["estimate"]["required_assurance_amount"], 4686618.22, "required assurance"
    )

    fixtures.close_operating_day(world["landfill"]["id"], world["first_day"]["id"])
    fixtures.close_operating_day(world["landfill"]["id"], world["second_day"]["id"])

    site = fixtures.read_landfill(world["landfill"]["id"])
    assert site["active_cell_count"] == 1
    assert site["operating_status"] == "RESTRICTED_AIRSPACE"
    assert_amount(site["consumed_airspace_cy"], 391.88, "site consumption")


COUNTERS_AT_THE_GATE = {"seam_length_ft": 4000, "destructive_test_count": 20,
                        "passing_test_count": 17, "panel_count": 40, "defect_count": 2}
COUNTERS_BELOW_THE_GATE = dict(COUNTERS_AT_THE_GATE, passing_test_count=16)
COUNTERS_WITH_ONE_EXTRA_DEFECT = dict(
    COUNTERS_AT_THE_GATE, passing_test_count=20, defect_count=3
)


def _package_under_review(landfill_id, cell_code, end_date, counters):
    cell = fixtures.create_cell_under_construction(
        landfill_id, cell_code=cell_code, construction_end_date=end_date
    )
    package = fixtures.submit_liner_qa_package(landfill_id, cell["id"], **counters)
    fixtures.begin_liner_review(package["id"])
    return cell, package


def _approve(package_id, reference):
    return api_client.approve_liner_qa_package(
        package_id, {"certification_reference": reference}, CQA_ENGINEER
    )


def test_a_score_of_exactly_eighty_five_passes_the_inclusive_gate():
    """17 of 20 passing tests score 85.00, and 85.00 is enough.

    PRD: "Three preconditions apply, and they are checked in the ladder order of §2.9: the
    package must be in `UNDER_REVIEW`; the approver's `X-User-ID` must differ from
    `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; and the `qa_conformance_score`
    must be at least 85.0, where exactly 85.0 passes, else `ERR_QA_SCORE_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/qa_score_and_defect_penalty_boundaries
    """
    landfill = fixtures.create_landfill()
    cell, package = _package_under_review(
        landfill["id"], "C-A", "2026-07-15T00:00:00Z", COUNTERS_AT_THE_GATE
    )
    assert_amount(package["qa_conformance_score"], 85.00, "conformance score")

    approved = get_success_data(_approve(package["id"], "CQA-BOUND-A"))

    assert approved["status"] == "APPROVED"
    assert get_success_data(api_client.get_cell(cell["id"], AGENCY))["status"] == "QA_CERTIFIED"


def test_a_score_of_eighty_is_refused_and_cascades_nothing():
    """One failed destructive test costs five points and the whole certification.

    PRD: "The score itself is one hundred multiplied by the test pass rate multiplied by the
    coverage factor, minus that already-rounded defect penalty; the difference is then
    clamped so it can be no lower than 0.0 and no higher than 100.0, and the clamped result
    is rounded to 2 decimal places."

    Design: Difficulty/boundary_precision_check/qa_score_and_defect_penalty_boundaries
    """
    landfill = fixtures.create_landfill()
    cell, package = _package_under_review(
        landfill["id"], "C-B", "2026-07-16T00:00:00Z", COUNTERS_BELOW_THE_GATE
    )
    assert_amount(package["qa_conformance_score"], 80.00, "conformance score")

    response = _approve(package["id"], "CQA-BOUND-B")

    validate_error(response, ApiErrorId.ERR_QA_SCORE_BELOW_THRESHOLD.value, 422)
    unchanged = get_success_data(
        api_client.get_liner_qa_package(package["id"], CQA_ENGINEER)
    )
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["certification_reference"] is None
    assert get_success_data(api_client.get_cell(cell["id"], AGENCY))["status"] == "QA_REVIEW"


def test_the_defect_penalty_is_rounded_before_it_is_subtracted():
    """A defect density of 0.075 costs exactly 10.00 points off a perfect pass rate.

    PRD: "The *defect density* is `defect_count` divided by `panel_count`; a density at or
    below the free allowance of 0.05 defects per panel — that is, up to one repaired defect
    for every twenty panels — attracts no penalty at all, and above it the penalty is one
    hundred times the amount by which the density exceeds 0.05, multiplied by a slope of 4,
    rounded to 2 decimal places, and then capped at 30.0 penalty points."

    Design: Difficulty/boundary_precision_check/qa_score_and_defect_penalty_boundaries
    """
    landfill = fixtures.create_landfill()
    at_the_allowance, first = _package_under_review(
        landfill["id"], "C-A", "2026-07-15T00:00:00Z", COUNTERS_AT_THE_GATE
    )
    over_the_allowance, third = _package_under_review(
        landfill["id"], "C-C", "2026-07-17T00:00:00Z", COUNTERS_WITH_ONE_EXTRA_DEFECT
    )
    assert_amount(third["qa_conformance_score"], 90.00, "conformance score")

    get_success_data(_approve(first["id"], "CQA-BOUND-A"))
    approved = get_success_data(_approve(third["id"], "CQA-BOUND-C"))

    assert approved["status"] == "APPROVED"
    assert get_success_data(
        api_client.get_cell(over_the_allowance["id"], AGENCY)
    )["status"] == "QA_CERTIFIED"
    site = fixtures.read_landfill(landfill["id"])
    assert_amount(site["certified_airspace_cy"], 2000000, "certified airspace")
    assert at_the_allowance["design_airspace_cy"] == 1000000


FIRST_FLIGHT = {
    "flown_on": "2026-08-01T00:00:00Z",
    "coverage_period_start": "2026-05-01T00:00:00Z",
    "coverage_period_end": "2026-07-31T00:00:00Z",
    "measured_remaining_airspace_cy": 700000,
    "tons_placed_in_period": 250000,
}
SECOND_FLIGHT = {
    "measured_remaining_airspace_cy": 640000,
    "tons_placed_in_period": 50000,
}


def _site_with_one_recorded_flight():
    """A million certified cubic yards and one reduced flight covering May to July."""
    landfill = fixtures.create_landfill()
    fixtures.setup_qa_certified_cell(landfill["id"])
    first = fixtures.record_aerial_survey(landfill["id"], **FIRST_FLIGHT)
    assert_amount(first["airspace_consumed_in_period_cy"], 300000.00, "consumed in period")
    assert_density(first["measured_density_tons_per_cy"], 0.8333, "measured density")
    return landfill, first


def _fly(landfill_id, flown_on, coverage_period_start, coverage_period_end):
    from test_helpers.factories import aerial_survey_payload

    return api_client.create_aerial_survey(
        aerial_survey_payload(
            landfill_id,
            flown_on=flown_on,
            coverage_period_start=coverage_period_start,
            coverage_period_end=coverage_period_end,
            **SECOND_FLIGHT,
        ),
        SURVEYOR,
    )


def test_a_flight_eighty_nine_days_after_the_last_one_is_too_close():
    """Spacing is measured in whole days and 89 of them is one short.

    PRD: "Separately, the new survey's `flown_on` date must be at least 90 whole days away
    from the `flown_on` date of every `RECORDED` or `SUPERSEDED` survey of the same site;
    exactly 90 days apart is allowed, and anything closer is refused with
    `ERR_SURVEY_SPACING_VIOLATION`."

    Design: Difficulty/boundary_precision_check/survey_overlap_and_ninety_day_spacing_boundaries
    """
    landfill, _first = _site_with_one_recorded_flight()

    response = _fly(
        landfill["id"], "2026-10-29T00:00:00Z", "2026-08-01T00:00:00Z", "2026-10-29T00:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_SURVEY_SPACING_VIOLATION.value, 409)


def test_a_coverage_period_starting_on_the_previous_closing_day_overlaps():
    """Coverage intervals are closed, so touching endpoints collide.

    PRD: "Coverage intervals are treated as **closed** on both ends, so two intervals
    overlap whenever the new period's start is at or before an existing period's end *and*
    that existing period's start is at or before the new period's end — touching endpoints
    therefore **do** count as an overlap."

    Design: Difficulty/boundary_precision_check/survey_overlap_and_ninety_day_spacing_boundaries
    """
    landfill, _first = _site_with_one_recorded_flight()

    response = _fly(
        landfill["id"], "2026-10-30T00:00:00Z", "2026-07-31T00:00:00Z", "2026-10-29T00:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_SURVEY_PERIOD_OVERLAP.value, 409)


def test_the_accepted_flight_reduces_against_the_prior_survey():
    """Ninety days apart and one day clear of the old interval, the flight lands.

    PRD: "When such a prior survey exists, the consumed figure is that prior survey's
    `measured_remaining_airspace_cy` minus the new survey's own
    `measured_remaining_airspace_cy`, rounded to 2 decimal places."

    Design: Difficulty/boundary_precision_check/survey_overlap_and_ninety_day_spacing_boundaries
    """
    landfill, first = _site_with_one_recorded_flight()

    second = get_success_data(
        _fly(
            landfill["id"],
            "2026-10-30T00:00:00Z",
            "2026-08-01T00:00:00Z",
            "2026-10-29T00:00:00Z",
        )
    )

    assert second["status"] == "RECORDED"
    assert_amount(second["airspace_consumed_in_period_cy"], 60000.00, "consumed in period")
    assert_density(second["measured_density_tons_per_cy"], 0.8333, "measured density")
    assert get_success_data(
        api_client.get_aerial_survey(first["id"], SURVEYOR)
    )["status"] == "SUPERSEDED"
    assert_amount(
        fixtures.read_landfill(landfill["id"])["remaining_life_years"], 1.78, "remaining life"
    )
    rows, _meta = validate_paginated(
        api_client.list_aerial_surveys(SURVEYOR, params={"limit": 100})
    )
    mine = [row for row in rows if row["landfill_id"] == landfill["id"]]
    assert len(mine) == 2, "the two refused flights must not have created rows"


HAULING_ENVELOPE = {
    "daily_gallon_cap": 20000,
    "concurrent_slot_capacity": 2,
    "base_haul_fee": 350.0,
    "treatment_rate_per_kgal": 62.5,
}


def _agreement_with_twelve_thousand_booked():
    """Two hauls on 2026-08-05 leaving 8,000 gallons and one free slot after noon."""
    landfill = fixtures.create_landfill()
    agreement = fixtures.register_treatment_agreement(landfill["id"], **HAULING_ENVELOPE)
    fixtures.set_clock("2026-08-05T06:00:00Z")
    fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=8000,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=4000,
        window_start="2026-08-05T10:00:00Z",
        window_end="2026-08-05T14:00:00Z",
    )
    return landfill, agreement


def _haul(landfill_id, agreement_id, gallons, window_start, window_end):
    from test_helpers.factories import leachate_shipment_payload

    return api_client.create_leachate_shipment(
        leachate_shipment_payload(
            agreement_id,
            gallons=gallons,
            window_start=window_start,
            window_end=window_end,
        ),
        make_site_operator_headers(landfill_id),
    )


def test_a_window_that_begins_as_another_ends_does_not_share_its_slot():
    """Half-open windows let a noon departure ride the slot the morning haul just left.

    PRD: "The window is **half-open**: it includes its start instant and excludes its end
    instant, `window_end` must be strictly after `window_start`, and both must fall on the
    same UTC calendar date."

    Design: Difficulty/boundary_precision_check/leachate_daily_gallon_cap_exact_equality_and_touching_window
    """
    landfill, agreement = _agreement_with_twelve_thousand_booked()

    third = get_success_data(
        _haul(
            landfill["id"],
            agreement["id"],
            8000,
            "2026-08-05T12:00:00Z",
            "2026-08-05T16:00:00Z",
        )
    )

    assert third["status"] == "SCHEDULED"
    reread = get_success_data(api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 20000, "scheduled gallons today")


def test_one_gallon_past_the_inclusive_daily_cap_is_refused():
    """Twenty thousand gallons exactly is allowed; twenty thousand and one is not.

    PRD: "Second, `scheduled_gallons_today` for that agreement on the calendar date of the
    requested `window_start`, plus the requested `gallons`, may not exceed
    `daily_gallon_cap`; exact equality with the cap is allowed, and exceeding it is refused
    with `ERR_DAILY_GALLON_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/leachate_daily_gallon_cap_exact_equality_and_touching_window
    """
    landfill, agreement = _agreement_with_twelve_thousand_booked()
    _haul(landfill["id"], agreement["id"], 8000, "2026-08-05T12:00:00Z", "2026-08-05T16:00:00Z")

    response = _haul(
        landfill["id"], agreement["id"], 1, "2026-08-05T16:00:00Z", "2026-08-05T18:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_DAILY_GALLON_CAP_EXCEEDED.value, 422)
    reread = get_success_data(api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 20000, "scheduled gallons today")


def test_the_cap_is_keyed_on_the_calendar_date_of_the_window_start():
    """A full day's allowance is available again on the next date, and today's total holds.

    PRD: "`scheduled_gallons_today` is a derivation, not a counter: at any moment it is the
    sum of `gallons` over the shipments of that agreement which are in `SCHEDULED`,
    `DISPATCHED` or `ACCEPTED` and whose `window_start` falls on the current logical clock's
    UTC calendar date."

    Design: Difficulty/boundary_precision_check/leachate_daily_gallon_cap_exact_equality_and_touching_window
    """
    landfill, agreement = _agreement_with_twelve_thousand_booked()
    _haul(landfill["id"], agreement["id"], 8000, "2026-08-05T12:00:00Z", "2026-08-05T16:00:00Z")

    tomorrow = get_success_data(
        _haul(
            landfill["id"],
            agreement["id"],
            20000,
            "2026-08-06T08:00:00Z",
            "2026-08-06T10:00:00Z",
        )
    )

    assert tomorrow["status"] == "SCHEDULED"
    reread = get_success_data(api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER))
    assert_amount(reread["scheduled_gallons_today"], 20000, "scheduled gallons today")
    rows, _meta = validate_paginated(
        api_client.list_leachate_shipments(ENV_MANAGER, params={"limit": 100})
    )
    mine = [row for row in rows if row["treatment_agreement_id"] == agreement["id"]]
    assert len(mine) == 4, "four bookings survived, one per accepted request"
