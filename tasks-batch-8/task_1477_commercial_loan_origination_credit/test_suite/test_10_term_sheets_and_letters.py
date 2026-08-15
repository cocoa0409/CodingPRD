"""Term sheets (OCC, supersede, decline/replacement, expiry sweep, tiered fee) and
commitment letters (issue window, accept order) (PRD sections 2.6, 2.7, 3.6).
"""
from test_helpers import (
    ApiErrorId, api_client, deal_approved, deal_commitment, deal_committee_review,
    deal_letter_issued, get_application, get_letter, issue_letter, issue_term_sheet,
    respond_sheet, set_clock, setup_officers, validate_error, validate_paginated,
    validate_success, create_borrower, loan_application_payload, attach_statement,
    submit_application, spread_and_finalize, finalize_spreads, create_appraiser,
    order_and_accept_appraisal, submit_to_committee, create_session, open_decision,
    approve_decision, cast_vote,
)


def _approved_200m(**kw):
    """Clean 200,000,000 deal approved by a STANDARD committee."""
    return deal_approved(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN", **kw)


def test_term_sheet_decline_allows_replacement():
    """PRD section 3.6: "A `DECLINED` response requires only that the sheet be
    `ISSUED`; the sheet moves to `DECLINED`, the application remains in
    `TERM_SHEET_NEGOTIATION`, and a replacement sheet may be issued."

    Design: Corner/state_machines/term_sheet_decline_allows_replacement
    """
    ctx = _approved_200m()
    o = ctx["o"]
    sheet1 = issue_term_sheet(o, ctx["application"]["id"], 200_000_000)
    assert sheet1["status"] == "ISSUED"

    declined = respond_sheet(o, sheet1["id"], "DECLINED")
    assert declined["status"] == "DECLINED"
    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "TERM_SHEET_NEGOTIATION", "decline does not move the application"

    sheet2 = issue_term_sheet(o, app["id"], 200_000_000, rate_bps=700, term_months=48,
                              expires_at="2026-08-25T00:00:00Z")
    assert sheet2["status"] == "ISSUED"

    letters, meta = validate_paginated(api_client.list_commitment_letters(
        o["rm"]["headers"], params={"loan_application_id": app["id"]}))
    assert letters == [], "no commitment letter exists before an ACCEPTED response"


def test_new_term_sheet_supersedes_prior_issued():
    """PRD section 3.6: "Issuing a new sheet supersedes the application's currently
    `ISSUED` sheet if one exists, moving it to `SUPERSEDED`, and advances the
    application's `version` by one." and "An `ACCEPTED` response requires the sheet
    to be `ISSUED` and the application in `TERM_SHEET_NEGOTIATION`".

    Design: Corner/state_machines/new_term_sheet_supersedes_prior_issued
    """
    ctx = _approved_200m(officer_keys=("rm", "an", "po", "apm", "ch",
                                       "m1", "m2", "m3", "m4", "adm"))
    o = ctx["o"]
    sheet1 = issue_term_sheet(o, ctx["application"]["id"], 200_000_000)
    sheet2 = issue_term_sheet(o, ctx["application"]["id"], 200_000_000,
                              rate_bps=625, expires_at="2026-08-22T00:00:00Z")
    assert sheet2["status"] == "ISSUED"

    rows, _ = validate_paginated(api_client.list_application_term_sheets(
        ctx["application"]["id"], o["rm"]["headers"]))
    by_id = {s["id"]: s for s in rows}
    assert by_id[sheet1["id"]]["status"] == "SUPERSEDED"

    stale = api_client.respond_term_sheet(sheet1["id"], {"outcome": "ACCEPTED"}, o["rm"]["headers"])
    validate_error(stale, ApiErrorId.ERR_INVALID_STATE)

    accepted = respond_sheet(o, sheet2["id"], "ACCEPTED")
    assert accepted["status"] == "ACCEPTED"
    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "COMMITMENT"
    letter = get_letter(o, app["id"])
    assert letter["status"] == "DRAFT"
    assert letter["rate_bps"] == 625


def test_term_sheet_expiry_sweep():
    """PRD section 2.6: "Any term sheet still `ISSUED` whose `expires_at` is
    strictly earlier than the current clock instant transitions to `EXPIRED`."
    PRD section 3.6: "the clock sweep moves any sheet still `ISSUED` whose
    `expires_at` is strictly before the current instant to `EXPIRED`."

    Design: Corner/state_machines/term_sheet_expiry_sweep
    """
    ctx = _approved_200m()
    o = ctx["o"]
    sheet = issue_term_sheet(o, ctx["application"]["id"], 200_000_000,
                             expires_at="2026-08-12T00:00:00Z")
    assert sheet["status"] == "ISSUED"

    set_clock("2026-08-13T00:00:00Z")
    rows, _ = validate_paginated(api_client.list_application_term_sheets(
        ctx["application"]["id"], o["rm"]["headers"]))
    assert rows[0]["status"] == "EXPIRED"

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "TERM_SHEET_NEGOTIATION", (
        "sheet expiry does NOT cascade to the application")

    resp = api_client.respond_term_sheet(sheet["id"], {"outcome": "ACCEPTED"}, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_term_sheet_amount_must_equal_proposed():
    """PRD section 3.6: "the offered `amount_cents` must equal the application's
    `proposed_amount_cents` exactly (otherwise `ERR_VALIDATION`)."

    Design: Corner/validations/term_sheet_amount_must_equal_proposed
    """
    ctx = _approved_200m()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    assert ctx["application"]["proposed_amount_cents"] == 200_000_000

    current = get_application(o, app_id)
    bad = api_client.create_term_sheet(
        {"loan_application_id": app_id, "amount_cents": 199_999_999, "rate_bps": 650,
         "term_months": 60, "expires_at": "2026-08-20T00:00:00Z",
         "expected_loan_application_version": current["version"]}, o["rm"]["headers"])
    validate_error(bad, ApiErrorId.ERR_VALIDATION)

    # The rejected attempt consumed no version bump: the same expected version works.
    good = issue_term_sheet(o, app_id, 200_000_000)
    assert good["status"] == "ISSUED"
    assert good["origination_fee_cents"] == 1_750_000


def test_origination_fee_tier_boundaries_and_straddle():
    """PRD section 3.6: "the first $1,000,000.00 is charged at 1.00%, the next
    $4,000,000.00 at 0.75%, and any portion above $5,000,000.00 at 0.50%. Each
    tier's slice is rounded half-up to whole cents individually, and the three
    rounded slices are then summed in tier order".

    Design: Corner/calculations/origination_fee_tier_boundaries_and_straddle
    """
    # app1: 100,000,000 (exactly the tier-1 cap) approved by SMALL committee.
    o = setup_officers(["rm", "an", "apm", "ch", "m1", "m2"])
    bor1 = create_borrower(o, legal_name="Tier One LLC", naics_code="531120",
                           relationship_since="2010-01-01")
    app1 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor1["id"], requested_amount_cents=100_000_000, term_months=60),
        o["rm"]["headers"]), 201)
    stmt1 = attach_statement(o, app1["id"], shape="TIER")
    submit_application(o, app1["id"])
    spread_and_finalize(o, stmt1["id"])
    finalize_spreads(o, app1["id"])
    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, app1["id"], appraiser["id"], 400_000_000, 380_000_000)
    submit_to_committee(o, app1["id"])
    sess1 = create_session(o, level="SMALL", starts_at="2026-08-10T14:00:00Z",
                           ends_at="2026-08-10T15:00:00Z")
    set_clock("2026-08-10T14:30:00Z")
    dec1 = open_decision(o, app1["id"], sess1["id"])
    cast_vote(o, dec1["id"], "m1", "APPROVE")
    cast_vote(o, dec1["id"], "m2", "APPROVE")

    sheet1 = issue_term_sheet(o, app1["id"], 100_000_000)
    assert sheet1["origination_fee_cents"] == 1_000_000, (
        "100,000,000 x 0.0100; the tier-2 slice is exactly 0 at the inclusive cap")

    # app2: 600,000,000 straddling all three tiers, STANDARD committee.
    bor2 = create_borrower(o, legal_name="Tier Three LLC", naics_code="531120",
                           relationship_since="2010-01-01")
    app2 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor2["id"], requested_amount_cents=600_000_000, term_months=60),
        o["rm"]["headers"]), 201)
    stmt2 = attach_statement(o, app2["id"], shape="TIER3")
    submit_application(o, app2["id"])
    spread_and_finalize(o, stmt2["id"])
    finalize_spreads(o, app2["id"])
    order_and_accept_appraisal(o, app2["id"], appraiser["id"], 1_000_000_000, 950_000_000,
                               engagement_start_date="2026-08-11",
                               engagement_end_date="2026-08-14")
    submit_to_committee(o, app2["id"])
    sess2 = create_session(o, level="STANDARD", starts_at="2026-08-10T15:30:00Z",
                           ends_at="2026-08-10T16:30:00Z")
    set_clock("2026-08-10T15:45:00Z")
    dec2 = open_decision(o, app2["id"], sess2["id"])
    cast_vote(o, dec2["id"], "m1", "APPROVE")
    cast_vote(o, dec2["id"], "m2", "APPROVE")

    sheet2 = issue_term_sheet(o, app2["id"], 600_000_000)
    assert sheet2["origination_fee_cents"] == 4_500_000, (
        "1,000,000 + 400,000,000 x 0.0075 + 100,000,000 x 0.0050, slices rounded then summed")


