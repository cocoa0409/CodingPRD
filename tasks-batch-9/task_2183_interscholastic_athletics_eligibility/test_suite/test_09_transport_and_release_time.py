"""Bus requests, the instructional-release ledger, and fleet capacity."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_transport_request,
    create_transport_request_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _two_trips_touching_at_the_fleet_boundary():
    """North High commits two buses to a trip returning exactly when the next departs."""
    set_clock("2026-09-10T09:00:00Z")
    north = fx.create_school(name="North High", school_day_end_utc_hhmm="17:00",
                             bus_fleet_size=2, max_release_minutes_per_request=240)
    south = fx.create_school(name="South High", region_code="R-SOUTH")
    season = fx.create_season(required_officials=1)
    fx.open_season_to_regular(season["id"])
    official = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_2")

    first_contest = fx.create_contest(season["id"], north["id"], south["id"],
                                      "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    second_contest = fx.create_contest(season["id"], south["id"], north["id"],
                                       "2026-09-20T23:15:00Z", "2026-09-21T01:15:00Z",
                                       headers=fx.make_director_headers(south["id"]))
    for contest in (first_contest, second_contest):
        assignment = fx.offer_official(contest["id"], official["id"])
        fx.respond_to_offer(assignment["id"], official["id"], "ACCEPT")

    trip_one = fx.create_transport(first_contest["id"], north["id"],
                                   travel_minutes=45, bus_count=2)
    trip_two = fx.create_transport(second_contest["id"], north["id"],
                                   travel_minutes=45, bus_count=1)
    return {"north": north, "south": south, "season": season,
            "trip_one": trip_one, "trip_two": trip_two}


def test_transport_window_and_release_minutes_are_computed_from_the_contest(api):
    """PRD §3.8: "`depart_at` is the contest's `starts_at` moved earlier by the
    travel time plus a 75-minute pre-game buffer."
    PRD §3.8: "`return_at` is the contest's `ends_at` moved later by the travel time
    plus a 30-minute post-game buffer."
    PRD §3.8: "`release_minutes` — the instructional time actually lost — is the
    number of whole minutes from `depart_at` until the end of the school's
    instructional day, where that end is the instant on `depart_at`'s own UTC
    calendar date at the requesting school's `school_day_end_utc_hhmm`."
    PRD §3.8: "The minute count truncates toward zero and is floored at 0, so a bus
    leaving at or after the end of the school day costs exactly 0 release minutes
    rather than a negative figure — and an after-hours trip like that therefore
    leaves the school's `release_minutes_used` untouched both when it is approved and
    when it is later cancelled."

    Design: Difficulty/resource_temporal_overlap/school_bus_fleet_closed_interval_counts_a_touching_trip_against_capacity
    """
    ctx = _two_trips_touching_at_the_fleet_boundary()

    approved = validate_success(
        api.approve_transport_request(ctx["trip_one"]["id"], fx.ADMIN), 200
    )

    assert_transport_request(approved)
    assert_same_instant(approved["depart_at"], "2026-09-20T16:00:00Z", "depart_at")
    assert_same_instant(approved["return_at"], "2026-09-20T21:15:00Z", "return_at")
    assert approved["release_minutes"] == 60
    assert approved["status"] == "APPROVED"
    after_hours = fx.read_transport(ctx["trip_two"]["id"])
    assert_same_instant(after_hours["depart_at"], "2026-09-20T21:15:00Z", "depart_at")
    assert after_hours["release_minutes"] == 0


def test_touching_trips_collide_on_the_closed_fleet_interval(api):
    """PRD §3.8: "The service gathers the requesting school's trips standing at
    `APPROVED` or `COMPLETED` — trips at `REQUESTED` and `CANCELLED` hold no buses —
    and keeps those that overlap this trip's window, where two trips fail to overlap
    only when one's `return_at` falls strictly before the other's `depart_at` or
    one's `depart_at` falls strictly after the other's `return_at`. If the total
    `bus_count` across the overlapping trips plus this trip's own `bus_count` would
    exceed the school's `bus_fleet_size`, the answer is
    `ERR_FLEET_CAPACITY_EXCEEDED`; the comparison is strictly greater-than, so a
    school may commit exactly its whole fleet over a single instant."
    PRD §3.8: "Then the fleet is checked, and here the interval geometry is **closed
    on both ends**, so two trips that merely touch do collide."

    Design: Difficulty/resource_temporal_overlap/school_bus_fleet_closed_interval_counts_a_touching_trip_against_capacity
    """
    ctx = _two_trips_touching_at_the_fleet_boundary()
    fx.approve_transport(ctx["trip_one"]["id"])

    response = api.approve_transport_request(ctx["trip_two"]["id"], fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_FLEET_CAPACITY_EXCEEDED.value, 409)
    assert fx.read_transport(ctx["trip_two"]["id"])["status"] == "REQUESTED"
    assert fx.read_school(ctx["north"]["id"])["release_minutes_used"] == 60


def _one_requested_trip():
    ctx = fx.setup_staffed_contest(
        home_overrides={"name": "North High", "school_day_end_utc_hhmm": "17:00",
                        "bus_fleet_size": 2, "max_release_minutes_per_request": 240},
    )
    ctx["trip"] = fx.create_transport(ctx["contest"]["id"], ctx["home"]["id"],
                                      travel_minutes=45, bus_count=1)
    return ctx


def test_approving_a_trip_adds_its_release_minutes_to_the_school_ledger(api):
    """PRD §3.8: "On approval the trip moves `REQUESTED → APPROVED` and the school's
    `release_minutes_used` increases by exactly that trip's `release_minutes`."
    PRD §3.8: "A surviving request opens at `REQUESTED` with `cancelled_reason` null,
    and the school's `release_minutes_used` is deliberately left unchanged: an
    unapproved trip commits nothing."

    Design: Difficulty/compensating_invariant/transport_approve_then_cancel_conserves_school_release_minutes
    """
    ctx = _one_requested_trip()
    assert ctx["trip"]["status"] == "REQUESTED"
    assert ctx["trip"]["cancelled_reason"] is None
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 0

    approved = validate_success(
        api.approve_transport_request(ctx["trip"]["id"], fx.ADMIN), 200
    )

    assert approved["status"] == "APPROVED"
    assert approved["release_minutes"] == 60
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 60


def test_cancelling_an_approved_trip_returns_the_ledger_to_its_pre_approval_value(
    api, admin_headers
):
    """PRD §3.8: "A trip cancelled from `APPROVED` moves to `CANCELLED` with the
    same `SCHOOL_REQUEST` reason and decrements the school's `release_minutes_used`
    by exactly that trip's `release_minutes`, so an approve-then-cancel pair leaves
    the ledger precisely where it started."
    PRD §2.9: "`release_minutes_used` must at all times equal the sum of
    `release_minutes` over that school's transport requests whose status is
    `APPROVED` or `COMPLETED`."
    PRD §2.9: "After any approve-then-cancel pair on the same trip, the school's
    `release_minutes_used` returns to precisely its pre-approval value."

    Design: Difficulty/compensating_invariant/transport_approve_then_cancel_conserves_school_release_minutes
    """
    ctx = _one_requested_trip()
    fx.approve_transport(ctx["trip"]["id"])
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 60

    cancelled = validate_success(
        api.cancel_transport_request(ctx["trip"]["id"],
                                     {"cancel_note": "opponent withdrew"},
                                     fx.make_director_headers(ctx["home"]["id"])),
        200,
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "SCHOOL_REQUEST"
    assert cancelled["release_minutes"] == 60, "the trip still reports what it once cost"
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 0
    rows, _meta = validate_paginated(
        api.list_transport_requests(admin_headers,
                                    {"requesting_school_id": ctx["home"]["id"],
                                     "limit": 100})
    )
    assert [row["status"] for row in rows] == ["CANCELLED"]


def test_release_minutes_above_the_schools_own_ceiling_are_refused(api, admin_headers):
    """PRD §3.8: "Two rejections guard the request, and per §2.6 the temporal one is
    reported first: a computed `depart_at` that falls at or before the logical clock
    is refused with `ERR_TRANSPORT_DEPARTURE_IN_PAST`, and a computed
    `release_minutes` strictly greater than the school's
    `max_release_minutes_per_request` is refused with `ERR_RELEASE_TIME_EXCEEDED`."

    Design: Corner/validations/release_minutes_above_the_schools_configured_ceiling_are_rejected
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "North High", "school_day_end_utc_hhmm": "20:30",
                        "max_release_minutes_per_request": 30, "bus_fleet_size": 4},
        season_overrides={"required_officials": 1},
        open_season=False,
    )
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")

    response = api.create_transport_request(
        create_transport_request_payload(contest["id"], ctx["home"]["id"],
                                         travel_minutes=45, bus_count=1),
        fx.make_director_headers(ctx["home"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_RELEASE_TIME_EXCEEDED.value, 409)
    rows, _meta = validate_paginated(
        api.list_transport_requests(admin_headers, {"contest_id": contest["id"]})
    )
    assert rows == []
    assert fx.read_school(ctx["home"]["id"])["release_minutes_used"] == 0


def test_a_trip_whose_departure_already_passed_is_refused(api, admin_headers):
    """PRD §3.8: "Two rejections guard the request, and per §2.6 the temporal one is
    reported first: a computed `depart_at` that falls at or before the logical clock
    is refused with `ERR_TRANSPORT_DEPARTURE_IN_PAST`, and a computed
    `release_minutes` strictly greater than the school's
    `max_release_minutes_per_request` is refused with `ERR_RELEASE_TIME_EXCEEDED`."
    PRD §2.5: "Nothing in this service reads real wall-clock time."

    Design: Corner/errors/transport_request_whose_departure_already_passed_is_rejected
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "North High", "school_day_end_utc_hhmm": "17:00",
                        "bus_fleet_size": 2},
        season_overrides={"required_officials": 1},
        open_season=False,
    )
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    fx.set_clock("2026-09-20T17:00:00Z")

    response = api.create_transport_request(
        create_transport_request_payload(contest["id"], ctx["home"]["id"],
                                         travel_minutes=45, bus_count=1),
        fx.make_director_headers(ctx["home"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TRANSPORT_DEPARTURE_IN_PAST.value, 409)
    rows, _meta = validate_paginated(
        api.list_transport_requests(admin_headers, {"contest_id": contest["id"]})
    )
    assert rows == []
