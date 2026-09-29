"""Annual verification: how one set of findings revalues issued credits, rewrites the
settlement waterfall and tightens the lender covenant, and how the loop is bounded."""
from test_helpers import (
    ADMIN,
    FINANCE_A,
    OPERATOR,
    PROGRAM,
    VERIFIER,
    assert_credit_control_holds,
    create_audit,
    issue_findings,
    open_remediation,
    record_fieldwork,
    setup_certified_pathway,
    setup_two_dairy_statement,
    validate_error,
    validate_success,
)

MATERIAL_ACTUALS = {
    "actual_pipeline_mmbtu": 120.500,
    "actual_vs_tonnes_lagoon": 9.500,
    "actual_vs_tonnes_solid_storage": 5.600,
    "actual_vs_tonnes_daily_spread": 0.000,
    "actual_haul_tonne_km": 5040.00,
    "actual_process_g_per_mj": 15.95,
}

MINOR_ACTUALS = {
    "actual_pipeline_mmbtu": 120.280,
    "actual_vs_tonnes_lagoon": 9.840,
    "actual_vs_tonnes_solid_storage": 0.000,
    "actual_vs_tonnes_daily_spread": 0.000,
    "actual_haul_tonne_km": 1800.00,
    "actual_process_g_per_mj": 16.90,
}


def _month_awaiting_findings():
    """Two dairies, issued August credits, a DSCR sitting exactly on the covenant."""
    plant = setup_two_dairy_statement()
    audit = create_audit(plant["pathway"]["id"])
    plant["audit"] = record_fieldwork(audit["id"], **MATERIAL_ACTUALS)
    return plant


def test_01_material_findings_suspend_the_pathway_and_record_the_delta(api):
    """The auditor's own numbers move the intensity 9.69 grams the wrong way.

    PRD: "The severity classification works on the absolute value of `ci_delta`, compared at 2 decimal places on the already-rounded delta: `finding_severity` is `NONE` when that absolute value is exactly 0.00, `MINOR` when it is greater than 0.00 and less than or equal to the material tolerance of 2.00 — the minor band is closed at the top, so a delta of exactly 2.00 is still `MINOR` — and `MATERIAL` when it is strictly greater than 2.00."

    Design: Difficulty/transitive_cascade/tc_material_finding_suspends_pathway_revalues_batch_recomputes_statement_restricts_distribution
    """
    plant = _month_awaiting_findings()
    assert plant["pathway"]["certified_ci_score"] == -236.67
    assert plant["audit"]["reported_ci_score"] == -226.98
    assert plant["audit"]["ci_delta"] == 9.69

    audit = validate_success(
        api.issue_findings(
            plant["audit"]["id"],
            {
                "narrative": "Metered volumes and haul logs disagree with the certified pathway inputs"
            },
            VERIFIER,
        )
    )
    assert audit["finding_severity"] == "MATERIAL"
    assert audit["status"] == "FINDINGS_ISSUED"

    pathway = validate_success(api.get_pathway(plant["pathway"]["id"], PROGRAM))
    assert pathway["status"] == "SUSPENDED"
    assert pathway["verified_ci_score"] == -226.98
    assert pathway["ci_adjustment"] == 9.69


def test_02_the_issued_batch_is_revalued_without_leaving_the_issued_state(api):
    """The credit quantity is recomputed from the verified intensity, not the certified one.

    PRD: "When `finding_severity` is `MATERIAL`, the pathway moves `CERTIFIED → SUSPENDED`, `verified_ci_score` is set from `reported_ci_score` and `ci_adjustment` to `verified_ci_score` less `certified_ci_score`, and the cascade runs: because `verified_ci_score` changed, every batch of that pathway whose status is `VERIFIED` or `ISSUED` recomputes `ci_score_used`, `credit_quantity_final` and `credit_value_cents` from the `FINAL` variant of the credit quantity calculation; `credits_issued_total`, `credits_reversed_total`, `credits_outstanding` and `credit_control_residual` are then recomputed, with the residual required to remain 0.000; and because the issued batches' `credit_value_cents` have changed, every `DRAFT` revenue statement whose period contains an affected batch's period recomputes its `credit_revenue_cents` and its whole waterfall, which in turn re-derives the facility's `dscr_current` and `distribution_posture`."

    Design: Difficulty/transitive_cascade/tc_material_finding_suspends_pathway_revalues_batch_recomputes_statement_restricts_distribution
    """
    plant = _month_awaiting_findings()
    assert plant["batch"]["credit_quantity_final"] == 36.111
    assert plant["batch"]["credit_value_cents"] == 269027

    issue_findings(plant["audit"]["id"], "Metered volumes disagree with the pathway inputs")

    batch = validate_success(api.get_batch(plant["batch"]["id"], PROGRAM))
    assert batch["ci_score_used"] == -226.98
    assert batch["credit_quantity_final"] == 35.004
    assert batch["credit_value_cents"] == 260780
    assert batch["status"] == "ISSUED"

    pathway = validate_success(api.get_pathway(plant["pathway"]["id"], PROGRAM))
    assert pathway["credits_issued_total"] == 35.004
    assert pathway["credits_outstanding"] == 35.004
    assert pathway["credit_control_residual"] == 0.000
    assert_credit_control_holds(pathway)


