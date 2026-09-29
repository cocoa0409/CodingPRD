"""Carbon-intensity variants, credit quantity variants and the credit-control ledger."""
from test_helpers import (
    OPERATOR,
    PROGRAM,
    VERIFIER,
    assert_credit_control_holds,
    certify_pathway,
    close_day,
    condition_gas,
    create_active_agreement,
    create_audit,
    create_batch,
    create_dairy,
    create_facility,
    create_interconnect,
    create_ops_day,
    create_pathway,
    book_delivery,
    read_pathway,
    read_pathway_version,
    record_fieldwork,
    set_clock,
    setup_two_dairy_injected_day,
    setup_two_dairy_issued_batch,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"

# Fieldwork actuals that restate metered volume and haul distance far enough to
# push the reported carbon intensity outside the two-gram material tolerance.
RESTATED_ACTUALS = {
    "actual_pipeline_mmbtu": 120.500,
    "actual_vs_tonnes_lagoon": 9.500,
    "actual_vs_tonnes_solid_storage": 5.600,
    "actual_vs_tonnes_daily_spread": 0.000,
    "actual_haul_tonne_km": 5040.00,
    "actual_process_g_per_mj": 15.95,
}

# Fieldwork actuals that reproduce every certified input except the process
# intensity, which the auditor measures at 17.55 instead of the design constant.
MEASURED_PROCESS_ACTUALS = {
    "actual_pipeline_mmbtu": 120.280,
    "actual_vs_tonnes_lagoon": 9.840,
    "actual_vs_tonnes_solid_storage": 5.760,
    "actual_vs_tonnes_daily_spread": 0.000,
    "actual_haul_tonne_km": 4800.00,
    "actual_process_g_per_mj": 17.55,
}


def _issued_batch_with_restated_fieldwork():
    """Issued August credits, then an audit whose fieldwork restates the inputs."""
    plant = setup_two_dairy_issued_batch()
    audit = create_audit(
        plant["pathway"]["id"], verifier_body_name="Verdant Registry Services"
    )
    plant["audit"] = record_fieldwork(audit["id"], **RESTATED_ACTUALS)
    return plant


def _close_lagoon_plant():
    """A short-haul lagoon dairy pushing 400 tonnes a day into one mesophilic digester."""
    set_clock(CLOCK_START)
    dairy = create_dairy(
        name="Close Lagoon Dairy",
        county="Tulare",
        herd_size=4200,
        manure_management_baseline="LAGOON",
        haul_distance_km=1.0,
        annual_nitrogen_budget_kg=26000.000,
    )
    facility = create_facility()
    agreement = create_active_agreement(
        dairy["id"],
        facility["id"],
        committed_tonnes_per_day=400.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2000,
        revenue_share_basis="NET",
        curtailable=False,
    )
    create_interconnect(facility["id"])
    ops_day = create_ops_day(facility["id"], "2026-08-03")
    book_delivery(
        agreement["id"],
        ops_day["id"],
        gross_tonnes=400.000,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )
    ops_day = close_day(ops_day["id"], raw_biogas_scf=40000.000)
    ops_day = condition_gas(ops_day["id"])
    pathway = create_pathway(facility["id"], pathway_code="CA-LCFS-DDRNG-2026-02")
    return {
        "dairy": dairy,
        "facility": facility,
        "agreement": agreement,
        "ops_day": ops_day,
        "pathway": pathway,
    }


def test_01_provisional_and_final_credit_quantities_diverge_after_material_finding(api):
    """A material finding revalues the final quantity while the provisional one stands.

    PRD: "Verification sets `ci_score_used` to the pathway's `verified_ci_score` when that field is not null and to `certified_ci_score` otherwise, then runs the `FINAL` variant of the credit quantity calculation, which writes both `credit_quantity_final` and `credit_value_cents`."

    Design: Difficulty/dual_variant_calc/dv_credit_quantity_provisional_vs_final_diverge_after_material_finding
    """
    plant = _issued_batch_with_restated_fieldwork()

    validate_success(
        api.issue_findings(
            plant["audit"]["id"],
            {"narrative": "Metered volume and haul distance restated"},
            VERIFIER,
        )
    )

    batch = validate_success(api.get_batch(plant["batch"]["id"], PROGRAM))
    assert batch["delivered_mmbtu"] == 120.280
    assert batch["credit_quantity_provisional"] == 36.111
    assert batch["credit_quantity_final"] == 35.004
    assert batch["credit_quantity_provisional"] != batch["credit_quantity_final"]
    assert batch["credit_value_cents"] == 260780


def test_02_material_finding_writes_verified_score_and_holds_credit_control_at_zero(api):
    """The audit's own numbers move onto the pathway and the ledger still balances.

    PRD: "Fieldwork runs the `VERIFIED` variant of the carbon intensity calculation, writing `reported_ci_score`, and sets `ci_delta` to `reported_ci_score` less the pathway's `certified_ci_score`, rounded to 2 decimal places."

    Design: Difficulty/dual_variant_calc/dv_credit_quantity_provisional_vs_final_diverge_after_material_finding
    """
    plant = _issued_batch_with_restated_fieldwork()
    assert plant["audit"]["reported_ci_score"] == -226.98
    assert plant["audit"]["ci_delta"] == 9.69

    audit = validate_success(
        api.issue_findings(
            plant["audit"]["id"],
            {"narrative": "Metered volume and haul distance restated"},
            VERIFIER,
        )
    )
    assert audit["finding_severity"] == "MATERIAL"

    pathway = read_pathway(plant["pathway"]["id"])
    assert pathway["certified_ci_score"] == -236.67
    assert pathway["verified_ci_score"] == -226.98
    assert pathway["ci_adjustment"] == 9.69
    assert pathway["credit_control_residual"] == 0.000
    assert_credit_control_holds(pathway)


def test_03_certified_variant_uses_the_design_process_constant(api):
    """Certification prices the month with the 15.40 design constant, not a measurement.

    PRD: "In the `CERTIFIED` variant, the pipeline energy is the sum of `pipeline_gas_mmbtu` over operations days of the pathway's facility whose `gas_state` is `PIPELINE_SPEC` or `INJECTED` and whose `ops_date` lies inside the inclusive reference window; the per-baseline volatile-solids tonnages are the sums of `vs_tonnes` over `ACCEPTED` deliveries on those same days, grouped by the supplying dairy's `manure_management_baseline`; the hauling activity is the sum of `haul_tonne_km` over that same delivery set; and the process intensity is the design constant 15.40 grams of carbon dioxide equivalent per megajoule."

    Design: Difficulty/dual_variant_calc/dv_pathway_ci_certified_variant_uses_design_constant_verified_uses_measured_process
    """
    plant = setup_two_dairy_injected_day()
    assert plant["ops_day"]["pipeline_gas_mmbtu"] == 120.280

    pathway = create_pathway(plant["facility"]["id"])
    certified = certify_pathway(pathway["id"], "2026-08-01", "2026-08-31")
    assert certified["certified_ci_score"] == -236.67


def test_04_verified_variant_substitutes_the_measured_process_intensity(api):
    """Identical gas reports a different intensity once the auditor measures the process.

    PRD: "In the `VERIFIED` variant, every one of those inputs is replaced by the auditor's measurement — `actual_pipeline_mmbtu`, `actual_vs_tonnes_lagoon`, `actual_vs_tonnes_solid_storage`, `actual_vs_tonnes_daily_spread`, `actual_haul_tonne_km` and a measured `actual_process_g_per_mj` that supplants the design constant — so identical gas can yield a different carbon intensity depending on which variant ran."

    Design: Difficulty/dual_variant_calc/dv_pathway_ci_certified_variant_uses_design_constant_verified_uses_measured_process
    """
    plant = setup_two_dairy_injected_day()
    pathway = create_pathway(plant["facility"]["id"])
    certified = certify_pathway(pathway["id"], "2026-08-01", "2026-08-31")
    audit = create_audit(pathway["id"], verifier_body_name="Verdant Registry Services")

    audit = validate_success(
        api.record_fieldwork(audit["id"], dict(MEASURED_PROCESS_ACTUALS), VERIFIER)
    )
    assert audit["reported_ci_score"] == -234.52
    assert audit["reported_ci_score"] != certified["certified_ci_score"]
    assert audit["ci_delta"] == 2.15
    assert audit["status"] == "FIELDWORK"


def test_05_carbon_intensity_cap_binds_before_the_floor_on_a_short_haul_lagoon_month(api):
    """Twenty times the direct intensity caps a huge avoidance claim well above the floor.

    PRD: "The avoidance credit actually granted is the lesser of the raw avoidance intensity and the direct intensity multiplied by 20.0 and rounded to 2 decimal places — the regulator will not let a project claim avoidance credit beyond twenty times its own direct emissions."

    Design: Difficulty/combinatorial_formula/cf_ci_score_nested_cap_binds_over_three_input_families
    """
    plant = _close_lagoon_plant()

    pathway = validate_success(
        api.certification_decision(
            plant["pathway"]["id"],
            {
                "decision": "CERTIFY",
                "reference_start_date": "2026-08-01",
                "reference_end_date": "2026-08-31",
            },
            PROGRAM,
        )
    )
    assert pathway["status"] == "CERTIFIED"
    assert pathway["certified_ci_score"] == -320.53


def test_06_capped_month_still_reports_its_loading_stress_and_conditioned_energy(api):
    """The same 400-tonne day that triggers the cap also books a stressed loading rate.

    PRD: "`stability_status` is `INHIBITED` when `stress_points` is greater than or equal to 4, `STRESSED` when it is greater than or equal to 2 but below 4, and `STABLE` when it is 0 or 1."

    Design: Difficulty/combinatorial_formula/cf_ci_score_nested_cap_binds_over_three_input_families
    """
    plant = _close_lagoon_plant()
    ops_day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert ops_day["organic_loading_rate"] == 4.373
    assert ops_day["stress_points"] == 3
    assert ops_day["stability_status"] == "STRESSED"
    assert ops_day["pipeline_gas_scf"] == 25185.492
    assert ops_day["pipeline_hhv_btu_per_scf"] == 974.65
    assert ops_day["pipeline_gas_mmbtu"] == 24.547

    facility = validate_success(api.get_facility(plant["facility"]["id"], OPERATOR))
    assert facility["ops_posture"] == "WATCH"


def test_07_issuance_lifts_outstanding_credits_and_leaves_the_residual_at_zero(api):
    """Issuing August credits fills both the issued total and the outstanding balance.

    PRD: "Issuance increases the pathway's `credits_issued_total` and `credits_outstanding` by `credit_quantity_final`, recomputes `credit_control_residual` which must equal 0.000, and increments both the batch's `version` and the pathway's `version` by one."

    Design: Difficulty/compensating_invariant/comp_credit_control_credits_return_to_zero_residual_after_issue_then_reverse
    """
    plant = setup_two_dairy_issued_batch()

    ledger = validate_success(api.get_credit_ledger(plant["pathway"]["id"], PROGRAM))
    assert ledger["credits_issued_total"] == 36.111
    assert ledger["credits_outstanding"] == 36.111
    assert ledger["credit_control_residual"] == 0.000


def test_08_reversal_returns_outstanding_credits_to_zero_without_erasing_history(api):
    """The compensating reversal drains the outstanding balance and keeps the residual flat.

    PRD: "It moves the batch `ISSUED → REVERSED`, a terminal state, increases the pathway's `credits_reversed_total` by `credit_quantity_final` and decreases `credits_outstanding` by the same amount, and recomputes `credit_control_residual`, which must return to exactly 0.000."

    Design: Difficulty/compensating_invariant/comp_credit_control_credits_return_to_zero_residual_after_issue_then_reverse
    """
    plant = setup_two_dairy_issued_batch()

    batch = validate_success(
        api.reverse_batch(
            plant["batch"]["id"], {"reversal_reason": "OPERATOR_WITHDRAWAL"}, PROGRAM
        )
    )
    assert batch["status"] == "REVERSED"
    assert batch["reversal_reason"] == "OPERATOR_WITHDRAWAL"
    assert batch["credit_quantity_final"] == 36.111
    assert batch["credit_value_cents"] == 269027

    pathway = read_pathway(plant["pathway"]["id"])
    assert pathway["credits_issued_total"] == 36.111
    assert pathway["credits_reversed_total"] == 36.111
    assert pathway["credits_outstanding"] == 0.000
    assert pathway["credit_control_residual"] == 0.000
    assert_credit_control_holds(pathway)


def test_09_claiming_a_batch_on_a_provisional_pathway_is_refused(api):
    """A batch may exist under a provisional pathway but cannot be claimed against it.

    PRD: "It requires the pathway to be `CERTIFIED`, or the request fails with `ERR_PATHWAY_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/ced_credit_batch_claim_blocked_until_parent_pathway_reaches_certified
    """
    plant = setup_two_dairy_injected_day()
    pathway = create_pathway(plant["facility"]["id"])
    assert pathway["status"] == "PROVISIONAL"
    batch = create_batch(
        pathway["id"], plant["facility"]["id"], read_pathway_version(pathway["id"])
    )

    validate_error(
        api.claim_batch(batch["id"], {"claim_note": "Early claim attempt"}, PROGRAM),
        "ERR_PATHWAY_NOT_CERTIFIED",
        409,
    )

    blocked = validate_success(api.get_batch(batch["id"], PROGRAM))
    assert blocked["status"] == "DRAFT"


def test_10_the_same_claim_succeeds_once_the_pathway_is_certified(api):
    """Certification unblocks the waiting draft and prices it provisionally only.

    PRD: "The `PROVISIONAL` variant deliberately does **not** write `credit_value_cents`: a claimed batch carries no monetary value yet and contributes nothing to any settlement statement."

    Design: Difficulty/cross_entity_state_dependency/ced_credit_batch_claim_blocked_until_parent_pathway_reaches_certified
    """
    plant = setup_two_dairy_injected_day()
    pathway = create_pathway(plant["facility"]["id"])
    batch = create_batch(
        pathway["id"], plant["facility"]["id"], read_pathway_version(pathway["id"])
    )
    validate_error(
        api.claim_batch(batch["id"], {"claim_note": "Early claim attempt"}, PROGRAM),
        "ERR_PATHWAY_NOT_CERTIFIED",
        409,
    )

    certified = certify_pathway(pathway["id"], "2026-08-01", "2026-08-31")
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_ci_score"] == -236.67

    claimed = validate_success(
        api.claim_batch(batch["id"], {"claim_note": "Claim after certification"}, PROGRAM)
    )
    assert claimed["status"] == "CLAIMED"
    assert claimed["delivered_mmbtu"] == 120.280
    assert claimed["ci_score_used"] == -236.67
    assert claimed["credit_quantity_provisional"] == 36.111
    assert claimed["credit_value_cents"] is None
