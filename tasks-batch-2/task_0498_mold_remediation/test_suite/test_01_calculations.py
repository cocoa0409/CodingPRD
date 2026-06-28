"""Difficulty queue (A): dual-variant and combinatorial calculations.

Covers rule dual_variant_calc, combinatorial_formula, and the numeric-threshold
arm of boundary_precision_check, plus the corner-queue calculation breadth probes.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_completed_order,
    setup_draft_clearance,
    setup_verified_project,
    create_project,
    create_worker,
    create_assessment,
    create_active_zone,
    create_analyzed_air_sample,
    set_clock,
    get_project_version,
    create_abatement_order_payload,
    create_manifest_payload,
    create_sample_payload,
    create_permit_payload,
    create_insurance_claim_payload,
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
def test_claim_estimate_vs_settlement_diverge_on_planned_vs_actual(api):
    """PRD §3.9: "The labor component sums, over those scope orders, the order's
    `planned_weight_kg` multiplied by 1500 cents per kilogram, each product rounded
    half up to whole cents before summing." and PRD §3.9: "The labor component sums,
    over those completed orders, the actual `removed_weight_kg` multiplied by 1500
    cents per kilogram, each product rounded half up to whole cents before summing.
    The disposal component sums the `disposal_fee_cents` of only the `ACCEPTED`
    manifests whose order is completed."

    The estimate uses planned_weight_kg (100) and applies no deductible; the
    settlement uses removed_weight_kg (80) and subtracts the deductible. They diverge.

    Design: Difficulty/dual_variant_calc/claim_estimate_vs_settlement_diverge_on_planned_vs_actual_weight
    """
    ctx = setup_completed_order(
        hazard_class="MOLD", abatement_type="MOLD",
        planned_weight_kg=100, removed_weight_kg=80, manifest_weight_kg=100,
    )
    claim = get_success_data(
        api.create_insurance_claim(
            create_insurance_claim_payload(ctx["pid"], policy_number="POL-1",
                                           deductible_cents=5000,
                                           coverage_limit_cents=10_000_000), PM)
    )
    submitted = validate_success(api.submit_insurance_claim(claim["id"], PM), 200)
    # estimate: 100*1500 + 8000 (100kg mold manifest fee) = 158000
    assert submitted["estimated_amount_cents"] == 158000
    # settlement: 80*1500 + 8000 - 5000 deductible = 123000
    assert submitted["settled_amount_cents"] == 123000
    assert submitted["estimated_amount_cents"] != submitted["settled_amount_cents"]


def test_sample_grade_vs_clearance_outcome_diverge_on_same_concentration(api):
    """PRD §3.3: "For an air sample, a concentration below 1000 spores per cubic
    meter grades `CLEAN`; a concentration at or above 1000 but below 10000 grades
    `ELEVATED`; a concentration at or above 10000 grades `HAZARDOUS`."
    PRD §3.8: "The outcome is `PASS` when the clearance concentration is strictly
    below the applicable limit, and `FAIL` when it is at or above the limit — a
    concentration exactly equal to the limit fails."

    A diagnostic AIR sample at 500 grades CLEAN, yet a clearance test at 900 (== the
    mold limit) FAILs — two distinct decision algorithms.

    Design: Difficulty/dual_variant_calc/sample_grade_air_vs_clearance_outcome_diverge_on_same_concentration
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="Sampler")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=50, volume_liters=100)
    assert sample["concentration"] == 500
    assert sample["result_grade"] == "CLEAN"

    # Build a completed order + draft clearance with concentration 900 == MOLD_LIMIT.
    ctx = setup_completed_order(hazard_class="MOLD", with_sampler=True)
    clearance = get_success_data(
        api.create_clearance_test(
            {"project_id": ctx["pid"], "zone_id": ctx["zid"],
             "abatement_order_id": ctx["aid"], "sampler_worker_id": ctx["sampler_id"],
             "clearance_air_count": 90, "clearance_volume_liters": 100}, LT)
    )
    analyzed = validate_success(api.analyze_clearance_test(clearance["id"], LT), 200)
    assert analyzed["clearance_concentration"] == 900
    assert analyzed["outcome"] == "FAIL"


# ===========================================================================
# Difficulty/combinatorial_formula
# ===========================================================================
def test_disposal_fee_tiered_marginal_with_asbestos_surcharge(api):
    """PRD §3.6: "the portion up to 100 kg is charged at 80 cents per kilogram; the
    portion above 100 kg and up to 500 kg is charged at 120 cents per kilogram; and
    the portion above 500 kg is charged at 200 cents per kilogram." and PRD §3.6:
    "an asbestos order multiplies the base fee by 1.5, a lead order by 1.25, and a
    mold order by 1.0."

    250 kg ASBESTOS: tier1 100*80=8000, tier2 150*120=18000, base 26000, *1.5 = 39000.

    Design: Difficulty/combinatorial_formula/disposal_fee_tiered_marginal_with_asbestos_surcharge
    """
    set_clock()
    lead = create_worker(cert_type="ASBESTOS", full_name="Lead Asb")
    project = create_project(hazard_class="ASBESTOS", structure_sqft=80, site_name="Asb Site")
    zone = get_success_data(api.create_zone(
        {"project_id": project["id"], "zone_label": "Z1", "required_pressure_pa": 10}, PM))
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="ASBESTOS", planned_weight_kg=250), AS))
    manifest = validate_success(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=250), AS), 201)
    assert manifest["disposal_fee_cents"] == 39000


