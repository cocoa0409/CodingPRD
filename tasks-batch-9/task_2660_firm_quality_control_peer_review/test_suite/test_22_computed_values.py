"""Computed-value tests for the Firm Quality Control & Peer Review API.

Every test builds its whole world from scratch through the declared endpoints and
then asserts the exact figure the PRD pins, including the operand order and the
position of each rounding step.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions, factories as f, fixtures
from test_helpers.test_users import make_committee_headers, make_peer_reviewer_headers

CLOCK = "2026-08-01T00:00:00Z"

FIRM_KWARGS = dict(
    legal_name="Harbor & Vance LLP",
    state_code="TX",
    aa_hours_last_year=9000,
    enrolled_program="AICPA_PRC",
    peer_review_year_end="2026-06-30",
)

REVIEW_ENGAGEMENT = dict(
    client_name="Aurora Metals Inc",
    engagement_type="REVIEW",
    period_end="2026-03-31",
)

ERISA_ENGAGEMENT = dict(
    client_name="Borealis Pension Trust",
    engagement_type="ERISA_AUDIT",
    period_end="2026-04-30",
)

ROSTER_REVIEWER = dict(
    reviewer_firm_name="Calder & Boone PC",
    license_state="TX",
    qualified_categories=[
        "ERISA_AUDIT",
        "SINGLE_AUDIT",
        "BROKER_DEALER",
        "GOVERNMENTAL",
        "PUBLIC_INTEREST",
    ],
    max_concurrent_reviews=2,
    experience_hours=4000,
)

SYSTEM_REVIEW = dict(
    review_type="SYSTEM_REVIEW",
    year_end="2026-06-30",
    scheduled_window_start="2026-10-01",
    scheduled_window_end="2026-10-15",
)


def _run_selector_for_setup(api, ctx, inspection_id):
    """Run the deterministic engagement selector as a setup step."""
    response = api.run_inspection_selector(inspection_id, headers=ctx["qc_headers"])
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )
    return get_success_data(response)


def _assert_instant(actual, expected_iso):
    """Assert a stamped instant equals the logical-clock instant exactly."""
    assert actual is not None, f"expected {expected_iso}, got None"
    parsed = datetime.fromisoformat(str(actual).replace("Z", "+00:00"))
    want = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    assert parsed.astimezone(timezone.utc) == want.astimezone(timezone.utc), (
        f"expected {expected_iso}, got {actual}"
    )


def _scope(api, review_id, reviewer_id):
    return assertions.read_entity(
        api.set_peer_review_scope(
            review_id, {}, headers=make_peer_reviewer_headers(reviewer_id)
        ),
        200,
    )


def test_peer_review_scope_hours_use_base_tier_forty_with_no_categories(api):
    """A 9000-hour STABLE firm with no must-select category draws exactly 40 scope hours.

    "The base tier is 16 hours when the firm's `aa_hours_last_year` is 500 or fewer,
    24 hours when it is 2000 or fewer, 40 hours when it is 10000 or fewer".

    Design: Corner/calculations/peer_review_scope_hours_use_base_tier_forty_with_no_categories
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    reviewer = fixtures.new_peer_reviewer(api, **ROSTER_REVIEWER)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **SYSTEM_REVIEW)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])

    scoped = _scope(api, review["id"], reviewer["id"])

    assertions.assert_fields(
        scoped,
        state="SCOPE_SET",
        must_select_categories=[],
        total_scope_hours=40,
        unallocated_hours=40,
        assigned_reviewer_id=reviewer["id"],
        rating="NONE",
    )
    firm = assertions.read_entity(
        api.get_firm(ctx["firm_id"], headers=ctx["mp_headers"]), 200
    )
    assertions.assert_fields(firm, unassigned_review_flag=False)


