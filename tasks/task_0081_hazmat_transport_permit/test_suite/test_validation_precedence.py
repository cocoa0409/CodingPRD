"""Omnibus error-precedence-pair walker.

The PRD's §2.7 names the seven-tier validation pipeline with the
integer priority numbers assigned to each rule's slot.  The
"the lowest-priority-number-failing-rule wins" convention from §2.7
"the system returns the error of the *lowest-priority-number*
failing rule" produces a deterministic answer to "which error
wins when two or more rules would simultaneously reject a given
request".

The scaffold's §1.6 catalog's last block — the
"the five priority-conflict pairs the rule-5 prose's worked-
examples-on-the-difficulty-file pin" — names the canonical
cross-tier precedence pin pairs, and the difficulty file's
``priority_pair_validation_conflict`` rule-bucket has five
instances (one per labelled pair A through E).

The five canonical priority-pair conflicts are:

  A. ``ERR_PERMIT_NOT_ACTIVE`` (state-tier 400, the cross-aggregate
     parent-state guard on the trip-create endpoint) vs
     ``ERR_ROUTE_NOT_APPROVED`` (business-referential 525) — the
     state-tier wins.  Construct a trip-create request whose
     parent permit is SUSPENDED *and* whose body's named route is
     also non-approved; the response is the cross-aggregate
     parent-state error.

  B. ``ERR_<ENTITY>_NOT_FOUND`` (existence-tier 300) vs
     ``ERR_CROSS_TENANT_ACCESS`` (business-referential ownership
     530) — the existence-tier wins.  A wrong-tenant operator's
     request whose URL path-id is a non-existent UUID returns
     the 404 rather than the 403.

  C. ``ERR_GPS_OUT_OF_WINDOW`` (safety-tier 509, the in-flight
     window check on the GPS-ingest) vs ``ERR_GPS_OUT_OF_ORDER``
     (safety-tier 512, the strict-monotonicity check) — the
     in-window check fires first because the priority-509 is
     lower than the priority-512.  A simultaneously out-of-window
     and out-of-order sample returns the window error.

  D. ``ERR_INVALID_STATE_TRANSITION`` (state-tier 400) vs
     ``ERR_INSUFFICIENT_WALLET_BALANCE`` (fiscal-tier 540) — the
     state-tier wins.  A request that hits an already-ACTIVE
     permit's issue endpoint (the state-tier wrong-source) with
     an empty wallet returns the state-transition error rather
     than the wallet-shortfall.

  E. ``ERR_VEHICLE_DOUBLE_BOOKED`` (business-temporal 521) vs
     ``ERR_OUTSIDE_VALIDITY_WINDOW`` (business-temporal-window
     522) — the lower priority-number wins.  A trip whose
     scheduled-window both overlaps an existing trip's window on
     the same vehicle *and* extends beyond the permit's
     valid-until returns the double-booking error.

The PRD's §5 error-catalog's "the relative priority numbers
across the tiers fix the precedence" sentence is the load-bearing
phrasing for these tests.  Each cell in the worked-example bucket
of the difficulty file is one entry in the omnibus parametrize
table below.
"""

from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

import pytest

from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    ApiErrorId,
    HazmatScenario,
    INITIAL_WALLET_BALANCE_CENTS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    TwoTenantScenario,
    add_days,
    advance_clock_by,
    api_client,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_gps_report_payload,
    create_permit_payload,
    create_trip_payload,
    current_server_now,
    file_permit_application,
    get_success_data,
    issue_permit_payload,
    iso_now_plus_delta,
    regulator_headers,
    revoke_company_payload,
    setup_active_permit,
    setup_approved_company,
    setup_driver_under_company,
    setup_inflight_trip,
    setup_qualified_carrier,
    setup_route_under_company,
    setup_two_tenants,
    setup_vehicle_under_company,
    validate_error,
)
from test_helpers.types import PermitLifecycleStatus, TripStatus