def test_claim_disposal_cents_per_manifest_then_sum_rounding_order(api):
    """PRD §3.9: "the per-manifest fees are summed and the order of operations
    matters — two separate 60 kg manifests, each entirely inside the first disposal
    tier, do not produce the same total as one 120 kg manifest whose 20 kg crosses
    into the second tier."

    Two completed 60 kg MOLD orders: labor 60*1500*2 = 180000; disposal 4800+4800 =
    9600; total 189600 (not 180000 + 10400 = 190400).

    Design: Difficulty/combinatorial_formula/claim_disposal_cents_per_manifest_then_sum_rounding_order
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")
    project = create_project(hazard_class="MOLD", site_name="Two Order Site")
    zone = create_active_zone(project["id"])

    def build_completed(planned, shift_start, shift_end):
        order = get_success_data(api.create_abatement_order(
            create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                           abatement_type="MOLD", planned_weight_kg=planned), AS))
        get_success_data(api.create_assignment(
            {"abatement_order_id": order["id"], "worker_id": lead["id"],
             "shift_start_at": shift_start, "shift_end_at": shift_end}, AS))
        get_success_data(api.start_abatement_order(order["id"], AS))
        man = get_success_data(api.create_manifest(
            create_manifest_payload(order["id"], project["id"], manifest_weight_kg=planned), AS))
        get_success_data(api.submit_manifest(man["id"], AS))
        get_success_data(api.accept_manifest(man["id"], PM))
        get_success_data(api.complete_abatement_order(
            order["id"], {"removed_weight_kg": planned}, AS))
        return order

    build_completed(60, "2026-01-15T08:00:00Z", "2026-01-15T16:00:00Z")
    build_completed(60, "2026-01-16T08:00:00Z", "2026-01-16T16:00:00Z")

    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(project["id"], policy_number="POL-2",
                                       deductible_cents=0,
                                       coverage_limit_cents=100_000_000), PM))
    submitted = validate_success(api.submit_insurance_claim(claim["id"], PM), 200)
    assert submitted["estimated_amount_cents"] == 189600


# ===========================================================================
# Difficulty/boundary_precision_check (numeric-threshold arm)
# ===========================================================================
def test_clearance_equality_to_limit_fails_strict_boundary(api):
    """PRD §3.8: "The outcome is `PASS` when the clearance concentration is strictly
    below the applicable limit, and `FAIL` when it is at or above the limit — a
    concentration exactly equal to the limit fails."

    clearance_air_count=900 vol=1000 -> concentration exactly 900 == MOLD_LIMIT -> FAIL.

    Design: Difficulty/boundary_precision_check/clearance_equality_to_limit_fails_strict_boundary
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=900, clearance_volume_liters=1000)
    analyzed = validate_success(api.analyze_clearance_test(ctx["cid"], LT), 200)
    assert analyzed["clearance_concentration"] == 900
    assert analyzed["outcome"] == "FAIL"
    assert analyzed["status"] == "FAILED"


def test_clearance_just_below_limit_passes(api):
    """PRD §3.8: "The outcome is `PASS` when the clearance concentration is strictly
    below the applicable limit, and `FAIL` when it is at or above the limit — a
    concentration exactly equal to the limit fails."

    Boundary minus one: concentration 899 (< MOLD_LIMIT 900) -> PASS.

    Design: Difficulty/boundary_precision_check/clearance_equality_to_limit_fails_strict_boundary
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=899, clearance_volume_liters=1000)
    analyzed = validate_success(api.analyze_clearance_test(ctx["cid"], LT), 200)
    assert analyzed["clearance_concentration"] == 899
    assert analyzed["outcome"] == "PASS"
    assert analyzed["status"] == "PASSED"


# ===========================================================================
# Corner/calculations
# ===========================================================================
def test_air_sample_concentration_round_half_up(api):
    """PRD §3.3: "for an `AIR` sample it is the raw count divided by the sampled
    volume in liters, multiplied by 1000 liters per cubic meter, then rounded half up
    to a whole number, expressed as spores per cubic meter".

    raw_count=15 vol=110 -> 136.36.. -> 136 (grade CLEAN, below 1000).

    Design: Corner/calculations/air_sample_concentration_round_half_up
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=15, volume_liters=110)
    assert sample["concentration"] == 136
    assert sample["result_grade"] == "CLEAN"


