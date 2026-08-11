"""Assignment progression: acceptance/confirm gates, check-in window, double-booking
buffer, VRI aggregate capacity, no-show grace, and interpreter ownership."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_interpreter_headers,
    set_clock,
    create_org,
    create_standard_rate_card,
    create_active_interpreter,
    create_vri_interpreter,
    create_vri_rate_card,
    add_availability,
    create_submitted_request,
    create_submitted_vri_request,
    offer_to,
    accept_assignment,
    confirm_assignment,
    get_assignment,
    get_request_version,
    create_offer_payload,
    setup_offered_assignment,
    setup_accepted_assignment,
    setup_confirmed_assignment,
    drive_to_checkout,
    assert_instant_equal,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def test_assignment_state_errors_bundle():
    """PRD §3.5: "Anything other than `ACCEPTED` is rejected with
    `ERR_ASSIGNMENT_NOT_ACCEPTED`; the interpreter must still be `ACTIVE`."
    PRD §3.5: "Check-out ends service, moving the assignment from `ON_SITE` to
    `COMPLETED` (any other status draws `ERR_ASSIGNMENT_NOT_ON_SITE`)."
    PRD §3.4: "the interpreter must be `ACTIVE` (else `ERR_INTERPRETER_NOT_ACTIVE`)".
    PRD §3.5: "Check-in is accepted only within the window that opens thirty minutes
    before `scheduled_start` and closes at `scheduled_end` — outside it,
    `ERR_CHECK_IN_WINDOW_VIOLATION` (HTTP 422) — and from any other status,
    `ERR_ASSIGNMENT_NOT_CONFIRMED`."

    Design: Corner/errors/assignment_state_errors_bundle
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    pending = get_success_data(api_client.create_interpreter(
        {"full_name": "Pete Pending", "modalities_offered": ["ASL_ONSITE"],
         "home_zip": "02139"}, ADMIN))

    req1 = create_submitted_request(org["id"])  # June 10 14:00-16:30
    a1 = offer_to(req1["id"], interp["id"])

    req2 = create_submitted_request(
        org["id"], consumer_name="Second Pat",
        scheduled_start="2026-06-12T14:00:00Z", scheduled_end="2026-06-12T15:00:00Z",
        estimated_mileage=5)
    a2 = offer_to(req2["id"], interp["id"])
    accept_assignment(a2)
    confirm_assignment(a2)

    req3 = create_submitted_request(
        org["id"], consumer_name="Third Pat",
        scheduled_start="2026-06-13T14:00:00Z", scheduled_end="2026-06-13T15:00:00Z",
        estimated_mileage=5)

    # e1: confirm an assignment still OFFERED.
    e1 = api_client.confirm_assignment(a1["id"], ADMIN)
    validate_error(e1, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED)

    # e2: check-out from EN_ROUTE (after a valid depart).
    get_success_data(api_client.depart_assignment(
        a2["id"], make_interpreter_headers(interp["id"])))
    e2 = api_client.check_out_assignment(
        a2["id"], {}, make_interpreter_headers(interp["id"]))
    validate_error(e2, ApiErrorId.ERR_ASSIGNMENT_NOT_ON_SITE)

    # e3: offer to a PENDING_ONBOARD interpreter.
    e3 = api_client.create_offer(
        req3["id"], create_offer_payload(pending["id"], get_request_version(req3["id"])),
        ADMIN)
    validate_error(e3, ApiErrorId.ERR_INTERPRETER_NOT_ACTIVE)

    # e4: check-in 31 minutes before scheduled_start (window opens 30 before).
    set_clock("2026-06-12T13:29:00Z")
    e4 = api_client.check_in_assignment(a2["id"], make_interpreter_headers(interp["id"]))
    validate_error(e4, ApiErrorId.ERR_CHECK_IN_WINDOW_VIOLATION)


def test_mark_no_show_before_grace_returns_too_early():
    """PRD §3.6: "A `PlatformAdmin` marks no-show on an assignment in `CONFIRMED` or
    `EN_ROUTE` (else `ERR_ASSIGNMENT_NOT_CONFIRMED`), but only once the logical time
    has reached fifteen minutes past the `scheduled_start` — earlier attempts are
    rejected with `ERR_NO_SHOW_TOO_EARLY`."
    PRD §3.6: "Link one: a strike is created for the interpreter with `occurred_at`
    set to the assignment's scheduled start and status `ACTIVE`."

    Design: Corner/errors/mark_no_show_before_grace_returns_too_early
    """
    ctx = setup_confirmed_assignment()
    asg_id = ctx["assignment"]["id"]
    set_clock("2026-06-10T14:10:00Z")  # start + 10 min, grace is 15
    early = api_client.mark_no_show(asg_id, ADMIN)
    validate_error(early, ApiErrorId.ERR_NO_SHOW_TOO_EARLY)
    set_clock("2026-06-10T14:16:00Z")  # start + 16 min
    marked = get_success_data(api_client.mark_no_show(asg_id, ADMIN))
    assert marked["status"] == "NO_SHOW"
    interp = get_success_data(api_client.get_interpreter(ctx["interpreter"]["id"], ADMIN))
    assert interp["active_strike_count"] == 1, "the no-show strike joins the rolling window"


