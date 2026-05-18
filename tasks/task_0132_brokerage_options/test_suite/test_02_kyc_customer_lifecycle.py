"""Customer onboarding + KYC submission + W-9 + KYC decision lifecycle.

Coverage targets (PRD §3.1):
- Customer registration shape.
- KYC submission: address_country == 'US' gate.
- KYC submission: age >= 18 gate.
- KYC submission: W-9 signed_name matches Customer.legal_name (case-
  insensitive, trimmed).
- KYC decision (VERIFY): cascades Customer.kyc_status, w9_collected,
  Account.status, trading_posture.
- KYC decision (REJECT): cyclic revision loop back to PENDING_KYC.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_customer,
    assert_kyc_submission,
    create_account,
    create_account_payload,
    create_customer,
    create_customer_payload,
    kyc_decision_payload,
    make_customer_headers,
    setup_approved_customer_and_account,
    submit_kyc,
    submit_kyc_payload,
    today_utc,
    validate_error,
    validate_success,
    verify_kyc,
    years_ago_dob,
)


# ===========================================================================
# Customer creation — PRD §3.1
# ===========================================================================
class TestCustomerCreation:
    """PRD §3.1: 'The new Customer row is created with kyc_status set to
    NOT_STARTED and w9_collected set to false.'"""

    def test_create_customer_initial_state(self, api):
        """PRD §3.1: "The new Customer row is created with kyc_status
        set to NOT_STARTED and w9_collected set to false."

        Claim: a newly-created Customer has kyc_status=NOT_STARTED and
        w9_collected=false.
        """
        resp = api.create_customer(
            create_customer_payload(),
            TEST_USERS["platform_admin_headers"],
        )
        customer = validate_success(resp, expected_status=201)
        assert_customer(customer)
        assert customer["kyc_status"] == "NOT_STARTED"
        assert customer["w9_collected"] is False
        assert customer["version"] == 1


# ===========================================================================
# KYC eligibility — country gate (PRD §3.1)
# ===========================================================================
class TestKycCountryEligibility:
    """PRD §3.1: 'address_country must equal US exactly — only US
    persons are supported, and any other country is rejected with
    ERR_KYC_INELIGIBLE_COUNTRY at HTTP 422'."""

    @pytest.mark.parametrize("country", ["CA", "MX", "GB", "FR", "DE"])
    def test_non_us_country_rejected(self, api, country):
        """PRD §3.1: "address_country must equal US exactly — only US
        persons are supported, and any other country is rejected with
        ERR_KYC_INELIGIBLE_COUNTRY at HTTP 422".

        Claim: any non-US address_country -> ERR_KYC_INELIGIBLE_COUNTRY
        / 422.
        """
        customer = create_customer()
        create_account(customer=customer)
        headers = make_customer_headers(customer["id"])
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9=customer["legal_name"],
                address_country=country,
            ),
            headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_KYC_INELIGIBLE_COUNTRY.value,
        )


# ===========================================================================
# KYC eligibility — age gate (PRD §3.1)
# ===========================================================================
class TestKycAgeEligibility:
    """PRD §3.1: 'the customer's age, derived from date_of_birth, must
    be at least 18 years at the moment of submission, with anything
    younger rejected with ERR_KYC_AGE_INELIGIBLE at HTTP 422.'"""

    def test_seventeen_year_old_rejected(self, api):
        """PRD §3.1: "the customer's age, derived from date_of_birth,
        must be at least 18 years at the moment of submission, with
        anything younger rejected with ERR_KYC_AGE_INELIGIBLE at HTTP
        422."

        Claim: customer with age=17 -> ERR_KYC_AGE_INELIGIBLE / 422.
        """
        customer = create_customer(date_of_birth=years_ago_dob(17))
        create_account(customer=customer)
        headers = make_customer_headers(customer["id"])
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9=customer["legal_name"],
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_KYC_AGE_INELIGIBLE.value)

    def test_exactly_eighteen_accepted(self, api):
        """PRD §3.1: "the customer's age, derived from date_of_birth,
        must be at least 18 years at the moment of submission".

        Claim: age == 18 exactly passes the age gate (boundary).
        """
        customer = create_customer(date_of_birth=years_ago_dob(18))
        create_account(customer=customer)
        headers = make_customer_headers(customer["id"])
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9=customer["legal_name"],
            ),
            headers,
        )
        # 18 exactly passes; expect 201 KYCSubmission created.
        sub = validate_success(resp, expected_status=201)
        assert_kyc_submission(sub)
        assert sub["status"] == "PENDING"


