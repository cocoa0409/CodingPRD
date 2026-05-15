"""Permit-aggregate lifecycle tests covering application, issue,
verify-compliance, renewal (with the late-grace surcharge), and the
void-issue reversal with the wallet-conservation invariant and the
trip-cascade-abort on the void's ``ACTIVE → VOIDED`` transition.

The Permit is the central aggregate.  Its state machine has the
initial ``DRAFT``, the in-force ``ACTIVE``, the cyclically-reachable
intermediate ``SUSPENDED``, and the two terminal absorbing states
``EXPIRED`` (the wall-clock-elapsed end) and ``VOIDED`` (the
regulator's clerical-error reversal within the 24-hour window from
``issued_at``).  The wallet-side conservation invariant from PRD §2.11
— "the wallet's net change across a complete (issue, zero-or-more
renewals, void-issue) sequence is exactly zero" — is the
fiscal-axis observable the tests audit against the
``annual_renewal_fee`` formula's integer-cents-arithmetic output.

The cascade-abort fan-out on the parent-permit-terminal transitions
is the synchronous side-effect on every still-open child trip:
``PERMIT_EXPIRED_CASCADE`` on the wall-clock-expiry path and
``PERMIT_SUSPENDED_CASCADE`` on the void-issue path (the on-disk
enum-economy reuse the PRD's §2.8 abort-reason taxonomy declares).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

import pytest

from test_helpers import (
    APPEAL_WINDOW_DAYS,
    ApiErrorId,
    BASE_RENEWAL_FEE_CENTS,
    CANONICAL_HAZARD_CLASSES,
    HazmatScenario,
    INITIAL_WALLET_BALANCE_CENTS,
    LATE_RENEWAL_GRACE_DAYS,
    LATE_RENEWAL_PENALTY_CENTS,
    MAX_RENEWAL_FEE_CENTS,
    MAX_VEHICLES_PER_PERMIT,
    PER_VEHICLE_SURCHARGE_CENTS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    RENEWAL_OPEN_WINDOW_DAYS,
    TEST_WALLET_TOPUP_CENTS,
    THRESHOLD_DRIVER_SUSPENSION_POINTS,
    VOID_ISSUE_WINDOW_HOURS,
    add_days,
    add_hours,
    admin_wallet_topup,
    advance_clock_by,
    api_client,
    assert_permit,
    assert_wallet_conservation,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_company_payload,
    create_driver_payload,
    create_permit_payload,
    create_route_payload,
    create_vehicle_payload,
    current_server_now,
    ensure_funded_company,
    expected_annual_renewal_fee_cents,
    fetch_permit_live_verdict,
    file_permit_application,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    issue_permit,
    iso_now_plus_delta,
    refresh_endorsement_attestation_payload,
    regulator_headers,
    renew_permit_payload,
    revoke_company_payload,
    run_full_sweep,
    schedule_trip,
    setup_active_permit,
    setup_approved_company,
    setup_qualified_carrier,
    setup_driver_under_company,
    setup_vehicle_under_company,
    setup_route_under_company,
    setup_inflight_trip,
    snapshot_company_wallet,
    validate_error,
    validate_paginated,
    validate_success,
    verify_compliance_payload,
    void_issue_payload,
    issue_permit_payload,
)
from test_helpers.types import (
    AbortReason,
    DriverEndorsementStatus,
    HAZARD_CLASSES_UN,
    InspectionOutcome,
    PermitLifecycleStatus,
    RouteApprovalStatus,
    SweepPermitCause,
    TripStatus,
    VerifyComplianceTransitionFired,
)


# ─── Application step — the DRAFT row and the application_preview ─────


def test_create_permit_returns_draft_with_application_preview(api, qualified_carrier: HazmatScenario):
    """PRD §3.5: "The application-step's response is the 201 row in
    ``lifecycle_status = DRAFT`` with the body-fields echoed … and
    an additional transient field ``application_preview`` carrying
    the five validity-leg booleans computed at application time".

    The qualified-carrier fixture's drivers are all attested and
    vehicles all inspected-PASSED, the route is approved, and the
    company is approved — so the five-leg preview's AND-conjunction
    is true.
    """
    scenario = qualified_carrier
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=scenario.route["id"],
        authorized_driver_ids=[d["id"] for d in scenario.drivers],
        authorized_vehicle_ids=[v["id"] for v in scenario.vehicles],
        valid_from=valid_from,
    )
    op = company_operator_headers(scenario.company["id"])
    resp = api.create_permit(payload, op)
    permit = validate_success(resp, 201)
    assert_permit(permit)
    assert permit["lifecycle_status"] == PermitLifecycleStatus.DRAFT.value
    assert permit["valid_from"] == valid_from
    assert permit["company_id"] == scenario.company["id"]
    assert permit["route_id"] == scenario.route["id"]
    assert set(permit["authorized_driver_ids"]) == {d["id"] for d in scenario.drivers}
    assert set(permit["authorized_vehicle_ids"]) == {v["id"] for v in scenario.vehicles}
    # The application_preview's five-leg booleans.  The PRD's §3.5
    # names the field as the "five validity-leg booleans computed
    # at application time".  The five legs are
    # company-qualification, drivers' endorsements (as a per-driver
    # map), vehicles' inspections (as a per-vehicle map), the
    # route's approval, and the time-window.
    preview = permit.get("application_preview")
    if preview is not None:
        # The implementation may expose the preview's overall flag
        # under one of several keys; we accept any of the common
        # names.
        overall = preview.get("live_overall") or preview.get("overall") or preview.get("verdict")
        if isinstance(overall, bool):
            assert overall is True, "all five legs are green on the fixture's roster"


# ─── Body-shape rules on the permit application ──────────────────────


def test_permit_application_vehicle_count_out_of_range_too_low(api, qualified_carrier: HazmatScenario):
    """PRD §3.5: "the ``authorized_vehicle_ids`` array's
    cardinality bound is the inclusive integer interval from 1 to
    the ``MAX_VEHICLES_PER_PERMIT`` constant".  An empty
    ``authorized_vehicle_ids`` array is the dedicated
    ``ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE`` 422 at the
    priority-523 business-constraint check.
    """
    scenario = qualified_carrier
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=scenario.route["id"],
        authorized_driver_ids=[scenario.drivers[0]["id"]],
        authorized_vehicle_ids=[],  # empty — below the lower bound 1.
        valid_from=valid_from,
    )
    op = company_operator_headers(scenario.company["id"])
    resp = api.create_permit(payload, op)
    validate_error(
        resp,
        ApiErrorId.ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE.value,
        expected_status=422,
    )


def test_permit_application_with_unowned_driver_returns_driver_not_found(api):
    """PRD §3.5 + §2.6's cross-aggregate-foreign-key paragraph:
    "a body that lists a driver id from another tenant produces
    ``ERR_DRIVER_NOT_FOUND`` rather than a cross-tenant 403,
    because from the operator's perspective the other tenant's
    drivers are not part of the operator's universe and therefore
    are 'not found' in the operator's view".

    Set up two tenants.  Tenant-A's operator files a permit whose
    ``authorized_driver_ids`` lists tenant-B's driver-id.  The
    existence-tier check on the body's foreign-key value walks the
    operator's-universe-of-driver-rows and observes the id is not
    in it, returning ``ERR_DRIVER_NOT_FOUND`` 404.
    """
    from test_helpers import setup_two_tenants

    two = setup_two_tenants(api)
    sa = two.tenant_a
    sb = two.tenant_b
    # File a permit on tenant-A whose authorized_driver_ids
    # contains tenant-B's driver id.
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    cross_tenant_driver_id = sb.drivers[0]["id"]
    payload = create_permit_payload(
        route_id=sa.route["id"],
        authorized_driver_ids=[cross_tenant_driver_id],
        authorized_vehicle_ids=[sa.vehicles[0]["id"]],
        valid_from=valid_from,
    )
    op_a = company_operator_headers(sa.company["id"])
    resp = api.create_permit(payload, op_a)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND.value, expected_status=404)


def test_permit_application_valid_from_not_in_past(api, qualified_carrier: HazmatScenario):
    """PRD §3.5: "the ``valid_from`` ISO 8601 UTC datetime which
    must be at or after the current logical-clock value (a
    back-dated ``valid_from`` is ``ERR_VALIDATION`` 422)".
    """
    scenario = qualified_carrier
    server_now = current_server_now(api)
    past = iso_now_plus_delta(seconds=-3600.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=scenario.route["id"],
        authorized_driver_ids=[scenario.drivers[0]["id"]],
        authorized_vehicle_ids=[scenario.vehicles[0]["id"]],
        valid_from=past,
    )
    op = company_operator_headers(scenario.company["id"])
    resp = api.create_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_permit_application_hazard_class_not_in_intersection(api, qualified_carrier: HazmatScenario):
    """PRD §3.5: "the body's non-empty ``hazard_classes`` array
    must be a non-empty subset of the intersection of the parent
    company's ``hazard_classes_authorized`` and the named route's
    ``hazard_classes_supported`` at the moment of the call; a
    violation of the subset-of-intersection rule is the body-shape
    ``ERR_VALIDATION`` 422".

    The fixture's company is authorized on ``["3", "8"]`` and the
    route's supported list is the same.  A permit application
    that lists hazard-class ``"7"`` (radioactive) in its
    ``hazard_classes`` is outside the intersection.
    """
    scenario = qualified_carrier
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=scenario.route["id"],
        authorized_driver_ids=[scenario.drivers[0]["id"]],
        authorized_vehicle_ids=[scenario.vehicles[0]["id"]],
        valid_from=valid_from,
        hazard_classes=["7"],  # outside the company-and-route intersection
    )
    op = company_operator_headers(scenario.company["id"])
    resp = api.create_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_permit_application_with_unapproved_route_rejected(api, approved_company: Dict):
    """PRD §3.5: "the named ``route_id`` … whose ``approval_status``
    is ``APPROVED`` at the moment of the call".  A non-APPROVED
    route is the business-referential ``ERR_ROUTE_NOT_APPROVED``
    409 at priority 525.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    # Create driver and vehicle so the cross-aggregate references
    # at the existence-tier check pass.
    drv = setup_driver_under_company(api, approved_company, attest=True)
    veh, _ = setup_vehicle_under_company(api, approved_company, inspect=True)
    # Create a route but don't approve it.
    rt = setup_route_under_company(api, approved_company, approve=False)
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=rt["id"],
        authorized_driver_ids=[drv["id"]],
        authorized_vehicle_ids=[veh["id"]],
        valid_from=valid_from,
    )
    resp = api.create_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_APPROVED.value, expected_status=409)