def test_peer_review_scope_hours_add_erisa_category_hours(api):
    """A released ERISA_AUDIT adds its 8 category hours to the 40-hour base tier.

    "Each must-select category adds hours of its own: 8 for `ERISA_AUDIT` ... the two
    rounded components are then added and the sum raised to the next whole hour".

    Design: Corner/calculations/peer_review_scope_hours_add_erisa_category_hours
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    erisa = fixtures.released_engagement(api, ctx, **ERISA_ENGAGEMENT)
    reviewer = fixtures.new_peer_reviewer(api, **ROSTER_REVIEWER)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **SYSTEM_REVIEW)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])

    scoped = _scope(api, review["id"], reviewer["id"])

    assertions.assert_fields(
        scoped,
        must_select_categories=["ERISA_AUDIT"],
        total_scope_hours=48,
        unallocated_hours=48,
    )
    released = assertions.read_entity(
        api.get_engagement(erisa["id"], headers=ctx["ep_headers"]), 200
    )
    assert released["eqr_concurred_at"] is not None, (
        "a concurring quality review must stamp eqr_concurred_at"
    )
    assertions.assert_fields(released, workflow_state="REPORT_RELEASED")


def test_remediation_acceptance_score_is_strong_tier_eight_ninety(api):
    """An on-time submission scores 8.90 in the STRONG tier with no lateness penalty.

    "Step one derives `raw_completeness` ... as 0.40 of the cited analysis's
    `depth_score`, plus 0.35 of the plan's `action_specificity_score`, plus 0.25 of an
    action-progress term equal to ten multiplied by `completed_action_count` and
    divided by `action_count`."

    Design: Corner/calculations/remediation_acceptance_score_is_strong_tier_eight_ninety
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector_for_setup(api, ctx, inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Review notes not cleared before report release",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    fixtures.classify(
        api,
        ctx,
        finding["id"],
        "DEFICIENCY",
        pervasiveness="ISOLATED",
        affects_report_conclusion=False,
    )
    rca = fixtures.validated_rca(
        api,
        ctx,
        finding["id"],
        method="FISHBONE",
        root_cause_category="SUPERVISION_REVIEW",
        contributing_factor_count=3,
        narrative=(
            "Supervisory review was performed after the report date and was not "
            "documented."
        ),
    )
    plan = fixtures.new_remediation_plan(
        api,
        ctx,
        finding["id"],
        rca["id"],
        ctx["qc"]["id"],
        target_completion_date="2026-09-30",
        action_count=4,
        action_specificity_score=8.00,
    )

    submitted = fixtures.plan_step(
        api, ctx, plan["id"], "SUBMITTED", completed_action_count=4
    )

    assertions.assert_fields(
        submitted, state="SUBMITTED", completed_action_count=4,
        completeness_tier="STRONG",
    )
    assertions.assert_decimal_equals(submitted["raw_completeness"], 8.90)
    assertions.assert_decimal_equals(submitted["acceptance_score"], 8.90)
    stored_rca = assertions.read_entity(
        api.get_root_cause_analysis(rca["id"], headers=ctx["qc_headers"]), 200
    )
    assertions.assert_decimal_equals(stored_rca["depth_score"], 9.00)
    assertions.assert_fields(stored_rca, recurrence_flag=False)


def test_engagement_risk_score_caps_prior_finding_points_at_twenty(api):
    """Nine prior findings contribute the capped 20 points, giving a risk score of 40.

    "4 points for each prior finding recorded in `prior_finding_count_3y` — with the
    prior-finding contribution capped at 20 points".

    Design: Corner/calculations/engagement_risk_score_caps_prior_finding_points_at_twenty
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)

    engagement = assertions.created_entity(
        api.create_engagement(
            f.engagement_payload(
                ctx["firm_id"],
                ctx["ep"]["id"],
                client_name="Fenwick Cold Storage",
                engagement_type="AUDIT",
                period_end="2026-05-31",
                prior_finding_count_3y=9,
            ),
            headers=ctx["mp_headers"],
        )
    )

    assertions.assert_fields(
        engagement,
        risk_score=40,
        eqr_required=False,
        prior_finding_count_3y=9,
        workflow_state="PLANNING",
    )


def test_must_select_coverage_excludes_unreleased_engagements(api):
    """An ERISA_AUDIT still in PLANNING is invisible to the selector and to coverage.

    "an engagement is window-eligible when it belongs to the cycle's firm, its
    `workflow_state` is exactly `REPORT_RELEASED`, and its `period_end` falls within
    the calendar year of `inspection_year`".

    Design: Corner/calculations/must_select_coverage_excludes_unreleased_engagements
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    released = fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    fixtures.new_engagement(api, ctx, **ERISA_ENGAGEMENT)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )

    response = api.run_inspection_selector(inspection["id"], headers=ctx["qc_headers"])
    validate_success(response, expected_status=200)
    cycle = get_success_data(response)

    assertions.assert_fields(
        cycle,
        state="SELECTION_COMPLETE",
        engagements_selected_count=1,
        must_select_eligible_count=0,
        must_select_selected_count=0,
    )
    assertions.assert_decimal_equals(cycle["must_select_coverage_pct"], 100.00)
    selections = fixtures.selections_of(api, ctx, inspection["id"])
    assert len(selections) == 1, f"expected exactly one selection, got {selections}"
    assertions.assert_fields(selections[0], engagement_id=released["id"])
    partner = assertions.read_entity(
        api.get_partner(ctx["ep"]["id"], headers=ctx["qc_headers"]), 200
    )
    assertions.assert_fields(partner, last_inspected_year=2026)


