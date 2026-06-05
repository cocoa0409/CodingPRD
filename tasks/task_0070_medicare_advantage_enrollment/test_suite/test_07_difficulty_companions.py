"""Second tests for each depth (Difficulty) instance.

Each test here pairs with a primary test in test_01-test_05, asserting a distinct
PRD-derivable facet of the same difficulty instance (the complementary boundary
side, an additional cascade member, the alternate calculation variant, or a
side-effect not asserted by the primary).
"""
from test_helpers import (
    validate_success, validate_error, set_clock, create_beneficiary, create_plan,
    create_period, setup_beneficiary_with_active_part_b, setup_confirmed_part_c,
    setup_confirmed_mapd_with_bundled_part_d,
    setup_active_part_d, setup_active_part_d_with_total, setup_pending_part_d,
    post_claim, file_part_c, confirm_part_c, read_beneficiary_version,
    create_part_b_enrollment_payload, create_part_c_enrollment_payload, confirm_part_c_payload,
    create_part_d_enrollment_payload, create_drug_claim_payload, create_medigap_policy_payload,
    create_penalty_assessment_payload, create_enrollment_period_payload,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["enrollment_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── dual_variant_calc (companion) ────────────────────────────────────────────

def test_partd_drug_enrollment_uncovered_months_thirteen(api):
    """PRD §3.7: "if that is null - the beneficiary never held creditable drug coverage
    - the anchor instead becomes the last instant of the beneficiary's IEP window, that
    is, the window_end of their IEP EnrollmentPeriod."
    PRD §3.7: "The count is the number of whole calendar months strictly between the
    anchor's month and the effective month: take the effective year times twelve plus
    the effective month index, subtract the anchor year times twelve plus the anchor
    month index, then subtract one more, and floor the result at zero so it can never
    go negative."

    Design: Difficulty/dual_variant_calc/partd_lep_drug_enrollment_vs_partb_lep_penalty_assessment
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d(confirm_clock="2026-01-15T00:00:00.000Z")
    # Anchor = IEP window_end (Nov 2024), effective month Jan 2026 -> 13 uncovered months.
    assert pde["uncovered_months"] == 13
    assert pde["lep_premium_cents"] == 450


def test_partd_assessment_variant_takes_uncovered_months_verbatim(api):
    """PRD §3.10: "the penalty uses the same Part D formula as drug confirmation but
    with the caller-supplied uncovered_months taken verbatim rather than computed: one
    percent of the national base beneficiary premium of 3,470 cents, multiplied by the
    uncovered months, rounded to the nearest dime (divide by ten, round half up,
    multiply by ten) to yield integer cents."

    Design: Difficulty/dual_variant_calc/partd_lep_variant_from_confirm_vs_from_assessment
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="VariantB")
    # uncovered_months=7 supplied verbatim: 0.01*3470*7=242.9 -> round(24.29)=24 dimes -> 240c.
    pa = validate_success(api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_D", 7), COMPLIANCE), 201)
    assert pa["uncovered_months"] == 7
    assert pa["monthly_penalty_cents"] == 240


# ─── combinatorial_formula (companion) ────────────────────────────────────────

def test_deductible_phase_claim_full_100_percent(api):
    """PRD §3.8: "DEDUCTIBLE phase, while T is below 54,500 cents: the member pays 100%
    of the segment."
    PRD §3.8: "A claim's phase_at_post records the phase of its very first cent."

    Design: Difficulty/combinatorial_formula/donut_hole_claim_straddles_deductible_and_initial_phases
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d()
    # A 10000c claim entirely within the deductible (T 0 -> 10000, < 54500): 100% share.
    res = api.post_drug_claim(pde["id"],
                              create_drug_claim_payload(10000, "2024-11-05T00:00:00.000Z"), ADMIN)
    claim = validate_success(res, 201)
    assert claim["phase_at_post"] == "DEDUCTIBLE"
    assert claim["member_share_cents"] == 10000


def test_single_initial_phase_claim_rounds_quarter(api):
    """PRD §3.8: "INITIAL phase, while T is at least 54,500 cents and below 503,000
    cents: the member pays 25% of the segment."
    PRD §3.8: "the member share for that segment is the segment's cents multiplied by
    25%, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/donut_hole_round_per_segment_then_sum_ordering
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d()
    post_claim(pde["id"], 54500, "2024-11-05T00:00:00.000Z")  # exactly through deductible
    # One 333c claim in INITIAL: 333*0.25=83.25 -> round_half_up -> 83.
    claim = validate_success(api.post_drug_claim(
        pde["id"], create_drug_claim_payload(333, "2024-11-06T00:00:00.000Z"), ADMIN), 201)
    assert claim["member_share_cents"] == 83


# ─── boundary_precision_check (companion: the X-1 / inside-window side) ────────

def test_icl_boundary_just_below_stays_initial(api):
    """PRD §3.8: "INITIAL phase, while T is at least 54,500 cents and below 503,000
    cents: the member pays 25% of the segment."
    PRD §3.8: "the initial-to-gap crossing occurs when T reaches 503,000 cents (at or
    above)"

    Design: Difficulty/boundary_precision_check/donut_hole_icl_boundary_initial_to_gap_crossing
    """
    set_clock("2024-11-01T00:00:00.000Z")
    # Drive T to 502999 (one below ICL); next claim's first cent is still INITIAL.
    _ben, pde = setup_active_part_d_with_total(502999)
    assert pde["total_drug_cost_cents"] == 502999
    claim = validate_success(api.post_drug_claim(
        pde["id"], create_drug_claim_payload(1, "2024-11-06T00:00:00.000Z"), ADMIN), 201)
    assert claim["phase_at_post"] == "INITIAL"


def test_medigap_application_day63_inclusive_issues(api):
    """PRD §3.9: "the clock must be at or after source_event_date and at or before
    source_event_date plus 63 days (day 63 inclusive)."

    Design: Difficulty/boundary_precision_check/medigap_gi_window_day63_inclusive_vs_day64_expired
    """
    set_clock("2026-01-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="Day63")
    gi = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-01-01T00:00:00.000Z")
    # source_event_date + 63 days = 2026-03-05 -> inside the window (day 63 inclusive).
    set_clock("2026-03-05T00:00:00.000Z")
    res = api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi["id"],
                                      "2026-03-05T00:00:00.000Z", "2027-03-05T00:00:00.000Z"),
        ADMIN)
    mp = validate_success(res, 201)
    assert mp["status"] == "ISSUED"
    assert mp["guaranteed_issue"] is True


# ─── non_linear_state_machine beneficiary (companion) ─────────────────────────

def test_fraud_hold_sets_lock_then_clear_releases(api):
    """PRD §3.1: "The hold sets enrollment_lock to true and increments version."
    PRD §3.1: "clearing sets enrollment_lock back to false and increments version."

    Design: Difficulty/non_linear_state_machine/beneficiary_branching_fraud_hold_cycle_vs_deceased_terminal
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="LockCycle")
    base_ver = ben["version"]
    held = validate_success(api.fraud_hold(ben["id"], COMPLIANCE), 200)
    assert held["enrollment_lock"] is True
    assert held["version"] == base_ver + 1
    cleared = validate_success(api.clear_hold(ben["id"], COMPLIANCE), 200)
    assert cleared["enrollment_lock"] is False
    assert cleared["version"] == base_ver + 2


# ─── transitive_cascade (companions: assert deeper-hop versioning / states) ────

def test_supersede_keeps_new_part_c_active_and_old_superseded(api):
    """PRD §3.6: "On success, confirmation enforces that a beneficiary holds at most one
    active Medicare Advantage enrollment. Any other PartCEnrollment of the same
    beneficiary currently in ACTIVE is transitioned to SUPERSEDED"

    Design: Difficulty/transitive_cascade/confirm_supersede_disenroll_bundled_mapd_depth3
    """
    set_clock("2024-06-01T00:00:00.000Z")
    # ACTIVE MAPD Part C with a bundled ACTIVE Part D, built in PRD-faithful order
    # (bundled Part D filed while the MAPD is PENDING, then both confirmed).
    ben, iep, _mapd1, _pdp, pce1, _pde = setup_confirmed_mapd_with_bundled_part_d(
        mapd_plan_overrides={"name": "MAPD Sup", "monthly_premium_cents": 0, "star_rating": 4.0},
        pdp_plan_overrides={"name": "PDP Sup", "monthly_premium_cents": 1500})

    aep = create_period(ben["id"], "AEP", aep_year=2024)
    ma2 = create_plan(name="MA Sup2", part_type="PART_C", monthly_premium_cents=0,
                      star_rating=4.5, includes_drug_coverage=False)
    set_clock("2024-11-01T00:00:00.000Z")
    pce2 = file_part_c(ben["id"], ma2["id"], aep["id"])
    pce2 = confirm_part_c(pce2["id"], ben["id"])
    # The new enrollment is ACTIVE; the superseded one's version was incremented.
    assert pce2["status"] == "ACTIVE"
    pce1_after = validate_success(api.get_part_c_enrollment(pce1["id"], ADMIN), 200)
    assert pce1_after["status"] == "SUPERSEDED"
    assert pce1_after["version"] == pce1["version"] + 1


def test_record_death_voids_filed_part_b_without_status_reset(api):
    """PRD §3.2: "Every PartBEnrollment of this beneficiary currently in FILED or ACTIVE
    transitions to VOIDED."
    PRD §3.2: "The beneficiary's own version increments once for the death event."

    Design: Difficulty/transitive_cascade/record_death_voids_partb_which_resets_part_b_status_depth2
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="FiledDeath")
    iep = create_period(ben["id"], "IEP")
    pbe = validate_success(api.create_part_b_enrollment(
        create_part_b_enrollment_payload(ben["id"], iep["id"]), ADMIN), 201)
    assert pbe["status"] == "FILED"
    # part_b_status was never ENROLLED (never activated), so it stays NONE.
    dead = validate_success(api.record_death(ben["id"], ADMIN), 200)
    assert dead["status"] == "DECEASED"
    assert dead["part_b_status"] == "NONE"
    pbe_after = validate_success(api.get_part_b_enrollment(pbe["id"], ADMIN), 200)
    assert pbe_after["status"] == "VOIDED"