def test_sample_grade_air_elevated_lower_bound_inclusive(api):
    """PRD §3.3: "a concentration at or above 1000 but below 10000 grades `ELEVATED`".

    raw_count=100 vol=100 -> concentration exactly 1000 == AIR_ELEVATED -> ELEVATED
    (lower bound inclusive).

    Design: Corner/calculations/sample_grade_air_elevated_lower_bound_inclusive
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=100, volume_liters=100)
    assert sample["concentration"] == 1000
    assert sample["result_grade"] == "ELEVATED"


def test_disposal_fee_mold_no_surcharge_single_tier(api):
    """PRD §3.6: "the portion up to 100 kg is charged at 80 cents per kilogram" and
    PRD §3.6: "a mold order by 1.0".

    50 kg MOLD fully in tier 1: 50*80 = 4000, *1.0 = 4000.

    Design: Corner/calculations/disposal_fee_mold_no_surcharge_single_tier
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    project = create_project(hazard_class="MOLD")
    zone = get_success_data(api.create_zone(
        {"project_id": project["id"], "zone_label": "Z1", "required_pressure_pa": 10}, PM))
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    manifest = validate_success(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS), 201)
    assert manifest["disposal_fee_cents"] == 4000


def test_disposal_fee_lead_three_tier_with_surcharge(api):
    """PRD §3.6: "the portion above 100 kg and up to 500 kg is charged at 120 cents
    per kilogram; and the portion above 500 kg is charged at 200 cents per kilogram."
    and PRD §3.6: "a lead order by 1.25".

    600 kg LEAD: 100*80 + 400*120 + 100*200 = 76000, *1.25 = 95000.

    Design: Corner/calculations/disposal_fee_lead_three_tier_with_surcharge
    """
    set_clock()
    lead = create_worker(cert_type="LEAD", full_name="Lead")
    project = create_project(hazard_class="LEAD", site_name="Pb")
    zone = get_success_data(api.create_zone(
        {"project_id": project["id"], "zone_label": "Z1", "required_pressure_pa": 10}, PM))
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="LEAD", planned_weight_kg=600), AS))
    manifest = validate_success(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=600), AS), 201)
    assert manifest["disposal_fee_cents"] == 95000


def test_settlement_cap_applied_when_gross_exceeds_limit(api):
    """PRD §3.9: "if the gross settlement (before deductible and cap) exceeds
    `coverage_limit_cents`, the request must carry `allow_over_cap` set to true to
    proceed; if `allow_over_cap` is omitted or false while the gross exceeds the
    coverage limit, the settle is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED` (HTTP 402)".

    Gross 50*1500 + 4000 = 79000 > coverage 50000, allow_over_cap omitted -> 402.

    Design: Corner/calculations/settlement_cap_applied_when_gross_exceeds_limit
    """
    ctx = setup_verified_project(hazard_class="MOLD")
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-C",
                                       deductible_cents=0, coverage_limit_cents=50000), PM))
    get_success_data(api.submit_insurance_claim(claim["id"], PM))
    res = api.settle_insurance_claim(claim["id"], {}, CO)
    validate_error(res, "ERR_COVERAGE_LIMIT_EXCEEDED")


def test_settlement_caps_with_allow_over_cap(api):
    """PRD §3.9: "Finally the coverage cap is applied: the settlement is the smaller
    of the after-deductible amount and `coverage_limit_cents`."

    With allow_over_cap=true, gross 79000 > coverage 50000 -> settle succeeds and
    settled_amount_cents is capped to 50000.

    Design: Corner/calculations/settlement_caps_with_allow_over_cap
    """
    ctx = setup_verified_project(hazard_class="MOLD")
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(ctx["pid"], policy_number="POL-C2",
                                       deductible_cents=0, coverage_limit_cents=50000), PM))
    get_success_data(api.submit_insurance_claim(claim["id"], PM))
    settled = validate_success(
        api.settle_insurance_claim(claim["id"], {"allow_over_cap": True}, CO), 200)
    assert settled["settled_amount_cents"] == 50000
    assert settled["status"] == "SETTLED"


def test_notice_lead_days_floor_partial_day(api):
    """PRD §3.7: "the elapsed seconds from `postmarked_at` to `work_start_at` are
    divided by 86400 and floored".

    postmark 2026-01-01T00:00, work_start 2026-01-11T12:00 -> 10.5 days -> floor 10.

    Design: Corner/calculations/notice_lead_days_floor_partial_day
    """
    set_clock()
    project = create_project(hazard_class="ASBESTOS", site_name="Asb")
    permit = validate_success(api.create_permit(
        create_permit_payload(project["id"], permit_type="NESHAP_NOTIFICATION",
                              postmarked_at="2026-01-01T00:00:00Z",
                              work_start_at="2026-01-11T12:00:00Z"), CO), 201)
    assert permit["notice_days"] == 10
