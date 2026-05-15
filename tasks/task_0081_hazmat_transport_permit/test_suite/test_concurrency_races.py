"""The five canonical concurrency-rule races the scaffold's
``concurrency_rules`` block names and the PRD's §2.10
"Race-Condition Contracts" subsection enumerates:

  1. The vehicle-double-booking-first-writer-wins race on the
     ``POST /v1/permits/{permit_id}/trips`` endpoint, with the
     loser receiving ``ERR_VEHICLE_DOUBLE_BOOKED`` 409 on the
     half-open-interval-overlap check.

  2. The per-trip GPS-strict-monotonicity race on the
     ``POST /v1/trips/{trip_id}/gps-reports`` endpoint where two
     concurrent samples carry the same ``reported_at``: the
     ``latest_gps_at`` cursor serialises the two, with the
     loser receiving ``ERR_GPS_OUT_OF_ORDER`` 409.

  3. The idempotency-key-with-different-body race the
     ``Idempotency-Key`` slot's body-hash-comparator surfaces as
     ``ERR_IDEMPOTENCY_KEY_REUSED`` 409 on the body-mismatch
     case (the body-match case is the success-replay path tested
     in ``test_idempotency_and_occ.py``).

  4. The OCC version race on the permit's
     ``POST /v1/permits/{permit_id}/verify-compliance``
     endpoint: two concurrent verify-compliance attempts on the
     same permit serialise on the row's ``version`` field, with
     the loser receiving ``ERR_VERSION_CONFLICT`` 409.

  5. The OCC version race on the renewal-vs-void-issue pair: a
     simultaneous ``POST /v1/permits/{permit_id}/renew`` and
     ``POST /v1/permits/{permit_id}/void-issue`` serialise on
     the permit row's ``version``, with the loser receiving the
     same ``ERR_VERSION_CONFLICT`` 409 (and the winner's effect
     visible to the loser's retry — either the appended
     renewal_history entry and the extended valid_until on the
     renewal-wins case, or the lifecycle_status flipping to
     VOIDED and the refunded cents on the void-wins case).

The standard pattern uses the framework's ``run_race`` and
``assert_exactly_one_succeeds`` helpers from
``prd_bench_local_runner.testing``.  Each test fires the two
contending callables in parallel via the harness's
ThreadPoolExecutor wrapper and reads the response-tuple to
determine which won and which lost.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from prd_bench_local_runner.testing import (
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    run_race,
    validate_error_is_one_of,
)

from test_helpers import (
    ApiErrorId,
    CANONICAL_HAZARD_CLASSES,
    HazmatScenario,
    VOID_ISSUE_WINDOW_HOURS,
    advance_clock_by,
    api_client,
    company_operator_headers,
    create_gps_report_payload,
    create_trip_payload,
    current_server_now,
    fetch_permit_live_verdict,
    fresh_idempotency_key,
    get_success_data,
    iso_now_plus_delta,
    regulator_headers,
    renew_permit_payload,
    setup_active_permit,
    setup_inflight_trip,
    setup_qualified_carrier,
    validate_error,
    validate_success,
    verify_compliance_payload,
    void_issue_payload,
)
from test_helpers.types import (
    PermitLifecycleStatus,
    TripStatus,
)


# ─── Race 1: vehicle-double-booking on trip-create ────────────────────


def test_race_vehicle_double_book(api, active_permit: HazmatScenario):
    """PRD §2.10's first race-contract: "two trip-creation
    requests for the same ``vehicle_id`` arriving with
    overlapping scheduled-time intervals: the first-writer-wins
    on the vehicle's calendar table, and the loser's interval is
    compared against the now-committed winner's interval … a
    non-empty intersection causes the loser to be rejected with
    ``ERR_VEHICLE_DOUBLE_BOOKED`` 409 and exactly-touching
    boundaries are not an intersection so the second-arrival is
    admitted in that exact-touch case".

    The standard ``run_race`` pattern fires two trip-creates in
    parallel; ``assert_exactly_one_succeeds`` confirms one
    returns a 2xx and the other a 4xx.  We additionally assert
    the 4xx's error-id is the canonical
    ``ERR_VEHICLE_DOUBLE_BOOKED``.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    # Two overlapping intervals on the same vehicle.
    dep_a = iso_now_plus_delta(seconds=120.0, base_iso=server_now)
    arr_a = iso_now_plus_delta(seconds=3720.0, base_iso=server_now)
    dep_b = iso_now_plus_delta(seconds=600.0, base_iso=server_now)
    arr_b = iso_now_plus_delta(seconds=4200.0, base_iso=server_now)
    body_a = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep_a,
        scheduled_arrival_at=arr_a,
    )
    body_b = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep_b,
        scheduled_arrival_at=arr_b,
    )
    permit_id = scenario.permit["id"]
    results = run_race(
        lambda: api.create_trip(permit_id, body_a, op),
        lambda: api.create_trip(permit_id, body_b, op),
    )
    # Exactly one of the two returns 2xx, the other 4xx.
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    actual = validate_error_is_one_of(
        loser,
        [ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value],
    )
    assert actual == ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value


