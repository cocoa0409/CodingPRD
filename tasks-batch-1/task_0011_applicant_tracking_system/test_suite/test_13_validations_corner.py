"""Validation violations: duplicate application, duplicate offer, panelist mismatch,
incomplete feedback, salary out of band, background-check independence."""
import pytest
from test_helpers import (
    api_client, validate_error, get_success_data, TEST_USERS,
    set_clock,
    setup_approved_req_with_screened_app,
    create_offer, schedule_interview, create_interview_payload,
    create_interview_feedback_payload,
    create_offer_payload, create_application_payload,
    setup_offer_in_state, accept_offer,
    fetch_background_check_for_offer, start_background_check,
    resolve_background_check_payload,
    make_headers,
)


# =========================================================================
# Instance: duplicate_application_same_candidate_same_requisition
# =========================================================================

def test_duplicate_application_same_candidate_same_requisition(api, recruiter_headers):
    """PRD §3.4: "The system also rejects a duplicate application against the
    same (candidate, requisition) pair with `ERR_DUPLICATE_APPLICATION`..."

    Design: Corner/validations/duplicate_application_same_candidate_same_requisition
    """
    dept, req, cand, app = setup_approved_req_with_screened_app()
    # First application already exists from the fixture. Try a second.
    payload = create_application_payload(cand["id"], req["id"])
    res = api_client.create_application(payload, recruiter_headers)
    validate_error(res, "ERR_DUPLICATE_APPLICATION", expected_status=422)


# =========================================================================
# Instance: duplicate_offer_second_pending_blocked
# =========================================================================

def test_duplicate_offer_second_pending_blocked(api, recruiter_headers):
    """PRD §3.6: "At most one offer per application may exist in the active
    set `{PENDING_APPROVAL, APPROVED, EXTENDED, ACCEPTED}`; a second active
    offer triggers `ERR_DUPLICATE_OFFER`."

    Design: Corner/validations/duplicate_offer_second_pending_blocked
    """
    dept, req, cand, app = setup_approved_req_with_screened_app(
        req_overrides={"base_salary_max_cents": 15_000_000},
    )
    create_offer(app["id"], base_salary_cents=12_000_000)
    # Second offer on same application.
    payload = create_offer_payload(app["id"], base_salary_cents=13_000_000)
    res = api_client.create_offer(payload, recruiter_headers)
    validate_error(res, "ERR_DUPLICATE_OFFER", expected_status=422)


# =========================================================================
# Instance: panelist_not_assigned_in_panel_blocked
# =========================================================================

def test_panelist_not_assigned_in_panel_blocked(api, hiring_manager_headers):
    """PRD §3.5: "The `panelist_user_id` must belong to the interview's
    `panel_user_ids`; otherwise the feedback is rejected with
    `ERR_PANELIST_NOT_ASSIGNED`."

    Design: Corner/validations/panelist_not_assigned_in_panel_blocked
    """
    set_clock("2027-07-01T00:00:00Z")
    dept, req, cand, app = setup_approved_req_with_screened_app()
    intv = schedule_interview(app["id"], panel_user_ids=["emp_in_panel"],
                              scheduled_at="2027-07-02T10:00:00Z",
                              duration_minutes=60)
    payload = create_interview_feedback_payload(
        intv["id"], "emp_NOT_in_panel", score=4, comments="x"
    )
    res = api_client.create_interview_feedback(payload, hiring_manager_headers)
    validate_error(res, "ERR_PANELIST_NOT_ASSIGNED", expected_status=422)


# =========================================================================
# Instance: feedback_incomplete_blocks_interview_complete
# =========================================================================

