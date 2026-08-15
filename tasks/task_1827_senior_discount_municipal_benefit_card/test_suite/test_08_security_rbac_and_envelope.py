"""Authentication, role authorization, ownership boundaries, the pinned
validation order, the not-found family, and the response envelope
(PRD §2.1–§2.3, §2.8–§2.10)."""
from test_helpers import (
    BOGUS_UUID_1,
    BOGUS_UUID_2,
    BOGUS_UUID_4,
    BOGUS_UUID_5,
    BOGUS_UUID_6,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_fee_waiver_payload,
    create_merchant_payload,
    create_usage_transaction_payload,
    create_merchant,
    create_offer,
    file_claim,
    is_iso8601_timestamp,
    make_cardholder_headers,
    make_merchant_operator_headers,
    onboard_cardholder,
    post_transactions,
    set_clock,
    setup_posted_transactions,
    start_review,
    submit_initial_application,
    upload_document,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["program_administrator_headers"]
SPEC_HEADERS = TEST_USERS["eligibility_specialist_headers"]
FRAUD1_HEADERS = TEST_USERS["fraud_analyst_headers"]
APPLICANT_HEADERS = TEST_USERS["applicant_headers"]

# A request carrying no X-User-ID / X-User-Role credentials at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request with missing or malformed headers, an unrecognized
    role name, or — for the entity-backed roles described below — an
    `X-User-ID` that references no existing entity of the backing type is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    merchant = create_merchant(name="Auth Deli", reimbursement_rate_pct=25,
                               monthly_reimbursement_cap_cents=50000)
    res = api.get_merchant(merchant["id"], NO_AUTH_HEADERS)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_auth_runs_before_existence(api):
    """PRD §2.10: "The server evaluates guards in a pinned order and reports
    the earliest failing tier, so the error a client observes is
    deterministic"
    PRD §2.10: "**Authentication** — header presence, role recognition, and
    entity-backed identity resolution; failures surface as
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "**Path existence** — the left-to-right identifier resolution
    of §2.8; failures surface as the 404 family."
    An unauthenticated read of a nonexistent cardholder reports 401, never 404
    — resource existence is not leaked before authentication.

    Design: Corner/validations/auth_runs_before_existence
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.get_cardholder(NON_EXISTENT_UUID, NO_AUTH_HEADERS)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_specialist_cannot_create_merchant(api, eligibility_specialist_headers):
    """PRD §2.1: "An authenticated caller whose role is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.5: "A `ProgramAdministrator` enrolls a participating merchant by
    supplying the business `name`, the `reimbursement_rate_pct` — the
    percentage of each granted discount the city will repay, greater than zero
    and at most one hundred — and the `monthly_reimbursement_cap_cents`, a
    non-negative ceiling on approved reimbursements per calendar month."
    Enrollment is the administrator's; the EligibilitySpecialist is not
    authorized even with a well-formed body.

    Design: Corner/validations/specialist_cannot_create_merchant_forbidden
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.create_merchant(
        create_merchant_payload("Spec Mart", 25, 50000),
        eligibility_specialist_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_existence_validates_path_left_to_right(api, eligibility_specialist_headers):
    """PRD §2.8: "Requests that address nested resources are validated
    strictly left to right along the path. Existence of each path identifier
    is confirmed in order — the application `id` before the document `docId`,
    the merchant before its offers or claims, the cardholder before its cards
    or fee waivers — and the request is rejected immediately with the 404
    error corresponding to the first identifier that does not resolve to an
    existing resource."
    Both path identifiers are bogus; the leftmost one (the application) is
    reported.

    Design: Corner/validations/existence_validates_path_left_to_right
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.review_document(NON_EXISTENT_UUID, BOGUS_UUID_1, "VERIFIED",
                              eligibility_specialist_headers)
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_not_found_sweep_document_card_transaction_claim_fund(
        api, eligibility_specialist_headers, program_administrator_headers):
    """PRD §2.8: "The not-found family comprises `ERR_APPLICATION_NOT_FOUND`,
    `ERR_DOCUMENT_NOT_FOUND`, `ERR_CARDHOLDER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`,
    `ERR_MERCHANT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, and `ERR_FUND_NOT_FOUND`."
    Each code is triggered on its own resource: a bogus document under a real
    application, a bogus card reference with a real operator and merchant, a
    bogus transaction flag, a bogus claim approval, a bogus fund read.

    Design: Corner/errors/not_found_sweep_document_card_transaction_claim_fund
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Sweep Sam",
                                     residency_address="56 Lost Ln")
    merchant = create_merchant(name="Sweep Store", reimbursement_rate_pct=10,
                               monthly_reimbursement_cap_cents=100000)

    res_doc = api.review_document(app["id"], BOGUS_UUID_1, "VERIFIED",
                                  eligibility_specialist_headers)
    validate_error(res_doc, ApiErrorId.ERR_DOCUMENT_NOT_FOUND)

    res_card = api.create_usage_transaction(
        create_usage_transaction_payload(BOGUS_UUID_2, merchant["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant["id"]))
    validate_error(res_card, ApiErrorId.ERR_CARD_NOT_FOUND)

    res_txn = api.flag_transaction(BOGUS_UUID_4, "ghost", FRAUD1_HEADERS)
    validate_error(res_txn, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)

    res_claim = api.approve_claim(BOGUS_UUID_5, program_administrator_headers)
    validate_error(res_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    res_fund = api.get_program_fund(BOGUS_UUID_6, program_administrator_headers)
    validate_error(res_fund, ApiErrorId.ERR_FUND_NOT_FOUND)


def test_merchant_operator_cannot_approve_claim(api):
    """PRD §2.1: "An authenticated caller whose role is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.8: "Approval is the administrator's settlement act, guarded in the
    order of §2.10."
    Even the merchant's own operator cannot approve the claim.

    Design: Corner/rbac/merchant_operator_cannot_approve_claim_forbidden
    """
    scenario = setup_posted_transactions(
        1, 1000, clock="2026-08-05T10:00:00Z",
        merchant_overrides={"name": "Role Retail", "reimbursement_rate_pct": 50},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 1000})
    merchant_id = scenario["merchant"]["id"]
    set_clock("2026-09-01T00:00:00Z")
    claim = file_claim(merchant_id, "2026-08")

    res = api.approve_claim(claim["id"], make_merchant_operator_headers(merchant_id))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    claims = validate_success(
        api.list_reimbursement_claims(merchant_id, ADMIN_HEADERS), 200)
    assert claims[0]["status"] == "SUBMITTED", "the forbidden approval changes nothing"


def test_cardholder_cannot_flag_transaction(api):
    """PRD §2.1: "An authenticated caller whose role is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.7: "Beyond the automatic velocity flag, a `FraudAnalyst` may
    manually flag a transaction that stands in `POSTED`, supplying a free-form
    `reason` (its absence is an `ERR_INVALID_REQUEST`); flagging a transaction
    in any other status is rejected with `ERR_TRANSACTION_NOT_FLAGGABLE`
    (HTTP 409)."
    Flagging is the FraudAnalyst's; even the transaction's own cardholder is
    not authorized.

    Design: Corner/rbac/cardholder_cannot_flag_transaction_forbidden
    """
    scenario = setup_posted_transactions(
        1, 100, clock=None,
        merchant_overrides={"name": "Flag Mart", "reimbursement_rate_pct": 10},
        offer_overrides={"category": "GROCERY", "discount_pct": 10,
                         "max_discount_cents": 100})
    txn = scenario["transactions"][0]
    res = api.flag_transaction(
        txn["id"], "self report",
        make_cardholder_headers(scenario["cardholder"]["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_usage_transaction(txn["id"], FRAUD1_HEADERS), 200)
    assert after["status"] == "POSTED"


def test_applicant_cannot_review_documents(api, applicant_headers,
                                           eligibility_specialist_headers):
    """PRD §2.1: "An authenticated caller whose role is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.2: "The specialist adjudicates each document with a `decision` of
    `VERIFIED` or `REJECTED`; a rejection must carry a `rejection_reason` in
    the payload (its absence is an `ERR_INVALID_REQUEST`), and the decision
    stamps `reviewed_by_user_id` with the reviewing specialist."
    The applicant who uploaded the document cannot adjudicate it.

    Design: Corner/rbac/applicant_cannot_review_documents_forbidden
    """
    set_clock("2026-08-01T00:00:00Z")
    app = submit_initial_application(full_name="Review Ron",
                                     residency_address="59 Review Rd")
    start_review(app["id"])
    doc = upload_document(app["id"], "PROOF_OF_AGE", "VR-AGE")

    res = api.review_document(app["id"], doc["id"], "VERIFIED", applicant_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    docs = validate_success(api.list_documents(app["id"], SPEC_HEADERS), 200)
    assert docs[0]["status"] == "SUBMITTED"


def test_fraud_analyst_cannot_grant_waiver(api, fraud_analyst_headers):
    """PRD §2.1: "An authenticated caller whose role is not listed among the
    roles authorized for the target endpoint is rejected with
    `ERR_FORBIDDEN`."
    PRD §3.5: "A `ProgramAdministrator` may grant a cardholder a waiver of
    `waiver_type` `TRANSIT_FARE` or `FACILITY_FEE` over a closed date interval
    from `start_date` through `end_date`, both inclusive."

    Design: Corner/rbac/fraud_analyst_cannot_grant_waiver_forbidden
    """
    onboard = onboard_cardholder(full_name="Waiver Will",
                                 residency_address="60 Grant Gr")
    res = api.grant_fee_waiver(
        onboard["cardholder"]["id"],
        create_fee_waiver_payload("TRANSIT_FARE", "2026-09-01", "2026-09-30"),
        fraud_analyst_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_cardholder_cannot_read_other_cardholder(api):
    """PRD §2.9: "Symmetrically, a `Cardholder` caller may read a cardholder
    record, list its applications, cards, or fee waiver grants, and request a
    card only when the path cardholder identifier equals their own
    `X-User-ID`; otherwise the request is rejected with
    `ERR_CARDHOLDER_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/cardholder_cannot_read_other_cardholder_forbidden
    """
    alice = onboard_cardholder(full_name="Alice Own", residency_address="51 Own St")
    bob = onboard_cardholder(full_name="Bob Other", residency_address="52 Other St")
    res = api.get_cardholder(bob["cardholder"]["id"],
                             make_cardholder_headers(alice["cardholder"]["id"]))
    validate_error(res, ApiErrorId.ERR_CARDHOLDER_OWNERSHIP_MISMATCH)


def _setup_ownership_vs_velocity():
    """One cardholder with nine transactions inside the trailing 24-hour
    window (four at 2026-08-10T20:00:00Z, five at 2026-08-11T08:00:00Z — the
    fifth auto-flagged, still below the suspension threshold), and two
    merchants A and B each with a GROCERY offer."""
    onboard = onboard_cardholder(full_name="Owner Mismatch",
                                 residency_address="11 Hemlock St")
    merchant_a = create_merchant(name="Merchant A", reimbursement_rate_pct=10,
                                 monthly_reimbursement_cap_cents=100000)
    merchant_b = create_merchant(name="Merchant B", reimbursement_rate_pct=10,
                                 monthly_reimbursement_cap_cents=100000)
    for merchant in (merchant_a, merchant_b):
        create_offer(merchant["id"], category="GROCERY", discount_pct=10,
                     max_discount_cents=100)
    set_clock("2026-08-10T20:00:00Z")
    post_transactions(onboard["card"]["id"], merchant_a["id"], 4, 100)
    set_clock("2026-08-11T08:00:00Z")
    post_transactions(onboard["card"]["id"], merchant_a["id"], 5, 100)
    return onboard, merchant_a, merchant_b


def test_ownership_mismatch_beats_velocity_limit(api):
    """PRD §2.9: "A `MerchantOperator` caller's `X-User-ID` must equal the
    merchant being acted upon — the `merchant_id` supplied when recording a
    purchase, the merchant that owns the transaction being voided, the path
    merchant when publishing an offer, and the path merchant when filing a
    reimbursement claim; any mismatch is rejected with
    `ERR_MERCHANT_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §2.10: "The server evaluates guards in a pinned order and reports the
    earliest failing tier, so the error a client observes is deterministic"
    PRD §2.10: "**Ownership** — the entity-backed boundaries of §2.9; failures
    surface as `ERR_MERCHANT_OWNERSHIP_MISMATCH` or
    `ERR_CARDHOLDER_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §2.10: "**Fraud and segregation safeguards** — the velocity hard limit
    on purchase recording (HTTP 422) and the segregation-of-duties guards on
    application approval and flag clearing (HTTP 403)."
    Operator A records a purchase naming merchant B while the cardholder's
    trailing-24h count would reach ten: the ownership tier fires first.

    Design: Difficulty/priority_pair_validation_conflict/usage_ownership_vs_velocity_priority
    """
    onboard, merchant_a, merchant_b = _setup_ownership_vs_velocity()
    res = api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant_b["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant_a["id"]))
    validate_error(res, ApiErrorId.ERR_MERCHANT_OWNERSHIP_MISMATCH)


def test_velocity_limit_fires_when_ownership_ok(api):
    """PRD §3.6: "The trailing-window count tallies transactions whose
    `created_at` falls later than twenty-four hours before the current clock
    instant and at or before it, and adds one for the candidate; if that total
    reaches ten, creation is refused outright with `ERR_VELOCITY_HARD_LIMIT`
    (HTTP 422)."
    Control for the ownership-priority case: the same cardholder history at
    the operator's OWN merchant reaches the velocity tier and is refused —
    the safety condition was genuinely armed.

    Design: Difficulty/priority_pair_validation_conflict/usage_ownership_vs_velocity_priority
    """
    onboard, merchant_a, _ = _setup_ownership_vs_velocity()
    set_clock("2026-08-11T10:00:00Z")
    res = api.create_usage_transaction(
        create_usage_transaction_payload(onboard["card"]["id"], merchant_a["id"],
                                         "GROCERY", 100),
        make_merchant_operator_headers(merchant_a["id"]))
    validate_error(res, ApiErrorId.ERR_VELOCITY_HARD_LIMIT)


def test_response_envelope_success_and_error_shape(api, program_administrator_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    merchant = create_merchant(name="Envelope Eats", reimbursement_rate_pct=25,
                               monthly_reimbursement_cap_cents=50000)

    ok_res = api.get_merchant(merchant["id"], program_administrator_headers)
    assert ok_res.status_code == 200
    ok_body = ok_res.json()
    assert isinstance(ok_body["meta"].get("api_request_id"), str)
    assert ok_body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(ok_body["meta"]["api_request_timestamp"])
    assert ok_body["response_type"] == "object"
    assert ok_body["data"]["id"] == merchant["id"]

    err_res = api.get_merchant(NON_EXISTENT_UUID, program_administrator_headers)
    assert err_res.status_code == 404
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_MERCHANT_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert err_body["data"]["message"].strip()
