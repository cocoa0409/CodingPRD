"""State-machine tests: account posture, withdrawal branching-with-revert,
beneficiary-change branching, schedule resume, Form 1099-Q cyclic spawn."""
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
    approve_beneficiary_change,
    create_scheduled_contribution,
    create_form_1099q,
    issue_form_1099q,
    make_account_owner_headers,
    make_compliance_headers,
    make_custodian_headers,
    make_tax_authority_headers,
    get_account,
)


# ---------------------------------------------------------------------------
# Corner/state_machines
# ---------------------------------------------------------------------------

class TestAccountStateMachine:
    def test_account_initial_state_is_open(self, api):
        """PRD §3.2: "An account moves through three postures. The initial posture is OPEN."

        Design: Corner/state_machines/account_initial_state_is_open
        """
        _donor, _ben, account = setup_donor_beneficiary_account(clock_iso=None)
        assert account["status"] == "OPEN"

    def test_account_close_from_open_with_zero_balance_succeeds(self, api):
        """PRD §3.2: "The AccountOwner may close the account, taking it from OPEN to CLOSED, but
        only when the account is fully drained. All of the following must be true at close
        time: the account_balance_cents is exactly zero, there is no ScheduledContribution for
        the account in ACTIVE status, there is no Withdrawal for the account in either
        SUBMITTED or APPROVED status, and there is no BeneficiaryChange for the account in
        PENDING status."

        Design: Corner/state_machines/account_close_from_open_with_zero_balance_succeeds
        """
        donor, _ben, account = setup_donor_beneficiary_account(clock_iso=None)
        resp = api.close_account(account["id"], make_account_owner_headers(donor["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CLOSED"

    def test_account_close_with_nonzero_balance_blocked(self, api):
        """PRD §3.2: "All of the following must be true at close time: the account_balance_cents
        is exactly zero ... Any of these blocking conditions surfaces as ERR_INVALID_STATE."

        Design: Corner/state_machines/account_close_with_nonzero_balance_blocked
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        create_and_post_contribution(account["id"], 50_000)
        resp = api.close_account(account["id"], make_account_owner_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        # State must be unchanged.
        after = get_account(account["id"])
        assert after["status"] == "OPEN"

    def test_account_restrict_from_restricted_invalid(self, api):
        """PRD §3.2: "A ComplianceOfficer may place an OPEN account on a compliance hold,
        transitioning the account to RESTRICTED; the same officer (or a colleague) later
        returns the account to OPEN by lifting the hold, driving the transition
        RESTRICTED -> OPEN."

        Design: Corner/state_machines/account_restrict_from_restricted_invalid
        """
        _donor, _ben, account = setup_donor_beneficiary_account(clock_iso=None)
        # Place on hold once.
        resp1 = api.restrict_account(account["id"], make_compliance_headers())
        validate_success(resp1, expected_status=200)
        # Second restrict from RESTRICTED is invalid.
        resp2 = api.restrict_account(account["id"], make_compliance_headers())
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_account_closed_terminal_lockdown(self, api):
        """PRD §3.2: "CLOSED is terminal; no further transitions out of CLOSED exist."

        Design: Corner/state_machines/account_closed_terminal_lockdown
        """
        donor, _ben, account = setup_donor_beneficiary_account(clock_iso=None)
        close_resp = api.close_account(account["id"], make_account_owner_headers(donor["id"]))
        validate_success(close_resp, expected_status=200)
        # /restrict on CLOSED must fail.
        resp = api.restrict_account(account["id"], make_compliance_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        after = get_account(account["id"])
        assert after["status"] == "CLOSED"


class TestScheduledContributionStateMachine:
    def test_scheduled_contribution_resume_recomputes_next_run(self, api):
        """PRD §3.3: "Resuming a PAUSED schedule returns it to ACTIVE (requires the account to be
        OPEN) and resets next_run_utc to the current clock plus a fresh cadence interval — the
        previous due time is discarded."

        Design: Corner/state_machines/scheduled_contribution_resume_recomputes_next_run
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        schedule = create_scheduled_contribution(account["id"], donor["id"], 50_000, "MONTHLY")
        # Pause first.
        pause_resp = api.pause_scheduled_contribution(
            schedule["id"], make_account_owner_headers(donor["id"])
        )
        validate_success(pause_resp, expected_status=200)
        # Advance clock to 2026-04-15; resume; next_run_utc must reset to 2026-05-15.
        set_clock("2026-04-15T00:00:00.000Z")
        resume_resp = api.resume_scheduled_contribution(
            schedule["id"], make_account_owner_headers(donor["id"])
        )
        data = validate_success(resume_resp, expected_status=200)
        assert data["status"] == "ACTIVE"
        assert data["next_run_utc"] == "2026-05-15T00:00:00.000Z"


class TestForm1099QCyclicStateMachine:
    def test_form_1099q_cyclic_correct_spawns_reissued(self, api):
        """PRD §3.9: "On correction, the system marks the existing form as CORRECTED (this is a
        marker state — the form is now superseded), then creates a fresh Form1099Q row in the
        same call: the new row's supersedes_form_id is set to the just-corrected form's id, its
        aggregates are recomputed from current DISBURSED Withdrawal data, and its status moves
        through DRAFT to REISSUED in the same operation with issued_at_utc pinned to the
        current clock."

        Design: Corner/state_machines/form_1099q_cyclic_correct_spawns_reissued
        """
        set_clock("2026-05-01T00:00:00.000Z")
        donor, _ben, account = setup_donor_beneficiary_account(clock_iso=None, donor_email="dfc@x.com")
        posted = create_and_post_contribution(account["id"], 500_000)
        a_v1 = posted["version"]
        w = create_draft_withdrawal(account["id"], donor["id"], 100_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        approve_withdrawal(w["id"], a_v1)
        disburse_withdrawal(w["id"])
        form = create_form_1099q(account["id"], 2026)
        set_clock("2027-01-15T00:00:00.000Z")
        issue_form_1099q(form["id"])
        # Correct.
        correct_resp = api.correct_form_1099q(form["id"], make_tax_authority_headers())
        corrected = validate_success(correct_resp, expected_status=200)
        assert corrected["status"] == "CORRECTED"
        # Verify a successor REISSUED form exists with supersedes_form_id == form.id.
        list_resp = api.list_forms_1099q(
            make_tax_authority_headers(),
            params={"account_id": account["id"], "tax_year": 2026},
        )
        body = list_resp.json()
        items = body["data"]
        reissued = [
            f
            for f in items
            if f.get("status") == "REISSUED" and f.get("supersedes_form_id") == form["id"]
        ]
        assert len(reissued) == 1, f"expected exactly one REISSUED successor, got {len(reissued)}"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine
# ---------------------------------------------------------------------------

class TestWithdrawalBranchingWithRevert:
    def test_withdrawal_rejected_to_draft_cycle_increments_rejection_count(self, api):
        """PRD §3.5: "Rejecting a SUBMITTED withdrawal drives it to REJECTED and increments its
        rejection_count by one. The owner may then revise the rejected row, driving it from
        REJECTED back to DRAFT for editing — but only when the rejection_count is strictly less
        than 3."

        Design: Difficulty/non_linear_state_machine/withdrawal_branching_with_revert_rejected_to_draft_cycle
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="d3@x.com")
        create_and_post_contribution(account["id"], 200_000)
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        # Reject.
        reject_resp = api.reject_withdrawal(w["id"], make_compliance_headers())
        validate_success(reject_resp, expected_status=200)
        # Revise back to DRAFT.
        revise_resp = api.revise_withdrawal(w["id"], make_account_owner_headers(donor["id"]))
        revised = validate_success(revise_resp, expected_status=200)
        assert revised["status"] == "DRAFT"
        assert revised["rejection_count"] == 1
        # Submit again.
        resubmit = submit_withdrawal(w["id"], donor["id"])
        assert resubmit["status"] == "SUBMITTED"
        assert resubmit["rejection_count"] == 1

    def test_withdrawal_revert_cycle_full_traversal_to_count_one(self, api):
        """PRD §3.5: "This branching-with-revert loop — DRAFT -> SUBMITTED -> REJECTED -> DRAFT —
        can be traversed up to three times for the same withdrawal row before the row is
        exhausted."

        Design: Difficulty/non_linear_state_machine/withdrawal_branching_with_revert_rejected_to_draft_cycle
        """
        donor, _ben, account = setup_donor_beneficiary_account(donor_email="d3b@x.com")
        create_and_post_contribution(account["id"], 200_000)
        w = create_draft_withdrawal(account["id"], donor["id"], 50_000, "HIGHER_ED_TUITION")
        submit_withdrawal(w["id"], donor["id"])
        api.reject_withdrawal(w["id"], make_compliance_headers())
        api.revise_withdrawal(w["id"], make_account_owner_headers(donor["id"]))
        # After one full reject->revise cycle, rejection_count==1 and status==DRAFT.
        get_resp = api.get_withdrawal(w["id"], make_account_owner_headers(donor["id"]))
        cur = validate_success(get_resp, expected_status=200)
        assert cur["rejection_count"] == 1
        assert cur["status"] == "DRAFT"


class TestBeneficiaryChangeBranching:
    def test_beneficiary_change_approve_mutates_account_beneficiary(self, api):
        """PRD §3.7: "Approval drives it to APPROVED; rejection drives it to REJECTED. Both
        transitions pin decided_at_utc to the current clock. Approval mutates more state than
        rejection: on approval, the account's beneficiary_id is overwritten with the change's
        to_beneficiary_id, and Account.version is incremented along with a refresh of
        updated_at."

        Design: Difficulty/non_linear_state_machine/beneficiary_change_branching_pending_to_approved_or_rejected
        """
        donor, b1, account = setup_donor_beneficiary_account(donor_email="d4@x.com")
        a_v0 = account["version"]
        b2 = create_beneficiary(
            full_name="B2",
            date_of_birth="2010-06-01",
            relationship_class="CHILD",
            federal_tax_id_last4="3333",
        )
        bc = create_beneficiary_change(account["id"], donor["id"], b2["id"])
        approved = approve_beneficiary_change(bc["id"], a_v0)
        assert approved["status"] == "APPROVED"
        # Account.beneficiary_id swapped + version bumped.
        after = get_account(account["id"])
        assert after["beneficiary_id"] == b2["id"]
        assert after["version"] == a_v0 + 1

    def test_beneficiary_change_reject_leaves_account_untouched(self, api):
        """PRD §3.7: "Rejection touches only the change row itself; the account's beneficiary_id
        is left untouched."

        Design: Difficulty/non_linear_state_machine/beneficiary_change_branching_pending_to_approved_or_rejected
        """
        donor, b1, account = setup_donor_beneficiary_account(donor_email="d4r@x.com")
        b2 = create_beneficiary(
            full_name="B2",
            date_of_birth="2010-06-01",
            relationship_class="CHILD",
            federal_tax_id_last4="3333",
        )
        bc = create_beneficiary_change(account["id"], donor["id"], b2["id"])
        reject_resp = api.reject_beneficiary_change(bc["id"], make_compliance_headers())
        rejected = validate_success(reject_resp, expected_status=200)
        assert rejected["status"] == "REJECTED"
        after = get_account(account["id"])
        assert after["beneficiary_id"] == b1["id"]