def _tested_response(api, ctx, risk_id, response_type, description):
    response = fixtures.new_risk_response(
        api, ctx, risk_id, response_type=response_type, description=description
    )
    fixtures.record_effectiveness_test(
        api,
        ctx,
        response["id"],
        design_effectiveness="EFFECTIVE",
        operating_effectiveness="EFFECTIVE",
    )
    return response


def _evaluate(api, ctx, risk_id, basis):
    return assertions.read_entity(
        api.create_risk_evaluation(
            risk_id, f.risk_evaluation_payload(basis), headers=ctx["qc_headers"]
        ),
        200,
    )


def test_residual_risk_diverges_between_design_and_operating_basis(api):
    """The additive capped DESIGN_BASIS gives 5.00 where the multiplicative OPERATING_BASIS gives 8.58.

    "those weights are added together, the total is capped at 0.80 ... This
    multiplicative fold has no cap, and the result is rounded half-up to two decimals
    once at the end."

    Design: Corner/calculations/residual_risk_diverges_between_design_and_operating_basis
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    risk_a = fixtures.new_quality_risk(
        api,
        ctx,
        component="ENGAGEMENT_PERFORMANCE",
        quality_objective_code="EP-01",
        risk_statement=(
            "Engagement teams may not obtain sufficient appropriate evidence over "
            "significant estimates."
        ),
        likelihood=5,
        impact=5,
    )
    _tested_response(
        api, ctx, risk_a["id"], "PREVENTIVE",
        "Mandatory second-partner review of all significant estimate workpapers.",
    )
    _tested_response(
        api, ctx, risk_a["id"], "DETECTIVE",
        "Quarterly monitoring sample of estimate documentation.",
    )
    _tested_response(
        api, ctx, risk_a["id"], "PREVENTIVE",
        "Annual specialist training on estimate audit procedures.",
    )
    _evaluate(api, ctx, risk_a["id"], "DESIGN_BASIS")

    risk_b = fixtures.new_quality_risk(
        api,
        ctx,
        component="RESOURCES",
        quality_objective_code="RES-01",
        risk_statement=(
            "Staffing levels may be insufficient for peak-season engagement "
            "supervision."
        ),
        likelihood=5,
        impact=5,
    )
    _tested_response(
        api, ctx, risk_b["id"], "PREVENTIVE",
        "Capacity model reviewed before every busy season.",
    )
    _tested_response(
        api, ctx, risk_b["id"], "DETECTIVE",
        "Monthly utilisation exception report to the QC director.",
    )
    _tested_response(
        api, ctx, risk_b["id"], "PREVENTIVE",
        "Contract reviewer bench retained for overflow supervision.",
    )

    evaluated_b = _evaluate(api, ctx, risk_b["id"], "OPERATING_BASIS")

    assertions.assert_decimal_equals(evaluated_b["residual_risk_score"], 8.58)
    assertions.assert_fields(
        evaluated_b,
        severity_band="HIGH",
        evaluation_basis="OPERATING_BASIS",
        state="EVALUATED",
    )
    stored_a = assertions.read_entity(
        api.get_quality_risk(risk_a["id"], headers=ctx["qc_headers"]), 200
    )
    assertions.assert_decimal_equals(stored_a["residual_risk_score"], 5.00)
    assertions.assert_fields(
        stored_a, severity_band="MODERATE", evaluation_basis="DESIGN_BASIS"
    )
    firm = assertions.read_entity(
        api.get_firm(ctx["firm_id"], headers=ctx["mp_headers"]), 200
    )
    assertions.assert_fields(firm, critical_risk_count=0, risk_posture="STABLE")


def test_deficiency_severity_index_firm_pervasive_adds_systemic_bonus(api):
    """FIRM_PERVASIVE adds 5 points per SYSTEMIC finding and ignores is_must_select.

    "the classification points are instead grouped by `sqm_component`, the largest
    single component total is taken ... 5 points are added for each finding whose
    `pervasiveness` is `SYSTEMIC`, and that sum is divided by the number of distinct
    components represented among the findings".

    Design: Corner/calculations/deficiency_severity_index_firm_pervasive_adds_systemic_bonus
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector_for_setup(api, ctx, inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Review notes not cleared before report release",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    fixtures.classify(
        api,
        ctx,
        finding["id"],
        "DEFICIENCY",
        pervasiveness="SYSTEMIC",
        affects_report_conclusion=False,
    )

    classified = fixtures.inspection_step(
        api,
        ctx,
        inspection["id"],
        "FINDINGS_CLASSIFIED",
        severity_index_basis="FIRM_PERVASIVE",
    )

    assertions.assert_fields(
        classified,
        state="FINDINGS_CLASSIFIED",
        severity_index_basis="FIRM_PERVASIVE",
    )
    assertions.assert_decimal_equals(classified["deficiency_severity_index"], 8.00)
    # Classification itself recomputes the selection's weighted_points: a single
    # 3-point DEFICIENCY on a must-select selection reads 3 * 1.5 = 4.50.
    stored_selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    assertions.assert_decimal_equals(stored_selection["weighted_points"], 4.50)


