"""Appeal review cycle, decisions, SoD-adjacent flows, abatement conservation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_officer_headers, make_taxpayer_headers,
    create_active_taxpayer, set_clock,
    create_late_filing_assessment, create_submitted_appeal, get_taxpayer,
    get_assessment,
)


def _tp_assessment_appeal(api, base=100000):
    """ACTIVE taxpayer + ISSUED LATE_FILING assessment (issued 2026-04-20) + SUBMITTED appeal."""
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-04-20T00:00:00Z")
    asmt = create_late_filing_assessment(api, tp["id"], tax_deficiency_cents=base,
                                         original_due_date="2026-01-20T00:00:00Z")
    appeal = create_submitted_appeal(api, asmt["id"], tp["id"])
    return tp, asmt, appeal


def test_request_info_moves_appeal_to_info_requested(api):
    """PRD §3.6: "An `AppealsOfficer` who needs more information moves a `SUBMITTED` appeal
    to `INFO_REQUESTED`, recording the `info_request_note` from the request and bumping `version`."

    Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    resp = api.request_info_appeal(appeal["id"], {"info_request_note": "Provide invoices."},
                                   make_officer_headers("off-1"))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "INFO_REQUESTED"


def test_respond_returns_appeal_to_submitted(api):
    """PRD §3.6: "The owning taxpayer responds to an info request with a `response_note`,
    moving the appeal from `INFO_REQUESTED` back to `SUBMITTED` and bumping `version`".

    Design: Difficulty/non_linear_state_machine/appeal_info_request_cycle
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    validate_success(api.request_info_appeal(appeal["id"], {"info_request_note": "Provide invoices."},
                                             make_officer_headers("off-1")))
    resp = api.respond_appeal(appeal["id"], {"response_note": "Invoices attached."},
                              make_taxpayer_headers(tp["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "SUBMITTED"


def test_allowed_appeal_abates_assessment(api):
    """PRD §3.6: "An `outcome` of `ALLOW` drives the appeal to `ALLOWED` and cascades the
    appealed assessment from `ISSUED` to `ABATED`: the abated assessment's `total_due_cents`
    drops out of the balance".

    Design: Difficulty/compensating_invariant/assessment_abatement_conserves_account_balance
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    validate_success(api.decide_appeal(appeal["id"], {"outcome": "ALLOW"},
                                       make_officer_headers("off-1")))
    asmt_after = get_assessment(api, asmt["id"])
    assert asmt_after["status"] == "ABATED"


def test_abatement_conserves_account_balance(api):
    """PRD §3.6: "Either decision recomputes the owning taxpayer's balance; abating lowers
    it by exactly the abated `total_due_cents`."
    PRD §2.6: "plus the `total_due_cents` of every `Assessment` owned by the taxpayer whose
    `status` is either `ISSUED` or `AFFIRMED` (an `ABATED` assessment contributes nothing)".

    Design: Difficulty/compensating_invariant/assessment_abatement_conserves_account_balance
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    before = get_taxpayer(api, tp["id"])
    assert before["account_balance_cents"] == 113300
    validate_success(api.decide_appeal(appeal["id"], {"outcome": "ALLOW"},
                                       make_officer_headers("off-1")))
    after = get_taxpayer(api, tp["id"])
    assert after["account_balance_cents"] == 0


def test_denied_appeal_affirms_and_keeps_balance(api):
    """PRD §3.6: "An `outcome` of `DENY` drives the appeal to `DENIED` and cascades the
    assessment from `ISSUED` to `AFFIRMED`, leaving its `total_due_cents` in the balance."

    Design: Corner/state_machines/appeal_deny_affirms_assessment_keeps_balance
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    validate_success(api.decide_appeal(appeal["id"], {"outcome": "DENY"},
                                       make_officer_headers("off-1")))
    asmt_after = get_assessment(api, asmt["id"])
    assert asmt_after["status"] == "AFFIRMED"
    tp_after = get_taxpayer(api, tp["id"])
    assert tp_after["account_balance_cents"] == 113300


def test_respond_on_submitted_appeal_rejected(api):
    """PRD §3.6: "responding requires the appeal to currently be `INFO_REQUESTED`
    (otherwise `ERR_INFO_NOT_REQUESTED`) and requires the acting taxpayer to own the
    appealed assessment."

    Design: Corner/state_machines/respond_when_not_info_requested_rejected
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    resp = api.respond_appeal(appeal["id"], {"response_note": "Premature."},
                              make_taxpayer_headers(tp["id"]))
    validate_error(resp, ApiErrorId.ERR_INFO_NOT_REQUESTED, expected_status=409)


def test_appeal_after_window_rejected(api):
    """PRD §3.6: "the appeal must be filed within 60 days of the assessment's `issued_at`,
    measured on the logical clock; filing more than 60 days after issuance is rejected with
    `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_after_window_rejected
    """
    tp = create_active_taxpayer(api)
    set_clock(api, "2026-04-20T00:00:00Z")
    asmt = create_late_filing_assessment(api, tp["id"], tax_deficiency_cents=100000,
                                         original_due_date="2026-01-20T00:00:00Z")
    set_clock(api, "2026-06-20T00:00:00Z")  # 61 days after issuance
    resp = api.create_appeal({"assessment_id": asmt["id"], "grounds": "Too late."},
                             make_taxpayer_headers(tp["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, expected_status=409)


def test_appeal_on_abated_assessment_rejected(api):
    """PRD §3.6: "The assessment must be in `ISSUED` (otherwise `ERR_ASSESSMENT_NOT_ISSUED`,
    and a missing assessment yields `ERR_ASSESSMENT_NOT_FOUND`)".

    Design: Corner/validations/appeal_on_non_issued_assessment_rejected
    """
    tp, asmt, appeal = _tp_assessment_appeal(api)
    validate_success(api.decide_appeal(appeal["id"], {"outcome": "ALLOW"},
                                       make_officer_headers("off-1")))  # -> assessment ABATED
    resp = api.create_appeal({"assessment_id": asmt["id"], "grounds": "Second appeal."},
                             make_taxpayer_headers(tp["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_ISSUED, expected_status=409)
