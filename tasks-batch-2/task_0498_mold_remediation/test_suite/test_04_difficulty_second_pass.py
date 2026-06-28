"""Difficulty queue (A): second test per rule instance.

Each test here is a second coverage of a difficulty rule instance, asserting a
complementary scenario of the same rule under a distinct setup.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_completed_order,
    setup_draft_clearance,
    setup_passed_clearance,
    create_project,
    create_worker,
    create_assessment,
    create_active_zone,
    create_zone,
    create_analyzed_air_sample,
    set_clock,
    get_project_version,
    create_abatement_order_payload,
    create_assignment_payload,
    create_manifest_payload,
    create_sample_payload,
    create_clearance_test_payload,
    create_permit_payload,
    create_pressure_log_payload,
    create_insurance_claim_payload,
    create_worker_payload,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]
AS = TEST_USERS["abatement_supervisor_headers"]
LT = TEST_USERS["lab_tech_headers"]
HY = TEST_USERS["hygienist_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc
# ===========================================================================
def test_claim_estimate_vs_settlement_diverge_via_deductible(api):
    """PRD §3.9: "The estimate is the labor plus disposal sum; no deductible and no
    coverage cap are applied." and PRD §3.9: "The deductible is then subtracted,
    floored at zero — the amount after deductible is the gross minus `deductible_cents`
    but never below zero."

    Same planned == removed weight (50), but a 10000-cent deductible only the
    settlement applies: estimate 50*1500 + 4000 = 79000; settlement 79000 - 10000 =
    69000. They diverge purely through the deductible asymmetry.

    Design: Difficulty/dual_variant_calc/claim_estimate_vs_settlement_diverge_on_planned_vs_actual_weight
    """
    ctx = setup_completed_order(hazard_class="MOLD", planned_weight_kg=50,
                                removed_weight_kg=50, manifest_weight_kg=50)
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-D",
                                       deductible_cents=10000,
                                       coverage_limit_cents=10_000_000), PM))
    submitted = validate_success(api.submit_insurance_claim(claim["id"], PM), 200)
    assert submitted["estimated_amount_cents"] == 79000
    assert submitted["settled_amount_cents"] == 69000
    assert submitted["estimated_amount_cents"] != submitted["settled_amount_cents"]


def test_sample_grade_vs_clearance_outcome_diverge_asbestos_limit(api):
    """PRD §3.3: "for an `AIR` sample it is the raw count divided by the sampled
    volume in liters, multiplied by 1000 ... For an air sample, a concentration below
    1000 spores per cubic meter grades `CLEAN`".
    PRD §3.8: "70 spores per cubic meter for asbestos ... `FAIL` when it is at or
    above the limit — a concentration exactly equal to the limit fails."

    Concentration 70 grades a diagnostic AIR sample CLEAN, but an ASBESTOS clearance
    at 70 == ASBESTOS_LIMIT FAILs — same number, two algorithms.

    Design: Difficulty/dual_variant_calc/sample_grade_air_vs_clearance_outcome_diverge_on_same_concentration
    """
    set_clock()
    assessor = create_worker(cert_type="ASBESTOS", full_name="Sampler")
    proj_diag = create_project(hazard_class="ASBESTOS", site_name="Diag")
    assessment = create_assessment(proj_diag["id"], assessor["id"])
    sample = create_analyzed_air_sample(proj_diag["id"], assessment["id"],
                                        raw_count=7, volume_liters=100)
    assert sample["concentration"] == 70
    assert sample["result_grade"] == "CLEAN"

    ctx = setup_completed_order(hazard_class="ASBESTOS", abatement_type="ASBESTOS",
                                lead_cert_type="ASBESTOS", with_sampler=True,
                                structure_sqft=80)
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(ctx["pid"], ctx["zid"], ctx["aid"], ctx["sampler_id"],
                                      clearance_air_count=70, clearance_volume_liters=1000), LT))
    analyzed = validate_success(api.analyze_clearance_test(clearance["id"], LT), 200)
    assert analyzed["clearance_concentration"] == 70
    assert analyzed["outcome"] == "FAIL"


# ===========================================================================
# Difficulty/combinatorial_formula
# ===========================================================================
def test_disposal_fee_asbestos_all_three_tiers_with_surcharge(api):
    """PRD §3.6: "the portion up to 100 kg is charged at 80 cents per kilogram; the
    portion above 100 kg and up to 500 kg is charged at 120 cents per kilogram; and
    the portion above 500 kg is charged at 200 cents per kilogram." and PRD §3.6: "an
    asbestos order multiplies the base fee by 1.5".

    700 kg ASBESTOS spans all three tiers: 100*80 + 400*120 + 200*200 = 96000,
    *1.5 = 144000.

    Design: Difficulty/combinatorial_formula/disposal_fee_tiered_marginal_with_asbestos_surcharge
    """
    set_clock()
    lead = create_worker(cert_type="ASBESTOS", full_name="Lead Asb")
    project = create_project(hazard_class="ASBESTOS", structure_sqft=80, site_name="Asb 700")
    zone = get_success_data(api.create_zone(
        {"project_id": project["id"], "zone_label": "Z1", "required_pressure_pa": 10}, PM))
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="ASBESTOS", planned_weight_kg=700), AS))
    manifest = validate_success(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=700), AS), 201)
    assert manifest["disposal_fee_cents"] == 144000


def test_single_manifest_crossing_tier_two_differs_from_split(api):
    """PRD §3.9: "two separate 60 kg manifests, each entirely inside the first
    disposal tier, do not produce the same total as one 120 kg manifest whose 20 kg
    crosses into the second tier."
    PRD §3.6: "the portion above 100 kg and up to 500 kg is charged at 120 cents per
    kilogram".

    The combined-weight branch the rule warns against: a single 120 kg manifest fees
    100*80 + 20*120 = 10400, which is strictly more than two 60 kg fees (4800+4800).

    Design: Difficulty/combinatorial_formula/claim_disposal_cents_per_manifest_then_sum_rounding_order
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")
    project = create_project(hazard_class="MOLD", site_name="One 120 Site")
    zone = get_success_data(api.create_zone(
        {"project_id": project["id"], "zone_label": "Z1", "required_pressure_pa": 10}, PM))
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=120), AS))
    manifest = validate_success(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=120), AS), 201)
    assert manifest["disposal_fee_cents"] == 10400
    assert manifest["disposal_fee_cents"] != 4800 + 4800


