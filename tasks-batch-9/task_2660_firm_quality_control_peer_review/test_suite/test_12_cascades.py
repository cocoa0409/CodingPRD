"""Multi-link cascade tests.

Two operations in this service propagate five links deep: classifying an
inspection finding `MATERIAL_FAILURE` (PRD 3.7) and rejecting a corrective
action plan's evidence (PRD 3.9).  Each link fires only because the link before
it fired, and the whole chain lands inside the single request.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.assertions import assert_fields, read_entity
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    make_committee_headers,
    make_engagement_partner_headers,
    make_peer_reviewer_headers,
)

COMMITTEE = make_committee_headers()


def _run_selector(api, ctx, inspection_id: str) -> None:
    """Run the deterministic engagement selector for a cycle (setup only)."""
    response = api.run_inspection_selector(inspection_id, headers=ctx["qc_headers"])
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )


def _stage_material_failure_world(api) -> Dict[str, Any]:
    """Firm with a LOCKED released engagement, a PLANNING engagement, a CRITICAL
    evaluated quality risk and one unclassified finding on the 2024 cycle."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = fixtures.firm_context(api, legal_name="Kelder Vann LLP")
    ep_headers = ctx["ep_headers"]

    e1 = fixtures.released_engagement(
        api,
        ctx,
        client_name="Alder Foods",
        engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    fixtures.file_step(api, e1, "ASSEMBLED", ep_headers)
    locked = fixtures.file_step(api, e1, "LOCKED", ep_headers)
    assert locked["file_state"] == "LOCKED"

    e2 = fixtures.new_engagement(
        api,
        ctx,
        client_name="Marrow Freight",
        engagement_type="AUDIT",
        period_end="2026-06-30",
    )
    assert e2["eqr_required"] is False, "E2 must start without a required review"

    risk = fixtures.new_quality_risk(
        api,
        ctx,
        component="ENGAGEMENT_PERFORMANCE",
        quality_objective_code="QO-1",
        risk_statement=(
            "Engagement teams conclude on judgemental areas without adequate review."
        ),
        likelihood=5,
        impact=5,
    )
    response = fixtures.new_risk_response(
        api,
        ctx,
        risk["id"],
        response_type="PREVENTIVE",
        description="Second-partner review of all judgemental conclusions.",
    )
    fixtures.record_effectiveness_test(
        api,
        ctx,
        response["id"],
        design_effectiveness="EFFECTIVE",
        operating_effectiveness="EFFECTIVE",
    )
    evaluated = read_entity(
        api.create_risk_evaluation(
            risk["id"], f.risk_evaluation_payload("DESIGN_BASIS"),
            headers=ctx["qc_headers"],
        )
    )
    assert evaluated["severity_band"] == "CRITICAL", "residual 16.25 bands CRITICAL"

    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=1
    )
    _run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Impairment conclusion unsupported by evidence",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    return {
        "ctx": ctx,
        "firm_id": ctx["firm_id"],
        "e1": e1,
        "e2": e2,
        "risk": risk,
        "inspection": inspection,
        "selection": selection,
        "finding": finding,
    }


def _classify_material_failure(api, world) -> Dict[str, Any]:
    return fixtures.classify(
        api,
        world["ctx"],
        world["finding"]["id"],
        "MATERIAL_FAILURE",
        pervasiveness="SYSTEMIC",
        affects_report_conclusion=True,
    )


