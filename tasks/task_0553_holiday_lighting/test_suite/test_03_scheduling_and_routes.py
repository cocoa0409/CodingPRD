"""Crews, route days, booking, and the job lifecycle.

Covers the booking sequence (window validity, bookability, half-open overlap, capacity,
optimistic concurrency), the weather reschedule cycle, cross-entity start gating, the
contract-cancel and job-cancel cascades, booked_stops conservation, and job listing.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    create_customer, create_draft_contract, create_crew, create_route_day, create_job,
    book_assignment, dispatch_route_day, setup_active_contract, setup_booked_install_job,
)
from test_helpers.factories import (
    create_job_payload, create_route_assignment_payload,
)
from test_helpers.test_users import make_crewlead_headers

SALES = TEST_USERS["salesrep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


def _route_day_version(route_day_id):
    rd = validate_success(api_client.get_route_day(route_day_id, DISPATCH), 200)
    return rd["version"]


# ── Difficulty/transitive_cascade/contract_cancel_cascade_depth3 ─────────────

def test_contract_cancel_cascades_to_job(api):
    """PRD §3.1: "As the first hop of a three-hop cascade, every job belonging to this
    contract whose status is `SCHEDULED` or `RESCHEDULED` is transitioned to `CANCELLED`;
    the second and third hops of that cascade — the release of those jobs' route
    assignments and the correction of the affected route days' stop counters — are
    described in §3.4, and they run as part of this same cancellation."

    Design: Difficulty/transitive_cascade/contract_cancel_cascade_depth3
    """
    ctx = setup_booked_install_job()
    validate_success(api.cancel_contract(ctx["contract"]["id"], SALES), 200)
    contract = validate_success(api.get_contract(ctx["contract"]["id"], SALES), 200)
    job = validate_success(api.get_job(ctx["job"]["id"], DISPATCH), 200)
    assert contract["status"] == "CANCELLED", contract
    assert job["status"] == "CANCELLED", job


def test_contract_cancel_releases_assignment_and_decrements_stops(api):
    """PRD §3.4: "As the cascade's second hop, every route assignment for this job whose
    status is `BOOKED` or `DISPATCHED` is transitioned to `RELEASED`. As the third hop,
    each such release recomputes its route day's `booked_stops` downward and refreshes
    that route day's `updated_at`."

    Design: Difficulty/transitive_cascade/contract_cancel_cascade_depth3
    """
    ctx = setup_booked_install_job()
    validate_success(api.cancel_contract(ctx["contract"]["id"], SALES), 200)
    assignment = validate_success(
        api.get_route_assignment(ctx["assignment"]["id"], DISPATCH), 200)
    route_day = validate_success(api.get_route_day(ctx["route_day"]["id"], DISPATCH), 200)
    assert assignment["status"] == "RELEASED", assignment
    assert route_day["booked_stops"] == 0, route_day


# ── Difficulty/compensating_invariant/routeday_booked_stops_conserved ────────

def test_job_cancel_releases_assignment(api):
    """PRD §3.4: "As the cascade's second hop, every route assignment for this job whose
    status is `BOOKED` or `DISPATCHED` is transitioned to `RELEASED`."

    Design: Difficulty/compensating_invariant/routeday_booked_stops_conserved
    """
    ctx = setup_booked_install_job()
    validate_success(api.cancel_job(ctx["job"]["id"], DISPATCH), 200)
    assignment = validate_success(
        api.get_route_assignment(ctx["assignment"]["id"], DISPATCH), 200)
    assert assignment["status"] == "RELEASED", assignment


def test_job_cancel_restores_booked_stops_to_zero(api):
    """PRD §3.4: "As the third hop, each such release recomputes its route day's
    `booked_stops` downward and refreshes that route day's `updated_at`."

    The forward booking (+1) and its compensating release leave booked_stops back at 0.

    Design: Difficulty/compensating_invariant/routeday_booked_stops_conserved
    """
    ctx = setup_booked_install_job()
    assert ctx["route_day"]["booked_stops"] == 1, ctx["route_day"]
    validate_success(api.cancel_job(ctx["job"]["id"], DISPATCH), 200)
    route_day = validate_success(api.get_route_day(ctx["route_day"]["id"], DISPATCH), 200)
    assert route_day["booked_stops"] == 0, route_day


# ── Difficulty/boundary_precision_check/route_capacity_last_slot_rejected ─────

def _route_day_with_two_booked(max_stops=2):
    customer, contract = setup_active_contract()
    crew = create_crew(name="Crew D", home_zone="W", daily_stop_capacity=max_stops)
    rd = create_route_day(crew["id"], service_date="2026-11-25T00:00:00Z", zone="W",
                          max_stops=max_stops)
    job_a = create_job(contract["id"], scheduled_date="2026-11-25T08:00:00Z")
    book_assignment(rd["id"], job_a["id"], "2026-11-25T08:00:00Z",
                    "2026-11-25T09:00:00Z", _route_day_version(rd["id"]))
    job_b = create_job(contract["id"], scheduled_date="2026-11-25T09:00:00Z")
    book_assignment(rd["id"], job_b["id"], "2026-11-25T09:00:00Z",
                    "2026-11-25T10:00:00Z", _route_day_version(rd["id"]))
    return contract, rd


def test_booking_beyond_capacity_rejected(api):
    """PRD §3.3: "The day must still have room, meaning its `booked_stops` must be strictly
    less than its `max_stops` before this assignment is added; a full day is rejected with
    `ERR_ROUTE_DAY_FULL`."

    max_stops 2 with two stops booked -> the third booking is rejected.

    Design: Difficulty/boundary_precision_check/route_capacity_last_slot_rejected
    """
    contract, rd = _route_day_with_two_booked(max_stops=2)
    job_c = create_job(contract["id"], scheduled_date="2026-11-25T10:00:00Z")
    resp = api.create_route_assignment(create_route_assignment_payload(
        rd["id"], job_c["id"], "2026-11-25T10:00:00Z", "2026-11-25T11:00:00Z",
        _route_day_version(rd["id"])), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_FULL.value, 409)


def test_booking_at_capacity_leaves_stops_at_max(api):
    """PRD §3.3: "The day must still have room, meaning its `booked_stops` must be strictly
    less than its `max_stops` before this assignment is added; a full day is rejected with
    `ERR_ROUTE_DAY_FULL`."

    After two bookings the day sits at booked_stops == 2 (== max_stops).

    Design: Difficulty/boundary_precision_check/route_capacity_last_slot_rejected
    """
    contract, rd = _route_day_with_two_booked(max_stops=2)
    route_day = validate_success(api.get_route_day(rd["id"], DISPATCH), 200)
    assert route_day["booked_stops"] == 2, route_day


# ── Difficulty/resource_temporal_overlap/assignment_window_halfopen_overlap_rejected

def test_touching_windows_do_not_overlap(api):
    """PRD §3.3: "The proposed window must not overlap any other `BOOKED` or `DISPATCHED`
    window already on the same route day; because the interval is half-open, two windows
    that merely touch (one ending exactly when the next begins) do not overlap, but any
    true overlap is rejected with `ERR_WINDOW_OVERLAP`."

    Booking [11:00,12:00) adjacent to [09:00,11:00) succeeds (end == start allowed).

    Design: Difficulty/resource_temporal_overlap/assignment_window_halfopen_overlap_rejected
    """
    customer, contract = setup_active_contract()
    crew = create_crew(name="Crew F", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-11-30T00:00:00Z", zone="N",
                          max_stops=5)
    job_a = create_job(contract["id"], scheduled_date="2026-11-30T09:00:00Z")
    book_assignment(rd["id"], job_a["id"], "2026-11-30T09:00:00Z",
                    "2026-11-30T11:00:00Z", _route_day_version(rd["id"]))
    job_b = create_job(contract["id"], scheduled_date="2026-11-30T11:00:00Z")
    adjacent = validate_success(api.create_route_assignment(
        create_route_assignment_payload(
            rd["id"], job_b["id"], "2026-11-30T11:00:00Z", "2026-11-30T12:00:00Z",
            _route_day_version(rd["id"])), DISPATCH), 201)
    assert adjacent["status"] == "BOOKED", adjacent


def test_true_overlap_window_rejected(api):
    """PRD §3.3: "The proposed window must not overlap any other `BOOKED` or `DISPATCHED`
    window already on the same route day; because the interval is half-open, two windows
    that merely touch (one ending exactly when the next begins) do not overlap, but any
    true overlap is rejected with `ERR_WINDOW_OVERLAP`."

    A [10:00,12:00) window genuinely overlapping [09:00,11:00) is rejected.

    Design: Difficulty/resource_temporal_overlap/assignment_window_halfopen_overlap_rejected
    """
    customer, contract = setup_active_contract()
    crew = create_crew(name="Crew F", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-11-30T00:00:00Z", zone="N",
                          max_stops=5)
    job_a = create_job(contract["id"], scheduled_date="2026-11-30T09:00:00Z")
    book_assignment(rd["id"], job_a["id"], "2026-11-30T09:00:00Z",
                    "2026-11-30T11:00:00Z", _route_day_version(rd["id"]))
    job_c = create_job(contract["id"], scheduled_date="2026-11-30T10:00:00Z")
    resp = api.create_route_assignment(create_route_assignment_payload(
        rd["id"], job_c["id"], "2026-11-30T10:00:00Z", "2026-11-30T12:00:00Z",
        _route_day_version(rd["id"])), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value, 409)


# ── Difficulty/priority_pair_validation_conflict/assignment_referential_vs_temporal_conflict

def _cancelled_job_overlapping_booking(contract, rd):
    """Book job A at [09,11); create job B, cancel it (unbookable); return job_b id."""
    job_a = create_job(contract["id"], scheduled_date="2026-11-20T09:00:00Z")
    book_assignment(rd["id"], job_a["id"], "2026-11-20T09:00:00Z",
                    "2026-11-20T11:00:00Z", _route_day_version(rd["id"]))
    job_b = create_job(contract["id"], scheduled_date="2026-11-20T10:00:00Z")
    validate_success(api_client.cancel_job(job_b["id"], DISPATCH), 200)
    return job_b["id"]


def test_bookability_checked_before_window_overlap(api):
    """PRD §3.3: "The referenced job must be bookable — its status must be `SCHEDULED` or
    `RESCHEDULED`; a job that is `CANCELLED`, `COMPLETED`, or `IN_PROGRESS` cannot be
    booked onto a day, and such an attempt is rejected with `ERR_JOB_NOT_BOOKABLE`."

    Booking a CANCELLED job onto a window that also overlaps an existing assignment
    surfaces the earlier bookability failure, ERR_JOB_NOT_BOOKABLE.

    Design: Difficulty/priority_pair_validation_conflict/assignment_referential_vs_temporal_conflict
    """
    customer, contract = setup_active_contract()
    crew = create_crew(name="Crew C", home_zone="E", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-11-20T00:00:00Z", zone="E",
                          max_stops=5)
    job_b = _cancelled_job_overlapping_booking(contract, rd)
    resp = api.create_route_assignment(create_route_assignment_payload(
        rd["id"], job_b, "2026-11-20T10:00:00Z", "2026-11-20T12:00:00Z",
        _route_day_version(rd["id"])), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_BOOKABLE.value, 409)


def test_bookability_conflict_not_reported_as_window_overlap(api):
    """PRD §3.3: "The referenced job must be bookable — its status must be `SCHEDULED` or
    `RESCHEDULED`; a job that is `CANCELLED`, `COMPLETED`, or `IN_PROGRESS` cannot be
    booked onto a day, and such an attempt is rejected with `ERR_JOB_NOT_BOOKABLE`."
    PRD §3.3: "The proposed window must not overlap any other `BOOKED` or `DISPATCHED`
    window already on the same route day; because the interval is half-open, two windows
    that merely touch (one ending exactly when the next begins) do not overlap, but any
    true overlap is rejected with `ERR_WINDOW_OVERLAP`."

    Bookability (stated earlier in the sequence) pre-empts the overlap check, so the
    error is not ERR_WINDOW_OVERLAP.

    Design: Difficulty/priority_pair_validation_conflict/assignment_referential_vs_temporal_conflict
    """
    customer, contract = setup_active_contract()
    crew = create_crew(name="Crew C", home_zone="E", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-11-20T00:00:00Z", zone="E",
                          max_stops=5)
    job_b = _cancelled_job_overlapping_booking(contract, rd)
    resp = api.create_route_assignment(create_route_assignment_payload(
        rd["id"], job_b, "2026-11-20T10:00:00Z", "2026-11-20T12:00:00Z",
        _route_day_version(rd["id"])), DISPATCH)
    error = validate_error(resp, ApiErrorId.ERR_JOB_NOT_BOOKABLE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_WINDOW_OVERLAP.value, error


# ── Difficulty/cross_entity_state_dependency/job_start_requires_routeday_dispatched

def test_job_start_requires_dispatched_route_day(api):
    """PRD §3.4: "A crew lead starts a job, moving it from `SCHEDULED` to `IN_PROGRESS`,
    only when three conditions hold: the job is in `SCHEDULED` (otherwise
    `ERR_JOB_NOT_SCHEDULED`); there exists a route assignment for this job whose route day
    is in `DISPATCHED` status (otherwise `ERR_ROUTE_DAY_NOT_DISPATCHED`); and the acting
    crew lead owns that route day's crew, meaning the route day's `crew_id` equals the
    caller's `X-User-ID`."

    With the route day still PLANNED, the owning crew lead's start is refused.

    Design: Difficulty/cross_entity_state_dependency/job_start_requires_routeday_dispatched
    """
    ctx = setup_booked_install_job()
    resp = api.start_job(ctx["job"]["id"], make_crewlead_headers(ctx["crew"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_DISPATCHED.value, 409)


def test_job_stays_scheduled_when_start_refused(api):
    """PRD §3.4: "there exists a route assignment for this job whose route day is in
    `DISPATCHED` status (otherwise `ERR_ROUTE_DAY_NOT_DISPATCHED`)"

    The refused start leaves the job in SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/job_start_requires_routeday_dispatched
    """
    ctx = setup_booked_install_job()
    api.start_job(ctx["job"]["id"], make_crewlead_headers(ctx["crew"]["id"]))
    job = validate_success(api.get_job(ctx["job"]["id"], DISPATCH), 200)
    assert job["status"] == "SCHEDULED", job


# ── Difficulty/non_linear_state_machine/job_weather_reschedule_cycle ─────────

def _held_then_rescheduled_job():
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], job_type="TAKEDOWN",
                     scheduled_date="2026-12-01T09:00:00Z")
    validate_success(api_client.weather_hold_job(job["id"], DISPATCH), 200)
    validate_success(api_client.reschedule_job(
        job["id"], {"new_scheduled_date": "2026-12-05T09:00:00Z"}, DISPATCH), 200)
    return job["id"]


def test_reschedule_returns_job_to_scheduled(api):
    """PRD §3.4: "To put the held job back on the calendar, the dispatcher reschedules it,
    which moves it from `RESCHEDULED` back to `SCHEDULED` (permitted only while
    `RESCHEDULED`, otherwise `ERR_JOB_NOT_HELD`); this sets the job's `scheduled_date` to
    the supplied `new_scheduled_date`, increments the `reschedule_count` by one, and
    increments the `version`."

    Design: Difficulty/non_linear_state_machine/job_weather_reschedule_cycle
    """
    job_id = _held_then_rescheduled_job()
    job = validate_success(api.get_job(job_id, DISPATCH), 200)
    assert job["status"] == "SCHEDULED", job
    assert job["scheduled_date"].startswith("2026-12-05"), job


def test_reschedule_increments_reschedule_count(api):
    """PRD §3.4: "A job may cycle through this loop any number of times, each pass adding
    one to its reschedule count."

    One hold-and-rebook pass leaves reschedule_count == 1.

    Design: Difficulty/non_linear_state_machine/job_weather_reschedule_cycle
    """
    job_id = _held_then_rescheduled_job()
    job = validate_success(api.get_job(job_id, DISPATCH), 200)
    assert job["reschedule_count"] == 1, job


# ── Corner/state_machines/reschedule_non_held_job_returns_invalid_state ──────

def test_reschedule_scheduled_job_rejected(api):
    """PRD §3.4: "To put the held job back on the calendar, the dispatcher reschedules it,
    which moves it from `RESCHEDULED` back to `SCHEDULED` (permitted only while
    `RESCHEDULED`, otherwise `ERR_JOB_NOT_HELD`)"

    Design: Corner/state_machines/reschedule_non_held_job_returns_invalid_state
    """
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], job_type="TAKEDOWN",
                     scheduled_date="2026-12-01T09:00:00Z")
    resp = api.reschedule_job(job["id"], {"new_scheduled_date": "2026-12-05T09:00:00Z"},
                              DISPATCH)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_HELD.value, 409)


# ── Corner/state_machines/dispatch_non_planned_route_day_returns_invalid_state

def test_dispatch_already_dispatched_route_day_rejected(api):
    """PRD §3.3: "A `Dispatcher` moves a route day from `PLANNED` to `DISPATCHED`,
    permitted only while it is `PLANNED` (otherwise `ERR_ROUTE_DAY_NOT_PLANNED`)"

    Design: Corner/state_machines/dispatch_non_planned_route_day_returns_invalid_state
    """
    crew = create_crew(name="Crew H", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-12-03T00:00:00Z", zone="N",
                          max_stops=5)
    dispatch_route_day(rd["id"])
    resp = api.dispatch_route_day(rd["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_PLANNED.value, 409)


# ── Corner/state_machines/route_day_dispatch_promotes_assignment ─────────────

def test_dispatch_promotes_booked_assignment(api):
    """PRD §3.3: "as a side effect, every assignment on that day currently in `BOOKED` is
    transitioned to `DISPATCHED`, and the route day's `version` is incremented. Because
    both `BOOKED` and `DISPATCHED` assignments count toward `booked_stops`, promoting the
    assignments does not change the day's stop count."

    Design: Corner/state_machines/route_day_dispatch_promotes_assignment
    """
    ctx = setup_booked_install_job()
    dispatched = validate_success(api.dispatch_route_day(ctx["route_day"]["id"], DISPATCH), 200)
    assignment = validate_success(
        api.get_route_assignment(ctx["assignment"]["id"], DISPATCH), 200)
    assert dispatched["status"] == "DISPATCHED", dispatched
    assert assignment["status"] == "DISPATCHED", assignment
    assert dispatched["booked_stops"] == 1, dispatched


# ── Corner/state_machines/takedown_job_start_complete_happy_path ─────────────

def test_takedown_job_start_and_complete(api):
    """PRD §3.4: "The same crew lead completes a job, moving it from `IN_PROGRESS` to
    `COMPLETED`, only while it is `IN_PROGRESS` (otherwise `ERR_JOB_NOT_IN_PROGRESS`) and,
    again, only when they own the route day's crew."

    A TAKEDOWN job on a DISPATCHED route day, started and completed by the owning crew,
    reaches COMPLETED (no estimate finalization).

    Design: Corner/state_machines/takedown_job_start_complete_happy_path
    """
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], job_type="TAKEDOWN",
                     scheduled_date="2026-12-06T09:00:00Z")
    crew = create_crew(name="Crew J", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-12-06T00:00:00Z", zone="N",
                          max_stops=5)
    book_assignment(rd["id"], job["id"], "2026-12-06T09:00:00Z",
                    "2026-12-06T11:00:00Z", _route_day_version(rd["id"]))
    dispatch_route_day(rd["id"])
    crew_hdr = make_crewlead_headers(crew["id"])
    validate_success(api.start_job(job["id"], crew_hdr), 200)
    completed = validate_success(api.complete_job(job["id"], {}, crew_hdr), 200)
    assert completed["status"] == "COMPLETED", completed


# ── Corner/validations/job_create_on_non_active_contract_returns_invalid_state

def test_job_create_on_draft_contract_rejected(api):
    """PRD §3.4: "Creating a job requires the parent contract to be `ACTIVE`; an attempt
    against a non-active contract is rejected with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Corner/validations/job_create_on_non_active_contract_returns_invalid_state
    """
    customer = create_customer(name="Job Owner", service_address="118 Main St",
                               roofline_feet=100)
    draft = create_draft_contract(customer["id"])
    resp = api.create_job(create_job_payload(
        draft["id"], job_type="INSTALL", scheduled_date="2026-12-07T09:00:00Z"), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)


# ── Corner/validations/route_assignment_invalid_window_returns_invalid_window

def test_route_assignment_inverted_window_rejected(api):
    """PRD §3.3: "The window must be well-formed, with `window_end` strictly after
    `window_start`, or the request fails with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/route_assignment_invalid_window_returns_invalid_window
    """
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], scheduled_date="2026-12-08T09:00:00Z")
    crew = create_crew(name="Crew K", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-12-08T00:00:00Z", zone="N",
                          max_stops=5)
    resp = api.create_route_assignment(create_route_assignment_payload(
        rd["id"], job["id"], "2026-12-08T11:00:00Z", "2026-12-08T09:00:00Z",
        rd["version"]), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value, 422)


# ── Corner/cross_cutting_complexity_layers/route_assignment_correct_version_succeeds

def test_booking_with_current_version_succeeds_and_bumps_version(api):
    """PRD §2.6: "When all checks pass, the assignment is created in `BOOKED`, the route
    day's `booked_stops` is recomputed upward, and the route day's `version` is
    incremented."

    Booking with expected_route_day_version equal to the observed version succeeds and
    advances the route day's version by one.

    Design: Corner/cross_cutting_complexity_layers/route_assignment_correct_version_succeeds
    """
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], scheduled_date="2026-12-12T09:00:00Z")
    crew = create_crew(name="Crew L", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-12-12T00:00:00Z", zone="N",
                          max_stops=5)
    initial_version = rd["version"]
    assignment = validate_success(api.create_route_assignment(
        create_route_assignment_payload(
            rd["id"], job["id"], "2026-12-12T09:00:00Z", "2026-12-12T11:00:00Z",
            initial_version), DISPATCH), 201)
    assert assignment["status"] == "BOOKED", assignment
    route_day = validate_success(api.get_route_day(rd["id"], DISPATCH), 200)
    assert route_day["version"] == initial_version + 1, route_day
    assert route_day["booked_stops"] == 1, route_day


# ── Corner/cross_cutting_complexity_layers/route_assignment_stale_version_rejected

def test_booking_with_stale_version_rejected(api):
    """PRD §2.6: "If `expected_route_day_version` does not equal the route day's current
    `version` — that is, if the day has advanced since the client read it — the client's
    availability snapshot is stale and the booking is refused with `ERR_STALE_VERSION`
    (HTTP 412), so it cannot commit against an outdated view."

    A first booking advances the version; a second booking still carrying the original
    version is rejected.

    Design: Corner/cross_cutting_complexity_layers/route_assignment_stale_version_rejected
    """
    customer, contract = setup_active_contract()
    crew = create_crew(name="Crew M", home_zone="N", daily_stop_capacity=5)
    rd = create_route_day(crew["id"], service_date="2026-12-13T00:00:00Z", zone="N",
                          max_stops=5)
    stale_version = rd["version"]
    job_a = create_job(contract["id"], scheduled_date="2026-12-13T08:00:00Z")
    book_assignment(rd["id"], job_a["id"], "2026-12-13T08:00:00Z",
                    "2026-12-13T09:00:00Z", stale_version)
    job_b = create_job(contract["id"], scheduled_date="2026-12-13T10:00:00Z")
    resp = api.create_route_assignment(create_route_assignment_payload(
        rd["id"], job_b["id"], "2026-12-13T10:00:00Z", "2026-12-13T11:00:00Z",
        stale_version), DISPATCH)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
    route_day = validate_success(api.get_route_day(rd["id"], DISPATCH), 200)
    assert route_day["booked_stops"] == 1, route_day


# ── Corner/endpoints/jobs_list_by_contract_fk ────────────────────────────────

def test_jobs_list_returns_contract_job(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, all list endpoints return
    resources sorted by their creation timestamp (`created_at`) in ascending order."
    PRD §2.3: "Every list response includes the following fields inside the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/jobs_list_by_contract_fk
    """
    customer, contract = setup_active_contract()
    job = create_job(contract["id"], scheduled_date="2026-12-09T09:00:00Z")
    data, meta = validate_paginated(
        api.list_jobs(DISPATCH, params={"contract_id": contract["id"]}))
    assert meta["total_count"] == 1, meta
    assert len(data) == 1 and data[0]["id"] == job["id"], data
