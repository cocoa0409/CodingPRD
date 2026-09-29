"""Two interval rules with opposite edge semantics: half-open terms, closed windows."""
from test_helpers import (
    accept_assignment,
    api_client,
    ApiErrorId,
    assignment_for_application,
    bootstrap_plan,
    certify_application,
    create_applicant_with_vehicle,
    create_assignment_cycle_payload,
    create_policy_payload,
    file_two_market_rejections,
    make_plan_administrator_headers,
    make_servicing_carrier_headers,
    read_application,
    read_assignment,
    read_assignment_cycle,
    read_policy,
    record_deposit,
    run_cycle,
    schedule_cycle,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verify_mvr,
)

ADMIN_HEADERS = make_plan_administrator_headers()


def _one_vehicle_two_accepted_assignments_and_a_first_policy():
    """Two applications on one vehicle, placed with different carriers, one written.

    The first policy runs 2026-09-15 to 2027-09-15. The clock is then advanced to
    2027-09-14 so that a second term can be asked for either one day early, which
    intersects the first, or exactly on the boundary, which does not.
    """
    env = bootstrap_plan()
    atlas, beacon = env["carriers"]
    applicant, vehicle = create_applicant_with_vehicle(
        {"full_name": "Owen Pike", "driver_license_number": "D-99011"})
    applications = []
    for requested_effective_date, prefix in (("2026-09-15T00:00:00Z", "DEC-26"),
                                             ("2027-09-15T00:00:00Z", "DEC-27")):
        application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"],
                                        requested_effective_date=requested_effective_date)
        file_two_market_rejections(application["id"], env["producer"]["id"],
                                   document_prefix=prefix)
        verify_mvr(application["id"], [])
        record_deposit(application["id"], env["producer"]["id"], 38939)
        certify_application(application["id"])
        applications.append(read_application(application["id"]))

    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    first_assignment = assignment_for_application(applications[0]["id"])
    second_assignment = assignment_for_application(applications[1]["id"])
    assert first_assignment["carrier_id"] == atlas["id"]
    assert second_assignment["carrier_id"] == beacon["id"]
    accept_assignment(first_assignment["id"], atlas["id"])
    accept_assignment(second_assignment["id"], beacon["id"])

    set_clock("2026-09-15T00:00:00Z")
    first_policy = validate_success(api_client.create_policy(
        create_policy_payload(first_assignment["id"], policy_number="AR-100011",
                              effective_date="2026-09-15T00:00:00Z",
                              expiration_date="2027-09-15T00:00:00Z"),
        make_servicing_carrier_headers(atlas["id"])), 201)
    set_clock("2027-09-14T00:00:00Z")
    return {"beacon": beacon, "first_policy": first_policy,
            "second_assignment": second_assignment}


def _issue_second_term(world, effective_date: str, expiration_date: str):
    return api_client.create_policy(
        create_policy_payload(world["second_assignment"]["id"],
                              policy_number="AR-100012",
                              effective_date=effective_date,
                              expiration_date=expiration_date),
        make_servicing_carrier_headers(world["beacon"]["id"]))


def test_a_second_term_starting_one_day_early_truly_intersects_and_is_refused():
    """One day of overlap on the same vehicle is a genuine intersection.

    A term running 2027-09-14 to 2028-09-13 is exactly 365 days long, so the term
    length gate is satisfied and the refusal is not about the arithmetic. It
    overlaps the first policy's last day, and any true intersection on the same
    vehicle is refused. No policy row is written and the assignment is still merely
    accepted.

    PRD: "And no other policy on the same vehicle may have a term that intersects
    the requested one: terms are treated as half-open intervals running from the
    `effective_date` inclusive to the `expiration_date` exclusive, so exact
    adjacency — a new `effective_date` equal to a prior policy's `expiration_date` —
    is permitted, while any true intersection is refused with
    `ERR_POLICY_TERM_OVERLAP` and HTTP 409."
    Design: Difficulty/resource_temporal_overlap/vehicle_policy_terms_are_half_open_so_adjacency_is_legal
    """
    world = _one_vehicle_two_accepted_assignments_and_a_first_policy()

    response = _issue_second_term(world, "2027-09-14T00:00:00Z", "2028-09-13T00:00:00Z")

    error = validate_error(response, ApiErrorId.ERR_POLICY_TERM_OVERLAP, 409)
    assert error["error_id"] != ApiErrorId.ERR_POLICY_TERM_INVALID
    _, meta = validate_paginated(api_client.list_policies(
        ADMIN_HEADERS, params={"assignment_id": world["second_assignment"]["id"]}))
    assert meta["total_count"] == 0
    assert read_assignment(world["second_assignment"]["id"])["status"] == "ACCEPTED"


