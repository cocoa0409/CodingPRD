"""Complaint workflow: auto-match, quota rollup, suspension cascade, resume."""
from test_helpers import (
    ApiErrorId,
    complaint_event,
    confirm_booking,
    create_booking,
    create_flight,
    file_complaint,
    get_booking,
    get_complaint,
    get_flight,
    get_route,
    is_valid_uuid,
    list_credits_for_booking,
    passenger_entry,
    set_clock,
    setup_completed_flight,
    setup_ops_env,
    substantiate_complaint,
    TEST_USERS,
    validate_error,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
DISP = TEST_USERS["dispatcher_headers"]
OPS = TEST_USERS["ops_admin_headers"]

VILLAGE_ROUTE = {"route_code": "RC", "noise_zones": ["VILLAGE"]}


def test_complaint_dismiss_and_close_records_note(api):
    """PRD §3.9: "The complaint workflow runs LOGGED → UNDER_REVIEW when an
    officer opens review, or LOGGED → DISMISSED when dismissed outright;
    UNDER_REVIEW can likewise fall to DISMISSED."
    PRD §3.9: "Closure records the outcome: SUBSTANTIATED → CLOSED or
    DISMISSED → CLOSED, capturing the officer's `resolution_note`."
    PRD §3.9: "The winner sets `match_status` MATCHED, `matched_flight_id` to
    the flight, and `matched_route_id` to that flight's route; an empty
    candidate set is not an error — the complaint simply lands UNMATCHED with
    `matched_flight_id` null."

    Design: Corner/state_machines/complaint_dismiss_and_close_records_note
    """
    set_clock("2026-08-03T00:00:00Z")
    from test_helpers.fixtures import create_base
    base = create_base()
    c1 = file_complaint(base["id"], "VILLAGE", "2026-08-02T10:00:00Z",
                        description="noise A")
    c2 = file_complaint(base["id"], "RIM", "2026-08-02T11:00:00Z",
                        description="noise B")
    # No flown flights exist: empty selector pool is not an error.
    assert c1["match_status"] == "UNMATCHED"
    assert c1["matched_flight_id"] is None

    reviewed = complaint_event(c1["id"], "REVIEW")
    assert reviewed["status"] == "UNDER_REVIEW"
    dismissed = complaint_event(c1["id"], "DISMISS")
    assert dismissed["status"] == "DISMISSED"
    closed = complaint_event(c1["id"], "CLOSE", resolution_note="notified operator")
    assert closed["status"] == "CLOSED"
    assert closed["resolution_note"] == "notified operator"

    # DISMISS directly from LOGGED.
    dismissed2 = complaint_event(c2["id"], "DISMISS")
    assert dismissed2["status"] == "DISMISSED"


def test_complaint_automatch_nearest_wins_window_exclusive(api):
    """PRD §3.9: "Eligible flights belong to the same base, sit in DISPATCHED
    or COMPLETED, fly a route whose `noise_zones` contain the complaint's
    `zone`, and have an overflight window — from `scheduled_departure_utc` up
    to but not including thirty minutes past `scheduled_arrival_utc` —
    containing `observed_at`."
    PRD §3.9: "Candidates rank by absolute distance between `observed_at` and
    the flight's scheduled departure, nearest first; ties break to the
    earlier scheduled departure, then the earlier `created_at`."

    Design: Corner/calculations/complaint_automatch_nearest_wins_window_exclusive
    """
    env = setup_ops_env(route_overrides=dict(VILLAGE_ROUTE))
    from test_helpers.fixtures import create_aircraft, fly_empty_flight
    a2 = create_aircraft(tail_number="N2")
    fa = create_flight(env, "2026-08-03T14:00:00Z")           # window [14:00, 14:55)
    fb = create_flight(env, "2026-08-03T14:30:00Z", aircraft=a2)  # [14:30, 15:25)
    fly_empty_flight(fa["id"], env["pilot"]["id"],
                     depart_at="2026-08-03T14:00:00Z",
                     complete_at="2026-08-03T14:25:00Z")
    fly_empty_flight(fb["id"], env["pilot"]["id"],
                     depart_at="2026-08-03T14:30:00Z",
                     complete_at="2026-08-03T14:55:00Z")

    set_clock("2026-08-03T15:30:00Z")
    # Distance 10 to FB (14:30) beats distance 40 to FA (14:00).
    c1 = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-03T14:40:00Z",
                        description="mid noise")
    assert c1["match_status"] == "MATCHED"
    assert c1["matched_flight_id"] == fb["id"]

    # 15:25 == FB's window end (14:55 + 30): half-open end exclusive.
    c2 = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-03T15:25:00Z",
                        description="edge noise")
    assert c2["match_status"] == "UNMATCHED"
    assert c2["matched_flight_id"] is None