# ─── cross_entity_state_dependency (companions) ───────────────────────────────

def test_drug_claim_succeeds_once_part_d_active(api):
    """PRD §3.8: "Once a Part D enrollment is ACTIVE, an EnrollmentAdmin posts a
    DrugClaim against it"
    PRD §3.8: "A claim may post only to a Part D enrollment in ACTIVE status"

    Design: Difficulty/cross_entity_state_dependency/drug_claim_requires_partd_enrollment_active
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_active_part_d()
    assert pde["status"] == "ACTIVE"
    res = api.post_drug_claim(pde["id"],
                              create_drug_claim_payload(1000, "2024-11-05T00:00:00.000Z"), ADMIN)
    claim = validate_success(res, 201)
    assert claim["phase_at_post"] == "DEDUCTIBLE"


def test_part_c_confirm_succeeds_when_plan_active(api):
    """PRD §3.6: "the plan must be ACTIVE, with a RETIRED plan triggering
    ERR_PLAN_RETIRED (HTTP 409)."
    PRD §3.6: "Confirmation advances a PENDING enrollment to ACTIVE"

    Design: Difficulty/cross_entity_state_dependency/part_c_confirm_requires_plan_active_not_retired
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _pbe = setup_beneficiary_with_active_part_b()
    ma = create_plan(name="MA Live", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    pce = file_part_c(ben["id"], ma["id"], iep["id"])
    ver = read_beneficiary_version(ben["id"])
    confirmed = validate_success(
        api.confirm_part_c_enrollment(pce["id"], confirm_part_c_payload(ver), ADMIN), 200)
    assert confirmed["status"] == "ACTIVE"


# ─── priority_pair_validation_conflict (companions: the loser fires in isolation) ─

def test_outside_window_fires_when_not_locked(api):
    """PRD §3.11: "A creation attempted while the clock lies outside that interval is
    rejected with ERR_OUTSIDE_ENROLLMENT_WINDOW (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_locked_safety_beats_outside_window_temporal
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, _pbe = setup_beneficiary_with_active_part_b()
    aep = create_period(ben["id"], "AEP", aep_year=2024)
    ma = create_plan(name="MA Y", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=3.5, includes_drug_coverage=False)
    # Not locked; clock outside the AEP window -> the temporal error fires alone.
    set_clock("2025-03-01T00:00:00.000Z")
    res = api.create_part_c_enrollment(
        create_part_c_enrollment_payload(ben["id"], ma["id"], aep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_OUTSIDE_ENROLLMENT_WINDOW.value)


def test_not_five_star_fires_when_period_type_correct(api):
    """PRD §3.11: "a SEP_5STAR period may justify a Part C enrollment only if the chosen
    plan's star_rating is exactly 5.0 ... A non-five-star plan used under a five-star
    period is rejected with ERR_NOT_FIVE_STAR (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/wrong_period_type_referential_beats_not_five_star_constraint
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, _pbe = setup_beneficiary_with_active_part_b()
    sep = create_period(ben["id"], "SEP_5STAR", aep_year=2024)
    ma = create_plan(name="MA 4star", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    # Correct period type (SEP_5STAR is valid for Part C), so NOT_FIVE_STAR fires alone.
    set_clock("2025-03-01T00:00:00.000Z")
    res = api.create_part_c_enrollment(
        create_part_c_enrollment_payload(ben["id"], ma["id"], sep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FIVE_STAR.value)


# ─── resource_temporal_overlap (companions) ───────────────────────────────────

def test_distinct_year_aep_periods_do_not_collide(api):
    """PRD §3.4: "A newly created IEP or AEP period for a beneficiary may not overlap an
    existing period of the same type for that same beneficiary. Overlap here uses
    closed-interval semantics on [window_start, window_end]"

    Design: Difficulty/resource_temporal_overlap/enrollment_period_closed_interval_adjacency_collides
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="TwoAEP")
    create_period(ben["id"], "AEP", aep_year=2024)
    # AEP 2025 (Oct 15 - Dec 7 2025) does not overlap AEP 2024 -> allowed.
    res = api.create_enrollment_period(
        ben["id"], create_enrollment_period_payload("AEP", aep_year=2025), ADMIN)
    period = validate_success(res, 201)
    assert period["period_type"] == "AEP"


def test_genuine_medigap_overlap_rejected(api):
    """PRD §3.9: "A new policy may not overlap an existing ISSUED policy of the same
    beneficiary. ... a genuine overlap is rejected with ERR_MEDIGAP_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/medigap_half_open_interval_adjacency_allowed
    """
    set_clock("2026-01-15T00:00:00.000Z")
    ben = create_beneficiary(full_name="MGOverlap")
    gi1 = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-01-10T00:00:00.000Z")
    validate_success(api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi1["id"],
                                      "2026-01-15T00:00:00.000Z", "2026-07-15T00:00:00.000Z"),
        ADMIN), 201)
    gi2 = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-03-10T00:00:00.000Z")
    set_clock("2026-03-12T00:00:00.000Z")
    # New policy starts 2026-03-15, before the first ends 2026-07-15 -> genuine overlap.
    res = api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi2["id"],
                                      "2026-03-15T00:00:00.000Z", "2026-09-15T00:00:00.000Z"),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_MEDIGAP_OVERLAP.value)


# ─── compensating_invariant (companions) ──────────────────────────────────────

def test_waived_penalty_requires_assessed_state(api):
    """PRD §3.10: "A ComplianceOfficer may waive an ASSESSED penalty, which requires the
    assessment to currently be ASSESSED, moves status to WAIVED, sets
    monthly_penalty_cents to 0, and increments the version."

    Design: Difficulty/compensating_invariant/penalty_assess_then_waive_zeroes_total_penalty_burden
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="DblWaive")
    pa = validate_success(api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_B", 24), COMPLIANCE), 201)
    # 24 // 12 = 2 periods -> 20%; 17470*20//100 = 3494c.
    assert pa["monthly_penalty_cents"] == 3494
    waived = validate_success(api.waive_penalty_assessment(pa["id"], COMPLIANCE), 200)
    assert waived["status"] == "WAIVED"
    assert waived["monthly_penalty_cents"] == 0
    # A second waive is rejected: no longer ASSESSED.
    res = api.waive_penalty_assessment(pa["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_part_b_activation_sets_enrolled_before_drop(api):
    """PRD §3.5: "On success, activation sets the beneficiary's part_b_status to
    ENROLLED, copies the enrollment's effective_date onto the beneficiary's
    part_b_effective_date"

    Design: Difficulty/compensating_invariant/partb_activate_then_drop_restores_part_b_coverage_count
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, _pbe = setup_beneficiary_with_active_part_b()
    after = validate_success(api.get_beneficiary(ben["id"], ADMIN), 200)
    assert after["part_b_status"] == "ENROLLED"
    assert after["part_b_effective_date"] is not None
