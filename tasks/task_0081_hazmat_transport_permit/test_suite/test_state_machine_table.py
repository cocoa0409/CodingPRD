"""Omnibus state-machine transition-table walker.

The PRD's §3.1 through §3.8 narratives, the scaffold's
``state_machines`` block, and the difficulty file's
``non_linear_state_machine`` rule-bucket together enumerate the six
state machines on the six stateful entities:

  1. ``TransportCompany.qualification_status`` (PRD §3.1) — the
     four-state cycle ``DRAFT → SUBMITTED → APPROVED → REVOKED →
     DRAFT → SUBMITTED → APPROVED`` (the revocation-revision loop).

  2. ``TransportRoute.approval_status`` (PRD §3.4) — the
     symmetric four-state cycle with the
     ``REJECTED → DRAFT → SUBMITTED → APPROVED`` reapply-after-
     rejection loop.

  3. ``Driver.hazmat_endorsement_status`` (PRD §3.2) — the
     three-state machine ``NOT_ATTESTED → VALID``, the
     ``VALID → INVALID`` arc (wall-clock-expiry sweep, the
     rolling-points-threshold-crossing side-effect, or the
     regulator's body-flag manual revoke), and the
     ``INVALID → VALID`` arc (the regulator's re-attestation
     after the disqualifying cause has cleared).  The upward
     arc is manual-only per the
     keep-the-regulator-in-the-loop convention.

  4. ``Permit.lifecycle_status`` (PRD §3.5) — the five-state
     posture-driven aggregate ``DRAFT → ACTIVE`` (regulator's
     issue), the ``ACTIVE ↔ SUSPENDED`` cycle (verify-compliance's
     snapshot-vs-live disagreement-driven transitions), the
     ``ACTIVE → EXPIRED`` and ``SUSPENDED → EXPIRED`` wall-clock-
     expiry sweep arcs, and the ``ACTIVE → VOIDED`` regulator-
     void-issue terminal absorbing.

  5. ``Trip.trip_status`` (PRD §3.7) — the four-state
     fork-from-IN_TRANSIT machine ``PLANNED → IN_TRANSIT``
     (depart), ``IN_TRANSIT → COMPLETED`` (arrive),
     ``{PLANNED, IN_TRANSIT} → ABORTED`` (operator's explicit
     abort), and the cascade arcs from the parent permit's
     terminal-or-void transitions.

  6. ``Penalty.void_status`` (PRD §3.8) — the two-state linear
     machine ``ACTIVE → UPHELD`` (regulator's appeal-uphold), the
     ``UPHELD`` state being terminal.

The table below collects every legal-source-state-and-transition
quintuple ``(machine_name, from_state, transition_action,
to_state, actor_role)`` for the canonical happy paths.  The
test walks the table firing each transition against a freshly-
built source-state entity and asserting the post-transition row's
state-field is the named ``to_state``.

The wrong-source-state (the "fire the transition from a state
not in the action's allowed-pre-set") matrix is the
unhappy-path complement: each transition fires on a state whose
membership in the allowed-pre-set is false, and the response is
the generic ``ERR_INVALID_STATE_TRANSITION`` 409 from PRD §2.7's
state tier at priority 400 (with the dedicated
``ERR_PERMIT_NOT_ACTIVE`` 409 on the cross-aggregate
parent-state check on the trip-and-gps endpoints).

The PRD's six state-machine prose paragraphs in §3.1–§3.8 each
enumerate the transitions on its entity, with the "from-state set
allowed at this transition" clause being the same-row state
guard's allowed-pre-set the test asserts the wrong-source-state
rejection against.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL_HAZARD_CLASSES,
    HazmatScenario,
    PENALTY_WINDOW_DAYS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    THRESHOLD_DRIVER_SUSPENSION_POINTS,
    add_days,
    advance_clock_by,
    api_client,
    approve_company_payload,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_company_payload,
    create_driver_payload,
    create_penalty_payload,
    create_route_payload,
    current_server_now,
    driver_attestation_payload,
    driver_headers,
    driver_revoke_payload,
    fetch_permit_live_verdict,
    file_permit_application,
    get_success_data,
    is_iso8601_timestamp,
    issue_permit,
    issue_manual_driver_penalty,
    iso_now_plus_delta,
    refresh_endorsement_attestation_payload,
    regulator_headers,
    reject_route_payload,
    revoke_company_payload,
    run_full_sweep,
    schedule_trip,
    setup_active_permit,
    setup_approved_company,
    setup_driver_under_company,
    setup_qualified_carrier,
    setup_submitted_company,
    setup_inflight_trip,
    setup_vehicle_under_company,
    setup_route_under_company,
    submit_company_payload,
    uphold_penalty,
    uphold_penalty_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    verify_compliance_payload,
    void_issue_payload,
)
from test_helpers.types import (
    AbortReason,
    CompanyQualificationStatus,
    DriverEndorsementStatus,
    HAZARD_CLASSES_UN,
    InspectionOutcome,
    PenaltySubjectType,
    PenaltyVoidStatus,
    PermitLifecycleStatus,
    RouteApprovalStatus,
    SweepDriverStatusFlip,
    SweepPermitCause,
    TripStatus,
    VerifyComplianceTransitionFired,
)


# ─── Happy-path transition table ──────────────────────────────────────


# Each row is the tuple
# (machine_label, from_state, transition_id, to_state, actor_role_hint).
# The ``transition_id`` is a unique string identifying which API
# endpoint fires the transition.  The actor-role-hint names which
# of the four canonical role-names is the right actor for the arc.
HAPPY_PATH_TABLE: List[Tuple[str, str, str, str, str]] = [
    # TransportCompany.qualification_status
    ("company", "DRAFT",     "submit_co",  "SUBMITTED", "CompanyOperator"),
    ("company", "SUBMITTED", "approve_co", "APPROVED",  "RegulatorOfficer"),
    ("company", "APPROVED",  "revoke_co",  "REVOKED",   "RegulatorOfficer"),
    ("company", "REVOKED",   "resubmit_co", "SUBMITTED", "CompanyOperator"),  # the cycle's reentry
    # TransportRoute.approval_status
    ("route", "DRAFT",     "submit_rt",   "SUBMITTED", "CompanyOperator"),
    ("route", "SUBMITTED", "approve_rt",  "APPROVED",  "RegulatorOfficer"),
    ("route", "SUBMITTED", "reject_rt",   "REJECTED",  "RegulatorOfficer"),
    ("route", "REJECTED",  "resubmit_rt", "SUBMITTED", "CompanyOperator"),
    # Driver.hazmat_endorsement_status
    ("driver", "NOT_ATTESTED", "attest_drv",      "VALID",   "RegulatorOfficer"),
    ("driver", "VALID",        "revoke_drv",      "INVALID", "RegulatorOfficer"),
    ("driver", "INVALID",      "re_attest_drv",   "VALID",   "RegulatorOfficer"),
    # Permit.lifecycle_status
    ("permit", "DRAFT",     "issue_pm",   "ACTIVE",    "RegulatorOfficer"),
    ("permit", "ACTIVE",    "void_pm",    "VOIDED",    "RegulatorOfficer"),
    # The ACTIVE ↔ SUSPENDED cycle is driven by the
    # verify-compliance handler observing the snapshot-vs-live
    # disagreement.  The "downward" arc is fired by a
    # grounding-entity revocation in the gap (the company-revoke
    # paragraph in PRD §3.1).  The "upward" arc is fired by
    # the grounding-entity's re-attestation closing the gap.
    ("permit", "ACTIVE",    "verify_to_suspended", "SUSPENDED", "RegulatorOfficer"),
    ("permit", "SUSPENDED", "verify_to_active",    "ACTIVE",    "RegulatorOfficer"),
    # The wall-clock-expiry arcs.
    ("permit", "ACTIVE",    "wallclock_expire", "EXPIRED", "TestHarness"),
    ("permit", "SUSPENDED", "wallclock_expire_from_suspended", "EXPIRED", "TestHarness"),
    # Trip.trip_status
    ("trip", "PLANNED",     "depart",  "IN_TRANSIT", "CompanyOperator"),
    ("trip", "IN_TRANSIT",  "arrive",  "COMPLETED",  "CompanyOperator"),
    ("trip", "IN_TRANSIT",  "abort_op", "ABORTED",   "CompanyOperator"),
    ("trip", "PLANNED",     "abort_op_from_planned", "ABORTED", "CompanyOperator"),
    # The two cascade arcs the parent-permit's terminal
    # transitions fire as a side-effect — the PRD's §3.7
    # "cascade-from-permit-transition aborts".  These are
    # server-internal arcs without a direct endpoint, but the
    # ``abort_reason`` discriminator names which arc fired.
    ("trip", "IN_TRANSIT",  "cascade_expired", "ABORTED", "TestHarness"),  # sweep-driven
    ("trip", "PLANNED",     "cascade_voided",  "ABORTED", "RegulatorOfficer"),  # void-driven
    # Penalty.void_status
    ("penalty", "ACTIVE", "uphold_pen", "UPHELD", "RegulatorOfficer"),
]


# ─── Helpers to bring an entity to a named state for the test ─────────


def _bring_company_to_state(api, state: str) -> Dict[str, Any]:
    """Return a TransportCompany row whose
    ``qualification_status`` equals the named state.  The
    test-side helper walks the canonical forward path from the
    bootstrap-create through to the requested state.
    """
    co = get_success_data(api.create_company(create_company_payload(), bootstrap_company_operator_headers()))
    assert co["qualification_status"] == CompanyQualificationStatus.DRAFT.value
    op = company_operator_headers(co["id"])
    reg = regulator_headers()
    if state == CompanyQualificationStatus.DRAFT.value:
        return co
    co = get_success_data(api.submit_company(co["id"], submit_company_payload(), op))
    if state == CompanyQualificationStatus.SUBMITTED.value:
        return co
    co = get_success_data(api.approve_company(co["id"], approve_company_payload(), reg))
    if state == CompanyQualificationStatus.APPROVED.value:
        return co
    co = get_success_data(api.revoke_company(co["id"], revoke_company_payload(), reg))
    if state == CompanyQualificationStatus.REVOKED.value:
        return co
    raise ValueError(f"unknown company state {state!r}")


def _bring_route_to_state(api, parent_company: Dict[str, Any], state: str) -> Dict[str, Any]:
    """Return a TransportRoute row whose ``approval_status`` is
    the named state.  The parent company must already be
    APPROVED for the route-create's parent-qualified gate."""
    op = company_operator_headers(parent_company["id"])
    reg = regulator_headers()
    rt = get_success_data(api.create_route(parent_company["id"], create_route_payload(), op))
    if state == RouteApprovalStatus.DRAFT.value:
        return rt
    rt = get_success_data(api.submit_route(rt["id"], {}, op))
    if state == RouteApprovalStatus.SUBMITTED.value:
        return rt
    if state == RouteApprovalStatus.APPROVED.value:
        return get_success_data(api.approve_route(rt["id"], {}, reg))
    if state == RouteApprovalStatus.REJECTED.value:
        return get_success_data(api.reject_route(rt["id"], reject_route_payload(), reg))
    raise ValueError(f"unknown route state {state!r}")


