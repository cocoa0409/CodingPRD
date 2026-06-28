"""Cascade, conserved-invariant, boundary-precision, and auto-FNOL tests.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rules `transitive_cascade`,
`compensating_invariant`, and `boundary_precision_check`; and
SCAFFOLD_CORNER_DESIGN.yaml queue B sections `state_machines` (crash auto-FNOL) and
`consistency_model`.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_trip_payload,
    create_trip_event_payload,
    create_privacy_consent_payload,
    TEST_USERS,
    make_driver_headers,
    set_clock,
    create_rate_plan,
    create_driver,
    create_enrollment,
    add_enrollment_trip,
    finalize_scoring,
    create_quote,
    bind_policy,
    driver_headers,
    add_policy_trip,
    hard_brake_events,
    get_policy,
    get_driver,
    get_discount_bank,
    list_risk_snapshots,
    setup_bound_policy,
    setup_bound_policy_with_standard_score,
    setup_driver_two_active_policies,
)
from test_helpers import api_client

UW = TEST_USERS["underwriting_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: transitive_cascade
#   instance: trip_accept_score_multiplier_snapshot_chain (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_trip_accept_recomputes_score_and_multiplier(api):
    """PRD §3.5: "for a policy-bound trip the driver's `lifetime_safe_miles` is
    increased by the trip's `distance_miles` and the policy's `current_risk_score` is
    recomputed with the operational variant. Then the policy's
    `current_risk_multiplier` is recomputed from the new score via the tier table".

    Design: Difficulty/transitive_cascade/trip_accept_score_multiplier_snapshot_chain
    """
    ctx, _trip = setup_bound_policy_with_standard_score(
        clock="2026-05-01T00:00:00Z", scoring_day="2026-05-01",
        drive_day="2026-05-02", distance=30.0)
    policy = get_policy(ctx)
    # hb=6 -> 6*2.0 = 12.0 (STANDARD) -> multiplier 1.0
    assert policy["current_risk_score"] == pytest.approx(12.0, abs=0.001)
    assert policy["current_risk_multiplier"] == pytest.approx(1.0, abs=0.001)


def test_trip_accept_appends_snapshot_with_new_multiplier(api):
    """PRD §3.5: "and a risk-score snapshot is appended with trigger reason
    `TRIP_ACCEPTED`."

    Design: Difficulty/transitive_cascade/trip_accept_score_multiplier_snapshot_chain
    """
    ctx, _trip = setup_bound_policy_with_standard_score(
        clock="2026-05-01T00:00:00Z", scoring_day="2026-05-01",
        drive_day="2026-05-02", distance=30.0)
    snapshots = list_risk_snapshots(ctx)
    accepted = [s for s in snapshots if s["trigger_reason"] == "TRIP_ACCEPTED"]
    assert accepted, "expected a TRIP_ACCEPTED snapshot"
    newest = accepted[-1]
    assert newest["risk_score"] == pytest.approx(12.0, abs=0.001)
    assert newest["risk_multiplier"] == pytest.approx(1.0, abs=0.001)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: transitive_cascade
#   instance: optout_flag_then_policy_suspend_cascade (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_optout_flips_driver_flag(api):
    """PRD §3.2: "A `REVOKE` is the opt-out: it flips the driver's
    `telematics_opted_out` from false to true."

    Design: Difficulty/transitive_cascade/optout_flag_then_policy_suspend_cascade
    """
    driver, _p1, _p2, hdr = setup_driver_two_active_policies(clock="2026-05-01T00:00:00Z")
    get_success_data(api.create_privacy_consent(
        driver["id"], create_privacy_consent_payload("REVOKE", reason="stop tracking"), hdr))
    refreshed = get_success_data(api.get_driver(driver["id"], hdr))
    assert refreshed["telematics_opted_out"] is True


def test_optout_cascades_suspend_to_all_active_policies(api):
    """PRD §3.2: "When a driver revokes consent, every one of that driver's policies
    whose lifecycle is `ACTIVE` has its telematics dimension transitioned from
    `CAPTURING` to `SUSPENDED` as a cascade, so that no further trips can be accepted on
    any of them."

    Design: Difficulty/transitive_cascade/optout_flag_then_policy_suspend_cascade
    """
    driver, p1, p2, hdr = setup_driver_two_active_policies(clock="2026-05-01T00:00:00Z")
    get_success_data(api.create_privacy_consent(
        driver["id"], create_privacy_consent_payload("REVOKE", reason="stop tracking"), hdr))
    p1_after = get_success_data(api.get_policy(p1["id"], UW))
    p2_after = get_success_data(api.get_policy(p2["id"], UW))
    assert p1_after["telematics_status"] == "SUSPENDED"
    assert p2_after["telematics_status"] == "SUSPENDED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: compensating_invariant
#   instance: trip_void_restores_lifetime_safe_miles (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def _bound_policy_with_accepted_miles(distance, clock="2026-06-01T00:00:00Z"):
    """Bound policy + one accepted policy trip of `distance` miles (clean). Returns
    (ctx, trip)."""
    ctx = setup_bound_policy(clock=clock, scoring_day="2026-06-01")
    trip = add_policy_trip(ctx, "2026-06-05T01:00:00Z", "2026-06-05T02:00:00Z", distance,
                           events=None, accept=True)
    return ctx, trip


def test_trip_void_restores_lifetime_safe_miles(api):
    """PRD §3.5: "for a policy-bound trip the driver's `lifetime_safe_miles` is
    decreased by the trip's `distance_miles`, restoring the conserved-odometer
    invariant".

    Design: Difficulty/compensating_invariant/trip_void_restores_lifetime_safe_miles
    """
    ctx, trip = _bound_policy_with_accepted_miles(30.0)
    before = get_driver(ctx)
    assert before["lifetime_safe_miles"] == 30
    get_success_data(api.void_trip(trip["id"], UW))
    after = get_driver(ctx)
    assert after["lifetime_safe_miles"] == 0


def test_trip_void_marks_trip_voided(api):
    """PRD §3.5: "An `UnderwritingOps` operator may void an already-`ACCEPTED` trip,
    moving it to the terminal `VOIDED` state."

    Design: Difficulty/compensating_invariant/trip_void_restores_lifetime_safe_miles
    """
    ctx, trip = _bound_policy_with_accepted_miles(30.0)
    voided = get_success_data(api.void_trip(trip["id"], UW))
    assert voided["status"] == "VOIDED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: compensating_invariant
#   instance: trip_void_reverses_banked_safe_trip_discount (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_trip_void_reverses_banked_safe_trip_discount(api):
    """PRD §3.5: "if this trip had earned a safe-trip grant, the discount bank's
    `earned_cents` is decreased by 250 and a reversal-leg grant is appended, preserving
    the non-negative available-funds invariant."

    Design: Difficulty/compensating_invariant/trip_void_reverses_banked_safe_trip_discount
    """
    ctx, trip = _bound_policy_with_accepted_miles(10.0)  # clean 10-mile trip earns 250
    earned_before = get_discount_bank(ctx)["earned_cents"]
    assert earned_before == 250
    get_success_data(api.void_trip(trip["id"], UW))
    bank = get_discount_bank(ctx)
    assert bank["earned_cents"] == 0


def test_trip_void_keeps_available_funds_non_negative(api):
    """PRD §2.6: "available funds equal cumulative earned funds minus cumulative
    redeemed funds, and available funds may never go negative."

    Design: Difficulty/compensating_invariant/trip_void_reverses_banked_safe_trip_discount
    """
    ctx, trip = _bound_policy_with_accepted_miles(10.0)
    get_success_data(api.void_trip(trip["id"], UW))
    bank = get_discount_bank(ctx)
    assert bank["available_cents"] == 0
    assert bank["available_cents"] == bank["earned_cents"] - bank["redeemed_cents"]
    assert bank["available_cents"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: boundary_precision_check
#   instance: safe_trip_discount_exact_five_miles_inclusive (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_safe_trip_below_five_miles_earns_nothing(api):
    """PRD §3.5: "When an accepted policy trip has a hard-brake count of zero **and** a
    speeding count of zero **and** a phone-use count of zero, and its `distance_miles`
    is greater than or equal to 5.0 miles, the driver earns a safe-trip discount of 250
    cents". PRD §3.5: "A trip of exactly 5.0 miles qualifies; any distance below 5.0
    does not."

    Design: Difficulty/boundary_precision_check/safe_trip_discount_exact_five_miles_inclusive
    """
    ctx = setup_bound_policy(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    add_policy_trip(ctx, "2026-06-02T01:00:00Z", "2026-06-02T01:30:00Z", 4.99,
                    events=None, accept=True)
    bank = get_discount_bank(ctx)
    assert bank["earned_cents"] == 0


def test_safe_trip_exactly_five_miles_earns_250(api):
    """PRD §3.5: "A trip of exactly 5.0 miles qualifies; any distance below 5.0 does
    not." PRD §3.5: "the driver earns a safe-trip discount of 250 cents: the discount
    bank's `earned_cents` increases by 250".

    Design: Difficulty/boundary_precision_check/safe_trip_discount_exact_five_miles_inclusive
    """
    ctx = setup_bound_policy(clock="2026-06-01T00:00:00Z", scoring_day="2026-06-01")
    add_policy_trip(ctx, "2026-06-02T02:00:00Z", "2026-06-02T02:30:00Z", 5.0,
                    events=None, accept=True)
    bank = get_discount_bank(ctx)
    assert bank["earned_cents"] == 250


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: boundary_precision_check
#   instance: finalize_scoring_blocked_below_min_trip_count (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def _scoring_enrollment_with_n_trips(n, clock="2026-06-01T00:00:00Z"):
    set_clock(clock)
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    for i in range(n):
        hour = f"{i + 1:02d}"
        add_enrollment_trip(driver, enrollment,
                            f"2026-06-01T{hour}:00:00Z", f"2026-06-01T{hour}:10:00Z", 4.0,
                            accept=True)
    return driver, enrollment


def test_finalize_blocked_with_two_trips_below_minimum(api):
    """PRD §3.3: "Finalization is permitted only when the enrollment is currently in
    `SCORING` ..., when at least three scoring trips have been captured — the minimum
    scoring-trip count is three — (otherwise `ERR_INSUFFICIENT_SCORING_TRIPS`)".

    Design: Difficulty/boundary_precision_check/finalize_scoring_blocked_below_min_trip_count
    """
    driver, enrollment = _scoring_enrollment_with_n_trips(2)
    res = api.finalize_scoring(enrollment["id"], make_driver_headers(driver["id"]))
    validate_error(res, "ERR_INSUFFICIENT_SCORING_TRIPS", expected_status=422)


def test_finalize_blocked_leaves_enrollment_in_scoring(api):
    """PRD §3.3: "a freshly opened enrollment has `status` `SCORING`".
    PRD §3.3: "at least three scoring trips have been captured ... (otherwise
    `ERR_INSUFFICIENT_SCORING_TRIPS`)".

    Design: Difficulty/boundary_precision_check/finalize_scoring_blocked_below_min_trip_count
    """
    driver, enrollment = _scoring_enrollment_with_n_trips(2)
    hdr = make_driver_headers(driver["id"])
    api.finalize_scoring(enrollment["id"], hdr)
    refreshed = get_success_data(api.get_enrollment(enrollment["id"], hdr))
    assert refreshed["captured_trip_count"] == 2
    assert refreshed["status"] == "SCORING"


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines (crash auto-FNOL) + consistency_model
# ─────────────────────────────────────────────────────────────────────────────

def test_crash_auto_fnol_claim_created_on_accept(api):
    """PRD §3.8: "When a policy-bound trip carrying a qualifying crash is accepted, the
    platform automatically opens a **claim** as a First Notice Of Loss". PRD §3.8: "An
    auto-created claim records the `policy_id`, the `trip_id` of the crash trip, an
    `origin` of `AUTO_FNOL`, and a `reported_severity` copied from the triggering
    `CRASH` event; it opens in `status` `FNOL`".
    PRD §3.5: "A `CRASH` event whose `severity` is at least the crash-FNOL severity
    threshold of 4 sets the trip's `crash_detected` flag to true".

    Design: Corner/state_machines/crash_auto_fnol_claim_created_on_accept
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    trip = add_policy_trip(
        ctx, "2026-02-05T01:00:00Z", "2026-02-05T01:30:00Z", 12.0,
        events=[("CRASH", 5, "2026-02-05T01:10:00Z")], accept=True)
    assert trip["crash_detected"] is True
    res = api.list_claims(UW, params={"trip_id": trip["id"]})
    body = res.json()
    claims = body.get("data", [])
    assert len(claims) == 1
    assert claims[0]["origin"] == "AUTO_FNOL"
    assert claims[0]["status"] == "FNOL"


def test_score_visible_immediately_after_accept(api):
    """PRD §3.5: "the policy's `current_risk_score` is recomputed with the operational
    variant." PRD §3.5: "a risk-score snapshot is appended with trigger reason
    `TRIP_ACCEPTED`."

    Design: Corner/consistency_model/immediate_consistency_score_visible_in_same_accept_response
    """
    ctx, _trip = setup_bound_policy_with_standard_score(
        clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01",
        drive_day="2026-02-05", distance=30.0)
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], UW))
    assert policy["current_risk_score"] == pytest.approx(12.0, abs=0.001)
    snapshots = list_risk_snapshots(ctx)
    matching = [s for s in snapshots
                if s["trigger_reason"] == "TRIP_ACCEPTED" and s["risk_score"] == pytest.approx(12.0, abs=0.001)]
    assert matching, "expected an immediately-visible TRIP_ACCEPTED snapshot at score 12.0"
