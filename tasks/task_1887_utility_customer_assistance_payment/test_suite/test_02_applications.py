"""Assistance applications: income tier variants, review cycle, guards,
supersede, and RBAC."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    assert_application, assert_enrollment,
    create_account, submit_application, begin_review, verify_application,
    create_verified_application, get_enrollment_for_application,
    fresh_account_version, create_application_payload,
    TEST_USERS, make_csr_headers, make_specialist_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


class TestIncomeTierProvisionalVsFinal:
    def test_provisional_tier_uses_annualized_current_month(self, api):
        """PRD §3.2: "At creation the system computes a `provisional_benefit_tier`
        using the `ANNUALIZED_CURRENT_MONTH` income measure — the
        `current_month_income_cents` multiplied by 12, a forward-looking
        annualization — and records that choice in `income_measure_used`."
        PRD §3.2: "one hundred times the income measure is compared against one
        hundred fifty times the guideline for `TIER_1` (an income of exactly 150
        percent of the guideline still qualifies)".

        Design: Difficulty/dual_variant_calc/income_tier_provisional_vs_final
        """
        account = create_account(service_address="100 Elm St")
        app = submit_application(
            account["id"], household_size=2,
            gross_annual_income_cents=4_000_000, current_month_income_cents=250_000)
        # 250000*12 = 3000000 <= 150% of the $21,150.00 household-of-2 guideline
        # (3172500), so the provisional variant lands on TIER_1.
        assert app["provisional_benefit_tier"] == "TIER_1"
        assert app["income_measure_used"] == "ANNUALIZED_CURRENT_MONTH"

    def test_final_tier_uses_annual_gross_and_differs(self, api):
        """PRD §3.2: "Passing those guards, the system recomputes the tier from the
        `ANNUAL_GROSS` measure — the documented `gross_annual_income_cents` —
        against the same guideline scale, and records `income_measure_used` as
        `ANNUAL_GROSS`."
        PRD §3.2: "An eligible result verifies the application, sets `benefit_tier`
        to the computed `TIER_1`, `TIER_2`, or `TIER_3`, stamps the decision time
        as `decided_at`, and creates an AssistanceEnrollment in `PENDING` status
        carrying that tier and its discount."

        Design: Difficulty/dual_variant_calc/income_tier_provisional_vs_final
        """
        account = create_account(service_address="100 Elm St")
        app = submit_application(
            account["id"], household_size=2,
            gross_annual_income_cents=4_000_000, current_month_income_cents=250_000)
        provisional = app["provisional_benefit_tier"]
        begin_review(app["id"])
        decided = verify_application(app["id"])
        # 4000000 > 150% (3172500) but <= 200% (4230000) of the guideline, so the
        # ANNUAL_GROSS variant lands on TIER_2 — different from the provisional.
        assert decided["status"] == "VERIFIED"
        assert decided["benefit_tier"] == "TIER_2"
        assert decided["income_measure_used"] == "ANNUAL_GROSS"
        assert provisional == "TIER_1"
        assert decided["benefit_tier"] != provisional, (
            "the two income variants must diverge on identical inputs here")


class TestDocsRequestCycle:
    def _under_review_app(self, api):
        account = create_account(service_address="7 Cycle Ct")
        app = submit_application(
            account["id"], household_size=1,
            gross_annual_income_cents=1_000_000, current_month_income_cents=90_000)
        begin_review(app["id"])
        return app

    def test_docs_cycle_repeats_with_fresh_documents(self, api):
        """PRD §3.2: "the request sets `docs_requested` to true and resets
        `documents_received` to false, because every new request round demands
        fresh documents. The customer or a representative then supplies them,
        returning the application from `DOCS_PENDING` to `UNDER_REVIEW` with
        `documents_received` set true; this request-and-supply cycle may repeat
        as often as needed."

        Design: Difficulty/non_linear_state_machine/application_docs_request_cycle
        """
        app = self._under_review_app(api)
        for round_no in (1, 2):
            pending = validate_success(api.request_documents(app["id"], SPECIALIST), 200)
            assert pending["status"] == "DOCS_PENDING"
            assert pending["docs_requested"] is True
            assert pending["documents_received"] is False, (
                f"round {round_no}: each new request round demands fresh documents")
            supplied = validate_success(
                api.submit_documents(app["id"], make_csr_headers("csr_1")), 200)
            assert supplied["status"] == "UNDER_REVIEW"
            assert supplied["documents_received"] is True
            assert supplied["docs_requested"] is True

    def test_verify_succeeds_after_two_cycles(self, api):
        """PRD §3.2: "this request-and-supply cycle may repeat as often as needed."
        PRD §3.2: "An eligible result verifies the application, sets `benefit_tier`
        to the computed `TIER_1`, `TIER_2`, or `TIER_3`, stamps the decision time
        as `decided_at`, and creates an AssistanceEnrollment in `PENDING` status
        carrying that tier and its discount."

        Design: Difficulty/non_linear_state_machine/application_docs_request_cycle
        """
        app = self._under_review_app(api)
        for _ in range(2):
            validate_success(api.request_documents(app["id"], SPECIALIST), 200)
            validate_success(api.submit_documents(app["id"], make_csr_headers("csr_1")), 200)
        decided = verify_application(app["id"])
        assert decided["status"] == "VERIFIED"
        # 1000000*100 <= 150*1565000 — comfortably inside the TIER_1 boundary.
        assert decided["benefit_tier"] == "TIER_1"


class TestIncomeBoundaryExactly150Pct:
    def test_exactly_150_percent_qualifies_tier1(self, api):
        """PRD §3.2: "The comparison uses integer cross-multiplication, never
        floating-point division: one hundred times the income measure is compared
        against one hundred fifty times the guideline for `TIER_1` (an income of
        exactly 150 percent of the guideline still qualifies), against two hundred
        times the guideline for `TIER_2`, and against two hundred fifty times for
        `TIER_3`; a measure above the 250 percent line yields `INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/income_exactly_150pct_fpl_qualifies_tier1
        """
        account = create_account(service_address="41 Boundary Blvd")
        # 150% of the $15,650.00 household-of-1 guideline is exactly 2347500 cents.
        app = submit_application(
            account["id"], household_size=1,
            gross_annual_income_cents=2_347_500, current_month_income_cents=100_000)
        begin_review(app["id"])
        decided = verify_application(app["id"])
        assert decided["status"] == "VERIFIED"
        assert decided["benefit_tier"] == "TIER_1", (
            "2347500*100 == 150*1565000 exactly; the inclusive boundary qualifies")

    def test_boundary_verify_creates_pending_tier1_enrollment(self, api):
        """PRD §3.2: "An eligible result verifies the application, sets
        `benefit_tier` to the computed `TIER_1`, `TIER_2`, or `TIER_3`, stamps the
        decision time as `decided_at`, and creates an AssistanceEnrollment in
        `PENDING` status carrying that tier and its discount."
        PRD §3.3: "The enrollment's `discount_pct` is the bill-discount percentage
        keyed to its `tier`: 50 percent for `TIER_1`, 30 percent for `TIER_2`, and
        15 percent for `TIER_3`."

        Design: Difficulty/boundary_precision_check/income_exactly_150pct_fpl_qualifies_tier1
        """
        account = create_account(service_address="41 Boundary Blvd")
        app = create_verified_application(
            account["id"], household_size=1,
            gross_annual_income_cents=2_347_500, current_month_income_cents=100_000)
        enrollment = get_enrollment_for_application(app["id"])
        assert_enrollment(enrollment)
        assert enrollment["tier"] == "TIER_1"
        assert enrollment["discount_pct"] == 50
        assert enrollment["status"] == "PENDING"


def test_application_create_missing_required_field_rejected(api):
    """PRD §3.2: "The intake payload names the `account_id`, the `household_size`
    (between 1 and 12 persons inclusive), the documented
    `gross_annual_income_cents`, the `current_month_income_cents`, and optionally
    the `income_source`".
    PRD §2.8: "4. **Request shape** — required fields are present, types match,
    enum members are valid, and integer ranges hold (`household_size` from 1 to 12
    inclusive, `installment_count` from 2 to 12 inclusive, a payment's
    `amount_cents` strictly positive), else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/application_create_missing_required_field
    """
    account = create_account(service_address="2 Req Rd")
    payload = create_application_payload(account["id"], fresh_account_version(account["id"]))
    del payload["household_size"]
    resp = api.create_application(payload, CSR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_application_initial_state_submitted(api):
    """PRD §3.2: "Creation records `submitted_by_user_id` from the acting header,
    stamps the account's `last_activity_at`, and bumps the account's `version`."
    PRD §3.2: "An `EligibilitySpecialist` begins the review, moving the application
    from `SUBMITTED` to `UNDER_REVIEW`".

    Design: Corner/state_machines/application_initial_state_submitted
    """
    account = create_account(service_address="6 Init Ave")
    app = submit_application(account["id"], submitter_user_id="csr_9")
    assert_application(app)
    assert app["status"] == "SUBMITTED"
    assert app["submitted_by_user_id"] == "csr_9"
    assert app.get("reviewed_by_user_id") is None


def test_application_withdraw_from_verified_rejected(api):
    """PRD §3.2: "An applicant or representative may also withdraw a non-terminal
    application explicitly; withdrawal is available from `SUBMITTED`,
    `UNDER_REVIEW`, or `DOCS_PENDING` and is terminal."
    PRD §2.8: "with `ERR_INVALID_STATE` (HTTP 409) as the generic catch-all for
    transitions that have no more specific error."

    Design: Corner/state_machines/application_withdraw_from_verified_rejected
    """
    account = create_account(service_address="7 Terminal Ter")
    app = create_verified_application(account["id"])
    resp = api.withdraw_application(app["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    stayed = validate_success(api.get_application(app["id"], SPECIALIST), 200)
    assert stayed["status"] == "VERIFIED"


def test_segregation_of_duties_blocks_submitter_review(api):
    """PRD §3.2: "An `EligibilitySpecialist` begins the review, moving the
    application from `SUBMITTED` to `UNDER_REVIEW`; the acting specialist's
    `X-User-ID` must differ from `submitted_by_user_id`, or the request fails
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/sod_verifier_equals_submitter
    """
    account = create_account(service_address="30 Sod St")
    app = submit_application(account["id"], submitter_user_id="dup_1")
    resp = api.begin_review(app["id"], make_specialist_headers("dup_1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    stayed = validate_success(api.get_application(app["id"], SPECIALIST), 200)
    assert stayed["status"] == "SUBMITTED"


def test_documents_outstanding_blocks_verify(api):
    """PRD §3.2: "when `docs_requested` is true and `documents_received` is still
    false, verification is refused with `ERR_DOCUMENTS_OUTSTANDING` (HTTP 422),
    which is what surfaces when verification is attempted from `DOCS_PENDING`
    before documents are resubmitted."

    Design: Corner/validations/documents_outstanding_blocks_verify
    """
    account = create_account(service_address="33 Docs Dr")
    app = submit_application(account["id"])
    begin_review(app["id"])
    validate_success(api.request_documents(app["id"], SPECIALIST), 200)
    resp = api.verify_application(app["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DOCUMENTS_OUTSTANDING)
    stayed = validate_success(api.get_application(app["id"], SPECIALIST), 200)
    assert stayed["status"] == "DOCS_PENDING"


def test_begin_review_twice_rejected(api):
    """PRD §3.2: "Each application action enforces the application's required
    from-state — begin-review from `SUBMITTED`, request-documents from
    `UNDER_REVIEW`, submit-documents from `DOCS_PENDING`, verify from
    `UNDER_REVIEW` or `DOCS_PENDING`, deny from `UNDER_REVIEW` — and a wrong state
    is rejected with `ERR_APPLICATION_NOT_REVIEWABLE` (HTTP 409)."
    PRD §3.2: "Beginning the review records the specialist as `reviewed_by_user_id`."

    Design: Corner/validations/begin_review_twice_rejected
    """
    account = create_account(service_address="50 Twice Ter")
    app = submit_application(account["id"], submitter_user_id="csr_1")
    begin_review(app["id"], reviewer_user_id="es_1")
    resp = api.begin_review(app["id"], make_specialist_headers("es_2"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE)
    stayed = validate_success(api.get_application(app["id"], SPECIALIST), 200)
    assert stayed["status"] == "UNDER_REVIEW"
    assert stayed["reviewed_by_user_id"] == "es_1"


def test_applications_reverse_reachability_and_supersede(api):
    """PRD §3.2: "Filing a new application supersedes any open one — an application
    sitting in `SUBMITTED`, `UNDER_REVIEW`, or `DOCS_PENDING` — moving the older
    one to `WITHDRAWN`."
    PRD §3.2: "The applications listing supports the `account_id` and `status`
    filters."

    Design: Corner/endpoints/applications_reverse_reachability_and_supersede
    """
    account = create_account(service_address="65 Reverse Rd")
    app1 = submit_application(account["id"], gross_annual_income_cents=500_000,
                              current_month_income_cents=40_000)
    app2 = submit_application(account["id"], gross_annual_income_cents=550_000,
                              current_month_income_cents=45_000)
    old = validate_success(api.get_application(app1["id"], CSR), 200)
    new = validate_success(api.get_application(app2["id"], CSR), 200)
    assert old["status"] == "WITHDRAWN", "the superseded open application is withdrawn"
    assert new["status"] == "SUBMITTED"
    rows, meta = validate_paginated(api.list_applications(CSR, params={"account_id": account["id"]}))
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_csr_cannot_verify_application(api):
    """PRD §2.1: "A request whose role is not among the roles permitted for the
    targeted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "The decision lands at verify, again by an `EligibilitySpecialist`
    who is not the submitter."

    Design: Corner/rbac/csr_cannot_verify_application
    """
    account = create_account(service_address="71 Rbac Rd")
    app = submit_application(account["id"])
    begin_review(app["id"])
    resp = api.verify_application(app["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
