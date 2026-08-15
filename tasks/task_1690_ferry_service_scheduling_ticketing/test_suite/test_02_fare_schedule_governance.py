"""Fare schedule governance: the revision loop, fuel surcharge tiers pinned
at submission, window integrity, rejection finality, OCC on the route
version, and the fixed logical clock default."""
from test_helpers import (
    ApiErrorId,
    assert_fare_schedule,
    create_fare_schedule,
    create_fare_schedule_payload,
    create_route,
    get_route,
    submit_and_approve,
    submit_fare_schedule,
    set_clock,
    validate_error,
    validate_success,
)


def test_revision_loop_reopens_draft_then_approves(api, scheduler_admin_headers):
    """PRD §3.2: "Returning for revision moves it `SUBMITTED → DRAFT` — the
    revision loop — after which the schedule may be edited and resubmitted
    through the same path."
    PRD §3.2: "Approval moves the schedule `SUBMITTED → APPROVED`."

    Design: Difficulty/non_linear_state_machine/fare_schedule_revision_loop
    """
    route = create_route(route_code="SEA-BI")
    fs = create_fare_schedule(route["id"], route_version=route["version"])
    assert fs["status"] == "DRAFT"

    submitted = submit_fare_schedule(fs["id"], 350)
    assert submitted["status"] == "SUBMITTED"

    returned = validate_success(
        api.return_fare_schedule_for_revision(fs["id"], scheduler_admin_headers)
    )
    assert returned["status"] == "DRAFT", (
        f"return-for-revision must land back in DRAFT, got {returned['status']}"
    )

    resubmitted = submit_fare_schedule(fs["id"], 550)
    assert resubmitted["status"] == "SUBMITTED", "revision loop must allow resubmission"

    approved = validate_success(
        api.approve_fare_schedule(fs["id"], scheduler_admin_headers)
    )
    assert_fare_schedule(approved)
    assert approved["status"] == "APPROVED"


def test_resubmit_repins_fuel_surcharge(api, scheduler_admin_headers):
    """PRD §3.2: "The caller supplies `fuel_price_index_cents`, and the system
    re-pins the surcharge from it: an index below 300 cents yields a
    `fuel_surcharge_cents` of 0; an index of at least 300 but below 500 yields
    100; an index of 500 or more yields 250."

    Design: Difficulty/non_linear_state_machine/fare_schedule_revision_loop
    """
    route = create_route(route_code="SEA-BI")
    fs = create_fare_schedule(route["id"], route_version=route["version"])

    first = submit_fare_schedule(fs["id"], 350)
    assert first["fuel_surcharge_cents"] == 100, (
        f"index 350 must pin surcharge 100, got {first['fuel_surcharge_cents']}"
    )

    validate_success(api.return_fare_schedule_for_revision(fs["id"], scheduler_admin_headers))
    resubmitted = submit_fare_schedule(fs["id"], 550)
    assert resubmitted["fuel_surcharge_cents"] == 250, (
        "resubmission re-pins the surcharge from the new index; "
        f"index 550 >= 500 must yield 250, got {resubmitted['fuel_surcharge_cents']}"
    )


def test_fuel_surcharge_tier_boundaries(api, scheduler_admin_headers):
    """PRD §3.2: "an index below 300 cents yields a `fuel_surcharge_cents` of
    0; an index of at least 300 but below 500 yields 100; an index of 500 or
    more yields 250. An index of exactly 300 therefore produces 100, and
    exactly 500 produces 250."

    Design: Corner/calculations/fuel_surcharge_tier_boundaries
    """
    route = create_route(route_code="SEA-BI")
    fs = create_fare_schedule(route["id"], route_version=route["version"])

    expected = [(299, 0), (300, 100), (499, 100), (500, 250)]
    for index, surcharge in expected:
        submitted = submit_fare_schedule(fs["id"], index)
        assert submitted["fuel_surcharge_cents"] == surcharge, (
            f"fuel index {index} must pin fuel_surcharge_cents {surcharge}, "
            f"got {submitted['fuel_surcharge_cents']}"
        )
        if index != expected[-1][0]:
            validate_success(
                api.return_fare_schedule_for_revision(fs["id"], scheduler_admin_headers)
            )


def test_reject_is_terminal_for_fare_schedule(api, scheduler_admin_headers):
    """PRD §3.2: "Rejection moves it `SUBMITTED → REJECTED`, which is
    terminal."
    PRD §2.11: "4. Target resource in a legal state for the requested
    transition — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reject_is_terminal_for_fare_schedule
    """
    route = create_route(route_code="SEA-BI")
    fs = create_fare_schedule(route["id"], route_version=route["version"])
    submit_fare_schedule(fs["id"], 200)
    rejected = validate_success(api.reject_fare_schedule(fs["id"], scheduler_admin_headers))
    assert rejected["status"] == "REJECTED"

    resp = api.approve_fare_schedule(fs["id"], scheduler_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_fare_schedule(fs["id"], scheduler_admin_headers))
    assert after["status"] == "REJECTED", "terminal REJECTED state must not move"