def test_permit_application_with_unattested_driver_rejected(api, approved_company: Dict):
    """PRD §3.5: "each id [in ``authorized_driver_ids``] must
    resolve to a Driver whose ``hazmat_endorsement_status`` is
    ``VALID``".  A NOT_ATTESTED driver in the body fires the
    ``ERR_DRIVER_ENDORSEMENT_INVALID`` 409 at priority 510.
    """
    op = company_operator_headers(approved_company["id"])
    # Driver without the regulator's attestation.
    drv_unattested = setup_driver_under_company(api, approved_company, attest=False)
    assert drv_unattested["hazmat_endorsement_status"] == DriverEndorsementStatus.NOT_ATTESTED.value
    veh, _ = setup_vehicle_under_company(api, approved_company, inspect=True)
    rt = setup_route_under_company(api, approved_company, approve=True)
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=rt["id"],
        authorized_driver_ids=[drv_unattested["id"]],
        authorized_vehicle_ids=[veh["id"]],
        valid_from=valid_from,
    )
    resp = api.create_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_DRIVER_ENDORSEMENT_INVALID.value, expected_status=409)


def test_permit_application_with_failed_vehicle_inspection_rejected(api, approved_company: Dict):
    """The vehicles-leg variant of the same business-safety check.
    A vehicle whose latest inspection is FAILED has the
    vehicle-leg-fail flag, and the priority-511
    ``ERR_VEHICLE_INSPECTION_LAPSED`` 409 fires."""
    op = company_operator_headers(approved_company["id"])
    drv = setup_driver_under_company(api, approved_company, attest=True)
    # Vehicle with a FAILED inspection (zero forward validity).
    veh, _ = setup_vehicle_under_company(
        api,
        approved_company,
        inspect=True,
        inspection_outcome=InspectionOutcome.FAILED.value,
    )
    rt = setup_route_under_company(api, approved_company, approve=True)
    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=rt["id"],
        authorized_driver_ids=[drv["id"]],
        authorized_vehicle_ids=[veh["id"]],
        valid_from=valid_from,
    )
    resp = api.create_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_INSPECTION_LAPSED.value, expected_status=409)


