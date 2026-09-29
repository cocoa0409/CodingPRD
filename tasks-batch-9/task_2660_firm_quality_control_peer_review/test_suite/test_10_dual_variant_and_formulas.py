"""Dual-variant computations and combinatorial formulas.

Covers the two genuinely different residual-risk / severity-index variants and
the three formulas whose operand order, caps and rounding points the PRD pins:
the engagement risk score, the engagement-weighted severity index and the
remediation acceptance score.
"""
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.assertions import assert_decimal_equals, assert_fields, read_entity
from test_helpers.test_users import make_managing_partner_headers

_RESPONSE_SPECS = (
    ("PREVENTIVE", "Mandatory second-partner sign-off on judgemental areas."),
    ("DETECTIVE", "Quarterly file review sample by the QC director."),
    ("PREVENTIVE", "Annual technical training on judgemental estimates."),
)


# ---------------------------------------------------------------------------
# dual_variant_calc / residual_risk_design_basis_cap_vs_operating_basis_fold
# ---------------------------------------------------------------------------
def _two_identical_max_inherent_risks(api):
    """Two identically populated risks: inherent 25, three TESTED EFFECTIVE responses."""
    ctx = fixtures.firm_context(api, legal_name="Calder Mote LLP")
    risk_a = fixtures.new_quality_risk(api, ctx, quality_objective_code="QO-A")
    risk_b = fixtures.new_quality_risk(api, ctx, quality_objective_code="QO-B")
    for risk in (risk_a, risk_b):
        for response_type, description in _RESPONSE_SPECS:
            response = fixtures.new_risk_response(
                api, ctx, risk["id"],
                response_type=response_type, description=description,
            )
            fixtures.record_effectiveness_test(
                api, ctx, response["id"],
                design_effectiveness="EFFECTIVE",
                operating_effectiveness="EFFECTIVE",
            )
    return ctx, risk_a, risk_b


def _evaluate(api, ctx, risk_id, basis):
    return read_entity(
        api.create_risk_evaluation(
            risk_id, f.risk_evaluation_payload(basis), headers=ctx["qc_headers"]
        ),
        expected_status=200,
    )


def test_residual_risk_design_basis_caps_additive_mitigation_at_eighty_hundredths(api):
    """DESIGN_BASIS adds each response's design weight, caps the total at 0.80 and
    rounds once at the end, so inherent 25 with three EFFECTIVE responses reads 5.00.

    "those weights are added together, the total is capped at 0.80, and the
    residual score is the inherent score multiplied by one minus that capped
    mitigation factor, rounded half-up to two decimals once at the end."

    Design: Difficulty/dual_variant_calc/residual_risk_design_basis_cap_vs_operating_basis_fold
    """
    ctx, risk_a, risk_b = _two_identical_max_inherent_risks(api)

    assert_fields(
        read_entity(api.get_quality_risk(risk_a["id"], headers=ctx["qc_headers"])),
        inherent_risk_score=25,
    )
    assert_fields(
        read_entity(api.get_quality_risk(risk_b["id"], headers=ctx["qc_headers"])),
        inherent_risk_score=25,
    )

    evaluated = _evaluate(api, ctx, risk_a["id"], "DESIGN_BASIS")

    assert_fields(
        evaluated,
        inherent_risk_score=25,
        evaluation_basis="DESIGN_BASIS",
        severity_band="MODERATE",
        state="EVALUATED",
    )
    # 0.35 + 0.35 + 0.35 = 1.05 clamped to 0.80, so 25 * (1 - 0.80) = 5.00.
    assert_decimal_equals(evaluated["residual_risk_score"], 5.00)


def test_residual_risk_operating_basis_fold_is_uncapped_and_diverges_from_design(api):
    """OPERATING_BASIS folds the inherent score multiplicatively over the TESTED
    responses with no cap, so the same data reads 8.58/HIGH instead of 5.00/MODERATE.

    "a running value that begins at the inherent score is multiplied, response by
    response in that order, by one minus that response's operating weight ... This
    multiplicative fold has no cap."

    Design: Difficulty/dual_variant_calc/residual_risk_design_basis_cap_vs_operating_basis_fold
    """
    ctx, risk_a, risk_b = _two_identical_max_inherent_risks(api)

    design = _evaluate(api, ctx, risk_a["id"], "DESIGN_BASIS")
    operating = _evaluate(api, ctx, risk_b["id"], "OPERATING_BASIS")

    assert_fields(
        operating,
        inherent_risk_score=25,
        evaluation_basis="OPERATING_BASIS",
        severity_band="HIGH",
        state="EVALUATED",
    )
    # 25 * 0.70 * 0.70 * 0.70 = 8.575, rounded half-up once at the end.
    assert_decimal_equals(operating["residual_risk_score"], 8.58)
    assert_decimal_equals(design["residual_risk_score"], 5.00)
    assert float(design["residual_risk_score"]) != float(
        operating["residual_risk_score"]
    ), "the two variants must disagree on identical input data"
    assert_fields(design, state="EVALUATED")

    firm = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(firm, critical_risk_count=0, risk_posture="STABLE")