def test_03_the_draft_statement_recomputes_its_whole_waterfall(api):
    """A smaller credit line walks through fee, sweep, shares and retention.

    PRD: "For each participating agreement, the base amount is `net_distributable_cents` when its `revenue_share_basis` is `NET` and `gross_revenue_cents` when it is `GROSS`."

    Design: Difficulty/transitive_cascade/tc_material_finding_suspends_pathway_revalues_batch_recomputes_statement_restricts_distribution
    """
    plant = _month_awaiting_findings()
    assert plant["statement"]["net_distributable_cents"] == 1406289

    issue_findings(plant["audit"]["id"], "Metered volumes disagree with the pathway inputs")

    statement = validate_success(api.get_statement(plant["statement"]["id"], FINANCE_A))
    assert statement["credit_revenue_cents"] == 260780
    assert statement["gross_revenue_cents"] == 1997156
    assert statement["management_fee_cents"] == 129815
    assert statement["after_fee_cents"] == 1867341
    assert statement["reserve_sweep_cents"] == 466835
    assert statement["net_distributable_cents"] == 1400506
    assert statement["share_lines"][0]["share_cents"] == 308111
    assert statement["share_lines"][1]["share_cents"] == 299573
    assert statement["total_dairy_share_cents"] == 607684
    assert statement["retained_cents"] == 792822
    assert statement["status"] == "DRAFT"


def test_04_the_recomputed_covenant_restricts_distributions(api):
    """The debt-service ratio slips from exactly 1.250 to 1.245 and closes the tap.

    PRD: "The facility's `distribution_posture` is then `OPEN` when `dscr_at_close` is greater than or equal to `dscr_minimum` — the boundary is inclusive, so meeting the covenant exactly keeps distributions open."

    Design: Difficulty/transitive_cascade/tc_material_finding_suspends_pathway_revalues_batch_recomputes_statement_restricts_distribution
    """
    plant = _month_awaiting_findings()
    assert plant["statement"]["dscr_at_close"] == 1.250
    before = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert before["distribution_posture"] == "OPEN"

    issue_findings(plant["audit"]["id"], "Metered volumes disagree with the pathway inputs")

    statement = validate_success(api.get_statement(plant["statement"]["id"], FINANCE_A))
    assert statement["dscr_at_close"] == 1.245

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["dscr_current"] == 1.245
    assert facility["distribution_posture"] == "RESTRICTED"
    assert facility["posture_override_active"] is False


def test_05_a_third_remediation_round_is_refused_while_the_findings_stand(api):
    """Two rounds of corrective action are all the audit allows, minor findings or not.

    PRD: "It is permitted only when `finding_severity` is `MINOR` or `MATERIAL` — a clean audit has nothing to remediate — and only while `remediation_round` is below two; a third remediation round on the same audit is rejected with `ERR_REMEDIATION_ROUNDS_EXHAUSTED`."

    Design: Corner/validations/validation_third_remediation_round_is_refused
    """
    plant = setup_certified_pathway()
    assert plant["pathway"]["certified_ci_score"] == -190.40
    audit = create_audit(plant["pathway"]["id"])
    audit = record_fieldwork(audit["id"], **MINOR_ACTUALS)
    assert audit["reported_ci_score"] == -188.90
    assert audit["ci_delta"] == 1.50
    issue_findings(audit["id"], "Parasitic load above the certified assumption")

    open_remediation(audit["id"], "Install submetering on the blower skid")
    record_fieldwork(audit["id"], **MINOR_ACTUALS)
    issue_findings(audit["id"], "Submetering not yet in service")
    second = open_remediation(audit["id"], "Complete commissioning of the submeters")
    assert second["remediation_round"] == 2
    record_fieldwork(audit["id"], **MINOR_ACTUALS)
    issue_findings(audit["id"], "Parasitic load still above the certified assumption")

    validate_error(
        api.open_remediation(
            audit["id"], {"remediation_plan": "Third corrective action plan"}, OPERATOR
        ),
        "ERR_REMEDIATION_ROUNDS_EXHAUSTED",
        422,
    )

    frozen = validate_success(api.get_audit(audit["id"], VERIFIER))
    assert frozen["status"] == "FINDINGS_ISSUED"
    assert frozen["remediation_round"] == 2
    assert frozen["reported_ci_score"] == -188.90
    assert frozen["ci_delta"] == 1.50
    assert frozen["finding_severity"] == "MINOR"

    pathway = validate_success(api.get_pathway(plant["pathway"]["id"], PROGRAM))
    assert pathway["status"] == "CERTIFIED"
    assert pathway["certified_ci_score"] == -190.40
    assert pathway["verified_ci_score"] == -188.90
    assert pathway["ci_adjustment"] == 1.50