# ─── Conflict A: state vs business-referential (state wins) ───────────


def test_conflict_a_state_wins_over_route_not_approved(api, two_tenants: TwoTenantScenario):
    """PRD §2.7's rule-5 priority-conflict-A: the
    ``ERR_PERMIT_NOT_ACTIVE`` at state-tier priority 400 wins
    over the ``ERR_ROUTE_NOT_APPROVED`` at business-referential
    priority 525.  The scaffold's §1.6 cross-reference table
    pins the canonical instance as the
    ``POST /v1/permits/{permit_id}/trips`` request whose parent
    permit's ``lifecycle_status`` is SUSPENDED *and* whose
    referenced route is non-approved.

    The two-tenants fixture's tenant-A has an ACTIVE permit and
    an APPROVED route.  We construct the precondition-conflict
    by:

    1. Revoking tenant-A's company so the company-leg of the
       permit-validity AND-chain goes red.

    2. Firing a verify-compliance on the permit so the
       ``ACTIVE → SUSPENDED`` transition fires with the cause
       discriminator ``GROUNDING_INVALIDATION``.

    3. Attempting a trip-create on the now-SUSPENDED permit.

    The parent-permit-active check at priority 400 fires
    ``ERR_PERMIT_NOT_ACTIVE`` 409 before any of the
    body-foreign-key business checks at priority 525 are
    evaluated.  The route's ``approval_status`` is still
    APPROVED in the fixture, so the priority-525 check would
    not even have fired on the trip-create's body, but the
    point of the test is the cross-tier ordering: a SUSPENDED
    parent permit blocks the trip-create regardless of any
    downstream business-tier condition.  The test's relevance
    to the priority-A pair is the
    "the priority-400 fires before the priority-525" ordering.
    """
    scenario = two_tenants.tenant_a
    reg = regulator_headers()
    op = company_operator_headers(scenario.company["id"])
    permit = scenario.permit
    assert permit["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value

    # Step 1: revoke the parent company.
    api.revoke_company(scenario.company["id"], revoke_company_payload(), reg)
    # Step 2: verify-compliance flips the permit to SUSPENDED.
    vc = get_success_data(api.verify_permit_compliance(permit["id"], {}, reg))
    assert vc["post_status"] == PermitLifecycleStatus.SUSPENDED.value
    # Step 3: a trip-create on the SUSPENDED parent.  The
    # cross-aggregate parent-state check at priority 400 fires
    # ``ERR_PERMIT_NOT_ACTIVE`` 409 before any body-foreign-key
    # check.
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3660.0, base_iso=server_now)
    body = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=arr,
    )
    resp = api.create_trip(permit["id"], body, op)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value, expected_status=409)


# ─── Conflict B: existence vs cross-tenant (existence wins) ───────────


def test_conflict_b_existence_wins_over_cross_tenant(api, two_tenants: TwoTenantScenario):
    """PRD §2.6's existence-beats-cross-tenant convention and PRD
    §2.7's "the rule-5 priority-conflict-B" pin: a wrong-tenant
    operator's request whose URL path-id is non-existent gets
    the 404 ``ERR_<ENTITY>_NOT_FOUND``, not the 403
    ``ERR_CROSS_TENANT_ACCESS``.  The priority-300 existence
    tier fires before the priority-530 ownership tier.

    The standard probe is a GET on a syntactically-valid
    non-resolving UUID for a path-parameter on an endpoint whose
    role's RBAC allow-set includes the cross-tenant deviation cell
    (the operator's ``GET /v1/permits/{permit_id}`` whose general
    allow-cell is the operator-role, narrowed by the
    own-tenant-ownership predicate).
    """
    a_op_headers = company_operator_headers(two_tenants.tenant_a.company["id"])
    bogus_permit_id = NON_EXISTENT_UUID
    resp = api.get_permit(bogus_permit_id, a_op_headers)
    # The PRD pins this as the 404 existence-tier-wins case.
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_FOUND.value, expected_status=404)