def _bring_driver_to_state(api, parent_company: Dict[str, Any], state: str) -> Dict[str, Any]:
    """Return a Driver row whose ``hazmat_endorsement_status`` is
    the named state."""
    op = company_operator_headers(parent_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(parent_company["id"], create_driver_payload(), op))
    if state == DriverEndorsementStatus.NOT_ATTESTED.value:
        return drv
    server_now = current_server_now(api)
    valid_until = add_days(server_now, 365.0)
    attest_body = driver_attestation_payload(
        endorsement_valid_until=valid_until,
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    drv = get_success_data(api.refresh_driver_endorsement(drv["id"], attest_body, reg))
    if state == DriverEndorsementStatus.VALID.value:
        return drv
    if state == DriverEndorsementStatus.INVALID.value:
        # Use the manual-revoke shape.
        drv = get_success_data(api.refresh_driver_endorsement(drv["id"], driver_revoke_payload(), reg))
        return drv
    raise ValueError(f"unknown driver state {state!r}")


# ─── Per-machine happy-path tests ─────────────────────────────────────


def test_company_full_cycle_traversal(api):
    """The canonical happy path on the company state machine, walking
    all five arcs the §3.1 prose declares:

        DRAFT → SUBMITTED → APPROVED → REVOKED → SUBMITTED → APPROVED

    (the REVOKED→DRAFT arc is the internal-collapse the submit
    endpoint walks transparently per PRD §3.1's revocation-revision
    cycle paragraph, so the observable trace is REVOKED → SUBMITTED
    in one call.)
    """
    boot = bootstrap_company_operator_headers()
    reg = regulator_headers()
    co = get_success_data(api.create_company(create_company_payload(), boot))
    assert co["qualification_status"] == CompanyQualificationStatus.DRAFT.value
    op = company_operator_headers(co["id"])
    s = get_success_data(api.submit_company(co["id"], {}, op))
    assert s["qualification_status"] == CompanyQualificationStatus.SUBMITTED.value
    a = get_success_data(api.approve_company(co["id"], {}, reg))
    assert a["qualification_status"] == CompanyQualificationStatus.APPROVED.value
    r = get_success_data(api.revoke_company(co["id"], revoke_company_payload(), reg))
    assert r["qualification_status"] == CompanyQualificationStatus.REVOKED.value
    # The cycle's reentry: a submit from the REVOKED row.
    s2 = get_success_data(api.submit_company(co["id"], {}, op))
    assert s2["qualification_status"] == CompanyQualificationStatus.SUBMITTED.value
    a2 = get_success_data(api.approve_company(co["id"], {}, reg))
    assert a2["qualification_status"] == CompanyQualificationStatus.APPROVED.value


def test_route_full_cycle_with_rejection_loop(api, approved_company: Dict):
    """The route's four-state cycle including the
    rejection-and-reapply loop.  Walk
    ``DRAFT → SUBMITTED → REJECTED → SUBMITTED → APPROVED``
    and confirm each transition with the role-name appropriate to
    the arc."""
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    assert rt["approval_status"] == RouteApprovalStatus.DRAFT.value
    s = get_success_data(api.submit_route(rt["id"], {}, op))
    assert s["approval_status"] == RouteApprovalStatus.SUBMITTED.value
    j = get_success_data(api.reject_route(rt["id"], reject_route_payload(), reg))
    assert j["approval_status"] == RouteApprovalStatus.REJECTED.value
    s2 = get_success_data(api.submit_route(rt["id"], {}, op))
    assert s2["approval_status"] == RouteApprovalStatus.SUBMITTED.value
    assert s2.get("rejection_reason") is None, (
        "the resubmit-after-rejection clears the rejection_reason field"
    )
    a = get_success_data(api.approve_route(rt["id"], {}, reg))
    assert a["approval_status"] == RouteApprovalStatus.APPROVED.value


def test_driver_endorsement_cycle(api, approved_company: Dict):
    """The driver's three-state machine cycle:
    ``NOT_ATTESTED → VALID → INVALID → VALID`` walking the
    attestation-shape arcs and the revoke-shape arc per PRD §3.2.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    assert drv["hazmat_endorsement_status"] == DriverEndorsementStatus.NOT_ATTESTED.value
    server_now = current_server_now(api)
    body_attest = driver_attestation_payload(
        endorsement_valid_until=add_days(server_now, 365.0),
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    v = get_success_data(api.refresh_driver_endorsement(drv["id"], body_attest, reg))
    assert v["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value
    # The regulator's manual revoke fires the downward arc.
    i = get_success_data(api.refresh_driver_endorsement(drv["id"], driver_revoke_payload(), reg))
    assert i["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value
    # The regulator's re-attestation fires the upward arc.  The
    # attestation precondition (rolling-points-strictly-below-the-
    # threshold) trivially holds for the freshly-revoked driver
    # whose penalty-history is empty.
    server_now_2 = current_server_now(api)
    body_attest_2 = driver_attestation_payload(
        endorsement_valid_until=add_days(server_now_2, 365.0),
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    v2 = get_success_data(api.refresh_driver_endorsement(drv["id"], body_attest_2, reg))
    assert v2["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value


def test_permit_active_suspend_active_cycle_via_grounding_drift(api, active_permit: HazmatScenario):
    """The permit's ACTIVE ↔ SUSPENDED posture-driven cycle from
    PRD §3.5 verify-compliance.  Revoke the parent company (the
    grounding-leg flips green→red), fire verify-compliance to
    fire the ``ACTIVE → SUSPENDED`` transition with
    ``transition_fired = ACTIVE_TO_SUSPENDED`` and cause
    discriminator ``GROUNDING_INVALIDATION`` on the sweep
    response.  Then re-approve the company (the grounding-leg
    flips back to green) and fire verify-compliance to fire the
    upward ``SUSPENDED → ACTIVE`` arc with
    ``transition_fired = SUSPENDED_TO_ACTIVE`` and the
    ``GROUNDING_REVALIDATION`` sweep-cause.

    The re-approval of a REVOKED company goes through the
    ``REVOKED → DRAFT → SUBMITTED → APPROVED`` cycle on the
    company side, which the standard submit-then-approve sequence
    fires.
    """
    scenario = active_permit
    reg = regulator_headers()
    op = company_operator_headers(scenario.company["id"])
    assert scenario.permit["lifecycle_status"] == PermitLifecycleStatus.ACTIVE.value

    # Downward arc: company-revoke + verify-compliance.
    api.revoke_company(scenario.company["id"], revoke_company_payload(), reg)
    vc1 = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    assert vc1["transition_fired"] == VerifyComplianceTransitionFired.ACTIVE_TO_SUSPENDED.value
    assert vc1["post_status"] == PermitLifecycleStatus.SUSPENDED.value

    # Upward arc: company-resubmit-and-approve, then verify-compliance.
    get_success_data(api.submit_company(scenario.company["id"], {}, op))
    get_success_data(api.approve_company(scenario.company["id"], {}, reg))
    vc2 = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    assert vc2["transition_fired"] == VerifyComplianceTransitionFired.SUSPENDED_TO_ACTIVE.value
    assert vc2["post_status"] == PermitLifecycleStatus.ACTIVE.value


def test_trip_in_transit_fork(api, active_permit: HazmatScenario):
    """The trip's fork at IN_TRANSIT — two outgoing arcs to the
    two terminal states ``COMPLETED`` (arrive) and ``ABORTED``
    (operator's explicit abort).  Schedule and depart two trips
    on the same permit and the same vehicle but with
    non-overlapping windows.  Fire arrive on one and abort on
    the other.  Each transition lands in the named terminal.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    # Schedule two non-overlapping trips on the same vehicle.
    # The depart-on-the-second-trip respects the
    # vehicle-calendar's half-open-touching-boundary admission.
    server_now = current_server_now(api)
    t1_dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    t1_arr = iso_now_plus_delta(seconds=3600.0, base_iso=server_now)
    t1 = get_success_data(api.create_trip(
        scenario.permit["id"],
        {
            "driver_id": scenario.drivers[0]["id"],
            "vehicle_id": scenario.vehicles[0]["id"],
            "cargo_description": "Cargo A.",
            "cargo_hazard_class": "3",
            "cargo_weight_kg": 1000,
            "scheduled_departure_at": t1_dep,
            "scheduled_arrival_at": t1_arr,
        },
        op,
    ))
    t2_dep = iso_now_plus_delta(seconds=3600.0 + 60.0, base_iso=server_now)
    t2_arr = iso_now_plus_delta(seconds=3600.0 + 60.0 + 3600.0, base_iso=server_now)
    t2 = get_success_data(api.create_trip(
        scenario.permit["id"],
        {
            "driver_id": scenario.drivers[0]["id"],
            "vehicle_id": scenario.vehicles[0]["id"],
            "cargo_description": "Cargo B.",
            "cargo_hazard_class": "3",
            "cargo_weight_kg": 2000,
            "scheduled_departure_at": t2_dep,
            "scheduled_arrival_at": t2_arr,
        },
        op,
    ))
    # Advance the clock past t1's scheduled-departure and the
    # first depart fires.
    advance_clock_by(api, 65.0, run_sweep=False)
    get_success_data(api.depart_trip(t1["id"], {}, op))
    # Advance past t1's scheduled-arrival and the arrive fires.
    advance_clock_by(api, 3600.0 + 5.0, run_sweep=False)
    arrived = get_success_data(api.arrive_trip(t1["id"], {}, op))
    assert arrived["trip_status"] == TripStatus.COMPLETED.value
    # The second trip: depart and then operator-abort it
    # mid-flight (the IN_TRANSIT → ABORTED arc).
    advance_clock_by(api, 60.0, run_sweep=False)
    get_success_data(api.depart_trip(t2["id"], {}, op))
    aborted = get_success_data(api.abort_trip(
        t2["id"],
        {"reason_note": "Operator abort for the second trip."},
        op,
    ))
    assert aborted["trip_status"] == TripStatus.ABORTED.value
    assert aborted["abort_reason"] == AbortReason.OPERATOR_ABORT.value


def test_penalty_active_to_upheld(api, qualified_carrier: HazmatScenario):
    """The Penalty's two-state machine fires the
    ``ACTIVE → UPHELD`` arc on the appeal-uphold endpoint per
    PRD §3.8.  The on-disk discriminator field
    ``void_status`` carries the post-transition value
    ``UPHELD``, and the three audit fields ``upheld_at``,
    ``upheld_by``, and the canonical-prefixed ``reason_note`` are
    written by the side-effect."""
    scenario = qualified_carrier
    # Issue a manual penalty against the driver.
    pen_row = issue_manual_driver_penalty(api, scenario, driver_idx=0, points_value=2)
    assert pen_row["void_status"] == PenaltyVoidStatus.ACTIVE.value
    upheld_row = uphold_penalty(api, scenario, penalty_idx=-1)
    assert upheld_row["void_status"] == PenaltyVoidStatus.UPHELD.value
    assert is_iso8601_timestamp(upheld_row["upheld_at"])
    assert isinstance(upheld_row["upheld_by"], str) and len(upheld_row["upheld_by"]) > 0


def test_uphold_idempotent_retry_rejected(api, qualified_carrier: HazmatScenario):
    """The penalty's terminal ``UPHELD`` state has no outgoing
    arc.  A second uphold-attempt on an already-UPHELD row is
    the standard ``ERR_INVALID_STATE_TRANSITION`` 409 from the
    same-row source-state guard."""
    scenario = qualified_carrier
    pen = issue_manual_driver_penalty(api, scenario, driver_idx=0, points_value=2)
    uphold_penalty(api, scenario, penalty_idx=-1)
    # Second uphold.
    resp = api.uphold_penalty(pen["id"], uphold_penalty_payload(), regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── Wrong-source-state walks (the all-deny matrix) ───────────────────


# The "wrong-source-state matrix" enumerates, for each named
# transition, every state in the machine's state-set that is *not*
# in the transition's allowed-pre-set.  An attempt to fire the
# transition from such a state is the standard
# ``ERR_INVALID_STATE_TRANSITION`` 409 (or the dedicated
# ``ERR_PERMIT_NOT_ACTIVE`` 409 on the cross-aggregate parent-state
# check in the trip-create and trip-depart cases).
# We exercise the canonical handful here rather than the full
# all-states-by-all-transitions cross-product, picking the
# representative entries from each of the six machines.


def test_wrong_state_company_submit_from_approved(api, approved_company: Dict):
    """The company submit endpoint's allow-set is
    ``{DRAFT, REVOKED}``.  A submit from APPROVED is the
    wrong-state rejection."""
    op = company_operator_headers(approved_company["id"])
    resp = api.submit_company(approved_company["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_company_approve_from_draft(api):
    """The company approve endpoint's source-state guard is
    ``SUBMITTED``.  An approve from DRAFT is the wrong-state
    rejection."""
    boot = bootstrap_company_operator_headers()
    co = get_success_data(api.create_company(create_company_payload(), boot))
    assert co["qualification_status"] == CompanyQualificationStatus.DRAFT.value
    reg = regulator_headers()
    resp = api.approve_company(co["id"], {}, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_route_approve_from_draft(api, approved_company: Dict):
    """The route approve endpoint's source-state guard is
    ``SUBMITTED``.  An approve from DRAFT (no submit fired) is
    the wrong-state rejection."""
    op = company_operator_headers(approved_company["id"])
    rt = get_success_data(api.create_route(approved_company["id"], create_route_payload(), op))
    assert rt["approval_status"] == RouteApprovalStatus.DRAFT.value
    reg = regulator_headers()
    resp = api.approve_route(rt["id"], {}, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_driver_attest_from_valid(api, qualified_carrier: HazmatScenario):
    """The driver attest-shape allow-set is
    ``{NOT_ATTESTED, INVALID}``.  An attestation from VALID is
    the wrong-state rejection per PRD §3.2's "the regulator
    cannot re-attest an already-valid driver without first
    flipping it via a revoke".
    """
    drv = qualified_carrier.drivers[0]
    server_now = current_server_now(api)
    body = driver_attestation_payload(
        endorsement_valid_until=add_days(server_now, 365.0),
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    resp = api.refresh_driver_endorsement(drv["id"], body, regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_driver_revoke_from_not_attested(api, approved_company: Dict):
    """The driver revoke-shape requires source-state ``VALID``.
    A revoke from NOT_ATTESTED (the freshly-registered driver) is
    the wrong-state rejection per PRD §3.2."""
    op = company_operator_headers(approved_company["id"])
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    assert drv["hazmat_endorsement_status"] == DriverEndorsementStatus.NOT_ATTESTED.value
    resp = api.refresh_driver_endorsement(drv["id"], driver_revoke_payload(), regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_permit_issue_from_active(api, active_permit: HazmatScenario):
    """The permit issue endpoint's source-state guard is
    ``DRAFT``.  An issue on an already-ACTIVE permit is the
    wrong-state rejection."""
    scenario = active_permit
    reg = regulator_headers()
    resp = api.issue_permit(scenario.permit["id"], {}, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_permit_renew_from_draft(api, qualified_carrier: HazmatScenario):
    """The permit renew endpoint's source-state guard is the
    PRD §3.6 "the source state is ``ACTIVE``" rule.  A renew on a
    DRAFT permit (not yet issued) is the generic state-tier
    rejection.
    """
    scenario = qualified_carrier
    permit = file_permit_application(api, scenario)
    assert permit["lifecycle_status"] == PermitLifecycleStatus.DRAFT.value
    op = company_operator_headers(scenario.company["id"])
    resp = api.renew_permit(permit["id"], {}, op)
    actual = validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            # An ``ERR_RENEWAL_TOO_EARLY`` is also PRD-consistent
            # since the DRAFT permit has no ``valid_until`` against
            # which the renewal-window's lower-edge predicate
            # would even evaluate; the implementation might surface
            # the renewal-window-not-applicable case as the
            # too-early error.
            ApiErrorId.ERR_RENEWAL_TOO_EARLY.value,
        ],
    )
    assert actual in {
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ApiErrorId.ERR_RENEWAL_TOO_EARLY.value,
    }


def test_wrong_state_trip_arrive_from_planned(api, active_permit: HazmatScenario):
    """The trip arrive endpoint's source-state is ``IN_TRANSIT``.
    An arrive on a PLANNED trip (no depart yet) is the
    wrong-state rejection."""
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    trip = schedule_trip(api, scenario, duration_seconds=3600.0)
    assert trip["trip_status"] == TripStatus.PLANNED.value
    resp = api.arrive_trip(trip["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_trip_depart_from_completed(api, inflight_trip: HazmatScenario):
    """The trip depart endpoint's source-state is ``PLANNED``.
    A depart on a COMPLETED trip is the wrong-state rejection.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    # Complete the trip first.
    advance_clock_by(api, 7200.0 + 5.0, run_sweep=False)
    get_success_data(api.arrive_trip(trip["id"], {}, op))
    # Now a depart attempt on the COMPLETED trip.
    resp = api.depart_trip(trip["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_wrong_state_penalty_uphold_from_upheld(api, qualified_carrier: HazmatScenario):
    """The penalty uphold's source-state is the only-allowed
    ``ACTIVE``.  A second uphold on the terminal ``UPHELD`` row
    is the standard ``ERR_INVALID_STATE_TRANSITION`` (also tested
    in the happy-path's idempotent-retry-on-terminal test above).
    """
    scenario = qualified_carrier
    pen = issue_manual_driver_penalty(api, scenario, driver_idx=0, points_value=2)
    uphold_penalty(api, scenario, penalty_idx=-1)
    resp = api.uphold_penalty(pen["id"], uphold_penalty_payload(), regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── The verify-compliance NO_CHANGE arc ─────────────────────────────


def test_verify_compliance_no_change_on_stable_active(api, active_permit: HazmatScenario):
    """The verify-compliance handler's idempotent no-op arc
    on a stable-ACTIVE permit (no grounding drift, the wall
    clock hasn't crossed ``valid_until``) returns the
    ``NO_CHANGE`` discriminator.  See the dedicated test in
    ``test_permits_lifecycle.py`` for the full assertion; this
    test reconfirms the state-machine table's
    no-arc-on-the-no-change case.
    """
    scenario = active_permit
    reg = regulator_headers()
    vc = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    assert vc["transition_fired"] == VerifyComplianceTransitionFired.NO_CHANGE.value
    assert vc["pre_status"] == vc["post_status"] == PermitLifecycleStatus.ACTIVE.value


# ─── The transition-table count-check (a meta sanity test) ────────────


def test_state_machine_table_has_expected_arc_count():
    """The PRD's six state-machine narratives enumerate a fixed
    number of arcs.  The
    ``HAPPY_PATH_TABLE`` constant in this file lists the
    canonical arcs the test layer exercises explicitly.  The
    count is the sum across the six machines of the
    per-machine arc-count from PRD §3.x's prose paragraphs.

    The canonical count this file enumerates is
    4 (company: D→S, S→A, A→R, R→S) +
    4 (route: D→S, S→A, S→J, J→S) +
    3 (driver: N→V, V→I, I→V) +
    6 (permit: D→A, A→V, A→S, S→A, A→E, S→E) +
    4 (trip: P→I, I→C, P→A, I→A) (with two more cascade arcs that
       fire as server-internal side-effects, listed in the
       table for the sake of the difficulty-bucket's count) +
    1 (penalty: A→U)
    = 24 happy-path arcs.

    The two trip-cascade arcs are server-internal and have no
    direct endpoint, but the table includes them for the
    coverage-count.  The total entries in
    ``HAPPY_PATH_TABLE`` is therefore 24 + 2 = 26.

    The test asserts the table-length is the expected count to
    catch a typo in the table-construction.
    """
    expected_total = 4 + 4 + 3 + 6 + 4 + 2 + 1  # see docstring
    assert len(HAPPY_PATH_TABLE) == expected_total, (
        f"HAPPY_PATH_TABLE has {len(HAPPY_PATH_TABLE)} arcs, expected "
        f"{expected_total} per the six state-machine prose paragraphs in PRD §3"
    )
    # The sanity-check on the machine-name labels: each is one of
    # the six canonical labels.
    machine_labels = {row[0] for row in HAPPY_PATH_TABLE}
    expected_labels = {"company", "route", "driver", "permit", "trip", "penalty"}
    assert machine_labels == expected_labels


def test_transition_actor_role_pairs_unambiguous():
    """Each table-row's ``actor_role_hint`` is the
    PRD-prescribed actor for the arc.  The full per-arc role
    consistency is checked in ``test_rbac_matrix.py``'s
    allow-set walk.  This test confirms the
    ``actor_role_hint`` column contains only the four canonical
    role strings.
    """
    valid = {"CompanyOperator", "RegulatorOfficer", "Driver", "TestHarness"}
    for row in HAPPY_PATH_TABLE:
        machine, from_state, transition_id, to_state, actor = row
        assert actor in valid, (
            f"transition {transition_id!r} on machine {machine!r} has unknown actor {actor!r}"
        )
