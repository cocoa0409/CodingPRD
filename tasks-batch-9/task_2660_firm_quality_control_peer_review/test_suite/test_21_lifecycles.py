"""Lifecycle rules of the PRD: initial states, legs, guards, cascades, terminals.

Every test starts from an empty database and builds its own state through the
endpoints the PRD declares.  Headers for the five entity-backed roles are always
built from the id of the row backing the acting identity.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import (
    ERR_FINDING_ALREADY_VERIFIED,
    ERR_INVALID_TRANSITION,
)
from test_helpers.constants import DEFAULT_CLOCK, DEFAULT_CLOCK_DATE
from test_helpers.test_users import (
    make_eq_reviewer_headers,
    make_peer_reviewer_headers,
)

# The firm under test throughout this module.
FIRM_UNDER_TEST = dict(
    legal_name="Harbor & Vance LLP",
    state_code="TX",
    aa_hours_last_year=9000,
    enrolled_program="AICPA_PRC",
    peer_review_year_end="2026-06-30",
)

RELEASE_LEGS = ("FIELDWORK", "EQR_PENDING", "EQR_CLEARED", "REPORT_RELEASED")


def _firm_context(api):
    """Pin the logical clock, then register the firm and its partner roster."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    return fixtures.firm_context(api, **FIRM_UNDER_TEST)


def _accept_engagement(api, ctx, partner=None, **overrides):
    """Accept a client engagement, driven by the firm's managing partner."""
    partner = partner or ctx["ep"]
    return assertions.created_entity(
        api.create_engagement(
            factories.engagement_payload(ctx["firm_id"], partner["id"], **overrides),
            headers=ctx["mp_headers"],
        )
    )


def _workflow_response(api, engagement_id, to_state, headers):
    """Raw response of one engagement performance-dimension leg."""
    return api.create_workflow_transition(
        engagement_id, factories.workflow_transition_payload(to_state), headers=headers
    )


def _finding_response(api, finding_id, to_state, headers):
    """Raw response of one inspection-finding lifecycle leg."""
    return api.create_finding_transition(
        finding_id, factories.finding_transition_payload(to_state), headers=headers
    )


def _released_review_engagement(api, ctx):
    """A REVIEW engagement (eqr_required false) walked to REPORT_RELEASED."""
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    for state in RELEASE_LEGS:
        fixtures.workflow_step(api, engagement, state, ctx["ep_headers"])
    return engagement


def _verified_deficiency_finding(api, ctx):
    """The full monitoring ladder: released engagement through to a VERIFIED finding."""
    engagement = _released_review_engagement(api, ctx)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    fixtures.run_selector(api, ctx, inspection["id"])
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
    # The owner submits and reports completion; a different partner accepts.
    fixtures.plan_step(api, ctx, plan["id"], "SUBMITTED", completed_action_count=4)
    assertions.read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            factories.remediation_transition_payload("ACCEPTED"),
            headers=ctx["mp_headers"],
        )
    )
    fixtures.plan_step(api, ctx, plan["id"], "COMPLETED", completed_action_count=4)
    assertions.read_entity(
        _finding_response(api, finding["id"], "VERIFIED", ctx["mp_headers"])
    )
    return {
        "engagement": engagement,
        "inspection": inspection,
        "selection": selection,
        "finding": finding,
        "plan": plan,
        "rca": rca,
    }


