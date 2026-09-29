"""Optimistic concurrency, multi-link cascades and immediate consistency.

The version guard is exercised only on the three creates that declare one, and
each cascade is observed through every aggregate it is required to touch, in the
same request that caused it.
"""
from typing import Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    created_entity,
    read_entity,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import make_committee_headers, make_peer_reviewer_headers

ALL_CATEGORIES = [
    "ERISA_AUDIT",
    "SINGLE_AUDIT",
    "BROKER_DEALER",
    "GOVERNMENTAL",
    "PUBLIC_INTEREST",
]


def _firm(api, legal_name: str = "Harbor & Vance LLP", **overrides) -> Dict:
    """A Texas firm in the 10000-hour tier with its three firm-side partners."""
    payload = dict(
        legal_name=legal_name,
        state_code="TX",
        aa_hours_last_year=9000,
        peer_review_year_end="2026-06-30",
    )
    payload.update(overrides)
    return fixtures.firm_context(api, **payload)


def _run_selector(api, headers: Dict, inspection_id: str) -> None:
    """Run the deterministic engagement selector for a cycle (setup only)."""
    response = api.run_inspection_selector(inspection_id, headers=headers)
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )


def _erisa_engagement_in_fieldwork(api, ctx):
    """An ERISA_AUDIT engagement advanced to FIELDWORK, plus its create version."""
    engagement = fixtures.new_engagement(
        api,
        ctx,
        client_name="Borealis Pension Trust",
        engagement_type="ERISA_AUDIT",
        period_end="2026-04-30",
    )
    create_version = engagement["version"]
    fixtures.workflow_step(api, engagement, "FIELDWORK", ctx["ep_headers"])
    return engagement, create_version


def _reviewed_firm(api):
    """A firm with one released REVIEW engagement, a rostered reviewer and a review."""
    ctx = _firm(api)
    engagement = fixtures.released_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    reviewer = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Calder & Boone PC",
        license_state="TX",
        qualified_categories=ALL_CATEGORIES,
        experience_hours=4000,
    )
    review = fixtures.new_peer_review(
        api,
        ctx["firm_id"],
        review_type="SYSTEM_REVIEW",
        year_end="2026-06-30",
        scheduled_window_start="2026-10-01",
        scheduled_window_end="2026-10-15",
    )
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    return ctx, engagement, reviewer, review


