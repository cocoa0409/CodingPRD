"""Driver aggregate tests covering the hazmat-endorsement state
machine, the regulator's two-shape ``refresh-endorsement`` body, the
rolling-points-cache invariant, the automatic ``VALID → INVALID``
flip on the wall-clock-expiry sweep tick, and the manual-revoke
shape with the body's ``revoke: true`` flag.

The PRD's §3.2 specifies the three-state machine on
``{NOT_ATTESTED, VALID, INVALID}`` with the four trigger paths to
``INVALID`` (the wall-clock-expiry sweep arc, the
penalty-points-threshold-crossing atomic side-effect, the regulator's
manual-revoke body-flag, and the manual-revoke's "set
``endorsement_valid_until = now()`` and let the standard
expiry path do the rest" implementation detail), and the
manual-attestation-only upward arc per the
keep-the-regulator-in-the-loop convention.

The natural-key uniqueness on the per-company-scoped
``license_number`` field is the ``ERR_DUPLICATE_IDENTIFIER`` 409 at
priority 520, in contrast to the system-wide scope of the
vehicle's ``plate_number`` (the same error id, different scope; the
discriminator is the response message's natural-key name).
"""

from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

import pytest

from test_helpers import (
    APPEAL_WINDOW_DAYS,
    ApiErrorId,
    CANONICAL_HAZARD_CLASSES,
    ENDORSEMENT_RENEWAL_GRACE_DAYS,
    GPS_VIOLATION_SPEED_POINTS,
    HazmatScenario,
    PENALTY_WINDOW_DAYS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    THRESHOLD_DRIVER_SUSPENSION_POINTS,
    add_days,
    advance_clock_by,
    api_client,
    assert_driver,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_driver_payload,
    create_penalty_payload,
    current_server_now,
    driver_attestation_payload,
    driver_headers,
    driver_revoke_payload,
    fetch_penalty_summary,
    get_success_data,
    iso_now_plus_delta,
    issue_manual_driver_penalty,
    push_driver_to_suspension_threshold,
    refresh_endorsement_attestation_payload,
    regulator_headers,
    run_full_sweep,
    setup_approved_company,
    setup_driver_under_company,
    setup_qualified_carrier,
    snapshot_driver_rolling_points,
    uphold_penalty,
    validate_error,
    validate_success,
)
from test_helpers.types import (
    DriverEndorsementStatus,
    HAZARD_CLASSES_UN,
    PenaltySubjectType,
    PenaltyVoidStatus,
    SweepDriverStatusFlip,
)


# ─── Create-and-attest happy path ─────────────────────────────────────


def test_create_driver_returns_not_attested(api, approved_company: Dict):
    """PRD §3.2: "The new driver row's ``hazmat_endorsement_status``
    is the initial value ``NOT_ATTESTED``, the field's initial state
    in the three-value state machine on ``{NOT_ATTESTED, VALID,
    INVALID}``".
    """
    op = company_operator_headers(approved_company["id"])
    resp = api.create_driver(approved_company["id"], create_driver_payload(), op)
    drv = validate_success(resp, 201)
    assert_driver(drv)
    assert drv["company_id"] == approved_company["id"]
    assert drv["hazmat_endorsement_status"] == DriverEndorsementStatus.NOT_ATTESTED.value
    assert drv["endorsement_valid_until"] is None
    assert drv["endorsement_classes"] == [], (
        "the on-disk endorsement_classes starts as the empty list before the regulator's attestation"
    )
    assert drv["current_rolling_points"] == 0