def test_quality_risk_create_is_never_observable_in_draft(api):
    """A recorded quality risk is already ASSESSED with its inherent score computed.

    "`DRAFT` is nominal only: within the same create request the server computes
    `inherent_risk_score` as the `likelihood` multiplied by the `impact` ... and
    advances the risk to `ASSESSED` before the response is written."

    Design: Corner/state_machines/quality_risk_create_is_never_observable_in_draft
    """
    ctx = _firm_context(api)

    risk = fixtures.new_quality_risk(
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

    assertions.assert_fields(
        risk,
        state="ASSESSED",
        inherent_risk_score=25,
        residual_risk_score=None,
        severity_band="NONE",
        evaluation_basis="NONE",
        response_count=0,
        reopen_count=0,
    )


def test_engagement_workflow_walks_planning_to_report_released(api):
    """Each forward performance leg bumps version by one and needs no review when none is required.

    "When `eqr_required` is false no quality review is required at all and the
    leg proceeds unconditionally. On success the engagement's `eqr_concurred_at`
    is set to the `concluded_at` instant of the concurring review — or left null
    when `eqr_required` was false — and the `version` increments."

    Design: Corner/state_machines/engagement_workflow_walks_planning_to_report_released
    """
    ctx = _firm_context(api)
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    fixtures.workflow_step(api, engagement, "FIELDWORK", ctx["ep_headers"])
    fixtures.workflow_step(api, engagement, "EQR_PENDING", ctx["ep_headers"])

    cleared = assertions.read_entity(
        _workflow_response(api, engagement["id"], "EQR_CLEARED", ctx["ep_headers"])
    )

    assertions.assert_fields(
        cleared,
        workflow_state="EQR_CLEARED",
        file_state="OPEN",
        eqr_concurred_at=None,
        risk_score=8,
        eqr_required=False,
    )
    # create 1, FIELDWORK 2, EQR_PENDING 3, EQR_CLEARED 4.
    assertions.assert_version_is(cleared, 4)


def test_report_released_stamps_release_date_and_frees_partner_load(api):
    """Releasing the report dates the release from the clock and frees partner load.

    "Releasing the report, `EQR_CLEARED → REPORT_RELEASED`, stamps
    `report_release_date` with the date portion of the logical clock, recomputes
    the engagement partner's `open_engagement_count` (which decreases by one,
    since released engagements leave the open set), and increments the
    engagement's `version`."

    Design: Corner/state_machines/report_released_stamps_release_date_and_frees_partner_load
    """
    ctx = _firm_context(api)
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    for state in ("FIELDWORK", "EQR_PENDING", "EQR_CLEARED"):
        fixtures.workflow_step(api, engagement, state, ctx["ep_headers"])

    released = assertions.read_entity(
        _workflow_response(api, engagement["id"], "REPORT_RELEASED", ctx["ep_headers"])
    )

    assertions.assert_fields(
        released,
        workflow_state="REPORT_RELEASED",
        report_release_date=DEFAULT_CLOCK_DATE,
    )
    assertions.assert_version_is(released, 5)
    partner = assertions.read_entity(
        api.get_partner(ctx["ep"]["id"], headers=ctx["qc_headers"])
    )
    assertions.assert_fields(partner, open_engagement_count=0, last_inspected_year=None)


def test_engagement_workflow_planning_to_report_released_is_rejected(api):
    """Skipping the intermediate performance legs is refused and changes nothing.

    "Requesting a `to_state` that is a real state of the dimension but not
    reachable from the row's current state is refused with
    `ERR_INVALID_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/engagement_workflow_planning_to_report_released_is_rejected
    """
    ctx = _firm_context(api)
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )

    response = _workflow_response(
        api, engagement["id"], "REPORT_RELEASED", ctx["ep_headers"]
    )

    validate_error(response, ERR_INVALID_TRANSITION, expected_status=409)
    read = fixtures.read_engagement(api, engagement["id"], ctx["ep_headers"])
    assertions.assert_fields(
        read, workflow_state="PLANNING", version=1, report_release_date=None
    )


def test_file_assembly_during_fieldwork_is_rejected_by_cross_dimension_guard(api):
    """Documentation assembly follows the report, so it is barred during fieldwork.

    "`OPEN → ASSEMBLED` requires that the engagement's `workflow_state` already
    be `EQR_CLEARED` or `REPORT_RELEASED`."

    Design: Corner/state_machines/file_assembly_during_fieldwork_is_rejected_by_cross_dimension_guard
    """
    ctx = _firm_context(api)
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    fixtures.workflow_step(api, engagement, "FIELDWORK", ctx["ep_headers"])

    response = api.create_file_transition(
        engagement["id"],
        factories.file_transition_payload("ASSEMBLED"),
        headers=ctx["ep_headers"],
    )

    validate_error(response, ERR_INVALID_TRANSITION, expected_status=409)
    read = fixtures.read_engagement(api, engagement["id"], ctx["ep_headers"])
    assertions.assert_fields(
        read, file_state="OPEN", workflow_state="FIELDWORK", version=2
    )


