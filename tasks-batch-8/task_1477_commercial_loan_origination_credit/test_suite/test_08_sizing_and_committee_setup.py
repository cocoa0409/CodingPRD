"""Deal sizing (pinned evaluation order), committee level tiers, decision opening
constraints, and the LARGE quorum chair gate (PRD section 3.5).
"""
from test_helpers import (
    ApiErrorId, api_client, approve_decision, attach_statement, cast_vote,
    create_appraiser, create_borrower, create_session, deal_appraisal_review,
    deal_committee_review, deal_decision_open, deal_underwritten, finalize_spreads,
    get_application, list_exceptions, loan_application_payload, open_decision,
    order_and_accept_appraisal, set_clock, setup_officers, spread_and_finalize,
    submit_application, submit_to_committee, validate_error, validate_paginated,
    validate_success,
)


def _thin_deal_at_committee_review():
    """THIN 50,000,000 deal with both DSCR exceptions waived, one ACCEPTED appraisal
    (40,000,000 / 36,000,000 REAL_ESTATE), submitted to committee."""
    return deal_committee_review(
        borrower_kw={"legal_name": "Thin Margin Foods", "naics_code": "311410",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 50_000_000, "term_months": 60},
        statement_shape="THIN",
        appraised_value_cents=40_000_000, orderly_liquidation_value_cents=36_000_000)


def test_dscr_cap_binds_sizing():
    """PRD section 3.5: "Sizing follows a pinned evaluation order with no iteration
    back ... Step one: divide the standard cash flow (the numerator behind
    `dscr_standard`) by 1.25, floor the result to whole cents, and subtract the
    statement's `existing_annual_debt_service_cents` ... The application's
    `proposed_amount_cents` is the minimum of the requested amount, the DSCR cap,
    the LTV cap, and the headroom".

    Design: Difficulty/combinatorial_formula/sizing_circular_dependency_pinned_order
    """
    ctx = _thin_deal_at_committee_review()
    sized = ctx["sizing"]
    # max_annual = floor(8,000,000/1.25) - 0 = 6,400,000; pmt_max = 533,333.33;
    # dscr cap = floor(533,333.33 x 50.501992...) == 26,934,396 (binds over the
    # 50,000,000 request and the 32,000,000 LTV cap).
    assert sized["proposed_amount_cents"] == 26_934_396
    assert sized["status"] == "COMMITTEE_REVIEW"


def test_dscr_not_recomputed_on_sized_amount():
    """PRD section 3.5: "it deliberately does not recompute the DSCR on the sized
    amount — the coverage ratio was computed on the requested amount at spread
    finalization, and the coverage constraint is instead inverted algebraically
    into a principal cap." and "Submission also re-tests policy, this time against
    the deal as asked — the requested amount."

    Design: Difficulty/combinatorial_formula/sizing_circular_dependency_pinned_order
    """
    ctx = _thin_deal_at_committee_review()
    o = ctx["o"]
    sized = ctx["sizing"]
    assert sized["dscr_standard"] == 0.6734, (
        "DSCR computed on the REQUESTED amount at finalize; not recomputed on 26,934,396")

    open_exc = list_exceptions(o, sized["id"], status="OPEN")
    open_high = {e["rule_code"] for e in open_exc if e["severity"] == "HIGH"}
    assert "LTV_MAXIMUM" in open_high, "50,000,000 / 40,000,000 == 1.2500 > 0.8000"
    assert "COLLATERAL_COVERAGE_MIN" in open_high, "eligible 30,000,000 < requested 50,000,000"

    # FULL basis: dscr 0.6734 -> 20, leverage 0.5000 -> 100, coverage 0.6000 -> 25,
    # tenure 16 years -> 100; score 0.4*20+0.3*100+0.2*25+0.1*100 == 53.00 -> band 5.
    assert sized["rating_basis"] == "FULL"
    assert sized["risk_rating"] == 5