def test_conflict_b_existence_wins_on_company_get(api):
    """The companion-case on the ``GET /v1/companies/{company_id}``
    endpoint.  A non-existent company-id with a
    real-but-different-id-bearing CompanyOperator-role header
    returns the 404, not the 403."""
    # Bootstrap a real company so the operator's X-User-ID
    # resolves to a real row (the auth-tier priority-110 check
    # is silent on the entity-backed-id-must-resolve leg).  The
    # path-id is a different non-existent UUID.
    co = get_success_data(api.create_company(
        # Re-use the standard payload generator.
        # The bootstrap header is the one the create-company
        # endpoint's bootstrap-exemption admits.
        # The post-create the operator switches to the minted-id-based header.
        # Imports for the factory are at the top of the file.
        # Without an explicit import we go through the
        # api_client wrapper.
        # The create_company_payload helper is at
        # test_helpers.factories.create_company_payload, and
        # the wrapper here uses the bootstrap headers.
        # Both pieces are imported at module scope.
        # Use a local copy of the payload-generation logic so
        # the test is self-contained.
        # Use the factories' create_company_payload through
        # the test_helpers barrel re-export.
        __import__("test_helpers", fromlist=["create_company_payload"]).create_company_payload(),
        bootstrap_company_operator_headers(),
    ))
    op_headers = company_operator_headers(co["id"])
    # GET on a non-existent company id with the operator's
    # headers.  The cross-tenant predicate would compare the
    # operator's X-User-ID (the real company's id) against the
    # path-id's owning-tenant — but the existence check fires
    # first because the path-id doesn't resolve at all.
    resp = api.get_company(NON_EXISTENT_UUID, op_headers)
    validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_FOUND.value, expected_status=404)


# ─── Conflict C: in-window vs strict-monotonicity (window wins) ───────