# ===========================================================================
# Difficulty/non_linear_state_machine
# ===========================================================================
def test_reopened_order_can_be_recompleted_closing_cycle(api):
    """PRD §3.5: "A `REOPENED` order is started again by an `AbatementSupervisor`,
    returning to `IN_PROGRESS`".
    PRD §3.5: "An `AbatementSupervisor` completes an `IN_PROGRESS` order, moving it to
    `COMPLETED`".

    After a FAIL reopens the order, the full cycle re-closes: REOPENED -> IN_PROGRESS
    (start) -> COMPLETED (complete with a fresh ACCEPTED manifest).

    Design: Difficulty/non_linear_state_machine/abatement_order_cyclic_reopen_on_clearance_fail
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=90, clearance_volume_liters=100)
    get_success_data(api.analyze_clearance_test(ctx["cid"], LT))  # FAIL -> REOPENED
    get_success_data(api.start_abatement_order(ctx["aid"], AS))   # REOPENED -> IN_PROGRESS
    man2 = get_success_data(api.create_manifest(
        create_manifest_payload(ctx["aid"], ctx["pid"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man2["id"], AS))
    get_success_data(api.accept_manifest(man2["id"], PM))
    recompleted = validate_success(
        api.complete_abatement_order(ctx["aid"], {"removed_weight_kg": 50}, AS), 200)
    assert recompleted["status"] == "COMPLETED"


def test_clearance_test_branching_fail_runs_divergent_cascade(api):
    """PRD §3.8: "`FAILED` is terminal for that test and triggers a four-hop cascade:
    the referenced order is reopened (`COMPLETED → REOPENED`); that order's `ACCEPTED`
    (and `SUBMITTED`) disposal manifests are voided to `VOIDED`".

    The FAIL fork (complement of the PASS fork): order REOPENED, manifest VOIDED.

    Design: Difficulty/non_linear_state_machine/clearance_test_branching_pass_vs_fail_divergent_cascades
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=90, clearance_volume_liters=100)
    analyzed = validate_success(api.analyze_clearance_test(ctx["cid"], LT), 200)
    assert analyzed["outcome"] == "FAIL"
    assert analyzed["status"] == "FAILED"
    order = validate_success(api.get_abatement_order(ctx["aid"], AS), 200)
    assert order["status"] == "REOPENED"
    manifest = validate_success(api.get_manifest(ctx["mid"], PM), 200)
    assert manifest["status"] == "VOIDED"


