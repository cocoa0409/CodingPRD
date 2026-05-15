"""Validation priority and cross-entity state dependencies (PRD §2.7).

This file covers the difficulty-design instances
`state_vs_business_fiscal_priority`,
`business_safety_vs_business_constraint_priority`, and
`contribution_settle_requires_account_open`. Each test asserts only an
ordering rule the PRD names verbatim.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ANNUAL_GIFT_EXCLUSION_CENTS,
    TEST_USERS,
    create_beneficiary,
    create_contribution_payload,
    create_pending_contribution,
    create_withdrawal_payload,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    restrict_account,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    submit_beneficiary_change,
    validate_error,
)


class TestValidationPriority:

    def test_state_check_precedes_fiscal_check_on_settle(
        self, api, admin_headers,
    ):
        """PRD §2.7: "State-machine checks come next: an account whose
        status is not OPEN causes write operations on it to fail with
        ERR_ACCOUNT_RESTRICTED ... The next priority tier is business
        safety ahead of business fiscal."

        Claim: when an account is RESTRICTED AND a pending contribution
        would also breach the lifetime cap, the state error
        (ERR_ACCOUNT_RESTRICTED) is returned — not the fiscal error
        (ERR_LIFETIME_CAP_WOULD_EXCEED).

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_priority
        """
        ensure_state_rule(
            "AA", lifetime_aggregate_cap_cents=1_000_000, parity="PARITY",
        )
        donor, _ben, account = setup_account_with_balance(
            donor_state="AA", plan_state="AA", parity="PARITY",
            lifetime_aggregate_cap_cents=1_000_000,
            target_total_cents=900_000,
        )
        # Create a contribution that would breach the cap (200k > 100k
        # of room).
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=200_000,
        )
        # Restrict the account so the state-check would also fire.
        restrict_account(account["id"])
        res = api.settle_contribution(contribution["id"], admin_headers)
        # PRD §2.7: state-check fires before fiscal-check.
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")

    def test_generation_skip_safety_distinct_from_k12_constraint(
        self, api, admin_headers,
    ):
        """PRD §2.7: "The generation-skip check is classified as a
        safety check and intentionally fires ahead of business-
        constraint checks such as the K-12 annual cap
        (ERR_K12_CAP_EXCEEDED)."
        PRD §3.6: "the canonical example being a change from a CHILD
        beneficiary to a PARENT or IN_LAW beneficiary."

        Claim: a generation-skip approval returns
        ERR_BENEFICIARY_GENERATION_SKIP (safety, priority 13). A K-12
        cap-breach withdrawal create returns ERR_K12_CAP_EXCEEDED
        (constraint, priority 16). The two errors surface from
        distinct endpoints and are categorically distinct.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_priority
        """
        # Generation-skip path.
        donor, _ben, account = setup_donor_beneficiary_account(
            relationship_family_code="CHILD",
        )
        parent_ben = create_beneficiary(relationship_family_code="PARENT")
        bcr = submit_beneficiary_change(
            account=account, proposed_beneficiary=parent_ben,
        )
        res_safety = api.approve_beneficiary_change_request(
            bcr["id"], admin_headers,
        )
        validate_error(res_safety, "ERR_BENEFICIARY_GENERATION_SKIP")

        # K-12 cap path on a separate account whose beneficiary already
        # has zero cap room.
        from test_helpers import withdraw_and_classify, settle_lump_sum
        donor2, ben2, account2 = setup_account_with_balance(
            target_total_cents=2_000_000,
            contributions_split=[1_500_000, 500_000],
        )
        # Drive beneficiary k12_ytd_qualified to 1_000_000.
        # Use 5× 200k K-12 withdrawals with full receipts.
        for _ in range(5):
            withdraw_and_classify(
                account=account2, requested_amount_cents=200_000,
                expense_category="K_12", receipt_amount_cents=200_000,
            )
        ben_after = get_success_data(
            api.get_beneficiary(ben2["id"], admin_headers),
        )
        assert ben_after["k12_ytd_qualified_cents"] == 1_000_000
        # Now any K-12 withdrawal would push to negative cap room.
        # Top up account so the balance check does not fire first.
        settle_lump_sum(account=account2, donor=donor2, amount_cents=10_000)
        account2 = get_success_data(
            api.get_account(account2["id"], make_donor_headers(donor2["id"])),
        )
        res_constraint = api.create_withdrawal(
            account2["id"],
            create_withdrawal_payload(
                requested_amount_cents=1, expense_category="K_12",
            ),
            make_donor_headers(donor2["id"]),
        )
        validate_error(res_constraint, "ERR_K12_CAP_EXCEEDED")

    def test_contribution_settle_blocked_when_account_restricted(
        self, api, admin_headers,
    ):
        """PRD §2.7: "an account whose status is not OPEN causes write
        operations on it to fail with ERR_ACCOUNT_RESTRICTED."
        PRD §3.3: "Settlement requires the account to be OPEN (else
        ERR_ACCOUNT_RESTRICTED)."

        Claim: a PENDING contribution remains PENDING when the account
        is RESTRICTED, and settle returns ERR_ACCOUNT_RESTRICTED.

        # difficulty: cross_entity_state_dependency/contribution_settle_requires_account_open
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=50_000,
        )
        restrict_account(account["id"])
        res = api.settle_contribution(contribution["id"], admin_headers)
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")
        # PRD §3.3: "with no balance change" — the contribution remains
        # PENDING.
        c_after = get_success_data(
            api.get_contribution(
                contribution["id"], make_donor_headers(donor["id"]),
            ),
        )
        assert c_after["status"] == "PENDING"
