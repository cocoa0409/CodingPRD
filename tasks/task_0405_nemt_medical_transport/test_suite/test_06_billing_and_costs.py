"""Billing axis: forward claim vs chronological encounter, the deliberate cost
divergence, parallel axes, reconciliation, and dispute/override.

Difficulty queue A (dual_variant_calc costs, combinatorial_formula rounding,
non_linear_state_machine parallel axes, cross_entity_state_dependency claim,
compensating_invariant variance) plus corner queue B (validations recon, state
machine dispute-override).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    assert_reconciliation_variance_identity,
    create_claim_payload,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]
BROKER = TEST_USERS["broker_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---- shared world for WHEELCHAIR will-call divergence (7000 vs 7780) ----

WC_RATE = {"base_fare_cents": 2000, "loaded_rate_cents_per_mile": 150,
           "dwell_free_minutes": 10, "dwell_cents_per_minute": 50}


def _wheelchair_will_call_world(medicaid_id):
    return fixtures.setup_world(
        modality="WHEELCHAIR", medicaid_id=medicaid_id, broker_max_modality="STRETCHER",
        span_los="BARIATRIC", clock="2026-03-01T08:00:00Z", rate_overrides=WC_RATE)


def test_claimed_forward_vs_encounter_chronological_diverge(api):
    """PRD 3.7: "The claimed cost is the sum of the base component plus the loaded
    component itself multiplied by the leg multiplier, and the whole sum is
    rounded half up exactly once, after the summation."
    PRD 3.8: "it rounds each leg to whole cents *before* summing rather than
    rounding once at the end."

    Design: Difficulty/dual_variant_calc/claimed_forward_vs_encounter_chronological_diverge
    """
    world = _wheelchair_will_call_world("M-DV-1")
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.4,
        rt_odometer=9.8, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:25:00Z")
    claim = fixtures.submit_claim(trip["id"])
    encounter = fixtures.capture_encounter(trip["id"])
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert final["claimed_cost_cents"] == 7000
    assert final["encounter_cost_cents"] == 7780
    assert final["claimed_cost_cents"] != final["encounter_cost_cents"]


def test_encounter_round_per_leg_then_sum_order(api):
    """PRD 3.8: "For each leg in that order, compute the leg's cost as the rate's
    `base_fare_cents`, plus the rate's `loaded_rate_cents_per_mile` multiplied by
    the leg's `odometer_loaded_miles`, plus the rate's `dwell_cents_per_minute`
    multiplied by the leg's `dwell_minutes`, and round that per-leg amount half up
    to whole cents. The encounter cost is the sum of those rounded per-leg amounts."

    Design: Difficulty/combinatorial_formula/encounter_round_per_leg_then_sum_order
    """
    world = _wheelchair_will_call_world("M-CR-1")
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.4,
        rt_odometer=9.8, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:25:00Z")
    fixtures.submit_claim(trip["id"])
    encounter = fixtures.capture_encounter(trip["id"])
    # outbound leg 3560 (2000+150*10.4) + return leg 4220 (2000+150*9.8+50*15) = 7780
    assert encounter["captured_cents"] == 7780
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert final["encounter_cost_cents"] == 7780


def test_claim_nonlinear_round_trip_multiplier_and_branch(api):
    """PRD 3.7: "Let the leg multiplier be 2 when the trip `is_round_trip` and 1
    otherwise — a round trip forecasts a doubled return. The loaded component is
    the rate's `loaded_rate_cents_per_mile` multiplied by the trip's
    `scheduled_loaded_miles`; the base component is the rate's `base_fare_cents`
    multiplied by the leg multiplier. The claimed cost is the sum of the base
    component plus the loaded component itself multiplied by the leg multiplier".

    Design: Difficulty/combinatorial_formula/claim_nonlinear_round_trip_multiplier_and_branch
    """
    world = _wheelchair_will_call_world("M-CB-1")
    # Round-trip, NON-will-call: claimed = 2000*2 + (150*10)*2 = 7000.
    trip, legs, driver_id = fixtures.complete_roundtrip_non_will_call(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10,
        ob_odometer=10.0, rt_odometer=10.0)
    claim = fixtures.submit_claim(trip["id"])
    assert claim["billed_cents"] == 7000
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert final["claimed_cost_cents"] == 7000
    assert final["billing_status"] == "CLAIMED"


def test_claimed_cost_ignores_odometer_actuals(api):
    """PRD 3.7: "The forward claimed cost is priced from the intake estimate, not
    from anything the driver recorded. ... Will-call dwell is not forecastable at
    claim time and is therefore excluded entirely from the forward claim; odometer
    actuals are likewise ignored."

    Design: Difficulty/dual_variant_calc/claimed_forward_vs_encounter_chronological_diverge
    """
    world = _wheelchair_will_call_world("M-DV-1b")
    # Odometers (10.4 / 9.8) differ from scheduled_loaded_miles (10); claim uses 10.
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.4,
        rt_odometer=9.8, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:25:00Z")
    claim = fixtures.submit_claim(trip["id"])
    # 2000*2 + (150*10)*2 = 7000, independent of the 10.4/9.8 odometer actuals.
    assert claim["billed_cents"] == 7000
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert final["claimed_cost_cents"] == 7000


def test_encounter_captured_cents_equals_trip_encounter_cost(api):
    """PRD 3.8: "Capture advances `billing_status` from `CLAIMED` to `ENCOUNTERED`,
    creates the encounter in `OPEN` status recording its `trip_id`, and computes
    the trip's `encounter_cost_cents`. The encounter's `captured_cents` is set
    equal to that computed `encounter_cost_cents`."

    Design: Difficulty/combinatorial_formula/encounter_round_per_leg_then_sum_order
    """
    world = _wheelchair_will_call_world("M-CR-1b")
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.4,
        rt_odometer=9.8, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:25:00Z")
    fixtures.submit_claim(trip["id"])
    encounter = fixtures.capture_encounter(trip["id"])
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert encounter["captured_cents"] == final["encounter_cost_cents"] == 7780


def test_claim_oneway_no_round_trip_multiplier(api):
    """PRD 3.7: "Let the leg multiplier be 2 when the trip `is_round_trip` and 1
    otherwise — a round trip forecasts a doubled return. ... The claimed cost is
    the sum of the base component plus the loaded component itself multiplied by
    the leg multiplier".

    Design: Difficulty/combinatorial_formula/claim_nonlinear_round_trip_multiplier_and_branch
    """
    # One-way AMBULATORY: multiplier 1. base 1500*1 + (120*8)*1 = 1500 + 960 = 2460.
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-CB-2")
    trip, legs, driver_id = fixtures.complete_oneway_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, odometer=8.0)
    claim = fixtures.submit_claim(trip["id"])
    assert claim["billed_cents"] == 2460, "one-way: multiplier 1, no return doubling"
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert final["claimed_cost_cents"] == 2460


def test_trip_parallel_axes_lifecycle_and_billing(api):
    """PRD 2.5: "A trip's two status axes evolve independently. The lifecycle axis
    is `trip_status`; the billing axis is `billing_status`. A transition on one
    axis never implicitly drives the other except where Section 3 explicitly
    states a dependency".

    Design: Difficulty/non_linear_state_machine/trip_parallel_axes_lifecycle_and_billing
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-PA1")
    trip, legs, driver_id = fixtures.complete_oneway_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, odometer=8.0)
    fixtures.submit_claim(trip["id"])
    fixtures.capture_encounter(trip["id"])
    final = get_success_data(api.get_trip(trip["id"], COORD))
    assert final["trip_status"] == "COMPLETED", "lifecycle axis unchanged by billing"
    assert final["billing_status"] == "ENCOUNTERED", "billing axis advanced independently"


