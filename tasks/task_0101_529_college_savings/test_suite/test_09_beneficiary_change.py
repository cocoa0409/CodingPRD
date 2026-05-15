"""BeneficiaryChangeRequest submit/approve/reject (PRD §3.6).
Includes the difficulty-design `beneficiary_change_preserves_balances`
instance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    approve_beneficiary_change,
    assert_account_balance_invariant,
    assert_beneficiary_change_request,
    create_beneficiary,
    create_donor,
    create_beneficiary_change_request_payload,
    create_state_rule,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    open_account,
    reject_beneficiary_change_request_payload,
    restrict_account,
    settle_lump_sum,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    submit_beneficiary_change,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submit
# ===========================================================================
class TestSubmitBeneficiaryChange:

    def test_submit_captures_current_beneficiary_snapshot(self, api):
        """PRD §3.6: "the system creates a BeneficiaryChangeRequest in
        status SUBMITTED and captures a current_beneficiary_id
        snapshot from the account's beneficiary_id at submit time."

        Claim: BCR.current_beneficiary_id equals
        Account.beneficiary_id at submit time.
        """
        donor, current_ben, account = setup_donor_beneficiary_account()
        new_ben = create_beneficiary(relationship_family_code="SIBLING")
        res = api.create_beneficiary_change_request(
            account["id"],
            create_beneficiary_change_request_payload(
                proposed_beneficiary_id=new_ben["id"],
            ),
            make_donor_headers(donor["id"]),
        )
        bcr = validate_success(res, 201)
        assert_beneficiary_change_request(bcr)
        assert bcr["status"] == "SUBMITTED"
        assert bcr["current_beneficiary_id"] == current_ben["id"]
        assert bcr["proposed_beneficiary_id"] == new_ben["id"]

    def test_only_donor_can_submit(self, api, admin_headers):
        """PRD §4 endpoint table: POST
        /accounts/{id}/beneficiary-change-requests authorized role is
        Donor.

        Claim: PlanAdministrator cannot submit a beneficiary change →
        ERR_FORBIDDEN.
        """
        _donor, _ben, account = setup_donor_beneficiary_account()
        new_ben = create_beneficiary(relationship_family_code="SIBLING")
        res = api.create_beneficiary_change_request(
            account["id"],
            create_beneficiary_change_request_payload(
                proposed_beneficiary_id=new_ben["id"],
            ),
            admin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# Approve — happy path + identity + generation skip
# ===========================================================================
class TestApproveBeneficiaryChange:

    def test_approve_permitted_relationship(self, api, admin_headers):
        """PRD §3.6: "On a successful approval, the account's
        beneficiary_id is set to the request's proposed_beneficiary_id."

        Claim: an approved BCR mutates Account.beneficiary_id to the
        proposed beneficiary.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        new_ben = create_beneficiary(relationship_family_code="SIBLING")
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=new_ben,
        )
        res = api.approve_beneficiary_change_request(
            bcr["id"], admin_headers,
        )
        approved = validate_success(res, 200)
        assert approved["status"] == "APPROVED"
        # Re-read account.
        account_after = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert account_after["beneficiary_id"] == new_ben["id"]

    def test_approve_preserves_balances(self, api, admin_headers):
        """PRD §2.9: "approving a beneficiary change mutates only
        beneficiary_id on the account; basis_balance_cents,
        earnings_balance_cents, and total_balance_cents are unchanged.
        The new beneficiary inherits the existing balance composition;
        no basis/earnings reset occurs."
        PRD §3.6: "no other account field is mutated —
        basis_balance_cents, earnings_balance_cents, and
        total_balance_cents are conserved exactly, and
        state_rule_version_at_open and lifetime_contribution_cap_cents
        are untouched."

        Claim: post-approval Account balances (basis, earnings, total)
        and pinned fields (lifetime cap, state_rule_version_at_open)
        are unchanged.

        # difficulty: compensating_invariant/beneficiary_change_preserves_balances
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        new_ben = create_beneficiary(relationship_family_code="SIBLING")
        before = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=new_ben,
        )
        approve_beneficiary_change(bcr["id"])
        after = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        # PRD §3.6: balances + pinned fields conserved.
        assert after["basis_balance_cents"] == before["basis_balance_cents"]
        assert after["earnings_balance_cents"] == (
            before["earnings_balance_cents"]
        )
        assert after["total_balance_cents"] == before["total_balance_cents"]
        assert after["lifetime_contribution_cap_cents"] == (
            before["lifetime_contribution_cap_cents"]
        )
        assert after["state_rule_version_at_open"] == (
            before["state_rule_version_at_open"]
        )
        # Only beneficiary_id moved.
        assert after["beneficiary_id"] == new_ben["id"]
        assert_account_balance_invariant(after)

    def test_approve_identical_beneficiary_rejected(self, api, admin_headers):
        """PRD §3.6: "the proposed beneficiary's id must not equal the
        current beneficiary_id (else
        ERR_BENEFICIARY_IDENTICAL_TO_CURRENT)."

        Claim: submitting + approving a BCR with
        proposed_beneficiary_id == current beneficiary →
        ERR_BENEFICIARY_IDENTICAL_TO_CURRENT.

        Note: submit may succeed (the no-op is only forbidden at
        approval per PRD), so we make the explicit approve call.
        """
        donor, current_ben, account = setup_donor_beneficiary_account()
        # Attempt submit with the same beneficiary id; the submit
        # validation may already reject, but the approval-time rule is
        # the one PRD §3.6 names explicitly.
        res_submit = api.create_beneficiary_change_request(
            account["id"],
            create_beneficiary_change_request_payload(
                proposed_beneficiary_id=current_ben["id"],
            ),
            make_donor_headers(donor["id"]),
        )
        if res_submit.status_code == 201:
            bcr = res_submit.json()["data"]
            res_approve = api.approve_beneficiary_change_request(
                bcr["id"], admin_headers,
            )
            validate_error(res_approve, "ERR_BENEFICIARY_IDENTICAL_TO_CURRENT")
        else:
            # The implementation may instead reject at submit time;
            # either way, the error_id must be the same.
            validate_error(
                res_submit, "ERR_BENEFICIARY_IDENTICAL_TO_CURRENT",
            )

    def test_approve_self_relationship_rejected(self, api, admin_headers):
        """PRD §3.6: "the proposed beneficiary's
        relationship_family_code must be one of CHILD, SIBLING,
        NIECE_NEPHEW, COUSIN, FIRST_COUSIN_ONCE_REMOVED, SPOUSE,
        IN_LAW, or PARENT — SELF is not in the permissible set for a
        change — and otherwise the request is rejected with
        ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN."

        Claim: proposing a beneficiary with relationship_family_code=
        SELF → ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        new_ben = create_beneficiary(relationship_family_code="SELF")
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=new_ben,
        )
        res = api.approve_beneficiary_change_request(
            bcr["id"], admin_headers,
        )
        validate_error(res, "ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN")

    @pytest.mark.parametrize("forbidden_relationship", ["PARENT", "IN_LAW"])
    def test_approve_generation_skip_rejected(
        self, api, admin_headers, forbidden_relationship,
    ):
        """PRD §3.6: "when the proposed beneficiary's relationship is
        more than one generation removed upward from the current
        beneficiary (the canonical example being a change from a CHILD
        beneficiary to a PARENT or IN_LAW beneficiary), the request is
        rejected with ERR_BENEFICIARY_GENERATION_SKIP."

        Claim: from a CHILD current beneficiary, proposing PARENT or
        IN_LAW → ERR_BENEFICIARY_GENERATION_SKIP.
        """
        # PRD §3.6: the current beneficiary in setup_donor_beneficiary_account
        # is created with relationship_family_code=CHILD.
        donor, _ben, account = setup_donor_beneficiary_account(
            relationship_family_code="CHILD",
        )
        new_ben = create_beneficiary(
            relationship_family_code=forbidden_relationship,
        )
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=new_ben,
        )
        res = api.approve_beneficiary_change_request(
            bcr["id"], admin_headers,
        )
        validate_error(res, "ERR_BENEFICIARY_GENERATION_SKIP")

    def test_approve_requires_account_open(self, api, admin_headers):
        """PRD §3.6: "Approval requires the account to be OPEN."

        Claim: restrict the account, then attempt approve →
        ERR_ACCOUNT_RESTRICTED.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        new_ben = create_beneficiary(relationship_family_code="SIBLING")
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=new_ben,
        )
        restrict_account(account["id"])
        res = api.approve_beneficiary_change_request(
            bcr["id"], admin_headers,
        )
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")


# ===========================================================================
# Reject
# ===========================================================================
class TestRejectBeneficiaryChange:

    def test_reject_submitted_request_stamps_reason(self, api, admin_headers):
        """PRD §3.6: "A PlanAdministrator may instead reject a SUBMITTED
        request, transitioning its status from SUBMITTED to REJECTED
        and stamping rejection_reason ... Rejection mutates no account
        field."

        Claim: reject on SUBMITTED → status REJECTED with
        rejection_reason stamped; Account.beneficiary_id unchanged.
        """
        donor, current_ben, account = setup_donor_beneficiary_account()
        new_ben = create_beneficiary(relationship_family_code="SIBLING")
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=new_ben,
        )
        res = api.reject_beneficiary_change_request(
            bcr["id"],
            reject_beneficiary_change_request_payload(
                rejection_reason="RELATIONSHIP_NOT_PERMITTED",
            ),
            admin_headers,
        )
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "RELATIONSHIP_NOT_PERMITTED"
        # PRD §3.6: rejection mutates no account field.
        account_after = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert account_after["beneficiary_id"] == current_ben["id"]