def test_checkout_creates_encounter_with_computed_times():
    """PRD §3.5: "Check-out stamps the encounter's `actual_end`, computes
    `actual_minutes` as the elapsed time from `actual_start` rounded up to whole
    minutes, sets `billable_minutes` to the greater of `actual_minutes` and the
    assignment's `pinned_minimum_billable_minutes`, and arms the `verify_deadline`
    seventy-two hours after `actual_end`. The request deliberately remains
    `IN_PROGRESS` — it cannot complete until the encounter is verified."
    PRD §3.5: "Here the interpreter may attach travel claims: `travel_minutes_claimed`
    for round-trip travel time and `mileage_claimed` for round-trip miles, each
    optional, each zero or more, each defaulting to zero."

    Design: Corner/state_machines/checkout_creates_encounter_with_computed_times
    """
    ctx = setup_confirmed_assignment()
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 12})
    asg = ctx["assignment"]
    assert asg["status"] == "COMPLETED"
    assert asg["travel_minutes_claimed"] == 90
    assert asg["mileage_claimed"] == 12
    enc = ctx["encounter"]
    assert_instant_equal(enc["actual_start"], "2026-06-10T14:00:00Z", "actual_start")
    assert_instant_equal(enc["actual_end"], "2026-06-10T16:10:00Z", "actual_end")
    assert enc["actual_minutes"] == 130, "elapsed 14:00 -> 16:10 is 130 whole minutes"
    assert enc["billable_minutes"] == 130, "max(130 actual, 120 minimum)"
    assert_instant_equal(enc["verify_deadline"], "2026-06-13T16:10:00Z",
                         "verify_deadline = actual_end + 72h")
    assert enc["verified"] is False
    assert ctx["request"]["status"] == "IN_PROGRESS", (
        "check-out alone must not complete the request"
    )


