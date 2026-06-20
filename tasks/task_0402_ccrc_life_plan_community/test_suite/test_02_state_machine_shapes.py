"""Non-linear state-machine and transitive-cascade tests (PRD §3.2-§3.7).

Queue (A) difficulty instances for the branching Residency terminate fork, the
back-stepping care continuum, the depth-3 terminate→release→free cascade, and
the depth-2 waitlist place→reserve→re-rank cascade.
"""
from test_helpers import (
    activate_residency,
    advance_clock,
    get_residency,
    get_unit,
    get_waitlist_entry,
    hold_bed,
    list_refund_disbursements,
    occupy_bed,
    propose_and_apply_transition,
    reserve_residency_via_assign,
    setup_active_residency,
    setup_community_and_plan,
    setup_two_waitlisted_for_independent,
    terminate_residency,
    AD,
)
from test_helpers.api_client import api_client
from test_helpers import validate_success


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / residency_terminate_branches_voluntary_vs_death
# ─────────────────────────────────────────────────────────────────────────────

def test_terminate_death_branch_reaches_terminated_death_state(api):
    """PRD §3.7: "A `VOLUNTARY` reason drives the residency to `TERMINATED_VOLUNTARY`
    and a `DEATH` reason to `TERMINATED_DEATH`; both branches perform the identical
    cascade and differ only in how the refund is sized."

    NINETY_REFUNDABLE plan, G=10_000_000, m=5: the DEATH branch reaches
    TERMINATED_DEATH and pays the full ninety-percent floor 9_000_000.

    Design: Difficulty/non_linear_state_machine/residency_terminate_branches_voluntary_vs_death
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Willow",
        plan_overrides={
            "name": "Ninety",
            "contract_type": "TYPE_C",
            "entrance_fee_cents": 10_000_000,
            "refund_plan": "NINETY_REFUNDABLE",
            "monthly_service_fee_cents": 300_000,
            "second_person_fee_cents": 0,
            "declining_monthly_bps": 200,
        },
    )
    advance_clock(community["id"], 5)
    fresh = get_residency(active["id"])
    terminated = terminate_residency(fresh["id"], "DEATH", fresh["version"])
    assert terminated["status"] == "TERMINATED_DEATH", (
        f"DEATH reason must reach TERMINATED_DEATH, got {terminated['status']}"
    )
    refund = list_refund_disbursements(fresh["id"])[0]
    assert refund["refundable_cents"] == 9_000_000, (
        f"NINETY DEATH floor must be 9_000_000, got {refund['refundable_cents']}"
    )


def test_terminate_voluntary_branch_reaches_terminated_voluntary_state(api):
    """PRD §3.7: "A `VOLUNTARY` reason drives the residency to `TERMINATED_VOLUNTARY`
    and a `DEATH` reason to `TERMINATED_DEATH`".

    Same NINETY_REFUNDABLE plan, m=5: the VOLUNTARY branch reaches the distinct
    TERMINATED_VOLUNTARY terminal state (not TERMINATED_DEATH).

    Design: Difficulty/non_linear_state_machine/residency_terminate_branches_voluntary_vs_death
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Willow2",
        plan_overrides={
            "name": "Ninety",
            "contract_type": "TYPE_C",
            "entrance_fee_cents": 10_000_000,
            "refund_plan": "NINETY_REFUNDABLE",
            "monthly_service_fee_cents": 300_000,
            "second_person_fee_cents": 0,
            "declining_monthly_bps": 200,
        },
    )
    advance_clock(community["id"], 5)
    fresh = get_residency(active["id"])
    terminated = terminate_residency(fresh["id"], "VOLUNTARY", fresh["version"])
    assert terminated["status"] == "TERMINATED_VOLUNTARY", (
        f"VOLUNTARY reason must reach TERMINATED_VOLUNTARY, got {terminated['status']}"
    )
    assert terminated["status"] != "TERMINATED_DEATH"


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / care_transition_continuum_step_back_toward_independent
# ─────────────────────────────────────────────────────────────────────────────

