"""Refusals that never reach the domain: a pagination ceiling, a backwards steam window,
tomorrow's discharge, a reused machine name, a saturated header and a double void.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_customer_headers, declare_fiber_grade, declare_tl_140,
    register_machine, register_permit, register_customer, log_reading,
    setup_run_ready_to_start, start_run, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENERGY = TEST_USERS["energy_headers"]

MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}


def _steam(consumer_kind, start, end, demand_tph, priority_rank):
    return api_client.create_steam_allocation(
        {"consumer_kind": consumer_kind, "consumer_ref_id": None,
         "window_start": start, "window_end": end, "demand_tph": demand_tph,
         "priority_rank": priority_rank}, ENERGY)


def test_asking_for_one_page_past_the_ceiling_is_a_pagination_error():
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, has a minimum accepted
    value of 1 and a maximum accepted value of 100."
    PRD §2.3: "A `limit` outside the range of 1 through 100 inclusive, or an `offset` that is
    negative or not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_limit_above_one_hundred_is_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)

    response = api_client.list_fiber_grades(BUYER, {"limit": 101})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    assert response.json()["response_type"] == "error", \
        "an over-wide page is refused outright, not clamped to a hundred rows"
    at_the_ceiling = api_client.list_fiber_grades(BUYER, {"limit": 100}).json()
    assert at_the_ceiling["meta"]["total_count"] == 1


def test_a_steam_window_that_ends_before_it_opens_books_nothing():
    """PRD §3.8: "`window_end` must be strictly after `window_start`, failing which the
    request is rejected with `ERR_INVALID_WINDOW`, and `window_start` may not precede the
    logical clock instant, failing which it is rejected with `ERR_DATE_OUT_OF_RANGE` (HTTP
    422)."
    PRD §3.8: "An allocation's `status` begins as `REQUESTED` and is resolved by the dispatch
    below to `GRANTED` or `CURTAILED` before the response is returned."

    Design: Corner/errors/steam_window_ending_before_it_starts_is_unprocessable
    """
    set_clock("2026-08-01T00:00:00Z")

    response = _steam("EVAPORATOR", "2026-08-01T12:00:00Z", "2026-08-01T06:00:00Z",
                      40.000, 2)
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

    assert api_client.list_steam_allocations(ENERGY).json()["meta"]["total_count"] == 0, \
        "the waterfall never ran, so the header stays uncommitted"


def test_tomorrows_discharge_cannot_be_logged_today():
    """PRD §3.7: "A `reading_date` later than the logical clock's current calendar date is
    rejected with `ERR_DATE_OUT_OF_RANGE` (HTTP 422) — the mill cannot log tomorrow's
    discharge."
    PRD §3.7: "If the permit has no non-voided readings at all, `rolling_bod_kg_per_day` and
    `rolling_tss_kg_per_day` are 0.000, `exceedance_day_count` is 0, and the posture is
    `COMPLIANT`."

    Design: Corner/errors/a_reading_dated_after_the_logical_clock_is_out_of_range
    """
    set_clock("2026-08-01T00:00:00Z")
    permit = register_permit(**MILL_PERMIT)

    response = api_client.create_effluent_reading(
        permit["id"], {"reading_date": "2026-08-02", "flow_m3": 100.00,
                       "bod_kg": 10.00, "tss_kg": 5.00}, ENV)
    validate_error(response, ApiErrorId.ERR_DATE_OUT_OF_RANGE.value, 422)

    untouched = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert untouched["rolling_bod_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert untouched["exceedance_day_count"] == 0
    assert untouched["compliance_posture"] == "COMPLIANT"
    listing = api_client.list_permit_readings(permit["id"], ENV).json()
    assert listing["meta"]["total_count"] == 0


def test_a_second_machine_may_not_borrow_the_first_ones_name():
    """PRD §3.4: "A `MillPlanner` registers each paper machine with a `name` of 1 to 20
    characters that must be unique across the mill, a `wire_width_mm` trimmed deckle width
    from 1000 through 8000 that caps how wide any roll slit on that machine may be, a
    nameplate `max_tons_per_hour` greater than zero at two decimal places, a
    `changeover_buffer_minutes` idle buffer from 0 through 240 that must separate two run
    windows on that machine, and a `steam_tph_per_ton` figure greater than zero at three
    decimal places describing how many tonnes per hour of steam the machine draws per
    production ton."
    PRD §2.7: "Uniqueness collisions on business keys — a duplicate `grade_code`,
    `product_code`, machine `name`, `permit_number`, `manifest_number`, a duplicate
    `rank_order`, or a second non-voided reading for the same permit and `reading_date` —
    yield `ERR_DUPLICATE_KEY` (HTTP 409)."

    Design: Corner/errors/reusing_a_machine_name_hits_the_uniqueness_guard
    """
    first = register_machine(name="PM1", wire_width_mm=5600, max_tons_per_hour=20.00,
                             changeover_buffer_minutes=30, steam_tph_per_ton=2.500)

    response = api_client.create_paper_machine(
        {"name": "PM1", "wire_width_mm": 4200, "max_tons_per_hour": 12.00,
         "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.800}, PLANNER)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

    kept = get_success_data(api_client.get_paper_machine(first["id"], PLANNER))
    assert kept["wire_width_mm"] == 5600
    assert kept["changeover_buffer_minutes"] == 30
    assert kept["version"] == first["version"], \
        "the name is the business key; the losing row wrote nothing"


def test_a_header_already_fully_committed_refuses_the_overlapping_dribble():
    """PRD §3.8: "The dispatch is a priority waterfall over the header's total capacity of
    180.000 tonnes per hour."
    PRD §3.8: "If the remaining headroom is 0.000 or less, the request is rejected with
    `ERR_STEAM_HEADER_SATURATED` (HTTP 409)."
    PRD §3.8: "The candidate set is every allocation whose `status` is `GRANTED` or
    `CURTAILED` and whose window overlaps the requested window under the half-open test
    above."

    Design: Corner/errors/a_fully_committed_steam_header_refuses_the_next_overlapping_request
    """
    set_clock("2026-08-01T00:00:00Z")
    incumbent = validate_success(_steam("DEINK_PLANT", "2026-08-01T06:00:00Z",
                                        "2026-08-01T12:00:00Z", 180.000, 1), 201)
    assert incumbent["granted_tph"] == pytest.approx(180.000, abs=1e-6)

    response = _steam("EVAPORATOR", "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z",
                      10.000, 3)
    validate_error(response, ApiErrorId.ERR_STEAM_HEADER_SATURATED.value, 409)

    still_whole = get_success_data(
        api_client.get_steam_allocation(incumbent["id"], ENERGY))
    assert still_whole["granted_tph"] == pytest.approx(180.000, abs=1e-6)
    assert still_whole["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert still_whole["status"] == "GRANTED"
    assert api_client.list_steam_allocations(ENERGY).json()["meta"]["total_count"] == 1, \
        "a zero-tonnage CURTAILED grant is not an acceptable outcome"


def test_voiding_a_voided_reading_twice_does_not_re_run_the_recompute():
    """PRD §3.7: "A mis-recorded reading can be voided, which requires the reading's `voided`
    flag to be currently false — voiding an already-voided reading is rejected with
    `ERR_ENV_RECORD_INVALID_STATE` (HTTP 409) — and sets `voided` to true, taking the row out
    of the rolling window entirely."
    PRD §3.7: "If the permit has no non-voided readings at all, `rolling_bod_kg_per_day` and
    `rolling_tss_kg_per_day` are 0.000, `exceedance_day_count` is 0, and the posture is
    `COMPLIANT`."

    Design: Corner/errors/voiding_an_already_voided_reading_is_an_env_record_state_error
    """
    set_clock("2026-08-01T00:00:00Z")
    permit = register_permit(**MILL_PERMIT)
    reading = log_reading(permit["id"], headers=ENV, reading_date="2026-07-20",
                          flow_m3=8000.00, bod_kg=300.00, tss_kg=100.00)
    voided = validate_success(api_client.void_effluent_reading(reading["id"], ENV))
    assert voided["voided"] is True

    response = api_client.void_effluent_reading(reading["id"], ENV)
    validate_error(response, ApiErrorId.ERR_ENV_RECORD_INVALID_STATE.value, 409)

    assert get_success_data(api_client.get_effluent_reading(
        reading["id"], ENV))["voided"] is True
    quiet = get_success_data(api_client.get_effluent_permit(permit["id"], ENV))
    assert quiet["rolling_bod_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert quiet["rolling_tss_kg_per_day"] == pytest.approx(0.000, abs=1e-6)
    assert quiet["compliance_posture"] == "COMPLIANT"
    live = api_client.list_permit_readings(permit["id"], ENV, {"voided": False}).json()
    assert live["meta"]["total_count"] == 0


def test_an_order_two_hundred_millimetres_past_the_customers_envelope_is_refused():
    """PRD §3.6: "The requested specification must fit inside the customer's declared
    envelope — `roll_width_mm` no greater than the customer's `max_roll_width_mm`,
    `roll_diameter_mm` no greater than the customer's `max_roll_diameter_mm`, and `wrap_spec`
    exactly equal to the customer's `wrap_spec` — and a request outside that envelope is
    rejected with `ERR_CUSTOMER_SPEC_VIOLATION` (HTTP 422)."
    PRD §3.6: "A new order opens in `SUBMITTED` with `allocated_tons` of 0.000,
    `shipped_tons` of 0.000, `shortfall_tons` equal to its `ordered_tons`,
    `deschedule_count` of 0, `scheduled_run_id` null, and `version` of 1."

    Design: Corner/errors/an_order_wider_than_the_customers_envelope_is_refused
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    customer = register_customer(name="Great Lakes Converting",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    headers = make_customer_headers(customer["id"])

    response = api_client.create_customer_order(
        {"customer_id": customer["id"], "product_code": "TL_140",
         "ordered_tons": 10.00, "requested_ship_date": "2026-09-10T00:00:00Z",
         "roll_width_mm": 2600, "roll_diameter_mm": 1300,
         "wrap_spec": "KRAFT_ONLY"}, headers)
    validate_error(response, ApiErrorId.ERR_CUSTOMER_SPEC_VIOLATION.value, 422)

    assert api_client.list_customer_orders(headers).json()["meta"]["total_count"] == 0, \
        "2600 mm is a legal field value and still too wide for this converter"


def test_a_slit_wider_than_the_trimmed_deckle_cannot_come_off_the_winder():
    """PRD §3.6: "The set's `slit_width_mm` may not exceed the producing machine's
    `wire_width_mm`, and a wider slit is rejected with `ERR_WIDTH_EXCEEDS_DECKLE` (HTTP 409) —
    a rule that applies equally when a set is wrapped and when a rewind is completed."
    PRD §3.6: "A new set opens in `WOUND` with `rewind_count` of 0, `quarantine_reason` null,
    and `allocated_order_id` null, and its creation recomputes the run's `produced_tons`."

    Design: Corner/errors/a_roll_set_wider_than_the_deckle_cannot_be_wound
    """
    bundle = setup_run_ready_to_start(
        machine_overrides={"name": "PM2", "wire_width_mm": 1000,
                           "max_tons_per_hour": 20.00,
                           "changeover_buffer_minutes": 30,
                           "steam_tph_per_ton": 2.500},
        run_overrides={"pulp_draw_tons": 15.000})
    start_run(bundle["machine"]["id"], bundle["run"]["id"])

    response = api_client.create_roll_set(
        bundle["run"]["id"], {"slit_width_mm": 2200, "diameter_mm": 1400,
                              "roll_count": 4, "net_tons": 5.000},
        TEST_USERS["operator_headers"])
    validate_error(response, ApiErrorId.ERR_WIDTH_EXCEEDS_DECKLE.value, 409)

    still_running = get_success_data(
        api_client.get_run(bundle["run"]["id"], PLANNER))
    assert still_running["run_status"] == "RUNNING"
    assert still_running["produced_tons"] == pytest.approx(0.000, abs=1e-6)
    assert api_client.list_roll_sets(
        PLANNER, {"production_run_id": bundle["run"]["id"]}
    ).json()["meta"]["total_count"] == 0