def test_complaint_quota_window_inclusive_bounds(api):
    """PRD §3.9: "When a complaint substantiates, the matched route's
    `substantiated_complaints_30d` recomputes — the count of SUBSTANTIATED
    complaints matched to that route whose `observed_at` lies within the
    rolling window from `complaint_window_days` days ago through now, both
    bounds inclusive — and if the count now meets or exceeds the base's
    `complaint_quota_threshold`, the route flips ACTIVE → SUSPENDED and its
    cascade fires"

    Design: Corner/calculations/complaint_quota_window_inclusive_bounds
    """
    env, completed = setup_completed_flight(
        route_overrides=dict(VILLAGE_ROUTE),
        clock="2026-07-01T00:00:00Z",
        departure="2026-07-01T14:00:00Z",
        depart_at="2026-07-01T14:00:00Z",
        complete_at="2026-07-01T14:25:00Z",
    )

    set_clock("2026-08-03T00:00:00Z")
    # Exactly now - 30 days (inclusive lower bound) vs one minute earlier.
    c_in = file_complaint(env["base"]["id"], "VILLAGE", "2026-07-04T00:00:00Z",
                          description="in window")
    c_out = file_complaint(env["base"]["id"], "VILLAGE", "2026-07-03T23:59:00Z",
                           description="out of window")
    # Both fall outside the flight's overflight window, so they are linked
    # manually (LINK_FLIGHT only requires the route to overfly the zone).
    complaint_event(c_in["id"], "LINK_FLIGHT", flight_id=completed["id"])
    complaint_event(c_out["id"], "LINK_FLIGHT", flight_id=completed["id"])
    substantiate_complaint(c_in["id"])
    substantiate_complaint(c_out["id"])

    route = get_route(env["route"]["id"])
    assert route["substantiated_complaints_30d"] == 1
    assert route["status"] == "ACTIVE", "count 1 < threshold 3, no suspension"
    # The out-of-window complaint IS substantiated; it just does not count.
    assert get_complaint(c_out["id"])["status"] == "SUBSTANTIATED"


def test_link_flight_zone_mismatch_rejected(api):
    """PRD §3.9: "A `ComplianceOfficer` may later link a flight manually; the
    link requires the target flight's route to overfly the complaint's zone,
    otherwise `ERR_COMPLAINT_FLIGHT_MISMATCH`, and it sets the same match
    fields without itself advancing the workflow status."

    Design: Corner/validations/link_flight_zone_mismatch_rejected
    """
    env = setup_ops_env(route_overrides=dict(VILLAGE_ROUTE))
    flight = create_flight(env, "2026-08-06T14:00:00Z")
    c_rim = file_complaint(env["base"]["id"], "RIM", "2026-08-02T10:00:00Z",
                           description="rim noise")
    c_vil = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-02T10:05:00Z",
                           description="village noise")

    from test_helpers import api_client as _api
    resp = _api.complaint_event(
        c_rim["id"], {"event_type": "LINK_FLIGHT", "flight_id": flight["id"]},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_FLIGHT_MISMATCH)
    assert get_complaint(c_rim["id"])["match_status"] == "UNMATCHED", (
        "failed link changes nothing"
    )

    linked = complaint_event(c_vil["id"], "LINK_FLIGHT", flight_id=flight["id"])
    assert linked["match_status"] == "MATCHED"
    assert linked["matched_flight_id"] == flight["id"]
    assert linked["matched_route_id"] == env["route"]["id"]


def _setup_route_auto_suspended(api):
    """A COMPLETED flight on a VILLAGE-zone route draws three substantiated
    complaints; the third trips the quota (3 >= 3) and auto-suspends the
    route. Returns (env, flight_id)."""
    env, completed = setup_completed_flight(
        route_overrides=dict(VILLAGE_ROUTE),
        departure="2026-08-03T14:00:00Z",
        depart_at="2026-08-03T14:00:00Z",
        complete_at="2026-08-03T14:25:00Z",
    )
    ids = [
        file_complaint(env["base"]["id"], "VILLAGE", "2026-08-03T14:10:00Z",
                       description=f"n{i}", reporter_ref=f"r{i}")["id"]
        for i in range(3)
    ]
    for cid in ids:
        substantiate_complaint(cid)
    return env, completed["id"]