def test_inspection_selection_waterfall_overrides_the_target_count(api):
    """Blocks A and B are mandatory, so a target of one still selects two engagements.

    "Block A takes precedence over `target_engagement_count` — a cycle whose
    must-select population exceeds its target inspects them all anyway."

    Design: Corner/calculations/inspection_selection_waterfall_overrides_the_target_count
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    review_engagement = fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    erisa_engagement = fixtures.released_engagement(api, ctx, **ERISA_ENGAGEMENT)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )

    response = api.run_inspection_selector(inspection["id"], headers=ctx["qc_headers"])
    validate_success(response, expected_status=200)
    cycle = get_success_data(response)

    assertions.assert_fields(
        cycle,
        engagements_selected_count=2,
        must_select_eligible_count=1,
        must_select_selected_count=1,
        state="SELECTION_COMPLETE",
    )
    assertions.assert_decimal_equals(cycle["must_select_coverage_pct"], 100.00)
    selections = fixtures.selections_of(api, ctx, inspection["id"])
    assert len(selections) == 2, f"expected two selections, got {selections}"
    by_engagement = {row["engagement_id"]: row for row in selections}
    assertions.assert_fields(
        by_engagement[erisa_engagement["id"]],
        selected_rank=1,
        selection_reason="MUST_SELECT_ERISA_AUDIT",
        is_must_select=True,
    )
    assertions.assert_fields(
        by_engagement[review_engagement["id"]],
        selected_rank=2,
        selection_reason="MUST_SELECT_PARTNER_COVERAGE",
        is_must_select=True,
    )


def test_root_cause_depth_score_saturates_at_the_declared_cap(api):
    """A five-factor FISHBONE analysis saturates the depth score at 10.00, not 13.00.

    "`depth_score` is then twice the `contributing_factor_count`, plus a method bonus
    of 2 for `FIVE_WHYS`, 3 for `FISHBONE` or 1 for `PARETO` ... with the total capped
    at 10 and stored with two decimals".

    Design: Corner/calculations/root_cause_depth_score_saturates_at_the_declared_cap
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector_for_setup(api, ctx, inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Review notes not cleared before report release",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    fixtures.classify(
        api,
        ctx,
        finding["id"],
        "DEFICIENCY",
        pervasiveness="ISOLATED",
        affects_report_conclusion=False,
    )
    rca = assertions.created_entity(
        api.create_root_cause_analysis(
            finding["id"],
            f.rca_payload(
                method="FISHBONE",
                root_cause_category="SUPERVISION_REVIEW",
                contributing_factor_count=5,
                narrative=(
                    "Five interacting factors span planning, staffing, supervision, "
                    "review timing and file assembly."
                ),
            ),
            headers=ctx["qc_headers"],
        )
    )

    validated = assertions.read_entity(
        api.create_rca_validation(
            rca["id"], f.rca_validation_payload("VALIDATED"), headers=ctx["qc_headers"]
        ),
        200,
    )

    assertions.assert_fields(validated, state="VALIDATED", recurrence_flag=False)
    _assert_instant(validated["validated_at"], CLOCK)
    assertions.assert_decimal_equals(validated["depth_score"], 10.00)