def test_eqr_concerns_raised_cascades_engagement_back_to_fieldwork(api):
    """Raising concerns records the round and drives the engagement back to fieldwork.

    "that leg increments `concern_round_count` by 1, copies the text into
    `last_concern_summary`, and cascades onto the engagement, driving it
    `EQR_PENDING → FIELDWORK` and clearing its `eqr_concurred_at`."

    Design: Corner/state_machines/eqr_concerns_raised_cascades_engagement_back_to_fieldwork
    """
    ctx = _firm_context(api)
    reviewer = fixtures.new_partner(
        api,
        ctx["firm_id"],
        full_name="Lena Ortiz",
        cpa_license_state="TX",
        designations=["EQ_REVIEWER"],
        cpe_hours_last_3y=150,
    )
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Borealis Pension Trust",
        engagement_type="ERISA_AUDIT",
        period_end="2026-04-30",
    )
    in_fieldwork = fixtures.workflow_step(
        api, engagement, "FIELDWORK", ctx["ep_headers"]
    )
    eqr = assertions.created_entity(
        api.assign_quality_review(
            engagement["id"],
            factories.quality_review_assignment_payload(
                reviewer["id"], in_fieldwork["version"]
            ),
            headers=ctx["qc_headers"],
        )
    )
    reviewer_headers = make_eq_reviewer_headers(reviewer["id"])
    assertions.read_entity(
        api.create_quality_review_transition(
            eqr["id"],
            factories.quality_review_transition_payload("IN_PROGRESS"),
            headers=reviewer_headers,
        )
    )
    fixtures.workflow_step(api, engagement, "EQR_PENDING", ctx["ep_headers"])
    summary = "Group audit instructions for the plan trustee were not documented."

    raised = assertions.read_entity(
        api.create_quality_review_transition(
            eqr["id"],
            factories.quality_review_transition_payload(
                "CONCERNS_RAISED", concern_summary=summary
            ),
            headers=reviewer_headers,
        )
    )

    assertions.assert_fields(
        raised,
        state="CONCERNS_RAISED",
        concern_round_count=1,
        last_concern_summary=summary,
    )
    read_engagement = fixtures.read_engagement(
        api, engagement["id"], ctx["ep_headers"]
    )
    assertions.assert_fields(
        read_engagement, workflow_state="FIELDWORK", eqr_concurred_at=None
    )
    read_reviewer = assertions.read_entity(
        api.get_partner(reviewer["id"], headers=ctx["qc_headers"])
    )
    assertions.assert_fields(read_reviewer, open_eqr_count=1)


def test_finding_second_verification_returns_already_verified(api):
    """Verification is not idempotent: a second pass is refused and no counter moves.

    "It requires the finding to be in `REMEDIATED`; a finding already in
    `VERIFIED` is refused with `ERR_FINDING_ALREADY_VERIFIED` (HTTP 409)."

    Design: Corner/state_machines/finding_second_verification_returns_already_verified
    """
    ctx = _firm_context(api)
    ladder = _verified_deficiency_finding(api, ctx)

    response = _finding_response(
        api, ladder["finding"]["id"], "VERIFIED", ctx["mp_headers"]
    )

    validate_error(response, ERR_FINDING_ALREADY_VERIFIED, expected_status=409)
    read = assertions.read_entity(
        api.get_inspection_finding(
            ladder["finding"]["id"], headers=ctx["qc_headers"]
        )
    )
    assertions.assert_fields(read, state="VERIFIED", reopen_count=0)
    firm = assertions.read_entity(
        api.get_firm(ctx["firm_id"], headers=ctx["mp_headers"])
    )
    assertions.assert_fields(
        firm, open_deficiency_count=0, risk_posture="STABLE"
    )


