"""State-machine workflow tests: cyclic transitions and precondition enforcement.

Translates queue-A non_linear_state_machine instances and queue-B state_machine
corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_tenant_headers, make_landlord_headers, make_caseworker_headers,
    create_program_payload, create_tenant_payload, create_landlord_payload,
    create_unit_payload, create_application_payload, income_source_payload,
    build_application, build_approved_application, create_disbursement,
    set_clock,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]


# =====================================================================
# Rule 3 — non_linear_state_machine
# =====================================================================

def test_application_info_request_moves_to_info_requested(api):
    """PRD §3.6: "From review, the caseworker may request more information — moving
    `status` to `INFO_REQUESTED` and optionally attaching a `note` — after which either
    the owning tenant or the owning landlord resubmits, moving `status` back to
    `UNDER_REVIEW`; this request/resubmit pair forms a cycle that may repeat."

    Design: Difficulty/non_linear_state_machine/application_info_request_review_cycle
    """
    ctx = build_application(
        api, review=True, approver_id="cw-x",
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    aid = ctx["aid"]
    data = validate_success(api.request_info(aid, {"note": "need paystubs"}, CW))
    assert data["status"] == "INFO_REQUESTED"


def test_application_resubmit_returns_to_under_review(api):
    """PRD §3.6: "From review, the caseworker may request more information — moving
    `status` to `INFO_REQUESTED` and optionally attaching a `note` — after which either
    the owning tenant or the owning landlord resubmits, moving `status` back to
    `UNDER_REVIEW`; this request/resubmit pair forms a cycle that may repeat."

    Design: Difficulty/non_linear_state_machine/application_info_request_review_cycle
    """
    ctx = build_application(
        api, review=True, approver_id="cw-y",
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-04-30",
        requested_prospective_months=2, ledger_lines=[],
    )
    aid, tid = ctx["aid"], ctx["tid"]
    get_success_data(api.request_info(aid, {"note": "need paystubs"}, CW))
    data = validate_success(api.resubmit_application(aid, make_tenant_headers(tid)))
    assert data["status"] == "UNDER_REVIEW"


def test_disbursement_retry_returns_to_pending(api):
    """PRD §3.7: "A failed payment is not final: a `CaseWorker` may retry it, advancing
    `status` from `FAILED` back to `PENDING`, which re-reserves both funds and months."

    Design: Difficulty/non_linear_state_machine/disbursement_fail_retry_cycle
    """
    ctx = build_approved_application(api, approver_id="cw-approver-6")
    aid, av = ctx["aid"], ctx["version"]
    did = create_disbursement(api, aid, amount_cents=1000000, months_covered=5,
                              coverage_kind="COMBINED", version=av, issuer_id="cw-issuer-6")["id"]
    get_success_data(api.send_disbursement(did, {"payment_reference": "ACH-6"}, make_caseworker_headers("cw-issuer-6")))
    get_success_data(api.fail_disbursement(did, {"reason": "bad account"}, ADMIN))

    data = validate_success(api.retry_disbursement(did, make_caseworker_headers("cw-issuer-6")))
    assert data["status"] == "PENDING"


def test_disbursement_retry_re_reserves_tenant_months(api):
    """PRD §3.7: "A failed payment is not final: a `CaseWorker` may retry it, advancing
    `status` from `FAILED` back to `PENDING`, which re-reserves both funds and months."

    Design: Difficulty/non_linear_state_machine/disbursement_fail_retry_cycle
    """
    ctx = build_approved_application(api, approver_id="cw-approver-6b")
    aid, tid, av = ctx["aid"], ctx["tid"], ctx["version"]
    did = create_disbursement(api, aid, amount_cents=1000000, months_covered=5,
                              coverage_kind="COMBINED", version=av, issuer_id="cw-issuer-6b")["id"]
    get_success_data(api.send_disbursement(did, {"payment_reference": "ACH-6"}, make_caseworker_headers("cw-issuer-6b")))
    get_success_data(api.fail_disbursement(did, {"reason": "bad account"}, ADMIN))
    get_success_data(api.retry_disbursement(did, make_caseworker_headers("cw-issuer-6b")))

    tenant = get_success_data(api.get_tenant(tid, ADMIN))
    assert tenant["months_used"] == 5


# =====================================================================
# Queue B — state_machines corner instances
# =====================================================================

def test_submit_with_incomplete_landlord_section_rejected(api):
    """PRD §3.3: "Submission enforces the co-application quorum: if either
    `tenant_section_status` or `landlord_section_status` is still `INCOMPLETE`, the
    submission is rejected with `ERR_SECTION_INCOMPLETE` (HTTP 409)"

    Design: Corner/state_machines/submit_with_incomplete_section_returns_section_incomplete
    """
    ctx = build_application(
        api, do_tenant_section=True, add_ledger=False, do_landlord_section=False,
        submit=False, review=False,
        income_sources=(("WAGES", 400000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31",
        requested_prospective_months=1,
    )
    resp = api.submit_application(ctx["aid"], make_tenant_headers(ctx["tid"]))
    validate_error(resp, ApiErrorId.ERR_SECTION_INCOMPLETE.value, expected_status=409)


def test_review_from_draft_is_invalid_state(api):
    """PRD §3.6: "A `CaseWorker` takes a submitted application under review, moving
    `status` from `SUBMITTED` to `UNDER_REVIEW`."
    PRD §2.6: "then whether the target is in a state from which the requested transition
    is defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/review_from_draft_returns_invalid_state
    """
    ctx = build_application(
        api, income_sources=(), do_tenant_section=False, add_ledger=False,
        do_landlord_section=False, submit=False, review=False,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31",
        requested_prospective_months=1,
    )
    resp = api.review_application(ctx["aid"], CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_verify_w9_from_missing_is_invalid_state(api):
    """PRD §3.2: "Attempting a W-9 transition from a state where it is undefined yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/verify_w9_from_missing_returns_invalid_state
    """
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    resp = api.verify_w9(lid, {"decision": "VERIFIED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