def test_eqr_assignment_with_a_stale_engagement_version_is_rejected(api):
    """An assignment carrying the version read before the FIELDWORK transition is
    refused on the concurrency guard, leaving no review behind.

    "the create is refused with `ERR_STALE_VERSION` (HTTP 412)" when the supplied
    version "does not match the parent's current `version`".

    Design: Corner/cross_cutting_complexity_layers/eqr_assignment_with_a_stale_engagement_version_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api)
    reviewer = fixtures.add_eq_reviewer(
        api, ctx, full_name="Lena Ortiz", cpe_hours_last_3y=150
    )
    engagement, stale_version = _erisa_engagement_in_fieldwork(api, ctx)

    stale = api.assign_quality_review(
        engagement["id"],
        f.quality_review_assignment_payload(reviewer["id"], stale_version),
        headers=ctx["qc_headers"],
    )
    validate_error(stale, E.ERR_STALE_VERSION, expected_status=412)

    current = read_entity(api.get_engagement(engagement["id"], headers=ctx["qc_headers"]))
    assert_fields(
        current, version=2, workflow_state="FIELDWORK", eqr_required=True
    )
    partner = read_entity(api.get_partner(reviewer["id"], headers=ctx["mp_headers"]))
    assert_fields(partner, open_eqr_count=0)

    _, meta = validate_paginated(
        api.list_quality_reviews(
            headers=ctx["qc_headers"], params={"engagement_id": engagement["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no quality review may exist after a stale create, got {meta['total_count']}"
    )


def test_eqr_assignment_with_the_observed_version_succeeds_and_bumps_the_parent(api):
    """The version observed after the last parent mutation is accepted, and the
    child create bumps the parent so the same version cannot be replayed.

    "A successful assignment ... increments the engagement's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/eqr_assignment_with_the_observed_version_succeeds_and_bumps_the_parent
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api)
    reviewer = fixtures.add_eq_reviewer(
        api, ctx, full_name="Lena Ortiz", cpe_hours_last_3y=150
    )
    engagement, _ = _erisa_engagement_in_fieldwork(api, ctx)
    observed = read_entity(
        api.get_engagement(engagement["id"], headers=ctx["qc_headers"])
    )
    assert_fields(observed, version=2)

    eqr = created_entity(
        api.assign_quality_review(
            engagement["id"],
            f.quality_review_assignment_payload(reviewer["id"], observed["version"]),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(
        eqr,
        state="ASSIGNED",
        reviewer_partner_id=reviewer["id"],
        cooling_off_days_at_assignment=None,
    )

    after = read_entity(api.get_engagement(engagement["id"], headers=ctx["qc_headers"]))
    assert_fields(after, version=3)
    partner = read_entity(api.get_partner(reviewer["id"], headers=ctx["mp_headers"]))
    assert_fields(partner, open_eqr_count=1)

    replay = api.assign_quality_review(
        engagement["id"],
        f.quality_review_assignment_payload(reviewer["id"], observed["version"]),
        headers=ctx["qc_headers"],
    )
    validate_error(replay, E.ERR_STALE_VERSION, expected_status=412)


def test_remediation_plan_create_with_a_pre_validation_finding_version_is_rejected(api):
    """A plan attached with the finding version read before the root cause ladder
    ran is refused on the concurrency guard, not on the analysis precondition.

    "the create is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/remediation_plan_create_with_a_pre_validation_finding_version_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api)
    fixtures.released_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector(api, ctx["qc_headers"], inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Analytical procedures were not documented at the assertion level",
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
    stale_view = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )
    stale_version = stale_view["version"]
    rca = fixtures.validated_rca(
        api,
        ctx,
        finding["id"],
        method="FISHBONE",
        root_cause_category="SUPERVISION_REVIEW",
        contributing_factor_count=3,
    )

    plan_payload = f.remediation_plan_payload(
        rca["id"],
        ctx["ep"]["id"],
        stale_version,
        target_completion_date="2026-09-30",
        action_count=4,
        action_specificity_score=8.00,
    )
    stale = api.create_remediation_plan(
        finding["id"], plan_payload, headers=ctx["qc_headers"]
    )
    validate_error(stale, E.ERR_STALE_VERSION, expected_status=412)

    fresh = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )
    assert_fields(fresh, state="RCA_COMPLETE")
    assert fresh["version"] > stale_version, (
        f"the analysis ladder must have bumped the finding past {stale_version}, "
        f"got {fresh['version']}"
    )

    _, meta = validate_paginated(
        api.list_remediation_plans(
            headers=ctx["qc_headers"], params={"finding_id": finding["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no plan may exist after a stale create, got {meta['total_count']}"
    )

    accepted_payload = f.remediation_plan_payload(
        rca["id"],
        ctx["ep"]["id"],
        fresh["version"],
        target_completion_date="2026-09-30",
        action_count=4,
        action_specificity_score=8.00,
    )
    plan = created_entity(
        api.create_remediation_plan(
            finding["id"], accepted_payload, headers=ctx["qc_headers"]
        )
    )
    assert_fields(plan, state="DRAFTED", completed_action_count=0)


def test_peer_review_selection_with_a_pre_scope_version_is_rejected(api):
    """Committing hours against the review version read before scope determination
    is refused, and the hours budget stays untouched.

    "the create is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/peer_review_selection_with_a_pre_scope_version_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx, engagement, reviewer, review = _reviewed_firm(api)
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    pre_scope = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    scoped = fixtures.set_scope(api, review["id"], reviewer["id"])
    assert scoped["version"] > pre_scope["version"], (
        "scope determination must bump the review version"
    )

    stale = api.create_peer_review_selection(
        review["id"],
        f.peer_review_selection_payload(
            engagement["id"], pre_scope["version"], hours_committed=12
        ),
        headers=reviewer_headers,
    )
    validate_error(stale, E.ERR_STALE_VERSION, expected_status=412)

    untouched = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    assert_fields(
        untouched, state="SCOPE_SET", total_scope_hours=40, unallocated_hours=40
    )
    _, meta = validate_paginated(
        api.list_peer_review_selections(
            headers=reviewer_headers, params={"peer_review_id": review["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no selection may exist after a stale create, got {meta['total_count']}"
    )

    selection = created_entity(
        api.create_peer_review_selection(
            review["id"],
            f.peer_review_selection_payload(
                engagement["id"], untouched["version"], hours_committed=12
            ),
            headers=reviewer_headers,
        )
    )
    assert_fields(selection, hours_committed=12, status="COMMITTED")
    debited = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    assert_fields(debited, total_scope_hours=40, unallocated_hours=28)


def test_material_failure_classification_fires_all_five_cascade_links(api):
    """One classification call is observable in the finding, the engagement's file,
    the matching quality risk, the firm's counters and the acceptance gate.

    "`MATERIAL_FAILURE` propagates all the way out to client acceptance being
    frozen".

    Design: Corner/cross_cutting_complexity_layers/material_failure_classification_fires_all_five_cascade_links
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api)
    engagement = fixtures.released_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    fixtures.file_step(api, engagement, "ASSEMBLED", ctx["ep_headers"])
    fixtures.file_step(api, engagement, "LOCKED", ctx["ep_headers"])

    risk = fixtures.new_quality_risk(
        api,
        ctx,
        component="ENGAGEMENT_PERFORMANCE",
        quality_objective_code="EP-01",
        likelihood=5,
        impact=5,
    )
    response = fixtures.new_risk_response(api, ctx, risk["id"], response_type="PREVENTIVE")
    fixtures.record_effectiveness_test(
        api,
        ctx,
        response["id"],
        design_effectiveness="EFFECTIVE",
        operating_effectiveness="EFFECTIVE",
    )
    evaluated = read_entity(
        api.create_risk_evaluation(
            risk["id"], f.risk_evaluation_payload("DESIGN_BASIS"), headers=ctx["qc_headers"]
        )
    )
    assert_fields(evaluated, state="EVALUATED", severity_band="CRITICAL")
    assert_decimal_equals(evaluated["residual_risk_score"], 16.25)

    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector(api, ctx["qc_headers"], inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Substantive procedures did not address the significant risk",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )

    classified = read_entity(
        api.classify_finding(
            finding["id"],
            f.classification_payload("MATERIAL_FAILURE"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(
        classified,
        classification="MATERIAL_FAILURE",
        pervasiveness="SYSTEMIC",
        affects_report_conclusion=True,
        class_points=20,
        state="RCA_PENDING",
    )

    reopened = read_entity(
        api.get_engagement(engagement["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reopened, file_state="OPEN", reopened_count=1)

    risk_after = read_entity(api.get_quality_risk(risk["id"], headers=ctx["qc_headers"]))
    assert_fields(
        risk_after,
        state="RESPONDED",
        reopen_count=1,
        residual_risk_score=None,
        severity_band="NONE",
        evaluation_basis="NONE",
    )

    firm_after = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(
        firm_after,
        open_material_failure_count=1,
        open_deficiency_count=1,
        critical_risk_count=0,
        risk_posture="CRITICAL",
    )

    frozen = api.create_engagement(
        f.engagement_payload(
            ctx["firm_id"],
            ctx["ep"]["id"],
            client_name="Meridian Benefit Plan",
            engagement_type="ERISA_AUDIT",
            period_end="2026-06-30",
        ),
        headers=ctx["ep_headers"],
    )
    validate_error(frozen, E.ERR_ACCEPTANCE_FROZEN, expected_status=409)

    ordinary = created_entity(
        api.create_engagement(
            f.engagement_payload(
                ctx["firm_id"],
                ctx["ep"]["id"],
                client_name="Cardinal Freight Co",
                engagement_type="REVIEW",
                period_end="2026-06-30",
            ),
            headers=ctx["ep_headers"],
        )
    )
    assert_fields(ordinary, risk_score=8, eqr_required=True)


def test_corrective_action_rejection_synthesizes_the_follow_up_review(api):
    """Rejecting the corrective-action evidence closes the original review and
    creates a self-referential follow-up review 180 days out.

    "a new peer review is created for the same firm in state `SCHEDULED`, with
    `prior_peer_review_id` set to the rejected review's `id`".

    Design: Corner/cross_cutting_complexity_layers/corrective_action_rejection_synthesizes_the_follow_up_review
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    committee = make_committee_headers()
    ctx, engagement, reviewer, review = _reviewed_firm(api)
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])

    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector(api, ctx["qc_headers"], inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    fixtures.inspection_step(
        api,
        ctx,
        inspection["id"],
        "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    fixtures.inspection_step(api, ctx, inspection["id"], "CONCLUDED")

    scoped = fixtures.set_scope(api, review["id"], reviewer["id"])
    fixtures.select_engagement(
        api,
        review["id"],
        reviewer["id"],
        engagement["id"],
        hours_committed=12,
        is_scope_limitation=True,
    )
    fixtures.peer_review_step(api, review["id"], "FIELDWORK", reviewer_headers)
    peer_selections, _ = validate_paginated(
        api.list_peer_review_selections(
            headers=reviewer_headers, params={"peer_review_id": review["id"]}
        )
    )
    fixtures.record_disposition(
        api, peer_selections[0]["id"], reviewer["id"], "FFC", non_conforming=False
    )
    rated = fixtures.peer_review_step(
        api, review["id"], "RATING_DRAFTED", reviewer_headers
    )
    assert_fields(rated, rating="PASS_WITH_DEFICIENCY", scope_limitation_count=1)
    issued = fixtures.peer_review_step(
        api, review["id"], "REPORT_ISSUED", reviewer_headers
    )
    assert_fields(issued, state="CORRECTIVE_ACTION_REQUIRED")

    plans = fixtures.corrective_action_plans_of(api, review["id"])
    assert len(plans) == 1, f"exactly one corrective action plan is synthesized: {plans}"
    plan = plans[0]
    assert_fields(plan, action_code="MONITORING_VISIT", due_date="2026-10-30",
                  status="REQUIRED", rejection_count=0)

    read_entity(
        api.create_corrective_action_evidence(
            plan["id"],
            f.corrective_action_evidence_payload(
                evidence_summary=(
                    "Monitoring visit performed; supervision checklist adopted "
                    "firm-wide."
                )
            ),
            headers=ctx["qc_headers"],
        )
    )
    submitted = read_entity(api.get_peer_review(review["id"], headers=committee))
    assert_fields(submitted, state="REMEDIATION_SUBMITTED")

    rejected = read_entity(
        api.create_corrective_action_disposition(
            plan["id"],
            f.corrective_action_disposition_payload("REJECTED"),
            headers=committee,
        )
    )
    assert_fields(rejected, status="REJECTED", rejection_count=1)

    original = read_entity(api.get_peer_review(review["id"], headers=committee))
    assert_fields(original, state="FOLLOW_UP_REQUIRED", rating="PASS_WITH_DEFICIENCY")

    follow_ups, meta = validate_paginated(
        api.list_peer_reviews(
            headers=committee, params={"prior_peer_review_id": review["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one follow-up review is synthesized, got {meta['total_count']}"
    )
    assert_fields(
        follow_ups[0],
        state="SCHEDULED",
        is_follow_up=True,
        review_type="SYSTEM_REVIEW",
        year_end="2026-06-30",
        scheduled_window_start="2027-04-13",
        scheduled_window_end="2027-04-27",
        prior_peer_review_id=review["id"],
    )

    firm_after = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(
        firm_after, last_peer_review_rating="PASS_WITH_DEFICIENCY", risk_posture="ELEVATED"
    )
    reviewer_after = read_entity(api.get_peer_reviewer(reviewer["id"], headers=committee))
    assert_fields(reviewer_after, active_review_count=0)

    still_accepted = created_entity(
        api.create_engagement(
            f.engagement_payload(
                ctx["firm_id"],
                ctx["ep"]["id"],
                client_name="Wexford County Schools",
                engagement_type="SINGLE_AUDIT",
                period_end="2026-06-30",
            ),
            headers=ctx["ep_headers"],
        )
    )
    assert_fields(still_accepted, eqr_required=True)
    assert scoped["total_scope_hours"] == 40, (
        f"the 9000-hour tier scopes 40 hours, got {scoped['total_scope_hours']}"
    )


def test_classification_response_already_carries_the_cascaded_counters(api):
    """The firm's deficiency counter is already correct in the request that
    classified the finding, and one deficiency leaves the posture STABLE.

    "The counters feeding this ladder are always recomputed from the underlying
    finding and quality-risk rows immediately before the ladder runs within the
    same request, so the posture never reads a stale counter."

    Design: Corner/consistency_model/classification_response_already_carries_the_cascaded_counters
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api)
    fixtures.released_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector(api, ctx["qc_headers"], inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Group audit instructions were not evidenced as reviewed",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    before = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(
        before,
        open_deficiency_count=0,
        open_material_failure_count=0,
        risk_posture="STABLE",
    )

    classified = read_entity(
        api.classify_finding(
            finding["id"],
            f.classification_payload(
                "SIGNIFICANT_DEFICIENCY",
                pervasiveness="SYSTEMIC",
                affects_report_conclusion=False,
            ),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(
        classified,
        classification="SIGNIFICANT_DEFICIENCY",
        class_points=8,
        state="RCA_PENDING",
        version=2,
    )

    firm_now = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(
        firm_now,
        open_deficiency_count=1,
        open_material_failure_count=0,
        risk_posture="STABLE",
    )
    selection_now = read_entity(
        api.get_inspection_selection(selection["id"], headers=ctx["qc_headers"])
    )
    assert_fields(selection_now, finding_count=1)

    # Nothing converges after the fact: a second round of reads must agree with
    # the first, field for field.
    firm_again = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert firm_again == firm_now, (
        "the firm's counters changed between two reads of the same state: "
        f"{firm_now} then {firm_again}"
    )
    finding_again = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        finding_again,
        classification="SIGNIFICANT_DEFICIENCY",
        class_points=8,
        state="RCA_PENDING",
        version=2,
    )


def test_selection_response_already_debits_the_hours_budget(api):
    """Committing hours debits the review's budget inside the same request, so the
    hours-conservation invariant holds at every observable instant.

    "at every instant the review's `total_scope_hours` equals its
    `unallocated_hours` plus the sum of `hours_committed` across its committed
    selections."

    Design: Corner/consistency_model/selection_response_already_debits_the_hours_budget
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx, engagement, reviewer, review = _reviewed_firm(api)
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    scoped = fixtures.set_scope(api, review["id"], reviewer["id"])
    assert_fields(scoped, total_scope_hours=40, unallocated_hours=40)

    selection = created_entity(
        api.create_peer_review_selection(
            review["id"],
            f.peer_review_selection_payload(
                engagement["id"], scoped["version"], hours_committed=12
            ),
            headers=reviewer_headers,
        )
    )
    assert_fields(
        selection,
        hours_committed=12,
        status="COMMITTED",
        disposition="NONE",
        must_select_category=None,
        is_scope_limitation=False,
    )

    debited = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    assert_fields(debited, total_scope_hours=40, unallocated_hours=28)
    assert (
        debited["unallocated_hours"] + selection["hours_committed"]
        == debited["total_scope_hours"]
    ), (
        "committed plus unallocated must equal the total scope hours: "
        f"{selection['hours_committed']} + {debited['unallocated_hours']} != "
        f"{debited['total_scope_hours']}"
    )

    listed, meta = validate_paginated(
        api.list_peer_review_selections(
            headers=reviewer_headers, params={"peer_review_id": review["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one committed selection is expected, got {meta['total_count']}"
    )
    assert listed[0]["id"] == selection["id"], (
        f"the listed selection must be the created one: {listed[0]['id']}"
    )