def test_route_resume_blocked_until_quota_window_passes(api):
    """PRD §3.9: "Resumption moves SUSPENDED → ACTIVE only when the
    recomputed count has fallen strictly below `complaint_quota_threshold`;
    otherwise the resume is rejected with
    `ERR_ROUTE_QUOTA_STILL_EXCEEDED`."
    PRD §3.9: "the count of SUBSTANTIATED complaints matched to that route
    whose `observed_at` lies within the rolling window from
    `complaint_window_days` days ago through now, both bounds inclusive"

    Design: Corner/validations/route_resume_blocked_until_quota_window_passes
    """
    env, _flight_id = _setup_route_auto_suspended(api)
    route = get_route(env["route"]["id"])
    assert route["status"] == "SUSPENDED"
    assert route["substantiated_complaints_30d"] == 3

    from test_helpers import api_client as _api
    resp = _api.route_event(env["route"]["id"], {"event_type": "RESUME"}, OPS)
    validate_error(resp, ApiErrorId.ERR_ROUTE_QUOTA_STILL_EXCEEDED)

    # At 2026-09-03 the window [08-04, 09-03] excludes all three 08-03
    # complaints -> count 0 < 3 -> the same RESUME succeeds.
    set_clock("2026-09-03T00:00:00Z")
    resp = _api.route_event(env["route"]["id"], {"event_type": "RESUME"}, OPS)
    from test_helpers import validate_success as _vs
    assert _vs(resp)["status"] == "ACTIVE"


def test_auto_match_pool_empty_without_flown_flights(api):
    """PRD §3.9: "The winner sets `match_status` MATCHED, `matched_flight_id`
    to the flight, and `matched_route_id` to that flight's route; an empty
    candidate set is not an error — the complaint simply lands UNMATCHED with
    `matched_flight_id` null."
    PRD §3.9: "Eligible flights belong to the same base, sit in DISPATCHED or
    COMPLETED, fly a route whose `noise_zones` contain the complaint's
    `zone`, and have an overflight window — from `scheduled_departure_utc` up
    to but not including thirty minutes past `scheduled_arrival_utc` —
    containing `observed_at`."

    Design: Difficulty/cross_entity_state_dependency/complaint_substantiate_requires_flown_flight
    """
    env = setup_ops_env(route_overrides=dict(VILLAGE_ROUTE))
    flight = create_flight(env, "2026-08-06T14:00:00Z")  # stays SCHEDULED

    c1 = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-05T10:00:00Z",
                        description="early noise")
    # No DISPATCHED/COMPLETED flight exists: empty pool fallback, not error.
    assert c1["match_status"] == "UNMATCHED"
    assert c1["matched_flight_id"] is None

    # Manual link succeeds (zone covered) even though the flight has not flown.
    linked = complaint_event(c1["id"], "LINK_FLIGHT", flight_id=flight["id"])
    assert linked["match_status"] == "MATCHED"
    assert linked["matched_flight_id"] == flight["id"]
    assert linked["matched_route_id"] == env["route"]["id"]


