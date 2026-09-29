"""Label clearance against stability state, the rejection loop, and the close ladder."""
import pytest

from test_helpers import (
    add_timepoint,
    assert_deliverable,
    assert_gate_review,
    book_pilot_run,
    cast_vote,
    complete_pilot_run,
    create_formulation,
    deliverable_by_type,
    draft_label,
    intake_project,
    make_functional_reviewer_headers,
    make_gate_chair_headers,
    open_gate_review,
    open_shelf_life_study,
    read_formulation,
    read_project,
    register_pilot_line,
    register_stage_gate,
    schedule_gate_review,
    screen_project,
    set_clock,
    start_pilot_run,
    validate_error,
    validate_success,
)

SUBMITTER = make_functional_reviewer_headers("sub-mkt")
DECIDER = make_functional_reviewer_headers("rev-mkt")


def _label_awaiting_stability():
    """A PILOT_PASSED formulation, an ACTIVE study with no readings, and a DRAFT label."""
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(line_code="AKR-3")
    project = intake_project(name="Label Gate Probe")
    formulation = create_formulation(project["id"])
    run = book_pilot_run(formulation["id"], line["id"], committed_cost_usd=20000.00)
    set_clock("2026-08-06T08:00:00Z")
    start_pilot_run(run["id"])
    complete_pilot_run(run["id"], 8500)
    study = open_shelf_life_study(
        formulation["id"], duration_days=30, committed_cost_usd=30000.00,
        start_at="2026-08-06T17:00:00Z",
    )
    label = draft_label(project["id"], formulation["id"], label_version="LG-v1",
                        claims=["Sparkling yuzu, no added sugar"])
    return {"project": project, "formulation": formulation, "study": study, "label": label}


def test_artwork_cannot_be_reviewed_while_stability_is_unproven(api, innovation_lead_headers):
    """Submitting a label against a merely PILOT_PASSED formulation is refused.

    PRD: "Critically, the described formulation must be `SHELF_LIFE_CLEARED` at submission time
    — claims cannot be reviewed against a formula whose stability is unproven — and a
    formulation in any other status answers `ERR_FORMULATION_INVALID_STATE` (409)."

    Design: Difficulty/cross_entity_state_dependency/label_submit_depends_on_formulation_shelf_life_state
    """
    ctx = _label_awaiting_stability()
    assert read_formulation(ctx["formulation"]["id"])["status"] == "PILOT_PASSED"

    response = api.submit_label_approval(ctx["label"]["id"], {}, innovation_lead_headers)

    validate_error(response, "ERR_FORMULATION_INVALID_STATE", 409)
    unchanged = validate_success(
        api.get_label_approval(ctx["label"]["id"], innovation_lead_headers)
    )
    assert unchanged["status"] == "DRAFT", "the refused submission left the artwork in DRAFT"
    assert unchanged["version"] == ctx["label"]["version"], "no field of the label changed"


def test_the_same_submission_succeeds_once_the_study_clears_the_formulation(
    api, innovation_lead_headers
):
    """One stability reading closes the study, clears the formulation and unblocks the label.

    PRD: "A `PASS` closes the study `ACTIVE → PASSED`, drives the formulation `PILOT_PASSED →
    SHELF_LIFE_CLEARED` and auto-approves the `SHELF_LIFE_REPORT` checklist item."

    Design: Difficulty/cross_entity_state_dependency/label_submit_depends_on_formulation_shelf_life_state
    """
    ctx = _label_awaiting_stability()
    validate_error(
        api.submit_label_approval(ctx["label"]["id"], {}, innovation_lead_headers),
        "ERR_FORMULATION_INVALID_STATE",
        409,
    )

    closed_study = add_timepoint(ctx["study"]["id"], 30, 88.00)
    submitted = validate_success(
        api.submit_label_approval(ctx["label"]["id"], {}, innovation_lead_headers)
    )

    assert closed_study["status"] == "PASSED"
    assert closed_study["verdict"] == "PASS"
    assert closed_study["min_quality_score"] == pytest.approx(88.00, abs=0.01)
    assert read_formulation(ctx["formulation"]["id"])["status"] == "SHELF_LIFE_CLEARED"
    assert submitted["status"] == "IN_REVIEW", (
        "the identical request is admitted once the formulation is cleared"
    )
    assert submitted["claims"] == ["Sparkling yuzu, no added sugar"]