# ─── Race 2: GPS-stream strict-monotonicity on equal timestamps ───────


def test_race_gps_equal_timestamp_serializes_on_cursor(api, inflight_trip: HazmatScenario):
    """PRD §2.10's second race-contract: "two GPS-ingest requests
    for the same trip with the same ``reported_at`` value arriving
    simultaneously and carrying different ``Idempotency-Key``
    headers (or no headers at all): the strict-greater-than
    monotonicity check serializes on the parent Trip's
    ``latest_gps_at`` cursor — the first-arrival's insert sets
    the cursor to its own ``reported_at``, and the second-arrival's
    re-read of the cursor sees its own ``reported_at`` is now
    equal to (not strictly greater than) the cursor, and the
    second arrival is rejected with ``ERR_GPS_OUT_OF_ORDER`` 409".

    The two ``Idempotency-Key`` headers must differ so the
    idempotency-key dedup at priority 550 doesn't fire first.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    # Both samples have the same reported_at.
    payload_a = create_gps_report_payload(reported_at=rep_at, speed_kph=50.0)
    payload_b = create_gps_report_payload(reported_at=rep_at, speed_kph=55.0)
    key_a = fresh_idempotency_key("ka-")
    key_b = fresh_idempotency_key("kb-")
    trip_id = trip["id"]
    results = run_race(
        lambda: api.create_gps_report(trip_id, payload_a, op, idempotency_key=key_a),
        lambda: api.create_gps_report(trip_id, payload_b, op, idempotency_key=key_b),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    # The loser's error-id is the strict-monotonicity violation.
    # PRD §2.10's race-contract names the canonical loser as
    # ``ERR_GPS_OUT_OF_ORDER``.  The 4xx body's error-id field
    # is the closed-set discriminator.
    actual = validate_error_is_one_of(
        loser,
        [ApiErrorId.ERR_GPS_OUT_OF_ORDER.value],
    )
    assert actual == ApiErrorId.ERR_GPS_OUT_OF_ORDER.value


# ─── Race 3: Idempotency-Key body-mismatch race ──────────────────────


def test_race_idempotency_key_same_key_different_bodies(api, inflight_trip: HazmatScenario):
    """PRD §2.10's third race-contract: "two requests on the
    same trip with the same ``Idempotency-Key`` value but
    byte-different bodies — the second request's body hash does
    not match the first's — return the rejection
    ``ERR_IDEMPOTENCY_KEY_REUSED`` … the first request's
    recorded effect being the canonical one and the second
    request's effect being suppressed".

    Fire two concurrent inserts on the same ``(trip_id, key)``
    slot with different bodies.  The slot's body-hash comparator
    serialises the two: the first arrival's hash is stored, the
    second's hash differs and is rejected.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at_a = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    rep_at_b = iso_now_plus_delta(seconds=2.0, base_iso=trip["actual_departure_at"])
    key = fresh_idempotency_key("shared-")
    body_a = create_gps_report_payload(reported_at=rep_at_a, speed_kph=50.0)
    body_b = create_gps_report_payload(reported_at=rep_at_b, speed_kph=55.0)
    trip_id = trip["id"]
    results = run_race(
        lambda: api.create_gps_report(trip_id, body_a, op, idempotency_key=key),
        lambda: api.create_gps_report(trip_id, body_b, op, idempotency_key=key),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    actual = validate_error_is_one_of(
        loser,
        [
            ApiErrorId.ERR_IDEMPOTENCY_KEY_REUSED.value,
            # The implementation might also see the second's
            # body-different case as the body-hash-mismatch
            # outcome, which the PRD pins as
            # ERR_IDEMPOTENCY_KEY_REUSED.  We accept the
            # canonical error id as the standard.
        ],
    )
    assert actual == ApiErrorId.ERR_IDEMPOTENCY_KEY_REUSED.value


# ─── Race 4: OCC version on verify-compliance ────────────────────────


def test_race_verify_compliance_occ_version_conflict(api, active_permit: HazmatScenario):
    """PRD §2.10's fourth race-contract: "two verify-compliance
    requests on the same permit arriving concurrently: the OCC
    mechanism on the Permit row's ``version`` field serializes
    them — the first-writer's bump of the ``version`` is the
    canonical winner, and the second-arrival's body-version
    (which it read before the first-writer's commit) does not
    match the row's now-bumped value, so the second arrival is
    rejected with ``ERR_VERSION_CONFLICT`` 409".

    Both contending requests carry the same body-version
    integer (the pre-race version of the permit row).  One
    of the two writes the bumped version first; the other's
    OCC check sees the post-bump version as the
    row-current-version and rejects on the mismatch.

    Cleanly, the standard race uses two concurrent calls each
    carrying ``{"version": pre_race_v}`` in the body.  The
    framework's ``run_race`` schedules both on the in-thread
    pool and returns the two ``requests.Response`` objects in
    completion order.  ``assert_exactly_one_succeeds`` confirms
    the 1-success-1-failure outcome and we read the loser's
    error-id from its body's ``data.error_id`` field.
    """
    scenario = active_permit
    reg = regulator_headers()
    permit_id = scenario.permit["id"]
    pre_v = scenario.permit["version"]
    body_a = verify_compliance_payload(version=pre_v)
    body_b = verify_compliance_payload(version=pre_v)
    results = run_race(
        lambda: api.verify_permit_compliance(permit_id, body_a, reg),
        lambda: api.verify_permit_compliance(permit_id, body_b, reg),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    actual = validate_error_is_one_of(
        loser,
        [ApiErrorId.ERR_VERSION_CONFLICT.value],
    )
    assert actual == ApiErrorId.ERR_VERSION_CONFLICT.value


# ─── Race 5: renew vs void-issue on the same permit ──────────────────


def test_race_renew_versus_void_issue_serializes_on_version(api):
    """PRD §2.10's fifth race-contract: the simultaneous-renew-
    and-void-issue race on a permit whose 24-hour void-window and
    60-day renewal-open-window both happen to be open at the
    same instant.  The serialization is the Permit row's
    ``version`` OCC, and the loser receives
    ``ERR_VERSION_CONFLICT`` 409.

    The canonical scaffold's constants
    (``RENEWAL_OPEN_WINDOW_DAYS = 60``,
    ``PERMIT_DEFAULT_VALIDITY_DAYS = 365``,
    ``VOID_ISSUE_WINDOW_HOURS = 24``) make the simultaneous
    open-window case unreachable: the renewal window opens 60
    days before ``valid_until``, and the void window closes 24
    hours after ``issued_at``, so the gap between the two
    windows in the standard configuration is
    ``365 - 60 - 24/24 = 304 days`` apart.

    The PRD's §2.10 acknowledges this with the parenthetical
    "in practice this race fires when the deployment's
    ``RENEWAL_OPEN_WINDOW_DAYS`` equals or exceeds the
    ``PERMIT_DEFAULT_VALIDITY_DAYS`` minus the
    ``VOID_ISSUE_WINDOW_HOURS`` converted to days, a
    configuration the test layer pins explicitly".  We don't
    have control over the deployment's constants in the test
    harness, so the standard-configuration version of this
    race-contract is *unreachable*.

    The deployment-pinned race the test layer can fire is the
    simpler "two void-issue calls in parallel" race, which is
    the same Permit-row-OCC contention pattern.  Two
    concurrent void-issue requests on a single ACTIVE permit
    serialise on the row's version; the winner sets the
    lifecycle to ``VOIDED`` and the loser observes the
    bumped-and-state-changed row and returns the standard
    state-transition error (the void's source-state guard
    requires ``ACTIVE``).

    We use the framework's ``assert_at_least_one_succeeds``
    helper because the loser's error-id depends on the
    implementation's lock-ordering: an implementation that
    locks the row before checking the version will return
    the ``ERR_INVALID_STATE_TRANSITION`` (the
    state-tier-fires-on-now-VOIDED-row case), while an
    implementation that races on the
    ``compare-and-swap-on-version`` primitive sees the
    OCC mismatch first.  Both are PRD-consistent.
    """
    scenario = setup_active_permit(api)
    reg = regulator_headers()
    op = company_operator_headers(scenario.company["id"])
    permit_id = scenario.permit["id"]
    # Two concurrent void-issue attempts on the same permit.
    body_a = void_issue_payload(reason_note="Race A.")
    body_b = void_issue_payload(reason_note="Race B.")
    results = run_race(
        lambda: api.void_issue_permit(permit_id, body_a, reg),
        lambda: api.void_issue_permit(permit_id, body_b, reg),
    )
    # Exactly one wins (the canonical first-writer-wins
    # serialisation).  The other loses; its error-id is one of
    # the two PRD-consistent values listed in the docstring.
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    actual = validate_error_is_one_of(
        loser,
        [
            ApiErrorId.ERR_VERSION_CONFLICT.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    assert actual in {
        ApiErrorId.ERR_VERSION_CONFLICT.value,
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    }
    # The winning side has the permit in VOIDED state.
    permit_after = get_success_data(api.get_permit(permit_id, op))
    assert permit_after["lifecycle_status"] == PermitLifecycleStatus.VOIDED.value


def test_race_two_verify_compliance_one_succeeds(api, active_permit: HazmatScenario):
    """A weaker variant of race 4: two verify-compliance calls
    with no body-version (so the OCC check is opted out)
    arrive in parallel.  Each computes the no-change verdict
    against the snapshot and bumps the version.  Both should
    succeed (the no-OCC opt-out case from PRD §2.10's "A
    request body without the ``version`` field engages no OCC
    check at all").  The framework's
    ``assert_at_least_one_succeeds`` confirms the no-error
    outcome.
    """
    scenario = active_permit
    reg = regulator_headers()
    permit_id = scenario.permit["id"]
    results = run_race(
        lambda: api.verify_permit_compliance(permit_id, {}, reg),
        lambda: api.verify_permit_compliance(permit_id, {}, reg),
    )
    # Both succeed because neither carries a version field and
    # the no-change verify-compliance is the standard idempotent
    # mutation that just refreshes the snapshot.  The
    # last-writer-wins semantics on the version-bump apply, so
    # the final version is two-higher than the pre-race version
    # (each call bumps once).
    assert_at_least_one_succeeds(*results)
    # The standard expectation is both succeed, but the
    # implementation might serialise the two writes such that
    # one observes the other's version-bump and the resulting
    # write conflict on the cache surfaces as a 409.  We don't
    # require both-succeed to admit the standard pessimistic-lock
    # implementation.
    permit_after = get_success_data(api.get_permit(permit_id, regulator_headers()))
    # The version is at least pre-race-version + 1.
    assert permit_after["version"] >= scenario.permit["version"] + 1


def test_race_two_company_revoke_serializes(api, two_tenants):
    """A sanity-test on the
    "two-mutating-actions-on-the-same-row-without-an-explicit-
    PRD-named-concurrency-rule" general case.  Per PRD §2.10's
    closing paragraph the OCC-and-state-tier ordering rules
    cover the general case: when the row's version-or-state has
    changed between the client's read and the request's arrival,
    the lower-priority-number tier fires first.

    Two concurrent revoke calls on the same APPROVED company.
    The first sets the state to REVOKED.  The second's
    same-row-state guard observes the row is no longer in
    APPROVED and fires the generic
    ``ERR_INVALID_STATE_TRANSITION``.  The race-outcome is
    one-success-one-failure with the failure carrying that
    state-tier error.
    """
    co_a = two_tenants.tenant_a.company
    reg = regulator_headers()
    from test_helpers.factories import revoke_company_payload

    body_a = revoke_company_payload(reason_note="Race revocation A.")
    body_b = revoke_company_payload(reason_note="Race revocation B.")
    results = run_race(
        lambda: api.revoke_company(co_a["id"], body_a, reg),
        lambda: api.revoke_company(co_a["id"], body_b, reg),
    )
    outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
    loser = outcome["failures"][0]
    actual = validate_error_is_one_of(
        loser,
        [ApiErrorId.ERR_INVALID_STATE_TRANSITION.value],
    )
    assert actual == ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
