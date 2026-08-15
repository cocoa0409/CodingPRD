"""Statement spreading lifecycle: submit gate, spread/finalize officer stamps,
restatement supersession, and the exception-review recompute (PRD sections 3.2, 3.3).
"""
from test_helpers import (
    ApiErrorId, api_client, attach_statement, clear_exceptions, create_borrower,
    deal_intake, deal_spreading, deal_underwritten, finalize_spreads, finalize_statement,
    get_application, get_success_data, list_exceptions, loan_application_payload,
    setup_officers, spread_statement, statement_payload, submit_application,
    validate_error, validate_paginated, validate_success, waive_exception,
)


def test_submit_moves_application_to_spreading():
    """PRD section 3.2: "submitting the application moves it `INTAKE` → `SPREADING`;
    at least one financial statement must exist for the application at that moment,
    or the submission is refused with `ERR_STATEMENTS_NOT_FINAL`."

    Design: Corner/state_machines/submit_moves_application_to_spreading
    """
    ctx = deal_intake()
    o = ctx["o"]
    submitted = validate_success(
        api_client.submit_application(ctx["application"]["id"], o["rm"]["headers"]), 200)
    assert submitted["status"] == "SPREADING"

    stmt = get_success_data(api_client.get_financial_statement(ctx["statement"]["id"], o["an"]["headers"]))
    assert stmt["status"] == "SUBMITTED", "submit does not touch statements"


