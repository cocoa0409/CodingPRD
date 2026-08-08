"""Payroll runs: claiming, lock/post lifecycle, posting segregation of duties, the
post-immutability void gate, and resource-specific 404 codes."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    make_facility_manager_headers,
    ApiErrorId,
)
from test_helpers.fixtures import (
    setup_active_assignment, submit_timesheet, approve_timesheet,
    statement_for_timesheet, get_assignment_data,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]
PA1 = TEST_USERS["payroll_admin_headers"]
PA2 = TEST_USERS["payroll_admin_2_headers"]
PA3 = TEST_USERS["payroll_admin_3_headers"]


def _run_with_posted_statement(api):
    ctx = setup_active_assignment(api, clock="2026-06-14")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    run = validate_success(api.create_payroll_run(
        {"period_start_date": "2026-06-01", "period_end_date": "2026-06-30"}, PA1), 201)
    return ctx, ts, run


def test_void_rejected_when_statement_already_posted(api):
    """PRD §3.6: "A PayrollAdmin may void an APPROVED timesheet by supplying the target to
    state, provided the linked earnings statement is still FINALIZED; if that statement has
    already been POSTED it is immutable and the void is rejected with
    ERR_STATEMENT_ALREADY_POSTED."
    PRD §3.7: "Posting records posted_by_user_id and flips every claimed statement whose
    ledger status is FINALIZED to POSTED"

    Design: Difficulty/cross_entity_state_dependency/timesheet_void_gated_by_posted_earnings_statement_state
    """
    ctx, ts, run = _run_with_posted_statement(api)
    assert run["statement_count"] == 1 and run["total_gross_bill_cents"] == 504000
    assert run["total_pay_cost_cents"] == 382132 and run["total_margin_cents"] == 121868
    assert run["opened_by_user_id"] == "pa-1"
    validate_success(api.transition_payroll_run(run["id"], "LOCKED", PA1), 200)
    posted = validate_success(api.transition_payroll_run(run["id"], "POSTED", PA2), 200)
    assert posted["status"] == "POSTED" and posted["posted_by_user_id"] == "pa-2"
    st = statement_for_timesheet(api, ts["id"])
    assert st["status"] == "POSTED" and st["payroll_run_id"] == run["id"]
    validate_error(api.transition_timesheet(ts["id"], {"to": "VOIDED"}, PA3),
                   ApiErrorId.ERR_STATEMENT_ALREADY_POSTED.value)


def test_void_rejection_leaves_timesheet_and_ledger_intact(api):
    """PRD §3.6: "if that statement has already been POSTED it is immutable and the void is
    rejected with ERR_STATEMENT_ALREADY_POSTED." — the rejected void mutates nothing.

    Design: Difficulty/cross_entity_state_dependency/timesheet_void_gated_by_posted_earnings_statement_state
    """
    ctx, ts, run = _run_with_posted_statement(api)
    validate_success(api.transition_payroll_run(run["id"], "LOCKED", PA1), 200)
    validate_success(api.transition_payroll_run(run["id"], "POSTED", PA2), 200)
    api.transition_timesheet(ts["id"], {"to": "VOIDED"}, PA3)
    st = statement_for_timesheet(api, ts["id"])
    assert st["status"] == "POSTED"
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["realized_gross_bill_cents"] == 504000


def test_payroll_run_cannot_post_while_still_open(api):
    """PRD §3.7: "Attempting to post a run that is still OPEN, or any other move that is not
    an outgoing edge of the run's current state, is rejected with ERR_INVALID_TRANSITION."

    Design: Corner/state_machines/corner_payroll_run_cannot_post_while_still_open
    """
    run = validate_success(api.create_payroll_run(
        {"period_start_date": "2026-06-01", "period_end_date": "2026-06-30"}, PA1), 201)
    assert run["status"] == "OPEN" and run["statement_count"] == 0
    assert run["total_pay_cost_cents"] == 0 and run["total_gross_bill_cents"] == 0
    assert run["total_margin_cents"] == 0 and run["opened_by_user_id"] == "pa-1"
    validate_error(api.transition_payroll_run(run["id"], "POSTED", PA2),
                   ApiErrorId.ERR_INVALID_TRANSITION.value)
    # It is still OPEN: the legal OPEN -> LOCKED move now succeeds.
    assert validate_success(api.transition_payroll_run(run["id"], "LOCKED", PA1), 200)["status"] == "LOCKED"


def test_same_payroll_admin_cannot_open_and_post_a_run(api):
    """PRD §3.7: "Posting is permitted only out of LOCKED and enforces segregation of
    duties: the acting X-User-ID must differ from opened_by_user_id, else
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/corner_same_payroll_admin_cannot_open_and_post_a_run
    """
    run = validate_success(api.create_payroll_run(
        {"period_start_date": "2026-06-01", "period_end_date": "2026-06-30"}, PA1), 201)
    validate_success(api.transition_payroll_run(run["id"], "LOCKED", PA1), 200)
    validate_error(api.transition_payroll_run(run["id"], "POSTED", PA1),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    posted = validate_success(api.transition_payroll_run(run["id"], "POSTED", PA2), 200)
    assert posted["status"] == "POSTED" and posted["posted_by_user_id"] == "pa-2"


def test_path_not_found_codes_are_resource_specific(api):
    """PRD §2.10: "Which error surfaces depends on which resource the unresolved id
    addresses: ERR_CLINICIAN_NOT_FOUND, ERR_LICENSE_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND, ERR_PACKET_NOT_FOUND, ERR_CREDENTIAL_ITEM_NOT_FOUND,
    ERR_TIMESHEET_NOT_FOUND, ERR_PAYROLL_RUN_NOT_FOUND, or ERR_EXTENSION_NOT_FOUND"

    Design: Corner/errors/corner_path_not_found_codes_are_resource_specific
    """
    validate_error(api.transition_contract(
        "aaaaaaaa-1111-4111-8111-111111111111", {"to": "SENT_FOR_SIGNATURE"}, RECRUITER),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)
    validate_error(api.get_credential_packet("bbbbbbbb-2222-4222-8222-222222222222", CS1),
                   ApiErrorId.ERR_PACKET_NOT_FOUND.value)
    validate_error(api.transition_credential_item(
        "cccccccc-3333-4333-8333-333333333333", "VERIFIED", CS1),
        ApiErrorId.ERR_CREDENTIAL_ITEM_NOT_FOUND.value)
    validate_error(api.transition_timesheet(
        "dddddddd-4444-4444-8444-444444444444", {"to": "APPROVED"},
        make_facility_manager_headers("eeeeeeee-5555-4555-8555-555555555555")),
        ApiErrorId.ERR_TIMESHEET_NOT_FOUND.value)
    validate_error(api.transition_payroll_run(
        "ffffffff-6666-4666-8666-666666666666", "LOCKED", PA1),
        ApiErrorId.ERR_PAYROLL_RUN_NOT_FOUND.value)
    validate_error(api.respond_extension(
        "99999999-7777-4777-8777-777777777777", {"action": "ACCEPT"}, RECRUITER),
        ApiErrorId.ERR_EXTENSION_NOT_FOUND.value)