def test_substantiate_against_scheduled_flight_rejected(api):
    """PRD §3.9: "Substantiation — UNDER_REVIEW → SUBSTANTIATED — is the
    consequential step: it requires a matched flight, and that flight must be
    DISPATCHED or COMPLETED, otherwise `ERR_COMPLAINT_FLIGHT_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/complaint_substantiate_requires_flown_flight
    """
    env = setup_ops_env(route_overrides=dict(VILLAGE_ROUTE))
    flight = create_flight(env, "2026-08-06T14:00:00Z")  # stays SCHEDULED
    c1 = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-05T10:00:00Z",
                        description="early noise")
    complaint_event(c1["id"], "LINK_FLIGHT", flight_id=flight["id"])
    complaint_event(c1["id"], "REVIEW")

    from test_helpers import api_client as _api
    resp = _api.complaint_event(c1["id"], {"event_type": "SUBSTANTIATE"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_FLIGHT_MISMATCH)
    assert get_complaint(c1["id"])["status"] == "UNDER_REVIEW", (
        "failed substantiate leaves state unchanged"
    )


def _setup_branching_complaints(api):
    """One COMPLETED flight on a VILLAGE route; complaints C1, C2 both
    auto-MATCHED to it. Returns (env, c1, c2)."""
    env, completed = setup_completed_flight(
        route_overrides=dict(VILLAGE_ROUTE),
        departure="2026-08-03T14:00:00Z",
        depart_at="2026-08-03T14:00:00Z",
        complete_at="2026-08-03T15:00:00Z",
    )
    c1 = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-03T14:10:00Z",
                        description="rotor noise", reporter_ref="res-1")
    c2 = file_complaint(env["base"]["id"], "VILLAGE", "2026-08-03T14:10:00Z",
                        description="rotor noise again", reporter_ref="res-2")
    assert c1["match_status"] == "MATCHED"
    assert c2["match_status"] == "MATCHED"
    return env, c1["id"], c2["id"]


def test_substantiate_increments_quota_dismiss_does_not(api):
    """PRD §3.9: "When a complaint substantiates, the matched route's
    `substantiated_complaints_30d` recomputes — the count of SUBSTANTIATED
    complaints matched to that route whose `observed_at` lies within the
    rolling window from `complaint_window_days` days ago through now, both
    bounds inclusive — and if the count now meets or exceeds the base's
    `complaint_quota_threshold`, the route flips ACTIVE → SUSPENDED and its
    cascade fires"
    PRD §3.9: "The complaint workflow runs LOGGED → UNDER_REVIEW when an
    officer opens review, or LOGGED → DISMISSED when dismissed outright;
    UNDER_REVIEW can likewise fall to DISMISSED."

    Design: Difficulty/non_linear_state_machine/complaint_branching_reopen_with_divergent_side_effects
    """
    env, c1, c2 = _setup_branching_complaints(api)
    substantiate_complaint(c1)
    # The SUBSTANTIATE branch increments the matched route's quota counter.
    assert get_route(env["route"]["id"])["substantiated_complaints_30d"] == 1

    complaint_event(c2, "REVIEW")
    complaint_event(c2, "DISMISS")
    # The DISMISS branch leaves the counter untouched.
    assert get_route(env["route"]["id"])["substantiated_complaints_30d"] == 1


def test_reopen_withdraws_quota_contribution(api):
    """PRD §3.9: "Closure records the outcome: SUBSTANTIATED → CLOSED or
    DISMISSED → CLOSED, capturing the officer's `resolution_note`."
    PRD §3.9: "And closure is not necessarily the end — a CLOSED complaint
    may be reopened back to UNDER_REVIEW; the prior substantiation is
    retained in history, but the complaint stops counting toward the quota
    until it is substantiated again."

    Design: Difficulty/non_linear_state_machine/complaint_branching_reopen_with_divergent_side_effects
    """
    env, c1, c2 = _setup_branching_complaints(api)
    substantiate_complaint(c1)
    assert get_route(env["route"]["id"])["substantiated_complaints_30d"] == 1

    complaint_event(c1, "CLOSE", resolution_note="operator warned")
    reopened = complaint_event(c1, "REOPEN")
    assert reopened["status"] == "UNDER_REVIEW"
    # The CLOSED -> REOPEN cycle withdraws the quota contribution.
    assert get_route(env["route"]["id"])["substantiated_complaints_30d"] == 0


def _setup_quota_cascade(api):
    """Route RC with a COMPLETED flight FC1 (08-03 14:00) and a SCHEDULED
    flight FC2 (08-04 14:00) carrying a CONFIRMED 50000-cent booking. Two
    complaints substantiated (count 2, route still ACTIVE); C3 reviewed and
    matched, ready for the third SUBSTANTIATE. Returns (env, fc2, bc2, c3)."""
    env, fc1 = setup_completed_flight(
        route_overrides=dict(VILLAGE_ROUTE),
        departure="2026-08-03T14:00:00Z",
        depart_at="2026-08-03T14:00:00Z",
        complete_at="2026-08-03T15:00:00Z",
    )
    fc2 = create_flight(env, "2026-08-04T14:00:00Z")
    bc2 = create_booking(fc2["id"], [passenger_entry("P0", 150),
                                     passenger_entry("P1", 150)],
                         contact_name="A", contact_email="a@x.com")
    confirm_booking(bc2["id"], 50000)

    ids = [
        file_complaint(env["base"]["id"], "VILLAGE",
                       f"2026-08-03T14:1{i}:00Z",
                       description=f"noise {i}", reporter_ref=f"r{i}")["id"]
        for i in (0, 1, 2)
    ]
    substantiate_complaint(ids[0])
    substantiate_complaint(ids[1])
    complaint_event(ids[2], "REVIEW")
    return env, fc2["id"], bc2["id"], ids[2]


