"""Contribution create / settle / reverse and the lifetime-cap and
gift-exclusion guardrails (PRD §3.3).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ANNUAL_GIFT_EXCLUSION_CENTS,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    assert_account_balance_invariant,
    assert_contribution,
    build_user_headers,
    create_contribution_payload,
    create_donor,
    create_pending_contribution,
    create_state_rule,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    settle_contribution,
    settle_lump_sum,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create Contribution (PRD §3.3)
# ===========================================================================
class TestCreateContribution:

    def test_create_pending_lump_sum(self, api):
        """PRD §3.3: "A lump-sum contribution is initiated by a Donor
        posting a payload containing donor_id, amount_cents,
        contribution_kind set to LUMP_SUM, and a null
        recurring_plan_id."
        PRD §3.3: "Every contribution starts in status PENDING with
        settled_at null."

        Claim: POST creates Contribution in PENDING with settled_at
        null; balances do not yet move.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        before = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        res = api.create_contribution(
            account["id"],
            create_contribution_payload(
                donor_id=donor["id"], amount_cents=50_000,
                contribution_kind="LUMP_SUM",
            ),
            make_donor_headers(donor["id"]),
        )
        contribution = validate_success(res, 201)
        assert_contribution(contribution)
        assert contribution["status"] == "PENDING"
        assert contribution["settled_at"] in (None, "")
        # PRD §3.3: balances move only on settle.
        after = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert after["total_balance_cents"] == before["total_balance_cents"]

    def test_third_party_donor_contribution_allowed(self, api):
        """PRD §3.3: "the donor in the payload need not equal the
        account's primary_donor_id, because third-party gifts (a
        grandparent funding a parent's account) are explicitly
        supported."

        Claim: a contribution with donor_id != primary_donor_id is
        accepted at create time.
        """
        primary_donor, _ben, account = setup_donor_beneficiary_account()
        third_party = create_donor(state_of_residence="NY")
        # The acting role is `Donor` per PRD §4; the acting donor
        # (X-User-ID) is the third-party donor making the gift.
        res = api.create_contribution(
            account["id"],
            create_contribution_payload(
                donor_id=third_party["id"],
                amount_cents=25_000,
                contribution_kind="LUMP_SUM",
            ),
            make_donor_headers(third_party["id"]),
        )
        contribution = validate_success(res, 201)
        assert contribution["donor_id"] == third_party["id"]
        assert contribution["account_id"] == account["id"]

    def test_create_contribution_unknown_donor_returns_404(self, api):
        """PRD §2.6: "Body-referenced resource ids ... that do not
        resolve to a live row" → ERR_NOT_FOUND.

        Claim: donor_id pointing to a non-existent donor → ERR_NOT_FOUND.
        """
        primary_donor, _ben, account = setup_donor_beneficiary_account()
        res = api.create_contribution(
            account["id"],
            create_contribution_payload(
                donor_id=NON_EXISTENT_UUID,
                amount_cents=25_000,
                contribution_kind="LUMP_SUM",
            ),
            make_donor_headers(primary_donor["id"]),
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# Settle Contribution (PRD §3.3)
# ===========================================================================
class TestSettleContribution:

    def test_settle_updates_balances_and_yt_total(self, api, admin_headers):
        """PRD §3.3: "On successful settlement, the account's
        basis_balance_cents and total_balance_cents each increase by
        amount_cents, the donor's ytd_contribution_total_cents
        increases by amount_cents, settled_at is set to the current
        server timestamp."

        Claim: settling a PENDING contribution moves balances and donor
        YTD as documented.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=70_000,
        )
        before_balance = account["total_balance_cents"]
        before_donor = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        before_ytd = before_donor["ytd_contribution_total_cents"]
        res = api.settle_contribution(contribution["id"], admin_headers)
        settled = validate_success(res, 200)
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] is not None
        # Re-read account.
        after_account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert after_account["basis_balance_cents"] == 70_000
        assert after_account["total_balance_cents"] == before_balance + 70_000
        assert_account_balance_invariant(after_account)
        # Re-read donor.
        after_donor = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        assert (
            after_donor["ytd_contribution_total_cents"]
            == before_ytd + 70_000
        )

    def test_settle_blocked_when_account_restricted(self, api, admin_headers):
        """PRD §3.3: "Settlement requires the account to be OPEN (else
        ERR_ACCOUNT_RESTRICTED)."

        Claim: settle on a contribution whose account has been
        RESTRICTED returns ERR_ACCOUNT_RESTRICTED.
        """
        from test_helpers import restrict_account
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=50_000,
        )
        restrict_account(account["id"])
        res = api.settle_contribution(contribution["id"], admin_headers)
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")

    def test_settle_exceeding_lifetime_cap_rejected(self, api, admin_headers):
        """PRD §3.3: "the post-credit account total to remain at or
        below the pinned lifetime cap (else ERR_LIFETIME_CAP_WOULD_EXCEED
        — that is, total_balance_cents plus the contribution's
        amount_cents must not exceed the account's
        lifetime_contribution_cap_cents)."

        Claim: a PENDING contribution that would push total over the
        pinned lifetime cap → ERR_LIFETIME_CAP_WOULD_EXCEED on settle.
        """
        ensure_state_rule(
            "WX", lifetime_aggregate_cap_cents=1_000_000, parity="PARITY",
        )
        donor, _ben, account = setup_account_with_balance(
            donor_state="WX", plan_state="WX",
            lifetime_aggregate_cap_cents=1_000_000, parity="PARITY",
            target_total_cents=900_000,
        )
        # Now total=900k, cap=1M. A 200k contribution would push to
        # 1.1M, over the 1M cap.
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=200_000,
        )
        res = api.settle_contribution(contribution["id"], admin_headers)
        validate_error(res, "ERR_LIFETIME_CAP_WOULD_EXCEED")

    def test_settle_exceeding_gift_exclusion_rejected(self, api, admin_headers):
        """PRD §3.3: "the post-credit donor calendar-year total to
        remain at or below the IRS annual gift-tax exclusion (else
        ERR_GIFT_EXCLUSION_EXCEEDED — the donor's
        ytd_contribution_total_cents plus the contribution's
        amount_cents must not exceed the annual gift exclusion of
        $18,000, equivalently 1,800,000 cents)."

        Claim: a contribution that would push donor YTD over 1,800,000
        cents → ERR_GIFT_EXCLUSION_EXCEEDED.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        # Use a generous lifetime cap so only the gift exclusion fires.
        # Settle one contribution that brings donor YTD to 1,700,000.
        settle_lump_sum(
            account=account, donor=donor,
            amount_cents=ANNUAL_GIFT_EXCLUSION_CENTS - 100_000,
        )
        # Now create a 200,000-cent contribution that would push YTD to
        # 1,900,000 > 1,800,000.
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=200_000,
        )
        res = api.settle_contribution(contribution["id"], admin_headers)
        validate_error(res, "ERR_GIFT_EXCLUSION_EXCEEDED")

    def test_settle_already_settled_rejected(self, api, admin_headers):
        """PRD §3.3 + §2.7: settle requires source state PENDING (via
        PRD §3.3 state machine narrative: "A PlanAdministrator settles
        a PENDING contribution, transitioning its status from PENDING
        to SETTLED.") and PRD §2.7 makes wrong from-state return
        ERR_INVALID_STATE.

        Claim: a second settle on a SETTLED contribution →
        ERR_INVALID_STATE.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=50_000,
        )
        settle_contribution(contribution["id"])
        res = api.settle_contribution(contribution["id"], admin_headers)
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Reverse Contribution (PRD §3.3)
# ===========================================================================
class TestReverseContribution:

    def test_reverse_pending_contribution(self, api, admin_headers):
        """PRD §3.3: "A PlanAdministrator may instead reverse a PENDING
        contribution, transitioning its status from PENDING to REVERSED
        with no balance change."

        Claim: reverse on PENDING flips status to REVERSED and does NOT
        mutate the account or donor YTD totals.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=80_000,
        )
        before_account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        before_donor = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        res = api.reverse_contribution(contribution["id"], admin_headers)
        reversed_c = validate_success(res, 200)
        assert reversed_c["status"] == "REVERSED"
        # No balance change.
        after_account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert after_account["total_balance_cents"] == (
            before_account["total_balance_cents"]
        )
        assert after_account["basis_balance_cents"] == (
            before_account["basis_balance_cents"]
        )
        # PRD §3.3: contribution never settled → donor YTD untouched.
        after_donor = get_success_data(
            api.get_donor(donor["id"], make_donor_headers(donor["id"])),
        )
        assert after_donor["ytd_contribution_total_cents"] == (
            before_donor["ytd_contribution_total_cents"]
        )

    def test_reverse_already_settled_rejected(self, api, admin_headers):
        """PRD §3.3: "A SETTLED contribution cannot be reversed —
        mistakes after settlement are corrected by a subsequent
        withdrawal."

        Claim: reverse on SETTLED → ERR_INVALID_STATE.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        contribution = create_pending_contribution(
            account=account, donor=donor, amount_cents=50_000,
        )
        settle_contribution(contribution["id"])
        res = api.reverse_contribution(contribution["id"], admin_headers)
        validate_error(res, "ERR_INVALID_STATE")