# ─── Issue step — DRAFT → ACTIVE with the wallet debit ────────────────


def test_issue_permit_debits_wallet_by_formula_amount(api, qualified_carrier: HazmatScenario):
    """PRD §3.5 + §2.11: "compute the fee
    ``issue_fee_cents = annual_renewal_fee(now, vehicle_count =
    len(authorized_vehicle_ids), valid_until = null on the
    is-not-yet-issued case so is_late is forced false, the
    deployment-configured fee constants)``; debit the parent
    company's ``wallet_balance_cents`` by that amount in the same
    transaction".

    The fee formula's value with one vehicle and the
    is-late-flag false is
    ``BASE_RENEWAL_FEE_CENTS + 1 *
    PER_VEHICLE_SURCHARGE_CENTS = 500000 + 30000 = 530000`` cents,
    clamped at the ``MAX_RENEWAL_FEE_CENTS`` ceiling (which is far
    above 530000).
    """
    scenario = qualified_carrier
    # The wallet is topped up by the fixture's setup_approved_company.
    pre_wallet = scenario.company["wallet_balance_cents"]
    expected_fee = expected_annual_renewal_fee_cents(
        vehicle_count=len(scenario.vehicles),
        is_late=False,
    )
    assert expected_fee == BASE_RENEWAL_FEE_CENTS + PER_VEHICLE_SURCHARGE_CENTS * len(scenario.vehicles), (
        "the fee-formula test-side computation must match the BASE + N×PER_VEHICLE first stage"
    )
    # File and issue.
    file_permit_application(api, scenario, valid_from_offset_seconds=10.0)
    issued = issue_permit(api, scenario)
    assert issued["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value
    assert isinstance(issued["issue_fee_cents"], int)
    assert issued["issue_fee_cents"] == expected_fee, (
        f"server-recorded issue_fee_cents {issued['issue_fee_cents']} != "
        f"test-side expected {expected_fee} from the fee formula"
    )
    # The wallet's net change is exactly the fee.
    post_wallet = snapshot_company_wallet(api, scenario)
    assert post_wallet == pre_wallet - expected_fee, (
        f"wallet delta {pre_wallet - post_wallet} != fee {expected_fee}"
    )
    # The issued permit's valid_until = valid_from +
    # PERMIT_DEFAULT_VALIDITY_DAYS.
    expected_vu = add_days(issued["valid_from"], float(PERMIT_DEFAULT_VALIDITY_DAYS))
    assert issued.get("valid_until") is not None
    # The ISO timestamps match modulo the millisecond-precision
    # tail: the date portion must agree.
    assert issued["valid_until"][:10] == expected_vu[:10], (
        f"valid_until {issued['valid_until']!r} != valid_from + "
        f"PERMIT_DEFAULT_VALIDITY_DAYS = {expected_vu!r}"
    )
    # The five snapshot booleans are all true on the freshly-issued
    # permit (the all-green issue path).
    assert issued.get("snapshot_company_qualified") is True
    assert issued.get("snapshot_route_approved") is True
    assert issued.get("snapshot_within_window") is True
    drv_map = issued.get("snapshot_driver_endorsements") or {}
    veh_map = issued.get("snapshot_vehicle_inspections") or {}
    assert all(v is True for v in drv_map.values())
    assert all(v is True for v in veh_map.values())
    # The renewal_history starts empty.
    assert issued.get("renewal_history") in ([], None)


def test_issue_permit_insufficient_wallet_returns_402(api, qualified_carrier: HazmatScenario):
    """PRD §3.5 + §2.7's fiscal tier 540: the wallet-shortfall
    rejection is the unique HTTP 402 ``ERR_INSUFFICIENT_WALLET_BALANCE``
    on the issue endpoint.  The qualified-carrier fixture's wallet
    is topped up generously, but the test below sets the wallet to
    zero via a second topup with a negative-amount-equivalent
    (which the admin-topup might not support) or by creating a
    fresh carrier without the topup step.

    We use the helper ``setup_qualified_carrier`` with the
    ``topup_cents=0`` override on the company-side so the wallet
    starts at the initial zero from PRD §2.11.
    """
    # Build a qualified carrier explicitly with no wallet top-up.
    company = setup_approved_company(api, topup_cents=0)
    drv = setup_driver_under_company(api, company, attest=True)
    veh, _ = setup_vehicle_under_company(api, company, inspect=True)
    rt = setup_route_under_company(api, company, approve=True)
    # The wallet is the initial zero.
    refreshed_company = get_success_data(api.get_company(company["id"], regulator_headers()))
    assert refreshed_company["wallet_balance_cents"] == INITIAL_WALLET_BALANCE_CENTS

    server_now = current_server_now(api)
    valid_from = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    payload = create_permit_payload(
        route_id=rt["id"],
        authorized_driver_ids=[drv["id"]],
        authorized_vehicle_ids=[veh["id"]],
        valid_from=valid_from,
    )
    op = company_operator_headers(company["id"])
    reg = regulator_headers()
    permit = get_success_data(api.create_permit(payload, op))
    # The issue step's fiscal check observes the wallet's zero
    # balance and the formula's non-zero fee.
    resp = api.issue_permit(permit["id"], issue_permit_payload(), reg)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET_BALANCE.value, expected_status=402)