# ===========================================================================
# W-9 name match — PRD §3.1
# ===========================================================================
class TestW9NameMatch:
    """PRD §3.1: 'w9_signed_name must equal Customer.legal_name after
    trimming surrounding whitespace and comparing case-insensitively;
    any mismatch is rejected with ERR_W9_NAME_MISMATCH at HTTP 422.'"""

    def test_w9_mismatch_rejected(self, api):
        """PRD §3.1: "w9_signed_name must equal Customer.legal_name
        after trimming surrounding whitespace and comparing case-
        insensitively; any mismatch is rejected with
        ERR_W9_NAME_MISMATCH at HTTP 422."

        Claim: w9_signed_name materially different from legal_name ->
        ERR_W9_NAME_MISMATCH / 422.
        """
        customer = create_customer(legal_name="Jane Q Doe")
        create_account(customer=customer)
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9="Jane Q Doe",
                w9_signed_name="John X Roe",
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_W9_NAME_MISMATCH.value)

    def test_w9_case_insensitive_match_accepted(self, api):
        """PRD §3.1: "w9_signed_name must equal Customer.legal_name
        after trimming surrounding whitespace and comparing case-
        insensitively".

        Claim: case-differing but otherwise matching W-9 name passes.
        """
        customer = create_customer(legal_name="Jane Q Doe")
        create_account(customer=customer)
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9="Jane Q Doe",
                w9_signed_name="JANE Q DOE",
            ),
            make_customer_headers(customer["id"]),
        )
        sub = validate_success(resp, expected_status=201)
        assert sub["status"] == "PENDING"

    def test_w9_trimmed_match_accepted(self, api):
        """PRD §3.1: "w9_signed_name must equal Customer.legal_name
        after trimming surrounding whitespace and comparing case-
        insensitively".

        Claim: whitespace-padded W-9 name still matches.
        """
        customer = create_customer(legal_name="Alex Smith")
        create_account(customer=customer)
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9="Alex Smith",
                w9_signed_name="  Alex Smith  ",
            ),
            make_customer_headers(customer["id"]),
        )
        sub = validate_success(resp, expected_status=201)
        assert sub["status"] == "PENDING"


# ===========================================================================
# KYC submission side-effects (PRD §3.1)
# ===========================================================================
class TestKycSubmissionSideEffects:
    """PRD §3.1: 'On success, a KYCSubmission row is inserted with its
    own status set to PENDING ... Customer.kyc_status advances to
    PENDING, and the Account advances from PENDING_KYC to KYC_REVIEW.'"""

    def test_kyc_submission_advances_customer_and_account(self, api):
        """PRD §3.1: "On success, a KYCSubmission row is inserted with
        its own status set to PENDING and its rejection_reason left
        null, Customer.kyc_status advances to PENDING, and the Account
        advances from PENDING_KYC to KYC_REVIEW."

        Claim: after a successful KYC submission:
        - KYCSubmission.status == PENDING
        - Customer.kyc_status == PENDING
        - Account.status == KYC_REVIEW
        """
        customer = create_customer()
        account = create_account(customer=customer)
        assert account["status"] == "PENDING_KYC"

        submission = submit_kyc(customer)
        assert submission["status"] == "PENDING"
        assert submission["rejection_reason"] is None

        # Re-fetch customer and account.
        cust = validate_success(api.get_customer(
            customer["id"], TEST_USERS["compliance_headers"],
        ))
        assert cust["kyc_status"] == "PENDING"

        acct = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert acct["status"] == "KYC_REVIEW"


