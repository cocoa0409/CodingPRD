"""Who may act: role lists, record scope and the three segregation rules."""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import (
    ANALYST,
    COMMITTEE,
    REVIEWER,
    SECOND_REVIEWER,
    UNDERWRITER,
)
from test_helpers.test_users import (
    make_borrower_headers,
    make_credit_committee_headers,
    make_headers,
    make_institution_officer_headers,
)


def test_the_two_credit_roles_cannot_perform_each_others_operation():
    """Pricing belongs to the underwriter and the signature to the committee.

    PRD: "A `CreditUnderwriter` enters verified capacity figures and runs the
    pricing and grading chain, and is barred from deciding the loans it
    underwrites."
    PRD: "A `CreditCommittee` member approves or declines underwritten loans
    subject to the technical-assistance prerequisite and the product cap."
    PRD: "The acting role appearing in the endpoint's authorised-role list
    (`ERR_UNAUTHORIZED`)."

    Design: Corner/rbac/credit_roles_cannot_swap_their_exclusive_operations
    """
    scenario = fixtures.setup_lending_ready_institution()
    loan = fixtures.file_loan(
        scenario["institution"]["id"], scenario["borrower"]["id"],
        scenario["product"]["id"], 1_000_000,
    )
    pricing = factories.underwrite_payload(1_000_000, 100_000, 740)

    validate_error(
        api_client.underwrite_loan(loan["id"], pricing, COMMITTEE),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.decide_loan(
            loan["id"],
            {"decision": "APPROVE", "approved_principal_cents": 1_000_000},
            UNDERWRITER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.underwrite_loan(loan["id"], pricing, ANALYST),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    priced = validate_success(
        api_client.underwrite_loan(loan["id"], pricing, UNDERWRITER)
    )
    assert priced["underwriting_state"] == "UNDERWRITING"
    assert float(priced["dti_pct"]) == 12.42
    assert priced["underwritten_by_user_id"] == "uw-1"


def test_market_authorship_and_market_approval_belong_to_different_roles():
    """The lender writes the definition and the authority alone approves it.

    PRD: "An `InstitutionOfficer` is the operating officer of the lender
    itself: it registers the institution, defines target markets, seats and
    retires board members, files certification and award paperwork, onboards
    borrowers, publishes products, books technical assistance, disburses
    principal and applies payments."
    PRD: "A `CertificationReviewer` acts for the certifying authority: it
    approves target-market definitions, opens review, records the six
    certification-test verdicts, requests further information and signs the
    certification decision."

    Design: Corner/rbac/officer_and_reviewer_cannot_take_over_each_others_market_operations
    """
    institution = fixtures.create_institution(ein="210000061")
    institution_id = institution["id"]
    officer = make_institution_officer_headers(institution_id)
    market = fixtures.create_target_market(institution_id)
    assert market["state"] == "DRAFT"

    validate_error(
        api_client.approve_target_market(market["id"], officer),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_target_market(
            institution_id,
            {
                "market_type": "INVESTMENT_AREA",
                "name": "Reviewer Authored Market",
                "census_tract_codes": ["36005011200"],
            },
            REVIEWER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    approved = validate_success(
        api_client.approve_target_market(market["id"], REVIEWER)
    )
    assert approved["state"] == "APPROVED"

    _rows, meta = validate_paginated(
        api_client.list_institution_target_markets(institution_id, ANALYST)
    )
    assert meta["total_count"] == 1, (
        "the refused authorship attempt left no second definition behind"
    )


def test_an_officer_of_one_lender_cannot_read_or_plant_records_of_another():
    """The acting identity is the lender itself, so scope is the lender itself.

    PRD: "When `X-User-Role` is `InstitutionOfficer`, `X-User-ID` is the `id` of
    the acting `Institution`; ownership checks on any resource that references
    an `Institution` compare the resource's owning-institution field to
    `X-User-ID`."
    PRD: "Concretely, an `InstitutionOfficer` must be the owner of the addressed
    resource — the path institution itself, or the owning institution of the
    addressed target market, board seat, borrower, loan product, loan,
    technical-assistance engagement, impact report, compliance measurement,
    award application or matching-fund commitment — and a mismatch is rejected
    with `ERR_INSTITUTION_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/officer_of_one_lender_cannot_reach_another_lenders_records
    """
    alpha = fixtures.create_institution(
        legal_name="Alpha Community Fund", ein="210000062"
    )
    beta = fixtures.create_institution(
        legal_name="Beta Community Fund", ein="210000063"
    )
    alpha_officer = make_institution_officer_headers(alpha["id"])
    beta_officer = make_institution_officer_headers(beta["id"])
    product = fixtures.create_loan_product(alpha["id"])
    borrower = fixtures.create_borrower(alpha["id"])
    loan = fixtures.file_loan(
        alpha["id"], borrower["id"], product["id"], 1_000_000
    )

    validate_error(
        api_client.get_loan(loan["id"], beta_officer),
        ApiErrorId.ERR_INSTITUTION_SCOPE_VIOLATION,
    )
    validate_error(
        api_client.create_borrower(
            alpha["id"], factories.borrower_payload(full_name="Planted Borrower"),
            beta_officer,
        ),
        ApiErrorId.ERR_INSTITUTION_SCOPE_VIOLATION,
    )

    own = validate_success(api_client.get_loan(loan["id"], alpha_officer))
    assert own["id"] == loan["id"]
    assert own["institution_id"] == alpha["id"]

    _rows, meta = validate_paginated(
        api_client.list_institution_borrowers(alpha["id"], ANALYST)
    )
    assert meta["total_count"] == 1, (
        "the cross-tenant intake attempt planted nothing"
    )


def test_a_borrower_may_only_file_impact_data_on_its_own_loan():
    """The filing identity must match the loan's borrower of record.

    PRD: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the
    acting `Borrower`; a borrower filing an impact report against a loan must
    match that loan's borrower of record, and a borrower correcting a disputed
    report must match that report's borrower of record."
    PRD: "Either mismatch is rejected with `ERR_BORROWER_SCOPE_VIOLATION`
    (HTTP 403)."
    PRD: "The report is created in `state` `SUBMITTED` with `revision_count` 0,
    `dispute_reason` null, `verified_at` null, and `borrower_id` copied from the
    loan's borrower of record rather than taken from the request."
    PRD: "Filing a report advances the loan's `version` by 1."

    Design: Corner/rbac/borrower_cannot_file_impact_data_on_a_loan_that_is_not_theirs
    """
    institution = fixtures.create_institution(ein="210000064")
    institution_id = institution["id"]
    product = fixtures.create_loan_product(institution_id)
    obligor = fixtures.create_borrower(institution_id, full_name="Maria Ortiz")
    stranger = fixtures.create_borrower(institution_id, full_name="Dana Whitfield")
    loan = fixtures.file_loan(
        institution_id, obligor["id"], product["id"], 1_000_000
    )
    assert loan["version"] == 1

    validate_error(
        api_client.create_impact_report(
            loan["id"],
            factories.impact_report_payload(
                loan["version"], "2026-07-31T00:00:00Z",
                jobs_created=9, jobs_retained=9, housing_units=9,
                businesses_financed=9,
            ),
            make_borrower_headers(stranger["id"]),
        ),
        ApiErrorId.ERR_BORROWER_SCOPE_VIOLATION,
    )

    filed = validate_success(
        api_client.create_impact_report(
            loan["id"],
            factories.impact_report_payload(
                loan["version"], "2026-07-31T00:00:00Z",
                jobs_created=3, jobs_retained=1, housing_units=0,
                businesses_financed=1,
            ),
            make_borrower_headers(obligor["id"]),
        ),
        201,
    )
    assert filed["borrower_id"] == obligor["id"]
    assert filed["state"] == "SUBMITTED"
    assert filed["jobs_created"] == 3

    reread_loan = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert reread_loan["version"] == 2, (
        "only the accepted filing consumed the loan's version token"
    )

    _rows, meta = validate_paginated(
        api_client.list_impact_reports(ANALYST, {"loan_id": loan["id"]})
    )
    assert meta["total_count"] == 1


def test_the_underwriter_of_record_cannot_sign_the_credit_decision():
    """The same operator identifier may not appear on both credit steps.

    PRD: "First, the credit-committee member deciding a loan must not be the
    underwriter recorded on that loan."
    PRD: "The loan must be in `underwriting_state` `UNDERWRITING`, failing with
    `ERR_LOAN_NOT_IN_UNDERWRITING`, and the deciding `X-User-ID` must differ
    from `underwritten_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "A successful approval moves the loan `UNDERWRITING → APPROVED`,
    records `approved_principal_cents` and `decided_by_user_id`, and adds the
    approved amount to the product's `committed_principal_cents`."

    Design: Corner/rbac/the_underwriter_who_priced_the_loan_cannot_also_sign_the_decision
    """
    scenario = fixtures.setup_lending_ready_institution()
    loan = fixtures.file_loan(
        scenario["institution"]["id"], scenario["borrower"]["id"],
        scenario["product"]["id"], 1_000_000,
    )
    priced = fixtures.underwrite_loan(loan["id"])
    assert priced["underwritten_by_user_id"] == "uw-1"

    approval = {"decision": "APPROVE", "approved_principal_cents": 1_000_000}
    validate_error(
        api_client.decide_loan(
            loan["id"], approval, make_credit_committee_headers("uw-1")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    decided = validate_success(
        api_client.decide_loan(loan["id"], approval, COMMITTEE)
    )
    assert decided["underwriting_state"] == "APPROVED"
    assert decided["underwritten_by_user_id"] == "uw-1"
    assert decided["decided_by_user_id"] == "cc-1"
    assert decided["approved_principal_cents"] == 1_000_000


def test_the_reviewer_who_opened_review_cannot_sign_the_certification():
    """A second reviewer must sign, and the opener stays on the record.

    PRD: "Second, the reviewer who signs a certification decision must not be
    the reviewer who opened review on that application."
    PRD: "The signing `CertificationReviewer` must present an `X-User-ID`
    different from `reviewed_by_user_id`, or the signature is refused with
    `ERR_SEGREGATION_OF_DUTIES`; the docket must be `UNDER_REVIEW`; and no
    verdict may still be `PENDING`, or the signature is refused with
    `ERR_TEST_VERDICT_PENDING`."
    PRD: "Given all six verdicts settled, the outcome is mechanical: when every
    one of the six is either `PASSED` or `WAIVED` the docket goes `UNDER_REVIEW
    → CERTIFIED`, and when at least one of the six is `FAILED` it goes
    `UNDER_REVIEW → DENIED`."
    PRD: "Certification is the moment the institution itself changes: on the
    `CERTIFIED` outcome the institution moves `UNCERTIFIED → CERTIFIED`,
    `certified_at` is stamped from the logical clock, `recertification_due_at`
    is set to the logical clock plus 1,095 days — three years, the interval at
    which target-market performance must be re-proved — and the institution's
    `version` advances by 1."

    Design: Corner/rbac/the_reviewer_who_scored_the_tests_cannot_sign_the_certification
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_application_under_review()
    institution_id = scenario["institution"]["id"]
    application_id = scenario["application"]["id"]
    assert scenario["application"]["reviewed_by_user_id"] == "rev-1"

    for test_code in (
        "PRIMARY_MISSION",
        "FINANCING_ENTITY",
        "TARGET_MARKET",
        "DEVELOPMENT_SERVICES",
        "ACCOUNTABILITY",
    ):
        fixtures.record_certification_verdict(application_id, test_code, "PASSED")
    fixtures.record_certification_verdict(
        application_id, "NON_GOVERNMENT", "WAIVED"
    )

    validate_error(
        api_client.decide_certification_application(application_id, REVIEWER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    signed = validate_success(
        api_client.decide_certification_application(
            application_id, SECOND_REVIEWER
        )
    )
    assert signed["state"] == "CERTIFIED"
    assert signed["test_non_government_state"] == "WAIVED"
    assert signed["decided_at"] == "2026-09-01T00:00:00.000Z"
    assert signed["reviewed_by_user_id"] == "rev-1", (
        "the signature never overwrites the identity that opened review"
    )

    certified = fixtures.read_institution(institution_id)
    assert certified["certification_state"] == "CERTIFIED"
    assert certified["certified_at"] == "2026-09-01T00:00:00.000Z"


def test_an_unknown_role_or_an_empty_identity_is_refused_before_every_check():
    """Authentication is the first gate, so even an unknown record reads 401.

    PRD: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role under
    which the principal acts."
    PRD: "If either header is absent or empty, or if `X-User-Role` does not name
    one of the seven roles below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD: "This authentication gate is evaluated before every other check in the
    system: the header-presence test is the very first evaluation, and the
    role-recognition test is the second, so an unrecognised role never reaches an
    authorisation or existence check."

    Design: Corner/rbac/missing_or_unknown_identity_headers_rejected_before_anything_else
    """
    institution = fixtures.create_institution(ein="210000065")
    institution_id = institution["id"]

    validate_error(
        api_client.get_institution(
            institution_id, make_headers("ops-1", "AUDITOR")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api_client.get_institution(
            institution_id, make_headers("", "ComplianceAnalyst")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api_client.get_institution(
            "00000000-0000-4000-8000-000000000000",
            make_headers("ops-1", "AUDITOR"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    untouched = fixtures.read_institution(institution_id)
    assert untouched["version"] == 1


def test_geocoding_is_open_to_the_officer_and_the_analyst_and_to_no_one_else():
    """Two roles share the attempt; a third is refused, and attempts accumulate.

    PRD: "if the acting role does not appear in the authorised-role list for the
    endpoint being called (see §4), the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "Every attempt increments `geocode_attempts` by 1 regardless of
    outcome, and every attempt advances the borrower's `version` by 1."
    PRD: "An `UNMATCHED` outcome puts the borrower at `GEOCODE_FAILED`, forces
    `in_target_market` to false and `matched_target_market_type` to null, and
    leaves the borrower retryable indefinitely."
    PRD: "A `MATCHED` outcome stores the tract code and puts the borrower at
    `GEOCODED` — this is the path from `UNGEOCODED → GEOCODED`, the retry path
    from `GEOCODE_FAILED → GEOCODED`, and a re-geocode of an already-matched
    borrower as `GEOCODED → GEOCODED` with the tract code overwritten."
    PRD: "an `INVESTMENT_AREA` matches when the borrower's resolved
    `census_tract_code` is one of the market's `census_tract_codes`."

    Design: Corner/rbac/geocoding_is_shared_by_the_officer_and_the_analyst_only
    """
    institution = fixtures.create_institution(ein="210000066")
    institution_id = institution["id"]
    officer = make_institution_officer_headers(institution_id)
    fixtures.create_approved_target_market(institution_id)
    borrower = fixtures.create_borrower(institution_id)
    assert borrower["geocode_state"] == "UNGEOCODED"

    failed = validate_success(
        api_client.geocode_borrower(
            borrower["id"], {"outcome": "UNMATCHED"}, officer
        )
    )
    assert failed["geocode_state"] == "GEOCODE_FAILED"
    assert failed["in_target_market"] is False
    assert failed["matched_target_market_type"] is None
    assert failed["geocode_attempts"] == 1

    matched_payload = {
        "outcome": "MATCHED",
        "census_tract_code": TEST_DEFAULTS["CENSUS_TRACT"],
    }
    validate_error(
        api_client.geocode_borrower(borrower["id"], matched_payload, UNDERWRITER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    resolved = validate_success(
        api_client.geocode_borrower(borrower["id"], matched_payload, ANALYST)
    )
    assert resolved["geocode_state"] == "GEOCODED"
    assert resolved["census_tract_code"] == TEST_DEFAULTS["CENSUS_TRACT"]
    assert resolved["in_target_market"] is True
    assert resolved["matched_target_market_type"] == "INVESTMENT_AREA"
    assert resolved["geocode_attempts"] == 2, (
        "the refused attempt never counted, so only the two accepted ones did"
    )
