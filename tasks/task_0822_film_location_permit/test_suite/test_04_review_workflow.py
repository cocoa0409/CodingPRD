"""Submission, the cyclic multi-department review loop, and related invalid-state guards."""
import test_helpers as th
from test_helpers import validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId


def _two_all_dept_under_review(api, company_name):
    """Company + POLICE(ALL) + FIRE(ALL) departments; a DRAFT application (1 location)
    submitted to UNDER_REVIEW with two PENDING reviews. Returns ids."""
    th.set_clock(api, th.DEFAULT_CLOCK)
    pc = th.make_company(api, legal_name=company_name, contact_email=f"{company_name}@x.test", primary_contact="X")
    dept_pol = th.make_department(api, code="POLICE", name="Police")
    dept_fire = th.make_department(api, code="FIRE", name="Fire")
    app = th.make_application(api, pc["id"], title=company_name, synopsis="x")
    th.add_location(api, app["id"], pc["id"])
    th.submit_app(api, app["id"], pc["id"])
    rev_pol = th.get_review(api, app["id"], dept_pol["id"])
    rev_fire = th.get_review(api, app["id"], dept_fire["id"])
    return {"pc_id": pc["id"], "app_id": app["id"],
            "dept_pol_id": dept_pol["id"], "dept_fire_id": dept_fire["id"],
            "rev_pol_id": rev_pol["id"], "rev_fire_id": rev_fire["id"]}


class TestApplicationRevisionLoop:
    def test_reject_drives_application_to_revision_required(self, api):
        """PRD §3.3: "A REJECT moves the review from PENDING to REJECTED and kicks off
        Cascade A: the parent application transitions from UNDER_REVIEW to REVISION_REQUIRED."

        Design: Difficulty/non_linear_state_machine/application_revision_loop
        """
        ctx = th.setup_under_review_single_review(api, company_name="Loop Films")
        th.decide_review(api, ctx["review_id"], ctx["dept_id"], "REJECT")
        app = get_success_data(api.get_application(ctx["app_id"], th.make_coordinator_headers()))
        assert app["status"] == "REVISION_REQUIRED"

    def test_resubmit_reopens_under_review(self, api):
        """PRD §3.3: "When the applicant submits the application, it moves from DRAFT to
        UNDER_REVIEW (or, on a later resubmission, from REVISION_REQUIRED back to
        UNDER_REVIEW)."

        Design: Difficulty/non_linear_state_machine/application_revision_loop
        """
        ctx = th.setup_under_review_single_review(api, company_name="Loop2 Films")
        th.decide_review(api, ctx["review_id"], ctx["dept_id"], "REJECT")
        resp = api.submit_application(ctx["app_id"], {}, th.make_production_company_headers(ctx["pc_id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "UNDER_REVIEW"


class TestDepartmentReviewRevisionCycle:
    def test_request_revision_alone_does_not_move_application(self, api):
        """PRD §3.3: "A REQUEST_REVISION moves it from PENDING to REVISION_REQUESTED; this is a
        soft, non-terminal signal that by itself does not move the application — only an
        outright rejection does."

        Design: Difficulty/non_linear_state_machine/department_review_revision_cycle
        """
        ctx = _two_all_dept_under_review(api, "Cyc1Co")
        th.decide_review(api, ctx["rev_pol_id"], ctx["dept_pol_id"], "REQUEST_REVISION")
        review = th.read_review(api, ctx["rev_pol_id"])
        assert review["status"] == "REVISION_REQUESTED"
        app = get_success_data(api.get_application(ctx["app_id"], th.make_coordinator_headers()))
        assert app["status"] == "UNDER_REVIEW"

    def test_revision_requested_review_resets_to_pending_on_resubmit(self, api):
        """PRD §3.3: "When the applicant addresses the feedback and resubmits, the application
        moves REVISION_REQUIRED → UNDER_REVIEW; as part of that transition, every
        DepartmentReview for the application whose status is REJECTED or REVISION_REQUESTED is
        reset to PENDING, estimated_fee_cents is recomputed from the ESTIMATE permit fee, and
        the application's version increments."

        Design: Difficulty/non_linear_state_machine/department_review_revision_cycle
        """
        ctx = _two_all_dept_under_review(api, "Cyc2Co")
        th.decide_review(api, ctx["rev_pol_id"], ctx["dept_pol_id"], "REQUEST_REVISION")
        th.decide_review(api, ctx["rev_fire_id"], ctx["dept_fire_id"], "REJECT")  # -> REVISION_REQUIRED
        th.submit_app(api, ctx["app_id"], ctx["pc_id"])  # resubmit
        review = th.read_review(api, ctx["rev_pol_id"])
        assert review["status"] == "PENDING"


def test_submit_fans_out_one_review_per_matching_department(api):
    """PRD §3.3: "For each Department whose trigger_condition matches this application, the
    system creates a DepartmentReview in PENDING status linking the application to that
    department. A department with trigger_condition ALL_APPLICATIONS always matches ..."

    Design: Corner/state_machines/submit_side_effect_creates_matching_reviews
    """
    ctx = _two_all_dept_under_review(api, "FanCo")
    resp = api.list_department_reviews(th.make_coordinator_headers(),
                                       params={"application_id": ctx["app_id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(r["status"] == "PENDING" for r in data)


def test_resubmit_from_under_review_is_invalid_state(api):
    """PRD §3.3: "Submission is refused with ERR_INVALID_STATE if the application is not in one
    of those two states."

    Design: Corner/state_machines/resubmit_from_under_review_returns_invalid_state
    """
    ctx = th.setup_under_review_single_review(api, company_name="Idem Co")
    resp = api.submit_application(ctx["app_id"], {}, th.make_production_company_headers(ctx["pc_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_decision_on_approved_review_is_invalid_state(api):
    """PRD §3.3: "An APPROVE moves the review from PENDING to APPROVED, which is terminal for
    that review."

    Design: Corner/state_machines/review_decision_on_approved_returns_invalid_state
    """
    ctx = th.setup_under_review_single_review(api, company_name="Term Co")
    th.decide_review(api, ctx["review_id"], ctx["dept_id"], "APPROVE")
    resp = api.decide_department_review(ctx["review_id"], {"decision": "REJECT"},
                                        th.make_department_reviewer_headers(ctx["dept_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_issue_from_draft_is_invalid_state(api):
    """PRD §3.5: "Issuance is available only from UNDER_REVIEW; from any other state it is
    rejected."

    Design: Corner/state_machines/issue_from_draft_returns_invalid_state
    """
    pc = th.make_company(api, legal_name="Inv Co", contact_email="iv@x.test", primary_contact="T")
    app = th.make_application(api, pc["id"], title="Inv")
    resp = api.issue_application(app["id"], {"expected_application_version": app["version"]},
                                th.make_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
