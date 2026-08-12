"""Day-route construction: stop geometry, buffers, ceilings and route states."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    arrive_stop,
    assert_route_time_partition,
    assert_same_instant,
    complete_route,
    depart_stop,
    dispatch_route,
    make_field_tech_headers,
    new_clinic,
    new_mobile_unit,
    new_route,
    new_technician,
    publish_route,
    route_version,
    set_clock,
    set_service_status,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# --------------------------------------------------------------------------
# Stop geometry — rung 40
# --------------------------------------------------------------------------
def test_stop_reserving_fewer_than_fifteen_service_minutes_is_refused(api):
    """PRD §3.3: "A routine stop must reserve at least 15 minutes."
    PRD §2.8 rung 40: "Internal order: first, a payload `service_minutes` below 15 raises
    `ERR_STOP_SERVICE_MINUTES_TOO_SHORT` (422) — this limb inspects the value the
    client supplied, even on a STAT stop whose effective service time was overridden"

    Design: Corner/validations/stop_service_minutes_below_the_floor_returns_too_short
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Short Stop Vet", "V1")
    unit = new_mobile_unit("Van V1")
    technician = new_technician("T One", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])

    response = api.add_route_stop(
        route["id"],
        {
            "clinic_id": clinic["id"],
            "planned_arrival_minute": 540,
            "service_minutes": 10,
            "drive_minutes_from_prev": 5,
            "stop_priority": "ROUTINE",
            "expected_route_version": route["version"],
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_STOP_SERVICE_MINUTES_TOO_SHORT.value)
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 0


def test_stop_running_past_the_shift_end_is_refused(api):
    """PRD §3.3: "**Second**, the stop's window — from its `planned_arrival_minute` up
    to but excluding that minute plus its effective service minutes — must sit wholly
    inside the route's shift window, or `ERR_STOP_OUTSIDE_SHIFT_WINDOW` is raised."

    Derivation: arrival 880 plus 30 reserved service minutes ends at minute 910,
    which is past the route's shift_end_minute of 900.

    Design: Corner/validations/stop_running_past_the_shift_end_returns_outside_shift_window
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Overrun Vet", "V2")
    unit = new_mobile_unit("Van V2")
    technician = new_technician("T Two", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"], shift_start_minute=480, shift_end_minute=900)

    response = api.add_route_stop(
        route["id"],
        {
            "clinic_id": clinic["id"],
            "planned_arrival_minute": 880,
            "service_minutes": 30,
            "drive_minutes_from_prev": 5,
            "stop_priority": "ROUTINE",
            "expected_route_version": route["version"],
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_STOP_OUTSIDE_SHIFT_WINDOW.value)
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 0


# --------------------------------------------------------------------------
# Buffer-expanded interval conflict — difficulty instance
# --------------------------------------------------------------------------
def _route_with_one_stop_540_to_585(api):
    set_clock("2026-05-04T08:00:00Z")
    first_clinic = new_clinic("Clinic P1", "Z16")
    second_clinic = new_clinic("Clinic P2", "Z16")
    unit = new_mobile_unit("Van P")
    technician = new_technician("Dov Klein", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], first_clinic["id"], planned_arrival_minute=540,
                    service_minutes=45, drive_minutes_from_prev=20)
    return route, stop, second_clinic


def test_a_nine_minute_gap_between_stops_is_a_window_conflict(api):
    """PRD §3.3: "**Third**, that window, expanded by a 10-minute buffer on **both**
    sides, must not overlap the window of any other counted stop on the same route; a
    proposed stop conflicts with an existing stop exactly when the proposed start is
    earlier than the existing end plus 10 minutes **and** the existing start is
    earlier than the proposed end plus 10 minutes, and the collision reports
    `ERR_STOP_WINDOW_CONFLICT`."

    Derivation: the existing stop occupies minutes 540 through 585. A proposal at 594
    for 20 minutes runs 594..614. 594 < 585 + 10 = 595 and 540 < 614 + 10 = 624, so
    both limbs hold and the proposal conflicts.

    Design: Difficulty/resource_temporal_overlap/route_stop_buffer_expanded_minute_interval_conflict
    """
    route, _, second_clinic = _route_with_one_stop_540_to_585(api)

    response = api.add_route_stop(
        route["id"],
        {
            "clinic_id": second_clinic["id"],
            "planned_arrival_minute": 594,
            "service_minutes": 20,
            "drive_minutes_from_prev": 5,
            "stop_priority": "ROUTINE",
            "expected_route_version": route_version(route["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_STOP_WINDOW_CONFLICT.value)
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 1


def test_a_ten_minute_gap_between_stops_is_accepted_and_resequenced(api):
    """PRD §3.3: "A gap of exactly 10 minutes between one stop's end and the next
    stop's start is legal; a gap of 9 minutes is a conflict."
    PRD §3.3: "After every stop insert, bump, cancel or arrival, the route's counted
    stops are ordered by `planned_arrival_minute` ascending, ties broken by
    `created_at` ascending, and numbered 1, 2, 3 and so on in that order."
    PRD §3.3: "`planned_occupied_minutes` sums `drive_minutes_from_prev` plus the
    reserved `service_minutes` over counted stops."

    Derivation: the existing stop ends at 585; a proposal at 595 leaves exactly a
    10-minute gap, so 595 < 585 + 10 = 595 is false and the first conflict limb fails.
    planned_occupied_minutes is then (20 + 45) + (5 + 20) = 90.

    Design: Difficulty/resource_temporal_overlap/route_stop_buffer_expanded_minute_interval_conflict
    """
    route, _, second_clinic = _route_with_one_stop_540_to_585(api)

    created = validate_success(
        api.add_route_stop(
            route["id"],
            {
                "clinic_id": second_clinic["id"],
                "planned_arrival_minute": 595,
                "service_minutes": 20,
                "drive_minutes_from_prev": 5,
                "stop_priority": "ROUTINE",
                "expected_route_version": route_version(route["id"]),
            },
            SCHED,
        ),
        expected_status=201,
    )

    assert created["sequence"] == 2
    assert created["planned_arrival_minute"] == 595
    route_after = validate_success(api.get_route(route["id"], SCHED))
    assert route_after["stop_count"] == 2
    assert route_after["planned_occupied_minutes"] == 90
    assert_route_time_partition(route_after)


# --------------------------------------------------------------------------
# Clinic hosts at most one stop per service date — difficulty instance
# --------------------------------------------------------------------------
def _two_vans_and_three_routes(api):
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Single Visit Vet", "Z17")
    van_one = new_mobile_unit("Van S1")
    van_two = new_mobile_unit("Van S2")
    technician = new_technician("Eve Marsh", ["RADIOGRAPHY"])
    route_one = new_route(van_one["id"], technician["id"], service_date="2026-05-04")
    add_stop(route_one["id"], clinic["id"], planned_arrival_minute=500,
             service_minutes=30, drive_minutes_from_prev=10)
    route_two = new_route(van_two["id"], technician["id"], service_date="2026-05-04")
    route_three = new_route(van_two["id"], technician["id"], service_date="2026-05-05")
    return clinic, route_two, route_three


def test_a_clinic_cannot_host_a_second_stop_on_the_same_service_date(api):
    """PRD §3.3: "**Fourth**, a clinic may host at most one counted route stop per
    `service_date`, and that uniqueness spans **every route and every mobile unit**,
    not just this one."
    PRD §2.8 rung 42: "Clinic already scheduled that day** — the clinic must not already host a counted
    route stop on the same `service_date`, across every route and every mobile unit,
    otherwise `ERR_CLINIC_STOP_ALREADY_SCHEDULED` (409)."

    Derivation: the clinic's existing stop occupies 500..530 on van S1; the proposal
    at 800..830 on van S2 does not overlap in minutes at all, yet the rule is
    day-granular and refuses it.

    Design: Difficulty/resource_temporal_overlap/clinic_hosts_at_most_one_stop_per_service_date_across_all_routes
    """
    clinic, route_two, _ = _two_vans_and_three_routes(api)

    response = api.add_route_stop(
        route_two["id"],
        {
            "clinic_id": clinic["id"],
            "planned_arrival_minute": 800,
            "service_minutes": 30,
            "drive_minutes_from_prev": 10,
            "stop_priority": "ROUTINE",
            "expected_route_version": route_two["version"],
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_CLINIC_STOP_ALREADY_SCHEDULED.value)
    assert validate_success(api.get_route(route_two["id"], SCHED))["stop_count"] == 0


def test_the_same_clinic_is_accepted_immediately_on_the_next_service_date(api):
    """PRD §3.3: "This last rule uses whole-calendar-day granularity with no buffer
    and no minute arithmetic at all — deliberately different interval semantics from
    the buffered minute overlap above — and a collision reports
    `ERR_CLINIC_STOP_ALREADY_SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/clinic_hosts_at_most_one_stop_per_service_date_across_all_routes
    """
    clinic, _, route_three = _two_vans_and_three_routes(api)

    created = validate_success(
        api.add_route_stop(
            route_three["id"],
            {
                "clinic_id": clinic["id"],
                "planned_arrival_minute": 800,
                "service_minutes": 30,
                "drive_minutes_from_prev": 10,
                "stop_priority": "ROUTINE",
                "expected_route_version": route_three["version"],
            },
            SCHED,
        ),
        expected_status=201,
    )

    assert created["clinic_id"] == clinic["id"]
    rows, _meta = validate_paginated(api.list_route_stops(SCHED, params={"clinic_id": clinic["id"]}))
    assert len(rows) == 2


# --------------------------------------------------------------------------
# Two independent ceilings with the buffer allowance — difficulty instance
# --------------------------------------------------------------------------
def _short_shift_van_with_two_stops(api):
    set_clock("2026-05-04T08:00:00Z")
    clinic_one = new_clinic("Clinic B1", "Z4")
    clinic_two = new_clinic("Clinic B2", "Z4")
    clinic_three = new_clinic("Clinic B3", "Z4")
    unit = new_mobile_unit("Van Short-Shift", max_stops=5, max_shift_minutes=120)
    technician = new_technician("Kit Marsh", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"], shift_start_minute=480, shift_end_minute=900)
    add_stop(route["id"], clinic_one["id"], planned_arrival_minute=480,
             service_minutes=45, drive_minutes_from_prev=10)
    add_stop(route["id"], clinic_two["id"], planned_arrival_minute=540,
             service_minutes=45, drive_minutes_from_prev=10)
    return route, clinic_three


def test_the_minute_ceiling_admits_a_stop_that_lands_exactly_on_the_budget(api):
    """PRD §3.3: "The buffer allowance is 10 minutes multiplied by one fewer than that
    prospective count, or zero if that would be negative. The minute budget is the
    **smaller** of the route's own shift span and the van's `max_shift_minutes`."
    PRD §3.3: "Both ceilings admit equality — a route may sit exactly on either
    limit."

    Derivation: each stop costs 10 drive + 45 service = 55 minutes. After the second
    insert the occupied total is 110 and the buffer allowance is 10 x (2 - 1) = 10, so
    110 + 10 = 120, exactly the budget min(420, 120) = 120. Equality is admitted, so
    both stops stand and slack is 420 - 110 = 310.

    Design: Difficulty/combinatorial_formula/route_capacity_two_independent_ceilings_with_buffer_allowance
    """
    route, _ = _short_shift_van_with_two_stops(api)

    route_after = validate_success(api.get_route(route["id"], SCHED))

    assert route_after["stop_count"] == 2
    assert route_after["planned_occupied_minutes"] == 110
    assert route_after["slack_minutes"] == 310
    assert_route_time_partition(route_after)


def test_the_minute_ceiling_refuses_the_third_stop_while_the_count_ceiling_is_slack(api):
    """PRD §3.3: "The count test passes when the prospective count is at most the van's
    `max_stops`; the minute test passes when the current occupied minutes plus the
    proposed load plus the buffer allowance is at most the budget."
    PRD §3.3: "When one fails and the proposed stop is `ROUTINE`, the insertion is
    refused — with `ERR_ROUTE_STOP_CAP_EXCEEDED` if the count test was the one that
    failed, otherwise `ERR_ROUTE_SHIFT_MINUTES_EXCEEDED`."

    Derivation: occupied 110, proposed load 15 service + 5 drive = 20, prospective
    count 3 so the buffer allowance is 10 x 2 = 20. 110 + 20 + 20 = 150 exceeds the
    budget of 120, while the count test (3 <= max_stops 5) still passes, so the
    minute code is the one reported.

    Design: Difficulty/combinatorial_formula/route_capacity_two_independent_ceilings_with_buffer_allowance
    """
    route, clinic_three = _short_shift_van_with_two_stops(api)

    response = api.add_route_stop(
        route["id"],
        {
            "clinic_id": clinic_three["id"],
            "planned_arrival_minute": 700,
            "service_minutes": 15,
            "drive_minutes_from_prev": 5,
            "stop_priority": "ROUTINE",
            "expected_route_version": route_version(route["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_ROUTE_SHIFT_MINUTES_EXCEEDED.value)
    route_after = validate_success(api.get_route(route["id"], SCHED))
    assert route_after["stop_count"] == 2
    assert route_after["planned_occupied_minutes"] == 110


def test_a_fourth_routine_stop_breaches_the_vans_stop_count_ceiling(api):
    """PRD §3.1: "`max_stops`, the hard ceiling on how many non-cancelled, non-bumped
    stops one day route on this van may carry, which defaults to 3 and must be at
    least 1"
    PRD §2.8 rung 43: "Route stop-count ceiling**, otherwise `ERR_ROUTE_STOP_CAP_EXCEEDED` (409). For a
    STAT stop this rung fires only after the bump fallback has been exhausted."

    Design: Corner/errors/route_stop_cap_and_repeat_cap_both_refuse_the_one_past_the_limit
    """
    set_clock("2026-05-04T08:00:00Z")
    clinics = [new_clinic(f"Cap Vet {n}", "S8") for n in range(1, 5)]
    unit = new_mobile_unit("Van Cap")
    technician = new_technician("T Cap", ["ULTRASOUND"])
    route = new_route(unit["id"], technician["id"])
    for clinic, arrival in zip(clinics[:3], (500, 540, 580)):
        add_stop(route["id"], clinic["id"], planned_arrival_minute=arrival,
                 service_minutes=20, drive_minutes_from_prev=5)
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 3

    response = api.add_route_stop(
        route["id"],
        {
            "clinic_id": clinics[3]["id"],
            "planned_arrival_minute": 620,
            "service_minutes": 20,
            "drive_minutes_from_prev": 5,
            "stop_priority": "ROUTINE",
            "expected_route_version": route_version(route["id"]),
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_ROUTE_STOP_CAP_EXCEEDED.value)
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 3


# --------------------------------------------------------------------------
# Optimistic concurrency on the route
# --------------------------------------------------------------------------
def test_a_second_stop_insert_carrying_the_pre_insert_route_version_is_refused(api):
    """PRD §2.7: "Inserting a stop into a route (`POST /routes/{route_id}/stops`)
    requires `expected_route_version`, matched against the target `Route`'s current
    `version`."
    PRD §2.7: "If the supplied value does not equal the parent record's current
    `version` at the moment the request is processed, the write is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_on_second_stop_insert_returns_412
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic_one = new_clinic("OCC Vet 1", "O1")
    clinic_two = new_clinic("OCC Vet 2", "O1")
    unit = new_mobile_unit("Van O1")
    technician = new_technician("T O1", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stale_version = route["version"]
    add_stop(route["id"], clinic_one["id"], planned_arrival_minute=500,
             service_minutes=20, drive_minutes_from_prev=5,
             expected_route_version=stale_version)

    response = api.add_route_stop(
        route["id"],
        {
            "clinic_id": clinic_two["id"],
            "planned_arrival_minute": 560,
            "service_minutes": 20,
            "drive_minutes_from_prev": 5,
            "stop_priority": "ROUTINE",
            "expected_route_version": stale_version,
        },
        SCHED,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 1
    rows, _ = validate_paginated(api.list_route_stops(SCHED, params={"clinic_id": clinic_two["id"]}))
    assert rows == []


# --------------------------------------------------------------------------
# Route state machine
# --------------------------------------------------------------------------
def test_publishing_a_route_with_no_stops_is_refused(api):
    """PRD §3.3: "Publishing takes it `DRAFT → PUBLISHED`, requires the van to be
    `IN_SERVICE` (gate G3) and requires at least one stop — publishing an empty route
    is refused with `ERR_ROUTE_HAS_NO_STOPS`."

    Design: Corner/validations/publishing_a_route_with_no_stops_returns_has_no_stops
    """
    set_clock("2026-05-04T08:00:00Z")
    unit = new_mobile_unit("Van V3")
    technician = new_technician("T Three", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])

    response = api.publish_route(route["id"], SCHED)

    validate_error(response, ApiErrorId.ERR_ROUTE_HAS_NO_STOPS.value)
    after = validate_success(api.get_route(route["id"], SCHED))
    assert after["status"] == "DRAFT"
    assert after["published_at"] is None


def test_unpublishing_returns_a_published_route_to_draft_and_it_may_republish(api):
    """PRD §3.3: "Unpublishing takes it `PUBLISHED → DRAFT`, clears `published_at`
    back to null, and is refused while any stop on the route is `EN_ROUTE`, `ARRIVED`
    or `SERVICED`."
    PRD §3.3: "This unpublish edge is what makes the route axis non-linear: a route
    may be republished any number of times."
    PRD §3.3: "Publication stamps `published_at` with the logical clock and refreshes
    `stop_count`, `planned_occupied_minutes` and `slack_minutes`."

    Design: Corner/state_machines/route_unpublish_returns_a_published_route_to_draft
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Cycle Vet", "ZL")
    unit = new_mobile_unit("Van L")
    technician = new_technician("Tor Lund", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=30, drive_minutes_from_prev=10)
    published = publish_route(route["id"])
    assert_same_instant(published["published_at"], "2026-05-04T08:00:00Z")

    unpublished = validate_success(api.unpublish_route(route["id"], SCHED))
    assert unpublished["status"] == "DRAFT"
    assert unpublished["published_at"] is None

    republished = validate_success(api.publish_route(route["id"], SCHED))
    assert republished["status"] == "PUBLISHED"
    assert validate_success(api.get_route_stop(stop["id"], SCHED))["status"] == "PLANNED"
    assert validate_success(api.get_route(route["id"], SCHED))["stop_count"] == 1


def test_arrive_checks_the_route_state_before_the_stop_state(api):
    """PRD §3.4: "Arriving at a stop moves it `EN_ROUTE → ARRIVED`, requires the owning
    route to be `DISPATCHED` and the acting technician to be that route's
    `technician_id`, stamps `arrived_at` with the logical clock, and fans out to move
    every appointment on that stop whose `status` is `SCHEDULED` to `IN_PROGRESS`."
    PRD §2.8 rung 17: "Internal order: the route is checked before its stop. A route in
    a from-state that does not admit the transition raises `ERR_ROUTE_INVALID_STATE`
    (409); a stop in such a state raises `ERR_STOP_INVALID_STATE` (409)."

    Design: Corner/state_machines/arrive_on_a_planned_stop_before_dispatch_returns_stop_invalid_state
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Early Arrive Vet", "ZA")
    unit = new_mobile_unit("Van A2")
    technician = new_technician("Pat Nam", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=30, drive_minutes_from_prev=10)
    publish_route(route["id"])

    # Route is PUBLISHED (arrive admits only DISPATCHED) and the stop is PLANNED
    # (arrive admits only EN_ROUTE): both limbs fail, and rung 17 names the route
    # limb as the one that is checked first.
    response = api.arrive_stop(stop["id"], make_field_tech_headers(technician["id"]))

    validate_error(response, ApiErrorId.ERR_ROUTE_INVALID_STATE.value)
    after = validate_success(api.get_route_stop(stop["id"], SCHED))
    assert after["status"] == "PLANNED"
    assert after["arrived_at"] is None

    # With the route DISPATCHED the route limb passes, isolating the stop limb: an
    # already-ARRIVED stop is in a from-state that does not admit the transition.
    dispatch_route(route["id"], technician["id"])
    arrived = arrive_stop(stop["id"], technician["id"])
    assert arrived["status"] == "ARRIVED"

    repeat = api.arrive_stop(stop["id"], make_field_tech_headers(technician["id"]))

    validate_error(repeat, ApiErrorId.ERR_STOP_INVALID_STATE.value)
    unchanged = validate_success(api.get_route_stop(stop["id"], SCHED))
    assert unchanged["status"] == "ARRIVED"
    assert_same_instant(unchanged["arrived_at"], arrived["arrived_at"])


def test_a_completed_route_freezes_every_later_write_against_its_stops(api):
    """PRD §2.9: "**G5 — the completed-route freeze (`ERR_ROUTE_FROZEN`, 409).** Once a
    `Route`'s `status` becomes `COMPLETED`, no write against that route or any of its
    stops is accepted. Eight operations are guarded: `POST /routes/{route_id}/stops`,
    `/publish`, `/unpublish`, `/dispatch` and `/complete`, plus `POST
    /route-stops/{stop_id}/arrive`, `/depart` and `/cancel`."
    PRD §3.3: "Completing takes it `DISPATCHED → COMPLETED`, is likewise the staffing
    technician's action, is refused while any stop is still `EN_ROUTE` or `ARRIVED`,
    stamps `completed_at` and recomputes `actual_occupied_minutes` from the serviced
    stops."

    Design: Corner/state_machines/completed_route_freezes_every_later_stop_write
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Frozen Vet", "ZF")
    unit = new_mobile_unit("Van F")
    technician = new_technician("Gil Roth", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=30, drive_minutes_from_prev=10)
    publish_route(route["id"])
    dispatch_route(route["id"], technician["id"])
    arrive_stop(stop["id"], technician["id"])
    set_clock("2026-05-04T09:25:00Z")
    depart_stop(stop["id"], technician["id"])
    complete_route(route["id"], technician["id"])

    response = api.cancel_stop(stop["id"], {"cancel_reason": "too late"}, SCHED)

    validate_error(response, ApiErrorId.ERR_ROUTE_FROZEN.value)
    route_after = validate_success(api.get_route(route["id"], SCHED))
    assert route_after["status"] == "COMPLETED"
    assert route_after["completed_at"] is not None
    assert validate_success(api.get_route_stop(stop["id"], SCHED))["status"] == "SERVICED"


# --------------------------------------------------------------------------
# Planned versus actual occupancy — difficulty instance
# --------------------------------------------------------------------------
def _route_serviced_between_nine_and_twenty_past(api):
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Eastgate Animal Hospital", "Z2")
    unit = new_mobile_unit("Van 2")
    technician = new_technician("Bo Chen", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=45, drive_minutes_from_prev=20)
    publish_route(route["id"])
    dispatch_route(route["id"], technician["id"])
    set_clock("2026-05-04T09:00:00Z")
    arrive_stop(stop["id"], technician["id"])
    set_clock("2026-05-04T09:20:00Z")
    depart_stop(stop["id"], technician["id"])
    return route, stop


def test_planned_occupancy_reads_the_reservation_while_actual_reads_the_visit(api):
    """PRD §3.3: "Two occupancy figures live on a route and they disagree on identical
    data by design. `planned_occupied_minutes` sums `drive_minutes_from_prev` plus the
    reserved `service_minutes` over counted stops. `actual_occupied_minutes` sums
    `drive_minutes_from_prev` plus `actual_service_minutes` over stops whose `status`
    is `SERVICED` only."

    Derivation: one stop reserved for 45 minutes after 20 drive minutes contributes
    20 + 45 = 65 planned minutes; arrived at 09:00 and departed at 09:20 it
    contributes 20 + 20 = 40 actual minutes.

    Design: Difficulty/dual_variant_calc/route_planned_versus_actual_occupied_minutes_diverge
    """
    route, _stop = _route_serviced_between_nine_and_twenty_past(api)

    fetched = validate_success(api.get_route(route["id"], SCHED))

    assert fetched["planned_occupied_minutes"] == 65
    assert fetched["actual_occupied_minutes"] == 40
    assert fetched["stop_count"] == 1


def test_slack_is_the_shift_span_less_planned_occupancy_and_the_stop_records_its_visit(api):
    """PRD §3.3: "`slack_minutes` is always the route's shift span minus
    `planned_occupied_minutes`, and `stop_count` is simply the number of counted
    stops."
    PRD §3.4: "Departing moves the stop `ARRIVED → SERVICED`, stamps `departed_at`,
    and derives `actual_service_minutes` as the whole minutes between `arrived_at` and
    `departed_at` — a figure that reads 0 for as long as `departed_at` is null."

    Derivation: the shift span is 900 - 480 = 420 minutes and planned occupancy is 65,
    so slack is 355; arrival 09:00 to departure 09:20 is 20 whole minutes.

    Design: Difficulty/dual_variant_calc/route_planned_versus_actual_occupied_minutes_diverge
    """
    route, stop = _route_serviced_between_nine_and_twenty_past(api)

    fetched_route = validate_success(api.get_route(route["id"], SCHED))
    fetched_stop = validate_success(api.get_route_stop(stop["id"], SCHED))

    assert fetched_route["slack_minutes"] == 355
    assert_route_time_partition(fetched_route)
    assert fetched_stop["actual_service_minutes"] == 20
    assert fetched_stop["status"] == "SERVICED"
    assert_same_instant(fetched_stop["arrived_at"], "2026-05-04T09:00:00Z")
    assert_same_instant(fetched_stop["departed_at"], "2026-05-04T09:20:00Z")


# --------------------------------------------------------------------------
# Gate G3 — unit out of service — difficulty instance
# --------------------------------------------------------------------------
def _draft_route_on_a_grounded_van(api):
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Grounded Vet", "Z15")
    unit = new_mobile_unit("Van O")
    technician = new_technician("Nia Ford", ["RADIOGRAPHY"])
    route = new_route(unit["id"], technician["id"])
    stop = add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
                    service_minutes=30, drive_minutes_from_prev=15)
    set_service_status(unit["id"], "OUT_OF_SERVICE")
    return unit, route, stop


def test_publishing_is_blocked_while_the_van_is_out_of_service(api):
    """PRD §2.9: "**G3 — unit out of service (`ERR_UNIT_OUT_OF_SERVICE`, 409).** A
    route whose `MobileUnit` has a `service_status` other than `IN_SERVICE` — that is,
    `OUT_OF_SERVICE` or `MAINTENANCE` — refuses exactly three operations: `POST
    /routes/{route_id}/stops`, `POST /routes/{route_id}/publish` and `POST
    /routes/{route_id}/dispatch`."

    Design: Difficulty/cross_entity_state_dependency/route_publish_blocked_until_mobile_unit_returns_to_service
    """
    _unit, route, stop = _draft_route_on_a_grounded_van(api)

    response = api.publish_route(route["id"], SCHED)

    validate_error(response, ApiErrorId.ERR_UNIT_OUT_OF_SERVICE.value)
    assert validate_success(api.get_route(route["id"], SCHED))["status"] == "DRAFT"
    assert validate_success(api.get_route_stop(stop["id"], SCHED))["status"] == "PLANNED"


def test_returning_the_van_to_service_unblocks_the_very_same_publish(api):
    """PRD §3.1: "Its `service_status` is one of `IN_SERVICE`, `OUT_OF_SERVICE` or
    `MAINTENANCE`, defaults to `IN_SERVICE`, and is changed by a `PlatformAdmin`'s
    service-status capability carrying a `service_status` value; anything other than
    `IN_SERVICE` trips gate G3 for every route on that van."
    PRD §3.3: "Publication stamps `published_at` with the logical clock and refreshes
    `stop_count`, `planned_occupied_minutes` and `slack_minutes`."

    Design: Difficulty/cross_entity_state_dependency/route_publish_blocked_until_mobile_unit_returns_to_service
    """
    unit, route, stop = _draft_route_on_a_grounded_van(api)
    validate_error(api.publish_route(route["id"], SCHED), ApiErrorId.ERR_UNIT_OUT_OF_SERVICE.value)

    set_service_status(unit["id"], "IN_SERVICE")
    published = validate_success(api.publish_route(route["id"], SCHED))

    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None
    assert_same_instant(published["published_at"], "2026-05-04T08:00:00Z")
    assert validate_success(api.get_route_stop(stop["id"], SCHED))["status"] == "PLANNED"