def test_care_transition_back_step_assisted_to_independent_applies(api):
    """PRD §3.4: "the requested `to_level` must be exactly one step away from
    `from_level` along the chain that runs `INDEPENDENT` to `ASSISTED` to `SKILLED`,
    in either direction, with no skipping a level".

    A residency at ASSISTED applies a transition back to INDEPENDENT (the reverse
    step); the transition reaches APPLIED.

    Design: Difficulty/non_linear_state_machine/care_transition_continuum_step_back_toward_independent
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Oak",
        plan_overrides={"name": "Step Plan", "second_person_fee_cents": 0},
    )
    propose_and_apply_transition(active["id"], "ASSISTED")
    # back-step ASSISTED → INDEPENDENT
    proposed = validate_success(api_client.create_care_transition(
        {"residency_id": active["id"], "to_level": "INDEPENDENT"},
        _CC(),
    ), expected_status=201)
    applied = validate_success(
        api_client.apply_care_transition(proposed["id"], _CC()),
    )
    assert applied["status"] == "APPLIED", (
        f"back-step transition must reach APPLIED, got {applied['status']}"
    )


def test_care_transition_back_step_sets_residency_care_level_independent(api):
    """PRD §3.4: "A successful apply sets the residency's `care_level` to `to_level`".

    After applying the back-step ASSISTED→INDEPENDENT, the parent residency's
    care_level is INDEPENDENT again.

    Design: Difficulty/non_linear_state_machine/care_transition_continuum_step_back_toward_independent
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Oak2",
        plan_overrides={"name": "Step Plan", "second_person_fee_cents": 0},
    )
    propose_and_apply_transition(active["id"], "ASSISTED")
    propose_and_apply_transition(active["id"], "INDEPENDENT")
    fresh = get_residency(active["id"])
    assert fresh["care_level"] == "INDEPENDENT", (
        f"care_level after back-step must be INDEPENDENT, got {fresh['care_level']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / terminate_releases_bed_then_frees_skilled_unit_depth3
# ─────────────────────────────────────────────────────────────────────────────

def test_terminate_releases_occupied_bed_reservation(api):
    """PRD §3.7: "every bed reservation for the residency that is `HELD` or
    `OCCUPIED` is set to `RELEASED`, and any skilled unit that was `OCCUPIED` through
    one of those reservations has its `status` returned to `AVAILABLE`."

    Depth-3 hop 2: terminate → the OCCUPIED BedReservation becomes RELEASED.

    Design: Difficulty/transitive_cascade/terminate_releases_bed_then_frees_skilled_unit_depth3
    """
    community, _ind, skilled_unit, brid, residency = _terminate_with_occupied_bed("Pine")
    br = validate_success(api_client.get_bed_reservation(brid, _AD()))
    assert br["status"] == "RELEASED", (
        f"OCCUPIED bed reservation must be RELEASED on terminate, got {br['status']}"
    )


def test_terminate_cascade_frees_skilled_unit_via_release(api):
    """PRD §3.7: "any skilled unit that was `OCCUPIED` through one of those
    reservations has its `status` returned to `AVAILABLE`."

    Depth-3 hop 3: the bed release (caused by terminate) frees the SKILLED Unit
    (status OCCUPIED → AVAILABLE), caused by the prior hop, not directly by
    terminate.

    Design: Difficulty/transitive_cascade/terminate_releases_bed_then_frees_skilled_unit_depth3
    """
    community, _ind, skilled_unit, brid, residency = _terminate_with_occupied_bed("Pine2")
    unit = get_unit(skilled_unit["id"])
    assert unit["status"] == "AVAILABLE", (
        f"skilled unit must be freed to AVAILABLE by the cascade, got {unit['status']}"
    )


def _terminate_with_occupied_bed(community_name: str):
    """ACTIVE residency in an INDEPENDENT unit with an OCCUPIED skilled bed, then
    terminated VOLUNTARY. Returns (community, ind_unit, skilled_unit, brid,
    pre_terminate_residency)."""
    community, plan = setup_community_and_plan(
        community_name=community_name,
        plan_overrides={
            "name": "Casc Plan", "contract_type": "TYPE_A",
            "second_person_fee_cents": 0,
        },
    )
    ind_unit = _create_unit(community["id"], "P-IND", "INDEPENDENT")
    skilled_unit = _create_unit(community["id"], "P-SK", "SKILLED", bed_capacity=1)
    reserved = reserve_residency_via_assign(community, plan, ind_unit)
    active = activate_residency(reserved)
    br = hold_bed(active["id"], skilled_unit["id"], 5)
    occupy_bed(br["id"])
    fresh = get_residency(active["id"])
    terminate_residency(fresh["id"], "VOLUNTARY", fresh["version"])
    return community, ind_unit, skilled_unit, br["id"], fresh


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / waitlist_place_reserves_residency_and_reranks_depth2
# ─────────────────────────────────────────────────────────────────────────────

def test_waitlist_place_reserves_parent_residency(api):
    """PRD §3.3: "On a successful placement, the residency's `unit_id` is set to that
    unit, the unit's `status` becomes `OCCUPIED`, the entry becomes `PLACED`, the
    residency becomes `RESERVED`".

    Depth-2 hop 1: placing the head entry (→ PLACED) drives its parent residency
    to RESERVED.

    Design: Difficulty/transitive_cascade/waitlist_place_reserves_residency_and_reranks_depth2
    """
    community, plan, unit, r1, w1, w2 = setup_two_waitlisted_for_independent("Elm")
    placed = validate_success(api_client.place_waitlist_entry(
        w1["id"], {"unit_id": unit["id"]}, _AD(),
    ))
    assert placed["status"] == "PLACED", (
        f"head entry must reach PLACED, got {placed['status']}"
    )
    r1_after = get_residency(r1["id"])
    assert r1_after["status"] == "RESERVED", (
        f"parent residency must become RESERVED, got {r1_after['status']}"
    )


def test_waitlist_place_reranks_remaining_entry_to_head(api):
    """PRD §3.3: "every remaining `PENDING` entry for the same community and
    `target_care_level` is re-ranked so that the gap left by the placed entry is
    closed."

    Depth-2 hop 2: after placing rank-1 w1, the previously rank-2 entry w2 is
    re-ranked to rank 1.

    Design: Difficulty/transitive_cascade/waitlist_place_reserves_residency_and_reranks_depth2
    """
    community, plan, unit, r1, w1, w2 = setup_two_waitlisted_for_independent("Elm2")
    validate_success(api_client.place_waitlist_entry(
        w1["id"], {"unit_id": unit["id"]}, _AD(),
    ))
    w2_after = get_waitlist_entry(w2["id"])
    assert w2_after["rank"] == 1, (
        f"remaining PENDING entry must re-rank to 1, got {w2_after['rank']}"
    )


# ─── local header builders (avoid importing the same name twice) ────────────

def _AD():
    from test_helpers import make_admissions_director_headers
    return make_admissions_director_headers()


def _CC():
    from test_helpers import make_care_coordinator_headers
    return make_care_coordinator_headers()


def _create_unit(community_id, unit_number, care_level, **overrides):
    from test_helpers import create_unit
    return create_unit(community_id, unit_number=unit_number,
                       care_level=care_level, **overrides)