def test_a_rejected_checklist_item_is_resubmitted_and_then_approved(api):
    """The revision loop ends in APPROVED carrying the second evidence URL.

    PRD: "`submission_count` counts every entry into `SUBMITTED`, which is how a completed
    revision loop is evidenced — an item that was rejected once and resubmitted shows
    `submission_count` 2."

    Design: Difficulty/non_linear_state_machine/deliverable_reject_resubmit_revision_cycle
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(gate_number=2, category="SNACK")
    project = intake_project(owner_user_id="lead-pc", name="Cycle Probe", category="SNACK",
                             project_type="LINE_EXTENSION")
    item = validate_success(
        api.create_deliverable(
            project["id"],
            {"gate_id": gate["id"], "deliverable_type": "MARKETING_LAUNCH_PLAN",
             "owner_function": "MARKETING", "due_at": "2026-08-25T00:00:00Z"},
            make_gate_chair_headers("chair-pc"),
        ),
        201,
    )
    assert_deliverable(item)
    assert item["status"] == "PENDING" and item["submission_count"] == 0

    validate_success(
        api.submit_deliverable(
            item["id"], {"evidence_url": "https://npd.example/pc/launch-plan-v1"}, SUBMITTER
        )
    )
    rejected = validate_success(
        api.decide_deliverable(
            item["id"], {"decision": "REJECT", "comment": "Media plan missing"}, DECIDER
        )
    )
    validate_success(
        api.submit_deliverable(
            item["id"], {"evidence_url": "https://npd.example/pc/launch-plan-v2"}, SUBMITTER
        )
    )
    approved = validate_success(
        api.decide_deliverable(
            item["id"], {"decision": "APPROVE", "comment": "Media plan complete"}, DECIDER
        )
    )

    assert rejected["status"] == "REJECTED"
    assert approved["status"] == "APPROVED"
    assert approved["submission_count"] == 2
    assert approved["evidence_url"] == "https://npd.example/pc/launch-plan-v2"
    assert approved["submitted_by_user_id"] == "sub-mkt"
    assert approved["decided_by_user_id"] == "rev-mkt"
    assert read_project(project["id"])["dev_status"] == "IDEA", (
        "the checklist loop never touches the development track"
    )


def test_resubmission_out_of_rejected_clears_the_stale_decider(api):
    """The item awaits its fresh verdict with no decider recorded.

    PRD: "The `PENDING → SUBMITTED` and `REJECTED → SUBMITTED` transitions differ in one
    respect: a resubmission out of `REJECTED` also clears `decided_by_user_id`, so the item
    carries no stale decider while it awaits a fresh verdict."

    Design: Difficulty/non_linear_state_machine/deliverable_reject_resubmit_revision_cycle
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(gate_number=2, category="SNACK")
    project = intake_project(owner_user_id="lead-pc", name="Cycle Probe", category="SNACK",
                             project_type="LINE_EXTENSION")
    item = validate_success(
        api.create_deliverable(
            project["id"],
            {"gate_id": gate["id"], "deliverable_type": "MARKETING_LAUNCH_PLAN",
             "owner_function": "MARKETING", "due_at": "2026-08-25T00:00:00Z"},
            make_gate_chair_headers("chair-pc"),
        ),
        201,
    )
    validate_success(
        api.submit_deliverable(
            item["id"], {"evidence_url": "https://npd.example/pc/launch-plan-v1"}, SUBMITTER
        )
    )
    validate_success(
        api.decide_deliverable(
            item["id"], {"decision": "REJECT", "comment": "Media plan missing"}, DECIDER
        )
    )

    resubmitted = validate_success(
        api.submit_deliverable(
            item["id"], {"evidence_url": "https://npd.example/pc/launch-plan-v2"}, SUBMITTER
        )
    )

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submission_count"] == 2
    assert resubmitted["decided_by_user_id"] is None, "the stale decider was cleared"
    assert resubmitted["submitted_by_user_id"] == "sub-mkt"
    assert resubmitted["evidence_url"] == "https://npd.example/pc/launch-plan-v2"