def test_third_substantiation_suspends_route_and_cancels_flights(api):
    """PRD §3.9: "When a complaint substantiates, the matched route's
    `substantiated_complaints_30d` recomputes — the count of SUBSTANTIATED
    complaints matched to that route whose `observed_at` lies within the
    rolling window from `complaint_window_days` days ago through now, both
    bounds inclusive — and if the count now meets or exceeds the base's
    `complaint_quota_threshold`, the route flips ACTIVE → SUSPENDED and its
    cascade fires: every flight of that route in SCHEDULED, DELAYED, or
    BOARDING departing now or later becomes CANCELLED_OPS with
    `cancel_reason` ROUTE_SUSPENDED, and the booking cascade of §3.8 runs on
    each."
    PRD §3.3: "and finally the route must be ACTIVE (`ERR_ROUTE_SUSPENDED`)."

    Design: Difficulty/transitive_cascade/complaint_quota_route_suspension_cascade
    """
    env, fc2, bc2, c3 = _setup_quota_cascade(api)

    # Hop 1: complaint -> route. Count reaches the default threshold 3.
    # The setup already advanced c3 LOGGED -> UNDER_REVIEW; only SUBSTANTIATE
    # remains (PRD 3.9: "Substantiation — UNDER_REVIEW → SUBSTANTIATED").
    complaint_event(c3, "SUBSTANTIATE")
    route = get_route(env["route"]["id"])
    assert route["substantiated_complaints_30d"] == 3
    assert route["status"] == "SUSPENDED"

    # Hop 2: route -> flight. FC2 departs after now and is still SCHEDULED.
    f2_after = get_flight(fc2)
    assert f2_after["status"] == "CANCELLED_OPS"
    assert f2_after["cancel_reason"] == "ROUTE_SUSPENDED"

    # New scheduling on the suspended route is blocked.
    from test_helpers import api_client as _api
    resp = _api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-05T14:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_SUSPENDED)


def test_suspension_cascade_credits_booking_and_blocks_scheduling(api):
    """PRD §3.8: "the bookings move the same way: HELD bookings become
    EXPIRED with no refund; CONFIRMED and CHECKED_IN bookings become
    CREDITED, their `credited_cents` set to `paid_cents`, and a
    `RebookingCredit` is minted for `paid_cents` plus
    `credits_applied_cents`"
    PRD §3.9: "if the count now meets or exceeds the base's
    `complaint_quota_threshold`, the route flips ACTIVE → SUSPENDED and its
    cascade fires: every flight of that route in SCHEDULED, DELAYED, or
    BOARDING departing now or later becomes CANCELLED_OPS with
    `cancel_reason` ROUTE_SUSPENDED, and the booking cascade of §3.8 runs on
    each."

    Design: Difficulty/transitive_cascade/complaint_quota_route_suspension_cascade
    """
    env, fc2, bc2, c3 = _setup_quota_cascade(api)
    # The setup already advanced c3 LOGGED -> UNDER_REVIEW; only SUBSTANTIATE
    # remains (PRD 3.9: "Substantiation — UNDER_REVIEW → SUBSTANTIATED").
    complaint_event(c3, "SUBSTANTIATE")

    # Hop 3: flight -> booking.
    b2_after = get_booking(bc2)
    assert b2_after["status"] == "CREDITED"
    assert b2_after["credited_cents"] == 50000

    # Hop 4: booking -> credit minted (paid 50000 + credits_applied 0).
    credits = list_credits_for_booking(bc2)
    assert len(credits) == 1
    assert credits[0]["amount_cents"] == 50000
    assert credits[0]["status"] == "ISSUED"

    # New scheduling on the suspended route is blocked.
    from test_helpers import api_client as _api
    resp = _api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-05T14:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_SUSPENDED)
