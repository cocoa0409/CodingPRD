"""CRUD, input validation, and per-request constraint tests.

Translated from SCAFFOLD_CORNER_DESIGN.yaml queue B instances under sections
`entities`, `validations`, and `endpoints`.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    create_rate_plan_payload,
    create_driver_payload,
    create_trip_payload,
    create_trip_event_payload,
    create_privacy_consent_payload,
    assert_rate_plan,
    TEST_USERS,
    make_driver_headers,
    set_clock,
    create_rate_plan,
    create_driver,
    create_enrollment,
    add_enrollment_trip,
    setup_bound_policy,
    add_policy_trip,
    get_policy,
    create_statement_payload,
)

UW = TEST_USERS["underwriting_headers"]


def test_create_rate_plan_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created plan has a `status` of `ACTIVE`."
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    and increments by one on every mutation of the resource".

    Design: Corner/entities/create_rate_plan_returns_201_with_defaults
    """
    payload = create_rate_plan_payload(
        name="TX UBI", state_code="TX", base_premium_cents=150000,
        per_mile_rate_cents=1.0, included_miles_per_period=800,
        hard_brake_weight=2.0, speeding_weight=1.0, phone_use_weight=1.0)
    res = api.create_rate_plan(payload, UW)
    plan = validate_success(res, 201)
    assert_rate_plan(plan)
    assert plan["status"] == "ACTIVE"
    assert plan["version"] == 1


def test_create_driver_missing_email_returns_validation(api):
    """PRD §2.5: "A request whose body is malformed — missing a required field or
    carrying a value of the wrong type — is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_driver_missing_email_returns_validation
    """
    payload = create_driver_payload(full_name="No Email", state_code="CA")
    del payload["email"]
    res = api.create_driver(payload, TEST_USERS["driver_headers"])
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_get_driver_nonexistent_returns_not_found(api):
    """PRD §2.5: "When a request addresses a resource by an `id` in its path, that
    `id` must resolve to an existing resource; if it does not, the request is
    rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_driver_nonexistent_returns_not_found
    """
    res = api.get_driver(NON_EXISTENT_UUID, UW)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_drivers_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_drivers_pagination_envelope
    """
    create_driver(email="p1-pagination@example.com")
    create_driver(email="p2-pagination@example.com")
    res = api.list_drivers(UW, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True


def test_driver_computed_lifetime_safe_miles_starts_zero(api):
    """PRD §3.2: "On creation a driver starts with `status` of `ACTIVE` ... with
    `telematics_opted_out` set to false and `lifetime_safe_miles` set to 0".

    Design: Corner/entities/driver_computed_lifetime_safe_miles_starts_zero
    """
    res = api.create_driver(create_driver_payload(email="comp-fresh@example.com"), UW)
    driver = validate_success(res, 201)
    assert driver["lifetime_safe_miles"] == 0
    assert driver["telematics_opted_out"] is False


def test_duplicate_email_registration_rejected(api):
    """PRD §3.2: "Email is unique on a case-insensitive basis; registering a second
    driver with an email that already exists (ignoring case) is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_email_registration_rejected
    """
    get_success_data(api.create_driver(create_driver_payload(email="dup-case@example.com"), UW))
    res = api.create_driver(create_driver_payload(email="DUP-CASE@example.com"), UW)
    validate_error(res, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_trip_ambiguous_parent_both_set_rejected(api):
    """PRD §3.5: "A request body that sets both parents or neither is rejected with
    `ERR_TRIP_PARENT_AMBIGUOUS`."

    Design: Corner/validations/trip_ambiguous_parent_both_set_rejected
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    payload = create_trip_payload(
        "2026-02-06T01:00:00Z", "2026-02-06T01:30:00Z", 10.0,
        policy_id=ctx["policy"]["id"], enrollment_id=ctx["enrollment"]["id"])
    res = api.create_trip(payload, ctx["dheaders"])
    validate_error(res, "ERR_TRIP_PARENT_AMBIGUOUS", expected_status=422)


