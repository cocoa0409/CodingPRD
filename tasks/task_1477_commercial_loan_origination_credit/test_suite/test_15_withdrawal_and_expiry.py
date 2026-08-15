"""Withdrawal compensation cascades, the clock-driven commitment expiry cascade,
and the committee-decline appraisal cascade (PRD sections 2.6, 3.4, 3.5, 3.6, 3.8).
"""
from test_helpers import (
    ApiErrorId, api_client, add_checklist_item, attach_statement, authorize_funding,
    cast_vote, create_appraiser, create_borrower, create_session, deal_closing,
    deal_intake, deal_letter_issued, finalize_spreads, get_application, get_borrower,
    loan_application_payload, open_decision, order_and_accept_appraisal,
    order_appraisal, propose_participation, request_funding, set_clock,
    setup_officers, spread_and_finalize, submit_application, submit_to_committee,
    validate_error, validate_paginated, validate_success,
)


def test_withdraw_is_terminal_lockdown():
    """PRD section 3.8: "the relationship manager may withdraw the application at any
    point before it reaches a terminal state; withdrawing from a terminal state is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_is_terminal_lockdown
    """
    ctx = deal_intake()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    withdrawn = validate_success(api_client.withdraw_application(app_id, o["rm"]["headers"]), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    again = api_client.withdraw_application(app_id, o["rm"]["headers"])
    validate_error(again, ApiErrorId.ERR_INVALID_STATE)

    submit = api_client.submit_application(app_id, o["rm"]["headers"])
    validate_error(submit, ApiErrorId.ERR_INVALID_STATE)


def test_withdraw_from_closing_compensation_cascade():
    """PRD section 3.8: "If a commitment letter stands `ACCEPTED`, it moves to
    `TERMINATED` and the borrower's `committed_exposure_cents` is reduced by the
    letter's `committed_amount_cents` — pairing exactly with the increment
    acceptance applied. ... Participations in `PROPOSED` or `COMMITTED` move to
    `RELEASED` ... If it was in `CLOSING`, funding authorizations in `REQUESTED` or
    `AUTHORIZED` move to `CANCELLED`."

    Design: Corner/state_machines/withdraw_from_closing_compensation_cascade
    """
    ctx = deal_closing(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        with_closing_condition=False)
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    p1 = propose_participation(o, app_id, participant_bank_name="Bank North",
                               allocated_amount_cents=50_000_000)
    fa = request_funding(o, app_id, amount_cents=120_000_000)
    authorize_funding(o, fa["id"])

    bor0 = get_borrower(o, ctx["borrower"]["id"])
    assert bor0["committed_exposure_cents"] == 200_000_000

    withdrawn = validate_success(api_client.withdraw_application(app_id, o["rm"]["headers"]), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    letter = validate_success(api_client.get_commitment_letter(ctx["letter"]["id"], o["adm"]["headers"]), 200)
    assert letter["status"] == "TERMINATED"

    bor1 = get_borrower(o, ctx["borrower"]["id"])
    assert bor1["committed_exposure_cents"] == 0
    assert bor1["funded_exposure_cents"] == 0
    assert bor1["total_exposure_cents"] == 0

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(app_id, o["adm"]["headers"]))
    assert fas[0]["id"] == fa["id"] and fas[0]["status"] == "CANCELLED"

    parts, _ = validate_paginated(api_client.list_application_participations(app_id, o["rm"]["headers"]))
    assert parts[0]["id"] == p1["id"] and parts[0]["status"] == "RELEASED"
    app = get_application(o, app_id)
    assert app["bank_hold_amount_cents"] == 200_000_000, "allocation headroom restored"


def _commitment_80m_with_stake():
    """80,000,000 SMALL deal in COMMITMENT: letter ISSUED (expiry 2026-09-01),
    one PROPOSED participation of 50,000,000, one PENDING DOCUMENT item."""
    ctx = deal_letter_issued(
        borrower_kw={"legal_name": "Cold Storage Partners", "naics_code": "493120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 80_000_000, "term_months": 60},
        statement_shape="COLD",
        appraised_value_cents=160_000_000, orderly_liquidation_value_cents=150_000_000,
        level="SMALL", session_window=("2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z"))
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    ctx["participation"] = propose_participation(
        o, app_id, participant_bank_name="Bank North", allocated_amount_cents=50_000_000)
    ctx["doc_item"] = add_checklist_item(o, app_id, label="Draft promissory note")
    return ctx


def test_clock_sweep_expires_letter_and_application():
    """PRD section 2.6: "Any commitment letter still `ISSUED` whose `expiry_date`
    falls on or before the clock's current date transitions to `EXPIRED` and
    triggers the three-hop cascade described in section 3.6 (application, checklist
    items, participations)."
    PRD section 3.6: "the expiry cascades three hops — the application moves
    `COMMITMENT` → `EXPIRED`".

    Design: Difficulty/transitive_cascade/commitment_expiry_three_hop_cascade
    """
    ctx = _commitment_80m_with_stake()
    o = ctx["o"]
    assert ctx["letter"]["status"] == "ISSUED"
    assert ctx["letter"]["expiry_date"] == "2026-09-01"

    set_clock("2026-09-02T00:00:00Z")

    letter = validate_success(api_client.get_commitment_letter(ctx["letter"]["id"], o["adm"]["headers"]), 200)
    assert letter["status"] == "EXPIRED", "hop 1: expiry_date <= clock date while ISSUED"

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "EXPIRED", "hop 2: letter expiry drives the application"


def test_expiry_cascade_releases_items_and_participations():
    """PRD section 3.6: "every checklist item of the application in `PENDING`,
    `RECEIVED`, or `REJECTED` status moves to `CANCELLED`; and every participation
    in `PROPOSED` or `COMMITTED` status moves to `RELEASED`, returning its allocated
    headroom to the bank's hold."

    Design: Difficulty/transitive_cascade/commitment_expiry_three_hop_cascade
    """
    ctx = _commitment_80m_with_stake()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    app0 = get_application(o, app_id)
    assert app0["bank_hold_amount_cents"] == 30_000_000

    set_clock("2026-09-02T00:00:00Z")

    items, _ = validate_paginated(api_client.list_application_checklist_items(app_id, o["adm"]["headers"]))
    assert items[0]["id"] == ctx["doc_item"]["id"]
    assert items[0]["status"] == "CANCELLED", "hop 3a: application expiry cancels items"

    parts, _ = validate_paginated(api_client.list_application_participations(app_id, o["rm"]["headers"]))
    assert parts[0]["id"] == ctx["participation"]["id"]
    assert parts[0]["status"] == "RELEASED", "hop 3b: application expiry releases participations"

    app = get_application(o, app_id)
    assert app["bank_hold_amount_cents"] == 80_000_000, (
        "allocation headroom fully restored by the cascade")

    bor = get_borrower(o, ctx["borrower"]["id"])
    assert bor["committed_exposure_cents"] == 0, (
        "the letter was never ACCEPTED, so no committed exposure existed to unwind")


def _decline_deal_with_engaged_appraisal():
    """Harbor 60,000,000 SMALL deal at COMMITTEE_REVIEW with decision OPEN;
    appraisal A1 ACCEPTED; second appraisal A2 ENGAGED mid-review on appraiser2."""
    o = setup_officers(["rm", "an", "apm", "ch", "m1", "m2"])
    bor = create_borrower(o, legal_name="Harbor Cold Chain", naics_code="493120",
                          relationship_since="2010-01-01")
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=60_000_000, term_months=60),
        o["rm"]["headers"]), 201)
    stmt = attach_statement(o, app["id"], shape="HARBOR")
    submit_application(o, app["id"])
    spread_and_finalize(o, stmt["id"])
    finalize_spreads(o, app["id"])
    appraiser1 = create_appraiser(o, name="AppraisalCo", license_number="LIC-100")
    appraiser2 = create_appraiser(o, name="ValueRight", license_number="LIC-200")
    order_and_accept_appraisal(o, app["id"], appraiser1["id"], 120_000_000, 110_000_000)
    submit_to_committee(o, app["id"])
    sess = create_session(o, level="SMALL", starts_at="2026-08-10T14:00:00Z",
                          ends_at="2026-08-10T15:00:00Z")
    set_clock("2026-08-10T14:30:00Z")
    dec = open_decision(o, app["id"], sess["id"])
    # Committee orders an additional collateral opinion mid-review.
    a2 = order_appraisal(o, app["id"], appraiser2["id"],
                         engagement_start_date="2026-08-11", engagement_end_date="2026-08-14")
    return {"o": o, "borrower": bor, "application": app, "appraiser2": appraiser2,
            "a2": a2, "decision": dec, "session": sess}


