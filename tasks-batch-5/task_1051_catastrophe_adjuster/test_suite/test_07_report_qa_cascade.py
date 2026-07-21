"""Report revision cycle and the depth-3 QA-revision revert cascade."""
from test_helpers import validate_success, get_success_data, TEST_USERS
from test_helpers import fixtures as fx

DESK = TEST_USERS["desk_examiner_headers"]


# --------------------------------------------------------------------------
# Difficulty: cyclic report state machine (SUBMITTED -> REVISION_REQUESTED -> SUBMITTED)
# --------------------------------------------------------------------------
def _loop_back_to_submitted(api):
    ctx = fx.setup_two_adjusters_report_submitted(api)
    # QA requests a revision -> report REVISION_REQUESTED, inspection REOPENED.
    fx.qa_decision(api, ctx["rpt_id"], ctx["qa_id"], "REVISION_REQUESTED", qa_notes="add elevations")
    # Adjuster reworks: restart + re-complete the inspection, then resubmit.
    fx.start_inspection(api, ctx["insp_id"], ctx["adj_id"])
    fx.complete_inspection(api, ctx["insp_id"], ctx["adj_id"])
    fx.submit_report(api, ctx["rpt_id"], ctx["adj_id"])
    return ctx


def test_report_loops_back_to_submitted(api):
    """PRD 3.5: "The adjuster then reworks and resubmits — restarting the reopened
    inspection, re-completing it, and submitting the report again — whereupon the same
    forward side effects (assignment back to WORK_COMPLETE, claim back to UNDER_REVIEW)
    fire once more. This submit/revise loop may cycle any number of times before an
    eventual approval."

    Design: Difficulty/non_linear_state_machine/report_revision_cycle
    """
    ctx = _loop_back_to_submitted(api)
    data = validate_success(api.get_report(ctx["rpt_id"], DESK))
    assert data["status"] == "SUBMITTED"


def test_report_revision_count_increments_to_one(api):
    """PRD 3.5: "A revision request moves the report SUBMITTED -> REVISION_REQUESTED,
    increments revision_count by 1, and triggers a three-hop revert cascade."

    Design: Difficulty/non_linear_state_machine/report_revision_cycle
    """
    ctx = _loop_back_to_submitted(api)
    data = validate_success(api.get_report(ctx["rpt_id"], DESK))
    assert data["revision_count"] == 1


# --------------------------------------------------------------------------
# Difficulty: depth-3 revert cascade from a QA revision
# --------------------------------------------------------------------------
def _request_revision(api):
    ctx = fx.setup_two_adjusters_report_submitted(api)
    get_success_data(
        api.qa_decision_report(ctx["rpt_id"], {"decision": "REVISION_REQUESTED", "qa_notes": "redo"},
                               fx.make_qa_reviewer_headers(ctx["qa_id"]))
    )
    return ctx


def test_qa_revision_reverts_report_and_inspection(api):
    """PRD 3.5: "A revision request moves the report SUBMITTED -> REVISION_REQUESTED,
    increments revision_count by 1, and triggers a three-hop revert cascade: hop one,
    the parent inspection reverts COMPLETED -> REOPENED; hop two, caused by that
    inspection reopening, the parent assignment reverts WORK_COMPLETE -> FIELDWORK; hop
    three, caused by the assignment reverting, the claim reverts UNDER_REVIEW ->
    IN_PROGRESS."

    Design: Difficulty/transitive_cascade/qa_revision_cascade_depth3
    """
    ctx = _request_revision(api)
    report = validate_success(api.get_report(ctx["rpt_id"], DESK))
    inspection = validate_success(api.get_inspection(ctx["insp_id"], DESK))
    assert report["status"] == "REVISION_REQUESTED"
    assert inspection["status"] == "REOPENED"


def test_qa_revision_reverts_assignment_and_claim(api):
    """PRD 3.5: "hop two, caused by that inspection reopening, the parent assignment
    reverts WORK_COMPLETE -> FIELDWORK; hop three, caused by the assignment reverting,
    the claim reverts UNDER_REVIEW -> IN_PROGRESS."

    Design: Difficulty/transitive_cascade/qa_revision_cascade_depth3
    """
    ctx = _request_revision(api)
    assignment = validate_success(api.get_assignment(ctx["asg_id"], DESK))
    claim = validate_success(api.get_claim(ctx["claim_id"], DESK))
    assert assignment["work_status"] == "FIELDWORK"
    assert claim["status"] == "IN_PROGRESS"