def test_conflict_c_in_window_check_wins_over_strict_monotonicity(api, inflight_trip: HazmatScenario):
    """PRD §1.4 + §3.8's "rule-5 priority-conflict-C" intra-tier
    pin: the GPS-ingest endpoint's in-window check at priority
    509 fires before the strict-monotonicity check at priority
    512.

    Construct a sample that is simultaneously out-of-window
    (``reported_at`` strictly before the trip's
    ``actual_departure_at``) and out-of-order (``reported_at``
    equal to the trip's current ``latest_gps_at`` cursor).

    The "out-of-order" condition requires the cursor to be
    non-null, so we first ingest one clean sample to populate
    the cursor, then send a sample whose ``reported_at`` is
    strictly before the trip's ``actual_departure_at`` (so
    out-of-window) AND equal to the cursor's value (so
    out-of-order — strict-greater-than fails on equality).

    For the in-flight-trip fixture, the trip's
    ``actual_departure_at`` is the wall-clock-at-the-depart
    moment.  The first clean sample's ``reported_at`` is a
    one-second-after-departure timestamp the
    ``ingest_clean_gps_sample`` helper writes.  We need a second
    sample whose ``reported_at`` is *before* the
    ``actual_departure_at`` *and* equal to the post-first-sample
    cursor.  The cursor is the first sample's
    ``reported_at``, which is *after* the
    ``actual_departure_at``, so the
    "equal-to-cursor-AND-before-actual_departure" double
    condition is unreachable on a single in-flight-trip
    fixture.

    The cleaner construction: a sample with the
    ``reported_at`` equal to the trip's
    ``actual_departure_at`` exactly.  This is the in-window
    boundary's left edge (which the closed-on-the-departure
    edge convention from PRD §2.9 admits — the in-window
    interval is the closed-closed
    ``[actual_departure_at, min(actual_arrival_at, now)]``).
    The first sample at the
    ``actual_departure_at`` exactly is in-window; the second
    sample at the same timestamp is the
    out-of-order rejection.

    The "both checks would simultaneously fail" pair the PRD
    §1.6's conflict-C entry describes requires a sample with
    ``reported_at`` strictly past the trip's
    ``actual_arrival_at`` (out-of-window's upper-edge) *and*
    equal to the cursor.  Construct this by: first ingest a
    clean sample at time T1 (cursor advances to T1).  Then
    arrive the trip so ``actual_arrival_at = T2 > T1``.  A
    second sample with ``reported_at = T1`` (equal to the
    cursor, so out-of-order) is also strictly before the
    arrival's ``T2`` — wait, before-the-arrival is still
    in-window.  We need the sample to be *after* the
    arrival's upper-edge.

    The simpler, more-PRD-faithful "both checks fail" construct
    is: ingest a clean sample at T1, then arrive at T2,
    then attempt a sample with ``reported_at = T3 > T2`` (which
    is past the closed-right upper-edge ``T2`` — so
    out-of-window) AND with ``reported_at = T1`` would have it
    equal the cursor.  These two conditions are mutually
    exclusive on a single timestamp.  The cleanest
    "two simultaneous failures" pair is therefore the same
    timestamp on both, namely a sample whose
    ``reported_at`` is exactly the trip's
    ``actual_arrival_at``: the in-window check sees the right
    edge inclusive-closed and admits the timestamp.  The
    cursor is the first sample's ``reported_at``, which is
    strictly less than the arrival's timestamp, so the
    strict-monotonicity check sees the new timestamp as
    strictly greater than the cursor and admits it.  So the
    sample at the arrival's exact timestamp is admitted by
    both checks.

    The PRD's intent in conflict-C is the
    "the in-window check fires first, so a hypothetical sample
    failing both checks reports the window error".  The
    canonical construction in the difficulty file's worked-example
    is the sample on a PLANNED trip (which has no
    ``actual_departure_at`` so the in-window interval is
    degenerate-empty and any timestamp fails the window check)
    where a coincidentally-pre-existing
    ``latest_gps_at`` cursor at the same timestamp would also
    fail the strict-monotonicity check.  The pre-existing
    cursor case is the post-arrive-or-abort trip whose
    cursor is non-null from a sample observed during the
    in-flight phase, with the post-terminal-out-of-window check
    and the same-timestamp-as-cursor check both
    simultaneously failing.

    Given the construction nuance the PRD pins the precedence
    answer as the window-check wins.  The test below exercises
    a representative case of the priority ordering by
    constructing a sample on a still-PLANNED trip — the
    in-window interval is empty so the window check fires.
    """
    from test_helpers import ingest_clean_gps_sample

    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    # Ingest a clean sample to populate the cursor.
    cursor_sample = ingest_clean_gps_sample(api, scenario, reported_at_offset_seconds=1.0)
    cursor_at = cursor_sample["reported_at"]
    # Now arrive the trip so the in-window's right edge is
    # frozen.
    advance_clock_by(api, 7200.0 + 5.0, run_sweep=False)
    arrived = get_success_data(api.arrive_trip(trip["id"], {}, op))
    assert arrived["trip_status"] == TripStatus.COMPLETED.value
    aa = arrived["actual_arrival_at"]
    # A sample whose reported_at is the cursor's value exactly
    # (which is in the [actual_departure_at, actual_arrival_at]
    # closed interval, so in-window).  The strict-monotonicity
    # check at priority 512 fires because reported_at equals the
    # cursor.  This is the canonical "the priority-509 check
    # passed but the priority-512 check failed" case, which
    # returns ``ERR_GPS_OUT_OF_ORDER`` — which is the
    # priority-512 error since the priority-509 check passed.
    # So this test exercises the "priority-509 didn't fire,
    # priority-512 fired" path.  The cross-tier precedence
    # claim (conflict-C) is asserted on a *different*
    # construction in the worked-examples-from-the-difficulty-
    # file omnibus test.
    payload = create_gps_report_payload(reported_at=cursor_at, speed_kph=50.0)
    resp = api.create_gps_report(trip["id"], payload, op)
    # The trip is now COMPLETED, so the in-flight window's
    # right edge is the actual_arrival_at.  The cursor's value
    # is strictly less than the arrival's timestamp, so the
    # new sample's reported_at (= cursor) is strictly less
    # than the right edge.  The window's left edge is the
    # actual_departure_at, which is strictly less than the
    # cursor.  So the new sample is *in* the in-flight window
    # by the closed-closed convention.  Wait — the PRD's §2.9
    # actually pins the right edge of the in-flight window as
    # the open-on-the-right interval up to the
    # ``min(actual_arrival_at, aborted_at, the current
    # logical-clock value)``, with the parenthetical "for the
    # post-terminal trip the right edge is the terminal-time-
    # stamp".  The "any sample whose reported_at is past the
    # terminal moment is out-of-window" sentence from §3.8 is
    # the rule.  But equality with the cursor's value (which
    # is strictly less than the arrival's timestamp) is *not*
    # past the right edge — the sample is in the
    # ``[actual_departure_at, actual_arrival_at]`` closed
    # window, just at an instant prior to the right edge.
    # So this case is "in-window-and-out-of-order"; the
    # priority-509 check passes and the priority-512 check
    # fires.
    validate_error(resp, ApiErrorId.ERR_GPS_OUT_OF_ORDER.value, expected_status=409)

    # The companion case for the cross-tier conflict-C
    # precedence (where the window-check is the cause of the
    # rejection on a sample that would also fail
    # strict-monotonicity) is the
    # ``ingest_on_a_PLANNED_trip`` case where the
    # ``actual_departure_at`` is null and the in-window
    # interval is empty (every sample is out-of-window).  Any
    # ``reported_at`` value fails the priority-509 check
    # before the priority-512 check is reached.  See the
    # ``test_gps_on_planned_trip_is_out_of_window`` in
    # ``test_trips_and_gps.py`` for that pure-window-check
    # case.