# ===========================================================================
# Difficulty/transitive_cascade
# ===========================================================================
def test_clearance_fail_reprices_settlement_with_larger_weight(api):
    """PRD §3.8: "the referenced order is reopened (`COMPLETED → REOPENED`); that
    order's `ACCEPTED` (and `SUBMITTED`) disposal manifests are voided to `VOIDED`;
    the insurance settlement is recomputed because the voided manifests leave the
    actuals".

    With a 200 kg order the settlement is non-zero before the fail, then drops to 0
    after the depth-3 chain removes the sole completed order and accepted manifest.

    Design: Difficulty/transitive_cascade/clearance_fail_reopen_void_manifest_reprice_settlement_depth3
    """
    ctx = setup_completed_order(hazard_class="MOLD", with_sampler=True,
                                planned_weight_kg=200, removed_weight_kg=200,
                                manifest_weight_kg=200)
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-T2",
                                       deductible_cents=0,
                                       coverage_limit_cents=100_000_000), PM))
    submitted = validate_success(api.submit_insurance_claim(claim["id"], PM), 200)
    # 200*1500 + (100*80 + 100*120) = 300000 + 20000 = 320000 (manifest fee), settled non-zero
    assert submitted["settled_amount_cents"] > 0
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(ctx["pid"], ctx["zid"], ctx["aid"], ctx["sampler_id"],
                                      clearance_air_count=90, clearance_volume_liters=100), LT))
    validate_success(api.analyze_clearance_test(clearance["id"], LT), 200)
    manifest = validate_success(api.get_manifest(ctx["mid"], PM), 200)
    assert manifest["status"] == "VOIDED"
    reclaim = validate_success(api.get_insurance_claim(claim["id"], PM), 200)
    assert reclaim["settled_amount_cents"] == 0


