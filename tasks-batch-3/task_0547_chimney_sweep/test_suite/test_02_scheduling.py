"""Scheduling: appointment windows, travel buffer, route capacity, minute conservation,
and the job-cancel appointment/route-day cascade."""
from test_helpers import (
    api_client, TEST_USERS, make_technician_headers, ApiErrorId,
    validate_success, validate_error,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.constants import ROUTE_WINDOW_END, APPT_START, APPT_END_90

DISPATCHER = TEST_USERS["dispatcher_headers"]

# A 120-minute slot spaced 40 minutes after the standard 90-minute slot ends
# (buffer of 30 min satisfied). 1746353400 - 1746351000 == 2400 s == 40 min.
APPT2_120_START = 1746353400
APPT2_120_END = 1746360600  # (1746360600 - 1746353400) / 60 == 120


def _two_jobs_one_route_day(capacity_minutes=600):
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech = fx.make_technician()
    rd = fx.make_route_day(tech["id"], capacity_minutes=capacity_minutes)
    job1 = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    job2 = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    return customer, chimney, tech, rd, job1, job2


# ---------------------------------------------------------------- rto buffer
def test_second_appointment_ten_minutes_after_first_double_booked():
    """PRD §3.3: "the new interval, treated as half-open from `start_ts` up to but
    not including `end_ts`, may not overlap another of that technician's
    non-cancelled appointments, and consecutive appointments must be separated by a
    gap of at least 30 minutes of travel buffer. A violation of the technician
    match, an overlap, or an insufficient gap all raise
    `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/rto_technician_buffer_overlap
    """
    _, _, tech, rd, job1, job2 = _two_jobs_one_route_day(capacity_minutes=600)
    fx.book_appointment(rd["id"], job1["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)
    # Second slot starts only 10 minutes after the first ends (1746351600 - 1746351000 == 600 s).
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=rd["id"], service_job_id=job2["id"],
                                     technician_id=tech["id"], start_ts=1746351600, end_ts=1746355200),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)


def test_overlapping_appointment_double_booked():
    """PRD §3.3: "the new interval, treated as half-open from `start_ts` up to but
    not including `end_ts`, may not overlap another of that technician's
    non-cancelled appointments, and consecutive appointments must be separated by a
    gap of at least 30 minutes of travel buffer. A violation of the technician
    match, an overlap, or an insufficient gap all raise
    `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/rto_technician_buffer_overlap
    """
    _, _, tech, rd, job1, job2 = _two_jobs_one_route_day(capacity_minutes=600)
    fx.book_appointment(rd["id"], job1["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)
    # Second slot starts inside the first appointment's half-open interval.
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=rd["id"], service_job_id=job2["id"],
                                     technician_id=tech["id"], start_ts=1746348000, end_ts=1746352800),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)


# ---------------------------------------------------------------- rto capacity
def test_route_capacity_exceeded_by_aggregate_minutes():
    """PRD §3.3: "Finally, the day must have room: the day's current
    `booked_minutes` plus the new appointment's on-site minutes must not exceed
    `capacity_minutes`, else `ERR_ROUTE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/rto_routeday_capacity_aggregate
    """
    _, _, tech, rd, job1, job2 = _two_jobs_one_route_day(capacity_minutes=120)
    fx.book_appointment(rd["id"], job1["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90 min
    # 90 booked + 60 new == 150 > 120 capacity; buffer of 40 min is satisfied.
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=rd["id"], service_job_id=job2["id"],
                                     technician_id=tech["id"], start_ts=1746353400, end_ts=1746357000),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 90


def test_route_capacity_exact_fit_succeeds():
    """PRD §3.3: "Finally, the day must have room: the day's current
    `booked_minutes` plus the new appointment's on-site minutes must not exceed
    `capacity_minutes`, else `ERR_ROUTE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/rto_routeday_capacity_aggregate
    """
    _, _, tech, rd, job1, job2 = _two_jobs_one_route_day(capacity_minutes=150)
    fx.book_appointment(rd["id"], job1["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90 min
    # 90 + 60 == 150 exactly equals capacity, so booking is allowed ("must not exceed").
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=rd["id"], service_job_id=job2["id"],
                                     technician_id=tech["id"], start_ts=1746353400, end_ts=1746357000),
        DISPATCHER,
    )
    validate_success(resp, 201)
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 150


# ---------------------------------------------------------------- bpc zero-duration
def test_zero_duration_appointment_rejected():
    """PRD §3.3: "Temporally, if `end_ts` is not strictly after `start_ts`
    (non-positive on-site minutes) the booking is rejected with
    `ERR_INVALID_APPOINTMENT_WINDOW`."

    Design: Difficulty/boundary_precision_check/bpc_zero_duration_appointment_rejected
    """
    setup = fx.setup_route_day()
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=setup["route_day"]["id"], service_job_id=job["id"],
                                     technician_id=setup["technician"]["id"],
                                     start_ts=APPT_START, end_ts=APPT_START),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_APPOINTMENT_WINDOW)