def test_a_second_term_starting_exactly_where_the_first_ends_is_permitted():
    """Because the interval is half-open, the boundary day belongs to the new term.

    Shifting the requested start by a single day to the first policy's expiration
    instant makes the two terms exactly adjacent rather than intersecting, and the
    issuance succeeds. Both policies are then in force on the same vehicle, the
    second is rated from scratch at its own effective date, and its assignment
    advances while its carrier picks up the risk.

    PRD: "And no other policy on the same vehicle may have a term that intersects
    the requested one: terms are treated as half-open intervals running from the
    `effective_date` inclusive to the `expiration_date` exclusive, so exact
    adjacency — a new `effective_date` equal to a prior policy's `expiration_date` —
    is permitted, while any true intersection is refused with
    `ERR_POLICY_TERM_OVERLAP` and HTTP 409."
    Design: Difficulty/resource_temporal_overlap/vehicle_policy_terms_are_half_open_so_adjacency_is_legal
    """
    world = _one_vehicle_two_accepted_assignments_and_a_first_policy()
    validate_error(
        _issue_second_term(world, "2027-09-14T00:00:00Z", "2028-09-13T00:00:00Z"),
        ApiErrorId.ERR_POLICY_TERM_OVERLAP, 409)

    second_policy = validate_success(
        _issue_second_term(world, "2027-09-15T00:00:00Z", "2028-09-14T00:00:00Z"), 201)

    assert second_policy["effective_date"][:10] == "2027-09-15"
    assert second_policy["expiration_date"][:10] == "2028-09-14"
    assert second_policy["effective_date"] == world["first_policy"]["expiration_date"]
    assert second_policy["policy_status"] == "IN_FORCE"
    assert read_policy(world["first_policy"]["id"])["policy_status"] == "IN_FORCE"
    assert second_policy["final_premium_cents"] == 148337
    assert second_policy["total_annual_charge_cents"] == 155754
    assert read_assignment(world["second_assignment"]["id"])["status"] == "POLICY_ISSUED"


def _period_with_one_september_cycle():
    """A period running September through November with a September cycle scheduled."""
    env = bootstrap_plan()
    cycle = schedule_cycle(env["plan_period"]["id"])
    assert cycle["window_end"][:10] == "2026-09-30"
    return env, cycle


def _schedule_second_cycle(env, window_start: str, window_end: str):
    return api_client.create_assignment_cycle(
        create_assignment_cycle_payload(env["plan_period"]["id"],
                                        window_start=window_start,
                                        window_end=window_end),
        ADMIN_HEADERS)


def test_a_cycle_window_abutting_the_previous_one_is_refused():
    """Adjacency is not enough here: the plan wants a clear settlement day between runs.

    A window opening on 2026-10-01 merely abuts the September window that closed on
    2026-09-30, leaving no clear day between the two. Cycle windows are closed
    intervals, so that abutment is a conflict and the earlier cycle is left exactly
    as it was.

    PRD: "Unlike policy terms, cycle windows are closed intervals and mere adjacency
    is refused — the plan requires a clear settlement day between runs — so an
    overlap or a mere abutment is refused with `ERR_CYCLE_WINDOW_CONFLICT` and HTTP
    409."
    Design: Difficulty/resource_temporal_overlap/assignment_cycle_windows_are_closed_and_demand_one_clear_day
    """
    env, september = _period_with_one_september_cycle()

    response = _schedule_second_cycle(env, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")

    validate_error(response, ApiErrorId.ERR_CYCLE_WINDOW_CONFLICT, 409)
    assert read_assignment_cycle(september["id"])["window_end"][:10] == "2026-09-30"
    _, meta = validate_paginated(api_client.list_assignment_cycles(
        env["plan_period"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_a_cycle_window_starting_two_days_after_the_previous_end_is_accepted():
    """Two days after the sibling's end is the first admissible start.

    Moving the requested start one day later to 2026-10-02 leaves 2026-10-01 clear,
    which is exactly what the separation rule demands. The cycle is scheduled with
    both of its counters at zero, and the period now carries two cycles.

    PRD: "And the cycle window must be separated from every sibling cycle window of
    the same period by at least one clear day: the new window's start must be at
    least two days after a sibling's end, or the new window's end must be at least
    two days before a sibling's start."
    Design: Difficulty/resource_temporal_overlap/assignment_cycle_windows_are_closed_and_demand_one_clear_day
    """
    env, september = _period_with_one_september_cycle()
    validate_error(
        _schedule_second_cycle(env, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z"),
        ApiErrorId.ERR_CYCLE_WINDOW_CONFLICT, 409)

    october = validate_success(
        _schedule_second_cycle(env, "2026-10-02T00:00:00Z", "2026-10-31T00:00:00Z"), 201)

    assert october["window_start"][:10] == "2026-10-02"
    assert october["status"] == "SCHEDULED"
    assert october["assigned_count"] == 0
    assert october["deferred_count"] == 0
    _, meta = validate_paginated(api_client.list_assignment_cycles(
        env["plan_period"]["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 2
    assert read_assignment_cycle(september["id"])["window_end"][:10] == "2026-09-30"