# ---------------------------------------------------------------------------
# dual_variant_calc /
#   severity_index_engagement_weighted_vs_firm_pervasive_across_two_cycles
# ---------------------------------------------------------------------------
def _two_cycles_each_one_systemic_material_failure(api):
    """Two structurally identical cycles, each holding one must-select selection
    carrying a single SYSTEMIC MATERIAL_FAILURE in ENGAGEMENT_PERFORMANCE."""
    ctx = fixtures.firm_context(api, legal_name="Dunmore Reach LLP")
    ep2 = fixtures.add_engagement_partner(api, ctx, "Rhea Solt")
    fixtures.released_engagement(
        api, ctx, partner=ctx["ep"], client_name="Alder Foods",
        engagement_type="AUDIT", period_end="2024-06-30",
    )
    fixtures.released_engagement(
        api, ctx, partner=ep2, client_name="Bramble Retail",
        engagement_type="AUDIT", period_end="2025-06-30",
    )

    cycles = []
    for year in (2024, 2025):
        inspection = fixtures.new_inspection(
            api, ctx, inspection_year=year, target_engagement_count=1
        )
        fixtures.run_selector(api, ctx, inspection["id"])
        fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
        selections = fixtures.selections_of(api, ctx, inspection["id"])
        assert len(selections) == 1, f"{year} cycle must select exactly one engagement"
        finding = fixtures.new_finding(
            api, ctx, selections[0]["id"],
            title="Group audit instructions not evidenced",
            sqm_component="ENGAGEMENT_PERFORMANCE",
        )
        fixtures.classify(
            api, ctx, finding["id"], "MATERIAL_FAILURE",
            pervasiveness="SYSTEMIC", affects_report_conclusion=True,
        )
        cycles.append(
            {"inspection": inspection, "selection": selections[0], "finding": finding}
        )
    return ctx, cycles[0], cycles[1]


