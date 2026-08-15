"""Response envelope shape, application version increments, computed-field reads,
and immediate visibility of cross-entity side effects (PRD sections 2.2, 2.4, 3.6).
"""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, api_client, assert_loan_application, attach_statement,
    create_borrower, deal_commitment, deal_intake, deal_letter_issued, deal_underwritten,
    finalize_spreads, get_application, is_iso8601_timestamp, loan_application_payload,
    setup_officers, spread_statement, submit_application, validate_error,
    validate_success, accept_letter, get_borrower, get_letter,
)


def test_response_envelope_object_and_error_shapes():
    """PRD section 2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" with `meta`,
    `response_type` and `data`; and "All error API responses (4xx status codes)
    follow this standard envelope format" with `data.error_id` and `data.message`.

    Design: Corner/endpoints/response_envelope_object_and_error_shapes
    """
    o = setup_officers(["rm"])
    bor = create_borrower(o)

    ok = api_client.get_borrower(bor["id"], o["rm"]["headers"])
    body = ok.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["data"]["id"] == bor["id"]

    err = api_client.get_borrower(NON_EXISTENT_UUID, o["rm"]["headers"])
    error_data = validate_error(err, ApiErrorId.ERR_NOT_FOUND)
    ebody = err.json()
    assert ebody["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    assert "api_request_id" in ebody["meta"] and "api_request_timestamp" in ebody["meta"]


def test_application_version_increments_on_each_mutation():
    """PRD section 2.4: "The `version` field is an integer that starts at its initial
    value on creation and increments by one on every mutation of the resource" and
    "Four operations in particular are guaranteed to advance a loan application's
    `version`: finalizing its spreads, submitting it to committee, issuing a term
    sheet for it, and opening a committee decision against it".

    Design: Corner/entities/application_version_increments_on_each_mutation
    """
    o = setup_officers(["rm", "an"])
    bor = create_borrower(o, legal_name="Window Watchers LLC", relationship_since="2015-01-01")
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=20_000_000, term_months=60),
        o["rm"]["headers"]), 201)
    v0 = app["version"]
    assert isinstance(v0, int) and v0 >= 1
    stmt = attach_statement(o, app["id"], shape="WINDOW")

    submitted = validate_success(api_client.submit_application(app["id"], o["rm"]["headers"]), 200)
    assert submitted["version"] == v0 + 1, "submit mutates the application (status)"
    u1 = submitted["updated_at"]

    # Statement spread/finalize mutate the statement, not the application.
    spread_statement(o, stmt["id"])
    from test_helpers import finalize_statement
    finalize_statement(o, stmt["id"])
    mid = get_application(o, app["id"])
    assert mid["version"] == submitted["version"], (
        "child-only statement mutations must not bump the application's version")

    underwritten = finalize_spreads(o, app["id"])
    assert underwritten["version"] == submitted["version"] + 1, (
        "finalize-spreads is one of the four guaranteed version-advancing operations")
    u2 = underwritten["updated_at"]
    assert is_iso8601_timestamp(u1) and is_iso8601_timestamp(u2)
    assert u2 >= u1, "updated_at refreshes on every modification"


def test_computed_read_reflects_underwriting_outputs():
    """PRD section 3.1: "a single application read exposes every computed
    underwriting field described in the sections that follow."
    PRD section 3.2: "`dscr_standard` is that cash flow divided by annual debt
    service, rounded half-up to four decimal places" and "The `REGULATORY_STRESS`
    variant instead applies a revenue haircut and forbids addbacks".

    Design: Corner/endpoints/computed_read_reflects_underwriting_outputs
    """
    ctx = deal_underwritten(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    data = get_application(o, ctx["application"]["id"])
    assert data["dscr_standard"] == 2.1042, "100,000,000 / 47,522,880"
    assert data["dscr_stress"] == 1.4730, "70,000,000 / 47,522,880"
    # Provisional score (0.4*100 + 0.3*100 + 0.1*100)/0.80 == 100.00 -> band 1.
    assert data["risk_rating"] == 1
    assert data["rating_basis"] == "PROVISIONAL"
    assert data["status"] == "APPRAISAL_REVIEW"


def test_cross_entity_writes_visible_immediately():
    """PRD section 3.6: "Acceptance moves the letter `ISSUED` → `ACCEPTED`, advances
    the application `COMMITMENT` → `DOCUMENTATION`, and adds the letter's
    `committed_amount_cents` to the borrower's `committed_exposure_cents`, with
    `total_exposure_cents` recomputing as ever from its two components."

    Design: Corner/consistency_model/cross_entity_writes_visible_immediately
    """
    ctx = deal_letter_issued(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN")
    o = ctx["o"]
    letter = ctx["letter"]
    assert letter["committed_amount_cents"] == 200_000_000

    accepted = accept_letter(o, letter["id"])
    assert accepted["status"] == "ACCEPTED"

    app_after = get_application(o, ctx["application"]["id"])
    assert app_after["status"] == "DOCUMENTATION", (
        "the application transition is visible on the very next read")

    bor_after = get_borrower(o, ctx["borrower"]["id"])
    assert bor_after["committed_exposure_cents"] == 200_000_000
    assert bor_after["funded_exposure_cents"] == 0
    assert bor_after["total_exposure_cents"] == 200_000_000