def test_occ_term_sheet_stale_version_rejected():
    """PRD section 2.7: "If the supplied value does not equal the application's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 2.4: "Four operations in particular are guaranteed to advance a loan
    application's `version`: ... issuing a term sheet for it".

    Design: Corner/cross_cutting_complexity_layers/occ_term_sheet_stale_version_rejected
    """
    ctx = _approved_200m()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    observed = get_application(o, app_id)["version"]

    sheet1 = issue_term_sheet(o, app_id, 200_000_000)
    assert sheet1["status"] == "ISSUED"

    stale = api_client.create_term_sheet(
        {"loan_application_id": app_id, "amount_cents": 200_000_000, "rate_bps": 600,
         "term_months": 60, "expires_at": "2026-08-22T00:00:00Z",
         "expected_loan_application_version": observed}, o["rm"]["headers"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    rows, meta = validate_paginated(api_client.list_application_term_sheets(app_id, o["rm"]["headers"]))
    assert len(rows) == 1, "the rejected create superseded nothing"
    assert rows[0]["id"] == sheet1["id"]
    assert rows[0]["status"] == "ISSUED"


def test_schema_validation_precedes_occ_check():
    """PRD section 2.8: optimistic concurrency "runs after schema validation but
    before every remaining state and business check" and "the first failing check
    determines the error response". Stage 4 covers "numeric and date ranges hold:
    monetary amounts strictly greater than zero" — so a non-positive `amount_cents`
    is a body-schema failure that fires before the OCC check.

    Design: Corner/validations/schema_validation_precedes_occ_check
    """
    ctx = _approved_200m()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    current = get_application(o, app_id)

    resp = api_client.create_term_sheet(
        {"loan_application_id": app_id, "amount_cents": 0, "rate_bps": 650,
         "term_months": 60, "expires_at": "2026-08-20T00:00:00Z",
         "expected_loan_application_version": current["version"] - 1}, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
    assert resp.json()["data"]["error_id"] != "ERR_STALE_VERSION"


def test_occ_check_precedes_state_check():
    """PRD section 2.8: "Optimistic concurrency ... Applies only to term-sheet
    issuance and committee-decision opening, and on those two endpoints it runs
    after schema validation but before every remaining state and business check" —
    so a stale version on an application still in COMMITTEE_REVIEW (wrong state for
    sheets) returns `ERR_STALE_VERSION`, not `ERR_INVALID_STATE`.

    Design: Corner/validations/occ_check_precedes_state_check
    """
    ctx = deal_committee_review()  # COMMITTEE_REVIEW; no session/decision opened
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    resp = api_client.create_term_sheet(
        {"loan_application_id": app_id, "amount_cents": 200_000_000, "rate_bps": 650,
         "term_months": 60, "expires_at": "2026-08-20T00:00:00Z",
         "expected_loan_application_version": ctx["application"]["version"] - 1},
        o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    rows, meta = validate_paginated(api_client.list_application_term_sheets(app_id, o["rm"]["headers"]))
    assert rows == []


def test_letter_accept_from_draft_rejected():
    """PRD section 3.6: "The borrower's acceptance, recorded by a
    `CreditAdministrator`, requires the letter `ISSUED`" and PRD section 2.8:
    "The target entity is in a legal from-state for the requested transition;
    otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/letter_accept_from_draft_rejected
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    letter = ctx["letter"]
    assert letter["status"] == "DRAFT"

    resp = api_client.accept_commitment_letter(letter["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api_client.get_commitment_letter(letter["id"], o["adm"]["headers"]), 200)
    assert after["status"] == "DRAFT"
    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "COMMITMENT", "no side effects fired"


def test_letter_issue_rate_lock_window_validated():
    """PRD section 3.6: "A `CreditAdministrator` then issues the draft letter by
    setting its `expiry_date` (an ISO date) and `rate_lock_expires_at` (an ISO 8601
    datetime), with the rate lock required to fall no later than 23:59:59 UTC on the
    expiry date (otherwise `ERR_VALIDATION`)".

    Design: Corner/validations/letter_issue_rate_lock_window_validated
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    letter = ctx["letter"]

    bad = api_client.issue_commitment_letter(
        letter["id"], {"expiry_date": "2026-09-01",
                       "rate_lock_expires_at": "2026-09-02T00:00:00Z"}, o["adm"]["headers"])
    validate_error(bad, ApiErrorId.ERR_VALIDATION)

    ok = validate_success(api_client.issue_commitment_letter(
        letter["id"], {"expiry_date": "2026-09-01",
                       "rate_lock_expires_at": "2026-09-01T23:59:59Z"}, o["adm"]["headers"]), 200)
    assert ok["status"] == "ISSUED", "exactly end-of-day is admitted (inclusive)"


def test_letter_accept_on_expiry_date_rejected():
    """PRD section 3.6: "The borrower's acceptance, recorded by a
    `CreditAdministrator`, requires the letter `ISSUED` and the logical clock's
    current date strictly earlier than the `expiry_date` — acceptance on or after
    that date is refused with `ERR_COMMITMENT_EXPIRED`."

    Design: Corner/validations/letter_accept_on_expiry_date_rejected
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    # The clock is at 2026-08-10 (set during the committee step); the letter is
    # issued with an expiry date already past. No clock-set has run since issue,
    # so no sweep has fired and the letter is still ISSUED.
    letter = issue_letter(o, ctx["letter"]["id"], expiry_date="2026-08-01",
                          rate_lock_expires_at="2026-08-01T23:59:59Z")
    assert letter["status"] == "ISSUED"

    resp = api_client.accept_commitment_letter(letter["id"], o["adm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXPIRED)

    after = validate_success(api_client.get_commitment_letter(letter["id"], o["adm"]["headers"]), 200)
    assert after["status"] == "ISSUED"
    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "COMMITMENT"


def test_letter_issue_denied_for_relationship_manager():
    """PRD section 4: issuing a commitment letter is restricted to
    `CreditAdministrator`. PRD section 2.1: "An authenticated caller who attempts an
    operation their role is not permitted to perform is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/letter_issue_denied_for_relationship_manager
    """
    ctx = deal_commitment(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    resp = api_client.issue_commitment_letter(
        ctx["letter"]["id"], {"expiry_date": "2026-09-01",
                              "rate_lock_expires_at": "2026-08-31T23:59:59Z"}, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    after = validate_success(api_client.get_commitment_letter(ctx["letter"]["id"], o["rm"]["headers"]), 200)
    assert after["status"] == "DRAFT"