def test_sample_void_recomputes_finding_level_to_remaining_worst(api):
    """PRD §3.3: "the finding level is the highest-severity grade across the analyzed
    samples".
    PRD §3.3: "on success it recomputes the parent assessment's `finding_level`, then
    the project's `open_finding_count` (because the finding level may have changed),
    then the project's `posture`."

    Two ANALYZED samples (HAZARDOUS + ELEVATED) under one assessment; voiding the
    HAZARDOUS one recomputes finding_level down to ELEVATED, and open_finding_count
    stays 1 (still in {ELEVATED, HAZARDOUS}).

    Design: Difficulty/transitive_cascade/sample_void_findinglevel_openfindings_posture_depth3
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="Assessor")
    project = create_project(hazard_class="MOLD", site_name="Two Sample Void")
    assessment = create_assessment(project["id"], assessor["id"], area_label="Room")
    haz = create_analyzed_air_sample(project["id"], assessment["id"],
                                     raw_count=1200, volume_liters=100)  # 12000 HAZARDOUS
    create_analyzed_air_sample(project["id"], assessment["id"],
                               raw_count=200, volume_liters=100,
                               collected_at="2026-01-14T01:00:00Z")       # 2000 ELEVATED
    voided = validate_success(api.void_sample(haz["id"], PM), 200)
    assert voided["status"] == "VOIDED"
    reassessment = validate_success(api.get_assessment(assessment["id"], PM), 200)
    assert reassessment["finding_level"] == "ELEVATED"
    reproject = validate_success(api.get_project(project["id"], PM), 200)
    assert reproject["open_finding_count"] == 1


# ===========================================================================
# Difficulty/priority_pair_validation_conflict
# ===========================================================================
def test_occ_stale_outranks_independence_with_lead_as_signer(api):
    """PRD §2.6: "Before any business rule is evaluated, the server compares
    `expected_project_version` against the project's current `version`. If they do not
    match ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "the sign-off worker must be independent, meaning `signoff_worker_id` is
    neither the `sampler_worker_id` of this test nor the `lead_worker_id` of the
    referenced abatement order (else `ERR_SIGNOFF_NOT_INDEPENDENT`)."

    Stale version AND a non-independent signer (the abatement lead, here a HYGIENIST):
    OCC (pre-business) wins -> ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_outranks_signoff_independence
    """
    set_clock()
    # Lead is a HYGIENIST so the only remaining checks are OCC and independence.
    lead = create_worker(cert_type="HYGIENIST", full_name="Lead Hyg")
    sampler = create_worker(cert_type="MOLD", full_name="Sampler")
    project = create_project(hazard_class="MOLD", site_name="Pri2 Site")
    zone = create_active_zone(project["id"])
    # Order requires lead cert_type == abatement_type; use a separate certified crew
    # worker for the order's lead, but name the HYGIENIST lead as both order lead and
    # signer. The order's abatement_type is HYGIENIST is invalid; instead make the
    # order lead a MOLD worker and have the signer equal that lead is not possible.
    # So: order lead is the HYGIENIST? cert mismatch. Use a MOLD order lead and set
    # signoff_worker_id to that same MOLD lead (non-independent) — but signer must be
    # HYGIENIST too; that fails cert. The clean construction: order lead == sampler is
    # disallowed. We therefore make the order lead a HYGIENIST-incompatible path.
    # Simplest faithful construction: order lead is a MOLD worker; signer is that lead.
    mold_lead = create_worker(cert_type="MOLD", full_name="Mold Lead")
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], mold_lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], mold_lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))
    man = get_success_data(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man["id"], AS))
    get_success_data(api.accept_manifest(man["id"], PM))
    get_success_data(api.complete_abatement_order(order["id"], {"removed_weight_kg": 50}, AS))
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(project["id"], zone["id"], order["id"], sampler["id"],
                                      clearance_air_count=10, clearance_volume_liters=100), LT))
    get_success_data(api.analyze_clearance_test(clearance["id"], LT))  # PASSED
    pv = get_project_version(project["id"])
    # Name 'lead' (the order's lead_worker_id) as signer -> non-independent; with a
    # stale version. OCC must win.
    res = api.signoff_clearance_test(
        clearance["id"],
        {"signoff_worker_id": mold_lead["id"], "expected_project_version": pv - 1}, HY)
    validate_error(res, "ERR_STALE_VERSION")


def test_invalid_state_outranks_zone_not_active_on_cancelled_order(api):
    """PRD §2.7: "the state-machine guard that the target is in a state from which the
    transition is defined (`ERR_INVALID_STATE`); and finally the operation-specific
    business and safety rules described throughout Section 3."
    PRD §3.5: "Completion further requires that the referenced zone still be `ACTIVE`
    (else `ERR_ZONE_NOT_ACTIVE`)".

    Completing a CANCELLED order (not IN_PROGRESS) whose zone is SETUP fails the state
    guard first -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_zone_not_active_on_complete
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    project = create_project(hazard_class="MOLD", site_name="State2 Site")
    zone = create_zone(project["id"])  # SETUP
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.cancel_abatement_order(order["id"], PM))  # PLANNED -> CANCELLED
    res = api.complete_abatement_order(order["id"], {"removed_weight_kg": 50}, AS)
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Difficulty/cross_entity_state_dependency
# ===========================================================================
def test_restart_reopened_order_blocked_when_zone_breached(api):
    """PRD §3.5: "A `REOPENED` order is started again by an `AbatementSupervisor`,
    returning to `IN_PROGRESS`, subject to the zone-active, lead-certification, and
    certified-crew gates above".
    PRD §3.5: "the referenced zone must be `ACTIVE` (else `ERR_ZONE_NOT_ACTIVE`)".

    A REOPENED order whose zone is BREACHED (not ACTIVE) cannot be restarted.

    Design: Difficulty/cross_entity_state_dependency/abatement_start_requires_zone_active
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=90, clearance_volume_liters=100)
    get_success_data(api.analyze_clearance_test(ctx["cid"], LT))  # FAIL -> REOPENED
    # Breach the zone with a low reading.
    get_success_data(api.create_pressure_log(
        ctx["zid"], create_pressure_log_payload(ctx["zid"], reading_pa=1,
                                                reading_at="2026-01-14T20:00:00Z"), AS))
    rezone = validate_success(api.get_zone(ctx["zid"], PM), 200)
    assert rezone["status"] == "BREACHED"
    res = api.start_abatement_order(ctx["aid"], AS)
    validate_error(res, "ERR_ZONE_NOT_ACTIVE")


def test_insurance_submit_blocked_while_posture_contained(api):
    """PRD §3.9: "A `ProjectManager` submits an `OPEN` claim only when the project
    posture is `CLEARANCE_PENDING` or `VERIFIED` (otherwise
    `ERR_PROJECT_NOT_READY_FOR_BILLING`)."

    Posture CONTAINED (active zone but no completed orders) still blocks submission.

    Design: Difficulty/cross_entity_state_dependency/insurance_submit_requires_project_posture_ready
    """
    set_clock()
    project = create_project(hazard_class="MOLD", site_name="Contained Bill")
    create_active_zone(project["id"])  # posture -> CONTAINED
    contained = validate_success(api.get_project(project["id"], PM), 200)
    assert contained["posture"] == "CONTAINED"
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(project["id"], policy_number="POL-CT",
                                       deductible_cents=0, coverage_limit_cents=100000), PM))
    res = api.submit_insurance_claim(claim["id"], PM)
    validate_error(res, "ERR_PROJECT_NOT_READY_FOR_BILLING")


# ===========================================================================
# Difficulty/resource_temporal_overlap
# ===========================================================================
def test_neshap_notice_window_exactly_ten_days_allows_submit(api):
    """PRD §3.7: "whose `notice_days` must be at least 10 at submission time,
    otherwise the submission is rejected with `ERR_NESHAP_NOTICE_NOT_MET`."
    PRD §3.7: "the elapsed seconds from `postmarked_at` to `work_start_at` are divided
    by 86400 and floored".

    A NESHAP permit with an exactly-10-day window (notice_days == 10, the inclusive
    boundary) submits successfully.

    Design: Difficulty/resource_temporal_overlap/neshap_notice_lead_window_too_short_blocks_submit
    """
    set_clock()
    project = create_project(hazard_class="ASBESTOS", site_name="Permit10 Site")
    permit = get_success_data(api.create_permit(
        create_permit_payload(project["id"], permit_type="NESHAP_NOTIFICATION",
                              postmarked_at="2026-01-01T00:00:00Z",
                              work_start_at="2026-01-11T00:00:00Z"), CO))
    assert permit["notice_days"] == 10
    submitted = validate_success(api.submit_permit(permit["id"], CO), 200)
    assert submitted["status"] == "SUBMITTED"


def test_latest_pressure_tie_broken_by_created_at_breaches_zone(api):
    """PRD §3.4: "Each new reading recomputes the zone's `latest_pressure_pa`, defined
    as the `reading_pa` of the zone's reading with the greatest `reading_at`, breaking
    ties by the greatest `created_at`".

    Two readings share the same reading_at; the later-created low reading wins the tie
    and breaches the ACTIVE zone.

    Design: Difficulty/resource_temporal_overlap/latest_pressure_reading_below_required_breaches_active_zone
    """
    set_clock()
    project = create_project(hazard_class="MOLD", site_name="Tie Site")
    zone = create_active_zone(project["id"], reading_pa=12, reading_at="2026-01-14T08:00:00Z")
    # Same reading_at as a fresh high reading, then a fresh low reading at the same
    # reading_at created later — the latest-created (low) wins the tie -> breach.
    get_success_data(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"], reading_pa=11,
                                                reading_at="2026-01-14T09:00:00Z"), AS))
    get_success_data(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"], reading_pa=3,
                                                reading_at="2026-01-14T09:00:00Z"), AS))
    rezone = validate_success(api.get_zone(zone["id"], PM), 200)
    assert rezone["latest_pressure_pa"] == 3
    assert rezone["is_compliant"] is False
    assert rezone["status"] == "BREACHED"


# ===========================================================================
# Difficulty/boundary_precision_check (zero-count arm)
# ===========================================================================
def test_assignment_with_expired_cert_still_blocks_start(api):
    """PRD §3.5: "at least one `ACTIVE` worker assignment on the order must belong to
    a worker whose certification is current (else `ERR_NO_CERTIFIED_CREW`)."
    PRD §3.1: "The certification comparison is strict: a certification whose expiry
    equals the current instant is not current."

    The order has one ACTIVE assignment, but the assigned worker's cert is expired, so
    the count of current-certified crew is zero -> ERR_NO_CERTIFIED_CREW.

    Design: Difficulty/boundary_precision_check/zero_active_certified_assignments_blocks_start
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")  # current cert
    # Crew worker whose cert expires exactly at clock now -> not current.
    stale = create_worker(cert_type="MOLD", full_name="Stale Crew",
                          cert_expires_at="2026-01-15T00:00:00Z",
                          ppe_fit_test_at="2025-12-15T00:00:00Z")
    project = create_project(hazard_class="MOLD", site_name="Stale Crew Site")
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    # Only the stale (non-current) worker is assigned.
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], stale["id"]), AS))
    res = api.start_abatement_order(order["id"], AS)
    validate_error(res, "ERR_NO_CERTIFIED_CREW")


