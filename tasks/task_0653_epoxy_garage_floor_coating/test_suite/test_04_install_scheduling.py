"""Install booking guards: validation precedence on booking, the discrete
crew same-day collision, the continuous site cure-window overlap, the cure
deadline inclusive boundary on mark-cured, crew capacity, and the conserved
crew-day occupancy under book-then-cancel.
"""
from test_helpers import (
    api_client, TEST_USERS, get_success_data, validate_success, validate_error,
    make_customer_headers, make_crew_headers, set_clock,
    setup_accepted_project, setup_sent_quote, setup_completed_install,
    create_system_with_color, create_customer, create_project, record_assessment,
    create_estimate_quote, send_quote, project_version, create_crew, book_install,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_install_book
# ===========================================================================
def test_sales_state_error_outranks_capacity_error():
    """PRD §2.8: "on install booking the cross-dimension acceptance guard is
    evaluated before the metallic-crew check, which is evaluated before the
    same-day collision check, which is evaluated before the cure-window overlap
    check, which is evaluated before the capacity check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_install_book
    """
    # QUOTED (not ACCEPTED) project + tiny crew (priced_sqft would exceed capacity).
    h = setup_sent_quote(family="FLAKE", sku="FLAKE_STANDARD")  # leaves project QUOTED
    tiny = create_crew("Tiny Crew", metallic_certified=False, max_sqft_per_day=100)
    resp = api_client.create_install_job(
        h["project"]["id"], {"crew_id": tiny["id"], "install_date": "2026-05-10T09:00:00Z"},
        SCHED,
    )
    validate_error(resp, "ERR_SALES_NOT_ACCEPTED")


def test_sales_state_precedence_returns_409_status():
    """PRD §5: the error catalogue maps `ERR_SALES_NOT_ACCEPTED` to "409 Conflict".
    PRD §2.8: "the cross-dimension acceptance guard is evaluated before ... the
    capacity check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_install_book
    """
    h = setup_sent_quote(family="FLAKE", sku="FLAKE_STANDARD")  # QUOTED, not ACCEPTED
    tiny = create_crew("Tiny Crew B", metallic_certified=False, max_sqft_per_day=100)
    resp = api_client.create_install_job(
        h["project"]["id"], {"crew_id": tiny["id"], "install_date": "2026-05-10T09:00:00Z"},
        SCHED,
    )
    assert resp.status_code == 409, (
        f"state precondition error (ERR_SALES_NOT_ACCEPTED) is 409, not the "
        f"capacity error's 422; got {resp.status_code}"
    )


# ===========================================================================
# Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_install_book
# ===========================================================================
def test_metallic_safety_error_outranks_same_day_collision():
    """PRD §2.8: "the metallic-crew check, which is evaluated before the same-day
    collision check".
    PRD §3.6: "a metallic job sent to an uncertified crew is rejected with
    `ERR_CREW_NOT_METALLIC_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_install_book
    """
    # Non-certified crew already booked on 2026-05-10 by a FLAKE project.
    crew_nc = create_crew("NonCert Crew", metallic_certified=False, max_sqft_per_day=2000)
    flake = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    book_install(flake["project"]["id"], crew_nc["id"], install_date="2026-05-10T09:00:00Z")
    # METALLIC accepted project tries to book the same non-certified crew same day.
    met = setup_accepted_project(
        family="METALLIC", sku="METALLIC", install_season="PEAK",
        assessment_kwargs={
            "measured_sqft": 600, "oil_stain_pct": 100, "crack_density": 50,
            "crack_linear_ft": 30, "spalling": False, "moisture_pct": 0,
        },
    )
    resp = api_client.create_install_job(
        met["project"]["id"],
        {"crew_id": crew_nc["id"], "install_date": "2026-05-10T14:00:00Z"},
        SCHED,
    )
    validate_error(resp, "ERR_CREW_NOT_METALLIC_CERTIFIED")


def test_metallic_safety_precedence_returns_422_status():
    """PRD §5: the error catalogue maps `ERR_CREW_NOT_METALLIC_CERTIFIED` to "422
    Unprocessable Entity".
    PRD §2.8: "the metallic-crew check, which is evaluated before the same-day
    collision check".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_install_book
    """
    crew_nc = create_crew("NonCert Crew B", metallic_certified=False, max_sqft_per_day=2000)
    flake = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    book_install(flake["project"]["id"], crew_nc["id"], install_date="2026-05-10T09:00:00Z")
    met = setup_accepted_project(
        family="METALLIC", sku="METALLIC", install_season="PEAK",
        assessment_kwargs={
            "measured_sqft": 600, "oil_stain_pct": 100, "crack_density": 50,
            "crack_linear_ft": 30, "spalling": False, "moisture_pct": 0,
        },
    )
    resp = api_client.create_install_job(
        met["project"]["id"],
        {"crew_id": crew_nc["id"], "install_date": "2026-05-10T14:00:00Z"},
        SCHED,
    )
    assert resp.status_code == 422, (
        f"safety error (ERR_CREW_NOT_METALLIC_CERTIFIED) is 422, not the same-day "
        f"collision error's 409; got {resp.status_code}"
    )


# ===========================================================================
# Difficulty/resource_temporal_overlap/crew_same_day_double_booking_rejected
# ===========================================================================
def test_crew_same_day_double_booking_rejected():
    """PRD §3.6: "the chosen crew may not already hold another install job in
    `BOOKED` or `IN_PROGRESS` status whose `install_date` falls on the same UTC
    calendar day - collision is decided purely by whether the two dates land in
    the same day bucket, and a clash is rejected with
    `ERR_CREW_DAY_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_same_day_double_booking_rejected
    """
    crew = create_crew("Crew Flake A", metallic_certified=False, max_sqft_per_day=2000)
    p1 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD",
                                customer_id=None)
    book_install(p1["project"]["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    p2 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    resp = api_client.create_install_job(
        p2["project"]["id"],
        {"crew_id": crew["id"], "install_date": "2026-05-10T14:00:00Z"},  # same day, 5h later
        SCHED,
    )
    validate_error(resp, "ERR_CREW_DAY_DOUBLE_BOOKED")


def test_crew_different_day_booking_succeeds():
    """PRD §3.6: "the chosen crew may not already hold another install job in
    `BOOKED` or `IN_PROGRESS` status whose `install_date` falls on the same UTC
    calendar day - collision is decided purely by whether the two dates land in
    the same day bucket".

    Design: Difficulty/resource_temporal_overlap/crew_same_day_double_booking_rejected
    """
    # crew_capacity large; site cure windows do not overlap because the two
    # projects belong to DIFFERENT customers (the site check is per-customer).
    crew = create_crew("Crew Flake C", metallic_certified=False, max_sqft_per_day=2000)
    p1 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    book_install(p1["project"]["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    p2 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    booked = validate_success(api_client.create_install_job(
        p2["project"]["id"],
        {"crew_id": crew["id"], "install_date": "2026-05-20T09:00:00Z"},  # different day bucket
        SCHED,
    ), expected_status=201)
    assert booked["status"] == "BOOKED", (
        f"same crew on a DIFFERENT calendar day should book, got {booked['status']}"
    )


# ===========================================================================
# Difficulty/resource_temporal_overlap/site_cure_window_continuous_overlap_rejected
# ===========================================================================
def test_site_cure_window_overlap_rejected_different_crew():
    """PRD §3.6: "the new job's cure window - the half-open interval running from
    its `install_date` up to but not including its `vehicle_traffic_ok_at` - may
    not overlap the cure window of any other non-terminal install job (one in
    `BOOKED`, `IN_PROGRESS`, or `COMPLETED`) belonging to a *different* project of
    the *same* customer ... A genuine overlap is rejected with
    `ERR_SITE_CURE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/site_cure_window_continuous_overlap_rejected
    """
    cust = create_customer("Solo Owner", email="solo@example.com")
    crew_a = create_crew("Crew A", metallic_certified=False, max_sqft_per_day=2000)
    crew_b = create_crew("Crew B", metallic_certified=False, max_sqft_per_day=2000)
    # First project booked crew_a 2026-05-10 (cure window ends 2026-05-13T17:00).
    p1 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD", customer_id=cust["id"])
    book_install(p1["project"]["id"], crew_a["id"], install_date="2026-05-10T09:00:00Z")
    # Same customer, second project, 2026-05-12 falls inside first window; diff crew.
    p2 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD", customer_id=cust["id"])
    resp = api_client.create_install_job(
        p2["project"]["id"],
        {"crew_id": crew_b["id"], "install_date": "2026-05-12T09:00:00Z"},
        SCHED,
    )
    validate_error(resp, "ERR_SITE_CURE_WINDOW_OVERLAP")


def test_site_cure_window_touching_endpoints_do_not_overlap():
    """PRD §3.6: "Two windows that merely touch at an endpoint, where one window's
    `vehicle_traffic_ok_at` equals the other's `install_date`, do not overlap."

    Design: Difficulty/resource_temporal_overlap/site_cure_window_continuous_overlap_rejected
    """
    cust = create_customer("Touch Owner", email="touch@example.com")
    crew_a = create_crew("Crew A2", metallic_certified=False, max_sqft_per_day=2000)
    crew_b = create_crew("Crew B2", metallic_certified=False, max_sqft_per_day=2000)
    # First FLAKE install 2026-05-10T09:00; cure window ends 2026-05-13T17:00.
    p1 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD", customer_id=cust["id"])
    book_install(p1["project"]["id"], crew_a["id"], install_date="2026-05-10T09:00:00Z")
    # Second install starts exactly at the first window's vehicle_traffic_ok_at.
    p2 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD", customer_id=cust["id"])
    booked = validate_success(api_client.create_install_job(
        p2["project"]["id"],
        {"crew_id": crew_b["id"], "install_date": "2026-05-13T17:00:00Z"},  # touches, no overlap
        SCHED,
    ), expected_status=201)
    assert booked["status"] == "BOOKED", (
        f"touching endpoints do not overlap; booking should succeed, got {booked['status']}"
    )


# ===========================================================================
# Difficulty/boundary_precision_check/cure_window_deadline_inclusive_on_mark_cured
# ===========================================================================
def test_mark_cured_one_second_before_deadline_rejected():
    """PRD §3.6: "This is permitted only when the logical clock has reached or
    passed the job's `vehicle_traffic_ok_at`; an early attempt is rejected with
    `ERR_CURE_WINDOW_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/cure_window_deadline_inclusive_on_mark_cured
    """
    # FLAKE: install_date 05-10T09:00, install_end 17:00, vehicle_traffic_ok_at 05-13T17:00.
    h = setup_completed_install(
        family="FLAKE", sku="FLAKE_STANDARD",
        install_date="2026-05-10T09:00:00Z",
        as_measured_sqft=600, as_measured_crack_ft=15,
    )
    set_clock("2026-05-13T16:59:59Z")  # one second before deadline
    resp = api_client.mark_cured(h["install_job"]["id"], SCHED)
    validate_error(resp, "ERR_CURE_WINDOW_NOT_ELAPSED")


def test_mark_cured_at_exact_deadline_succeeds():
    """PRD §3.6: "After the cure deadline has passed, a `Scheduler` **marks the
    floor cured**, moving the install job's `status` from `COMPLETED` to `CURED`
    and the build track from `CURING` to `COMPLETE`. This is permitted only when
    the logical clock has reached or passed the job's `vehicle_traffic_ok_at`".

    Design: Difficulty/boundary_precision_check/cure_window_deadline_inclusive_on_mark_cured
    """
    h = setup_completed_install(
        family="FLAKE", sku="FLAKE_STANDARD",
        install_date="2026-05-10T09:00:00Z",
        as_measured_sqft=600, as_measured_crack_ft=15,
    )
    set_clock("2026-05-13T17:00:00Z")  # exactly vehicle_traffic_ok_at -> inclusive
    job = validate_success(api_client.mark_cured(h["install_job"]["id"], SCHED))
    assert job["status"] == "CURED", f"expected CURED at exact deadline, got {job['status']}"


# ===========================================================================
# Difficulty/compensating_invariant/crew_day_occupancy_conserved_on_book_then_cancel
# ===========================================================================
def test_crew_day_freed_after_cancel_allows_rebook():
    """PRD §3.8: "any install job on the project in `BOOKED` or `IN_PROGRESS` is
    moved to `CANCELLED`, which frees the crew's day for that date."

    Design: Difficulty/compensating_invariant/crew_day_occupancy_conserved_on_book_then_cancel
    """
    crew = create_crew("Crew Flake A", metallic_certified=False, max_sqft_per_day=2000)
    p1 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    book_install(p1["project"]["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    p2 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    # Cancel p1, freeing crew's 2026-05-10 slot.
    pv1 = project_version(p1["project"]["id"], headers=ADMIN)
    validate_success(api_client.cancel_project(
        p1["project"]["id"], {"expected_project_version": pv1}, ADMIN
    ))
    rebook = validate_success(api_client.create_install_job(
        p2["project"]["id"],
        {"crew_id": crew["id"], "install_date": "2026-05-10T09:00:00Z"},
        SCHED,
    ), expected_status=201)
    assert rebook["status"] == "BOOKED", (
        f"re-book on freed crew/day should succeed BOOKED, got {rebook['status']}"
    )


def test_cancel_moves_booked_install_job_to_cancelled():
    """PRD §3.8: "On a successful cancel, any install job on the project in
    `BOOKED` or `IN_PROGRESS` is moved to `CANCELLED`, which frees the crew's day
    for that date."

    Design: Difficulty/compensating_invariant/crew_day_occupancy_conserved_on_book_then_cancel
    """
    crew = create_crew("Crew Flake D", metallic_certified=False, max_sqft_per_day=2000)
    p1 = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    job = book_install(p1["project"]["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    pv = project_version(p1["project"]["id"], headers=ADMIN)
    validate_success(api_client.cancel_project(
        p1["project"]["id"], {"expected_project_version": pv}, ADMIN
    ))
    jobs = get_success_data(api_client.list_project_install_jobs(p1["project"]["id"], SCHED))
    cancelled = next(j for j in jobs if j["id"] == job["id"])
    assert cancelled["status"] == "CANCELLED", (
        f"cancel must move the BOOKED install job to CANCELLED, got {cancelled['status']}"
    )


# ===========================================================================
# Corner/validations/crew_capacity_exceeded_on_accepted_project
# ===========================================================================
def test_crew_capacity_exceeded_in_isolation():
    """PRD §3.6: "the accepted quote's `priced_sqft` must not exceed the crew's
    `max_sqft_per_day`, or the booking is rejected with
    `ERR_CREW_CAPACITY_EXCEEDED`."

    Design: Corner/validations/crew_capacity_exceeded_on_accepted_project
    """
    h = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")  # priced_sqft 600
    small = create_crew("Small Crew", metallic_certified=False, max_sqft_per_day=300)
    resp = api_client.create_install_job(
        h["project"]["id"], {"crew_id": small["id"], "install_date": "2026-05-10T09:00:00Z"},
        SCHED,
    )
    validate_error(resp, "ERR_CREW_CAPACITY_EXCEEDED")