def test_severity_index_engagement_weighted_honours_the_must_select_multiplier(api):
    """ENGAGEMENT_WEIGHTED rounds each selection's 1.5x must-select weighting first and
    then divides by engagements_selected_count, so 20 raw points read 30.00.

    "each selection's own points are summed from the classification points of its
    findings, multiplied by 1.5 when that selection's `is_must_select` is true ...
    and rounded to two decimals per selection first."

    Design: Difficulty/dual_variant_calc/severity_index_engagement_weighted_vs_firm_pervasive_across_two_cycles
    """
    ctx, first, second = _two_cycles_each_one_systemic_material_failure(api)

    inspection = fixtures.inspection_step(
        api, ctx, first["inspection"]["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )

    assert_fields(inspection, severity_index_basis="ENGAGEMENT_WEIGHTED")
    assert_decimal_equals(inspection["deficiency_severity_index"], 30.00)

    selection = read_entity(
        api.get_inspection_selection(first["selection"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        selection, is_must_select=True, selection_reason="MUST_SELECT_PARTNER_COVERAGE"
    )
    assert_decimal_equals(selection["weighted_points"], 30.00)

    finding = read_entity(
        api.get_inspection_finding(first["finding"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(finding, class_points=20)


def test_severity_index_firm_pervasive_ignores_must_select_and_adds_systemic_bonus(api):
    """FIRM_PERVASIVE takes the largest single component total, adds 5 per SYSTEMIC
    finding and divides by the distinct component count, reading 25.00 not 30.00.

    "the largest single component total is taken ..., 5 points are added for each
    finding whose `pervasiveness` is `SYSTEMIC`, and that sum is divided by the
    number of distinct components represented among the findings."

    Design: Difficulty/dual_variant_calc/severity_index_engagement_weighted_vs_firm_pervasive_across_two_cycles
    """
    ctx, first, second = _two_cycles_each_one_systemic_material_failure(api)

    weighted = fixtures.inspection_step(
        api, ctx, first["inspection"]["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    pervasive = fixtures.inspection_step(
        api, ctx, second["inspection"]["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="FIRM_PERVASIVE",
    )

    assert_fields(pervasive, severity_index_basis="FIRM_PERVASIVE")
    # (20 largest component total + 5 systemic bonus) / 1 represented component.
    assert_decimal_equals(pervasive["deficiency_severity_index"], 25.00)
    assert_decimal_equals(weighted["deficiency_severity_index"], 30.00)
    assert float(weighted["deficiency_severity_index"]) != float(
        pervasive["deficiency_severity_index"]
    ), "the two bases must diverge on structurally identical cycles"

    assert_fields(
        read_entity(
            api.get_inspection_selection(
                second["selection"]["id"], headers=ctx["qc_headers"]
            )
        ),
        is_must_select=True,
    )
    for cycle in (first, second):
        assert_fields(
            read_entity(
                api.get_inspection_finding(
                    cycle["finding"]["id"], headers=ctx["qc_headers"]
                )
            ),
            class_points=20,
        )


# ---------------------------------------------------------------------------
# combinatorial_formula /
#   engagement_risk_score_nested_prior_finding_cap_load_penalty_and_spec_credit
# ---------------------------------------------------------------------------
_FILLER_NAMES = (
    "Filler One", "Filler Two", "Filler Three", "Filler Four", "Filler Five",
    "Filler Six", "Filler Seven", "Filler Eight", "Filler Nine",
)


def _partner_carrying_nine_open_engagements(api):
    """An EBP-specialised partner holding nine PLANNING engagements at a STABLE firm."""
    firm = fixtures.new_firm(api, legal_name="Everwood Tarn LLP")
    partner = fixtures.new_partner(
        api, firm["id"], full_name="Eli Parch",
        designations=["ENGAGEMENT_PARTNER"], industry_specializations=["EBP"],
        cpe_hours_last_3y=200,
    )
    ctx = {"firm_id": firm["id"], "ep": partner}
    for client_name in _FILLER_NAMES:
        fixtures.new_engagement(
            api, ctx, partner=partner, client_name=client_name,
            engagement_type="AUDIT", period_end="2026-01-31",
        )
    return ctx, partner


def _accept_specialised_erisa_engagement(api, ctx, partner):
    return fixtures.new_engagement(
        api, ctx, partner=partner, client_name="Hallow Pension Trust",
        engagement_type="ERISA_AUDIT", period_end="2026-06-30",
        is_public_interest=True, is_first_year_client=True, prior_finding_count_3y=12,
    )


def test_engagement_risk_score_caps_prior_findings_and_clamps_only_at_the_end(api):
    """The risk score sums the type base, first-year, public-interest and capped
    prior-finding points, adds the load penalty and subtracts the specialization
    credit before the 0-100 clamp, giving exactly 70.

    "with the prior-finding contribution capped at 20 points ... The final
    `risk_score` is the signed sum of base plus load penalty minus specialization
    credit, and only then is it clamped into the 0-through-100 range."

    Design: Difficulty/combinatorial_formula/engagement_risk_score_nested_prior_finding_cap_load_penalty_and_spec_credit
    """
    ctx, partner = _partner_carrying_nine_open_engagements(api)
    before = read_entity(api.get_partner(partner["id"], headers=fixtures.ADMIN))
    assert_fields(before, open_engagement_count=9)

    engagement = _accept_specialised_erisa_engagement(api, ctx, partner)

    # 30 base + 15 first-year + 12 public-interest + min(20, 4*12) + (9-8)*3 - 10 = 70.
    assert_fields(engagement, risk_score=70, eqr_required=True)
    assert engagement["risk_score"] != 98, (
        "ignoring the 20-point prior-finding cap would yield 98"
    )


def test_engagement_risk_score_side_effects_load_counter_and_initial_states(api):
    """Accepting the engagement raises the partner's open_engagement_count to ten and
    opens the engagement in PLANNING / OPEN at a firm still posturing STABLE.

    "A newly accepted engagement begins with `workflow_state` `PLANNING` and
    `file_state` `OPEN` ... Its partner's `open_engagement_count` increases by one."

    Design: Difficulty/combinatorial_formula/engagement_risk_score_nested_prior_finding_cap_load_penalty_and_spec_credit
    """
    ctx, partner = _partner_carrying_nine_open_engagements(api)

    engagement = _accept_specialised_erisa_engagement(api, ctx, partner)

    assert_fields(engagement, workflow_state="PLANNING", file_state="OPEN")
    assert_fields(
        read_entity(api.get_partner(partner["id"], headers=fixtures.ADMIN)),
        open_engagement_count=10,
    )
    assert_fields(
        read_entity(api.get_firm(ctx["firm_id"], headers=fixtures.ADMIN)),
        risk_posture="STABLE",
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / severity_index_per_selection_weighting_precedes_aggregation
# ---------------------------------------------------------------------------
def _cycle_with_one_must_select_and_one_risk_based_selection(api):
    """A 2024 cycle whose rank-1 partner-coverage selection carries 20 raw points and
    whose rank-2 risk-based selection carries 3."""
    ctx = fixtures.firm_context(api, legal_name="Grantham Vale LLP")
    fixtures.released_engagement(
        api, ctx, partner=ctx["ep"], client_name="Alder Foods",
        engagement_type="AUDIT", period_end="2024-06-30", is_first_year_client=True,
    )
    fixtures.released_engagement(
        api, ctx, partner=ctx["ep"], client_name="Bramble Retail",
        engagement_type="AUDIT", period_end="2024-09-30",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=2
    )
    fixtures.run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    selections = fixtures.selections_of(api, ctx, inspection["id"])
    assert len(selections) == 2, "the cycle must hold exactly two selections"

    first = fixtures.new_finding(
        api, ctx, selections[0]["id"],
        title="Revenue recognition conclusion unsupported",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    fixtures.classify(
        api, ctx, first["id"], "MATERIAL_FAILURE",
        pervasiveness="SYSTEMIC", affects_report_conclusion=True,
    )
    second = fixtures.new_finding(
        api, ctx, selections[1]["id"],
        title="Engagement acceptance checklist incomplete",
        sqm_component="RESOURCES",
    )
    fixtures.classify(
        api, ctx, second["id"], "DEFICIENCY",
        pervasiveness="ISOLATED", affects_report_conclusion=False,
    )
    return ctx, inspection, selections


def test_severity_index_rounds_each_selection_before_summing_and_dividing(api):
    """Weighting each selection before aggregation gives (30.00 + 3.00) / 2 = 16.50, not
    the 17.25 that summing raw points and multiplying the aggregate would produce.

    "those already-rounded `weighted_points` are then summed across the cycle's
    selections, divided by `engagements_selected_count`, and rounded half-up to two
    decimals once."

    Design: Difficulty/combinatorial_formula/severity_index_per_selection_weighting_precedes_aggregation
    """
    ctx, inspection, selections = _cycle_with_one_must_select_and_one_risk_based_selection(api)

    classified = fixtures.inspection_step(
        api, ctx, inspection["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )

    assert_fields(classified, state="FINDINGS_CLASSIFIED", engagements_selected_count=2)
    assert_decimal_equals(classified["deficiency_severity_index"], 16.50)
    assert round(float(classified["deficiency_severity_index"]), 2) != 17.25, (
        "applying the must-select multiplier to the aggregate would yield 17.25"
    )


def test_severity_index_pins_each_selections_own_weighted_points(api):
    """The must-select selection stores 30.00 weighted points and the risk-based one
    stores 3.00, which are the already-rounded operands of the cycle index.

    "Block C selections record `selection_reason` `RISK_BASED` and `is_must_select`
    false."

    Design: Difficulty/combinatorial_formula/severity_index_per_selection_weighting_precedes_aggregation
    """
    ctx, inspection, selections = _cycle_with_one_must_select_and_one_risk_based_selection(api)

    fixtures.inspection_step(
        api, ctx, inspection["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )

    must_select = read_entity(
        api.get_inspection_selection(selections[0]["id"], headers=ctx["qc_headers"])
    )
    risk_based = read_entity(
        api.get_inspection_selection(selections[1]["id"], headers=ctx["qc_headers"])
    )

    assert_fields(
        must_select,
        selection_reason="MUST_SELECT_PARTNER_COVERAGE",
        is_must_select=True,
    )
    assert_decimal_equals(must_select["weighted_points"], 30.00)
    assert_fields(risk_based, selection_reason="RISK_BASED", is_must_select=False)
    assert_decimal_equals(risk_based["weighted_points"], 3.00)


# ---------------------------------------------------------------------------
# combinatorial_formula / acceptance_score_tier_derived_from_raw_completeness_only
# ---------------------------------------------------------------------------
def _plan_ready_for_late_submission(api):
    """A DRAFTED plan citing a depth-10.00 analysis, with the clock 30 days past target."""
    ctx = fixtures.firm_context(api, legal_name="Halberd Cross LLP")
    fixtures.released_engagement(
        api, ctx, partner=ctx["ep"], client_name="Alder Foods",
        engagement_type="AUDIT", period_end="2024-06-30",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=1
    )
    fixtures.run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]

    finding = fixtures.new_finding(
        api, ctx, selection["id"], title="Sampling documentation incomplete",
        sqm_component="ENGAGEMENT_PERFORMANCE", prior_cycle_recurrence=False,
    )
    fixtures.classify(
        api, ctx, finding["id"], "DEFICIENCY",
        pervasiveness="ISOLATED", affects_report_conclusion=False,
    )
    rca = fixtures.validated_rca(
        api, ctx, finding["id"], method="FISHBONE",
        root_cause_category="SUPERVISION_REVIEW", contributing_factor_count=4,
        narrative="Reviewer workload prevented timely review of sampling workpapers.",
    )

    owner = ctx["mp"]
    owner_headers = make_managing_partner_headers(owner["id"])
    current = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )
    plan = read_entity(
        api.create_remediation_plan(
            finding["id"],
            f.remediation_plan_payload(
                rca["id"], owner["id"], current["version"],
                target_completion_date="2026-09-01", action_count=5,
                action_specificity_score=8.00,
            ),
            headers=owner_headers,
        ),
        expected_status=201,
    )
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    return ctx, finding, rca, plan, owner_headers


def _submit_and_accept(api, ctx, plan, owner_headers):
    submitted = read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("SUBMITTED", completed_action_count=5),
            headers=owner_headers,
        ),
        expected_status=200,
    )
    accepted = fixtures.plan_step(api, ctx, plan["id"], "ACCEPTED")
    return submitted, accepted


def test_acceptance_score_tier_comes_from_raw_completeness_not_from_the_penalised_score(api):
    """raw_completeness 9.30 tiers STRONG, so exactly one penalty pass at 0.05 a day over
    30 late days yields 7.80 rather than the circular reading's 6.30.

    "the tier is derived from `raw_completeness` and never re-derived from
    `acceptance_score`, and exactly one penalty pass runs per submission."

    Design: Difficulty/combinatorial_formula/acceptance_score_tier_derived_from_raw_completeness_only
    """
    ctx, finding, rca, plan, owner_headers = _plan_ready_for_late_submission(api)

    submitted, accepted = _submit_and_accept(api, ctx, plan, owner_headers)

    # 0.40*10.00 + 0.35*8.00 + 0.25*(10*5/5) = 4.00 + 2.80 + 2.50 = 9.30.
    assert_decimal_equals(submitted["raw_completeness"], 9.30)
    assert_fields(submitted, completeness_tier="STRONG")
    assert_decimal_equals(submitted["acceptance_score"], 7.80)
    assert round(float(submitted["acceptance_score"]), 2) != 6.30, (
        "re-tiering the penalised score as STANDARD would charge 0.10 a day and give 6.30"
    )
    assert_fields(accepted, state="ACCEPTED", return_count=0, completeness_tier="STRONG")
    assert_decimal_equals(accepted["acceptance_score"], 7.80)


def test_acceptance_of_a_strong_plan_cascades_onto_the_finding_and_its_counters(api):
    """The cited analysis reads depth_score 10.00 with recurrence_flag false, and clearing
    the 7.00 threshold drives the finding to REMEDIATED while it stays an open deficiency.

    "Acceptance stamps `accepted_at` from the logical clock and cascades onto the
    finding, driving it `REMEDIATION_ASSIGNED` -> `REMEDIATED`; note that a
    `REMEDIATED` finding is still an open finding."

    Design: Difficulty/combinatorial_formula/acceptance_score_tier_derived_from_raw_completeness_only
    """
    ctx, finding, rca, plan, owner_headers = _plan_ready_for_late_submission(api)

    assert_decimal_equals(rca["depth_score"], 10.00)
    assert_fields(rca, recurrence_flag=False)

    _submit_and_accept(api, ctx, plan, owner_headers)

    assert_fields(
        read_entity(api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])),
        state="REMEDIATED",
    )
    assert_fields(
        read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"])),
        open_deficiency_count=1,
    )