def test_overlapping_window_submit_rejected(api, scheduler_admin_headers):
    """PRD §3.2: "The submission is also where window integrity is enforced:
    `effective_from` must be strictly earlier than `effective_to`, and no
    other fare schedule for the same route and season may hold `SUBMITTED`,
    `APPROVED`, or `EFFECTIVE` status with an overlapping effective window.
    Violations of either clause are rejected with
    `ERR_SCHEDULE_WINDOW_CONFLICT`."

    Design: Corner/validations/schedule_window_conflict_on_submit
    """
    route = create_route(route_code="SEA-BI")
    fs1 = create_fare_schedule(
        route["id"],
        route_version=route["version"],
        season="OFF_PEAK",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
    )
    submit_and_approve(fs1["id"], 200)
    set_clock("2026-08-15T00:00:00Z")  # first schedule's window now covers: EFFECTIVE

    fs2 = create_fare_schedule(
        route["id"],
        season="OFF_PEAK",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-12-01T00:00:00Z",
    )
    resp = api.submit_fare_schedule(
        fs2["id"], {"fuel_price_index_cents": 200}, scheduler_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_CONFLICT)

    after = validate_success(api.get_fare_schedule(fs2["id"], scheduler_admin_headers))
    assert after["status"] == "DRAFT", (
        f"rejected submission must leave the schedule in DRAFT, got {after['status']}"
    )


def test_stale_route_version_rejected_then_fresh_accepted(api, scheduler_admin_headers):
    """PRD §2.9: "If the route's current `version` has advanced past that
    value — because another writer created a fare schedule against the same
    route in the interim, an action which itself increments the route's
    `version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_fare_schedule_create
    """
    route = create_route(route_code="SEA-BI")
    assert route["version"] == 1
    create_fare_schedule(route["id"], route_version=1)  # route version now 2

    stale_payload = create_fare_schedule_payload(
        season="PEAK",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        expected_route_version=1,
    )
    resp = api.create_fare_schedule(route["id"], stale_payload, scheduler_admin_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_payload = create_fare_schedule_payload(
        season="PEAK",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        expected_route_version=2,
    )
    created = validate_success(
        api.create_fare_schedule(route["id"], fresh_payload, scheduler_admin_headers),
        expected_status=201,
    )
    assert_fare_schedule(created)
    assert created["status"] == "DRAFT"


def test_fare_schedule_create_increments_route_version(api, scheduler_admin_headers):
    """PRD §3.2: "it must carry `expected_route_version` matching the route's
    current `version` or it fails with `ERR_STALE_VERSION`, and a successful
    create increments the route's `version` by 1, which is precisely what
    makes a second, concurrent drafter's version stale."

    Design: Corner/cross_cutting_layers/occ_version_increments_on_fare_schedule_create
    """
    route = create_route(route_code="SEA-BI")
    assert route["version"] == 1

    create_fare_schedule(route["id"], route_version=1)

    after = get_route(route["id"])
    assert after["version"] == 2, (
        f"one successful fare-schedule create must increment the route version "
        f"by exactly 1 (1 -> 2), got {after['version']}"
    )


def test_logical_clock_default_drives_lazy_effectiveness(api, scheduler_admin_headers):
    """PRD §2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z` as a fixed server default; it never falls back to
    wall-clock time."
    PRD §3.2: "When the current instant reaches an `APPROVED` schedule's
    `effective_from` while remaining before its `effective_to`, the schedule
    becomes `EFFECTIVE` — evaluated both when the clock is set and lazily
    whenever a fare schedule is read or consulted."

    Design: Corner/cross_cutting_layers/logical_clock_default_is_fixed
    """
    route = create_route(route_code="SEA-BI")
    peak = create_fare_schedule(
        route["id"],
        route_version=route["version"],
        season="PEAK",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    submit_and_approve(peak["id"], 200)
    off_peak = create_fare_schedule(
        route["id"],
        season="OFF_PEAK",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
    )
    submit_and_approve(off_peak["id"], 200)

    # No clock call issued: the fixed default 2026-08-01T00:00:00Z governs.
    peak_read = validate_success(api.get_fare_schedule(peak["id"], scheduler_admin_headers))
    assert peak_read["status"] == "EFFECTIVE", (
        "default clock 2026-08-01 lies inside the PEAK window [2026-06-01, "
        f"2026-09-01), so the schedule must read EFFECTIVE, got {peak_read['status']}"
    )
    off_read = validate_success(api.get_fare_schedule(off_peak["id"], scheduler_admin_headers))
    assert off_read["status"] == "APPROVED", (
        "default clock 2026-08-01 has not reached the OFF_PEAK window "
        f"[2026-09-01, 2026-11-01), so the schedule must stay APPROVED, got {off_read['status']}"
    )