# ===========================================================================
# KYC decision — VERIFY transition (PRD §3.1)
# ===========================================================================
class TestKycDecisionVerify:
    """PRD §3.1: 'Verification advances KYCSubmission.status to VERIFIED,
    sets Customer.kyc_status to VERIFIED, sets Customer.w9_collected to
    true, transitions the Account from KYC_REVIEW to APPROVED, and
    flips trading_posture from RESTRICTED to OPEN'."""

    def test_verify_cascades_to_account_open(self, api):
        """PRD §3.1: "Verification advances KYCSubmission.status to
        VERIFIED, sets Customer.kyc_status to VERIFIED, sets
        Customer.w9_collected to true, transitions the Account from
        KYC_REVIEW to APPROVED, and flips trading_posture from
        RESTRICTED to OPEN — the latter being the system-driven
        transition that finally permits trading."

        Claim: VERIFY decision cascades all five side-effects.
        """
        customer = create_customer()
        account = create_account(customer=customer)
        submit_kyc(customer)
        verified_sub = verify_kyc(customer["id"])
        assert verified_sub["status"] == "VERIFIED"

        cust = validate_success(api.get_customer(
            customer["id"], TEST_USERS["compliance_headers"],
        ))
        assert cust["kyc_status"] == "VERIFIED"
        assert cust["w9_collected"] is True

        acct = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert acct["status"] == "APPROVED"
        assert acct["trading_posture"] == "OPEN"


# ===========================================================================
# KYC decision — REJECT cyclic loop (PRD §3.1)
# ===========================================================================
class TestKycDecisionReject:
    """PRD §3.1: 'Rejection ... walks the Account back to PENDING_KYC
    so the customer can resubmit — this is a deliberate cyclic
    transition supporting an unbounded revision loop until either
    verification or account closure.'"""

    def test_reject_reverts_account_to_pending_kyc(self, api):
        """PRD §3.1: "Rejection sets KYCSubmission.status to REJECTED,
        records the populated rejection_reason, sets
        Customer.kyc_status to REJECTED, and walks the Account back to
        PENDING_KYC so the customer can resubmit — this is a deliberate
        cyclic transition supporting an unbounded revision loop until
        either verification or account closure."

        Claim: REJECT decision cascades: KYCSubmission -> REJECTED,
        Customer.kyc_status -> REJECTED, Account.status -> PENDING_KYC.
        """
        customer = create_customer()
        account = create_account(customer=customer)
        submit_kyc(customer)
        resp = api.kyc_decision(
            customer["id"],
            kyc_decision_payload(decision="REJECT"),
            TEST_USERS["compliance_headers"],
        )
        sub = validate_success(resp)
        assert sub["status"] == "REJECTED"

        cust = validate_success(api.get_customer(
            customer["id"], TEST_USERS["compliance_headers"],
        ))
        assert cust["kyc_status"] == "REJECTED"

        acct = validate_success(api.get_account(
            account["id"], make_customer_headers(customer["id"]),
        ))
        assert acct["status"] == "PENDING_KYC"

    def test_resubmit_after_reject_succeeds(self, api):
        """PRD §3.1: "KYC submission requires that the customer is
        either submitting for the first time (Customer.kyc_status equal
        to NOT_STARTED) or is resubmitting after a prior rejection
        (most recent KYCSubmission.status equal to REJECTED)".

        Claim: a Customer with a prior REJECTED submission may
        resubmit; the new submission is accepted.
        """
        customer = create_customer()
        create_account(customer=customer)
        submit_kyc(customer)
        # Reject the first submission.
        resp = api.kyc_decision(
            customer["id"],
            kyc_decision_payload(decision="REJECT"),
            TEST_USERS["compliance_headers"],
        )
        validate_success(resp)
        # Resubmit.
        resp = api.submit_kyc(
            customer["id"],
            submit_kyc_payload(
                legal_name_for_w9=customer["legal_name"],
            ),
            make_customer_headers(customer["id"]),
        )
        sub = validate_success(resp, expected_status=201)
        assert sub["status"] == "PENDING"