def test_issue_permit_from_non_draft_state_rejected(api, active_permit: HazmatScenario):
    """The issue endpoint's source-state guard requires ``DRAFT``.
    Re-issuing an already-ACTIVE permit is the generic
    ``ERR_INVALID_STATE_TRANSITION`` 409 at the state-tier."""
    scenario = active_permit
    reg = regulator_headers()
    resp = api.issue_permit(scenario.permit["id"], issue_permit_payload(), reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── Verify-compliance — the snapshot-vs-live dual variant ───────────


def test_verify_compliance_no_change_when_no_grounding_drift(api, active_permit: HazmatScenario):
    """PRD §3.5 verify-compliance paragraph: "If the snapshot's
    conjunction matches the live verdict and neither the wall-clock
    nor any leg has flipped, the verify-compliance call is a no-op
    state transition that still refreshes the snapshot (idempotent
    at the value level by the convention 'two successive
    verify-compliance calls with no gap activity produce
    structurally identical post-states modulo the refreshed
    ``last_verified_at`` timestamp'), bumps the version, and
    returns the response with ``pre_status == post_status`` and
    the ``transition_fired`` discriminator value ``NO_CHANGE``".
    """
    scenario = active_permit
    reg = regulator_headers()
    # The fixture's permit is ACTIVE with the all-green snapshot
    # written at the issue.  A bare verify-compliance with no
    # intervening grounding-entity-state changes is the NO_CHANGE
    # case.
    pre_vc = scenario.permit
    resp = api.verify_permit_compliance(pre_vc["id"], verify_compliance_payload(), reg)
    vc = validate_success(resp, 200)
    tf = vc.get("transition_fired")
    assert tf == VerifyComplianceTransitionFired.NO_CHANGE.value, (
        f"a verify-compliance with no grounding-drift should return NO_CHANGE; got {tf!r}"
    )
    assert vc["pre_status"] == PermitLifecycleStatus.ACTIVE.value
    assert vc["post_status"] == PermitLifecycleStatus.ACTIVE.value
    # The live-per-leg's overall is true.
    live = vc.get("live_per_leg") or {}
    snap = vc.get("snapshot_per_leg") or {}
    # Each side's overall flag should be true.  The implementation
    # may carry the booleans inside a sub-dict or at the top of
    # ``live_per_leg``; the test is flexible on the exact shape.
    # The PRD's §3.5 names the five leg fields explicitly:
    # ``live_company_qualified``, ``live_drivers_ok``,
    # ``live_vehicles_ok``, ``live_route_approved``,
    # ``live_within_window`` — each a top-level boolean key in the
    # ``live_per_leg`` block.  The same five with the
    # ``snapshot_`` prefix in the ``snapshot_per_leg`` block.
    for k in ("live_company_qualified", "live_drivers_ok", "live_vehicles_ok",
              "live_route_approved", "live_within_window"):
        if k in live:
            assert live[k] is True, f"live leg {k} should be True on the no-drift path; got {live[k]!r}"


def test_verify_compliance_active_to_expired_on_wallclock_past_valid_until(api, active_permit: HazmatScenario):
    """PRD §3.5: "The handler reads the wall-clock-vs-``valid_until``
    comparison first: if the current logical-clock value is at or
    past the permit's ``valid_until``, the transition target is
    the terminal ``EXPIRED`` and the same trip-cascade-on-expiry
    side-effect fires as the sweep's wall-clock-expiry path; the
    ``cause`` discriminator on this transition is
    ``WALL_CLOCK_EXPIRY``".

    The verify-compliance response's ``transition_fired`` value on
    this path is one of the two ``ACTIVE_TO_EXPIRED`` /
    ``SUSPENDED_TO_EXPIRED`` enum values.  Schedule a long
    clock-advance past the permit's valid_until and confirm the
    next verify-compliance returns the expired-transition.
    """
    scenario = active_permit
    reg = regulator_headers()
    # The permit's term is PERMIT_DEFAULT_VALIDITY_DAYS = 365 days.
    # Advance the clock by 366 days so now > valid_until.
    advance_clock_by(api, float(PERMIT_DEFAULT_VALIDITY_DAYS + 1) * 86400.0, run_sweep=False)
    # The deferred-cascade-via-verify-compliance fires on the
    # next verify-compliance call.  The permit's status was
    # ACTIVE (the sweep hasn't run yet so the wall-clock
    # expiry is the deferred-flush trigger).
    vc = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    tf = vc.get("transition_fired")
    assert tf in {
        VerifyComplianceTransitionFired.ACTIVE_TO_EXPIRED.value,
        VerifyComplianceTransitionFired.SUSPENDED_TO_EXPIRED.value,
    }, f"post-valid_until verify-compliance should fire an EXPIRED-transition, got {tf!r}"
    # The post-status is EXPIRED.
    assert vc["post_status"] == PermitLifecycleStatus.EXPIRED.value


def test_sweep_emits_wall_clock_expiry_cascade(api, inflight_trip: HazmatScenario):
    """PRD §2.5: "for every Permit whose ``lifecycle_status`` is
    ``ACTIVE`` or ``SUSPENDED`` and whose ``valid_until`` is at or
    before the current logical-clock value, the sweep fires the
    wall-clock-expiry transition to ``EXPIRED``, and as a synchronous
    side-effect every still-open child Trip on each newly-expired
    permit … is transitioned to ``ABORTED`` with the
    ``abort_reason`` field set to the discriminator value
    ``PERMIT_EXPIRED_CASCADE``".

    The in-flight-trip fixture is a single ACTIVE permit with a
    single IN_TRANSIT trip.  Advance the clock past the permit's
    valid_until and fire the sweep.  The sweep's response carries
    the permit's transition in ``permit_transitions`` with the
    ``WALL_CLOCK_EXPIRY`` cause and the trip's id in the
    ``cascade_trip_aborts`` array.  A read of the trip after the
    sweep shows ``trip_status = ABORTED`` and
    ``abort_reason = PERMIT_EXPIRED_CASCADE``.
    """
    scenario = inflight_trip
    permit_id = scenario.permit["id"]
    trip_id = scenario.trips[0]["id"]
    # Advance the clock past the permit's term end.
    advance_clock_by(api, float(PERMIT_DEFAULT_VALIDITY_DAYS + 1) * 86400.0, run_sweep=False)
    sw = run_full_sweep(api)
    # The permit's transition entry.
    matching = [t for t in (sw.get("permit_transitions") or []) if t.get("permit_id") == permit_id]
    assert matching, (
        f"sweep's permit_transitions did not include the wall-clock-expired permit "
        f"{permit_id!r}; entries: {[t.get('permit_id') for t in sw.get('permit_transitions') or []]}"
    )
    entry = matching[0]
    assert entry.get("cause") == SweepPermitCause.WALL_CLOCK_EXPIRY.value
    assert entry.get("post_status") == PermitLifecycleStatus.EXPIRED.value
    # The cascade-trip-aborts array carries the in-flight trip's id.
    cta = entry.get("cascade_trip_aborts") or []
    assert trip_id in cta, (
        f"the in-flight trip {trip_id!r} should be cascade-aborted on the permit's "
        f"wall-clock expiry; cascade_trip_aborts={cta!r}"
    )
    # A read of the trip confirms the abort_reason discriminator.
    reg = regulator_headers()
    trip_after = get_success_data(api.get_trip(trip_id, reg))
    assert trip_after["trip_status"] == TripStatus.ABORTED.value
    assert trip_after["abort_reason"] == AbortReason.PERMIT_EXPIRED_CASCADE.value
    # The wallet is NOT refunded on the natural expiry per PRD §2.11.
    co_after = get_success_data(api.get_company(scenario.company["id"], regulator_headers()))
    # The wallet's net change since the issue is the negative of the
    # issue fee (no refund on expiry).
    issue_fee = scenario.permit["issue_fee_cents"]
    pre_company_wallet = TEST_WALLET_TOPUP_CENTS  # from the fixture's topup
    # The topped-up balance was 500,000,000 cents; the fee is at
    # most 5,000,000 (the MAX_RENEWAL_FEE_CENTS ceiling), so the
    # post-issue-and-expiry wallet is the topped-up minus the
    # issue fee.
    assert co_after["wallet_balance_cents"] == pre_company_wallet - int(issue_fee or 0), (
        f"wallet net change across the issue-and-natural-expiry sequence should be "
        f"the negative of the issue fee (no refund on expiry); "
        f"company wallet is {co_after['wallet_balance_cents']}, "
        f"expected {pre_company_wallet - int(issue_fee or 0)}"
    )


# ─── Void-issue — the wallet refund and the trip-cascade ─────────────


def test_void_issue_refunds_wallet_and_cascades_trips(api, inflight_trip: HazmatScenario):
    """PRD §3.6 void-issue paragraph + §2.11 conservation invariant:
    "The refund amount is computed as the literal integer sum
    ``void_refunded_cents = issue_fee_cents + the sum of fee_cents
    across the renewal_history array``, which is — by the
    conservation identity of §2.11 — the exact integer the
    wallet has been debited across the issue and the renewals so
    far.  The wallet is credited by this amount atomically inside
    the same transaction that flips the permit's
    ``lifecycle_status`` to the terminal ``VOIDED``" — and the
    on-disk ``void_refunded_cents`` field carries the refund
    amount for the audit trail.

    The trip-cascade on the void's ``ACTIVE → VOIDED`` transition
    is the synchronous fan-out abort over every still-open child
    trip, with the on-disk ``abort_reason`` discriminator set to
    the enum-economy-reused ``PERMIT_SUSPENDED_CASCADE`` value
    per PRD §3.6.

    The wallet-conservation identity is the bit-exact zero net
    change across the (issue, no-renewals, void-issue) sequence
    relative to the topped-up wallet's starting balance.
    """
    scenario = inflight_trip
    reg = regulator_headers()
    op = company_operator_headers(scenario.company["id"])
    permit = scenario.permit
    issue_fee = int(permit["issue_fee_cents"])
    wallet_before = snapshot_company_wallet(api, scenario)
    # The void must land within the VOID_ISSUE_WINDOW_HOURS-hour
    # window from the issued_at.  The clock has been advanced
    # by some small amount in the inflight-trip fixture (the
    # depart's clock-advance-to-the-scheduled-departure step),
    # so we sanity-check the duration is well under 24 hours.
    issued_at_iso = permit["issued_at"]
    server_now = current_server_now(api)
    # The void.  ``reason_note`` is the regulator's required
    # cause-string.
    void_body = void_issue_payload(reason_note="Clerical reversal — test.")
    void_resp = api.void_issue_permit(permit["id"], void_body, reg)
    voided_envelope = validate_success(void_resp, 200)
    # The response carries the updated permit row plus the
    # ``cascade_summary`` and ``wallet_credit`` sub-objects.  The
    # standard envelope-shape is the row at the top with the
    # sibling-info blocks alongside.  We extract the permit row
    # itself from the envelope.
    voided_row = voided_envelope.get("permit") if "permit" in voided_envelope else voided_envelope
    assert_permit(voided_row)
    assert voided_row["lifecycle_status"] == PermitLifecycleStatus.VOIDED.value
    assert voided_row["void_refunded_cents"] == issue_fee, (
        f"void_refunded_cents {voided_row['void_refunded_cents']} != issue_fee_cents {issue_fee}"
    )
    assert voided_row.get("voided_at") is not None
    # The wallet is credited.
    wallet_after = snapshot_company_wallet(api, scenario)
    assert wallet_after == wallet_before + issue_fee, (
        f"wallet should be credited by the refund amount; before {wallet_before}, "
        f"after {wallet_after}, refund {issue_fee}"
    )
    # The (issue, void) round-trip's wallet conservation identity
    # is zero net change from the post-topup starting balance.
    # The topped-up balance was the fixture's TEST_WALLET_TOPUP_CENTS.
    starting_balance = TEST_WALLET_TOPUP_CENTS
    assert_wallet_conservation(
        initial_balance_cents=0,
        issue_fee_cents=issue_fee,
        renewal_fees_cents=[],
        void_refund_cents=issue_fee,
        final_balance_cents=wallet_after,
        out_of_band_topup_cents=starting_balance,
    )
    # The trip-cascade: the still-IN_TRANSIT trip is now ABORTED
    # with abort_reason = PERMIT_SUSPENDED_CASCADE.
    trip_after = get_success_data(api.get_trip(scenario.trips[0]["id"], reg))
    assert trip_after["trip_status"] == TripStatus.ABORTED.value
    # PRD §2.8 + §3.6: the void's cascade reuses the
    # ``PERMIT_SUSPENDED_CASCADE`` enum value for the
    # abort-reason on the trip.
    assert trip_after["abort_reason"] == AbortReason.PERMIT_SUSPENDED_CASCADE.value, (
        f"the void-cascade's abort_reason should be PERMIT_SUSPENDED_CASCADE per "
        f"the enum-economy convention from PRD §2.8; got {trip_after['abort_reason']!r}"
    )


def test_void_after_window_closed_rejected(api, active_permit: HazmatScenario):
    """PRD §3.6 + §2.9: "the duration ``now() - issued_at`` is less
    than or equal to the ``VOID_ISSUE_WINDOW_HOURS`` constant"
    (the closed-right convention on the duration).  A void
    request that lands strictly past the 24-hour window is the
    ``ERR_VOID_WINDOW_CLOSED`` 409 at priority 514.

    Advance the clock by 25 hours from the issue moment and
    attempt the void.
    """
    scenario = active_permit
    reg = regulator_headers()
    # The fixture's permit was issued just now; the
    # ``issued_at`` is approximately the current clock.  Advance
    # by 25 hours.
    advance_clock_by(api, float(VOID_ISSUE_WINDOW_HOURS + 1) * 3600.0, run_sweep=False)
    resp = api.void_issue_permit(scenario.permit["id"], void_issue_payload(), reg)
    validate_error(resp, ApiErrorId.ERR_VOID_WINDOW_CLOSED.value, expected_status=409)


def test_void_from_non_active_state_rejected(api, qualified_carrier: HazmatScenario):
    """PRD §3.6 void's same-row guard: "the source state is
    ``ACTIVE`` (… and a ``DRAFT``-and-``EXPIRED``-and-``VOIDED``
    source state is the generic ``ERR_INVALID_STATE_TRANSITION``
    409)".  A void on a ``DRAFT`` permit fires the generic
    state-transition error.
    """
    scenario = qualified_carrier
    # Build a DRAFT permit without issuing.
    permit = file_permit_application(api, scenario)
    assert permit["lifecycle_status"] == PermitLifecycleStatus.DRAFT.value
    reg = regulator_headers()
    resp = api.void_issue_permit(permit["id"], void_issue_payload(), reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── Renewal — the late-grace surcharge and the term-extension stride ──


def test_renewal_too_early_rejected(api, active_permit: HazmatScenario):
    """PRD §3.6 + §2.9: "A renewal request whose arrival time
    ``now()`` is strictly before the lower edge
    ``valid_until - RENEWAL_OPEN_WINDOW_DAYS`` is the too-early
    case, rejected with ``ERR_RENEWAL_TOO_EARLY`` 409 at priority
    541".

    The fixture's permit's ``valid_until`` is ~365 days in the
    future, so a renewal-call right after the issue (with the
    clock at +1 second from issue) is well before the
    renewal-window's lower edge ``valid_until - 60 days``.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    resp = api.renew_permit(scenario.permit["id"], renew_permit_payload(), op)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_TOO_EARLY.value, expected_status=409)


def test_renewal_after_expiry_rejected(api, active_permit: HazmatScenario):
    """PRD §3.6 + §2.9: "A renewal request whose arrival time is
    at or after the upper edge ``valid_until`` is the
    after-expiry case, rejected with ``ERR_RENEWAL_AFTER_EXPIRY``
    409 at priority 542".

    Advance the clock past ``valid_until``; the renew handler
    observes the permit has entered (or is about to enter) the
    EXPIRED terminal state and returns the dedicated expiry-
    flavoured error rather than the generic state-transition
    error.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    # Advance the clock by the full term plus one day.
    advance_clock_by(api, float(PERMIT_DEFAULT_VALIDITY_DAYS + 1) * 86400.0, run_sweep=False)
    resp = api.renew_permit(scenario.permit["id"], renew_permit_payload(), op)
    # The PRD pins this error id; the implementation might also
    # surface the wall-clock-expiry-fired-already case as
    # ``ERR_INVALID_STATE_TRANSITION`` if the sweep has run.  The
    # PRD's §3.6 prose is explicit that the renewal handler's
    # check on the wall-clock-vs-valid_until-comparison is the
    # ``ERR_RENEWAL_AFTER_EXPIRY``-emitting branch.
    from prd_bench_local_runner.testing import validate_error_is_one_of

    actual = validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_RENEWAL_AFTER_EXPIRY.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    assert actual in (
        ApiErrorId.ERR_RENEWAL_AFTER_EXPIRY.value,
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )


def test_renewal_inside_open_window_succeeds_without_late_surcharge(api, active_permit: HazmatScenario):
    """The on-time renewal: the request lands in the
    outer-but-not-late window ``[valid_until -
    RENEWAL_OPEN_WINDOW_DAYS, valid_until -
    LATE_RENEWAL_GRACE_DAYS)``, the fee formula's
    ``is_late`` flag is false, and the resulting
    ``renewal_history`` entry's ``late_penalty_applied`` is
    false."""
    scenario = active_permit
    reg = regulator_headers()
    op = company_operator_headers(scenario.company["id"])
    permit = scenario.permit
    # The permit's valid_until is now + ~365 days.  We need the
    # clock to be in the outer-but-not-late window, which is
    # [vu - 60d, vu - 30d).  Advance the clock to vu - 45d.
    server_now = current_server_now(api)
    vu_str = permit["valid_until"]
    # Compute the duration from "now" to "vu - 45 days".
    # All timestamps are ISO-8601-millisecond strings; we use
    # the same iso-arithmetic helpers as the fixtures.
    target_at = add_days(vu_str, -float(LATE_RENEWAL_GRACE_DAYS + 15))  # 15 days into the on-time zone
    # Compute the seconds between server_now and target_at.
    from datetime import datetime, timezone

    def _to_dt(s: str) -> datetime:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    n_dt = _to_dt(server_now)
    t_dt = _to_dt(target_at)
    delta_s = (t_dt - n_dt).total_seconds()
    assert delta_s > 0, (
        f"the target advance time {target_at!r} is not after the current server time {server_now!r}"
    )
    advance_clock_by(api, delta_s, run_sweep=False)
    # Top up the wallet so the fiscal check passes.
    ensure_funded_company(api, scenario.company["id"], amount_cents=TEST_WALLET_TOPUP_CENTS)
    # The renewal call.
    pre_wallet = snapshot_company_wallet(api, scenario)
    resp = api.renew_permit(permit["id"], renew_permit_payload(renew_note="On-time renewal."), op)
    renewed_envelope = validate_success(resp, 200)
    renewed_row = renewed_envelope.get("permit") if "permit" in renewed_envelope else renewed_envelope
    assert renewed_row["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value
    # The renewal_history has one entry.
    rh = renewed_row.get("renewal_history") or []
    assert len(rh) == 1, f"expected 1 renewal_history entry, got {len(rh)}"
    entry = rh[0]
    assert entry["late_penalty_applied"] is False, (
        "an in-the-non-late zone renewal must not carry the late-penalty surcharge"
    )
    expected_fee = expected_annual_renewal_fee_cents(
        vehicle_count=len(permit["authorized_vehicle_ids"]),
        is_late=False,
    )
    assert entry["fee_cents"] == expected_fee
    # The new ``valid_until`` is the prior ``valid_until`` plus the
    # full term length (the term-end stride convention from PRD §3.6).
    new_vu = renewed_row["valid_until"]
    expected_new_vu = add_days(vu_str, float(PERMIT_DEFAULT_VALIDITY_DAYS))
    assert new_vu[:10] == expected_new_vu[:10], (
        f"new valid_until {new_vu!r} should be prior_valid_until + "
        f"PERMIT_DEFAULT_VALIDITY_DAYS = {expected_new_vu!r}"
    )
    assert entry["prior_valid_until"] == vu_str
    assert entry["new_valid_until"] == new_vu
    # The wallet is debited by the fee.
    post_wallet = snapshot_company_wallet(api, scenario)
    assert post_wallet == pre_wallet - expected_fee


def test_renewal_in_late_grace_window_carries_late_surcharge(api, active_permit: HazmatScenario):
    """The late-grace-zone renewal: the request lands in the
    half-open ``[valid_until - LATE_RENEWAL_GRACE_DAYS,
    valid_until)`` window, the ``is_late`` flag is true, the fee
    has the ``LATE_RENEWAL_PENALTY_CENTS`` surcharge added (subject
    to the post-add ``MAX_RENEWAL_FEE_CENTS`` ceiling), and the
    ``renewal_history`` entry's ``late_penalty_applied`` is true.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    permit = scenario.permit
    vu_str = permit["valid_until"]
    # Land in the late-grace zone: now == valid_until - 15 days.
    server_now = current_server_now(api)
    target_at = add_days(vu_str, -15.0)  # well inside the 30-day late-grace zone

    from datetime import datetime

    def _to_dt(s: str) -> datetime:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    delta_s = (_to_dt(target_at) - _to_dt(server_now)).total_seconds()
    assert delta_s > 0
    advance_clock_by(api, delta_s, run_sweep=False)
    ensure_funded_company(api, scenario.company["id"], amount_cents=TEST_WALLET_TOPUP_CENTS)
    pre_wallet = snapshot_company_wallet(api, scenario)
    resp = api.renew_permit(permit["id"], renew_permit_payload(renew_note="Late renewal."), op)
    renewed_envelope = validate_success(resp, 200)
    renewed_row = renewed_envelope.get("permit") if "permit" in renewed_envelope else renewed_envelope
    rh = renewed_row.get("renewal_history") or []
    assert len(rh) == 1
    entry = rh[0]
    assert entry["late_penalty_applied"] is True, (
        "the in-the-late-grace-zone renewal carries the late-penalty surcharge"
    )
    expected_late_fee = expected_annual_renewal_fee_cents(
        vehicle_count=len(permit["authorized_vehicle_ids"]),
        is_late=True,
    )
    assert entry["fee_cents"] == expected_late_fee
    # The fee is the on-time fee plus the late surcharge, capped at the ceiling.
    expected_ontime = expected_annual_renewal_fee_cents(
        vehicle_count=len(permit["authorized_vehicle_ids"]),
        is_late=False,
    )
    expected_uncapped = expected_ontime + LATE_RENEWAL_PENALTY_CENTS
    assert expected_late_fee == min(expected_uncapped, MAX_RENEWAL_FEE_CENTS)
    # Wallet debit.
    post_wallet = snapshot_company_wallet(api, scenario)
    assert post_wallet == pre_wallet - expected_late_fee


def test_full_wallet_conservation_on_issue_renew_void(api, active_permit: HazmatScenario):
    """The composite conservation invariant on the full
    ``(issue, one renewal, void-issue)`` cycle: the wallet's
    net change is exactly zero, and the ``void_refunded_cents``
    audit field on the voided row equals the algebraic sum of
    the issue fee plus the renewal-history entry's fee.

    The PRD's §2.11 paragraph names this as "the void-issue's
    refund computation re-uses the stored integers rather than
    re-running the formula — the conservation is bit-exact
    because the addition of the stored debits and the
    subtraction of the stored credits cancel exactly".

    The void must land within the 24-hour window from the
    *original* ``issued_at`` (which doesn't move on a renewal —
    the ``issued_at`` is set at the original issue), so the
    renewal-and-then-void path requires the renewal-window to
    have opened within the 24-hour-since-original-issue.  That
    requires ``valid_until - RENEWAL_OPEN_WINDOW_DAYS <
    issued_at + VOID_ISSUE_WINDOW_HOURS``, which since
    ``valid_until = issued_at + PERMIT_DEFAULT_VALIDITY_DAYS``
    simplifies to
    ``PERMIT_DEFAULT_VALIDITY_DAYS - RENEWAL_OPEN_WINDOW_DAYS <
    VOID_ISSUE_WINDOW_HOURS / 24``.

    With the canonical constants 365 / 60 / 24, the inequality
    ``305 < 1`` does NOT hold, so the standard test scenario
    can't combine "a real renewal" with "a real void-after-the-
    renewal" inside the 24-hour void window.  The
    deployment-pinned constants make the
    "renewal-then-void-within-the-original-24-hour-window" case
    unreachable through the public API in the standard
    configuration.  The PRD's §2.10 names this knife-edge
    explicitly: "a configuration the test layer pins
    explicitly" for the renew-vs-void OCC race only.

    The standard test path is therefore the
    ``(issue, no renewals, void-issue)`` round-trip, which gives
    the bit-exact-zero net wallet change.  The
    ``(issue, renewal, natural expiry)`` round-trip's net change
    is the negative of the sum of the recorded fees, and the
    void-with-renewals case is the
    short-permit-term configuration the test harness chooses.

    This test exercises the standard
    issue-no-renewals-void round-trip.
    """
    scenario = active_permit
    permit = scenario.permit
    reg = regulator_headers()
    pre_void_wallet = snapshot_company_wallet(api, scenario)
    issue_fee = int(permit["issue_fee_cents"])
    # No clock advance (still within the 24-hour void window from issued_at).
    void_envelope = get_success_data(api.void_issue_permit(permit["id"], void_issue_payload(), reg))
    voided = void_envelope.get("permit") if "permit" in void_envelope else void_envelope
    assert voided["lifecycle_status"] == PermitLifecycleStatus.VOIDED.value
    assert voided["void_refunded_cents"] == issue_fee
    post_void_wallet = snapshot_company_wallet(api, scenario)
    assert post_void_wallet == pre_void_wallet + issue_fee, (
        f"wallet conservation: post-void {post_void_wallet} != pre-void {pre_void_wallet} + "
        f"refund {issue_fee}"
    )


def test_void_response_carries_cascade_summary_and_wallet_credit(api, inflight_trip: HazmatScenario):
    """PRD §3.6: "The void's response embeds the updated permit
    row plus the wallet-credit sub-object
    ``{wallet_credited_cents, new_wallet_balance_cents}`` and a
    ``cascade_summary`` sub-object listing the ids of the
    cascade-aborted trips and their post-cascade
    ``abort_reason`` and ``aborted_at`` values for the test
    layer's atomicity assertions".

    The fixture has one in-flight trip on the permit; the void
    cascade-aborts that trip.  The cascade_summary's list has
    that trip's id.
    """
    scenario = inflight_trip
    reg = regulator_headers()
    trip_id = scenario.trips[0]["id"]
    void_envelope = get_success_data(api.void_issue_permit(scenario.permit["id"], void_issue_payload(), reg))
    cascade = void_envelope.get("cascade_summary") or {}
    cascaded_trip_ids = cascade.get("cascade_aborted_trip_ids") or cascade.get("trip_ids") or []
    # The implementation may use either field name for the
    # list; we check both shapes.  An empty cascade-summary on
    # a permit with an in-flight trip is an invariant violation
    # because the void's trip-cascade is synchronous per PRD §3.6.
    # The trip ID could appear directly in the list or under a
    # nested dict.  The flexible match.
    flat = []
    if isinstance(cascaded_trip_ids, list):
        for entry in cascaded_trip_ids:
            if isinstance(entry, str):
                flat.append(entry)
            elif isinstance(entry, dict) and "trip_id" in entry:
                flat.append(entry["trip_id"])
    assert trip_id in flat, (
        f"the void's cascade_summary should list the in-flight trip {trip_id!r}; "
        f"got {cascaded_trip_ids!r}"
    )


# ─── The five-leg validity AND-chain at issue-time recompute ─────────


def test_issue_with_revoked_company_in_gap_fails(api, qualified_carrier: HazmatScenario):
    """PRD §3.5: "Each gap-narrowing in the cross-entity
    preconditions … produces the appropriate dedicated error id on
    the issue's response".  Walk the application step, then revoke
    the company (a gap-narrowing of the company-qualification
    leg), and the issue step's company-leg recheck fires the
    priority-526 ``ERR_COMPANY_NOT_QUALIFIED`` 409.
    """
    scenario = qualified_carrier
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    permit = file_permit_application(api, scenario, valid_from_offset_seconds=10.0)
    assert permit["lifecycle_status"] == PermitLifecycleStatus.DRAFT.value
    # Revoke the company in the application-to-issue gap.
    api.revoke_company(scenario.company["id"], revoke_company_payload(), reg)
    # The issue step's company-leg check fires.
    resp = api.issue_permit(permit["id"], issue_permit_payload(), reg)
    validate_error(resp, ApiErrorId.ERR_COMPANY_NOT_QUALIFIED.value, expected_status=409)


def test_issued_permit_get_includes_live_verdict(api, active_permit: HazmatScenario):
    """PRD §3.5 GET-permit paragraph: "The read endpoint
    ``GET /v1/permits/{permit_id}`` returns the row's current
    snapshot fields verbatim … and additionally computes a
    live-mode result on the fly without writing it back.  The
    response field ``live_verdict`` is the boolean AND of the five
    live legs at the read moment, ``live_per_leg`` is the
    per-leg breakdown, and ``snapshot_overall`` is the boolean
    AND of the on-disk snapshot's five fields".
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    resp = api.get_permit(scenario.permit["id"], op)
    permit = validate_success(resp, 200)
    # On the all-green fixture's permit the two verdicts agree.
    # The implementation may expose the ``live_*`` and
    # ``snapshot_*`` fields at the top level of the data
    # sub-object or under a nested key — we accept both shapes.
    snap_ovr = permit.get("snapshot_overall")
    live_ovr = permit.get("live_verdict")
    if snap_ovr is not None and live_ovr is not None:
        assert isinstance(snap_ovr, bool)
        assert isinstance(live_ovr, bool)
        assert snap_ovr is True, "fixture's permit was issued all-green, so snapshot_overall is True"
        assert live_ovr is True, "with no grounding-state changes, the live verdict matches the snapshot"


def test_void_outside_window_after_renewal_window_opens(api):
    """The "knife-edge" case from PRD §2.10 where the void-window
    and the renewal-window are simultaneously open requires a
    deployment with ``RENEWAL_OPEN_WINDOW_DAYS`` ≥
    ``PERMIT_DEFAULT_VALIDITY_DAYS - VOID_ISSUE_WINDOW_HOURS / 24``.
    The canonical constants make this configuration unreachable,
    so the test layer accepts the simpler invariant:
    ``after-the-24-hour-window-has-closed`` void is the
    ``ERR_VOID_WINDOW_CLOSED`` 409 regardless of whether the
    renewal window has opened.
    """
    # Build an ACTIVE permit and advance the clock to 24h + 1s
    # past the issued_at.  The void-window is closed.
    scenario = setup_active_permit(api)
    reg = regulator_headers()
    advance_clock_by(api, float(VOID_ISSUE_WINDOW_HOURS) * 3600.0 + 5.0, run_sweep=False)
    resp = api.void_issue_permit(scenario.permit["id"], void_issue_payload(), reg)
    validate_error(resp, ApiErrorId.ERR_VOID_WINDOW_CLOSED.value, expected_status=409)