def test_submit_twice_rejected_invalid_state():
    """PRD section 2.8: "Transition legality. The target entity is in a legal
    from-state for the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD section 3.2: "submitting the application moves it `INTAKE` → `SPREADING`".

    Design: Corner/state_machines/submit_twice_rejected_invalid_state
    """
    ctx = deal_spreading()
    o = ctx["o"]
    resp = api_client.submit_application(ctx["application"]["id"], o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_application(o, ctx["application"]["id"])
    assert after["status"] == "SPREADING"


def test_finalize_spreads_from_intake_rejected():
    """PRD section 3.2: "The application must be in `SPREADING`, and every one of its
    financial statements must be in `FINAL` or `SUPERSEDED` status with at least one
    `FINAL`, otherwise `ERR_STATEMENTS_NOT_FINAL`. These guards are evaluated with
    state legality first, then the segregation-of-duties check, then statement
    completeness."

    Design: Corner/state_machines/finalize_spreads_from_intake_rejected
    """
    ctx = deal_intake()  # INTAKE, statement still SUBMITTED
    o = ctx["o"]
    resp = api_client.finalize_spreads(ctx["application"]["id"], o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_application(o, ctx["application"]["id"])
    assert after["status"] == "INTAKE"
    assert after["dscr_standard"] is None, "no computation ran"


def test_submit_without_statements_rejected():
    """PRD section 3.2: "at least one financial statement must exist for the
    application at that moment, or the submission is refused with
    `ERR_STATEMENTS_NOT_FINAL`."

    Design: Corner/validations/submit_without_statements_rejected
    """
    ctx = deal_intake(statement_shape=None)
    o = ctx["o"]
    resp = api_client.submit_application(ctx["application"]["id"], o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_STATEMENTS_NOT_FINAL)
    after = get_application(o, ctx["application"]["id"])
    assert after["status"] == "INTAKE"


def test_finalize_spreads_with_unfinalized_statement_rejected():
    """PRD section 3.2: "every one of its financial statements must be in `FINAL` or
    `SUPERSEDED` status with at least one `FINAL`, otherwise `ERR_STATEMENTS_NOT_FINAL`."

    Design: Corner/validations/finalize_spreads_with_unfinalized_statement_rejected
    """
    ctx = deal_spreading()  # statement still SUBMITTED
    o = ctx["o"]
    resp = api_client.finalize_spreads(ctx["application"]["id"], o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_STATEMENTS_NOT_FINAL)
    after = get_application(o, ctx["application"]["id"])
    assert after["status"] == "SPREADING"
    assert after["dscr_standard"] is None


def test_statement_spread_finalize_records_officers():
    """PRD section 3.2: "spreading moves `SUBMITTED` → `SPREAD` ... stamping
    `spread_by_officer_id` with the caller's identity), and finalizing moves
    `SPREAD` → `FINAL` ... stamping `finalized_by_officer_id`."
    PRD section 2.9: "A financial statement records `spread_by_officer_id` when it
    is spread and `finalized_by_officer_id` when it is finalized."

    Design: Corner/state_machines/statement_spread_finalize_records_officers
    """
    ctx = deal_spreading()
    o = ctx["o"]
    stmt_id = ctx["statement"]["id"]

    spread = validate_success(api_client.spread_statement(stmt_id, o["an"]["headers"]), 200)
    assert spread["status"] == "SPREAD"
    assert spread["spread_by_officer_id"] == o["an"]["id"]

    final = validate_success(api_client.finalize_statement(stmt_id, o["an"]["headers"]), 200)
    assert final["status"] == "FINAL"
    assert final["finalized_by_officer_id"] == o["an"]["id"]


def test_superseded_statement_is_terminal():
    """PRD section 3.2: "Finalizing a restating statement automatically supersedes
    its target: the referenced statement moves `FINAL` → `SUPERSEDED`, so that at
    most one `FINAL` statement ever exists per `period_end_date` per application."
    PRD section 2.8: "The target entity is in a legal from-state for the requested
    transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/superseded_statement_is_terminal
    """
    ctx = deal_spreading()
    o = ctx["o"]
    s1 = ctx["statement"]
    spread_statement(o, s1["id"])
    finalize_statement(o, s1["id"])

    s2 = attach_statement(o, ctx["application"]["id"], shape="BEACON_RESTATED",
                          restatement_of_id=s1["id"])
    spread_statement(o, s2["id"])
    s2_final = finalize_statement(o, s2["id"])
    assert s2_final["status"] == "FINAL"

    s1_after = get_success_data(api_client.get_financial_statement(s1["id"], o["an"]["headers"]))
    assert s1_after["status"] == "SUPERSEDED"

    resp = api_client.spread_statement(s1["id"], o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_restatement_supersedes_and_recomputes_dscr():
    """PRD section 3.3: "when the underwriting computation is re-run (by statement
    finalization or application amendment while the application is in
    `EXCEPTION_REVIEW`), each `OPEN` auto-created exception whose triggering
    condition no longer holds is moved to `RESOLVED_BY_CHANGE`, newly triggered
    conditions create fresh exceptions, and a `WAIVED` exception is never
    resurrected even if its condition fires again."
    PRD section 3.2: the DSCR input is "the application's `FINAL` statement with
    the latest `period_end_date`".

    Design: Corner/calculations/restatement_supersedes_and_recomputes_dscr
    """
    ctx = deal_underwritten()  # BEACON shape -> EXCEPTION_REVIEW (OPEN LOW stress)
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    assert ctx["underwriting"]["status"] == "EXCEPTION_REVIEW"
    assert ctx["underwriting"]["dscr_standard"] == 1.2982
    assert ctx["underwriting"]["dscr_stress"] == 0.7010

    s2 = attach_statement(o, app_id, shape="BEACON_RESTATED",
                          restatement_of_id=ctx["statement"]["id"])
    spread_statement(o, s2["id"])
    finalize_statement(o, s2["id"])

    s1_after = get_success_data(api_client.get_financial_statement(ctx["statement"]["id"], o["an"]["headers"]))
    assert s1_after["status"] == "SUPERSEDED"

    app_after = get_application(o, app_id)
    assert app_after["dscr_standard"] == 1.5579, "15,000,000 / 9,628,432 from S2 only"
    assert app_after["dscr_stress"] == 1.2463, "(15,000,000 - 3,000,000) / 9,628,432"

    stress = list_exceptions(o, app_id, rule_code="STRESS_DSCR_MINIMUM")
    assert len(stress) == 1
    assert stress[0]["status"] == "RESOLVED_BY_CHANGE", (
        "the recompute cured the stress exception by change")

    cleared = clear_exceptions(o, app_id)
    assert cleared["status"] == "APPRAISAL_REVIEW"


def test_restatement_target_validation():
    """PRD section 3.2: "a restatement is valid only when the referenced statement
    exists, belongs to the same application, is in `FINAL` status, and covers the
    identical `period_end_date` — and a statement may never restate itself — with
    any violation rejected as `ERR_RESTATEMENT_TARGET_INVALID` (HTTP 422)."

    Design: Corner/validations/restatement_target_validation
    """
    from test_helpers import NON_EXISTENT_UUID
    # app1 in EXCEPTION_REVIEW with S1 FINAL; S2b attached but never spread.
    ctx = deal_underwritten()
    o = ctx["o"]
    app1 = ctx["application"]["id"]
    s1 = ctx["statement"]
    s2b = attach_statement(o, app1, shape="BEACON", revenue_cents=21_000_000,
                           ebitda_cents=12_000_000, addbacks_cents=0,
                           distributions_cents=0, maintenance_capex_cents=0)

    # Second application with its own FINAL statement (different application).
    bor2 = create_borrower(o, legal_name="Other Client Co", naics_code="441110",
                           relationship_since="2019-01-01")
    app2 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor2["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"]), 201)
    s_other = attach_statement(o, app2["id"], shape="WINDOW")
    submit_application(o, app2["id"])
    spread_statement(o, s_other["id"])
    finalize_statement(o, s_other["id"])

    base = statement_payload(app1, shape="BEACON_RESTATED")

    # Nonexistent target.
    r1 = api_client.create_financial_statement(
        {**base, "restatement_of_id": NON_EXISTENT_UUID}, o["an"]["headers"])
    validate_error(r1, ApiErrorId.ERR_RESTATEMENT_TARGET_INVALID)

    # Target still SUBMITTED (not FINAL).
    r2 = api_client.create_financial_statement(
        {**base, "restatement_of_id": s2b["id"]}, o["an"]["headers"])
    validate_error(r2, ApiErrorId.ERR_RESTATEMENT_TARGET_INVALID)

    # Period mismatch with the FINAL target.
    r3 = api_client.create_financial_statement(
        {**base, "period_end_date": "2024-12-31", "revenue_cents": 19_000_000,
         "ebitda_cents": 10_000_000, "restatement_of_id": s1["id"]}, o["an"]["headers"])
    validate_error(r3, ApiErrorId.ERR_RESTATEMENT_TARGET_INVALID)

    # FINAL target belonging to a DIFFERENT application.
    r4 = api_client.create_financial_statement(
        {**base, "restatement_of_id": s_other["id"]}, o["an"]["headers"])
    validate_error(r4, ApiErrorId.ERR_RESTATEMENT_TARGET_INVALID)

    rows, meta = validate_paginated(api_client.list_financial_statements(
        o["an"]["headers"], params={"loan_application_id": app1}))
    assert meta["total_count"] == 2, "no rejected restatement persisted"
    by_id = {s["id"]: s for s in rows}
    assert by_id[s1["id"]]["status"] == "FINAL"
    assert by_id[s2b["id"]]["status"] == "SUBMITTED"


def test_financial_statement_list_filters():
    """PRD section 3.2: "The statement collection can be listed filtered by
    `loan_application_id`, `restatement_of_id`, `spread_by_officer_id`, or
    `finalized_by_officer_id`."

    Design: Corner/entities/financial_statement_list_filters
    """
    ctx = deal_underwritten()  # EXCEPTION_REVIEW with S1 FINAL
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    s1 = ctx["statement"]

    s2 = attach_statement(o, app_id, shape="BEACON_RESTATED", restatement_of_id=s1["id"])
    spread_statement(o, s2["id"])
    finalize_statement(o, s2["id"])

    by_app, _ = validate_paginated(api_client.list_financial_statements(
        o["an"]["headers"], params={"loan_application_id": app_id}))
    assert len(by_app) == 2
    by_id = {s["id"]: s for s in by_app}
    assert by_id[s1["id"]]["status"] == "SUPERSEDED"
    assert by_id[s2["id"]]["status"] == "FINAL"

    by_target, _ = validate_paginated(api_client.list_financial_statements(
        o["an"]["headers"], params={"restatement_of_id": s1["id"]}))
    assert [s["id"] for s in by_target] == [s2["id"]]

    empty, _ = validate_paginated(api_client.list_financial_statements(
        o["an"]["headers"], params={"restatement_of_id": s2["id"]}))
    assert empty == []