def test_trip_time_order_violation_rejected(api):
    """PRD §3.5: "The `ended_at` instant must be strictly after `started_at`;
    otherwise the creation is rejected with `ERR_TRIP_TIME_ORDER`."

    Design: Corner/validations/trip_time_order_violation_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    payload = create_trip_payload(
        "2026-02-01T02:00:00Z", "2026-02-01T01:00:00Z", 10.0, enrollment_id=enrollment["id"])
    res = api.create_trip(payload, make_driver_headers(driver["id"]))
    validate_error(res, "ERR_TRIP_TIME_ORDER", expected_status=422)


def test_invalid_trip_distance_zero_rejected(api):
    """PRD §3.5: "The `distance_miles` must be greater than zero, both at trip
    creation and at accept time; a non-positive distance is rejected with
    `ERR_INVALID_TRIP_DISTANCE`."

    Design: Corner/validations/invalid_trip_distance_zero_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    payload = create_trip_payload(
        "2026-02-01T01:00:00Z", "2026-02-01T01:30:00Z", 0, enrollment_id=enrollment["id"])
    res = api.create_trip(payload, make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INVALID_TRIP_DISTANCE", expected_status=422)


def test_invalid_event_severity_out_of_range_rejected(api):
    """PRD §3.5: "A severity outside the 1-through-5 range, or an `event_type` not
    in the declared set, is rejected with `ERR_INVALID_EVENT`."

    Design: Corner/validations/invalid_event_severity_out_of_range_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    hdr = make_driver_headers(driver["id"])
    trip = get_success_data(api.create_trip(create_trip_payload(
        "2026-02-01T01:00:00Z", "2026-02-01T01:30:00Z", 10.0, enrollment_id=enrollment["id"]), hdr))
    res = api.create_trip_event(
        trip["id"], create_trip_event_payload("HARD_BRAKE", 6, "2026-02-01T01:10:00Z"), hdr)
    validate_error(res, "ERR_INVALID_EVENT", expected_status=422)


def test_consent_noop_revoke_when_already_opted_out(api):
    """PRD §3.2: "A consent change that would not alter the current opt-out state is a
    no-op and is rejected with `ERR_CONSENT_NOOP`; equivalently, a `REVOKE` while the
    driver is already opted out is rejected with `ERR_ALREADY_OPTED_OUT`, and a `GRANT`
    while the driver is not opted out is rejected with `ERR_NOT_OPTED_OUT`."

    PRD states the redundant-REVOKE outcome equivalently as ERR_CONSENT_NOOP or
    ERR_ALREADY_OPTED_OUT, so a faithful implementer may return either.

    Design: Corner/validations/consent_noop_revoke_when_already_opted_out
    """
    set_clock("2026-02-01T00:00:00Z")
    driver = create_driver(email="noop-consent@example.com")
    hdr = make_driver_headers(driver["id"])
    get_success_data(api.create_privacy_consent(
        driver["id"], create_privacy_consent_payload("REVOKE", reason="first"), hdr))
    res = api.create_privacy_consent(
        driver["id"], create_privacy_consent_payload("REVOKE", reason="again"), hdr)
    validate_error_is_one_of(res, ["ERR_CONSENT_NOOP", "ERR_ALREADY_OPTED_OUT"])


def test_trip_events_reverse_reachable_via_subresource(api):
    """PRD §3.5: "Attaching an event increments the trip's counter for that event
    type." PRD §3.5: "Events may be listed for a trip."

    Design: Corner/endpoints/trip_events_reverse_reachable_via_subresource
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    hdr = make_driver_headers(driver["id"])
    trip = get_success_data(api.create_trip(create_trip_payload(
        "2026-02-01T01:00:00Z", "2026-02-01T01:30:00Z", 10.0, enrollment_id=enrollment["id"]), hdr))
    get_success_data(api.create_trip_event(
        trip["id"], create_trip_event_payload("HARD_BRAKE", 2, "2026-02-01T01:05:00Z"), hdr))
    get_success_data(api.create_trip_event(
        trip["id"], create_trip_event_payload("SPEEDING", 3, "2026-02-01T01:06:00Z"), hdr))
    data, _meta = validate_paginated(api.list_trip_events(trip["id"], hdr))
    assert len(data) == 2
    assert all(ev["trip_id"] == trip["id"] for ev in data)


def test_scoring_window_expired_blocks_trip_accept(api):
    """PRD §3.5: "For an enrollment-bound trip, the enrollment must be in `SCORING` and
    the clock at or before its `scoring_deadline`, otherwise `ERR_SCORING_WINDOW_EXPIRED`."

    Design: Corner/validations/scoring_window_expired_blocks_trip_accept
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, scoring_days=1)
    hdr = make_driver_headers(driver["id"])
    trip = get_success_data(api.create_trip(create_trip_payload(
        "2026-02-01T01:00:00Z", "2026-02-01T01:30:00Z", 10.0, enrollment_id=enrollment["id"]), hdr))
    set_clock("2026-02-03T00:00:00Z")  # past the 1-day scoring deadline
    res = api.accept_trip(trip["id"], hdr)
    validate_error(res, "ERR_SCORING_WINDOW_EXPIRED", expected_status=409)


def test_open_trips_block_statement_creation(api):
    """PRD §3.6: "it requires that no `OPEN` trips remain in the current period window —
    every trip in the period must already be accepted or rejected — otherwise the
    creation is rejected with `ERR_OPEN_TRIPS_IN_PERIOD`."

    Design: Corner/validations/open_trips_block_statement_creation
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    # one OPEN (not accepted) policy trip remains in the period
    add_policy_trip(ctx, "2026-02-05T01:00:00Z", "2026-02-05T01:30:00Z", 10.0,
                    events=None, accept=False)
    p_ver = get_policy(ctx)["version"]
    res = api.create_statement(create_statement_payload(ctx["policy"]["id"], p_ver), UW)
    validate_error(res, "ERR_OPEN_TRIPS_IN_PERIOD", expected_status=409)
