"""State-machine invariants: invalid transitions, terminal lockdown, side-effect cascades."""
import pytest
from test_helpers import (
    api_client, validate_error, get_success_data, TEST_USERS,
    set_clock, create_department, create_requisition,
    setup_approved_req_with_screened_app, setup_offer_in_state,
    schedule_interview, create_candidate, create_application,
    accept_offer, make_headers,
)


# =========================================================================
# Instance: requisition_approve_from_draft_invalid_state
# =========================================================================

def test_requisition_approve_from_draft_invalid_state(api, hiring_manager_headers):
    """PRD §2.10: "5. State-machine declaration: the target resource is in a
    state from which the requested transition is declared
    (`ERR_INVALID_STATE`)."
    PRD §3.2: "Submission for approval requires `openings` to be at least 1
    and `base_salary_max_cents` to be strictly greater than
    `base_salary_min_cents`. Submitting advances the requisition from
    `DRAFT` to `PENDING_APPROVAL`..."
    PRD §3.2: "Approval from `PENDING_APPROVAL` to `APPROVED` is the
    privilege of a `HiringManager` other than the submitter..."

    Design: Corner/state_machines/requisition_approve_from_draft_invalid_state
    """
    dept = create_department()
    req = create_requisition(dept["id"])
    # Never submit → still DRAFT.
    res = api_client.approve_requisition(req["id"], hiring_manager_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =========================================================================
# Instance: application_withdraw_from_hired_terminal_lockdown
# =========================================================================

def test_application_withdraw_from_hired_terminal_lockdown(api, recruiter_headers):
    """PRD §3.4: "Three terminal pathways exist out of the active states. The
    recruiter may reject an application from any of `APPLIED`, `SCREENING`,
    or `INTERVIEWING`, moving it to `REJECTED`. The candidate may withdraw
    from the same three states, moving the application to `WITHDRAWN`."

    PRD §3.4 enumerates the active states `withdraw` is declared from
    (APPLIED, SCREENING, INTERVIEWING). HIRED is not in that list, so a
    withdraw call against a HIRED application must surface as
    ERR_INVALID_STATE (PRD §2.10 priority 5).

    Design: Corner/state_machines/application_withdraw_from_hired_terminal_lockdown
    """
    set_clock("2027-03-01T00:00:00Z")
    ctx = setup_offer_in_state(
        "EXTENDED",
        req_overrides={"base_salary_max_cents": 15_000_000, "openings": 1},
        base_salary_cents=12_000_000,
    )
    cand = ctx["candidate"]
    offer = ctx["offer"]
    app_id = ctx["app"]["id"]
    accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
    app_after = get_success_data(api_client.get_application(app_id, recruiter_headers))
    assert app_after["status"] == "HIRED"

    res = api_client.withdraw_application(app_id,
                                          make_headers(cand["id"], "Candidate"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =========================================================================
# Instance: interview_cascade_first_interview_application_to_interviewing
# =========================================================================

def test_interview_cascade_first_interview_application_to_interviewing(
        api, recruiter_headers):
    """PRD §3.4: "The transition from `SCREENING` to `INTERVIEWING` is
    system-driven and fires automatically when the first interview is
    created on the application — see §3.5."
    PRD §3.5: "Scheduling the first interview on an application cascades
    the application from `SCREENING` to `INTERVIEWING` and bumps the
    application's `version`."

    Design: Corner/state_machines/interview_cascade_first_interview_application_to_interviewing
    """
    set_clock("2027-04-01T00:00:00Z")
    dept, req, cand, app = setup_approved_req_with_screened_app()
    schedule_interview(app["id"], panel_user_ids=["emp_csc_p1"],
                       scheduled_at="2027-04-02T10:00:00Z", duration_minutes=60)
    app_after = get_success_data(api_client.get_application(app["id"], recruiter_headers))
    assert app_after["status"] == "INTERVIEWING"


# =========================================================================
# Instance: cascade_other_application_rejected_when_candidate_hired_elsewhere
# =========================================================================

def test_cascade_other_application_rejected_when_candidate_hired_elsewhere(
        api, recruiter_headers):
    """PRD §3.6: "rejects every other non-terminal application by the same
    candidate."
    PRD §3.6 (offer accept side-effects): "cascades the linked application
    to `HIRED`, bubbles the requisition's `filled_count` up by one ...
    rejects every other non-terminal application by the same candidate."

    Design: Corner/state_machines/cascade_other_application_rejected_when_candidate_hired_elsewhere
    """
    set_clock("2027-05-01T00:00:00Z")
    # First, set up Dept + Req1 (APPROVED) + Candidate + Application1 + Application2
    # (against a second requisition under the same department).
    from test_helpers import create_approved_requisition, screen_application
    dept = create_department(budget_cents=200_000_000)
    _, req1 = create_approved_requisition(
        department_id=dept["id"],
        req_overrides={"base_salary_max_cents": 15_000_000, "openings": 1},
    )
    _, req2 = create_approved_requisition(
        department_id=dept["id"],
        req_overrides={"title": "Role2",
                       "base_salary_max_cents": 15_000_000, "openings": 1},
    )
    cand = create_candidate(full_name="Multi Cand",
                            email="multicand_x@example.com")
    app1 = create_application(cand["id"], req1["id"])
    app2 = create_application(cand["id"], req2["id"])
    screen_application(app1["id"])
    # Drive app1 through accept.
    from test_helpers import (create_offer, fully_approve_offer, extend_offer)
    offer = create_offer(app1["id"], base_salary_cents=12_000_000)
    offer = fully_approve_offer(offer["id"])
    extend_offer(offer["id"])
    accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

    app1_after = get_success_data(api_client.get_application(app1["id"], recruiter_headers))
    app2_after = get_success_data(api_client.get_application(app2["id"], recruiter_headers))
    assert app1_after["status"] == "HIRED"
    assert app2_after["status"] == "REJECTED", \
        f"Expected other-app cascade to REJECTED, got {app2_after['status']}"