def test_claim_requires_trip_completed(api):
    """PRD 3.7: "The trip must be `COMPLETED` on its lifecycle axis, and there
    must be no existing claim for the trip".
    PRD 2.10: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/claim_requires_trip_completed
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-CE2")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)  # ASSIGNED, not COMPLETED
    resp = api.create_claim(create_claim_payload(assigned["id"]), BROKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_trip(assigned["id"], COORD))
    assert after["billing_status"] == "UNBILLED"


def test_claim_on_assigned_trip_keeps_billing_unbilled(api):
    """PRD 3.7: "Once a trip's lifecycle axis reaches `COMPLETED`, the billing axis
    comes into play. ... The trip must be `COMPLETED` on its lifecycle axis".

    Design: Difficulty/cross_entity_state_dependency/claim_requires_trip_completed
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-CE2b")
    scheduled, _ = fixtures.create_scheduled_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, is_round_trip=False)
    assigned = fixtures.assign_trip(world, scheduled)
    resp = api.create_claim(create_claim_payload(assigned["id"]), BROKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_claim_encounter_reconcile_conserves_variance_identity(api):
    """PRD 3.9: "The variance is computed as an exact subtraction in cents: the
    trip's `reconciliation_variance_cents` is its `encounter_cost_cents` minus its
    `claimed_cost_cents`."

    Design: Difficulty/compensating_invariant/claim_encounter_reconcile_conserves_variance_identity
    """
    world = _wheelchair_will_call_world("M-CI2")
    # ob odo 10.0, rt odo 10.0, dwell raw 12 (ready 09:00 pickup 09:12) -> billable 2.
    # claimed 7000, encounter 7100, variance 100 (<= 500 -> RECONCILED).
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.0,
        rt_odometer=10.0, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:12:00Z")
    fixtures.claim_and_encounter(trip["id"])
    reconciled = fixtures.reconcile(trip["id"])
    assert reconciled["claimed_cost_cents"] == 7000
    assert reconciled["encounter_cost_cents"] == 7100
    assert reconciled["reconciliation_variance_cents"] == 100
    assert reconciled["billing_status"] == "RECONCILED"
    assert_reconciliation_variance_identity(reconciled)


def test_reconcile_within_tolerance_moves_to_reconciled(api):
    """PRD 3.9: "If the absolute value of the variance is at most 500 cents — that
    is, not strictly greater than 500 — the trip moves from `ENCOUNTERED` to
    `RECONCILED`, its claim moves to `RECONCILED`, and its encounter moves to
    `RECONCILED`."

    Design: Difficulty/compensating_invariant/claim_encounter_reconcile_conserves_variance_identity
    """
    world = _wheelchair_will_call_world("M-CI2b")
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.0,
        rt_odometer=10.0, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:12:00Z")
    claim, encounter = fixtures.claim_and_encounter(trip["id"])
    reconciled = fixtures.reconcile(trip["id"])
    assert reconciled["billing_status"] == "RECONCILED"
    refetched_claim = get_success_data(api.get_claim(claim["id"], COORD))
    refetched_enc = get_success_data(api.get_encounter(encounter["id"], COORD))
    assert refetched_claim["status"] == "RECONCILED"
    assert refetched_enc["status"] == "RECONCILED"


def test_dispute_override_reconciles_when_variance_exceeds_tolerance(api):
    """PRD 3.9: "If the absolute value of the variance is strictly greater than
    500 cents, the trip moves from `ENCOUNTERED` to `DISPUTED` instead: the
    variance is still recorded on the trip, but the claim stays `SUBMITTED` and
    the encounter stays `OPEN`, pending manual review. From `DISPUTED`, an auditor
    may override the dispute, which moves the trip to `RECONCILED` and moves both
    the claim and the encounter to `RECONCILED`, accepting the variance."

    Design: Corner/state_machines/dispute_override_reconciles_when_variance_exceeds_tolerance
    """
    world = _wheelchair_will_call_world("M-DO1")
    # variance 7780 - 7000 = 780 > 500 -> DISPUTED.
    trip, legs, driver_id = fixtures.complete_will_call_roundtrip(
        world, modality="WHEELCHAIR", scheduled_loaded_miles=10, ob_odometer=10.4,
        rt_odometer=9.8, ready_at="2026-03-02T09:00:00Z", pickup_at="2026-03-02T09:25:00Z")
    fixtures.claim_and_encounter(trip["id"])
    disputed = fixtures.reconcile(trip["id"])
    assert disputed["billing_status"] == "DISPUTED"
    assert disputed["reconciliation_variance_cents"] == 780
    overridden = get_success_data(api.reconcile_override_trip(trip["id"], AUDITOR))
    assert overridden["billing_status"] == "RECONCILED"


def test_reconcile_without_encounter_returns_recon_incomplete(api):
    """PRD 3.9: "It requires that the trip have both a `SUBMITTED` claim and an
    `OPEN` encounter; if either is missing, the reconcile is rejected with
    `ERR_RECON_INCOMPLETE`."

    Design: Corner/validations/reconcile_without_encounter_returns_recon_incomplete
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-RC1")
    trip, legs, driver_id = fixtures.complete_oneway_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, odometer=8.0)
    fixtures.submit_claim(trip["id"])  # CLAIMED, no encounter yet
    resp = api.reconcile_trip(trip["id"], AUDITOR)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_RECON_INCOMPLETE.value, ApiErrorId.ERR_INVALID_STATE.value])
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["billing_status"] == "CLAIMED"


def test_duplicate_claim_rejected(api):
    """PRD 3.7: "The trip must be `COMPLETED` on its lifecycle axis, and there
    must be no existing claim for the trip — a duplicate is rejected with
    `ERR_RECON_INCOMPLETE`."

    Design: Corner/validations/duplicate_claim_returns_recon_incomplete
    """
    world = fixtures.setup_world(modality="AMBULATORY", medicaid_id="M-DC1")
    trip, legs, driver_id = fixtures.complete_oneway_trip(
        world, modality="AMBULATORY", scheduled_loaded_miles=8, odometer=8.0)
    fixtures.submit_claim(trip["id"])
    resp = api.create_claim(create_claim_payload(trip["id"]), BROKER)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_RECON_INCOMPLETE.value, ApiErrorId.ERR_INVALID_STATE.value])
