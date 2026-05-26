"""Validation-rule tests: uniqueness, family-member rule, revision limit,
insufficient balance, correction window."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_donor_beneficiary_account,
    set_clock,
    create_and_post_contribution,
    create_draft_withdrawal,
    submit_withdrawal,
    approve_withdrawal,
    disburse_withdrawal,
    create_beneficiary,
    create_beneficiary_change,
    create_state_tax_incentive,
    create_form_1099q,
    issue_form_1099q,
    create_donor,
    create_account,
    make_account_owner_headers,
    make_compliance_headers,
    make_custodian_headers,
    make_tax_authority_headers,
    create_donor_payload,
    create_form_1099q_payload,
    create_state_tax_incentive_payload,
    create_beneficiary_change_payload,
    approve_beneficiary_change_payload,
)


# ---------------------------------------------------------------------------
# Corner/validations
# ---------------------------------------------------------------------------

class TestUniqueness:
    def test_duplicate_donor_email_returns_email_taken(self, api):
        """PRD §3.1: "The email must be globally unique with case-insensitive comparison; a
        duplicate is rejected with ERR_EMAIL_TAKEN."

        Design: Corner/validations/duplicate_donor_email_returns_email_taken
        """
        # First create succeeds.
        resp1 = api.create_donor(
            create_donor_payload(full_name="Alice", state_code="CA", federal_tax_id_last4="1111", email="alice@x.com"),
            make_custodian_headers(),
        )
        validate_success(resp1, expected_status=201)
        # Second create with the same email (case-insensitive) is rejected.
        resp2 = api.create_donor(
            create_donor_payload(full_name="Alice 2", state_code="NY", federal_tax_id_last4="2222", email="ALICE@x.com"),
            make_custodian_headers(),
        )
        validate_error(resp2, ApiErrorId.ERR_EMAIL_TAKEN.value, expected_status=409)

    def test_state_tax_incentive_uniqueness_per_donor_tax_year(self, api):
        """PRD §3.8: "The combination of (donor_id, tax_year) is uniquely keyed; a second creation
        for the same pair is rejected with ERR_INCENTIVE_ALREADY_EXISTS."

        Design: Corner/validations/state_tax_incentive_uniqueness_per_donor_tax_year
        """
        donor = create_donor(email="duq@x.com")
        # First incentive succeeds.
        resp1 = api.create_state_tax_incentive(
            create_state_tax_incentive_payload(donor["id"], 2026), make_custodian_headers()
        )
        validate_success(resp1, expected_status=201)
        # Duplicate rejected.
        resp2 = api.create_state_tax_incentive(
            create_state_tax_incentive_payload(donor["id"], 2026), make_custodian_headers()
        )
        validate_error(resp2, ApiErrorId.ERR_INCENTIVE_ALREADY_EXISTS.value, expected_status=409)

    def test_form_1099q_uniqueness_per_account_tax_year(self, api):
        """PRD §3.9: "The (account_id, tax_year, status IN {DRAFT, ISSUED, REISSUED}) combination
        is uniquely keyed — a second DRAFT for the same (account_id, tax_year) is rejected with
        ERR_FORM_ALREADY_EXISTS unless the prior form has already moved to CORRECTED."

        Design: Corner/validations/form_1099q_uniqueness_per_account_tax_year
        """
        _donor, _ben, account = setup_donor_beneficiary_account(
            clock_iso=None, donor_email="dfq@x.com"
        )
        resp1 = api.create_form_1099q(
            create_form_1099q_payload(account["id"], 2026), make_tax_authority_headers()
        )
        validate_success(resp1, expected_status=201)
        # Second create for same (account_id, tax_year) while first is DRAFT.
        resp2 = api.create_form_1099q(
            create_form_1099q_payload(account["id"], 2026), make_tax_authority_headers()
        )
        validate_error(resp2, ApiErrorId.ERR_FORM_ALREADY_EXISTS.value, expected_status=409)


class TestBusinessRuleViolations:
    def test_beneficiary_change_to_other_family_rejected(self, api):
        """PRD §3.7: "The pinned to_relationship_class must be one of SELF, CHILD, SIBLING, or
        FIRST_COUSIN; a value of OTHER is rejected with ERR_BENEFICIARY_NOT_FAMILY_MEMBER,
        which is the IRS family-member rule applied at approve time (the same rule also rejects
        creation of a change whose target relationship class is OTHER)."

        Design: Corner/validations/beneficiary_change_to_other_family_rejected
        """
        donor, _b1, account = setup_donor_beneficiary_account(donor_email="dbo@x.com")
        a_v = account["version"]
        b2 = create_beneficiary(
            full_name="BO2",
            date_of_birth="1990-01-01",
            relationship_class="OTHER",
            federal_tax_id_last4="3333",
        )
        bc_resp = api.create_beneficiary_change(
            create_beneficiary_change_payload(account["id"], b2["id"]),
            make_account_owner_headers(donor["id"]),
        )
        # Per PRD §3.7 the same rule also rejects creation; if the impl allows creation,
        # the rule MUST fire at /approve. We test the /approve trigger explicitly because
        # that is the path uniquely committed by the rule. If creation already rejects we
        # short-circuit.
        if bc_resp.status_code in (200, 201):
            bc = bc_resp.json()["data"]
            approve_resp = api.approve_beneficiary_change(
                bc["id"], approve_beneficiary_change_payload(a_v), make_compliance_headers()
            )
            validate_error(
                approve_resp,
                ApiErrorId.ERR_BENEFICIARY_NOT_FAMILY_MEMBER.value,
                expected_status=422,
            )
        else:
            validate_error(
                bc_resp,
                ApiErrorId.ERR_BENEFICIARY_NOT_FAMILY_MEMBER.value,
                expected_status=422,
            )

    def test_form_1099q_correction_window_closed(self, api):
        """PRD §3.9: "The correction window is bounded: the form's tax_year must be no earlier
        than three calendar years before the current clock year (inclusive — that is, tax_year
        must be at least the current clock year minus 3); an attempt to correct an older form
        is rejected with ERR_FORM_CORRECTION_WINDOW_CLOSED."

        Design: Corner/validations/form_1099q_correction_window_closed
        """
        set_clock("2022-05-01T00:00:00.000Z")
        donor, _ben, account = setup_donor_beneficiary_account(clock_iso=None, donor_email="dcw@x.com")
        posted = create_and_post_contribution(account["id"], 500_000)
        w = create_draft_withdrawal(account["id"], donor["id"], 100_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        approve_withdrawal(w["id"], posted["version"])
        disburse_withdrawal(w["id"])
        form = create_form_1099q(account["id"], 2022)
        set_clock("2023-01-15T00:00:00.000Z")
        issue_form_1099q(form["id"])
        # Now jump to 2027 -> tax_year 2022 is current_year - 5, beyond the 3-year window.
        set_clock("2027-06-01T00:00:00.000Z")
        resp = api.correct_form_1099q(form["id"], make_tax_authority_headers())
        validate_error(
            resp, ApiErrorId.ERR_FORM_CORRECTION_WINDOW_CLOSED.value, expected_status=422
        )

    def test_withdrawal_revision_limit_exceeded(self, api):
        """PRD §3.5: "The owner may then revise the rejected row, driving it from REJECTED back to
        DRAFT for editing — but only when the rejection_count is strictly less than 3. A fourth
        revise attempt (when rejection_count is already 3 or higher) is rejected with
        ERR_REVISION_LIMIT_EXCEEDED."

        Design: Corner/validations/withdrawal_revision_limit_exceeded
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="drl@x.com")
        create_and_post_contribution(account["id"], 200_000)
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        # Cycle 3 times: submit, reject, revise, submit, reject, revise, submit, reject.
        # After the 3rd reject, rejection_count == 3, status == REJECTED.
        owner_headers = make_account_owner_headers(donor["id"])
        compliance_headers = make_compliance_headers()
        submit_withdrawal(w["id"], donor["id"])
        api.reject_withdrawal(w["id"], compliance_headers)
        api.revise_withdrawal(w["id"], owner_headers)
        submit_withdrawal(w["id"], donor["id"])
        api.reject_withdrawal(w["id"], compliance_headers)
        api.revise_withdrawal(w["id"], owner_headers)
        submit_withdrawal(w["id"], donor["id"])
        api.reject_withdrawal(w["id"], compliance_headers)
        # Fourth /revise attempt with rejection_count == 3.
        resp = api.revise_withdrawal(w["id"], owner_headers)
        validate_error(
            resp, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value, expected_status=409
        )
        # Status stays REJECTED.
        cur = api.get_withdrawal(w["id"], owner_headers).json()["data"]
        assert cur["status"] == "REJECTED"
        assert cur["rejection_count"] == 3

    def test_withdrawal_insufficient_balance_at_submit(self, api):
        """PRD §3.5: "Submitting the draft drives it to SUBMITTED. The submit step requires the
        account to be in OPEN status; it must not be in flight with any PENDING
        BeneficiaryChange (the account's beneficiary is allowed to change only while no
        withdrawal is mid-review); and the withdrawal's amount_cents must be no greater than
        the account's current account_balance_cents, otherwise ERR_INSUFFICIENT_BALANCE is
        returned."

        Design: Corner/validations/withdrawal_insufficient_balance_at_submit
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="dib@x.com")
        create_and_post_contribution(account["id"], 100_000)
        w = create_draft_withdrawal(account["id"], donor["id"], 200_000, "HIGHER_ED_TUITION")
        resp = api.submit_withdrawal(w["id"], make_account_owner_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value, expected_status=422)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict
# ---------------------------------------------------------------------------

class TestValidationPriorityConflicts:
    def test_state_beats_business_fiscal_on_withdrawal_approve_with_draft_status(self, api):
        """PRD §2.8: "Within each tier, ordering follows the priority numbers shown above. Where a
        single endpoint is guarded by checks from more than one tier, the tier order is
        authoritative: a state-precondition failure surfaces before an OCC-stale failure, an
        OCC-stale failure surfaces before a balance failure, and a balance failure surfaces
        before a request-shape failure."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_revise_after_three_rejections
        """
        # Per the design notes, the realised scenario is: withdrawal in DRAFT (not SUBMITTED)
        # AND amount_cents > account.account_balance_cents on /approve.
        # State precondition (priority 6) fires before insufficient balance (priority 15).
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="d7@x.com")
        posted = create_and_post_contribution(account["id"], 100_000)
        a_v = posted["version"]
        # Withdrawal stays in DRAFT (never submitted) AND amount > balance.
        w = create_draft_withdrawal(account["id"], donor["id"], 500_000, "HIGHER_ED_TUITION")
        # /approve on a DRAFT withdrawal: status precondition (SUBMITTED) fails first.
        resp = api.approve_withdrawal(
            w["id"], {"expected_account_version": a_v}, make_compliance_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_auth_segregation_beats_state_occ_on_beneficiary_change_approve(self, api):
        """PRD §2.1: "the same X-User-ID must not both create a BeneficiaryChange (initial PENDING)
        and later approve it (PENDING -> APPROVED). A violation is rejected with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403). This rule sits above existence checks but below
        the basic authentication and authorization checks in priority order."
        PRD §2.8: "Segregation-of-duties (ERR_SEGREGATION_OF_DUTIES) on the two approve endpoints
        where it applies."

        Design: Difficulty/priority_pair_validation_conflict/auth_segregation_beats_state_occ_on_beneficiary_change_approve
        """
        donor, b1, account = setup_donor_beneficiary_account(donor_email="d8@x.com")
        a_v0 = account["version"]
        b2 = create_beneficiary(
            full_name="B8b",
            date_of_birth="2010-06-01",
            relationship_class="CHILD",
            federal_tax_id_last4="3333",
        )
        # Donor creates the change (AccountOwner with X-User-ID == donor.id).
        bc = create_beneficiary_change(account["id"], donor["id"], b2["id"])
        # Bump Account.version via restrict + release so OCC would also be stale.
        api.restrict_account(account["id"], make_compliance_headers())
        api.release_account(account["id"], make_compliance_headers())
        # Approver uses ComplianceOfficer role with SAME X-User-ID as the change creator.
        from prd_bench_local_runner.testing import build_user_headers
        same_user_compliance_headers = build_user_headers(donor["id"], "ComplianceOfficer")
        resp = api.approve_beneficiary_change(
            bc["id"], {"expected_account_version": a_v0}, same_user_compliance_headers
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
        )


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency
# ---------------------------------------------------------------------------

class TestCrossEntityStateDependencies:
    def test_withdrawal_submit_blocked_by_pending_beneficiary_change(self, api):
        """PRD §3.5: "Submitting the draft drives it to SUBMITTED. The submit step requires the
        account to be in OPEN status; it must not be in flight with any PENDING
        BeneficiaryChange (the account's beneficiary is allowed to change only while no
        withdrawal is mid-review); and the withdrawal's amount_cents must be no greater than
        the account's current account_balance_cents, otherwise ERR_INSUFFICIENT_BALANCE is
        returned."

        Design: Difficulty/cross_entity_state_dependency/withdrawal_submit_blocked_by_pending_beneficiary_change
        """
        donor, _b1, account = setup_donor_beneficiary_account(donor_email="d11@x.com")
        create_and_post_contribution(account["id"], 200_000)
        b2 = create_beneficiary(
            full_name="B11b",
            date_of_birth="2010-06-01",
            relationship_class="SIBLING",
            federal_tax_id_last4="3333",
        )
        # Open a PENDING BeneficiaryChange.
        create_beneficiary_change(account["id"], donor["id"], b2["id"])
        # Now attempt to submit a withdrawal.
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        resp = api.submit_withdrawal(w["id"], make_account_owner_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        cur = api.get_withdrawal(w["id"], make_account_owner_headers(donor["id"])).json()["data"]
        assert cur["status"] == "DRAFT"

    def test_withdrawal_submit_blocked_by_account_restricted_status(self, api):
        """PRD §3.5: "Submitting the draft drives it to SUBMITTED. The submit step requires the
        account to be in OPEN status"

        Design: Difficulty/cross_entity_state_dependency/withdrawal_submit_blocked_by_account_restricted_status
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="d12@x.com")
        create_and_post_contribution(account["id"], 200_000)
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        # Put account on hold.
        api.restrict_account(account["id"], make_compliance_headers())
        resp = api.submit_withdrawal(w["id"], make_account_owner_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        cur = api.get_withdrawal(w["id"], make_account_owner_headers(donor["id"])).json()["data"]
        assert cur["status"] == "DRAFT"