def test_material_failure_classification_scores_the_finding_and_reopens_the_file(api):
    """Links 1 and 2: the classification writes 20 class_points and the firm's
    counters, then drives the released engagement's locked file back to OPEN.

    "Link 2 fires only because link 1 recorded MATERIAL_FAILURE: the selection's
    engagement has its file_state driven LOCKED -> OPEN and its reopened_count
    incremented by 1."

    Design: Difficulty/transitive_cascade/material_failure_classification_five_link_cascade_to_acceptance_freeze
    """
    world = _stage_material_failure_world(api)
    ctx = world["ctx"]

    classified = _classify_material_failure(api, world)
    assert_fields(
        classified,
        classification="MATERIAL_FAILURE",
        class_points=20,
        state="RCA_PENDING",
    )

    selection = read_entity(
        api.get_inspection_selection(world["selection"]["id"], headers=ctx["qc_headers"])
    )
    assert selection["finding_count"] == 1

    firm = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(firm, open_deficiency_count=1, open_material_failure_count=1)

    engagement = read_entity(
        api.get_engagement(world["e1"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        engagement,
        file_state="OPEN",
        reopened_count=1,
        workflow_state="REPORT_RELEASED",
    )


def test_material_failure_reopen_invalidates_the_component_risk_and_posture(api):
    """Links 3 and 4: because the file reopened, the EVALUATED quality risk in the
    finding's component returns to RESPONDED, and because it left EVALUATED the
    firm's critical_risk_count and risk_posture are recomputed.

    "Link 4 fires because link 3 took a risk out of EVALUATED: the firm's
    critical_risk_count is recomputed and the posture ladder is re-run."

    Design: Difficulty/transitive_cascade/material_failure_classification_five_link_cascade_to_acceptance_freeze
    """
    world = _stage_material_failure_world(api)
    ctx = world["ctx"]

    before = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(before, critical_risk_count=1, risk_posture="ELEVATED")

    _classify_material_failure(api, world)

    risk = read_entity(
        api.get_quality_risk(world["risk"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        risk,
        state="RESPONDED",
        severity_band="NONE",
        evaluation_basis="NONE",
        reopen_count=1,
    )
    assert risk["residual_risk_score"] is None, (
        f"residual_risk_score must be cleared, got {risk['residual_risk_score']}"
    )

    firm = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(firm, critical_risk_count=0, risk_posture="CRITICAL")


def test_material_failure_critical_posture_promotes_eqr_required_on_open_work(api):
    """Link 5: a CRITICAL posture promotes eqr_required to true on every engagement
    of the firm still in PLANNING or FIELDWORK, leaving its workflow untouched.

    "Link 5 fires because link 4 produced a CRITICAL posture: every engagement of
    the firm whose workflow_state is PLANNING or FIELDWORK and whose eqr_required
    is still false has eqr_required promoted to true."

    Design: Difficulty/transitive_cascade/material_failure_classification_five_link_cascade_to_acceptance_freeze
    """
    world = _stage_material_failure_world(api)
    ctx = world["ctx"]

    before = read_entity(
        api.get_engagement(world["e2"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(before, eqr_required=False, workflow_state="PLANNING")

    _classify_material_failure(api, world)

    after = read_entity(api.get_engagement(world["e2"]["id"], headers=ctx["qc_headers"]))
    assert_fields(after, eqr_required=True, workflow_state="PLANNING")
    assert after["version"] == before["version"] + 1, (
        "the promoted engagement's version must advance by exactly 1"
    )


def _stage_rejected_corrective_action_world(api) -> Dict[str, Any]:
    """Firm whose FAIL peer review sits in REMEDIATION_SUBMITTED with one
    corrective action plan carrying submitted evidence."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = fixtures.firm_context(api, legal_name="Lorren Skeel LLP")

    e1 = fixtures.released_engagement(
        api,
        ctx,
        client_name="Alder Foods",
        engagement_type="AUDIT",
        period_end="2024-06-30",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2024, target_engagement_count=1
    )
    _run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    fixtures.inspection_step(
        api, ctx, inspection["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    fixtures.inspection_step(api, ctx, inspection["id"], "CONCLUDED")

    reviewer = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Kestrel Peer Review PC",
        license_state="CA",
        qualified_categories=[],
        max_concurrent_reviews=2,
        experience_hours=5000,
    )
    review = fixtures.new_peer_review(
        api,
        ctx["firm_id"],
        review_type="SYSTEM_REVIEW",
        year_end="2026-12-31",
        scheduled_window_start="2026-09-01",
        scheduled_window_end="2026-09-15",
    )
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    fixtures.set_scope(api, review["id"], reviewer["id"])
    selection = fixtures.select_engagement(
        api, review["id"], reviewer["id"], e1["id"], hours_committed=10
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    fixtures.peer_review_step(api, review["id"], "FIELDWORK", reviewer_headers)
    fixtures.record_disposition(
        api, selection["id"], reviewer["id"], "SIGNIFICANT_DEFICIENCY",
        non_conforming=True,
    )
    fixtures.peer_review_step(api, review["id"], "RATING_DRAFTED", reviewer_headers)
    issued = fixtures.peer_review_step(
        api, review["id"], "REPORT_ISSUED", reviewer_headers
    )
    assert issued["rating"] == "FAIL", "one SIGNIFICANT_DEFICIENCY disposition rates FAIL"

    cap = fixtures.corrective_action_plans_of(api, review["id"])[0]
    read_entity(
        api.create_corrective_action_evidence(
            cap["id"], f.corrective_action_evidence_payload(),
            headers=ctx["qc_headers"],
        )
    )
    return {
        "ctx": ctx,
        "firm_id": ctx["firm_id"],
        "reviewer": reviewer,
        "review": review,
        "cap": cap,
    }


def _reject_corrective_action(api, world) -> Dict[str, Any]:
    return read_entity(
        api.create_corrective_action_disposition(
            world["cap"]["id"],
            f.corrective_action_disposition_payload("REJECTED"),
            headers=COMMITTEE,
        )
    )


def test_corrective_action_rejection_terminates_the_plan_and_forks_the_review(api):
    """Links 1 and 2: a REJECTED adjudication moves the plan to its terminal
    REJECTED status and drives the parent review to FOLLOW_UP_REQUIRED.

    "Link 1 sets the plan's status to the terminal REJECTED and increments its
    rejection_count by 1.  Link 2 fires because the plan was rejected: the review
    is driven REMEDIATION_SUBMITTED -> FOLLOW_UP_REQUIRED."

    Design: Difficulty/transitive_cascade/corrective_action_rejection_five_link_cascade_to_follow_up_review
    """
    world = _stage_rejected_corrective_action_world(api)
    ctx = world["ctx"]

    before = read_entity(
        api.get_peer_review(world["review"]["id"], headers=COMMITTEE)
    )
    assert before["state"] == "REMEDIATION_SUBMITTED"

    _reject_corrective_action(api, world)

    cap = read_entity(
        api.get_corrective_action_plan(world["cap"]["id"], headers=COMMITTEE)
    )
    assert_fields(cap, status="REJECTED", rejection_count=1)

    review = read_entity(api.get_peer_review(world["review"]["id"], headers=COMMITTEE))
    assert_fields(review, state="FOLLOW_UP_REQUIRED")
    assert ctx["firm_id"] == review["firm_id"]


def test_corrective_action_rejection_synthesizes_the_follow_up_peer_review(api):
    """Link 3: the fork to FOLLOW_UP_REQUIRED synthesizes exactly one follow-up
    review 180 days after the original window end and releases the reviewer.

    "a new peer review is created for the same firm in state SCHEDULED, with
    prior_peer_review_id set to the rejected review's id, is_follow_up true,
    review_type SYSTEM_REVIEW, year_end copied from the original review,
    scheduled_window_start set 180 days after the original review's
    scheduled_window_end and scheduled_window_end set 14 days after that new
    start; the original reviewer's active_review_count is decremented by 1."

    Design: Difficulty/transitive_cascade/corrective_action_rejection_five_link_cascade_to_follow_up_review
    """
    world = _stage_rejected_corrective_action_world(api)
    original_id = world["review"]["id"]

    _reject_corrective_action(api, world)

    listing = api.list_peer_reviews(
        headers=COMMITTEE, params={"prior_peer_review_id": original_id}
    )
    validate_success(listing)
    body = listing.json()
    assert body["meta"]["total_count"] == 1, (
        f"expected exactly 1 follow-up review, got {body['meta']['total_count']}"
    )
    assert len(body["data"]) == 1
    follow_up = read_entity(api.get_peer_review(body["data"][0]["id"], headers=COMMITTEE))
    assert_fields(
        follow_up,
        is_follow_up=True,
        prior_peer_review_id=original_id,
        state="SCHEDULED",
        review_type="SYSTEM_REVIEW",
        year_end="2026-12-31",
        scheduled_window_start="2027-03-14",
        scheduled_window_end="2027-03-28",
    )
    assert follow_up["assigned_reviewer_id"] is None, (
        "a synthesized follow-up review carries no reviewer yet"
    )

    reviewer = read_entity(
        api.get_peer_reviewer(world["reviewer"]["id"], headers=COMMITTEE)
    )
    assert reviewer["active_review_count"] == 0


def test_corrective_action_rejection_drives_posture_critical_and_freezes_acceptance(api):
    """Links 4 and 5: closing out the rejected review writes the firm's FAIL rating
    and rotation history, which recomputes the posture to CRITICAL and freezes
    acceptance of a must-select engagement type.

    "Link 5 fires when link 4 produced a CRITICAL posture: client acceptance is
    frozen at the firm, so any subsequent attempt to accept an ERISA_AUDIT,
    SINGLE_AUDIT or BROKER_DEALER engagement there is refused with
    ERR_ACCEPTANCE_FROZEN."

    Design: Difficulty/transitive_cascade/corrective_action_rejection_five_link_cascade_to_follow_up_review
    """
    world = _stage_rejected_corrective_action_world(api)
    ctx = world["ctx"]
    reviewer_id = world["reviewer"]["id"]

    _reject_corrective_action(api, world)

    firm = read_entity(api.get_firm(ctx["firm_id"], headers=COMMITTEE))
    assert_fields(firm, last_peer_review_rating="FAIL", risk_posture="CRITICAL")
    assert firm["prior_reviewer_ids"] == [reviewer_id], (
        f"expected [{reviewer_id}], got {firm['prior_reviewer_ids']}"
    )

    refused = api.create_engagement(
        f.engagement_payload(
            ctx["firm_id"],
            ctx["ep"]["id"],
            client_name="Frost Pension Plan",
            engagement_type="ERISA_AUDIT",
            period_end="2026-12-31",
        ),
        headers=make_engagement_partner_headers(ctx["ep"]["id"]),
    )
    validate_error(refused, E.ERR_ACCEPTANCE_FROZEN, 409)