def test_double_booking_buffer_reject_then_boundary_allow():
    """PRD §3.5: "The buffered double-booking check expands every other `CONFIRMED`,
    `EN_ROUTE`, or `ON_SITE` assignment of the same interpreter by a thirty-minute
    travel buffer on each side and rejects the confirm with
    `ERR_INTERPRETER_DOUBLE_BOOKED` when the new assignment's buffered interval
    starts before another's buffered interval ends and ends after that other's
    buffered start — the buffered intervals are half-open, so a new assignment
    starting exactly thirty minutes after another's scheduled end is allowed."

    Design: Corner/validations/double_booking_buffer_reject_then_boundary_allow
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-16T00:00:00Z", "2026-06-17T00:00:00Z")

    def _confirmed_or_accepted(start, end, consumer):
        req = create_submitted_request(
            org["id"], consumer_name=consumer, scheduled_start=start,
            scheduled_end=end, estimated_mileage=5)
        asg = offer_to(req["id"], interp["id"])
        accept_assignment(asg)
        return asg

    a1 = _confirmed_or_accepted("2026-06-16T10:00:00Z", "2026-06-16T11:00:00Z", "A One")
    confirm_assignment(a1)  # buffered span [09:30, 11:30)

    a2 = _confirmed_or_accepted("2026-06-16T11:30:00Z", "2026-06-16T12:30:00Z", "B Two")
    e_db = api_client.confirm_assignment(a2["id"], ADMIN)
    validate_error(e_db, ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED)

    # 12:00 start => buffered [11:30, 13:30) touches [09:30, 11:30) — allowed.
    a3 = _confirmed_or_accepted("2026-06-16T12:00:00Z", "2026-06-16T13:00:00Z", "C Three")
    ok = api_client.confirm_assignment(a3["id"], ADMIN)
    data = validate_success(ok, 200)
    assert data["status"] == "CONFIRMED", (
        "a start exactly thirty minutes after another's scheduled end is allowed"
    )


def test_interpreter_cannot_accept_others_assignment():
    """PRD §3.5: "Every interpreter action on an assignment requires self-ownership:
    the assignment's `interpreter_id` must equal the caller's `X-User-ID`, failing
    which the call is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/interpreter_cannot_accept_others_assignment
    """
    ctx = setup_offered_assignment()
    other = get_success_data(api_client.create_interpreter(
        {"full_name": "Bob Other", "modalities_offered": ["ASL_ONSITE"],
         "home_zip": "02140"}, ADMIN))
    resp = api_client.accept_assignment(
        ctx["assignment"]["id"], make_interpreter_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert get_assignment(ctx["assignment"]["id"])["status"] == "OFFERED"


def test_billing_clerk_cannot_mark_no_show():
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." and "a
    `BillingClerk` generates, issues, voids, and settles invoices and voids credits
    but cannot adjudicate complaints or dispatch assignments".
    PRD §4: POST /assignments/{id}/mark-no-show is authorized for PlatformAdmin only.

    Design: Corner/rbac/billing_clerk_cannot_mark_no_show
    """
    ctx = setup_offered_assignment()
    resp = api_client.mark_no_show(ctx["assignment"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_assignment(ctx["assignment"]["id"])["status"] == "OFFERED"


# ─── Difficulty: priority_pair_validation_conflict (state vs temporal) ──

def _setup_accepted_two_hours_before_start():
    ctx = setup_accepted_assignment()
    set_clock("2026-06-10T12:00:00Z")  # two hours before the 14:00 start
    return ctx


def test_checkin_not_confirmed_returns_state_error_not_window_error():
    """PRD §2.10: "When several validations could reject the same request, they are
    evaluated in a fixed twelve-tier order, and the earliest failing tier determines
    the error returned." and "Eighth, resource from-state preconditions per the state
    machines — the `ERR_REQUEST_NOT_*`, `ERR_ASSIGNMENT_NOT_*`, ... family
    (HTTP 409). ... Tenth, temporal rules (`ERR_INVALID_SCHEDULE`,
    `ERR_CHECK_IN_WINDOW_VIOLATION`, `ERR_NO_SHOW_TOO_EARLY`; HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/checkin_not_confirmed_and_too_early_returns_state_error
    """
    ctx = _setup_accepted_two_hours_before_start()
    resp = api_client.check_in_assignment(
        ctx["assignment"]["id"],
        make_interpreter_headers(ctx["interpreter"]["id"]))
    # Both the from-state (tier 8) and the window (tier 10) are violated; tier 8 wins.
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CONFIRMED)


def test_checkin_state_failure_leaves_assignment_untouched():
    """PRD §3.5: "Check-in creates the encounter, exactly one per assignment" — a
    rejected check-in creates none. PRD §2.10: "the earliest failing tier determines
    the error returned" (state tier over temporal tier).

    Design: Difficulty/priority_pair_validation_conflict/checkin_not_confirmed_and_too_early_returns_state_error
    """
    ctx = _setup_accepted_two_hours_before_start()
    resp = api_client.check_in_assignment(
        ctx["assignment"]["id"],
        make_interpreter_headers(ctx["interpreter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CONFIRMED)
    assert get_assignment(ctx["assignment"]["id"])["status"] == "ACCEPTED"
    rows = get_success_data(api_client.list_assignment_encounters(
        ctx["assignment"]["id"], ADMIN))
    assert rows == [], "no encounter may be materialized by a rejected check-in"


# ─── Difficulty: resource_temporal_overlap / VRI aggregate capacity ────

def _setup_vri_capacity_scenario():
    """Org + VRI card + four certified VRI interpreters + four requests all
    scheduled 2026-06-15T10:00:00Z-11:00:00Z; interpreters 1..3 CONFIRMED."""
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="State Univ", org_type="EDUCATION")
    create_vri_rate_card()
    interps = [create_vri_interpreter(full_name=f"Vee {n}")
               for n in ("One", "Two", "Three", "Four")]
    requests = [
        create_submitted_vri_request(org["id"]) for _ in range(4)
    ]
    confirmed = []
    for i in range(3):
        asg = offer_to(requests[i]["id"], interps[i]["id"])
        accept_assignment(asg)
        confirmed.append(confirm_assignment(asg))
    a4 = offer_to(requests[3]["id"], interps[3]["id"])
    accept_assignment(a4)
    return {"org": org, "interpreters": interps, "requests": requests,
            "confirmed": confirmed, "a4": a4}


def test_vri_capacity_first_three_overlapping_confirms_allowed():
    """PRD §3.5: "For VRI only, the aggregate capacity check counts every VRI
    assignment platform-wide in `CONFIRMED`, `EN_ROUTE`, or `ON_SITE` whose
    scheduled span overlaps the new one (half-open overlap): three overlapping
    sessions are allowed, and confirming a fourth is rejected with
    `ERR_VRI_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/vri_aggregate_capacity_third_allowed_fourth_rejected
    """
    scenario = _setup_vri_capacity_scenario()
    for asg in scenario["confirmed"]:
        assert asg["status"] == "CONFIRMED", (
            "overlap counts 0, 1, 2 are all below the capacity of 3"
        )


def test_vri_capacity_fourth_overlapping_confirm_rejected():
    """PRD §3.5: "three overlapping sessions are allowed, and confirming a fourth is
    rejected with `ERR_VRI_CAPACITY_EXCEEDED`."
    PRD §3.5: "Confirmation is the dispatcher's second gate, moving an `ACCEPTED`
    assignment to `CONFIRMED`." — a rejected confirm leaves the assignment ACCEPTED.

    Design: Difficulty/resource_temporal_overlap/vri_aggregate_capacity_third_allowed_fourth_rejected
    """
    scenario = _setup_vri_capacity_scenario()
    resp = api_client.confirm_assignment(scenario["a4"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_VRI_CAPACITY_EXCEEDED)
    assert get_assignment(scenario["a4"]["id"])["status"] == "ACCEPTED"
