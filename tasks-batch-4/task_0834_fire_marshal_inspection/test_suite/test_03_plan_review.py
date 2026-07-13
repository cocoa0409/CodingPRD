"""Plan review — three parallel discipline axes, the OPEN->APPROVED bubble-up,
the corrections cycle, and the not-UNDER_REVIEW rejection.
"""
from test_helpers import (
    validate_error,
    create_submitted_application, create_corrections_cycle_application,
    decide_discipline, get_plan_review_for_application, get_application,
    api_client, make_applicant_headers, get_success_data,
    discipline_decision_payload,
    TEST_USERS,
)

PLAN_REVIEWER = TEST_USERS["plan_reviewer_headers"]


# ─── Difficulty/non_linear_state_machine/plan_review_parallel_axes_independent
def test_approving_one_axis_leaves_others_under_review(api):
    """PRD §3.4: "A decision that approves an axis while others are still under review
    leaves the review `OPEN` and the application `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/plan_review_parallel_axes_independent
    """
    _prop, _app, pr = create_submitted_application(applicant_user_id="app-3")
    updated = decide_discipline(pr["id"], "SPRINKLER", "APPROVED")
    assert updated["sprinkler_status"] == "APPROVED"
    assert updated["alarm_status"] == "UNDER_REVIEW"
    assert updated["egress_status"] == "UNDER_REVIEW"


def test_overall_status_open_while_axes_pending(api):
    """PRD §3.4: "A derived `overall_status` summarizes them: it is `OPEN` until all
    three axes are `APPROVED`, at which point it becomes `APPROVED`."

    Design: Difficulty/non_linear_state_machine/plan_review_parallel_axes_independent
    """
    _prop, _app, pr = create_submitted_application(applicant_user_id="app-3b")
    updated = decide_discipline(pr["id"], "SPRINKLER", "APPROVED")
    assert updated["overall_status"] == "OPEN"


# ─── Difficulty/non_linear_state_machine/permit_application_cyclic_corrections
def test_resubmit_returns_application_to_under_review_and_counts(api):
    """PRD §3.4: "each axis that is `CORRECTIONS_REQUIRED` returns to `UNDER_REVIEW`,
    the review's `correction_cycles` increments by one, and the application's
    `resubmit_count` increments by one (which is what later inflates the final fee's
    surcharge). The application itself returns from `CORRECTIONS_REQUIRED` to
    `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/permit_application_cyclic_corrections
    """
    _prop, app, pr = create_corrections_cycle_application(applicant_user_id="app-4")
    get_success_data(api_client.resubmit_corrections(pr["id"], make_applicant_headers("app-4")))
    updated_app = get_application(app["id"])
    assert updated_app["status"] == "UNDER_REVIEW"
    assert updated_app["resubmit_count"] == 1


def test_resubmit_returns_corrected_axis_to_under_review(api):
    """PRD §3.4: "each axis that is `CORRECTIONS_REQUIRED` returns to `UNDER_REVIEW`,
    the review's `correction_cycles` increments by one, and the application's
    `resubmit_count` increments by one (which is what later inflates the final fee's
    surcharge)."

    Design: Difficulty/non_linear_state_machine/permit_application_cyclic_corrections
    """
    _prop, _app, pr = create_corrections_cycle_application(applicant_user_id="app-4b")
    updated_pr = get_success_data(
        api_client.resubmit_corrections(pr["id"], make_applicant_headers("app-4b")))
    assert updated_pr["sprinkler_status"] == "UNDER_REVIEW"
    assert updated_pr["correction_cycles"] == 1


# ─── Difficulty/boundary_precision_check/plan_review_empty_pending_set_approval
def test_two_of_three_axes_approved_stays_open(api):
    """PRD §3.4: "A decision that approves an axis while others are still under review
    leaves the review `OPEN` and the application `UNDER_REVIEW`."

    Design: Difficulty/boundary_precision_check/plan_review_empty_pending_set_approval
    """
    _prop, _app, pr = create_submitted_application(applicant_user_id="app-6")
    decide_discipline(pr["id"], "SPRINKLER", "APPROVED")
    after_two = decide_discipline(pr["id"], "ALARM", "APPROVED")
    assert after_two["overall_status"] == "OPEN", \
        "two of three axes approved (one still pending) must leave overall_status OPEN"


def test_all_three_axes_approved_bubbles_up(api):
    """PRD §3.4: "If the decision is the one that brings all three axes to `APPROVED`
    — that is, after applying it, zero axes remain outside `APPROVED` — then the
    review's `overall_status` bubbles up to `APPROVED` and the parent application
    advances from `UNDER_REVIEW` to `APPROVED`."

    Design: Difficulty/boundary_precision_check/plan_review_empty_pending_set_approval
    """
    _prop, app, pr = create_submitted_application(applicant_user_id="app-6b")
    decide_discipline(pr["id"], "SPRINKLER", "APPROVED")
    decide_discipline(pr["id"], "ALARM", "APPROVED")
    after_three = decide_discipline(pr["id"], "EGRESS", "APPROVED")
    assert after_three["overall_status"] == "APPROVED"
    assert get_application(app["id"])["status"] == "APPROVED"


# ─── Corner/state_machines/corner_discipline_decision_on_approved_axis_returns_409
def test_second_decision_on_approved_axis_rejected(api):
    """PRD §3.4: "The named axis must currently be `UNDER_REVIEW`; a decision aimed at
    an axis that is not `UNDER_REVIEW` is rejected with `ERR_REVIEW_INCOMPLETE`."

    Design: Corner/state_machines/corner_discipline_decision_on_approved_axis_returns_409
    """
    _prop, _app, pr = create_submitted_application(applicant_user_id="app-9")
    decide_discipline(pr["id"], "SPRINKLER", "APPROVED")
    res = api.discipline_decision(
        pr["id"], discipline_decision_payload("SPRINKLER", "APPROVED"), PLAN_REVIEWER)
    validate_error(res, "ERR_REVIEW_INCOMPLETE", expected_status=409)
