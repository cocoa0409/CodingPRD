"""Authentication, authorization, entity-backed ownership, and the per-resource
not-found sweep (PRD §2.1, §2.9, §2.10, §3.2, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    board_loan,
    create_case_payload,
    create_draft_agreement,
    get_case,
    make_borrower_headers,
    open_workout_case,
    register_borrower,
    setup_case_at_marketing_period,
    setup_case_at_terms_negotiation,
    validate_error,
    validate_success,
)

NF_QUOTE = (
    "PRD §2.9: \"Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, "
    "`ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, "
    "`ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, "
    "`ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and "
    "`ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404.\""
)


def test_missing_headers_unauthenticated(api):
    """A request omitting the identity headers fails the authentication rung.

    PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts."
    PRD §2.1: "A request that omits either header, or that names a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/create_loan_missing_auth_headers_returns_unauthenticated
    """
    payload = {
        "loan_number": "LN-R1",
        "unpaid_principal_balance_cents": 20000000,
        "accrued_interest_cents": 0,
        "escrow_advances_cents": 0,
        "foreclosure_fees_cents": 0,
        "note_annual_rate": 0.06,
        "fair_market_value_cents": 18000000,
        "delinquency_days": 90,
    }
    resp = api.create_loan(payload, headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_borrower_cannot_create_case(api, servicing_admin_headers):
    """Opening a case is exclusive to the specialist role; the Borrower role is
    refused even with a valid borrower id.

    PRD §2.1: "A request whose role is not among the roles authorized for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.2: "A `PropertySolutionsSpecialist` opens a workout case with a payload carrying the `loan_id`, the `borrower_id`, and the `program_type` — `DEED_IN_LIEU` or `CASH_FOR_KEYS`."

    Design: Corner/rbac/borrower_cannot_create_case
    """
    loan = board_loan("LN-RB1", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    borrower = register_borrower(full_name="R. One", email="r1@x.com", hardship_type="NONE",
                                 self_reported_condition_grade="A")
    resp = api.create_case(
        create_case_payload(loan["id"], borrower["id"], program_type="DEED_IN_LIEU"),
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_other_borrower_cannot_accept(api, specialist_headers):
    """Entity-backed ownership: a borrower whose id is not the case's borrower_id
    cannot accept its agreement.

    PRD §2.1: "A borrower may counter or accept an agreement only when the header equals the parent case's `borrower_id`, may withdraw only a case whose `borrower_id` matches the header, may read only their own borrower record, and may read only their own cases and those cases' sub-resources."
    PRD §3.5: "The borrower answers with a counter or an acceptance, and both borrower actions enforce the ownership rule of §2.1 — an `X-User-ID` that does not equal the case's `borrower_id` draws `ERR_FORBIDDEN`."

    Design: Corner/rbac/other_borrower_cannot_accept
    """
    bundle = setup_case_at_terms_negotiation(
        loan_number="LN-RB3",
        borrower_overrides={"full_name": "R. Three", "email": "r3@x.com"},
    )
    other = register_borrower(full_name="R. Other", email="ro@x.com", hardship_type="NONE",
                              self_reported_condition_grade="A")
    agreement = create_draft_agreement(bundle["case"]["id"])
    validate_success(api.offer_agreement(agreement["id"], {"offer_valid_days": 10}, specialist_headers))

    resp = api.accept_agreement(agreement["id"], make_borrower_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert validate_success(api.get_agreement(agreement["id"], specialist_headers))["status"] == "OFFERED"


def test_specialist_cannot_grant_marketing_exception(api, specialist_headers):
    """Granting a marketing exception is exclusive to the WorkoutManager.

    PRD §2.1: "A request whose role is not among the roles authorized for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.2: "During the marketing stage a `WorkoutManager` may grant a marketing-period exception, supplying a `reason`; the grant sets `marketing_exception_granted` to true and preserves the reason in `marketing_exception_reason`, incrementing the case's `version`."

    Design: Corner/rbac/specialist_cannot_grant_marketing_exception
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-RB5", with_listing=False)
    resp = api.grant_marketing_exception(
        bundle["case"]["id"], {"reason": "specialist self-grant attempt"}, specialist_headers
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert get_case(bundle["case"]["id"])["marketing_exception_granted"] is False


def test_unknown_agreement_not_found(api, specialist_headers):
    """GET on a nonexistent agreement id returns the agreement 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/unknown_agreement_returns_not_found
    """
    resp = api.get_agreement(NON_EXISTENT_UUID, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value)


def test_get_borrower_not_found(api, servicing_admin_headers):
    """GET on a nonexistent borrower id returns the borrower 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_borrower_not_found_returns_404
    """
    validate_error(api.get_borrower(NON_EXISTENT_UUID, servicing_admin_headers),
                   ApiErrorId.ERR_BORROWER_NOT_FOUND.value)


def test_get_property_not_found(api, servicing_admin_headers):
    """GET on a nonexistent property id returns the property 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_property_not_found_returns_404
    """
    validate_error(api.get_property(NON_EXISTENT_UUID, servicing_admin_headers),
                   ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_get_listing_not_found(api, specialist_headers):
    """GET on a nonexistent listing id returns the listing 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_listing_not_found_returns_404
    """
    validate_error(api.get_listing(NON_EXISTENT_UUID, specialist_headers),
                   ApiErrorId.ERR_LISTING_NOT_FOUND.value)


def test_get_title_commitment_not_found(api, title_officer_headers):
    """GET on a nonexistent commitment id returns the commitment 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_title_commitment_not_found_returns_404
    """
    validate_error(api.get_title_commitment(NON_EXISTENT_UUID, title_officer_headers),
                   ApiErrorId.ERR_TITLE_COMMITMENT_NOT_FOUND.value)


def test_get_appointment_not_found(api, specialist_headers):
    """GET on a nonexistent appointment id returns the appointment 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_appointment_not_found_returns_404
    """
    validate_error(api.get_inspection_appointment(NON_EXISTENT_UUID, specialist_headers),
                   ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value)


def test_get_report_not_found(api, inspector_headers):
    """GET on a nonexistent report id returns the report 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_report_not_found_returns_404
    """
    validate_error(api.get_inspection_report(NON_EXISTENT_UUID, inspector_headers),
                   ApiErrorId.ERR_REPORT_NOT_FOUND.value)


def test_get_disbursement_not_found(api, disbursement_officer_1_headers):
    """GET on a nonexistent disbursement id returns the disbursement 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_disbursement_not_found_returns_404
    """
    validate_error(api.get_disbursement(NON_EXISTENT_UUID, disbursement_officer_1_headers),
                   ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND.value)


def test_get_waiver_not_found(api, legal_counsel_headers):
    """GET on a nonexistent waiver id returns the waiver 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_waiver_not_found_returns_404
    """
    validate_error(api.get_deficiency_waiver(NON_EXISTENT_UUID, legal_counsel_headers),
                   ApiErrorId.ERR_WAIVER_NOT_FOUND.value)


def test_get_recording_not_found(api, legal_counsel_headers):
    """GET on a nonexistent recording id returns the recording 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_recording_not_found_returns_404
    """
    validate_error(api.get_deed_recording(NON_EXISTENT_UUID, legal_counsel_headers),
                   ApiErrorId.ERR_RECORDING_NOT_FOUND.value)


def test_get_eviction_case_not_found(api, legal_counsel_headers):
    """GET on a nonexistent eviction case id returns the eviction 404.

    PRD §2.9: "Each resource has its own not-found error — `ERR_LOAN_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_TITLE_COMMITMENT_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, and `ERR_EVICTION_CASE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors_not_found_sweep/get_eviction_case_not_found_returns_404
    """
    validate_error(api.get_eviction_case(NON_EXISTENT_UUID, legal_counsel_headers),
                   ApiErrorId.ERR_EVICTION_CASE_NOT_FOUND.value)
