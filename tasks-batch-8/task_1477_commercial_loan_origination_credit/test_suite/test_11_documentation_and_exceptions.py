"""Exception review loop (waive, clear) and the documentation file: checklist
lifecycle, waiver branch, closing gates, covenant presence, child-create stage
windows, and amendment windows (PRD sections 3.2, 3.3, 3.7).
"""
from test_helpers import (
    ApiErrorId, accept_letter, api_client, add_checklist_item, add_covenant,
    approve_item, attach_statement, cast_vote, clear_exceptions, create_appraiser,
    create_borrower, create_session, deal_commitment, deal_committee_review,
    deal_documentation, deal_intake, deal_underwritten, finalize_spreads,
    get_application, get_letter, issue_letter, issue_term_sheet, list_exceptions,
    loan_application_payload, open_decision, order_and_accept_appraisal,
    respond_sheet, set_clock, setup_officers, spread_and_finalize, spread_statement,
    finalize_statement, statement_payload, submit_application, submit_to_committee,
    transition_item, validate_error, validate_paginated, validate_success,
    waive_exception,
)


def _documentation_deal():
    """Clean 200,000,000 deal in DOCUMENTATION (letter ACCEPTED)."""
    return deal_documentation(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")


def test_clear_exceptions_with_open_exception_rejected():
    """PRD section 3.3: "Only when no `OPEN` exception remains may a
    `CreditPolicyOfficer` clear the review, moving the application
    `EXCEPTION_REVIEW` → `APPRAISAL_REVIEW`; attempting to clear while any
    exception is still `OPEN` is rejected with `ERR_OPEN_POLICY_EXCEPTIONS`."

    Design: Corner/validations/clear_exceptions_with_open_exception_rejected
    """
    ctx = deal_underwritten()  # BEACON -> EXCEPTION_REVIEW (OPEN LOW stress)
    o = ctx["o"]
    assert ctx["application"]["status"] == "EXCEPTION_REVIEW"

    resp = api_client.clear_exceptions(ctx["application"]["id"], o["po"]["headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_POLICY_EXCEPTIONS)

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "EXCEPTION_REVIEW"
    open_exc = list_exceptions(o, app["id"], status="OPEN")
    assert len(open_exc) == 1
    assert open_exc[0]["rule_code"] == "STRESS_DSCR_MINIMUM"


def test_exception_waive_rationale_min_length_and_happy_path():
    """PRD section 3.3: "A `CreditPolicyOfficer` may waive an exception outright,
    supplying a `waiver_rationale` of at least twenty characters; the waiver stamps
    `waived_by_officer_id` with the officer's identity." PRD section 2.8:
    "`waiver_rationale` at least twenty characters wherever it is required ...
    otherwise `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/exception_waive_rationale_min_length_and_happy_path
    """
    ctx = deal_underwritten()
    o = ctx["o"]
    exc = list_exceptions(o, ctx["application"]["id"], rule_code="STRESS_DSCR_MINIMUM",
                          status="OPEN")[0]

    short = api_client.waive_exception(exc["id"], {"waiver_rationale": "nope"}, o["po"]["headers"])
    validate_error(short, ApiErrorId.ERR_VALIDATION)

    waived = waive_exception(o, exc["id"], "Stress shortfall accepted by credit policy desk")
    assert waived["status"] == "WAIVED"
    assert waived["waived_by_officer_id"] == o["po"]["id"]

    assert list_exceptions(o, ctx["application"]["id"], status="OPEN") == []
    cleared = clear_exceptions(o, ctx["application"]["id"])
    assert cleared["status"] == "APPRAISAL_REVIEW"


def test_exception_waive_denied_for_credit_analyst():
    """PRD section 4: waiving a policy exception is restricted to
    `CreditPolicyOfficer`. PRD section 2.1: "An authenticated caller who attempts an
    operation their role is not permitted to perform is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/exception_waive_denied_for_credit_analyst
    """
    ctx = deal_underwritten()
    o = ctx["o"]
    exc = list_exceptions(o, ctx["application"]["id"], rule_code="STRESS_DSCR_MINIMUM",
                          status="OPEN")[0]

    resp = api_client.waive_exception(
        exc["id"], {"waiver_rationale": "Analyst overstepping authority here"},
        o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    still_open = list_exceptions(o, ctx["application"]["id"], status="OPEN")
    assert [e["id"] for e in still_open] == [exc["id"]]


def test_clear_exceptions_denied_for_credit_analyst():
    """PRD section 4: clearing exception review is restricted to
    `CreditPolicyOfficer`. PRD section 2.8: "The caller's role is permitted for
    this operation, including the operation-level restrictions that only a
    `CreditPolicyOfficer` may drive a checklist item to `WAIVED` and only a
    `CommitteeChair` may cast a REMAND vote; otherwise `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403). Applies to every endpoint."

    Design: Corner/rbac/clear_exceptions_denied_for_credit_analyst
    """
    ctx = deal_underwritten()  # EXCEPTION_REVIEW with an OPEN exception
    o = ctx["o"]
    resp = api_client.clear_exceptions(ctx["application"]["id"], o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "EXCEPTION_REVIEW"


def test_checklist_item_resubmission_cycle():
    """PRD section 3.7: "A checklist item's lifecycle runs from `PENDING` to
    `RECEIVED` to either `APPROVED` or `REJECTED`, driven by a `CreditAdministrator`
    through a transition request naming the target in `to`; a `REJECTED` item may be
    resubmitted by moving it back to `PENDING`, re-opening the cycle."

    Design: Corner/state_machines/checklist_item_resubmission_cycle
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Executed promissory note")
    assert item["status"] == "PENDING"

    seq = []
    seq.append(transition_item(o, item["id"], "RECEIVED")["status"])
    seq.append(transition_item(o, item["id"], "REJECTED")["status"])
    seq.append(transition_item(o, item["id"], "PENDING")["status"])
    seq.append(transition_item(o, item["id"], "RECEIVED")["status"])
    seq.append(transition_item(o, item["id"], "APPROVED")["status"])
    assert seq == ["RECEIVED", "REJECTED", "PENDING", "RECEIVED", "APPROVED"], (
        "the resubmission cycle loops through PENDING without recreating the item")


def test_checklist_skip_received_rejected():
    """PRD section 3.7: "A checklist item's lifecycle runs from `PENDING` to
    `RECEIVED` to either `APPROVED` or `REJECTED`" — no direct PENDING → APPROVED
    hop exists — and PRD section 2.8: "The target entity is in a legal from-state
    for the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/checklist_skip_received_rejected
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Executed promissory note")

    resp = api_client.transition_checklist_item(item["id"], {"to": "APPROVED"}, o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _ = validate_paginated(api_client.list_application_checklist_items(
        ctx["application"]["id"], o["adm"]["headers"]))
    assert rows[0]["status"] == "PENDING"


def test_critical_item_not_waivable():
    """PRD section 3.7: driving an item to `WAIVED` "may never be applied to a
    `CRITICAL` item (`ERR_CONDITION_NOT_WAIVABLE`, HTTP 422)."

    Design: Corner/validations/critical_item_not_waivable
    """
    ctx = _documentation_deal()
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Flood zone determination",
                              severity="CRITICAL")

    resp = api_client.transition_checklist_item(
        item["id"], {"to": "WAIVED",
                     "waiver_rationale": "Borrower provided private determination"},
        o["po"]["headers"])
    validate_error(resp, ApiErrorId.ERR_CONDITION_NOT_WAIVABLE)

    rows, _ = validate_paginated(api_client.list_application_checklist_items(
        ctx["application"]["id"], o["po"]["headers"]))
    assert rows[0]["status"] == "PENDING"


def test_checklist_waiver_rationale_min_length():
    """PRD section 3.7: driving an item to `WAIVED` "requires a `waiver_rationale`
    of at least twenty characters" and "Waiving an item whose `is_required` flag is
    set also auto-creates a `REQUIRED_DOC_WAIVER` policy exception of `LOW`
    severity, unless one is already `OPEN` for the same item."

    Design: Corner/validations/checklist_waiver_rationale_min_length
    """
    ctx = _documentation_deal()
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Insurance binder copy")

    short = api_client.transition_checklist_item(
        item["id"], {"to": "WAIVED", "waiver_rationale": "too short"}, o["po"]["headers"])
    validate_error(short, ApiErrorId.ERR_VALIDATION)

    waived = validate_success(api_client.transition_checklist_item(
        item["id"], {"to": "WAIVED",
                     "waiver_rationale": "Duplicate coverage verified on master policy"},
        o["po"]["headers"]), 200)
    assert waived["status"] == "WAIVED"
    assert waived["waived_by_officer_id"] == o["po"]["id"]

    excs = list_exceptions(o, ctx["application"]["id"], rule_code="REQUIRED_DOC_WAIVER")
    assert len(excs) == 1
    assert excs[0]["severity"] == "LOW"
    assert excs[0]["status"] == "OPEN"


def test_checklist_waive_denied_for_credit_administrator():
    """PRD section 3.7: "driving an item from `PENDING` or `RECEIVED` to `WAIVED` is
    reserved for a `CreditPolicyOfficer` — any other role is refused with
    `ERR_ONLY_POLICY_OFFICER_MAY_WAIVE` (HTTP 403)".

    Design: Corner/rbac/checklist_waive_denied_for_credit_administrator
    """
    ctx = _documentation_deal()
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Insurance binder copy")

    resp = api_client.transition_checklist_item(
        item["id"], {"to": "WAIVED",
                     "waiver_rationale": "Admin attempting waiver without authority"},
        o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_ONLY_POLICY_OFFICER_MAY_WAIVE)

    rows, _ = validate_paginated(api_client.list_application_checklist_items(
        ctx["application"]["id"], o["adm"]["headers"]))
    assert rows[0]["status"] == "PENDING"


def test_submit_for_closing_document_gate():
    """PRD section 3.7: "every checklist item in the `DOCUMENT` category whose
    `is_required` is set must stand `APPROVED` or `WAIVED` (otherwise
    `ERR_CHECKLIST_INCOMPLETE`)".

    Design: Corner/validations/submit_for_closing_document_gate
    """
    ctx = _documentation_deal()
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Executed promissory note")
    assert item["is_required"] is True
    add_covenant(o, ctx["application"]["id"])

    resp = api_client.submit_for_closing(ctx["application"]["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "DOCUMENTATION"


def test_submit_for_closing_requires_covenant():
    """PRD section 3.7: "at least one covenant must exist for the application
    (otherwise `ERR_NO_COVENANTS_CONFIGURED`)".

    Design: Corner/validations/submit_for_closing_requires_covenant
    """
    ctx = _documentation_deal()
    o = ctx["o"]
    item = add_checklist_item(o, ctx["application"]["id"], label="Executed promissory note")
    approve_item(o, item["id"])

    resp = api_client.submit_for_closing(ctx["application"]["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_NO_COVENANTS_CONFIGURED)

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "DOCUMENTATION"


def test_covenant_review_before_funded_rejected():
    """PRD section 3.8: "reviewing requires the application to be `FUNDED`
    (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/validations/covenant_review_before_funded_rejected
    """
    ctx = _documentation_deal()
    o = ctx["o"]
    cov = add_covenant(o, ctx["application"]["id"])
    assert cov["status"] == "MONITORING"

    resp = api_client.review_covenant(
        cov["id"], {"measured_value": 1.3, "period_end_date": "2026-09-30"}, o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _ = validate_paginated(api_client.list_application_covenants(
        ctx["application"]["id"], o["an"]["headers"]))
    assert rows[0]["status"] == "MONITORING"
    assert rows[0].get("last_reviewed_period") is None, "no review was recorded"


def test_child_create_stage_gates_enforced():
    """PRD section 3.7: "An attempt to add an item while the application is outside
    `COMMITMENT`, `DOCUMENTATION`, or `CLOSING` is rejected with
    `ERR_INVALID_STATE`." and "A `CreditAdministrator` configures covenants while
    the application is in `DOCUMENTATION`, `CLOSING`, or `FUNDED`" and
    "A `CreditAdministrator` requests a tranche against an application in `CLOSING`
    or `FUNDED`".

    Design: Corner/validations/child_create_stage_gates_enforced
    """
    # Probe 1: checklist item while the application is still INTAKE.
    ctx = deal_intake(officer_keys=("rm", "an", "po", "apm", "ch", "m1", "m2", "adm"),
                      borrower_kw={"legal_name": "Meridian Industrial Parks",
                                   "naics_code": "531120", "relationship_since": "2010-01-01"},
                      app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
                      statement_shape="MERIDIAN")
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    early_item = api_client.create_checklist_item(
        {"loan_application_id": app_id, "category": "DOCUMENT", "label": "Early probe at INTAKE"},
        o["adm"]["headers"])
    validate_error(early_item, ApiErrorId.ERR_INVALID_STATE)

    # Drive to COMMITTEE_REVIEW, approve, issue+accept a sheet (COMMITMENT).
    submit_application(o, app_id)
    spread_and_finalize(o, ctx["statement"]["id"])
    finalize_spreads(o, app_id)
    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, app_id, appraiser["id"], 400_000_000, 380_000_000)
    submit_to_committee(o, app_id)
    sess = create_session(o, level="STANDARD")
    set_clock("2026-08-10T14:30:00Z")
    dec = open_decision(o, app_id, sess["id"])
    cast_vote(o, dec["id"], "m1", "APPROVE")
    cast_vote(o, dec["id"], "m2", "APPROVE")
    sheet = issue_term_sheet(o, app_id, 200_000_000)
    respond_sheet(o, sheet["id"], "ACCEPTED")

    # Probe 2: covenant while COMMITMENT (needs DOCUMENTATION+).
    early_cov = api_client.create_covenant(
        {"loan_application_id": app_id, "covenant_type": "DSCR_MIN", "threshold_value": 1.25,
         "frequency": "QUARTERLY"}, o["adm"]["headers"])
    validate_error(early_cov, ApiErrorId.ERR_INVALID_STATE)

    # Advance to DOCUMENTATION via letter issue + accept.
    letter = get_letter(o, app_id)
    issue_letter(o, letter["id"])
    accept_letter(o, letter["id"])

    # Probe 3: funding authorization while DOCUMENTATION (needs CLOSING|FUNDED).
    early_fa = api_client.create_funding_authorization(
        {"loan_application_id": app_id, "amount_cents": 50_000_000,
         "disbursement_date": "2026-08-15"}, o["adm"]["headers"])
    validate_error(early_fa, ApiErrorId.ERR_INVALID_STATE)

    items, _ = validate_paginated(api_client.list_application_checklist_items(app_id, o["adm"]["headers"]))
    covs, _ = validate_paginated(api_client.list_application_covenants(app_id, o["adm"]["headers"]))
    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(app_id, o["adm"]["headers"]))
    assert items == [] and covs == [] and fas == [], "no rejected child row persisted"

    app = get_application(o, app_id)
    assert app["status"] == "DOCUMENTATION"


def test_amend_blocked_after_committee_stage():
    """PRD section 3.2: "While the application remains in `INTAKE`, `SPREADING`, or
    `EXCEPTION_REVIEW`, the `RelationshipManager` may still amend the request's
    commercial terms — `requested_amount_cents`, `term_months`, or `purpose` —
    through an update; outside that window the amendment is rejected with
    `ERR_AMEND_NOT_PERMITTED`." and "Attaching a statement while the parent
    application is outside the mutable window is rejected with
    `ERR_AMEND_NOT_PERMITTED`."

    Design: Corner/validations/amend_blocked_after_committee_stage
    """
    ctx = deal_committee_review()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    r1 = api_client.update_loan_application(
        app_id, {"requested_amount_cents": 250_000_000}, o["rm"]["headers"])
    validate_error(r1, ApiErrorId.ERR_AMEND_NOT_PERMITTED)

    r2 = api_client.create_financial_statement(
        statement_payload(app_id, shape="MERIDIAN", period_end_date="2024-12-31",
                          revenue_cents=180_000_000, ebitda_cents=90_000_000),
        o["an"]["headers"])
    validate_error(r2, ApiErrorId.ERR_AMEND_NOT_PERMITTED)

    app = get_application(o, app_id)
    assert app["requested_amount_cents"] == 200_000_000
    stmts, meta = validate_paginated(api_client.list_financial_statements(
        o["an"]["headers"], params={"loan_application_id": app_id}))
    assert meta["total_count"] == 1, "no statement persisted"
