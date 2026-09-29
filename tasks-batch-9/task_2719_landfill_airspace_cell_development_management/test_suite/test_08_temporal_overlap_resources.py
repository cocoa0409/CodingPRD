"""Two temporal resources with deliberately opposite interval semantics."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_density
from test_helpers.factories import aerial_survey_payload, leachate_shipment_payload
from test_helpers.test_users import TEST_USERS, make_site_operator_headers

SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]

FIRST_FLIGHT = {
    "flown_on": "2026-08-01T00:00:00Z",
    "coverage_period_start": "2026-05-01T00:00:00Z",
    "coverage_period_end": "2026-07-31T00:00:00Z",
    "measured_remaining_airspace_cy": 700000,
    "tons_placed_in_period": 250000,
}
# Coverage starts on the day the first flight's coverage ended: a closed-interval clash.
TOUCHING_COVERAGE = {
    "flown_on": "2026-11-15T00:00:00Z",
    "coverage_period_start": "2026-07-31T00:00:00Z",
    "coverage_period_end": "2026-10-31T00:00:00Z",
    "measured_remaining_airspace_cy": 640000,
    "tons_placed_in_period": 50000,
}
# Disjoint coverage, but only 89 whole days after the first flight.
EIGHTY_NINE_DAYS_OUT = {
    "flown_on": "2026-10-29T00:00:00Z",
    "coverage_period_start": "2026-08-01T00:00:00Z",
    "coverage_period_end": "2026-10-28T00:00:00Z",
    "measured_remaining_airspace_cy": 640000,
    "tons_placed_in_period": 50000,
}
# Touching coverage AND 89 days out: both rules broken by one request.
BOTH_RULES_BROKEN = {
    "flown_on": "2026-10-29T00:00:00Z",
    "coverage_period_start": "2026-07-31T00:00:00Z",
    "coverage_period_end": "2026-10-28T00:00:00Z",
    "measured_remaining_airspace_cy": 640000,
    "tons_placed_in_period": 50000,
}
# Exactly 90 whole days out with disjoint coverage: the clean second flight.
NINETY_DAYS_OUT = {
    "flown_on": "2026-10-30T00:00:00Z",
    "coverage_period_start": "2026-08-01T00:00:00Z",
    "coverage_period_end": "2026-10-29T00:00:00Z",
    "measured_remaining_airspace_cy": 640000,
    "tons_placed_in_period": 50000,
}


def _site_with_one_reduced_flight():
    """One certified cell of 1,000,000 cy and one survey holding both temporal claims."""
    landfill = fixtures.create_landfill(
        planned_density_tons_per_cy=0.9, annual_tonnage_forecast=300000
    )
    fixtures.setup_qa_certified_cell(
        landfill["id"], cell_overrides={"design_airspace_cy": 1000000}
    )
    first = fixtures.record_aerial_survey(landfill["id"], **FIRST_FLIGHT)
    assert first["status"] == "RECORDED"
    assert_amount(first["airspace_consumed_in_period_cy"], 300000.00, "S1 consumed airspace")
    assert_density(first["measured_density_tons_per_cy"], 0.8333, "S1 measured density")
    posture = fixtures.read_landfill(landfill["id"])
    assert_amount(posture["remaining_life_years"], 1.94, "remaining life after S1")
    assert posture["operating_status"] == "RESTRICTED_AIRSPACE"
    return landfill, first


def _fly(landfill_id, **overrides):
    return api_client.create_aerial_survey(
        aerial_survey_payload(landfill_id, **overrides), SURVEYOR
    )


def _surveys_of(landfill_id):
    data, _meta = validate_paginated(
        api_client.list_aerial_surveys(SURVEYOR, {"landfill_id": landfill_id})
    )
    return data


def test_coverage_periods_that_merely_touch_already_overlap():
    """A start date equal to an existing end date is a conflict, not an adjacency.

    PRD: "Coverage intervals are treated as **closed** on both ends, so two intervals
    overlap whenever the new period's start is at or before an existing period's end *and*
    that existing period's start is at or before the new period's end — touching endpoints
    therefore **do** count as an overlap."

    Design: Difficulty/resource_temporal_overlap/survey_coverage_closed_intervals_plus_ninety_day_spacing_buffer
    """
    landfill, first = _site_with_one_reduced_flight()

    response = _fly(landfill["id"], **TOUCHING_COVERAGE)

    validate_error(response, ApiErrorId.ERR_SURVEY_PERIOD_OVERLAP.value, 409)
    surveys = _surveys_of(landfill["id"])
    assert [survey["id"] for survey in surveys] == [first["id"]], (
        "a refused flight must not leave a survey row behind"
    )
    assert surveys[0]["status"] == "RECORDED"
    assert surveys[0]["version"] == first["version"]


def test_a_flight_eighty_nine_days_out_breaches_the_spacing_buffer():
    """Disjoint ground truth is not enough; the flight dates themselves are too close.

    PRD: "Separately, the new survey's `flown_on` date must be at least 90 whole days away
    from the `flown_on` date of every `RECORDED` or `SUPERSEDED` survey of the same site;
    exactly 90 days apart is allowed, and anything closer is refused with
    `ERR_SURVEY_SPACING_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/survey_coverage_closed_intervals_plus_ninety_day_spacing_buffer
    """
    landfill, first = _site_with_one_reduced_flight()

    response = _fly(landfill["id"], **EIGHTY_NINE_DAYS_OUT)

    validate_error(response, ApiErrorId.ERR_SURVEY_SPACING_VIOLATION.value, 409)
    assert [survey["id"] for survey in _surveys_of(landfill["id"])] == [first["id"]]


def test_a_flight_breaching_both_rules_is_reported_as_an_overlap():
    """Two live violations, one error id: the coverage rung is evaluated first.

    PRD: "Overlap is checked before spacing, so a survey that breaches both is reported as
    an overlap."

    Design: Difficulty/resource_temporal_overlap/survey_coverage_closed_intervals_plus_ninety_day_spacing_buffer
    """
    landfill, _first = _site_with_one_reduced_flight()

    response = _fly(landfill["id"], **BOTH_RULES_BROKEN)

    validate_error(response, ApiErrorId.ERR_SURVEY_PERIOD_OVERLAP.value, 409)


def test_exactly_ninety_days_out_with_disjoint_coverage_is_recorded():
    """One day later the identical coverage is accepted and reduced against S1.

    PRD: "When such a prior survey exists, the consumed figure is that prior survey's
    `measured_remaining_airspace_cy` minus the new survey's own
    `measured_remaining_airspace_cy`, rounded to 2 decimal places."

    Design: Difficulty/resource_temporal_overlap/survey_coverage_closed_intervals_plus_ninety_day_spacing_buffer
    """
    landfill, first = _site_with_one_reduced_flight()

    second = get_success_data(_fly(landfill["id"], **NINETY_DAYS_OUT))

    assert second["status"] == "RECORDED"
    assert_amount(second["airspace_consumed_in_period_cy"], 60000.00, "S2 consumed airspace")
    assert_density(second["measured_density_tons_per_cy"], 0.8333, "S2 measured density")
    superseded = get_success_data(api_client.get_aerial_survey(first["id"], SURVEYOR))
    assert superseded["status"] == "SUPERSEDED"
    assert_amount(
        fixtures.read_landfill(landfill["id"])["remaining_life_years"], 1.78, "remaining life"
    )


def test_voiding_the_second_flight_restores_the_superseded_first_one():
    """The compensation walks the supersession chain backwards, not to the ledger.

    PRD: "The void then **restores the previous picture**: among the site's surveys in
    `SUPERSEDED`, the one ranked first by `flown_on` descending and, as a tie-break,
    `created_at` descending, is put back to `RECORDED` with its `version` incremented by 1."

    Design: Difficulty/resource_temporal_overlap/survey_coverage_closed_intervals_plus_ninety_day_spacing_buffer
    """
    landfill, first = _site_with_one_reduced_flight()
    second = get_success_data(_fly(landfill["id"], **NINETY_DAYS_OUT))

    voided = fixtures.void_aerial_survey(
        second["id"], "Photogrammetric control point mis-surveyed."
    )

    assert voided["status"] == "VOID"
    restored = get_success_data(api_client.get_aerial_survey(first["id"], SURVEYOR))
    assert restored["status"] == "RECORDED"
    assert restored["version"] > first["version"]
    assert_amount(
        fixtures.read_landfill(landfill["id"])["remaining_life_years"], 1.94, "remaining life"
    )


def test_a_voided_flight_frees_both_its_interval_and_its_spacing_claim():
    """The payload that was just accepted is accepted again, over the void's own dates.

    PRD: "Only surveys currently in `RECORDED` or `SUPERSEDED` occupy an interval; a voided
    survey frees both its interval and its spacing buffer."

    Design: Difficulty/resource_temporal_overlap/survey_coverage_closed_intervals_plus_ninety_day_spacing_buffer
    """
    landfill, _first = _site_with_one_reduced_flight()
    second = get_success_data(_fly(landfill["id"], **NINETY_DAYS_OUT))
    fixtures.void_aerial_survey(second["id"], "Photogrammetric control point mis-surveyed.")

    replay = get_success_data(_fly(landfill["id"], **NINETY_DAYS_OUT))

    assert replay["status"] == "RECORDED"
    assert replay["id"] != second["id"]
    assert_density(replay["measured_density_tons_per_cy"], 0.8333, "replayed measured density")
    assert_amount(
        fixtures.read_landfill(landfill["id"])["remaining_life_years"], 1.78, "remaining life"
    )
    assert get_success_data(api_client.get_aerial_survey(second["id"], SURVEYOR))["status"] == (
        "VOID"
    ), "a terminal survey is never re-superseded by a later flight"


HAULING_ENVELOPE = {
    "facility_name": "Valley POTW",
    "daily_gallon_cap": 20000,
    "concurrent_slot_capacity": 2,
    "base_haul_fee": 350.0,
    "treatment_rate_per_kgal": 62.5,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-12-31T00:00:00Z",
}
# All four windows fall on the logical clock's startup date, so all four count today.
FOUR_HAULS = (
    ("w1", 8000, "2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z"),
    ("w2", 4000, "2026-08-01T10:00:00Z", "2026-08-01T14:00:00Z"),
    ("w4", 6000, "2026-08-01T12:00:00Z", "2026-08-01T16:00:00Z"),
    ("w5", 2000, "2026-08-01T16:00:00Z", "2026-08-01T18:00:00Z"),
)


def _contract_booked_to_the_daily_cap():
    """Four hauls totalling exactly 20,000 gallons and never more than two per instant."""
    landfill = fixtures.create_landfill()
    agreement = fixtures.register_treatment_agreement(landfill["id"], **HAULING_ENVELOPE)
    hauls = {}
    for label, gallons, window_start, window_end in FOUR_HAULS:
        hauls[label] = fixtures.book_shipment(
            landfill["id"],
            agreement["id"],
            gallons=gallons,
            window_start=window_start,
            window_end=window_end,
        )
    return landfill, agreement, hauls


def _book(landfill_id, agreement_id, gallons, window_start, window_end):
    return api_client.create_leachate_shipment(
        leachate_shipment_payload(
            agreement_id,
            gallons=gallons,
            window_start=window_start,
            window_end=window_end,
        ),
        make_site_operator_headers(landfill_id),
    )


def _gallons_today(agreement_id):
    return get_success_data(api_client.get_treatment_agreement(agreement_id, ENV_MANAGER))[
        "scheduled_gallons_today"
    ]


def _hauls_of(agreement_id):
    data, _meta = validate_paginated(
        api_client.list_agreement_leachate_shipments(agreement_id, ENV_MANAGER)
    )
    return data


def test_a_haul_starting_as_another_ends_shares_no_slot():
    """The 12:00 haul touches the one ending at 12:00, so only two slots are ever held.

    PRD: "Two shipments of the same agreement therefore overlap when the new window's start
    is strictly before the other window's end *and* the other window's start is strictly
    before the new window's end — windows that merely touch, where one begins exactly as the
    other ends, do **not** overlap."

    Design: Difficulty/resource_temporal_overlap/leachate_slot_occupancy_is_half_open_and_survives_state_changes
    """
    _landfill, agreement, hauls = _contract_booked_to_the_daily_cap()

    assert_amount(_gallons_today(agreement["id"]), 20000, "scheduled gallons today")
    assert len(_hauls_of(agreement["id"])) == 4
    for label in ("w1", "w2", "w4", "w5"):
        assert hauls[label]["status"] == "SCHEDULED", (
            "a booking that only touches its neighbour takes no extra slot"
        )


def test_a_window_overlapping_three_hauls_breaches_the_slot_ceiling():
    """One thousand gallons cannot be squeezed into an instant that already holds three.

    PRD: "First, the number of shipments of that agreement in `SCHEDULED`, `DISPATCHED` or
    `ACCEPTED` whose windows overlap the requested one, counting the new shipment itself,
    may not exceed `concurrent_slot_capacity`; exceeding it is refused with
    `ERR_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/leachate_slot_occupancy_is_half_open_and_survives_state_changes
    """
    landfill, agreement, _hauls = _contract_booked_to_the_daily_cap()

    response = _book(
        landfill["id"], agreement["id"], 1000, "2026-08-01T11:00:00Z", "2026-08-01T13:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)
    assert len(_hauls_of(agreement["id"])) == 4, "a refused booking creates no shipment row"
    assert_amount(_gallons_today(agreement["id"]), 20000, "scheduled gallons today")


def test_a_window_overlapping_nothing_isolates_the_gallon_ceiling():
    """An evening haul takes a free slot and still overruns the calendar-day total.

    PRD: "Second, `scheduled_gallons_today` for that agreement on the calendar date of the
    requested `window_start`, plus the requested `gallons`, may not exceed
    `daily_gallon_cap`; exact equality with the cap is allowed, and exceeding it is refused
    with `ERR_DAILY_GALLON_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/leachate_slot_occupancy_is_half_open_and_survives_state_changes
    """
    landfill, agreement, _hauls = _contract_booked_to_the_daily_cap()

    response = _book(
        landfill["id"], agreement["id"], 1000, "2026-08-01T18:00:00Z", "2026-08-01T20:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_DAILY_GALLON_CAP_EXCEEDED.value, 422)
    assert len(_hauls_of(agreement["id"])) == 4
    assert_amount(_gallons_today(agreement["id"]), 20000, "scheduled gallons today")


def _cancel(landfill_id, shipment_id, gate_reason="Tanker reassigned to a different site."):
    return get_success_data(
        api_client.cancel_leachate_shipment(
            shipment_id, {"gate_reason": gate_reason}, make_site_operator_headers(landfill_id)
        )
    )


def _morning_slot_reused(landfill, agreement, hauls):
    """Cancel the 10:00 haul and rebook its gallons into [09:00, 11:00)."""
    _cancel(landfill["id"], hauls["w2"]["id"])
    return get_success_data(
        _book(
            landfill["id"],
            agreement["id"],
            4000,
            "2026-08-01T09:00:00Z",
            "2026-08-01T11:00:00Z",
        )
    )


def test_cancelling_a_haul_releases_both_its_slot_and_its_gallons():
    """The freed 4,000 gallons are rebookable into a window that was previously full.

    PRD: "Cancellation before dispatch takes the shipment `SCHEDULED → CANCELLED`, also
    terminal, also recording a `gate_reason`, and compensates the booking exactly:
    `scheduled_gallons_today` is recomputed and falls by exactly this shipment's `gallons`,
    restoring the pre-booking total, with both `version` counters incremented by 1."

    Design: Difficulty/resource_temporal_overlap/leachate_slot_occupancy_is_half_open_and_survives_state_changes
    """
    landfill, agreement, hauls = _contract_booked_to_the_daily_cap()

    cancelled = _cancel(landfill["id"], hauls["w2"]["id"])

    assert cancelled["status"] == "CANCELLED"
    assert_amount(_gallons_today(agreement["id"]), 16000, "scheduled gallons today")

    rebooked = get_success_data(
        _book(
            landfill["id"],
            agreement["id"],
            4000,
            "2026-08-01T09:00:00Z",
            "2026-08-01T11:00:00Z",
        )
    )

    assert rebooked["status"] == "SCHEDULED"
    assert_amount(_gallons_today(agreement["id"]), 20000, "scheduled gallons today")


def test_a_dispatched_haul_still_occupies_its_slot_and_its_gallons():
    """Sending the tanker out moves no gallons and frees no room at the gate.

    PRD: "Dispatch takes it `SCHEDULED → DISPATCHED`, records the tanker's `hauler_ref` and
    increments `version` by 1; the agreement must be `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`,
    and `scheduled_gallons_today` is unchanged because a dispatched shipment still occupies
    its gallons."

    Design: Difficulty/resource_temporal_overlap/leachate_slot_occupancy_is_half_open_and_survives_state_changes
    """
    landfill, agreement, hauls = _contract_booked_to_the_daily_cap()
    _morning_slot_reused(landfill, agreement, hauls)

    dispatched = fixtures.dispatch_shipment(landfill["id"], hauls["w1"]["id"], "TNK-9")

    assert dispatched["status"] == "DISPATCHED"
    assert_amount(_gallons_today(agreement["id"]), 20000, "scheduled gallons today")

    response = _book(
        landfill["id"], agreement["id"], 1000, "2026-08-01T08:30:00Z", "2026-08-01T09:30:00Z"
    )

    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)


def test_a_terminal_rejection_releases_the_slot_the_dispatch_kept():
    """The very payload the dispatched haul blocked is accepted once it is turned away.

    PRD: "Shipments that reached `CANCELLED` or `REJECTED_AT_GATE` release both their slot
    and their gallons and participate in neither gate."

    Design: Difficulty/resource_temporal_overlap/leachate_slot_occupancy_is_half_open_and_survives_state_changes
    """
    landfill, agreement, hauls = _contract_booked_to_the_daily_cap()
    _morning_slot_reused(landfill, agreement, hauls)
    fixtures.dispatch_shipment(landfill["id"], hauls["w1"]["id"], "TNK-9")
    blocked = _book(
        landfill["id"], agreement["id"], 1000, "2026-08-01T08:30:00Z", "2026-08-01T09:30:00Z"
    )
    validate_error(blocked, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)

    rejected = get_success_data(
        api_client.reject_leachate_at_gate(
            hauls["w1"]["id"],
            {"gate_reason": "Load failed the POTW pretreatment screen."},
            make_site_operator_headers(landfill["id"]),
        )
    )

    assert rejected["status"] == "REJECTED_AT_GATE"
    assert_amount(_gallons_today(agreement["id"]), 12000, "scheduled gallons today")

    replay = get_success_data(
        _book(
            landfill["id"],
            agreement["id"],
            1000,
            "2026-08-01T08:30:00Z",
            "2026-08-01T09:30:00Z",
        )
    )

    assert replay["status"] == "SCHEDULED"
    assert_amount(_gallons_today(agreement["id"]), 13000, "scheduled gallons today")
    assert_amount(rejected["gallons"], 8000, "rejected haul gallons")
    cancelled = get_success_data(
        api_client.get_leachate_shipment(hauls["w2"]["id"], ENV_MANAGER)
    )
    assert cancelled["status"] == "CANCELLED"
    assert_amount(cancelled["gallons"], 4000, "cancelled haul gallons")
