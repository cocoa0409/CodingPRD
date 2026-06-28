"""Difficulty queue (A): state machines, transitive cascades, compensating invariants.

Covers rules non_linear_state_machine, transitive_cascade, compensating_invariant,
plus corner-queue state-machine and cross-cutting cascade breadth probes.
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
    setup_verified_project,
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
    create_insurance_claim_payload,
    create_pressure_log_payload,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]
AS = TEST_USERS["abatement_supervisor_headers"]
LT = TEST_USERS["lab_tech_headers"]
HY = TEST_USERS["hygienist_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Difficulty/non_linear_state_machine
# ===========================================================================
def test_abatement_order_cyclic_reopen_on_clearance_fail_then_restart(api):
    """PRD §3.5: "A `COMPLETED` order is reopened — `COMPLETED → REOPENED` —
    automatically by the system when a clearance test for that order fails".
    PRD §3.5: "A `REOPENED` order is started again by an `AbatementSupervisor`,
    returning to `IN_PROGRESS`, subject to the zone-active, lead-certification, and
    certified-crew gates above (the NESHAP gate is not re-checked on the reopened
    restart)."

    A FAILED clearance reopens the order; /start drives REOPENED -> IN_PROGRESS.

    Design: Difficulty/non_linear_state_machine/abatement_order_cyclic_reopen_on_clearance_fail
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=90, clearance_volume_liters=100)
    get_success_data(api.analyze_clearance_test(ctx["cid"], LT))  # FAIL -> REOPENED
    reopened = validate_success(api.get_abatement_order(ctx["aid"], AS), 200)
    assert reopened["status"] == "REOPENED"
    restarted = validate_success(api.start_abatement_order(ctx["aid"], AS), 200)
    assert restarted["status"] == "IN_PROGRESS"


def test_clearance_test_branching_pass_leaves_order_and_manifest_untouched(api):
    """PRD §3.8: "`PASSED` is an intermediate state awaiting an independent sign-off."
    PRD §3.8: "`FAILED` is terminal for that test and triggers a four-hop cascade:
    the referenced order is reopened (`COMPLETED → REOPENED`); that order's `ACCEPTED`
    (and `SUBMITTED`) disposal manifests are voided to `VOIDED`".

    The PASS branch is the complement: outcome PASS -> status PASSED, with the order
    still COMPLETED and the manifest still ACCEPTED (no reopen, no void).

    Design: Difficulty/non_linear_state_machine/clearance_test_branching_pass_vs_fail_divergent_cascades
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=10, clearance_volume_liters=100)
    analyzed = validate_success(api.analyze_clearance_test(ctx["cid"], LT), 200)
    assert analyzed["outcome"] == "PASS"
    assert analyzed["status"] == "PASSED"
    order = validate_success(api.get_abatement_order(ctx["aid"], AS), 200)
    assert order["status"] == "COMPLETED"
    manifest = validate_success(api.get_manifest(ctx["mid"], PM), 200)
    assert manifest["status"] == "ACCEPTED"


# ===========================================================================
# Difficulty/transitive_cascade
# ===========================================================================
def test_clearance_fail_reopen_void_manifest_reprice_settlement_depth3(api):
    """PRD §3.8: "`FAILED` is terminal for that test and triggers a four-hop cascade:
    the referenced order is reopened (`COMPLETED → REOPENED`); that order's `ACCEPTED`
    (and `SUBMITTED`) disposal manifests are voided to `VOIDED`; the insurance
    settlement is recomputed because the voided manifests leave the actuals; and the
    project posture is recomputed down to `ABATING`."

    Design: Difficulty/transitive_cascade/clearance_fail_reopen_void_manifest_reprice_settlement_depth3
    """
    ctx = setup_completed_order(hazard_class="MOLD", with_sampler=True,
                                planned_weight_kg=50, removed_weight_kg=50,
                                manifest_weight_kg=50)
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-3",
                                       deductible_cents=0,
                                       coverage_limit_cents=100_000_000), PM))
    get_success_data(api.submit_insurance_claim(claim["id"], PM))
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(ctx["pid"], ctx["zid"], ctx["aid"], ctx["sampler_id"],
                                      clearance_air_count=90, clearance_volume_liters=100), LT))
    analyzed = validate_success(api.analyze_clearance_test(clearance["id"], LT), 200)
    assert analyzed["status"] == "FAILED"

    order = validate_success(api.get_abatement_order(ctx["aid"], AS), 200)
    assert order["status"] == "REOPENED"
    manifest = validate_success(api.get_manifest(ctx["mid"], PM), 200)
    assert manifest["status"] == "VOIDED"
    reclaim = validate_success(api.get_insurance_claim(claim["id"], PM), 200)
    assert reclaim["settled_amount_cents"] == 0


def test_sample_void_findinglevel_openfindings_posture_depth3(api):
    """PRD §3.3: "Voiding an `ANALYZED` sample also moves it to `VOIDED` ... and on
    success it recomputes the parent assessment's `finding_level`, then the project's
    `open_finding_count` (because the finding level may have changed), then the
    project's `posture`."
    PRD §3.3: "the finding level is the highest-severity grade across the analyzed
    samples, and if there are no analyzed samples the finding level is `CLEAN`."

    Voiding the sole HAZARDOUS sample drops finding_level to CLEAN and the project's
    open_finding_count to 0.

    Design: Difficulty/transitive_cascade/sample_void_findinglevel_openfindings_posture_depth3
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="Assessor")
    project = create_project(hazard_class="MOLD", site_name="Void Site")
    assessment = create_assessment(project["id"], assessor["id"], area_label="Ceiling")
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=1200, volume_liters=100)
    assert sample["result_grade"] == "HAZARDOUS"

    voided = validate_success(api.void_sample(sample["id"], PM), 200)
    assert voided["status"] == "VOIDED"
    reassessment = validate_success(api.get_assessment(assessment["id"], PM), 200)
    assert reassessment["finding_level"] == "CLEAN"
    reproject = validate_success(api.get_project(project["id"], PM), 200)
    assert reproject["open_finding_count"] == 0


