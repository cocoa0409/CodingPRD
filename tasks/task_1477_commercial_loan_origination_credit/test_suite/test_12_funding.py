"""Funding pipeline: tranche request/authorize/release ordering, the exposure
compensating pair, the release gate order, and the cumulative cap
(PRD sections 3.1, 3.7).
"""
from test_helpers import (
    ApiErrorId, accept_letter, add_checklist_item, add_covenant, api_client,
    approve_item, authorize_funding, cast_vote, create_session, deal_closing,
    deal_committee_review, deal_funded, get_application, get_borrower, get_letter,
    issue_letter, issue_term_sheet, list_exceptions,
    make_credit_policy_officer_headers, open_decision, release_funding,
    request_funding, respond_sheet, set_clock, submit_for_closing, validate_error,
    validate_paginated, validate_success, waive_exception,
)


def _closing_200m():
    """Clean 200,000,000 deal in CLOSING with letter ACCEPTED, docs approved,
    covenant set, closing condition approved."""
    return deal_closing(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")


def test_accept_then_first_tranche_conserves_total():
    """PRD section 3.1: "releasing a funding tranche of a given amount
    simultaneously reduces the application's committed contribution by that amount
    and increases funded exposure by that amount, leaving `total_exposure_cents`
    unchanged; likewise, accepting a letter adds its committed amount".
    PRD section 3.7: "The first release carries the full transition set: the letter
    moves `ACCEPTED` → `FUNDED`, the application moves `CLOSING` → `FUNDED`".

    Design: Difficulty/compensating_invariant/exposure_conserved_across_accept_and_fund_tranches
    """
    ctx = _closing_200m()
    o = ctx["o"]
    bor_id = ctx["borrower"]["id"]

    bor0 = get_borrower(o, bor_id)
    assert bor0["committed_exposure_cents"] == 200_000_000
    assert bor0["funded_exposure_cents"] == 0
    assert bor0["total_exposure_cents"] == 200_000_000

    fa1 = request_funding(o, ctx["application"]["id"], amount_cents=120_000_000)
    authorize_funding(o, fa1["id"])
    released = release_funding(o, fa1["id"])
    assert released["status"] == "RELEASED"

    bor1 = get_borrower(o, bor_id)
    assert bor1["committed_exposure_cents"] == 80_000_000
    assert bor1["funded_exposure_cents"] == 120_000_000
    assert bor1["total_exposure_cents"] == 200_000_000, (
        "compensating pair: committed -120,000,000, funded +120,000,000")

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "FUNDED"
    assert app["funded_amount_cents"] == 120_000_000
    letter = get_letter(o, app["id"])
    assert letter["status"] == "FUNDED"


def test_second_tranche_completes_draw_conserving_total():
    """PRD section 3.1: "`total_exposure_cents` is exactly the sum of the two. The
    ledger is conserved across the accept-then-fund lifecycle" and PRD section 3.7:
    "the application's `funded_amount_cents` plus this tranche's `amount_cents` must
    not exceed the letter's `committed_amount_cents`" — a full draw to exactly the
    cap is permitted.

    Design: Difficulty/compensating_invariant/exposure_conserved_across_accept_and_fund_tranches
    """
    ctx = deal_funded(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        first_tranche_cents=120_000_000)
    o = ctx["o"]

    fa2 = request_funding(o, ctx["application"]["id"], amount_cents=80_000_000,
                          disbursement_date="2026-08-16")
    authorize_funding(o, fa2["id"])
    released2 = release_funding(o, fa2["id"])
    assert released2["status"] == "RELEASED"

    bor = get_borrower(o, ctx["borrower"]["id"])
    assert bor["committed_exposure_cents"] == 0
    assert bor["funded_exposure_cents"] == 200_000_000
    assert bor["total_exposure_cents"] == 200_000_000, "the invariant holds on every tranche"

    app = get_application(o, ctx["application"]["id"])
    assert app["funded_amount_cents"] == 200_000_000
    letter = get_letter(o, app["id"])
    assert app["funded_amount_cents"] == letter["committed_amount_cents"]


def _sized_down_closing_deal():
    """The release-ordering deal: requested 30,000,000; appraisal 30,000,000/27,000,000
    (LTV cap sizes proposed to 24,000,000 and raises OPEN HIGH LTV_MAXIMUM +
    COLLATERAL_COVERAGE_MIN at submit-to-committee; the HIGH-exception bump makes
    the committee STANDARD). Reaches CLOSING with one CLOSING_CONDITION item still
    PENDING and a 24,000,000 AUTHORIZED tranche."""
    ctx = deal_committee_review(
        borrower_kw={"legal_name": "Beacon Holdings LLC", "naics_code": "332710",
                     "relationship_since": "2018-01-01"},
        app_kw={"requested_amount_cents": 30_000_000, "term_months": 60},
        statement_shape="BEACON",
        appraised_value_cents=30_000_000, orderly_liquidation_value_cents=27_000_000,
        officer_keys=("rm", "an", "po", "apm", "ch", "m1", "m2", "m3", "m4", "adm"))
    o = ctx["o"]
    assert ctx["sizing"]["proposed_amount_cents"] == 24_000_000, (
        "LTV cap floor(30,000,000 x 0.80) bound the sizing")

    ctx["session"] = None
    sess = create_session(o, level="STANDARD")
    set_clock("2026-08-10T14:30:00Z")
    ctx["decision"] = open_decision(o, ctx["application"]["id"], sess["id"])
    cast_vote(o, ctx["decision"]["id"], "m1", "APPROVE")
    cast_vote(o, ctx["decision"]["id"], "m2", "APPROVE")

    sheet = issue_term_sheet(o, ctx["application"]["id"], 24_000_000)
    respond_sheet(o, sheet["id"], "ACCEPTED")
    letter = get_letter(o, ctx["application"]["id"])
    issue_letter(o, letter["id"])
    accept_letter(o, letter["id"])
    ctx["letter"] = letter

    doc = add_checklist_item(o, ctx["application"]["id"], label="Executed promissory note")
    approve_item(o, doc["id"])
    ctx["covenant"] = add_covenant(o, ctx["application"]["id"])
    ctx["cc_item"] = add_checklist_item(o, ctx["application"]["id"],
                                        category="CLOSING_CONDITION",
                                        label="Evidence of insurance")  # stays PENDING
    ctx["application"] = submit_for_closing(o, ctx["application"]["id"])
    assert ctx["application"]["status"] == "CLOSING"

    fa = request_funding(o, ctx["application"]["id"], amount_cents=24_000_000)
    authorize_funding(o, fa["id"])
    ctx["fa"] = fa
    return ctx


def test_open_high_exception_blocks_release_first():
    """PRD section 3.7: release moves `AUTHORIZED` → `RELEASED` "after evaluating its
    gates in this order: the authorization must be `AUTHORIZED` and the application
    in `CLOSING` or `FUNDED` (otherwise `ERR_INVALID_STATE`); no policy exception
    with `OPEN` status and `HIGH` severity may exist for the application (otherwise
    `ERR_UNRESOLVED_POLICY_EXCEPTION`, HTTP 403); every required `CLOSING_CONDITION`
    checklist item must be `APPROVED` or `WAIVED` (otherwise
    `ERR_CHECKLIST_INCOMPLETE`)".

    Design: Difficulty/priority_pair_validation_conflict/release_safety_error_beats_checklist_error
    """
    ctx = _sized_down_closing_deal()
    o = ctx["o"]

    open_high = [e for e in list_exceptions(o, ctx["application"]["id"], status="OPEN")
                 if e["severity"] == "HIGH"]
    assert {e["rule_code"] for e in open_high} == {"LTV_MAXIMUM", "COLLATERAL_COVERAGE_MIN"}

    resp = api_client.release_funding(ctx["fa"]["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_POLICY_EXCEPTION, 403)

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(
        ctx["application"]["id"], o["adm"]["headers"]))
    assert fas[0]["status"] == "AUTHORIZED", "rejected release leaves state untouched"


def test_checklist_error_surfaces_after_exceptions_waived():
    """PRD section 2.8: "the numeric order above governs their relative priority;
    the workflow narratives in Section 3 restate the evaluation sequence at the
    busiest gates — for example, funding release evaluates state legality, then open
    high-severity exceptions, then closing conditions, then the rate lock, then the
    letter's state, then the cumulative funding cap."

    Design: Difficulty/priority_pair_validation_conflict/release_safety_error_beats_checklist_error
    """
    ctx = _sized_down_closing_deal()
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    # First release: the safety gate fires.
    first = api_client.release_funding(ctx["fa"]["id"], o["adm"]["headers"])
    validate_error(first, ApiErrorId.ERR_UNRESOLVED_POLICY_EXCEPTION, 403)

    for code in ("LTV_MAXIMUM", "COLLATERAL_COVERAGE_MIN"):
        exc = list_exceptions(o, app_id, rule_code=code, status="OPEN")[0]
        waive_exception(o, exc["id"],
                        "Sized-down facility restores policy LTV compliance"
                        if code == "LTV_MAXIMUM" else
                        "Coverage shortfall accepted on sized-down commitment")

    second = api_client.release_funding(ctx["fa"]["id"], o["adm"]["headers"])
    validate_error(second, ApiErrorId.ERR_CHECKLIST_INCOMPLETE, 409)

    items, _ = validate_paginated(api_client.list_application_checklist_items(
        app_id, o["adm"]["headers"], params={"category": "CLOSING_CONDITION"}))
    assert items[0]["id"] == ctx["cc_item"]["id"]
    assert items[0]["status"] == "PENDING"


def test_funding_release_before_authorize_rejected():
    """PRD section 3.7: "the authorization must be `AUTHORIZED` and the application
    in `CLOSING` or `FUNDED` (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/funding_release_before_authorize_rejected
    """
    ctx = _closing_200m()
    o = ctx["o"]
    fa = request_funding(o, ctx["application"]["id"], amount_cents=50_000_000)
    assert fa["status"] == "REQUESTED"

    resp = api_client.release_funding(fa["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(
        ctx["application"]["id"], o["adm"]["headers"]))
    assert fas[0]["status"] == "REQUESTED"
    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "CLOSING"
    assert app["funded_amount_cents"] == 0


def test_funding_over_commitment_rejected():
    """PRD section 3.7: "the application's `funded_amount_cents` plus this tranche's
    `amount_cents` must not exceed the letter's `committed_amount_cents` (otherwise
    `ERR_FUNDING_OVER_COMMITMENT`, HTTP 422)."

    Design: Corner/validations/funding_over_commitment_rejected
    """
    ctx = deal_funded(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        first_tranche_cents=150_000_000)
    o = ctx["o"]

    fa2 = request_funding(o, ctx["application"]["id"], amount_cents=60_000_000,
                          disbursement_date="2026-08-16")
    authorize_funding(o, fa2["id"])
    resp = api_client.release_funding(fa2["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_FUNDING_OVER_COMMITMENT)

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(
        ctx["application"]["id"], o["adm"]["headers"]))
    by_id = {f["id"]: f for f in fas}
    assert by_id[fa2["id"]]["status"] == "AUTHORIZED", "rejected release leaves the tranche untouched"

    app = get_application(o, ctx["application"]["id"])
    assert app["funded_amount_cents"] == 150_000_000
    assert app["status"] == "FUNDED"


def test_rate_lock_expired_blocks_release():
    """PRD section 3.7: "the logical clock must not have passed the letter's
    `rate_lock_expires_at` (otherwise `ERR_RATE_LOCK_EXPIRED`)". PRD section 2.6:
    "Any commitment letter still `ISSUED` whose `expiry_date` falls on or before the
    clock's current date transitions to `EXPIRED`" — the sweep touches only ISSUED
    letters, so an ACCEPTED letter survives past its rate lock.

    Design: Corner/validations/rate_lock_expired_blocks_release
    """
    ctx = deal_closing(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        letter_kw={"expiry_date": "2026-09-01", "rate_lock_expires_at": "2026-08-20T12:00:00Z"})
    o = ctx["o"]
    fa = request_funding(o, ctx["application"]["id"], amount_cents=100_000_000,
                         disbursement_date="2026-08-21")
    authorize_funding(o, fa["id"])

    set_clock("2026-08-21T00:00:00Z")
    resp = api_client.release_funding(fa["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_RATE_LOCK_EXPIRED)

    letter = validate_success(api_client.get_commitment_letter(ctx["letter"]["id"], o["adm"]["headers"]), 200)
    assert letter["status"] == "ACCEPTED", "the expiry sweep touches only ISSUED letters"
    app = get_application(o, ctx["application"]["id"])
    assert app["funded_amount_cents"] == 0


def test_sod_funding_self_authorize_rejected():
    """PRD section 2.9: "The officer who authorizes a funding tranche must differ
    from the tranche's `requested_by_officer_id`; a violation is rejected with
    `ERR_SOD_FUNDING_SELF_AUTHORIZE`."

    Design: Corner/rbac/sod_funding_self_authorize_rejected
    """
    ctx = _closing_200m()
    o = ctx["o"]
    fa = request_funding(o, ctx["application"]["id"], amount_cents=50_000_000)
    assert fa["requested_by_officer_id"] == o["adm"]["id"]

    # The requester authorizes their own tranche, wearing the correct role.
    resp = api_client.authorize_funding(
        fa["id"], make_credit_policy_officer_headers(o["adm"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SOD_FUNDING_SELF_AUTHORIZE)

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(
        ctx["application"]["id"], o["adm"]["headers"]))
    assert fas[0]["status"] == "REQUESTED"
    assert fas[0].get("authorized_by_officer_id") is None


def test_funding_authorize_denied_for_credit_administrator():
    """PRD section 4: authorizing a funding tranche is restricted to
    `CreditPolicyOfficer`. PRD section 2.1: "An authenticated caller who attempts an
    operation their role is not permitted to perform is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/funding_authorize_denied_for_credit_administrator
    """
    ctx = _closing_200m()
    o = ctx["o"]
    fa = request_funding(o, ctx["application"]["id"], amount_cents=50_000_000)

    resp = api_client.authorize_funding(fa["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(
        ctx["application"]["id"], o["adm"]["headers"]))
    assert fas[0]["status"] == "REQUESTED"
