"""Bib/corral assignment, the charity fundraising gate, wave capacity, validation
priority pairs, and conserved-quantity invariants.

Covers difficulty rules dual_variant_calc (fundraising), boundary_precision_check
(fundraising equality), priority_pair_validation_conflict, resource_temporal_overlap
(wave full), compensating_invariant, and corner instances under sections
calculations and validations.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_participant_headers, assert_bib_assignment,
)
from test_helpers import fixtures as fx

RD = TEST_USERS["race_director_headers"]


# ---------------------------------------------------------------------------
# Fundraising gate: settled-only (dual variant) (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------
def test_assign_bib_blocked_when_settled_below_minimum(api):
    """PRD §3.5: "The provisional, optimistic total sums `amount_cents` over the
    registration's pledges that are either `PLEDGED` or `SETTLED` ... The final,
    settled total sums `amount_cents` over only the `SETTLED` pledges."
    PRD §3.6: "For a charity entry the assignment is gated on fundraising: the settled
    fundraising total must be at least the registration's `fundraising_minimum_cents`,
    and a shortfall is rejected with `ERR_FUNDRAISING_MINIMUM_NOT_MET`."

    Design: Difficulty/dual_variant_calc/fundraising_provisional_vs_final_diverge_on_pledge_status
    """
    # minimum 25000; pledges A=10000 PLEDGED, B=8000 PLEDGED, C=12000 SETTLED.
    # provisional (PLEDGED+SETTLED)=30000 >= 25000, but settled-only=12000 < 25000.
    event, distance, wave, participant, reg = fx.setup_confirmed_charity_registration(
        charity_fundraising_minimum_cents=25000)
    fx.add_pledge(reg, participant, 10000, donor_name="A")
    fx.add_pledge(reg, participant, 8000, donor_name="B")
    fx.add_pledge(reg, participant, 12000, donor_name="C", settle=True)
    resp = api.assign_bib(reg["id"], RD)
    validate_error(resp, ApiErrorId.ERR_FUNDRAISING_MINIMUM_NOT_MET.value)
    assert fx.get_registration_data(reg["id"])["status"] == "CONFIRMED", \
        "a blocked assign-bib must leave the registration CONFIRMED"


def test_settling_pledges_to_minimum_flips_fundraising_gate(api):
    """PRD §3.5: "The final, settled total sums `amount_cents` over only the `SETTLED`
    pledges."
    PRD §3.6: "For a charity entry the assignment is gated on fundraising: the settled
    fundraising total must be at least the registration's `fundraising_minimum_cents`,
    and a shortfall is rejected with `ERR_FUNDRAISING_MINIMUM_NOT_MET`."

    Design: Difficulty/dual_variant_calc/fundraising_provisional_vs_final_diverge_on_pledge_status
    """
    # Same pledges (A=10000 PLEDGED, B=8000 PLEDGED, C=12000 SETTLED) gate-blocked on
    # settled-only 12000. Settling A and B raises settled to 30000 >= 25000, so the
    # gate now passes — the SETTLED-only variant, not the optimistic PLEDGED+SETTLED
    # total, is what governs.
    event, distance, wave, participant, reg = fx.setup_confirmed_charity_registration(
        charity_fundraising_minimum_cents=25000)
    pa = fx.add_pledge(reg, participant, 10000, donor_name="A")
    pb = fx.add_pledge(reg, participant, 8000, donor_name="B")
    fx.add_pledge(reg, participant, 12000, donor_name="C", settle=True)
    # Settle A and B so SETTLED total = 30000.
    h = make_participant_headers(participant["id"])
    validate_success(api.settle_pledge(pa["id"], h))
    validate_success(api.settle_pledge(pb["id"], h))
    resp = api.assign_bib(reg["id"], RD)
    bib = validate_success(resp, expected_status=201)
    assert fx.get_registration_data(reg["id"])["status"] == "BIB_ASSIGNED", \
        "once settled total clears the minimum, assign-bib must succeed"


def test_assign_bib_allowed_when_settled_meets_minimum_exactly(api):
    """PRD §3.6: "the settled fundraising total must be at least the registration's
    `fundraising_minimum_cents`, and a shortfall is rejected with
    `ERR_FUNDRAISING_MINIMUM_NOT_MET`."
    PRD §3.6: "The `bib_number` is the next sequential integer within the distance,
    starting at 100".

    Design: Difficulty/boundary_precision_check/fundraising_minimum_exact_equal_passes_assign_bib
    """
    # settled exactly 25000 == minimum; gate is "at least", so equality passes.
    event, distance, wave, participant, reg = fx.setup_confirmed_charity_registration(
        charity_fundraising_minimum_cents=25000)
    fx.add_pledge(reg, participant, 25000, donor_name="A", settle=True)
    resp = api.assign_bib(reg["id"], RD)
    bib = validate_success(resp, expected_status=201)
    assert_bib_assignment(bib)
    assert fx.get_registration_data(reg["id"])["status"] == "BIB_ASSIGNED", \
        "meeting the minimum exactly must allow BIB_ASSIGNED"
    assert bib["corral"] == "A", f"first bib in an empty wave is corral A, got {bib['corral']}"
    assert bib["bib_number"] == 100, f"first bib number is 100, got {bib['bib_number']}"


def test_assign_bib_blocked_one_cent_below_minimum(api):
    """PRD §3.6: "the settled fundraising total must be at least the registration's
    `fundraising_minimum_cents`, and a shortfall is rejected with
    `ERR_FUNDRAISING_MINIMUM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/fundraising_minimum_exact_equal_passes_assign_bib
    """
    # settled 24999 == minimum-1 is a shortfall (boundary X-1): must be rejected.
    event, distance, wave, participant, reg = fx.setup_confirmed_charity_registration(
        charity_fundraising_minimum_cents=25000)
    fx.add_pledge(reg, participant, 24999, donor_name="A", settle=True)
    resp = api.assign_bib(reg["id"], RD)
    validate_error(resp, ApiErrorId.ERR_FUNDRAISING_MINIMUM_NOT_MET.value)
    assert fx.get_registration_data(reg["id"])["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Corral seeding by qualifying time (corner: calculations)
# ---------------------------------------------------------------------------
def test_corral_seeding_packs_by_qualifying_time(api):
    """PRD §3.6: "ordering them first by ascending `qualifying_time_seconds` ... With
    ranks counted from 0, the corral index is the rank divided by the wave's
    `corral_capacity` discarding any remainder, and the corral letter is the letter at
    that offset from `A`".
    PRD §3.6: "The `bib_number` is the next sequential integer within the distance,
    starting at 100 and handed out to bib assignments in ascending `created_at` order."

    Design: Corner/calculations/corral_seeding_packs_by_qualifying_time
    """
    # corral_capacity 2, seeds 1200 and 1500: both rank into corral A; bibs 100, 101.
    event, distance, wave = fx.setup_open_event(capacity_total=50, corral_capacity=2)
    p1 = fx.create_participant()
    p2 = fx.create_participant()
    reg1 = fx.create_registration(event, distance, wave, p1, qualifying_time_seconds=1200)
    reg1 = fx.confirm_registration(reg1, distance, p1)
    reg2 = fx.create_registration(event, distance, wave, p2, qualifying_time_seconds=1500)
    reg2 = fx.confirm_registration(reg2, distance, p2)
    bib1 = validate_success(api.assign_bib(reg1["id"], RD), expected_status=201)
    bib2 = validate_success(api.assign_bib(reg2["id"], RD), expected_status=201)
    assert bib1["corral"] == "A" and bib1["bib_number"] == 100, \
        f"faster runner: corral A bib 100, got {bib1['corral']}/{bib1['bib_number']}"
    assert bib2["corral"] == "A" and bib2["bib_number"] == 101, \
        f"second runner: corral A bib 101, got {bib2['corral']}/{bib2['bib_number']}"


# ---------------------------------------------------------------------------
# Wave full (difficulty: resource_temporal_overlap)
# ---------------------------------------------------------------------------
def test_wave_full_rejects_bib_assignment(api):
    """PRD §3.6: "The requested wave must also have room — its `assigned_count` must be
    strictly below its `wave_capacity` — and a full wave is rejected with
    `ERR_WAVE_FULL`."

    Design: Difficulty/resource_temporal_overlap/wave_aggregate_capacity_full_rejects_bib_assignment
    """
    # wave_capacity 1, filled by P1's bib; P2 CONFIRMED then assign-bib -> ERR_WAVE_FULL.
    event, distance, wave = fx.setup_open_event(capacity_total=50, wave_capacity=1)
    p1 = fx.create_participant()
    reg1 = fx.create_registration(event, distance, wave, p1)
    reg1 = fx.confirm_registration(reg1, distance, p1)
    validate_success(api.assign_bib(reg1["id"], RD), expected_status=201)
    p2 = fx.create_participant()
    reg2 = fx.create_registration(event, distance, wave, p2)
    reg2 = fx.confirm_registration(reg2, distance, p2)
    resp = api.assign_bib(reg2["id"], RD)
    validate_error(resp, ApiErrorId.ERR_WAVE_FULL.value)
    assert fx.get_registration_data(reg2["id"])["status"] == "CONFIRMED", \
        "a wave-full assign-bib must leave the registration CONFIRMED"


def test_wave_with_remaining_room_accepts_bib_assignment(api):
    """PRD §3.6: "The requested wave must also have room — its `assigned_count` must be
    strictly below its `wave_capacity` — and a full wave is rejected with
    `ERR_WAVE_FULL`."
    PRD §3.6: "Assignment increments the wave's `assigned_count` and bumps
    `Wave.version`."

    Design: Difficulty/resource_temporal_overlap/wave_aggregate_capacity_full_rejects_bib_assignment
    """
    # wave_capacity 2, one bib already assigned: assigned_count 1 < 2, so the second
    # assign-bib still has room and succeeds, taking assigned_count to 2.
    event, distance, wave = fx.setup_open_event(capacity_total=50, wave_capacity=2)
    p1 = fx.create_participant()
    reg1 = fx.create_registration(event, distance, wave, p1)
    reg1 = fx.confirm_registration(reg1, distance, p1)
    validate_success(api.assign_bib(reg1["id"], RD), expected_status=201)
    p2 = fx.create_participant()
    reg2 = fx.create_registration(event, distance, wave, p2)
    reg2 = fx.confirm_registration(reg2, distance, p2)
    validate_success(api.assign_bib(reg2["id"], RD), expected_status=201)
    assert fx.get_wave_data(wave["id"])["assigned_count"] == 2, \
        "second assignment within capacity must raise assigned_count to 2"


# ---------------------------------------------------------------------------
# Priority pair: safety (fundraising) outranks temporal (wave full)
# (difficulty: priority_pair_validation_conflict)
# ---------------------------------------------------------------------------
def test_fundraising_minimum_outranks_wave_full(api):
    """PRD §2.10: "Only after all of these pass does the system evaluate the
    domain-specific business rules described throughout §3 — temporal windows,
    pricing-tier availability, fundraising minimums, wave and distance capacity, the
    concurrency version check, packet eligibility, pricing-tier uniqueness, timing
    well-ordering, and deferral target validity".
    PRD §3.6: "For a charity entry the assignment is gated on fundraising: the settled
    fundraising total must be at least the registration's `fundraising_minimum_cents`,
    and a shortfall is rejected with `ERR_FUNDRAISING_MINIMUM_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_fundraising_minimum_outranks_wave_full
    """
    # wave_capacity 1 filled by a STANDARD bib; CHARITY P2 confirmed with only
    # 10000 PLEDGED (settled 0). assign-bib must report the fundraising error, which
    # §2.10 lists ahead of wave capacity.
    event, distance, wave = fx.setup_open_event(
        capacity_total=50, wave_capacity=1, charity_capacity=10,
        charity_fundraising_minimum_cents=25000)
    p1 = fx.create_participant()
    reg1 = fx.create_registration(event, distance, wave, p1)
    reg1 = fx.confirm_registration(reg1, distance, p1)
    validate_success(api.assign_bib(reg1["id"], RD), expected_status=201)  # fills the wave

    p2 = fx.create_participant()
    reg2 = fx.create_registration(event, distance, wave, p2, entry_type="CHARITY")
    reg2 = fx.confirm_registration(reg2, distance, p2)
    fx.add_pledge(reg2, p2, 10000, donor_name="A")  # PLEDGED only, settled 0
    resp = api.assign_bib(reg2["id"], RD)
    validate_error(resp, ApiErrorId.ERR_FUNDRAISING_MINIMUM_NOT_MET.value)
    assert fx.get_registration_data(reg2["id"])["status"] == "CONFIRMED"


def test_fundraising_shortfall_reports_safety_error_even_with_wave_room(api):
    """PRD §3.6: "For a charity entry the assignment is gated on fundraising: the
    settled fundraising total must be at least the registration's
    `fundraising_minimum_cents`, and a shortfall is rejected with
    `ERR_FUNDRAISING_MINIMUM_NOT_MET`. The requested wave must also have room — its
    `assigned_count` must be strictly below its `wave_capacity` — and a full wave is
    rejected with `ERR_WAVE_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_fundraising_minimum_outranks_wave_full
    """
    # CHARITY short on fundraising (settled 0) but the wave has ample room: the
    # fundraising safety error is the one reported, never ERR_WAVE_FULL.
    event, distance, wave, participant, reg = fx.setup_confirmed_charity_registration(
        charity_fundraising_minimum_cents=25000, wave_capacity=50)
    fx.add_pledge(reg, participant, 10000, donor_name="A")  # PLEDGED only
    resp = api.assign_bib(reg["id"], RD)
    validate_error(resp, ApiErrorId.ERR_FUNDRAISING_MINIMUM_NOT_MET.value)


# ---------------------------------------------------------------------------
# Conserved-quantity invariants (difficulty: compensating_invariant)
# ---------------------------------------------------------------------------
def test_confirmed_count_invariant_after_confirm_then_cancel(api):
    """PRD §2.6: "The `confirmed_count` is the number of registrations on the distance
    whose status is `CONFIRMED`, `BIB_ASSIGNED`, or `FINISHED`."
    PRD §3.4: "If the cancelled registration had been `CONFIRMED` or `BIB_ASSIGNED`,
    the distance's `confirmed_count` is decremented (and `charity_confirmed_count` for
    a charity entry) and `Distance.version` is bumped".

    Design: Difficulty/compensating_invariant/distance_confirmed_count_invariant_after_confirm_then_cancel
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(capacity_total=5)
    assert fx.get_distance_data(distance["id"])["confirmed_count"] == 1
    fx.api_cancel(reg, participant)
    dist = fx.get_distance_data(distance["id"])
    assert dist["confirmed_count"] == 0, \
        f"confirm(+1) then cancel(-1) must restore confirmed_count to 0, got {dist['confirmed_count']}"
    assert fx.get_registration_data(reg["id"])["status"] == "CANCELLED"


def test_confirmed_count_settles_to_one_after_two_confirms_one_cancel(api):
    """PRD §2.6: "The `confirmed_count` is the number of registrations on the distance
    whose status is `CONFIRMED`, `BIB_ASSIGNED`, or `FINISHED`."
    PRD §3.4: "If the cancelled registration had been `CONFIRMED` or `BIB_ASSIGNED`,
    the distance's `confirmed_count` is decremented".

    Design: Difficulty/compensating_invariant/distance_confirmed_count_invariant_after_confirm_then_cancel
    """
    # Two confirms (+2) then one cancel (-1) -> confirmed_count == 1, no drift.
    event, distance, wave = fx.setup_open_event(capacity_total=5)
    p1 = fx.create_participant()
    p2 = fx.create_participant()
    reg1 = fx.confirm_registration(fx.create_registration(event, distance, wave, p1), distance, p1)
    reg2 = fx.confirm_registration(fx.create_registration(event, distance, wave, p2), distance, p2)
    assert fx.get_distance_data(distance["id"])["confirmed_count"] == 2
    fx.api_cancel(reg1, p1)
    assert fx.get_distance_data(distance["id"])["confirmed_count"] == 1, \
        "two confirms then one cancel must leave confirmed_count at exactly 1"


def test_wave_assigned_count_invariant_after_assign_then_cancel(api):
    """PRD §2.6: "a wave's `assigned_count` counts the bib assignments referencing it."
    PRD §3.4: "if it had been `BIB_ASSIGNED`, the associated `BibAssignment` is
    deleted, the wave's `assigned_count` is decremented, and `Wave.version` is bumped".

    Design: Difficulty/compensating_invariant/wave_assigned_count_invariant_after_assign_then_cancel
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(
        capacity_total=50, wave_capacity=5)
    validate_success(api.assign_bib(reg["id"], RD), expected_status=201)
    assert fx.get_wave_data(wave["id"])["assigned_count"] == 1
    fx.api_cancel(reg, participant)
    wv = fx.get_wave_data(wave["id"])
    assert wv["assigned_count"] == 0, \
        f"assign(+1) then cancel(-1, bib deleted) must restore assigned_count to 0, got {wv['assigned_count']}"
    assert fx.get_registration_data(reg["id"])["status"] == "CANCELLED"


def test_wave_assigned_count_settles_to_one_after_two_assigns_one_cancel(api):
    """PRD §2.6: "a wave's `assigned_count` counts the bib assignments referencing it."
    PRD §3.4: "if it had been `BIB_ASSIGNED`, the associated `BibAssignment` is
    deleted, the wave's `assigned_count` is decremented".

    Design: Difficulty/compensating_invariant/wave_assigned_count_invariant_after_assign_then_cancel
    """
    # Two assigns (+2) then one cancel of a BIB_ASSIGNED reg (-1) -> assigned_count 1.
    event, distance, wave = fx.setup_open_event(capacity_total=50, wave_capacity=5)
    p1 = fx.create_participant()
    p2 = fx.create_participant()
    reg1 = fx.confirm_registration(fx.create_registration(event, distance, wave, p1), distance, p1)
    reg2 = fx.confirm_registration(fx.create_registration(event, distance, wave, p2), distance, p2)
    validate_success(api.assign_bib(reg1["id"], RD), expected_status=201)
    validate_success(api.assign_bib(reg2["id"], RD), expected_status=201)
    assert fx.get_wave_data(wave["id"])["assigned_count"] == 2
    fx.api_cancel(reg1, p1)
    assert fx.get_wave_data(wave["id"])["assigned_count"] == 1, \
        "two assigns then one cancel must leave assigned_count at exactly 1"