def test_feedback_incomplete_blocks_interview_complete(api, recruiter_headers,
                                                       hiring_manager_headers):
    """PRD §3.5: "Completing an interview moves `SCHEDULED` to `COMPLETED`
    and is permitted only when every panelist named in `panel_user_ids`
    has submitted a feedback row — otherwise the call is rejected with
    `ERR_FEEDBACK_INCOMPLETE`."

    Design: Corner/validations/feedback_incomplete_blocks_interview_complete
    """
    set_clock("2027-08-01T00:00:00Z")
    dept, req, cand, app = setup_approved_req_with_screened_app()
    intv = schedule_interview(app["id"],
                              panel_user_ids=["emp_fbi_p1", "emp_fbi_p2"],
                              scheduled_at="2027-08-02T10:00:00Z",
                              duration_minutes=60)
    # Only one of two panelists submits feedback.
    fb_payload = create_interview_feedback_payload(intv["id"], "emp_fbi_p1",
                                                   score=4, comments="x")
    api_client.create_interview_feedback(fb_payload, hiring_manager_headers)
    res = api_client.complete_interview(intv["id"], recruiter_headers)
    validate_error(res, "ERR_FEEDBACK_INCOMPLETE", expected_status=409)


# =========================================================================
# Instance: salary_out_of_band_blocks_offer_create
# =========================================================================

def test_salary_out_of_band_blocks_offer_create(api, recruiter_headers):
    """PRD §3.6: "The `base_salary_cents` must lie within the linked
    requisition's `[base_salary_min_cents, base_salary_max_cents]` band
    inclusive; a value outside the band is rejected with
    `ERR_SALARY_OUT_OF_BAND`."

    Design: Corner/validations/salary_out_of_band_blocks_offer_create
    """
    dept, req, cand, app = setup_approved_req_with_screened_app(
        req_overrides={"base_salary_min_cents": 10_000_000,
                       "base_salary_max_cents": 15_000_000},
    )
    # 9_500_000 < min 10_000_000 → out of band.
    payload = create_offer_payload(app["id"], base_salary_cents=9_500_000)
    res = api_client.create_offer(payload, recruiter_headers)
    validate_error(res, "ERR_SALARY_OUT_OF_BAND", expected_status=422)


# =========================================================================
# Instance: bgc_independence_blocks_resolver_who_is_submitter
# =========================================================================

def test_bgc_independence_blocks_resolver_who_is_submitter(api):
    """PRD §2.8: "The compliance officer resolving a background check must
    not be the requisition's `submitter_user_id` nor the requisition's
    `approver_user_id`. A violation is rejected with
    `ERR_BGC_INDEPENDENCE` (HTTP 403)."

    Design: Corner/validations/bgc_independence_blocks_resolver_who_is_submitter
    """
    set_clock("2027-09-01T00:00:00Z")
    user_x_recruiter = make_headers("user_x_bgc", "Recruiter")
    # The user_x_bgc identity must BE the requisition's submitter so the BGC
    # resolver-equals-submitter independence violation can be triggered.
    from test_helpers import (
        create_department, create_requisition, submit_requisition, approve_requisition,
        create_candidate, create_application, screen_application,
        create_offer, fully_approve_offer, extend_offer,
    )
    dept = create_department()
    req = create_requisition(dept["id"], recruiter_headers=user_x_recruiter,
                             title="IndRole", target_level="MID",
                             base_salary_min_cents=10_000_000,
                             base_salary_max_cents=15_000_000, openings=1)
    submit_requisition(req["id"], recruiter_headers=user_x_recruiter)
    approve_requisition(req["id"])  # HiringManager hm_bob (default)
    cand = create_candidate(full_name="Ind Cand", email="indc_x@example.com")
    app = create_application(cand["id"], req["id"], recruiter_headers=user_x_recruiter)
    screen_application(app["id"], recruiter_headers=user_x_recruiter)
    offer = create_offer(app["id"], base_salary_cents=12_000_000,
                         recruiter_headers=user_x_recruiter)
    offer = fully_approve_offer(offer["id"])
    extend_offer(offer["id"], recruiter_headers=user_x_recruiter)
    accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
    bgc = fetch_background_check_for_offer(offer["id"])
    start_background_check(bgc["id"])
    # Resolver X-User-ID == requisition submitter (user_x_bgc) → BGC_INDEPENDENCE.
    headers_bad_resolver = make_headers("user_x_bgc", "ComplianceOfficer")
    res = api_client.resolve_background_check(
        bgc["id"], resolve_background_check_payload("PASSED"), headers_bad_resolver
    )
    validate_error(res, "ERR_BGC_INDEPENDENCE", expected_status=403)