def test_finding_reopen_restores_firm_counters_exactly(api):
    """Reopening a verified finding compensates the firm's counters exactly.

    "`VERIFIED → REOPENED` clears `verified_at` back to null, increments the
    finding's `reopen_count` by 1, and **compensates the firm's counters
    exactly**: `open_deficiency_count` is incremented by 1 ... restoring both to
    the values they held immediately before verification."

    Design: Corner/state_machines/finding_reopen_restores_firm_counters_exactly
    """
    ctx = _firm_context(api)
    ladder = _verified_deficiency_finding(api, ctx)

    reopened = assertions.read_entity(
        _finding_response(api, ladder["finding"]["id"], "REOPENED", ctx["qc_headers"])
    )

    assertions.assert_fields(
        reopened,
        state="REOPENED",
        verified_at=None,
        reopen_count=1,
        classification="DEFICIENCY",
        class_points=3,
    )
    firm = assertions.read_entity(
        api.get_firm(ctx["firm_id"], headers=ctx["mp_headers"])
    )
    assertions.assert_fields(
        firm,
        open_deficiency_count=1,
        open_material_failure_count=0,
        risk_posture="STABLE",
    )


def test_accepted_peer_review_cannot_transition_again(api, committee_headers):
    """An accepted peer review is terminal, so re-issuing its report is refused.

    "the two terminal states `ACCEPTED` and `FOLLOW_UP_REQUIRED`" — a `to_state`
    that exists in the machine but is unreachable is a transition conflict.

    Design: Corner/state_machines/accepted_peer_review_cannot_transition_again
    """
    ctx = _firm_context(api)
    engagement = _released_review_engagement(api, ctx)
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    fixtures.run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    fixtures.inspection_step(
        api,
        ctx,
        inspection["id"],
        "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    fixtures.inspection_step(api, ctx, inspection["id"], "CONCLUDED")

    reviewer = fixtures.new_peer_reviewer(
        api,
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
    review = fixtures.new_peer_review(
        api,
        ctx["firm_id"],
        review_type="SYSTEM_REVIEW",
        year_end="2026-06-30",
        scheduled_window_start="2026-10-01",
        scheduled_window_end="2026-10-15",
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    fixtures.set_scope(api, review["id"], reviewer["id"])
    selection = fixtures.select_engagement(
        api, review["id"], reviewer["id"], engagement["id"], hours_committed=12
    )
    fixtures.peer_review_step(api, review["id"], "FIELDWORK", reviewer_headers)
    fixtures.record_disposition(
        api, selection["id"], reviewer["id"], "NO_MATTER", non_conforming=False
    )
    fixtures.peer_review_step(api, review["id"], "RATING_DRAFTED", reviewer_headers)
    fixtures.peer_review_step(api, review["id"], "REPORT_ISSUED", reviewer_headers)
    fixtures.peer_review_step(api, review["id"], "ACCEPTED", committee_headers)

    response = api.create_peer_review_transition(
        review["id"],
        factories.peer_review_transition_payload("REPORT_ISSUED"),
        headers=committee_headers,
    )

    validate_error(response, ERR_INVALID_TRANSITION, expected_status=409)
    read = assertions.read_entity(
        api.get_peer_review(review["id"], headers=committee_headers)
    )
    assertions.assert_fields(read, state="ACCEPTED", rating="PASS")
    firm = assertions.read_entity(
        api.get_firm(ctx["firm_id"], headers=ctx["mp_headers"])
    )
    assertions.assert_fields(
        firm, last_peer_review_rating="PASS", risk_posture="STABLE"
    )
    roster = assertions.read_entity(
        api.get_peer_reviewer(reviewer["id"], headers=committee_headers)
    )
    assertions.assert_fields(roster, active_review_count=0)
