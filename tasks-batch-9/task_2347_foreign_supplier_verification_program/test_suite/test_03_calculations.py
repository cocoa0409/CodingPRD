"""Derived scores: hazard risk, composite risk, coverage adequacy, retention."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_hazard_scores, assert_money, assert_supplier_performance
from test_helpers.test_users import make_qualified_individual_headers

# The ready-to-eat, non-RAC, GENERAL-consumer food the mango pair is built on.
RTE_FOOD = dict(
    food_name="Frozen mango chunks",
    fda_product_code="20-MAN-01",
    is_raw_agricultural_commodity=False,
    intended_consumer_group="GENERAL",
    ready_to_eat=True,
)

HAZARD_LISTERIA = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Listeria monocytogenes",
    severity=4,
    probability=3,
    control_owner="FOREIGN_SUPPLIER",
)
HAZARD_SANITIZER = dict(
    hazard_type="CHEMICAL_INCL_RADIOLOGICAL",
    hazard_name="Residual sanitizer carryover",
    severity=3,
    probability=2,
    control_owner="IMPORTER",
)

METHODOLOGY_NOTE = "Codex hazard identification for frozen ready-to-eat fruit"


def test_hazard_risk_score_ready_to_eat_biological_hazard(api: ApiClient):
    """PRD §3.3: "Multiply that by the exposure multiplier selected by the food's
    `intended_consumer_group`: 1.0 for `GENERAL`, 1.1 for `ELDERLY`, 1.25 for
    `IMMUNOCOMPROMISED`, and 1.4 for `INFANT`."
    PRD §3.3: "Multiply by a ready-to-eat penalty of 1.15 when the food's
    `ready_to_eat` is true *and* the `hazard_type` is `BIOLOGICAL`, and by 1.00
    otherwise."
    PRD §3.3: "A hazard's `requires_control` flag is true exactly when its
    `risk_score` is at or above 12.00 — the boundary is inclusive, so a hazard
    scoring exactly 12.00 *is* a significant hazard requiring a control."
    PRD §3.3: "The `risk_total` is the sum of the `risk_score` values of every
    hazard in the analysis, whether or not they require control, rounded half up
    to two decimal places."

    Design: Corner/calculations/hazard_risk_score_correct_result_for_ready_to_eat_biological_hazard
    """
    world = fx.base_program(
        api, evaluate_supplier_first=False, food_overrides=dict(RTE_FOOD)
    )
    analysis = fx.create_hazard_analysis(
        api, world.pair_id, world.qi_a_id, methodology_note=METHODOLOGY_NOTE
    )

    hazard = validate_success(
        api.create_hazard(
            analysis["id"],
            f.hazard_payload(**HAZARD_LISTERIA),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        201,
    )

    # 4 x 3 x GENERAL 1.0 x rac relief 1.00 x rte penalty 1.15 x FOREIGN_SUPPLIER 1.00
    assert_hazard_scores(hazard, 13.80, True)
    rolled_up = fx.get_analysis(api, analysis["id"])
    assert rolled_up["hazard_count"] == 1, f"hazard_count: {rolled_up['hazard_count']}"
    assert rolled_up["significant_hazard_count"] == 1, (
        f"significant_hazard_count: {rolled_up['significant_hazard_count']}"
    )
    assert_money(rolled_up["risk_total"], 13.80, "analysis.risk_total")


def test_hazard_load_excludes_hazard_below_significance_threshold(api: ApiClient):
    """PRD §3.3: "**Step one** derives the hazard load and the gross risk: the
    hazard load is the sum of the `risk_score` values of only those hazards in the
    active analysis whose `requires_control` is true, rounded half up to two
    decimal places, and it is 0.00 when `active_hazard_analysis_id` is null; the
    gross risk is that hazard load plus the supplier penalty selected by the
    supplier's `regulatory_compliance_status` — 0.00 for `NO_ADVERSE_FINDINGS`,
    6.00 for `WARNING_LETTER`, 15.00 for `IMPORT_ALERT`, and 25.00 for
    `REGISTRATION_SUSPENDED` — again rounded half up to two decimal places."
    PRD §3.3: "Because only controlled-significant hazards enter the hazard load,
    a hazard scoring below 12.00 contributes to the analysis's `risk_total` but not
    to the combination's composite risk."
    PRD §3.3: "Approval also recomputes the combination's
    `uncontrolled_significant_hazard_count` — the number of hazards in the newly
    active analysis whose `requires_control` is true and whose `control_owner` is
    `FOREIGN_SUPPLIER` or `SUPPLIER_OF_SUPPLIER`, that is, the significant hazards
    the importer does not itself control — along with `composite_hazard_risk`,
    `risk_tier`, `required_annual_frequency`, `required_coverage` and both
    adequacy variants, and increments the combination's `version` by one."

    Design: Corner/calculations/hazard_load_excludes_hazard_below_significance_threshold
    """
    world = fx.base_program(
        api, evaluate_supplier_first=False, food_overrides=dict(RTE_FOOD)
    )
    analysis = fx.create_hazard_analysis(
        api, world.pair_id, world.qi_a_id, methodology_note=METHODOLOGY_NOTE
    )
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **HAZARD_LISTERIA)
    # 3 x 2 x GENERAL 1.0 x 1.00 x 1.00 x IMPORTER 0.70 = 4.20, below 12.00.
    chemical = fx.add_hazard(api, analysis["id"], world.qi_a_id, **HAZARD_SANITIZER)

    validate_success(
        api.post_hazard_analysis_approval(
            analysis["id"],
            f.hazard_analysis_approval_payload(
                approval_note=(
                    "Two hazards identified; only the pathogen requires a supplier control"
                )
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        200,
    )

    assert_hazard_scores(chemical, 4.20, False)
    rolled_up = fx.get_analysis(api, analysis["id"])
    assert rolled_up["hazard_count"] == 2, f"hazard_count: {rolled_up['hazard_count']}"
    assert rolled_up["significant_hazard_count"] == 1, (
        f"significant_hazard_count: {rolled_up['significant_hazard_count']}"
    )
    assert_money(rolled_up["risk_total"], 18.00, "analysis.risk_total")

    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["composite_hazard_risk"], 13.80, "pair.composite_hazard_risk")
    assert pair["risk_tier"] == "LOW", f"risk_tier: {pair['risk_tier']}"
    assert pair["required_annual_frequency"] == 1, (
        f"required_annual_frequency: {pair['required_annual_frequency']}"
    )
    assert_money(pair["required_coverage"], 20.70, "pair.required_coverage")
    assert pair["uncontrolled_significant_hazard_count"] == 1, (
        f"uncontrolled_significant_hazard_count: "
        f"{pair['uncontrolled_significant_hazard_count']}"
    )


def test_hazard_risk_score_rounds_half_up_at_the_third_decimal(api: ApiClient):
    """PRD §2.8: "Rounding half up means a digit sequence exactly at the midpoint
    rounds away from zero: 12.345 becomes 12.35."
    PRD §3.3: "Finally multiply by the control factor selected by `control_owner`:
    1.00 for `FOREIGN_SUPPLIER`, 1.10 for `SUPPLIER_OF_SUPPLIER`, 0.70 for
    `IMPORTER`, and 0.55 for `CUSTOMER_DOWNSTREAM`."
    PRD §3.3: "The resulting product is clamped so that anything below 1.00 becomes
    1.00 and anything above 25.00 becomes 25.00, and the clamped value is then
    rounded half up to two decimal places to give `risk_score`."
    PRD §3.3: "and `required_coverage` is `composite_hazard_risk` multiplied by
    1.5, rounded half up to two decimal places."

    Design: Corner/calculations/hazard_risk_score_rounds_half_up_at_the_third_decimal
    """
    world = fx.base_program(
        api,
        evaluate_supplier_first=False,
        food_overrides=dict(
            food_name="Medical nutrition powder base",
            fda_product_code="40-MNP-07",
            is_raw_agricultural_commodity=False,
            intended_consumer_group="IMMUNOCOMPROMISED",
            ready_to_eat=False,
        ),
    )
    analysis = fx.create_hazard_analysis(
        api,
        world.pair_id,
        world.qi_a_id,
        methodology_note="Chemical hazard review for a medical nutrition ingredient",
    )

    # 3 x 3 x IMMUNOCOMPROMISED 1.25 x SUPPLIER_OF_SUPPLIER 1.10 = 12.375 -> 12.38.
    hazard = validate_success(
        api.create_hazard(
            analysis["id"],
            f.hazard_payload(
                hazard_type="CHEMICAL_INCL_RADIOLOGICAL",
                hazard_name="Heavy metal carryover from mineral premix",
                severity=3,
                probability=3,
                control_owner="SUPPLIER_OF_SUPPLIER",
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        201,
    )
    validate_success(
        api.post_hazard_analysis_approval(
            analysis["id"],
            f.hazard_analysis_approval_payload(
                approval_note=(
                    "Supplier of supplier premix control confirmed as the applicable control"
                )
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        200,
    )

    assert_hazard_scores(hazard, 12.38, True)
    assert_money(
        fx.get_analysis(api, analysis["id"])["risk_total"], 12.38, "analysis.risk_total"
    )
    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["composite_hazard_risk"], 12.38, "pair.composite_hazard_risk")
    assert pair["risk_tier"] == "LOW", f"risk_tier: {pair['risk_tier']}"
    assert_money(pair["required_coverage"], 18.57, "pair.required_coverage")


def test_pair_risk_tier_boundary_at_gross_exactly_eighteen_is_moderate(api: ApiClient):
    """PRD §3.3: "**Step two** fixes `risk_tier` from the gross risk and from
    nothing else: `HIGH` when gross risk is at or above 40.00, otherwise
    `MODERATE` when it is at or above 18.00, otherwise `LOW`. Both boundaries are
    inclusive."
    PRD §3.3: "**Step three** computes a performance relief. The relief base is
    0.00 for a `LOW` tier, 4.00 for `MODERATE`, and 9.00 for `HIGH`. The relief
    factor is 1.0 when the supplier's `performance_score_final` is at or above
    85.00, 0.5 when it is at or above 70.00, and 0.0 otherwise."
    PRD §3.3: "**Step five** reads the plan requirements off the tier fixed in step
    two and never re-derives that tier from the composite:
    `required_annual_frequency` is 1 for a `LOW` tier, 2 for `MODERATE`, and 4 for
    `HIGH`; and `required_coverage` is `composite_hazard_risk` multiplied by 1.5,
    rounded half up to two decimal places."

    Design: Corner/calculations/pair_risk_tier_boundary_at_gross_exactly_eighteen_is_moderate
    """
    world = fx.base_program(
        api,
        evaluate_supplier_first=False,
        supplier_overrides=dict(
            name="Andes Grain SAC",
            facility_registration_number="FRN-PE-88002",
            regulatory_compliance_status="WARNING_LETTER",
        ),
        food_overrides=dict(
            food_name="Milled quinoa flour",
            fda_product_code="20-QUI-11",
            is_raw_agricultural_commodity=False,
            intended_consumer_group="GENERAL",
            ready_to_eat=False,
        ),
    )
    analysis = fx.create_hazard_analysis(
        api,
        world.pair_id,
        world.qi_a_id,
        methodology_note="Mycotoxin hazard review for milled cereal products",
    )
    # 4 x 3 with every multiplier at 1.00 -> exactly 12.00, a significant hazard.
    hazard = fx.add_hazard(
        api,
        analysis["id"],
        world.qi_a_id,
        hazard_type="CHEMICAL_INCL_RADIOLOGICAL",
        hazard_name="Ochratoxin A",
        severity=4,
        probability=3,
        control_owner="FOREIGN_SUPPLIER",
    )

    validate_success(
        api.post_hazard_analysis_approval(
            analysis["id"],
            f.hazard_analysis_approval_payload(
                approval_note="Mycotoxin control assigned to the foreign supplier"
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        200,
    )

    assert_hazard_scores(hazard, 12.00, True)
    pair = fx.get_pair(api, world.pair_id)
    assert pair["risk_tier"] == "MODERATE", f"risk_tier: {pair['risk_tier']}"
    assert_money(pair["composite_hazard_risk"], 14.00, "pair.composite_hazard_risk")
    assert pair["required_annual_frequency"] == 2, (
        f"required_annual_frequency: {pair['required_annual_frequency']}"
    )
    assert_money(pair["required_coverage"], 21.00, "pair.required_coverage")


def test_hazard_analysis_risk_total_running_total_after_each_hazard_add(api: ApiClient):
    """PRD §3.3: "Writing a hazard recomputes its analysis's `hazard_count` as the
    number of hazard rows, its `significant_hazard_count` as the number of those
    rows whose `requires_control` is true, and its `risk_total`."
    PRD §3.3: "Because each `risk_score` was already rounded to two decimal places
    when its hazard was written, this is a round-then-sum: the already-rounded
    per-hazard values are added, and the sum is rounded."
    PRD §3.3: "the hazard load is the sum of the `risk_score` values of only those
    hazards in the active analysis whose `requires_control` is true, rounded half
    up to two decimal places, and it is 0.00 when `active_hazard_analysis_id` is
    null"

    Design: Corner/calculations/hazard_analysis_risk_total_running_total_after_each_hazard_add
    """
    world = fx.base_program(
        api, evaluate_supplier_first=False, food_overrides=dict(RTE_FOOD)
    )
    analysis = fx.create_hazard_analysis(
        api, world.pair_id, world.qi_a_id, methodology_note=METHODOLOGY_NOTE
    )

    fx.add_hazard(api, analysis["id"], world.qi_a_id, **HAZARD_LISTERIA)
    after_first = fx.get_analysis(api, analysis["id"])
    assert_money(after_first["risk_total"], 13.80, "analysis.risk_total after one hazard")
    assert after_first["hazard_count"] == 1, f"hazard_count: {after_first['hazard_count']}"
    assert after_first["significant_hazard_count"] == 1, (
        f"significant_hazard_count: {after_first['significant_hazard_count']}"
    )

    fx.add_hazard(api, analysis["id"], world.qi_a_id, **HAZARD_SANITIZER)
    after_second = fx.get_analysis(api, analysis["id"])
    assert_money(after_second["risk_total"], 18.00, "analysis.risk_total after two hazards")
    assert after_second["hazard_count"] == 2, f"hazard_count: {after_second['hazard_count']}"
    assert after_second["significant_hazard_count"] == 1, (
        f"significant_hazard_count: {after_second['significant_hazard_count']}"
    )
    assert after_second["status"] == "DRAFT", f"analysis.status: {after_second['status']}"

    # No analysis has been approved, so the pair's hazard load is still empty.
    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["composite_hazard_risk"], 0.00, "pair.composite_hazard_risk")


def test_adequacy_frequency_cap_and_score_ceiling_honored(api: ApiClient):
    """PRD §3.4: "Concretely, the activity's `coverage_weight` is the type weight
    for its `activity_type` — 10.0 for `ONSITE_AUDIT`, 6.0 for
    `SAMPLING_AND_TESTING`, 3.0 for `RECORDS_REVIEW`, and 2.0 for
    `OTHER_SUPPLIER_EVALUATION` — multiplied by the smaller of its
    `frequency_per_year` and 4, multiplied by a justification factor of 1.0 when
    `justification_text` is at least 40 characters long and 0.5 otherwise, with the
    product rounded half up to two decimal places."
    PRD §3.4: "Divide 100.00 times that sum by the larger of the combination's
    `required_coverage` and 1.00 — the denominator floor of 1.00 keeps a
    zero-coverage combination from dividing by zero. Cap the quotient at 100.00 and
    round it half up to two decimal places."
    PRD §3.4: "The **PLANNED** variant, surfaced as `adequacy_score_planned`, takes
    as its input set every activity on the combination whose `status` is
    `APPROVED`; it is recomputed whenever an activity's status or fields change,
    when a hazard analysis is approved, and when the supplier's compliance status
    or final performance score moves, and it is the variant that gates
    verification approval."

    Design: Corner/calculations/adequacy_frequency_cap_and_score_ceiling_honored
    """
    world = fx.analyzed_program(
        api, hazards=[HAZARD_LISTERIA], food_overrides=dict(RTE_FOOD)
    )
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=6,
        justification_text=(
            "Six sampling events per year were selected because the pathogen profile "
            "of this ready to eat fruit warrants bi-monthly testing"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )

    validate_success(
        api.post_activity_review(
            activity["id"],
            f.activity_review_payload(
                "APPROVE", reviewer_note="Bi-monthly sampling plan approved as written"
            ),
            make_qualified_individual_headers(world.qi_b_id),
        ),
        200,
    )

    approved = fx.get_activity(api, activity["id"])
    assert approved["frequency_per_year"] == 6, (
        f"frequency_per_year: {approved['frequency_per_year']}"
    )
    # 6.0 x min(6, 4) x 1.0 = 24.00; the raw ratio 115.94 is capped at 100.00.
    assert_money(approved["coverage_weight"], 24.00, "activity.coverage_weight")
    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["adequacy_score_planned"], 100.00, "pair.adequacy_score_planned")
    assert_money(pair["required_coverage"], 20.70, "pair.required_coverage")
    assert pair["required_annual_frequency"] == 1, (
        f"required_annual_frequency: {pair['required_annual_frequency']}"
    )


def test_adequacy_short_justification_halves_coverage_weight(api: ApiClient):
    """PRD §3.4: "A justification that clears 20 characters but is shorter than 40
    characters is accepted and halves the activity's contribution to coverage."
    PRD §3.4: "Concretely, the activity's `coverage_weight` is the type weight for
    its `activity_type` — 10.0 for `ONSITE_AUDIT`, 6.0 for `SAMPLING_AND_TESTING`,
    3.0 for `RECORDS_REVIEW`, and 2.0 for `OTHER_SUPPLIER_EVALUATION` — multiplied
    by the smaller of its `frequency_per_year` and 4, multiplied by a justification
    factor of 1.0 when `justification_text` is at least 40 characters long and 0.5
    otherwise, with the product rounded half up to two decimal places."
    PRD §3.4: "The **REALIZED** variant, surfaced as `adequacy_score_realized`,
    takes as its input set the `APPROVED` activities that have at least one
    verification record with `record_status` `ATTESTED`; it is recomputed on record
    attestation and rescission and is reporting-only — it never blocks a write."

    Design: Corner/calculations/adequacy_short_justification_halves_coverage_weight
    """
    world = fx.analyzed_program(
        api, hazards=[HAZARD_LISTERIA], food_overrides=dict(RTE_FOOD)
    )
    # 26 characters: past the 20-character floor, short of the 40-character bonus.
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=3,
        justification_text="Quarterly port sampling ok",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )

    validate_success(
        api.post_activity_review(
            activity["id"],
            f.activity_review_payload(
                "APPROVE",
                reviewer_note="Frequency accepted although the written justification is thin",
            ),
            make_qualified_individual_headers(world.qi_b_id),
        ),
        200,
    )

    # 6.0 x min(3, 4) x 0.5 = 9.00, so 100 x 9.00 / 20.70 = 43.48.
    assert_money(
        fx.get_activity(api, activity["id"])["coverage_weight"],
        9.00,
        "activity.coverage_weight",
    )
    pair = fx.get_pair(api, world.pair_id)
    assert_money(pair["adequacy_score_planned"], 43.48, "pair.adequacy_score_planned")
    assert_money(pair["adequacy_score_realized"], 0.00, "pair.adequacy_score_realized")


def test_adequacy_variant_selection_planned_gates_approval_while_realized_is_zero(
    api: ApiClient,
):
    """PRD §3.5: "And `adequacy_score_planned` must be at least the applicable
    adequacy floor — 30.00 when the combination's `modified_requirements_only` is
    true, and 60.00 otherwise — or `ERR_ADEQUACY_BELOW_FLOOR`."
    PRD §3.4: "Because the realized input set is a subset of the planned one, the
    planned score is always at least the realized score."
    PRD §3.5: "A successful approval sets `verification_status` to
    `VERIFICATION_APPROVED`, sets `last_reassessed_at` to the logical clock,
    recomputes `reassessment_due_at` as that instant advanced by 36 calendar
    months, increments the combination's `version` by one, and recomputes the
    importer's `program_status`. It also drives the second dimension:
    `entry_eligibility_status` moves `PENDING → ELIGIBLE` inside the same request."
    PRD §2.7: "Otherwise the importer is `COMPLIANT`."

    Design: Corner/calculations/adequacy_variant_selection_planned_gates_approval_while_realized_is_zero
    """
    world = fx.analyzed_program(
        api, hazards=[HAZARD_LISTERIA], food_overrides=dict(RTE_FOOD)
    )
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=3,
        justification_text=(
            "Three sampling events per year covering the pathogen profile of this "
            "frozen ready to eat fruit"
        ),
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    fx.review_activity(api, activity["id"], world.qi_b_id, "APPROVE")

    # No verification record exists at all, so only the PLANNED variant is non-zero.
    pair = validate_success(
        api.post_pair_verification_approval(
            world.pair_id,
            f.verification_approval_payload(
                approval_note=(
                    "Selected verification activities are adequate for the hazards "
                    "requiring control"
                )
            ),
            make_qualified_individual_headers(world.qi_a_id),
        ),
        200,
    )

    assert pair["verification_status"] == "VERIFICATION_APPROVED", (
        f"verification_status: {pair['verification_status']}"
    )
    assert pair["entry_eligibility_status"] == "ELIGIBLE", (
        f"entry_eligibility_status: {pair['entry_eligibility_status']}"
    )
    assert_money(pair["adequacy_score_planned"], 86.96, "pair.adequacy_score_planned")
    assert_money(pair["adequacy_score_realized"], 0.00, "pair.adequacy_score_realized")
    assert pair["last_reassessed_at"].startswith("2026-09-01T00:00:00"), (
        f"last_reassessed_at: {pair['last_reassessed_at']}"
    )
    assert pair["reassessment_due_at"].startswith("2029-09-01T00:00:00"), (
        f"reassessment_due_at: {pair['reassessment_due_at']}"
    )
    importer = fx.get_importer(api, world.importer_id)
    assert importer["program_status"] == "COMPLIANT", (
        f"program_status: {importer['program_status']}"
    )


def test_retention_calendar_month_arithmetic_clamps_to_end_of_february(api: ApiClient):
    """PRD §3.9: "Every verification record's `retained_until` is its
    `performed_end` advanced by the importer's `record_retention_months` in
    calendar months, and its `available_for_inspection` flag is true exactly when
    the record's `record_status` is not `RESCINDED` — that is, when it is
    `RECEIVED` or `ATTESTED` — and the evaluation instant is at or before
    `retained_until`."
    PRD §2.4: "Where advancing a calendar month would overflow the target month's
    length, the result clamps to the last day of that month."
    PRD §3.6: "Its `weight` is the record type weight for the parent activity's
    `activity_type` — 3.0 for `ONSITE_AUDIT`, 2.0 for `SAMPLING_AND_TESTING`, 1.0
    for `RECORDS_REVIEW`, and 0.5 for `OTHER_SUPPLIER_EVALUATION` — multiplied by a
    recency factor and rounded half up to two decimal places, where the recency
    factor is 1.0 when `performed_end` is within 365 days of the logical clock, 0.5
    when it is within 730 days, and 0.0 beyond that."
    PRD §3.6: "A new record starts in `record_status` `RECEIVED` with
    `submitted_by_qi_id` copied from `X-User-ID` and `attested_by_qi_id` null."

    Design: Corner/calculations/retention_calendar_month_arithmetic_clamps_to_end_of_february
    """
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api, record_retention_months=25)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    qi_b = fx.create_second_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_food(api, importer["id"], **RTE_FOOD)
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    analysis = fx.create_hazard_analysis(
        api, pair["id"], qi_a["id"], methodology_note=METHODOLOGY_NOTE
    )
    fx.add_hazard(api, analysis["id"], qi_a["id"], **HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], qi_a["id"])
    activity = fx.create_activity(
        api,
        pair["id"],
        qi_a["id"],
        qi_b["id"],
        activity_type="RECORDS_REVIEW",
        frequency_per_year=1,
        justification_text=(
            "Annual review of the supplier food safety records covering the pathogen "
            "control program"
        ),
        window_start="2026-01-25T00:00:00Z",
        window_end="2026-02-05T00:00:00Z",
    )
    fx.review_activity(api, activity["id"], qi_b["id"], "APPROVE")

    # performed_end 2026-01-31 plus 25 calendar months has no 31st to land on.
    record = validate_success(
        api.create_verification_record(
            f.record_payload(
                activity["id"],
                outcome="PASS",
                performed_start="2026-01-28T00:00:00Z",
                performed_end="2026-01-31T00:00:00Z",
                findings_count=0,
                document_reference="RR-2026-0131",
            ),
            make_qualified_individual_headers(qi_b["id"]),
        ),
        201,
    )

    stored = fx.get_record(api, record["id"])
    assert stored["retained_until"].startswith("2028-02-29T00:00:00"), (
        f"retained_until: {stored['retained_until']}"
    )
    assert stored["available_for_inspection"] is True, (
        f"available_for_inspection: {stored['available_for_inspection']}"
    )
    assert_money(stored["weight"], 1.00, "record.weight")
    assert_money(stored["record_points"], 100.00, "record.record_points")
    assert stored["record_status"] == "RECEIVED", (
        f"record_status: {stored['record_status']}"
    )


def test_stale_record_beyond_two_years_carries_zero_weight(api: ApiClient):
    """PRD §3.6: "Its `weight` is the record type weight for the parent activity's
    `activity_type` — 3.0 for `ONSITE_AUDIT`, 2.0 for `SAMPLING_AND_TESTING`, 1.0
    for `RECORDS_REVIEW`, and 0.5 for `OTHER_SUPPLIER_EVALUATION` — multiplied by a
    recency factor and rounded half up to two decimal places, where the recency
    factor is 1.0 when `performed_end` is within 365 days of the logical clock, 0.5
    when it is within 730 days, and 0.0 beyond that."
    PRD §3.6: "A record whose `performed_end` is more than 730 days before the
    clock has a `weight` of 0.00 and therefore drops out of both variants entirely,
    which is exactly how a weight total can return to 0.00 and a score back to
    100.00."
    PRD §3.6: "If the weight total is 0.00 the score is exactly 100.00 — no
    evidence is not bad evidence — and otherwise the score is the weighted sum
    divided by the weight total, rounded half up to two decimal places."
    PRD §3.6: "Its `record_points` is the outcome points for its `outcome` — 100
    for `PASS`, 75 for `PASS_WITH_FINDINGS`, 20 for `FAIL` — reduced by a findings
    penalty of 5 points per documented finding capped at 20 points in total,
    floored at 0 so the result never goes negative, and rounded half up to two
    decimal places."

    Design: Corner/calculations/stale_record_beyond_two_years_carries_zero_weight
    """
    world = fx.analyzed_program(
        api, hazards=[HAZARD_LISTERIA], food_overrides=dict(RTE_FOOD)
    )
    activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.qi_b_id,
        activity_type="RECORDS_REVIEW",
        frequency_per_year=1,
        justification_text=(
            "Historic records review retained in the FSVP file for the 2024 import season"
        ),
        window_start="2024-01-01T00:00:00Z",
        window_end="2024-01-31T00:00:00Z",
    )
    fx.review_activity(api, activity["id"], world.qi_b_id, "APPROVE")
    record = fx.file_record(
        api,
        activity["id"],
        world.qi_a_id,
        outcome="FAIL",
        performed_start="2024-01-05T00:00:00Z",
        performed_end="2024-01-06T00:00:00Z",
        findings_count=0,
        document_reference="RR-2024-0106",
    )

    # Attested, but performed far beyond the 730-day recency band.
    validate_success(
        api.post_record_attestation(
            record["id"],
            f.attestation_payload(
                attestation_note=(
                    "Historic failing review attested for completeness of the file"
                )
            ),
            make_qualified_individual_headers(world.qi_b_id),
        ),
        200,
    )

    stored = fx.get_record(api, record["id"])
    assert stored["record_status"] == "ATTESTED", (
        f"record_status: {stored['record_status']}"
    )
    assert_money(stored["weight"], 0.00, "record.weight")
    assert_money(stored["record_points"], 20.00, "record.record_points")
    assert stored["retained_until"].startswith("2026-01-06T00:00:00"), (
        f"retained_until: {stored['retained_until']}"
    )
    assert stored["available_for_inspection"] is False, (
        f"available_for_inspection: {stored['available_for_inspection']}"
    )
    assert_supplier_performance(
        fx.get_supplier(api, world.supplier_id),
        provisional=100.00,
        final=100.00,
        weight_total=0.00,
        status="APPROVED",
    )
    importer = fx.get_importer(api, world.importer_id)
    assert importer["open_corrective_action_count"] == 0, (
        f"open_corrective_action_count: {importer['open_corrective_action_count']}"
    )