def test_thin_quorum_is_reported_before_an_incomplete_checklist(api):
    """A close that misses quorum and completeness at once answers the quorum error.

    PRD: "`vote_count` must be at least the gate's `quorum_size`, else `ERR_QUORUM_NOT_MET`
    (409) — and because quorum is checked **before the decision is derived**, a lone `REJECT`
    ballot under quorum reports the quorum error rather than killing the project."

    Design: Difficulty/priority_pair_validation_conflict/quorum_check_precedes_checklist_completeness_on_close
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(
        gate_number=2, category="SNACK",
        required_deliverable_types=["CONSUMER_CONCEPT_TEST"], quorum_size=2,
    )
    project = intake_project(owner_user_id="lead-qp", name="Quorum Probe", category="SNACK",
                             project_type="LINE_EXTENSION")
    screen_project(project["id"], chair_user_id="chair-qp")
    review = schedule_gate_review(project["id"], gate["id"], chair_user_id="chair-qp")
    open_gate_review(review["id"], chair_user_id="chair-qp")
    cast_vote(review["id"], function="OPERATIONS", vote="APPROVE", voter_user_id="rev-ops")

    response = api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-qp"))

    validate_error(response, "ERR_QUORUM_NOT_MET", 409)
    concept_item = deliverable_by_type(project["id"], "CONSUMER_CONCEPT_TEST")
    assert concept_item["status"] == "PENDING", (
        "the checklist really was incomplete, so the lower band was live too"
    )


def test_the_refused_close_leaves_the_review_in_session_with_its_single_ballot(api):
    """Nothing about the review, its completeness or the project moved.

    PRD: "Both passing branches — and only the passing branches — must clear three further
    bars, evaluated in this order: `deliverable_completeness_pct` must be exactly `100.00`,
    else `ERR_DELIVERABLE_CHECKLIST_INCOMPLETE` (422); `readiness_index` must be at least the
    gate's `readiness_floor_index`, else `ERR_GATE_READINESS_BELOW_FLOOR` (422); and the
    authoritative business case must clear all three financial hurdles, else
    `ERR_BUSINESS_CASE_HURDLE_NOT_MET` (422)."

    Design: Difficulty/priority_pair_validation_conflict/quorum_check_precedes_checklist_completeness_on_close
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(
        gate_number=2, category="SNACK",
        required_deliverable_types=["CONSUMER_CONCEPT_TEST"], quorum_size=2,
    )
    project = intake_project(owner_user_id="lead-qp", name="Quorum Probe", category="SNACK",
                             project_type="LINE_EXTENSION")
    screen_project(project["id"], chair_user_id="chair-qp")
    review = schedule_gate_review(project["id"], gate["id"], chair_user_id="chair-qp")
    open_gate_review(review["id"], chair_user_id="chair-qp")
    cast_vote(review["id"], function="OPERATIONS", vote="APPROVE", voter_user_id="rev-ops")

    validate_error(
        api.close_gate_review(review["id"], {}, make_gate_chair_headers("chair-qp")),
        "ERR_QUORUM_NOT_MET",
        409,
    )

    review = validate_success(
        api.get_gate_review(review["id"], make_gate_chair_headers("chair-qp"))
    )
    assert_gate_review(review)
    assert review["status"] == "IN_SESSION"
    assert review["decision"] is None
    assert review["closed_at"] is None
    assert review["vote_count"] == 1
    assert review["deliverable_completeness_pct"] == pytest.approx(0.00, abs=0.01)
    project = read_project(project["id"])
    assert project["dev_status"] == "SCREENED"
    assert project["next_gate_number"] == 2