# ===========================================================================
# Difficulty/compensating_invariant
# ===========================================================================
def test_settlement_drops_to_zero_after_fail_before_recomplete(api):
    """PRD §3.8: "the insurance settlement is recomputed because the voided manifests
    leave the actuals".
    PRD §3.9: "Its scope is the abatement orders whose status is `COMPLETED`. ... The
    disposal component sums the `disposal_fee_cents` of only the `ACCEPTED` manifests
    whose order is completed."

    The mid-cycle low point of the conserved quantity: after a FAIL reopens the order
    and voids the manifest, settled_amount_cents is 0 (no COMPLETED order, no ACCEPTED
    manifest remain) — the value the conservation test later restores.

    Design: Difficulty/compensating_invariant/settlement_conserved_across_fail_recomplete_cycle
    """
    ctx = setup_completed_order(hazard_class="MOLD", with_sampler=True,
                                planned_weight_kg=50, removed_weight_kg=50,
                                manifest_weight_kg=50)
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-CI1",
                                       deductible_cents=0,
                                       coverage_limit_cents=100_000_000), PM))
    submitted = validate_success(api.submit_insurance_claim(claim["id"], PM), 200)
    assert submitted["settled_amount_cents"] == 79000  # 50*1500 + 4000 before the fail
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(ctx["pid"], ctx["zid"], ctx["aid"], ctx["sampler_id"],
                                      clearance_air_count=90, clearance_volume_liters=100), LT))
    get_success_data(api.analyze_clearance_test(clearance["id"], LT))  # FAIL cascade
    reclaim = validate_success(api.get_insurance_claim(claim["id"], PM), 200)
    assert reclaim["settled_amount_cents"] == 0


def test_open_finding_count_returns_to_zero_after_void(api):
    """PRD §2.5: "an `open_finding_count`: the number of assessments under the project
    whose `finding_level` is either `ELEVATED` or `HAZARDOUS` and whose `status` is
    not yet `CLEARED`."
    PRD §3.3: "if there are no analyzed samples the finding level is `CLEAN`."

    The mid-cycle return-to-baseline of the conserved count: analyzing a HAZARDOUS
    sample raises open_finding_count to 1, and voiding it returns the count to 0
    (the value the full conservation test then re-raises).

    Design: Difficulty/compensating_invariant/open_finding_count_conserved_across_void_and_reanalyze
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="Assessor")
    project = create_project(hazard_class="MOLD", site_name="CI2 Baseline")
    assessment = create_assessment(project["id"], assessor["id"], area_label="Floor")
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=1200, volume_liters=100)
    raised = validate_success(api.get_project(project["id"], PM), 200)
    assert raised["open_finding_count"] == 1
    get_success_data(api.void_sample(sample["id"], PM))
    restored = validate_success(api.get_project(project["id"], PM), 200)
    assert restored["open_finding_count"] == 0