def test_single_decline_closes_small_decision_and_declines_application():
    """PRD section 3.5: "A `SMALL` decision is a committee of 2 requiring 2 approvals
    and falling to a single decline vote" and "a `DECLINED` decision moves it to
    `DECLINED` and cancels every appraisal still `ENGAGED` or `REPORT_RECEIVED`,
    freeing those engagement windows".

    Design: Difficulty/transitive_cascade/committee_decline_appraisal_cancellation_cascade
    """
    ctx = _decline_deal_with_engaged_appraisal()
    o = ctx["o"]
    closed = cast_vote(o, ctx["decision"]["id"], "m1", "DECLINE")
    assert closed["status"] == "DECLINED", "SMALL decline threshold: 2 - 2 + 1 == 1"

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "DECLINED", "hop 2: the declined decision moves the application"

    rows, _ = validate_paginated(api_client.list_application_appraisals(app["id"], o["apm"]["headers"]))
    by_id = {a["id"]: a for a in rows}
    assert by_id[ctx["a2"]["id"]]["status"] == "CANCELLED", (
        "hop 3: the ENGAGED mid-review appraisal is cancelled")
    accepted = [a for a in rows if a["status"] == "ACCEPTED"]
    assert len(accepted) == 1, "the cascade touches only ENGAGED|REPORT_RECEIVED appraisals"


