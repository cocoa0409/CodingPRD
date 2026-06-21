"""Invalid transitions, precondition enforcement, terminal lockdown, guarded transitions.

Translates the Corner/state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data, ApiErrorId,
    setup_active_placement, setup_offer_extended_scenario,
    create_skill, create_client, create_open_job_order, create_candidate,
    create_draft_invoice, create_timesheet, submit_timesheet,
    drive_submission_to_offer_extended, create_placement, start_placement,
    make_account_manager_headers, make_recruiter_headers,
    make_client_headers, make_candidate_headers,
)

AM = make_account_manager_headers()
RECRUITER = make_recruiter_headers()


def test_open_an_already_open_job_order_returns_not_draft(api):
    """PRD 3.2: "opening requires the order to currently be `DRAFT` (otherwise
    `ERR_JOB_ORDER_NOT_DRAFT`)."
    PRD 3.2: "an `ON_HOLD` order may be resumed back to `OPEN`, which requires it to
    currently be `ON_HOLD` (otherwise `ERR_JOB_ORDER_NOT_ON_HOLD`)."

    A `target_status=OPEN` request collapses two PRD transitions — open-from-DRAFT
    (guarded by ERR_JOB_ORDER_NOT_DRAFT) and resume-from-ON_HOLD (guarded by
    ERR_JOB_ORDER_NOT_ON_HOLD). When the order is already OPEN, neither guard is
    satisfiable and the PRD names BOTH error ids without pinning which one fires for
    this collapsed case; a faithful implementer may surface either. The invariant
    the PRD does pin is that the order is NOT re-opened (it stays OPEN), so the
    assertion accepts either named guard error.

    Design: Corner/state_machines/job_order_open_from_filled_returns_invalid
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, _v = create_open_job_order(cl["id"], openings=1)  # already OPEN
    resp = api.patch_job_order(jo["id"], {"target_status": "OPEN"}, AM)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_JOB_ORDER_NOT_DRAFT, ApiErrorId.ERR_JOB_ORDER_NOT_ON_HOLD],
    )
    unchanged = validate_success(api.get_job_order(jo["id"], AM))
    assert unchanged["status"] == "OPEN", f"status should remain OPEN, got {unchanged['status']}"


def test_pause_an_already_on_hold_job_order_returns_not_open(api):
    """PRD 3.2: "An `OPEN` order may be paused, moving to `ON_HOLD`, which requires the order to
    currently be `OPEN` (otherwise `ERR_JOB_ORDER_NOT_OPEN`)."

    First pause OPEN -> ON_HOLD succeeds; a second pause from ON_HOLD is rejected with
    ERR_JOB_ORDER_NOT_OPEN.

    Design: Corner/state_machines/job_order_resume_from_open_returns_not_on_hold
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, _v = create_open_job_order(cl["id"], openings=1)
    get_success_data(api.patch_job_order(jo["id"], {"target_status": "ON_HOLD"}, AM))
    resp = api.patch_job_order(jo["id"], {"target_status": "ON_HOLD"}, AM)
    validate_error(resp, ApiErrorId.ERR_JOB_ORDER_NOT_OPEN)


def test_cancel_a_non_draft_job_order_returns_not_draft(api):
    """PRD 3.2: "From `DRAFT`, the order may instead be cancelled, advancing to `CANCELLED`,
    which likewise requires the order to be `DRAFT` (otherwise `ERR_JOB_ORDER_NOT_DRAFT`)."

    Design: Corner/state_machines/cancel_job_order_after_open_returns_not_draft
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, _v = create_open_job_order(cl["id"], openings=1)  # OPEN, left DRAFT
    resp = api.patch_job_order(jo["id"], {"target_status": "CANCELLED"}, AM)
    validate_error(resp, ApiErrorId.ERR_JOB_ORDER_NOT_DRAFT)


