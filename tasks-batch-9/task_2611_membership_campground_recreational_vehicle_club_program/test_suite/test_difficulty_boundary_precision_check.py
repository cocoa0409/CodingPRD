"""Thresholds probed one unit either side of the boundary."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_reservation_state,
    completed_stay,
    create_classic_tier,
    create_open_park,
    create_president_tier,
    make_capital_project_payload,
    make_park_manager_headers,
    make_reservation_payload,
    read_membership,
    read_park,
    reset_clock,
    sell_membership_to_new_member,
    set_clock,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
)


def _three_classic_probes_at_one_roomy_park(api):
    """Three separate CLASSIC contracts and 24 member pads, so only the window can fire."""
    reset_clock(api)
    tier = create_classic_tier(api)
    park = create_open_park(
        api,
        name="Cedar Flats RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    probes = [
        sell_membership_to_new_member(
            api,
            tier["id"],
            member_overrides={"full_name": name, "email": email},
            upfront_paid_cents=795000,
        )
        for name, email in (
            ("Probe Fifty Nine", "p59@example.com"),
            ("Probe Sixty", "p60@example.com"),
            ("Probe Sixty One", "p61@example.com"),
        )
    ]
    return park, probes


def test_advance_window_admits_arrival_on_the_sixtieth_day(api):
    """Fifty-nine and sixty days out are both inside a sixty-day window.

    PRD §3.3: "The days until arrival — the `arrival_date` minus the current logical date, in
    whole days — must be no greater than the tier's `advance_window_days`."

    Design: Difficulty/boundary_precision_check/advance_window_day_count_exact_at_59_60_and_61_days_on_reservation_create
    """
    park, probes = _three_classic_probes_at_one_roomy_park(api)
    inside, threshold, _outside = probes

    near = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], inside["membership_id"], "2026-09-29", "2026-10-01"
            ),
            inside["headers"],
        ),
        201,
    )
    assert_reservation_state(near, "CONFIRMED", entitlement_nights_charged=2)

    exact = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], threshold["membership_id"], "2026-09-30", "2026-10-02"
            ),
            threshold["headers"],
        ),
        201,
    )
    # 2026-09-30 is exactly sixty days after the 2026-08-01 logical date.
    assert_reservation_state(exact, "CONFIRMED", entitlement_nights_charged=2)
    assert_entitlement_counters(
        read_membership(api, threshold["membership_id"]), class_b=2, annual=2
    )


def test_advance_window_refuses_arrival_on_the_sixty_first_day(api):
    """One day past the window is refused, so the comparison is not off by one.

    PRD §3.3: "At a partner-network park the effective window is the **smaller** of the tier's
    `advance_window_days` and the agreement's `advance_window_cap_days`, so a tier granting a
    full year of lead time is trimmed to whatever the partner will accept. Exceeding the
    effective window is refused with `ERR_ADVANCE_WINDOW_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/advance_window_day_count_exact_at_59_60_and_61_days_on_reservation_create
    """
    park, probes = _three_classic_probes_at_one_roomy_park(api)
    _inside, _threshold, outside = probes

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], outside["membership_id"], "2026-10-01", "2026-10-03"
        ),
        outside["headers"],
    )
    validate_error(response, "ERR_ADVANCE_WINDOW_EXCEEDED", 422)

    rows, _meta = validate_paginated(
        api.list_reservations(ADMIN, {"membership_id": outside["membership_id"]})
    )
    assert rows == [], "a refused booking leaves no reservation row behind"
    assert_entitlement_counters(
        read_membership(api, outside["membership_id"]), class_b=0, annual=0
    )


def _one_park_surveyed_once_and_one_never_surveyed(api):
    """A 2.10 survey filed on logical date 2026-08-10, plus a silent control park."""
    reset_clock(api)
    tier = create_president_tier(api)
    quiet = create_open_park(
        api,
        name="Quiet Hollow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    loud = create_open_park(
        api,
        name="Loud Creek RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Rosa Kimball", "email": "rosa@example.com"},
        upfront_paid_cents=1850000,
    )
    stay = completed_stay(
        api,
        holder["headers"],
        loud["id"],
        holder["membership_id"],
        "2026-08-08",
        "2026-08-10",
    )
    survey = submit_survey(
        api,
        stay["id"],
        holder["headers"],
        overall_rating=2,
        cleanliness_rating=3,
        staff_rating=2,
        value_rating=1,
    )
    assert survey["weighted_score"] == 2.10, "0.40*2 + 0.25*3 + 0.20*2 + 0.15*1"
    return quiet, loud


def test_trailing_window_still_holds_a_survey_at_exactly_180_days(api):
    """At 180 days the survey counts; a never-surveyed park falls back to 3.00.

    PRD §3.9: "It hard-drops every survey older than 180 days and takes the
    plain unweighted arithmetic mean of the surviving surveys' `weighted_score`
    values, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/trailing_survey_window_at_180_and_181_days_and_empty_set_fallback_on_capital_project_create
    """
    quiet, loud = _one_park_surveyed_once_and_one_never_surveyed(api)

    set_clock(api, "2027-02-06")
    inside = validate_success(
        api.create_capital_project(
            make_capital_project_payload(
                loud["id"],
                title="Loud Creek loop rewire, day 180 probe",
                category="UTILITY",
                requested_cost_cents=4500000,
                fiscal_year=2027,
            ),
            make_park_manager_headers(loud["id"]),
        ),
        201,
    )
    # 1.20 * COMPLIANT 1.00 * (1 + (4.50 - 2.10)) * (1 + 0.0000) * 1.20 * 1000
    assert inside["priority_score"] == 4896, (
        "a survey aged exactly 180 days is still inside the trailing window"
    )

    control = validate_success(
        api.create_capital_project(
            make_capital_project_payload(
                quiet["id"],
                title="Quiet Hollow loop rewire, no-survey control",
                category="UTILITY",
                requested_cost_cents=4500000,
                fiscal_year=2027,
            ),
            make_park_manager_headers(quiet["id"]),
        ),
        201,
    )
    # The empty window scores off 3.00: 1.20 * 1.00 * 2.50 * 1.0000 * 1.20 * 1000
    assert control["priority_score"] == 3600, "an unsurveyed park uses the 3.00 default"
    assert read_park(api, quiet["id"])["rating_score"] == 0.00, (
        "the stored lifetime rating of a never-surveyed park is 0.00, not the 3.00 default"
    )


def test_trailing_window_drops_a_survey_at_181_days(api):
    """One day older and the window is empty, so the 3.00 default takes over.

    PRD §3.9: "It hard-drops every survey older than 180 days and takes the plain unweighted
    arithmetic mean of the surviving surveys' `weighted_score` values, rounded half up to two
    decimal places. When the trailing window is empty it yields exactly 3.00 as its default."

    Design: Difficulty/boundary_precision_check/trailing_survey_window_at_180_and_181_days_and_empty_set_fallback_on_capital_project_create
    """
    _quiet, loud = _one_park_surveyed_once_and_one_never_surveyed(api)

    set_clock(api, "2027-02-07")
    outside = validate_success(
        api.create_capital_project(
            make_capital_project_payload(
                loud["id"],
                title="Loud Creek loop rewire, day 181 probe",
                category="UTILITY",
                requested_cost_cents=4500000,
                fiscal_year=2027,
            ),
            make_park_manager_headers(loud["id"]),
        ),
        201,
    )
    assert outside["priority_score"] == 3600, (
        "the 181-day-old survey is dropped and the 3.00 default scores the work"
    )
    assert outside["priority_score"] != 4896, (
        "an inclusive reading of the cut-off at 181 days is the wrong reading"
    )
    assert read_park(api, loud["id"])["rating_score"] == 2.10, (
        "the stored lifetime rating never drops the survey the trailing window just did"
    )