def test_peer_review_rating_is_pass_with_deficiency_at_one_scope_limitation(api):
    """Exactly one scope limitation with an FFC disposition rates PASS_WITH_DEFICIENCY.

    "otherwise `PASS_WITH_DEFICIENCY` when at least one selection carries a
    `DEFICIENCY` disposition, or at least one selection is non-conforming, or the
    scope-limitation count is exactly 1".

    Design: Corner/calculations/peer_review_rating_is_pass_with_deficiency_at_one_scope_limitation
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    engagement = fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector_for_setup(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    fixtures.inspection_step(
        api,
        ctx,
        inspection["id"],
        "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    fixtures.inspection_step(api, ctx, inspection["id"], "CONCLUDED")
    reviewer = fixtures.new_peer_reviewer(api, **ROSTER_REVIEWER)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **SYSTEM_REVIEW)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    fixtures.set_scope(api, review["id"], reviewer["id"])
    selection = fixtures.select_engagement(
        api,
        review["id"],
        reviewer["id"],
        engagement["id"],
        hours_committed=12,
        is_scope_limitation=True,
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    fixtures.peer_review_step(api, review["id"], "FIELDWORK", reviewer_headers)
    fixtures.record_disposition(
        api, selection["id"], reviewer["id"], "FFC", non_conforming=False
    )

    rated = fixtures.peer_review_step(
        api, review["id"], "RATING_DRAFTED", reviewer_headers
    )

    assertions.assert_fields(
        rated,
        state="RATING_DRAFTED",
        rating="PASS_WITH_DEFICIENCY",
        scope_limitation_count=1,
        unallocated_hours=28,
    )


def test_reviewer_assignment_with_an_empty_pool_flags_the_firm(api):
    """An empty eligible pool refuses the assignment and raises the firm's flag.

    "If no candidate survives the filter, the review stays in `SCHEDULED`, the firm's
    `unassigned_review_flag` is set true, and the request is refused with
    `ERR_NO_ELIGIBLE_REVIEWER` (HTTP 409)."

    Design: Corner/calculations/reviewer_assignment_with_an_empty_pool_flags_the_firm
    """
    fixtures.set_clock(api, CLOCK)
    committee = make_committee_headers()
    firm = fixtures.new_firm(api, **FIRM_KWARGS)
    review = fixtures.new_peer_review(api, firm["id"], **SYSTEM_REVIEW)

    response = api.assign_peer_reviewer(review["id"], {}, headers=committee)

    validate_error(response, "ERR_NO_ELIGIBLE_REVIEWER", expected_status=409)
    stored_review = assertions.read_entity(
        api.get_peer_review(review["id"], headers=committee), 200
    )
    assertions.assert_fields(stored_review, state="SCHEDULED")
    assert stored_review["assigned_reviewer_id"] is None, (
        "a refused assignment must leave assigned_reviewer_id null"
    )
    stored_firm = assertions.read_entity(api.get_firm(firm["id"], headers=committee), 200)
    assertions.assert_fields(stored_firm, unassigned_review_flag=True)