def test_decline_frees_appraiser_window():
    """PRD section 3.4: "Appraisals still `ENGAGED` or `REPORT_RECEIVED` when the
    application is declined, withdrawn, or expired are moved to `CANCELLED` by the
    system, likewise freeing their windows."

    Design: Difficulty/transitive_cascade/committee_decline_appraisal_cancellation_cascade
    """
    ctx = _decline_deal_with_engaged_appraisal()
    o = ctx["o"]
    cast_vote(o, ctx["decision"]["id"], "m1", "DECLINE")

    # A different application in APPRAISAL_REVIEW can now use the freed window.
    other = deal_appraisal_review_for(o)
    freed = order_appraisal(o, other["id"], ctx["appraiser2"]["id"],
                            engagement_start_date="2026-08-11",
                            engagement_end_date="2026-08-14")
    assert freed["status"] == "ENGAGED", "the cancelled engagement's window was freed"


def deal_appraisal_review_for(o):
    """Second clean 20,000,000 deal in APPRAISAL_REVIEW reusing the bench o."""
    bor2 = create_borrower(o, legal_name="Second Client LLC", naics_code="332710",
                           relationship_since="2015-01-01")
    app2 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor2["id"], requested_amount_cents=20_000_000, term_months=60),
        o["rm"]["headers"]), 201)
    stmt2 = attach_statement(o, app2["id"], shape="WINDOW")
    submit_application(o, app2["id"])
    spread_and_finalize(o, stmt2["id"])
    finalize_spreads(o, app2["id"])
    return app2


# keep the helper importable without polluting test discovery
deal_appraisal_review_for.__test__ = False