# ===========================================================================
# Difficulty/compensating_invariant
# ===========================================================================
def test_settlement_conserved_across_fail_recomplete_cycle(api):
    """PRD §3.9: "The labor component sums, over those completed orders, the actual
    `removed_weight_kg` multiplied by 1500 cents per kilogram, each product rounded
    half up to whole cents before summing. The disposal component sums the
    `disposal_fee_cents` of only the `ACCEPTED` manifests whose order is completed.
    Those two sums give the gross. The deductible is then subtracted, floored at zero".

    After a clearance FAIL drives settlement to 0 (order reopened, manifest voided),
    re-completing the order with a fresh ACCEPTED 50 kg manifest restores it to 79000.

    Design: Difficulty/compensating_invariant/settlement_conserved_across_fail_recomplete_cycle
    """
    ctx = setup_completed_order(hazard_class="MOLD", with_sampler=True,
                                planned_weight_kg=50, removed_weight_kg=50,
                                manifest_weight_kg=50)
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-4",
                                       deductible_cents=0,
                                       coverage_limit_cents=100_000_000), PM))
    get_success_data(api.submit_insurance_claim(claim["id"], PM))
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(ctx["pid"], ctx["zid"], ctx["aid"], ctx["sampler_id"],
                                      clearance_air_count=90, clearance_volume_liters=100), LT))
    get_success_data(api.analyze_clearance_test(clearance["id"], LT))  # FAIL -> reopen, void

    # Re-run the work loop: restart, fresh manifest, accept, complete.
    get_success_data(api.start_abatement_order(ctx["aid"], AS))
    man2 = get_success_data(api.create_manifest(
        create_manifest_payload(ctx["aid"], ctx["pid"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man2["id"], AS))
    get_success_data(api.accept_manifest(man2["id"], PM))
    recompleted = validate_success(
        api.complete_abatement_order(ctx["aid"], {"removed_weight_kg": 50}, AS), 200)
    assert recompleted["status"] == "COMPLETED"

    reclaim = validate_success(api.get_insurance_claim(claim["id"], PM), 200)
    assert reclaim["settled_amount_cents"] == 79000


def test_open_finding_count_conserved_across_void_and_reanalyze(api):
    """PRD §2.5: "an `open_finding_count`: the number of assessments under the
    project whose `finding_level` is either `ELEVATED` or `HAZARDOUS` and whose
    `status` is not yet `CLEARED`."
    PRD §3.3: "the finding level is the highest-severity grade across the analyzed
    samples".

    Analyze a HAZARDOUS sample (count 1), void it (count 0), then analyze a fresh
    HAZARDOUS sample under the same assessment -> count restored to 1.

    Design: Difficulty/compensating_invariant/open_finding_count_conserved_across_void_and_reanalyze
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="Assessor")
    project = create_project(hazard_class="MOLD", site_name="Conserve2 Site")
    assessment = create_assessment(project["id"], assessor["id"], area_label="Floor")
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=1200, volume_liters=100)
    get_success_data(api.void_sample(sample["id"], PM))
    # Fresh HAZARDOUS sample under the same assessment.
    create_analyzed_air_sample(project["id"], assessment["id"],
                               raw_count=1200, volume_liters=100,
                               collected_at="2026-01-14T01:00:00Z")
    reassessment = validate_success(api.get_assessment(assessment["id"], PM), 200)
    assert reassessment["finding_level"] == "HAZARDOUS"
    reproject = validate_success(api.get_project(project["id"], PM), 200)
    assert reproject["open_finding_count"] == 1


# ===========================================================================
# Corner/state_machines
# ===========================================================================
def test_void_already_voided_sample_returns_invalid_state(api):
    """PRD §3.3: "Attempting to void a sample that is neither `PENDING` nor
    `ANALYZED` is an `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_already_voided_sample_returns_invalid_state
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = get_success_data(api.create_sample(
        create_sample_payload(assessment["id"], project["id"], "SURFACE"), LT))
    get_success_data(api.void_sample(sample["id"], PM))
    res = api.void_sample(sample["id"], PM)
    validate_error(res, "ERR_INVALID_STATE")


def test_new_sample_starts_pending_and_moves_assessment_to_sampled(api):
    """PRD §3.3: "A new sample starts in `PENDING`" and PRD §3.3: "The first sample
    created under a `DRAFT` assessment moves it to `SAMPLED`."

    Design: Corner/state_machines/new_sample_starts_pending_and_moves_assessment_to_sampled
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = validate_success(api.create_sample(
        create_sample_payload(assessment["id"], project["id"], "SURFACE"), LT), 201)
    assert sample["status"] == "PENDING"
    reassessment = validate_success(api.get_assessment(assessment["id"], LT), 200)
    assert reassessment["status"] == "SAMPLED"


def test_signoff_from_draft_clearance_returns_invalid_state(api):
    """PRD §3.8: "the test must be `PASSED` (else `ERR_INVALID_STATE`)".

    A DRAFT clearance (never analyzed) cannot be signed off.

    Design: Corner/state_machines/signoff_from_draft_clearance_returns_invalid_state
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=10, clearance_volume_liters=100)
    pv = get_project_version(ctx["pid"])
    res = api.signoff_clearance_test(
        ctx["cid"], {"signoff_worker_id": ctx["hyg_id"], "expected_project_version": pv}, HY)
    validate_error(res, "ERR_INVALID_STATE")


def test_terminal_failed_clearance_cannot_be_signed_off(api):
    """PRD §3.8: "`FAILED` is terminal for that test" and PRD §3.8: "the test must be
    `PASSED` (else `ERR_INVALID_STATE`)".

    A FAILED clearance (terminal) cannot transition to SIGNED_OFF.

    Design: Corner/state_machines/terminal_failed_clearance_cannot_be_signed_off
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=90, clearance_volume_liters=100)
    get_success_data(api.analyze_clearance_test(ctx["cid"], LT))  # -> FAILED
    pv = get_project_version(ctx["pid"])
    res = api.signoff_clearance_test(
        ctx["cid"], {"signoff_worker_id": ctx["hyg_id"], "expected_project_version": pv}, HY)
    validate_error(res, "ERR_INVALID_STATE")


def test_full_happy_path_project_reaches_verified_and_signed_off(api):
    """PRD §3.8: "On success the test moves `PASSED → SIGNED_OFF` ... the assessments
    covered by the cleared zone advance `ANALYZED → CLEARED` ... the project posture
    is recomputed, reaching `VERIFIED` once every zone is cleared and no findings
    remain".
    PRD §3.2: "A `Hygienist` performs the final sign-off only when the project is
    `OPEN`, its posture is `VERIFIED`, and its `open_finding_count` is zero; the
    project's `status` then becomes the terminal `SIGNED_OFF`."

    Design: Corner/state_machines/full_happy_path_project_reaches_verified_and_signed_off
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    sampler = create_worker(cert_type="MOLD", full_name="Sampler")
    hyg = create_worker(cert_type="HYGIENIST", full_name="Hyg")
    project = create_project(hazard_class="MOLD", site_name="Happy")
    assessment = create_assessment(project["id"], sampler["id"], area_label="Wall")
    # CLEAN finding so open_finding_count stays 0.
    create_analyzed_air_sample(project["id"], assessment["id"], raw_count=50, volume_liters=100)
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))
    man = get_success_data(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man["id"], AS))
    get_success_data(api.accept_manifest(man["id"], PM))
    get_success_data(api.complete_abatement_order(order["id"], {"removed_weight_kg": 50}, AS))
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(project["id"], zone["id"], order["id"], sampler["id"],
                                      clearance_air_count=10, clearance_volume_liters=100), LT))
    get_success_data(api.analyze_clearance_test(clearance["id"], LT))
    pv = get_project_version(project["id"])
    get_success_data(api.signoff_clearance_test(
        clearance["id"], {"signoff_worker_id": hyg["id"], "expected_project_version": pv}, HY))

    cleared_assessment = validate_success(api.get_assessment(assessment["id"], HY), 200)
    assert cleared_assessment["status"] == "CLEARED"
    signed = validate_success(api.signoff_project(project["id"], HY), 200)
    assert signed["posture"] == "VERIFIED"
    assert signed["status"] == "SIGNED_OFF"


# ===========================================================================
# Corner/cross_cutting_complexity_layers
# ===========================================================================
def test_occ_signoff_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.6: "Before any business rule is evaluated, the server compares
    `expected_project_version` against the project's current `version`."
    PRD §3.8: "the project posture is recomputed, reaching `VERIFIED` once every zone
    is cleared and no findings remain; and finally the project's `version` is
    incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_signoff_correct_version_succeeds_and_bumps_version
    """
    ctx = setup_passed_clearance(hazard_class="MOLD")
    pv = get_project_version(ctx["pid"])
    signed = validate_success(api.signoff_clearance_test(
        ctx["cid"], {"signoff_worker_id": ctx["hyg_id"], "expected_project_version": pv}, HY), 200)
    assert signed["status"] == "SIGNED_OFF"
    after = validate_success(api.get_project(ctx["pid"], HY), 200)
    assert after["version"] == pv + 1
    assert after["posture"] == "VERIFIED"


def test_derived_posture_freezes_on_breach_then_unfreezes(api):
    """PRD §3.4: "If the zone is currently `BREACHED` and a later reading restores
    compliance, the zone transitions `BREACHED → ACTIVE`, `is_compliant` is set true,
    and the project's posture is recomputed, clearing the freeze back to whatever the
    precedence ladder now yields (typically `ABATING` or `CONTAINED`)."

    Design: Corner/cross_cutting_complexity_layers/derived_posture_freezes_on_breach_then_unfreezes
    """
    set_clock()
    project = create_project(hazard_class="MOLD", site_name="Unfreeze")
    zone = create_active_zone(project["id"], reading_pa=12, reading_at="2026-01-14T08:00:00Z")
    # Low reading breaches the zone -> FROZEN.
    get_success_data(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"], reading_pa=4,
                                                reading_at="2026-01-14T10:00:00Z"), AS))
    frozen = validate_success(api.get_project(project["id"], PM), 200)
    assert frozen["posture"] == "FROZEN"
    # Restoring reading -> ACTIVE, posture back to CONTAINED.
    get_success_data(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"], reading_pa=15,
                                                reading_at="2026-01-14T12:00:00Z"), AS))
    rezone = validate_success(api.get_zone(zone["id"], PM), 200)
    assert rezone["status"] == "ACTIVE"
    assert rezone["latest_pressure_pa"] == 15
    reproject = validate_success(api.get_project(project["id"], PM), 200)
    assert reproject["posture"] == "CONTAINED"


def test_cancel_planned_order_cascade_releases_assignments(api):
    """PRD §3.5: "Cancelling a `PLANNED` order moves it to the terminal `CANCELLED`
    and releases all of its `ACTIVE` worker assignments to `RELEASED`, then recomputes
    posture."

    Design: Corner/cross_cutting_complexity_layers/cancel_planned_order_cascade_releases_assignments
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    project = create_project(hazard_class="MOLD", site_name="Cancel")
    zone = create_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    assignment = get_success_data(api.create_assignment(
        create_assignment_payload(order["id"], lead["id"]), AS))
    cancelled = validate_success(api.cancel_abatement_order(order["id"], PM), 200)
    assert cancelled["status"] == "CANCELLED"
    reassignment = validate_success(api.get_assignment(assignment["id"], AS), 200)
    assert reassignment["status"] == "RELEASED"


def test_rate_threshold_air_hazard_upper_tier_inclusive(api):
    """PRD §3.3: "a concentration at or above 10000 grades `HAZARDOUS`."

    raw_count=1000 vol=100 -> concentration exactly 10000 == AIR_HAZARD -> HAZARDOUS
    (upper tier lower bound inclusive).

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_air_hazard_upper_tier_inclusive
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=1000, volume_liters=100)
    assert sample["concentration"] == 10000
    assert sample["result_grade"] == "HAZARDOUS"


# ===========================================================================
# Corner/consistency_model
# ===========================================================================
def test_immediate_consistency_posture_visible_in_same_response(api):
    """PRD §3.4: "Activating the first zone recomputes the project posture, advancing
    it from `ASSESSMENT` to `CONTAINED`."
    PRD §2.10: "The system performs these cascades synchronously and to completion
    within the triggering request."

    Design: Corner/consistency_model/immediate_consistency_posture_visible_in_same_response
    """
    set_clock()
    project = create_project(hazard_class="MOLD", site_name="Imm")
    create_active_zone(project["id"])
    reproject = validate_success(api.get_project(project["id"], PM), 200)
    assert reproject["posture"] == "CONTAINED"