def test_no_sizeable_amount_rejected():
    """PRD section 3.5: "this is the maximum annual debt service the proposed
    facility may add, and if it is not positive the submission is rejected with
    `ERR_NO_SIZEABLE_AMOUNT`."

    Design: Corner/validations/no_sizeable_amount_rejected
    """
    # NOSIZE: cf_standard 1,000,000; floor(1,000,000/1.25) - 10,000,000 == -9,200,000 <= 0.
    ctx = deal_appraisal_review(
        borrower_kw={"legal_name": "Thin Margin Foods", "naics_code": "311410",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 30_000_000, "term_months": 60},
        statement_shape="NOSIZE")
    o = ctx["o"]
    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, ctx["application"]["id"], appraiser["id"],
                               40_000_000, 36_000_000)

    resp = api_client.submit_to_committee(ctx["application"]["id"], o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_NO_SIZEABLE_AMOUNT)

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "APPRAISAL_REVIEW"


def _tier_app(o, legal_name, requested):
    """Clean TIER-shaped deal driven to COMMITTEE_REVIEW at the given request size."""
    bor = create_borrower(o, legal_name=legal_name, naics_code="531120",
                          relationship_since="2010-01-01")
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=requested, term_months=60),
        o["rm"]["headers"]), 201)
    stmt = attach_statement(o, app["id"], shape="TIER")
    submit_application(o, app["id"])
    spread_and_finalize(o, stmt["id"])
    underwritten = finalize_spreads(o, app["id"])
    assert underwritten["status"] == "APPRAISAL_REVIEW"
    return app


def test_proposed_exactly_at_small_cap_stays_small():
    """PRD section 3.5: "at most $1,000,000.00 is `SMALL` (a proposed amount of
    exactly $1,000,000.00 stays `SMALL`)" and "A `SMALL` decision is a committee of
    2 requiring 2 approvals and falling to a single decline vote".

    Design: Difficulty/boundary_precision_check/committee_tier_amount_inclusive_boundary
    """
    o = setup_officers(["rm", "an", "apm", "ch", "m1"])
    app = _tier_app(o, "Tier Edge Exact LLC", 100_000_000)
    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, app["id"], appraiser["id"], 400_000_000, 380_000_000)
    sized = submit_to_committee(o, app["id"])
    assert sized["proposed_amount_cents"] == 100_000_000

    sess = create_session(o, level="SMALL", starts_at="2026-08-10T14:00:00Z",
                          ends_at="2026-08-10T15:00:00Z")
    set_clock("2026-08-10T14:30:00Z")
    dec = open_decision(o, app["id"], sess["id"])
    assert dec["level_required"] == "SMALL", "100,000,000 exactly is inside the SMALL tier"
    assert dec["votes_required"] == 2

    closed = cast_vote(o, dec["id"], "m1", "DECLINE")
    assert closed["status"] == "DECLINED", "SMALL decline threshold is a single vote"
    app_after = get_application(o, app["id"])
    assert app_after["status"] == "DECLINED"


def test_one_cent_over_cap_goes_standard():
    """PRD section 3.5: "at most $10,000,000.00 is `STANDARD` (exactly $10,000,000.00
    stays `STANDARD`), and anything larger is `LARGE`" — 100,000,001 cents exceeds
    the $1,000,000.00 SMALL cap — and "a `STANDARD` decision is a committee of 3
    requiring 2 approvals and falling to 2 decline votes".

    Design: Difficulty/boundary_precision_check/committee_tier_amount_inclusive_boundary
    """
    o = setup_officers(["rm", "an", "apm", "ch", "m1", "m2"])
    app = _tier_app(o, "Tier Edge Over LLC", 100_000_001)
    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, app["id"], appraiser["id"], 400_000_000, 380_000_000)
    sized = submit_to_committee(o, app["id"])
    assert sized["proposed_amount_cents"] == 100_000_001, (
        "the one-cent difference crosses the inclusive SMALL cap")

    sess = create_session(o, level="STANDARD", starts_at="2026-08-10T15:00:00Z",
                          ends_at="2026-08-10T16:00:00Z")
    set_clock("2026-08-10T15:30:00Z")
    dec = open_decision(o, app["id"], sess["id"])
    assert dec["level_required"] == "STANDARD"
    assert dec["votes_required"] == 2

    first = cast_vote(o, dec["id"], "m1", "DECLINE")
    assert first["status"] == "OPEN", "STANDARD decline threshold is 2 votes"
    second = cast_vote(o, dec["id"], "m2", "DECLINE")
    assert second["status"] == "DECLINED"
    app_after = get_application(o, app["id"])
    assert app_after["status"] == "DECLINED"