def test_approve_a_draft_timesheet_returns_bad_state(api):
    """PRD 3.6: "A `Client` then either approves or rejects a `SUBMITTED` timesheet — both
    transitions require it to currently be `SUBMITTED` (otherwise `ERR_TIMESHEET_BAD_STATE`)."

    Design: Corner/state_machines/timesheet_approve_from_draft_returns_bad_state
    """
    scen = setup_active_placement()
    pl, cand, cl = scen["placement"], scen["candidate"], scen["client"]
    ts = create_timesheet(pl["id"], cand["id"], "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 40)
    resp = api.patch_timesheet(ts["id"], {"target_status": "APPROVED"}, make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_TIMESHEET_BAD_STATE)


def test_pay_a_draft_invoice_returns_bad_state(api):
    """PRD 3.8: "From `ISSUED`, the manager may mark the invoice `PAID`, which requires it to
    currently be `ISSUED` (otherwise `ERR_INVOICE_BAD_STATE`)."

    Design: Corner/state_machines/invoice_pay_from_draft_returns_bad_state
    """
    cl = create_client(name="Acme")
    inv = create_draft_invoice(cl["id"])
    resp = api.patch_invoice(inv["id"], {"target_status": "PAID"}, AM)
    validate_error(resp, ApiErrorId.ERR_INVOICE_BAD_STATE)


def test_issue_an_empty_invoice_returns_invoice_empty(api):
    """PRD 3.8: "issuing requires the invoice to currently be `DRAFT` (otherwise
    `ERR_INVOICE_BAD_STATE`) and requires it to carry at least one line item (otherwise
    `ERR_INVOICE_EMPTY`)."

    Design: Corner/state_machines/issue_empty_invoice_returns_invoice_empty
    """
    cl = create_client(name="Acme")
    inv = create_draft_invoice(cl["id"])
    resp = api.patch_invoice(inv["id"], {"target_status": "ISSUED"}, AM)
    validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY)


def test_extend_offer_without_passed_interview_returns_no_passed_interview(api):
    """PRD 3.3: "Extending an offer requires the submission to currently be `INTERVIEWING`
    (otherwise `ERR_SUBMISSION_BAD_STATE`), requires that at least one interview for this
    submission has an `outcome` of `PASSED` (otherwise `ERR_NO_PASSED_INTERVIEW`)."

    A submission at INTERVIEWING whose only interview is still PENDING cannot extend an offer.

    Design: Corner/state_machines/extend_offer_without_passed_interview_returns_no_passed_interview
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    jo, _v = create_open_job_order(cl["id"], openings=1)
    cand = create_candidate(full_name="Cara Dev", skill_codes=["JAVA"])
    client_headers = make_client_headers(cl["id"])
    sub = get_success_data(api.create_submission(
        {"job_order_id": jo["id"], "candidate_id": cand["id"], "submitted_pay_rate_cents": 8000},
        RECRUITER))
    get_success_data(api.patch_submission(sub["id"], {"target_status": "CLIENT_REVIEW"}, RECRUITER))
    get_success_data(api.create_interview(
        sub["id"], {"scheduled_start": "2026-06-10T14:00:00Z", "scheduled_end": "2026-06-10T15:00:00Z"},
        client_headers))  # interview stays PENDING
    resp = api.patch_submission(sub["id"], {"target_status": "OFFER_EXTENDED"}, client_headers)
    validate_error(resp, ApiErrorId.ERR_NO_PASSED_INTERVIEW)


def test_convert_a_temp_placement_returns_not_convertible(api):
    """PRD 3.7: "Conversion requires the placement's `placement_type` to be `TEMP_TO_PERM`
    (otherwise `ERR_PLACEMENT_NOT_CONVERTIBLE`)."

    Design: Corner/state_machines/convert_temp_placement_returns_not_convertible
    """
    scen = setup_active_placement()  # default employment_type TEMP
    resp = api.convert_placement(scen["placement"]["id"], {"annual_salary_cents": 10000000}, AM)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_CONVERTIBLE)


def test_deactivate_an_already_inactive_candidate_returns_not_available(api):
    """PRD 3.1: "this deactivation is permitted only while the candidate is `AVAILABLE`, and an
    attempt to deactivate a candidate not in that state is rejected with
    `ERR_CANDIDATE_NOT_AVAILABLE`."

    Design: Corner/state_machines/deactivated_candidate_terminal_lockdown
    """
    create_skill(code="JAVA", category="TECH")
    cand = create_candidate(full_name="Gone", skill_codes=["JAVA"])
    get_success_data(api.patch_candidate(cand["id"], {"target_status": "INACTIVE"}, RECRUITER))
    resp = api.patch_candidate(cand["id"], {"target_status": "INACTIVE"}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_AVAILABLE)


def test_place_an_inactive_candidate_returns_candidate_inactive(api):
    """PRD 3.4: "Then the candidate must not be `INACTIVE`; otherwise `ERR_CANDIDATE_INACTIVE`."

    A submission reaches OFFER_EXTENDED, then its candidate is deactivated to INACTIVE; placing
    from that submission -> ERR_CANDIDATE_INACTIVE.

    Design: Corner/state_machines/place_inactive_candidate_returns_candidate_inactive
    """
    scen = setup_offer_extended_scenario()
    get_success_data(api.patch_candidate(scen["candidate"]["id"], {"target_status": "INACTIVE"}, RECRUITER))
    resp = api.create_placement(
        {"submission_id": scen["submission"]["id"], "start_date": "2026-06-15T00:00:00Z",
         "end_date": "2026-12-15T00:00:00Z", "expected_job_order_version": scen["jo_version"],
         "standard_weekly_hours": 40}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_INACTIVE)