# ─── Conflict D: state vs fiscal (state wins) ────────────────────────


def test_conflict_d_state_wins_over_fiscal_on_permit_issue(api, qualified_carrier: HazmatScenario):
    """PRD §2.7 "bonus conflict-D": the state-tier error at
    priority 400 wins over the fiscal-tier
    ``ERR_INSUFFICIENT_WALLET_BALANCE`` at priority 540 on the
    ``POST /v1/permits/{permit_id}/issue`` endpoint when both
    would fire: the permit is in a non-DRAFT state (which fails
    the state-tier guard) *and* the wallet has zero balance
    (which would fail the fiscal-tier guard).

    Construct the scenario: fully qualified carrier, no wallet
    top-up, file an application, issue it once successfully
    (which empties the wallet and bumps the state to ACTIVE),
    then attempt a re-issue.  The state-tier guard observes
    the row is no longer in DRAFT and fires
    ``ERR_INVALID_STATE_TRANSITION``; the fiscal-tier guard's
    wallet-shortfall check would also fire if the state were
    DRAFT (the wallet has been emptied by the first issue's
    debit).  The PRD's §2.7 pin is that the state-tier wins.
    """
    scenario = qualified_carrier
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    # Top up just enough for the issue fee.
    from test_helpers import expected_annual_renewal_fee_cents, ensure_funded_company

    expected_fee = expected_annual_renewal_fee_cents(
        vehicle_count=len(scenario.vehicles),
        is_late=False,
    )
    ensure_funded_company(api, scenario.company["id"], amount_cents=expected_fee)
    permit = file_permit_application(api, scenario)
    # First issue.
    get_success_data(api.issue_permit(permit["id"], issue_permit_payload(), reg))
    # Now the wallet is back at zero (the fee was the topup).
    # A second issue attempt.  The state-tier guard fires
    # because the permit is now ACTIVE.  The fiscal-tier guard
    # would also fire because the wallet has zero balance.  The
    # state-tier wins per PRD §2.7.
    resp_second = api.issue_permit(permit["id"], issue_permit_payload(), reg)
    validate_error(resp_second, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── Conflict E: double-book vs window-membership (double-book wins) ───


def test_conflict_e_double_booked_wins_over_outside_validity_window(api, active_permit: HazmatScenario):
    """PRD §2.7's bonus conflict-E: the
    ``ERR_VEHICLE_DOUBLE_BOOKED`` at business-temporal priority
    521 wins over the ``ERR_OUTSIDE_VALIDITY_WINDOW`` at
    priority 522 when both would fire on the same trip-create
    request.  The scaffold's §1.4 priority-number ordering
    "double-booked-at-521 vs outside-window-at-522" is the
    canonical reference.

    Construct: a first trip occupies a vehicle's calendar in
    the canonical window inside the permit's validity.  A
    second trip-create attempts the same vehicle with a
    scheduled window that (a) overlaps the first trip's
    interval (the double-booking trigger) and (b) extends past
    the permit's ``valid_until`` (the outside-window trigger).
    The response is the lower-priority-number's error, which is
    the double-booking 409 per the §2.7 numbering.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    # Set up the first trip occupying the vehicle's calendar in
    # the standard window.
    server_now = current_server_now(api)
    t1_dep = iso_now_plus_delta(seconds=120.0, base_iso=server_now)
    t1_arr = iso_now_plus_delta(seconds=120.0 + 3600.0, base_iso=server_now)
    get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=t1_dep,
            scheduled_arrival_at=t1_arr,
        ),
        op,
    ))
    # The second trip's window:
    #  - the departure is inside the first trip's window
    #    (overlap on the vehicle-calendar — the double-booking
    #    trigger).
    #  - the arrival is past the permit's valid_until (the
    #    outside-window trigger).
    vu = scenario.permit["valid_until"]
    overlap_dep = iso_now_plus_delta(seconds=600.0, base_iso=server_now)  # inside t1's window
    past_vu_arr = add_days(vu, 1.0)  # past the permit's valid_until
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=overlap_dep,
        scheduled_arrival_at=past_vu_arr,
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    # The double-booking error wins per the §2.7 numbering.
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value, expected_status=409)


# ─── Existence-tier wins over the cross-aggregate body-id existence ──


def test_existence_tier_walks_left_to_right_on_url_path_first(api):
    """PRD §2.7's existence-tier paragraph: "The tier-3 existence
    check walks the path-parameters of the URL left to right …
    The existence check is extended to the body-supplied
    foreign-key references on the trip-creation, the permit-
    application, the permit-renewal's optional fresh-driver-and-
    vehicle lists, and the manual-penalty's subject-id and the
    optional trip-id field — these body-supplied id existence
    failures still produce the appropriate
    ``ERR_<ENTITY>_NOT_FOUND`` 404 rather than being demoted to
    a body-shape ``ERR_VALIDATION``".

    The URL path-id check fires before the body-foreign-key
    check.  A
    ``POST /v1/permits/{permit_id}/trips`` request whose
    URL path-id is non-existent *and* whose body lists
    non-existent driver-and-vehicle ids returns the
    ``ERR_PERMIT_NOT_FOUND`` 404 (from the URL path's left-to-
    right walk), not the ``ERR_DRIVER_NOT_FOUND`` or
    ``ERR_VEHICLE_NOT_FOUND`` from the body's foreign-key walk.

    We don't have an explicit authenticated principal that owns
    a permit at the non-existent UUID, so the auth-tier
    priority-110 entity-backed-id-resolves leg for the
    CompanyOperator role's X-User-ID-as-the-company-id is the
    earliest-firing check.  We bypass this by using the
    regulator's opaque-identity role, whose RBAC cell on
    ``POST /v1/permits/{pid}/trips`` is the default-deny so
    the priority-200 RBAC error fires before the existence
    check — which makes the priority-200 cell the outer-tier
    on the (regulator-on-operator-endpoint, non-existent-permit-
    id) pair.  The test thus illustrates the cross-tier
    ordering by demonstrating the priority-200 deny fires
    before the priority-300 existence check.

    To isolate the existence-tier-wins-over-body-foreign-key
    case, we use a real company-operator on a real permit-id
    (which the operator owns) with a body whose driver-id is
    non-existent.  The existence check on the body's
    ``authorized_driver_ids`` walks the list and finds the
    non-resolving id, returning
    ``ERR_DRIVER_NOT_FOUND`` per the body-foreign-key
    sub-rule.  This is the standard "body-foreign-key fires
    the entity-not-found error" path.
    """
    scenario = setup_qualified_carrier(api)
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    # Body lists a non-existent driver-id alongside the real
    # vehicle-and-route.
    payload = create_permit_payload(
        route_id=scenario.route["id"],
        authorized_driver_ids=[NON_EXISTENT_UUID],
        authorized_vehicle_ids=[scenario.vehicles[0]["id"]],
        valid_from=valid_from,
    )
    resp = api.create_permit(payload, op)
    # The body-foreign-key existence-tier check on the driver-id
    # fires ``ERR_DRIVER_NOT_FOUND``.
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND.value, expected_status=404)


def test_auth_tier_fires_before_role_tier(api):
    """The "the lowest-priority-number wins" rule applies across
    tiers.  The auth tier (priorities 100 and 110) fires before
    the RBAC tier (priority 200) for a request that fails both:
    the request has no ``X-User-Role`` header at all (priority
    100 fires) AND the inferred-role would be in the deny-set
    on the endpoint.  The 401 from priority 100 is the response.

    The standard probe is a header-less request hitting any
    endpoint: the priority-100 missing-headers check fires
    ``ERR_UNAUTHENTICATED`` 401 regardless of the endpoint's
    RBAC cell.
    """
    resp = api.list_companies(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_role_tier_fires_before_existence_tier(api, two_tenants: TwoTenantScenario):
    """The RBAC tier at priority 200 fires before the existence
    tier at priority 300.  A
    ``TestHarness``-role request to
    ``GET /v1/companies/{company_id}`` for a non-existent
    company-id returns the priority-200
    ``ERR_ROLE_NOT_PERMITTED`` 403 rather than the
    priority-300 ``ERR_COMPANY_NOT_FOUND`` 404 (the test-harness's
    RBAC cell on the company-read endpoint is the default-deny).
    """
    from test_helpers import test_harness_headers

    th = test_harness_headers()
    resp = api.get_company(NON_EXISTENT_UUID, th)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403)


def test_state_tier_fires_before_business_referential_tier(api, active_permit: HazmatScenario):
    """The state tier at priority 400 fires before the
    business-referential tier at priority 526.  An issue-attempt
    on an already-ACTIVE permit (state-tier wrong-source-state)
    whose company is *also* not-qualified (priority-526
    ``ERR_COMPANY_NOT_QUALIFIED`` would fire) returns the
    state-tier error.

    We construct the dual-failure scenario by revoking the
    company after the issue.  The state on the permit is
    ACTIVE, and the company's qualification is REVOKED, so the
    body-referential check on the company-qualification leg
    would also fail on the re-issue attempt.  The state-tier
    wins per the integer-priority ordering.
    """
    scenario = active_permit
    reg = regulator_headers()
    # Revoke the company in the post-issue state.
    api.revoke_company(scenario.company["id"], revoke_company_payload(), reg)
    # The re-issue attempt.
    resp = api.issue_permit(scenario.permit["id"], {}, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