def test_session_level_mismatch_rejected():
    """PRD section 3.5: "the session's `level` must equal the decision's computed
    `level_required` (otherwise `ERR_SESSION_LEVEL_MISMATCH`, HTTP 422)."

    Design: Corner/validations/session_level_mismatch_rejected
    """
    ctx = deal_committee_review()
    o = ctx["o"]
    assert ctx["application"]["proposed_amount_cents"] == 200_000_000  # STANDARD
    sess = create_session(o, level="SMALL")

    resp = api_client.create_committee_decision(
        {"loan_application_id": ctx["application"]["id"], "committee_session_id": sess["id"],
         "expected_loan_application_version": ctx["application"]["version"]}, o["ch"]["headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_LEVEL_MISMATCH)

    rows, meta = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows == [], "no decision persisted"


def test_second_decision_while_open_rejected():
    """PRD section 3.5: "at most one decision may be `OPEN` for an application at
    any time (otherwise `ERR_DECISION_ALREADY_OPEN`)".

    Design: Corner/validations/second_decision_while_open_rejected
    """
    ctx = deal_decision_open()
    o = ctx["o"]
    assert ctx["decision"]["status"] == "OPEN"
    current = get_application(o, ctx["application"]["id"])

    resp = api_client.create_committee_decision(
        {"loan_application_id": ctx["application"]["id"],
         "committee_session_id": ctx["session"]["id"],
         "expected_loan_application_version": current["version"]}, o["ch"]["headers"])
    validate_error(resp, ApiErrorId.ERR_DECISION_ALREADY_OPEN)

    rows, meta = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert [d["id"] for d in rows] == [ctx["decision"]["id"]]
    assert rows[0]["status"] == "OPEN"


def test_large_committee_quorum_requires_chair_approval():
    """PRD section 3.5: "a `LARGE` decision is a committee of 5 requiring 4
    approvals, falling to 2 decline votes, and additionally requiring the chair's
    approval" and "the decision closes `APPROVED` when `votes_for` reaches
    `votes_required` and, for a `LARGE` decision only, `chair_approved` has become
    true through a chair's `APPROVE`".

    Design: Corner/calculations/large_committee_quorum_requires_chair_approval
    """
    ctx = deal_decision_open(
        borrower_kw={"legal_name": "National Logistics REIT", "naics_code": "531120",
                     "relationship_since": "2008-01-01"},
        app_kw={"requested_amount_cents": 1_200_000_000, "term_months": 60},
        statement_shape="LARGE",
        appraised_value_cents=2_000_000_000, orderly_liquidation_value_cents=1_900_000_000,
        level="LARGE")
    o = ctx["o"]
    dec = ctx["decision"]
    assert dec["level_required"] == "LARGE", "1,200,000,000 > 1,000,000,000 tier cap"
    assert dec["votes_required"] == 4

    for member in ("m1", "m2", "m3"):
        cast_vote(o, dec["id"], member, "APPROVE")
    mid = cast_vote(o, dec["id"], "m4", "APPROVE")
    assert mid["votes_for"] == 4
    assert mid["chair_approved"] is False
    assert mid["status"] == "OPEN", "numeric quorum met but the LARGE chair gate blocks closure"

    final = cast_vote(o, dec["id"], "ch", "APPROVE")
    assert final["votes_for"] == 5
    assert final["chair_approved"] is True
    assert final["status"] == "APPROVED"

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "TERM_SHEET_NEGOTIATION"