def test_negative_duration_appointment_rejected():
    """PRD §3.3: "Temporally, if `end_ts` is not strictly after `start_ts`
    (non-positive on-site minutes) the booking is rejected with
    `ERR_INVALID_APPOINTMENT_WINDOW`."

    Design: Difficulty/boundary_precision_check/bpc_zero_duration_appointment_rejected
    """
    setup = fx.setup_route_day()
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=setup["route_day"]["id"], service_job_id=job["id"],
                                     technician_id=setup["technician"]["id"],
                                     start_ts=APPT_END_90, end_ts=APPT_START),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_APPOINTMENT_WINDOW)


# ---------------------------------------------------------------- ci route minutes
def test_route_minutes_restored_after_appointment_cancel():
    """PRD §2.8: "A `RouteDay`'s `booked_minutes` is always the sum of
    `on_site_minutes` over that day's appointments whose status is neither
    `CANCELLED` nor `NO_SHOW`; it starts at 0."
    PRD §3.3: "Both cancellation and no-show release the appointment's minutes: the
    route day's `booked_minutes` drops by that appointment's on-site minutes."

    Design: Difficulty/compensating_invariant/ci_routeday_minutes_appointment_cancel_time
    """
    _, _, tech, rd, job1, job2 = _two_jobs_one_route_day(capacity_minutes=600)
    appt1 = fx.book_appointment(rd["id"], job1["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90
    fx.book_appointment(rd["id"], job2["id"], tech["id"], start_ts=APPT2_120_START, end_ts=APPT2_120_END)  # 120
    api_client.transition_appointment(appt1["id"], {"action": "CANCEL"}, DISPATCHER)
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 120
    assert fx.get_appointment(appt1["id"])["status"] == "CANCELLED"


def test_route_minutes_conserved_through_book_and_cancel():
    """PRD §2.8: "Both are invariants: booking an appointment and then cancelling
    it restores `booked_minutes` exactly, and proposing a repair and then
    cancelling or rejecting it returns `committed_cost_cents` to exactly the value
    implied by the surviving orders."

    Design: Difficulty/compensating_invariant/ci_routeday_minutes_appointment_cancel_time
    """
    _, _, tech, rd, job1, job2 = _two_jobs_one_route_day(capacity_minutes=600)
    appt1 = fx.book_appointment(rd["id"], job1["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90
    fx.book_appointment(rd["id"], job2["id"], tech["id"], start_ts=APPT2_120_START, end_ts=APPT2_120_END)  # 120
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 210
    api_client.transition_appointment(appt1["id"], {"action": "CANCEL"}, DISPATCHER)
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 120


# ---------------------------------------------------------------- tc jobcancel depth3
def test_job_cancel_cascades_appointment_to_cancelled():
    """PRD §3.9: "A successful cancellation drives a layered cascade. First, the
    job's `job_status` moves to `CANCELLED`. As a direct consequence, every
    appointment for the job whose status is `SCHEDULED`, `EN_ROUTE`, or `ON_SITE`
    is moved to `CANCELLED`; and for each appointment cancelled this way, its route
    day's `booked_minutes` is reduced by that appointment's on-site minutes,
    releasing the capacity."

    Design: Difficulty/transitive_cascade/tc_jobcancel_appointment_routeday_depth3
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech = fx.make_technician()
    rd = fx.make_route_day(tech["id"], capacity_minutes=300)
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    appt = fx.book_appointment(rd["id"], job["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)
    resp = api_client.cancel_service_job(job["id"], DISPATCHER)
    validate_success(resp, 200)
    assert fx.get_job(job["id"])["job_status"] == "CANCELLED"
    assert fx.get_appointment(appt["id"])["status"] == "CANCELLED"


def test_job_cancel_releases_route_day_minutes():
    """PRD §3.9: "As a direct consequence, every appointment for the job whose
    status is `SCHEDULED`, `EN_ROUTE`, or `ON_SITE` is moved to `CANCELLED`; and
    for each appointment cancelled this way, its route day's `booked_minutes` is
    reduced by that appointment's on-site minutes, releasing the capacity."

    Design: Difficulty/transitive_cascade/tc_jobcancel_appointment_routeday_depth3
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech = fx.make_technician()
    rd = fx.make_route_day(tech["id"], capacity_minutes=300)
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    fx.book_appointment(rd["id"], job["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90 booked
    api_client.cancel_service_job(job["id"], DISPATCHER)
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 0
    assert fx.get_job(job["id"])["job_status"] == "CANCELLED"


# ---------------------------------------------------------------- corner: outside window
def test_appointment_end_outside_route_window_rejected():
    """PRD §3.3: "the appointment must fall entirely within the route day's window,
    meaning both `start_ts` and `end_ts` lie inside the span from `window_start_ts`
    to `window_end_ts`, else `ERR_APPOINTMENT_OUTSIDE_WINDOW`."

    Design: Corner/validations/error_appointment_outside_route_window
    """
    setup = fx.setup_route_day()
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    # end_ts (1746378000) exceeds the route day window_end_ts (ROUTE_WINDOW_END).
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id=setup["route_day"]["id"], service_job_id=job["id"],
                                     technician_id=setup["technician"]["id"],
                                     start_ts=1746372000, end_ts=1746378000),
        DISPATCHER,
    )
    assert 1746378000 > ROUTE_WINDOW_END
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_WINDOW)


# ---------------------------------------------------------------- corner: tech identity
def test_technician_identity_mismatch_on_appointment_transition():
    """PRD §2.1: "when a technician drives an appointment through its lifecycle,
    `X-User-ID` must equal that appointment's `technician_id`; a mismatch is
    rejected with `ERR_TECH_IDENTITY_MISMATCH`."

    Design: Corner/validations/error_tech_identity_mismatch_on_appointment_transition
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech_a = fx.make_technician(name="Tech A", cert_level="MASTER")
    tech_b = fx.make_technician(name="Tech B", cert_level="MASTER")
    rd = fx.make_route_day(tech_a["id"], capacity_minutes=300)
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    appt = fx.book_appointment(rd["id"], job["id"], tech_a["id"], start_ts=APPT_START, end_ts=APPT_END_90)
    resp = api_client.transition_appointment(appt["id"], {"action": "DEPART"}, make_technician_headers(tech_b["id"]))
    validate_error(resp, ApiErrorId.ERR_TECH_IDENTITY_MISMATCH)


# ---------------------------------------------------------------- corner: no-show release
def test_no_show_releases_route_minutes():
    """PRD §3.3: "A `Dispatcher` may instead cancel an appointment that is still
    `SCHEDULED` or `EN_ROUTE` (`→ CANCELLED`), or mark a still-`SCHEDULED`
    appointment a no-show (`→ NO_SHOW`), in which case the supplied
    `no_show_reason` is stored. Both cancellation and no-show release the
    appointment's minutes: the route day's `booked_minutes` drops by that
    appointment's on-site minutes."

    Design: Corner/state_machines/appointment_no_show_releases_route_minutes
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech = fx.make_technician()
    rd = fx.make_route_day(tech["id"], capacity_minutes=300)
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    appt = fx.book_appointment(rd["id"], job["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90
    resp = api_client.transition_appointment(
        appt["id"], {"action": "NO_SHOW", "no_show_reason": "Customer not home"}, DISPATCHER
    )
    data = validate_success(resp, 200)
    assert data["status"] == "NO_SHOW"
    assert fx.get_route_day(rd["id"])["booked_minutes"] == 0


# ---------------------------------------------------------------- corner: computed booked read
def test_route_day_reports_booked_minutes():
    """PRD §3.3: "When a booking succeeds, the route day's `booked_minutes` grows
    by the new appointment's on-site minutes, and if the parent job was in `DRAFT`
    its `job_status` advances `DRAFT → SCHEDULED`."

    Design: Corner/endpoints/computed_read_routeday_booked_minutes
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech = fx.make_technician()
    rd = fx.make_route_day(tech["id"], capacity_minutes=300)
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    fx.book_appointment(rd["id"], job["id"], tech["id"], start_ts=APPT_START, end_ts=APPT_END_90)  # 90
    resp = api_client.get_route_day(rd["id"], DISPATCHER)
    data = validate_success(resp, 200)
    assert data["booked_minutes"] == 90


# ---------------------------------------------------------------- corner: FK route-day not found
def test_appointment_route_day_not_found():
    """PRD §2.9: "The same left-to-right rule governs foreign keys supplied in a
    request body: each referenced resource must exist, and the corresponding
    not-found error is raised for the first that does not."

    Design: Corner/errors/error_route_day_not_found_on_appointment_create
    """
    customer = fx.make_customer()
    chimney = fx.make_chimney(customer["id"])
    tech = fx.make_technician()
    job = fx.make_service_job(customer["id"], chimney["id"], inspection_level=1)
    resp = api_client.create_appointment(
        F.create_appointment_payload(route_day_id="00000000-0000-0000-0000-000000000000",
                                     service_job_id=job["id"], technician_id=tech["id"],
                                     start_ts=APPT_START, end_ts=APPT_END_90),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_NOT_FOUND)
