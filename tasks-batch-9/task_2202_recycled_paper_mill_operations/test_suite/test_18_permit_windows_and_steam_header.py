"""Boundaries that decide a posture and a steam grant: the permissive edge of the permit
ratios, the inclusive ends of the rolling window, and the half-open header intervals.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    register_permit, log_reading, set_clock,
)

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


def _permit_now(permit_id):
    return get_success_data(api_client.get_effluent_permit(permit_id, ENV))


def test_a_load_ratio_of_exactly_one_and_a_flow_on_the_limit_only_reach_watch():
    """PRD §3.7: "The posture is `EXCEEDANCE` when either ratio is strictly greater than
    1.00, or when `exceedance_day_count` is 2 or more."
    PRD §3.7: "The boundaries deserve care in both directions: a ratio of exactly 1.00 is
    **not** an exceedance, because the comparison is strict, so a permit sitting exactly at
    its limit lands on `WATCH`; and a `flow_m3` exactly equal to `flow_limit_m3_per_day` does
    not count as an exceedance day."
    PRD §3.7: "Logging records the acting officer's identifier as `logged_by_user_id`, and
    `voided` opens as false."

    Design: Corner/calculations/rolling_load_exactly_at_the_permit_limit_is_watch_not_exceedance
    """
    set_clock("2026-08-01T00:00:00Z", ENV)
    permit = register_permit(**MILL_PERMIT)
    log_reading(permit["id"], headers=ENV, reading_date="2026-07-15", flow_m3=8000.00,
                bod_kg=400.00, tss_kg=100.00)

    logged = validate_success(api_client.create_effluent_reading(
        permit["id"], {"reading_date": "2026-08-01", "flow_m3": 9000.00,
                       "bod_kg": 600.00, "tss_kg": 100.00}, ENV), 201)

    assert logged["voided"] is False
    assert logged["logged_by_user_id"] == "eo_1"

    posture = _permit_now(permit["id"])
    assert posture["rolling_bod_kg_per_day"] == pytest.approx(500.000, abs=1e-6)
    assert posture["rolling_tss_kg_per_day"] == pytest.approx(100.000, abs=1e-6)
    assert posture["exceedance_day_count"] == 0, \
        "a flow sitting exactly on the limit is not an exceedance day"
    assert posture["compliance_posture"] == "WATCH"


def test_the_day_just_outside_the_window_is_dropped_while_two_flow_days_trip_it():
    """PRD §3.7: "Otherwise, the window is anchored on the newest non-voided `reading_date`:
    it runs from that date backwards by the permit's `rolling_window_days` minus one, and
    **both ends are inclusive**, so a 30-day window spans exactly 30 calendar dates ending on
    the newest reading."
    PRD §3.7: "The rolling loads are averages over the readings **present** in that window:
    `rolling_bod_kg_per_day` is the sum of `bod_kg` over the window's readings divided by the
    count of those readings, rounded half up to three decimal places, and
    `rolling_tss_kg_per_day` is the same over `tss_kg`."
    PRD §3.7: "Days inside the window that carry no reading do not enter the denominator."
    PRD §3.7: "`exceedance_day_count` is the number of readings inside the window whose
    `flow_m3` is strictly greater than the permit's `flow_limit_m3_per_day`."

    Design: Corner/calculations/rolling_window_is_inclusive_at_both_ends_and_two_flow_days_force_exceedance
    """
    set_clock("2026-08-01T00:00:00Z", ENV)
    permit = register_permit(**MILL_PERMIT)
    outside = log_reading(permit["id"], headers=ENV, reading_date="2026-07-02",
                          flow_m3=9500.00, bod_kg=480.00, tss_kg=300.00)
    log_reading(permit["id"], headers=ENV, reading_date="2026-07-03", flow_m3=9500.00,
                bod_kg=100.00, tss_kg=50.00)

    validate_success(api_client.create_effluent_reading(
        permit["id"], {"reading_date": "2026-08-01", "flow_m3": 9600.00,
                       "bod_kg": 100.00, "tss_kg": 50.00}, ENV), 201)

    posture = _permit_now(permit["id"])
    assert posture["rolling_bod_kg_per_day"] == pytest.approx(100.000, abs=1e-6), \
        "the 2026-07-02 load falls one day short of the anchored window"
    assert posture["rolling_tss_kg_per_day"] == pytest.approx(50.000, abs=1e-6)
    assert posture["exceedance_day_count"] == 2
    assert posture["compliance_posture"] == "EXCEEDANCE"

    still_there = get_success_data(
        api_client.get_effluent_reading(outside["id"], ENV))
    assert still_there["voided"] is False, \
        "the older row is excluded by the window, not by voiding"


def test_the_third_consumer_is_curtailed_to_the_headers_remainder():
    """PRD §3.8: "The dispatch is a priority waterfall over the header's total capacity of
    180.000 tonnes per hour."
    PRD §3.8: "Otherwise the request is partially served: `granted_tph` equals the remaining
    headroom and `status` becomes `CURTAILED`."
    PRD §3.8: "In every granted or curtailed case, `curtailed_tph` is `demand_tph` minus
    `granted_tph`, rounded half up to three decimal places."
    PRD §3.8: "The exportable rate is 180.000 minus the consumed figure minus this
    allocation's own `granted_tph`, floored at 0.000 and rounded half up to three decimal
    places."

    Design: Corner/calculations/steam_waterfall_curtails_the_lowest_priority_request_to_the_remainder
    """
    set_clock("2026-08-01T00:00:00Z", ENERGY)
    first = validate_success(_steam("DEINK_PLANT", "2026-08-01T06:00:00Z",
                                    "2026-08-01T12:00:00Z", 100.000, 1), 201)
    second = validate_success(_steam("EVAPORATOR", "2026-08-01T06:00:00Z",
                                     "2026-08-01T12:00:00Z", 60.000, 2), 201)

    third = validate_success(_steam("EVAPORATOR", "2026-08-01T08:00:00Z",
                                    "2026-08-01T10:00:00Z", 50.000, 3), 201)

    assert third["status"] == "CURTAILED"
    assert third["granted_tph"] == pytest.approx(20.000, abs=1e-6)
    assert third["curtailed_tph"] == pytest.approx(30.000, abs=1e-6)
    assert third["cogen_credit_usd"] == pytest.approx(0.00, abs=1e-6), \
        "a fully committed header exports nothing"

    head = get_success_data(api_client.get_steam_allocation(first["id"], ENERGY))
    assert head["granted_tph"] == pytest.approx(100.000, abs=1e-6)
    assert head["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert head["status"] == "GRANTED"
    middle = get_success_data(api_client.get_steam_allocation(second["id"], ENERGY))
    assert middle["granted_tph"] == pytest.approx(60.000, abs=1e-6)
    assert middle["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert middle["status"] == "GRANTED"
    assert middle["cogen_credit_usd"] == pytest.approx(492.00, abs=1e-6)


def test_a_window_starting_where_another_ends_takes_the_whole_header():
    """PRD §3.8: "Header geometry is **half-open**: a window covers its `window_start`
    inclusively and its `window_end` exclusively."
    PRD §3.8: "Two allocations therefore overlap only when the first begins strictly before
    the second ends and ends strictly after the second begins, which means back-to-back
    allocations sharing an endpoint never contend and consume nothing from each other."
    PRD §3.8: "Otherwise, if the remaining headroom is at least the requested `demand_tph`,
    the request is granted in full: `granted_tph` equals `demand_tph` and `status` becomes
    `GRANTED`."
    PRD §3.8: "That exportable rate is then split into three marginal bands: the first band
    takes up to 30.000 tonnes per hour, the second takes up to a further 30.000, and the
    third takes everything beyond 60.000."

    Design: Corner/calculations/back_to_back_steam_windows_do_not_contend_because_the_interval_is_half_open
    """
    set_clock("2026-08-01T00:00:00Z", ENERGY)
    saturating = validate_success(_steam("DEINK_PLANT", "2026-08-01T06:00:00Z",
                                         "2026-08-01T12:00:00Z", 180.000, 1), 201)

    touching = validate_success(_steam("EVAPORATOR", "2026-08-01T12:00:00Z",
                                       "2026-08-01T18:00:00Z", 50.000, 2), 201)

    assert touching["status"] == "GRANTED"
    assert touching["granted_tph"] == pytest.approx(50.000, abs=1e-6)
    assert touching["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert touching["cogen_credit_usd"] == pytest.approx(5817.00, abs=1e-6)

    earlier = get_success_data(api_client.get_steam_allocation(saturating["id"], ENERGY))
    assert earlier["granted_tph"] == pytest.approx(180.000, abs=1e-6)
    assert earlier["cogen_credit_usd"] == pytest.approx(0.00, abs=1e-6)


def test_the_cogen_credit_rounds_each_band_before_the_three_are_added_up():
    """PRD §3.8: "The window's `duration_hours` is its length in seconds divided by 3600,
    rounded half up to four decimal places."
    PRD §3.8: "Each band's contribution is its tonnes per hour multiplied by its rate — 4.10
    dollars per tonne-per-hour-hour for the first band, 6.75 for the second, 9.20 for the
    third — multiplied by the duration in hours, and **each band's product is rounded half up
    to four decimal places before the three are summed**; `cogen_credit_usd` is that sum
    rounded half up to two decimal places."
    PRD §3.8: "This per-band-then-total rounding order is pinned: summing the three unrounded
    products and rounding once produces a different cent on fractional-hour windows and is
    not the behaviour required."

    Design: Corner/calculations/cogen_credit_rounds_each_marginal_tier_to_four_places_before_summing
    """
    set_clock("2026-08-01T00:00:00Z", ENERGY)
    validate_success(_steam("DEINK_PLANT", "2026-08-01T00:00:00Z",
                            "2026-08-01T12:00:00Z", 100.000, 1), 201)

    seventy_minutes = validate_success(_steam("EVAPORATOR", "2026-08-01T06:00:00Z",
                                              "2026-08-01T07:10:00Z", 15.000, 2), 201)

    assert seventy_minutes["status"] == "GRANTED"
    assert seventy_minutes["granted_tph"] == pytest.approx(15.000, abs=1e-6)
    assert seventy_minutes["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert seventy_minutes["cogen_credit_usd"] == pytest.approx(433.43, abs=1e-6), \
        "65.000 exported tonnes per hour over 1.1667 hours across all three bands"