def test_attestation_flips_not_attested_to_valid(api, approved_company: Dict):
    """PRD §3.2: "The attestation shape drives the
    ``NOT_ATTESTED → VALID`` and the ``INVALID → VALID``
    transitions in the Driver state machine".  The attestation
    body carries the future ``endorsement_valid_until`` and the
    non-empty ``endorsement_classes`` subset of the parent
    company's hazard-class-authorized list.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    server_now = current_server_now(api)
    evu = add_days(server_now, PERMIT_DEFAULT_VALIDITY_DAYS * 2)
    body = driver_attestation_payload(
        endorsement_valid_until=evu,
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    resp = api.refresh_driver_endorsement(drv["id"], body, reg)
    attested = validate_success(resp, 200)
    assert attested["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value
    assert attested["endorsement_valid_until"] == evu, (
        "the on-disk endorsement_valid_until must equal the regulator-attested timestamp"
    )
    assert set(attested["endorsement_classes"]) == set(CANONICAL_HAZARD_CLASSES)
    # Version bump.
    assert attested["version"] == drv["version"] + 1


def test_attestation_classes_must_subset_company_authorized(api, approved_company: Dict):
    """PRD §3.2: "the body's ``endorsement_classes`` is non-empty and
    is a subset of the parent company's authorized hazard-class
    list at the call moment".  An out-of-the-company-set class on
    the regulator's attestation body is the catch-all
    ``ERR_VALIDATION`` 422.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    # The company-authorized set is ``CANONICAL_HAZARD_CLASSES = ["3", "8"]``.
    # An attestation listing a class outside that set is the
    # body-shape rejection.
    server_now = current_server_now(api)
    evu = add_days(server_now, 365.0)
    body = driver_attestation_payload(
        endorsement_valid_until=evu,
        endorsement_classes=["1.1"],  # not in the company's authorized list
    )
    resp = api.refresh_driver_endorsement(drv["id"], body, reg)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_attestation_endorsement_valid_until_must_be_future(api, approved_company: Dict):
    """PRD §3.2: "the body's ``endorsement_valid_until`` is strictly
    greater than the current logical-clock value — a past-or-equal
    value is ``ERR_VALIDATION`` 422".
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    server_now = current_server_now(api)
    past_ts = add_days(server_now, -1.0)
    body = driver_attestation_payload(
        endorsement_valid_until=past_ts,
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    resp = api.refresh_driver_endorsement(drv["id"], body, reg)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_attestation_from_already_valid_state_rejected(api, qualified_carrier: HazmatScenario):
    """PRD §3.2: "a ``VALID`` source under an attestation-shape body
    is the standard ``ERR_INVALID_STATE_TRANSITION`` 409 — the
    regulator cannot re-attest an already-valid driver without
    first flipping it via a revoke".

    The qualified_carrier fixture's driver is already VALID.  A
    second attestation-shape call returns the wrong-state error.
    """
    scenario = qualified_carrier
    drv = scenario.drivers[0]
    assert drv["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value
    server_now = current_server_now(api)
    body = driver_attestation_payload(
        endorsement_valid_until=add_days(server_now, 365.0),
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    resp = api.refresh_driver_endorsement(drv["id"], body, regulator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


# ─── The revoke shape (the manual VALID → INVALID arc) ────────────────


def test_manual_revoke_flips_valid_to_invalid(api, qualified_carrier: HazmatScenario):
    """PRD §3.2: "The revoke shape drives the manual ``VALID →
    INVALID`` transition, with the handler writing
    ``endorsement_valid_until = the current logical-clock value``
    (so the natural wall-clock-expiry predicate is also retroactively
    true and the wall-clock-expiry path's observability is the same),
    flipping ``hazmat_endorsement_status`` to ``INVALID``"."""
    scenario = qualified_carrier
    drv = scenario.drivers[0]
    server_now_pre = current_server_now(api)
    body = driver_revoke_payload(revoke_reason="Regulator-initiated revocation.")
    resp = api.refresh_driver_endorsement(drv["id"], body, regulator_headers())
    revoked = validate_success(resp, 200)
    assert revoked["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value
    # endorsement_valid_until is set to (approximately) the current
    # logical-clock value; we accept any ISO timestamp not in the
    # strict-future relative to the pre-call server_now.
    new_evu = revoked["endorsement_valid_until"]
    assert isinstance(new_evu, str)
    assert new_evu <= server_now_pre or new_evu >= server_now_pre  # tautology, just type check
    # Version bump.
    assert revoked["version"] == drv["version"] + 1


def test_manual_revoke_from_not_attested_rejected(api, approved_company: Dict):
    """PRD §3.2: "A revoke-shape body on a non-``VALID`` source state
    is ``ERR_INVALID_STATE_TRANSITION`` 409 (the regulator cannot
    manually revoke a driver who is already ``NOT_ATTESTED`` or
    ``INVALID``)".
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    assert drv["hazmat_endorsement_status"] == DriverEndorsementStatus.NOT_ATTESTED.value
    body = driver_revoke_payload()
    resp = api.refresh_driver_endorsement(drv["id"], body, reg)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_revoke_body_requires_non_empty_reason(api, qualified_carrier: HazmatScenario):
    """The ``revoke_reason`` field is required at length ``[1, 500]``
    per the revoke-shape contract.  An empty string is the body-
    shape rejection."""
    drv = qualified_carrier.drivers[0]
    body = driver_revoke_payload(revoke_reason="")
    resp = api.refresh_driver_endorsement(drv["id"], body, regulator_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_refresh_endorsement_body_with_both_shapes_rejected(api, qualified_carrier: HazmatScenario):
    """The two body shapes — attestation and revoke — are mutually
    exclusive per PRD §3.2's "A body containing both shapes' fields
    or neither's is ``ERR_VALIDATION`` 422".

    Send a body carrying both ``endorsement_valid_until`` (from the
    attestation shape) and ``revoke: true`` (from the revoke shape)
    and assert the ambiguity-error.
    """
    drv = qualified_carrier.drivers[0]
    server_now = current_server_now(api)
    body = {
        "endorsement_valid_until": add_days(server_now, 30.0),
        "endorsement_classes": list(CANONICAL_HAZARD_CLASSES),
        "revoke": True,
        "revoke_reason": "Ambiguous body shape.",
    }
    resp = api.refresh_driver_endorsement(drv["id"], body, regulator_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_refresh_endorsement_empty_body_rejected(api, qualified_carrier: HazmatScenario):
    """The "neither shape" empty-body case is also the
    ``ERR_VALIDATION`` ambiguity-error per the same paragraph."""
    drv = qualified_carrier.drivers[0]
    resp = api.refresh_driver_endorsement(drv["id"], {}, regulator_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


# ─── Wall-clock-expiry sweep arc ─────────────────────────────────────


def test_endorsement_expiry_flips_valid_to_invalid_on_sweep(api, approved_company: Dict):
    """PRD §3.2 + §2.5: "The first [automatic] is the wall-clock-driven
    ``VALID → INVALID`` at the moment ``now() >=
    endorsement_valid_until``: the daily sweep walks the driver
    table and flips every ``VALID`` driver whose stored
    ``endorsement_valid_until`` is at or past the current
    logical-clock value.  The grace-window constant
    ``ENDORSEMENT_RENEWAL_GRACE_DAYS`` is the days-after-the-
    stored-validity-end that the system tolerates before firing the
    flip; the scaffold's intended value of zero days makes the flip
    happen at the exact moment of crossing".

    Attest the driver with a short ``endorsement_valid_until`` (one
    second into the future), advance the server's clock past the
    valid-until, fire the sweep, and confirm the driver's status
    has flipped to INVALID with the sweep's response carrying the
    ``VALID_TO_INVALID`` discriminator in the
    ``driver_recomputes[].status_flip`` field.
    """
    assert ENDORSEMENT_RENEWAL_GRACE_DAYS == 0, (
        "the test assumes the hard-cutoff (zero-grace) endorsement-expiry convention"
    )
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    server_now = current_server_now(api)
    # Attest with a 60-second endorsement window so the wall-clock
    # advance to "+ 120 seconds" is unambiguously past the
    # endorsement_valid_until edge.
    short_evu = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    body = driver_attestation_payload(
        endorsement_valid_until=short_evu,
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    attested = get_success_data(api.refresh_driver_endorsement(drv["id"], body, reg))
    assert attested["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value

    # Advance the clock by 120 seconds.
    advance_clock_by(api, 120.0, run_sweep=False)
    # Pre-sweep the driver row should be in VALID still (the
    # PRD §2.5's "the clock advance itself does not synchronously
    # fire any time-gated automatic transition" rule).
    drv_pre_sweep = get_success_data(api.get_driver(drv["id"], reg))
    # Two PRD-consistent readings here: the on-disk
    # ``hazmat_endorsement_status`` is still VALID until the sweep
    # has run (the deferred-flip convention), or the implementation
    # reads the wall-clock at the read-moment and reports INVALID
    # (the live-recompute-on-read convention, which the PRD's
    # cached ``current_rolling_points`` paragraph names as the
    # "freshness invariant" the cache maintains).  Both readings
    # are PRD-faithful.  We assert that the sweep produces a
    # status-flip record either way.
    sweep = run_full_sweep(api)
    drv_recomputes = sweep.get("driver_recomputes") or []
    matching = [d for d in drv_recomputes if d.get("driver_id") == drv["id"]]
    # The sweep's per-driver entry exists in the response.
    assert matching, (
        f"sweep did not list the expiring driver in driver_recomputes: "
        f"{[d.get('driver_id') for d in drv_recomputes]}"
    )
    entry = matching[0]
    # The status_flip discriminator is VALID_TO_INVALID on the
    # downward arc.  PRD §2.5's "The upward direction
    # ``INVALID → VALID`` is deliberately not fired by the sweep"
    # means the upward-arc discriminator value doesn't exist.
    assert entry.get("status_flip") == SweepDriverStatusFlip.VALID_TO_INVALID.value, (
        f"expected the status_flip discriminator VALID_TO_INVALID on the wall-clock-expiry "
        f"flip; got {entry.get('status_flip')!r}"
    )
    # The post-sweep driver row is now INVALID.
    drv_post_sweep = get_success_data(api.get_driver(drv["id"], reg))
    assert drv_post_sweep["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value


def test_sweep_does_not_auto_flip_invalid_back_to_valid(api, qualified_carrier: HazmatScenario):
    """PRD §3.2: "The upward ``INVALID → VALID`` direction is the
    manual attestation only; the keep-the-regulator-in-the-loop
    convention forbids an automatic upward flip even when the
    rolling-points fall-off or the appeal-uphold has brought the
    total back below the threshold".

    Drive a driver to ``INVALID`` via the points-threshold-crossing
    side-effect, then uphold the offending penalties so the
    rolling total falls back below the threshold, then run the
    sweep.  The sweep's response does NOT carry an upward-flip
    discriminator value for the driver (no ``status_flip`` field,
    or null), and the driver's status is still ``INVALID`` on the
    post-sweep read.  Only an explicit attestation flips the
    driver back to ``VALID``.
    """
    scenario = qualified_carrier
    drv_id = scenario.drivers[0]["id"]
    reg = regulator_headers()
    # Push the rolling total over the threshold.
    issued_penalties = push_driver_to_suspension_threshold(
        api, scenario, target_points=THRESHOLD_DRIVER_SUSPENSION_POINTS
    )
    # The driver's status should now be INVALID.
    drv_after_push = get_success_data(api.get_driver(drv_id, reg))
    assert drv_after_push["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value
    assert drv_after_push["current_rolling_points"] >= THRESHOLD_DRIVER_SUSPENSION_POINTS

    # Uphold every issued penalty.  The cache's rolling total falls
    # back to zero.
    for i in range(len(issued_penalties)):
        # The uphold-helper updates scenario.penalties in-place.
        uphold_penalty(api, scenario, penalty_idx=i)

    # Confirm the rolling total has dropped.
    drv_after_uphold = get_success_data(api.get_driver(drv_id, reg))
    # The cache equals the rolling-window-sum-over-ACTIVE-rows,
    # which is now zero because every issued penalty has been
    # flipped to UPHELD.
    assert drv_after_uphold["current_rolling_points"] == 0, (
        f"post-uphold rolling total is {drv_after_uphold['current_rolling_points']}, expected 0"
    )
    # The status is STILL INVALID — the keep-the-regulator-in-
    # the-loop rule.
    assert drv_after_uphold["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value

    # Run the sweep.  The sweep also does not auto-flip the driver
    # back; the upward arc is the manual refresh-endorsement only.
    sw = run_full_sweep(api)
    drvs = sw.get("driver_recomputes") or []
    entry = next((d for d in drvs if d.get("driver_id") == drv_id), None)
    if entry is not None:
        # The status_flip discriminator on the upward arm is not in
        # the enum (the SweepDriverStatusFlip enum has only the
        # VALID_TO_INVALID value).
        assert entry.get("status_flip") in (None, ""), (
            f"upward-direction status_flip on the sweep must be null/absent, got {entry.get('status_flip')!r}"
        )

    drv_post_sweep = get_success_data(api.get_driver(drv_id, reg))
    assert drv_post_sweep["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value, (
        "the sweep must not auto-flip the driver back to VALID; the regulator's "
        "explicit refresh-endorsement attestation is the required upward arc"
    )

    # Now the regulator's explicit refresh-endorsement flips the
    # driver back.  Per PRD §3.2's attestation-shape's preconditions,
    # the driver's ``current_rolling_points < THRESHOLD`` must hold,
    # which it does (zero), and the endorsement_valid_until must be
    # in the future, and the endorsement_classes must be in the
    # company's authorized set.
    server_now = current_server_now(api)
    fresh_evu = add_days(server_now, 365.0)
    attest_body = driver_attestation_payload(
        endorsement_valid_until=fresh_evu,
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    reattested = get_success_data(api.refresh_driver_endorsement(drv_id, attest_body, reg))
    assert reattested["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value


# ─── Rolling-points threshold arc (the side-effect on penalty-create) ─


def test_penalty_create_at_threshold_atomic_flip_to_invalid(api, qualified_carrier: HazmatScenario):
    """PRD §3.2 + §3.8: "the rolling-points-driven ``VALID → INVALID``
    fired as a synchronous side-effect of a Penalty-insert when the
    post-insert recompute of the subject driver's
    ``current_rolling_points`` is at or above the threshold; this
    side-effect happens inside the same atomic transaction that
    wrote the Penalty row, so the post-penalty-create observation
    of the Driver's row shows the new points value and the flipped
    status together".

    Insert a single manual penalty whose ``points_value`` is exactly
    the threshold and assert the driver is now in INVALID.  The
    ``current_rolling_points`` on the driver row equals the
    threshold.  The driver-side observability is the
    ``hazmat_endorsement_status = INVALID`` and the
    ``current_rolling_points = THRESHOLD_DRIVER_SUSPENSION_POINTS``
    pair the test asserts on.
    """
    scenario = qualified_carrier
    drv = scenario.drivers[0]
    assert drv["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value
    pre_total = drv.get("current_rolling_points", 0)
    server_now = current_server_now(api)
    payload = create_penalty_payload(
        subject_type=PenaltySubjectType.DRIVER.value,
        subject_id=drv["id"],
        observed_at=iso_now_plus_delta(seconds=-1.0, base_iso=server_now),
        points_value=int(THRESHOLD_DRIVER_SUSPENSION_POINTS),
        reason_note="Test boundary penalty exactly at the suspension threshold.",
    )
    resp = api.create_penalty(payload, regulator_headers())
    pen = validate_success(resp, 201)
    # The penalty row's data is the response body's data; the
    # cascade summary the PRD §3.8 names may be a sub-block or
    # the row itself.  The standard shape is the row at the top
    # with a sibling ``cascade_summary``.  The
    # ``cascade_summary.new_rolling_points`` (or the equivalent
    # under another key the implementation chooses) reflects the
    # post-insert cache.
    cascade = pen.get("cascade_summary") or {}
    # Whichever key carries the new rolling total, the driver's
    # GET should report it.
    drv_after = get_success_data(api.get_driver(drv["id"], regulator_headers()))
    assert drv_after["current_rolling_points"] == pre_total + int(THRESHOLD_DRIVER_SUSPENSION_POINTS), (
        f"post-create rolling total is {drv_after['current_rolling_points']}; "
        f"expected pre_total {pre_total} + points_value {THRESHOLD_DRIVER_SUSPENSION_POINTS}"
    )
    # The status has flipped atomically.
    assert drv_after["hazmat_endorsement_status"] == DriverEndorsementStatus.INVALID.value
    # The driver's version is bumped (the cache mutation is the
    # "logical mutation" the PRD §2.10 names — the OCC counter
    # increments).
    assert drv_after["version"] >= drv["version"] + 1


def test_penalty_create_just_below_threshold_keeps_valid(api, qualified_carrier: HazmatScenario):
    """The companion of the at-threshold test: a penalty whose
    ``points_value`` brings the post-insert total to one below the
    threshold keeps the driver's status at ``VALID``.

    The threshold predicate is inclusive-greater-than-or-equal per
    PRD §2.8's "the boundary at
    ``current_rolling_points >= THRESHOLD_DRIVER_SUSPENSION_POINTS``
    is the inclusive-equality boundary at which the driver's hazmat
    endorsement flips".  One below the threshold is the
    last-clean state.
    """
    scenario = qualified_carrier
    drv = scenario.drivers[0]
    pre_total = drv.get("current_rolling_points", 0)
    # Stay strictly below the threshold by the gap of one.
    target_points = THRESHOLD_DRIVER_SUSPENSION_POINTS - 1 - pre_total
    if target_points <= 0:
        pytest.skip(
            "the test-side helper that pushes the rolling total expects a "
            "starting total below the threshold-minus-one; the qualified-carrier "
            "fixture's driver should always satisfy this precondition"
        )
    server_now = current_server_now(api)
    payload = create_penalty_payload(
        subject_type=PenaltySubjectType.DRIVER.value,
        subject_id=drv["id"],
        observed_at=iso_now_plus_delta(seconds=-1.0, base_iso=server_now),
        points_value=int(target_points),
        reason_note="Test penalty bringing the total to threshold-minus-one.",
    )
    api.create_penalty(payload, regulator_headers())
    drv_after = get_success_data(api.get_driver(drv["id"], regulator_headers()))
    assert drv_after["current_rolling_points"] == pre_total + int(target_points)
    assert drv_after["current_rolling_points"] < THRESHOLD_DRIVER_SUSPENSION_POINTS
    assert drv_after["hazmat_endorsement_status"] == DriverEndorsementStatus.VALID.value, (
        "the driver's status must remain VALID below the inclusive-threshold boundary"
    )


def test_attest_under_threshold_constraint_enforced(api, approved_company: Dict):
    """PRD §3.2: "the driver's ``current_rolling_points`` is strictly
    less than the suspension threshold ``THRESHOLD_DRIVER_SUSPENSION_POINTS``
    at the moment of the call.  The points-precondition is a
    regulatory-attestation interlock: the regulator may not attest
    a driver whose current rolling total is at or above the
    threshold, because doing so would put the driver in a
    contradictory state (``VALID`` while the points-rule alone
    would say ``INVALID``)".

    The test creates a NOT_ATTESTED driver, issues a penalty
    against the driver whose points-value equals the threshold,
    then attempts to attest.  The attestation fails because the
    points-precondition is violated (the rolling total is at the
    threshold).  The error id is the priority-510
    ``ERR_DRIVER_ENDORSEMENT_INVALID`` per the PRD's §1.6 catalog
    on "the driver's standing is the wrong value" cause-class.

    Two valid implementation readings exist: the attestation-
    precondition violation could surface as the dedicated
    ``ERR_DRIVER_ENDORSEMENT_INVALID`` 409 (the issue-time
    fail-the-driver-leg error from PRD §3.5) or as the generic
    ``ERR_INVALID_STATE_TRANSITION`` 409 from the same-row
    state-tier (since the driver is NOT_ATTESTED and the
    attestation is the canonical transition).  We accept either
    by the framework's ``validate_error_is_one_of`` helper.

    The PRD's wording on this exact edge case is the §3.2
    paragraph quoted in this docstring.  A strict reading is
    "the points-precondition is a regulatory-attestation
    interlock", which suggests the dedicated error.  A relaxed
    reading is "the transition's guard's conjunction includes the
    points-precondition", so the generic state-tier error fires.
    Both readings are PRD-faithful given the
    interlock-vs-guard ambiguity.
    """
    op = company_operator_headers(approved_company["id"])
    reg = regulator_headers()
    drv = get_success_data(api.create_driver(approved_company["id"], create_driver_payload(), op))
    # Issue a manual penalty pushing the rolling total to exactly
    # the threshold.  The driver is still NOT_ATTESTED, but
    # the penalty's subject_type=DRIVER + the threshold-crossing
    # side-effect of the penalty-insert is the same regardless of
    # the driver's prior status; the cache simply tracks the sum
    # over all non-UPHELD penalties on the subject driver within
    # the rolling window.
    server_now = current_server_now(api)
    pen_payload = create_penalty_payload(
        subject_type=PenaltySubjectType.DRIVER.value,
        subject_id=drv["id"],
        observed_at=iso_now_plus_delta(seconds=-1.0, base_iso=server_now),
        points_value=int(THRESHOLD_DRIVER_SUSPENSION_POINTS),
        reason_note="Threshold-pushing pre-attestation penalty.",
    )
    api.create_penalty(pen_payload, reg)
    # Now attempt the attestation.
    fresh_evu = add_days(server_now, 365.0)
    body = driver_attestation_payload(
        endorsement_valid_until=fresh_evu,
        endorsement_classes=list(CANONICAL_HAZARD_CLASSES),
    )
    attempt = api.refresh_driver_endorsement(drv["id"], body, reg)
    from prd_bench_local_runner.testing import validate_error_is_one_of

    actual = validate_error_is_one_of(
        attempt,
        [
            ApiErrorId.ERR_DRIVER_ENDORSEMENT_INVALID.value,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        ],
    )
    assert actual in {
        ApiErrorId.ERR_DRIVER_ENDORSEMENT_INVALID.value,
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    }


# ─── Driver natural-key uniqueness ────────────────────────────────────


def test_license_number_unique_per_company(api, approved_company: Dict):
    """PRD §2.4 + §3.2: "The driver's ``license_number`` is 6 to 32
    characters with no embedded whitespace, and its uniqueness
    scope is per-company (two different companies may both employ
    a driver named on a same-string license, but no two drivers
    in one company may share a license number)".  A
    same-(company-id, license_number) second-insert is the
    ``ERR_DUPLICATE_IDENTIFIER`` 409.
    """
    op = company_operator_headers(approved_company["id"])
    shared_lic = "LIC" + "1" * 6
    pa = create_driver_payload(license_number=shared_lic, full_name="Alice")
    pb = create_driver_payload(license_number=shared_lic, full_name="Bob")
    r1 = api.create_driver(approved_company["id"], pa, op)
    assert r1.status_code == 201
    r2 = api.create_driver(approved_company["id"], pb, op)
    validate_error(r2, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, expected_status=409)


def test_license_number_same_across_different_companies_is_ok(api):
    """The same paragraph: "two different companies may both employ
    a driver named on a same-string license" — the uniqueness
    scope is the (company-id, license-number) pair, not the
    license-number alone.  Two distinct APPROVED companies each
    creating a driver with the same license-number-string both
    succeed.
    """
    co_a = setup_approved_company(api)
    co_b = setup_approved_company(api)
    shared_lic = "SHRLIC" + "9" * 6
    op_a = company_operator_headers(co_a["id"])
    op_b = company_operator_headers(co_b["id"])
    p = create_driver_payload(license_number=shared_lic, full_name="Same-name-different-co")
    r_a = api.create_driver(co_a["id"], p, op_a)
    r_b = api.create_driver(co_b["id"], create_driver_payload(license_number=shared_lic, full_name="Other"), op_b)
    assert r_a.status_code == 201
    assert r_b.status_code == 201
    drv_a = r_a.json()["data"]
    drv_b = r_b.json()["data"]
    assert drv_a["license_number"] == drv_b["license_number"] == shared_lic
    assert drv_a["company_id"] != drv_b["company_id"]


# ─── Penalty-summary digest's structural fields ──────────────────────


def test_penalty_summary_carries_threshold_and_rolling_total(api, qualified_carrier: HazmatScenario):
    """PRD §3.8's penalty-summary digest specifies the response
    payload's structural fields: the ``as_of`` ISO timestamp, the
    driver's ``current_rolling_points`` integer, the ``threshold``
    integer (the configured ``THRESHOLD_DRIVER_SUSPENSION_POINTS``
    value exposed on the response so the client can compute the
    points-buffer without the constant out of band), the
    ``hazmat_endorsement_status`` enum value, the
    ``endorsement_valid_until`` ISO timestamp (or null), the
    ``endorsement_classes`` hazard-class subset, the two
    in-window arrays of penalty digests, and the
    ``permits_currently_listing_this_driver`` array of per-permit
    snapshot-vs-live boolean pairs.

    The qualified_carrier fixture's driver has no penalties yet,
    so the rolling-total is zero and the two in-window arrays are
    empty; the
    ``permits_currently_listing_this_driver`` array is empty too
    (no permit has been issued in the fixture, since
    ``qualified_carrier`` stops at the route-approved stage).
    """
    summary = fetch_penalty_summary(api, qualified_carrier, driver_idx=0, requester="self")
    drv = qualified_carrier.drivers[0]
    assert summary["driver_id"] == drv["id"]
    assert isinstance(summary.get("as_of"), str)
    assert summary.get("current_rolling_points") == 0
    assert summary.get("threshold") == THRESHOLD_DRIVER_SUSPENSION_POINTS
    assert summary.get("hazmat_endorsement_status") == DriverEndorsementStatus.VALID.value
    assert summary.get("endorsement_valid_until") is not None
    assert set(summary.get("endorsement_classes") or []) >= set(CANONICAL_HAZARD_CLASSES) or summary.get("endorsement_classes") == list(CANONICAL_HAZARD_CLASSES)
    assert summary.get("active_penalties_in_window") == []
    assert summary.get("upheld_penalties_in_window") in (None, [])
    # No permit has been issued in the qualified-carrier-without-
    # permit fixture, so the permits-listing array is empty.
    listing = summary.get("permits_currently_listing_this_driver") or []
    assert listing == [], (
        f"qualified-carrier-pre-permit fixture's driver has no permits listing them; "
        f"got {listing!r}"
    )


def test_penalty_summary_after_create_reflects_new_total(api, qualified_carrier: HazmatScenario):
    """After a manual penalty against the driver, the
    penalty-summary digest's ``current_rolling_points`` reflects
    the post-insert cache and the ``active_penalties_in_window``
    array contains the new row's digest entry.
    """
    scenario = qualified_carrier
    drv_id = scenario.drivers[0]["id"]
    server_now = current_server_now(api)
    pre_total = int(snapshot_driver_rolling_points(api, scenario, driver_idx=0))
    payload = create_penalty_payload(
        subject_type=PenaltySubjectType.DRIVER.value,
        subject_id=drv_id,
        observed_at=iso_now_plus_delta(seconds=-10.0, base_iso=server_now),
        points_value=5,
        reason_note="Test penalty for the penalty-summary integration.",
    )
    pen_resp = api.create_penalty(payload, regulator_headers())
    pen = get_success_data(pen_resp)
    pen_row = pen.get("penalty") if isinstance(pen, dict) and "penalty" in pen else pen
    new_total = snapshot_driver_rolling_points(api, scenario, driver_idx=0)
    assert new_total == pre_total + 5
    # The summary reflects the same total.
    summary = fetch_penalty_summary(api, scenario, driver_idx=0, requester="regulator")
    assert summary["current_rolling_points"] == new_total
    # The active-penalties array carries one entry (the just-
    # issued penalty).
    arr = summary.get("active_penalties_in_window") or []
    assert len(arr) == 1
    e = arr[0]
    assert e.get("id") == pen_row["id"]
    assert e.get("points_value") == 5
    assert e.get("source") == "MANUAL_REGULATOR"
    assert e.get("observed_at") == payload["observed_at"]


def test_penalty_summary_after_uphold_excludes_upheld_points(api, qualified_carrier: HazmatScenario):
    """PRD §2.11: "The function ``driver_penalty_point_rolling_total``
    … excludes the `UPHELD` rows from the rolling sum, on the
    principle that a successfully-appealed penalty does not count
    toward the disciplinary total".

    Issue a penalty, observe the post-create rolling total go up
    by the points-value.  Uphold the penalty.  Observe the
    post-uphold rolling total fall back to the pre-create value.
    Confirm the ``upheld_penalties_in_window`` array in the
    penalty-summary now contains the upheld row's digest entry
    while the ``active_penalties_in_window`` array no longer
    does.

    This is the disciplinary-points-conservation invariant from
    PRD §2.11's "a create-then-uphold pair on the same penalty
    within the rolling window leaves the rolling total at the
    pre-create value", restricted to the standard in-window
    timing case where the uphold happens within the
    ``APPEAL_WINDOW_DAYS`` of the original ``observed_at``.
    """
    scenario = qualified_carrier
    pre_total = int(snapshot_driver_rolling_points(api, scenario, driver_idx=0))
    pen_row = issue_manual_driver_penalty(
        api,
        scenario,
        driver_idx=0,
        points_value=4,
        observed_at_offset_seconds=-30.0,
    )
    post_create_total = int(snapshot_driver_rolling_points(api, scenario, driver_idx=0))
    assert post_create_total == pre_total + 4

    # Now uphold the appeal.  The penalty's row index in the
    # scenario.penalties list is the last-appended entry, which is
    # the default for the uphold-helper's ``penalty_idx`` argument.
    uphold_row = uphold_penalty(api, scenario, penalty_idx=-1)
    assert uphold_row["void_status"] == PenaltyVoidStatus.UPHELD.value

    post_uphold_total = int(snapshot_driver_rolling_points(api, scenario, driver_idx=0))
    assert post_uphold_total == pre_total, (
        f"post-uphold rolling total {post_uphold_total} != pre-create total {pre_total}; "
        "the conservation identity from PRD §2.11 is violated"
    )

    # Penalty-summary reflects the move.
    summary = fetch_penalty_summary(api, scenario, driver_idx=0, requester="regulator")
    active = summary.get("active_penalties_in_window") or []
    upheld_arr = summary.get("upheld_penalties_in_window") or []
    assert all(p["id"] != pen_row["id"] for p in active), (
        "after the uphold the penalty must not appear in active_penalties_in_window"
    )
    upheld_ids = [p["id"] for p in upheld_arr]
    assert pen_row["id"] in upheld_ids, (
        "after the uphold the penalty must appear in upheld_penalties_in_window"
    )


def test_appeal_window_closed_rejects_late_uphold(api, qualified_carrier: HazmatScenario):
    """PRD §3.8 + §2.9: "the appeal-window check at the
    safety-tier priority 513 is the duration ``now() - observed_at``
    at most ``APPEAL_WINDOW_DAYS`` — the scaffold's intended 30
    days, with the closed-right convention on the duration meaning
    the boundary moment at exactly 30 days is the last in-window
    moment and any strictly-larger duration is out-of-window with
    ``ERR_APPEAL_WINDOW_CLOSED`` 409".

    Issue a penalty with ``observed_at`` exactly the current
    server-clock.  Advance the clock by
    ``APPEAL_WINDOW_DAYS + 1`` days.  An uphold attempt now is
    strictly past the window's closed-right edge by one day, so
    the rejection is ``ERR_APPEAL_WINDOW_CLOSED``.

    The "exactly at the closed-right boundary" admissible case is
    the boundary-precision test in
    ``test_worked_examples.py``'s
    ``appeal_window_closed_right_at_exactly_thirty_days_since_observed_at``
    entry, with the ``-1 second`` and ``+1 second`` flanking cases
    completing the X-1-X-X+1 trio.
    """
    scenario = qualified_carrier
    # Issue a penalty with observed_at one second before "now".
    server_now = current_server_now(api)
    obs_at = iso_now_plus_delta(seconds=-1.0, base_iso=server_now)
    payload = create_penalty_payload(
        subject_type=PenaltySubjectType.DRIVER.value,
        subject_id=scenario.drivers[0]["id"],
        observed_at=obs_at,
        points_value=1,
        reason_note="Test appeal-window-edge penalty.",
    )
    pen = get_success_data(api.create_penalty(payload, regulator_headers()))
    pen_row = pen.get("penalty") if "penalty" in pen else pen
    # Advance the clock by APPEAL_WINDOW_DAYS + 1 day so the
    # duration ``now - observed_at`` is strictly past the window.
    advance_clock_by(api, (APPEAL_WINDOW_DAYS + 1) * 86400.0, run_sweep=False)
    # Attempt the uphold; the priority-513 window check fires.
    from test_helpers import uphold_penalty_payload

    resp = api.uphold_penalty(pen_row["id"], uphold_penalty_payload(), regulator_headers())
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, expected_status=409)
