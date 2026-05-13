"""Card-type configuration and member registration.

PRD §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA,
    SO,
    assert_card_type,
    assert_member,
    create_card_type,
    create_card_type_payload,
    create_member,
    create_member_payload,
    create_funded_member,
    create_monthly_card_type,
    issue_card_payload,
    make_member_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# CardType creation
# ===========================================================================
class TestCardTypeShape:

    def test_active_card_type_shape(self, api):
        """PRD §3.1: 'Every CardType carries a configuration-lifecycle
        status that begins at ACTIVE.'"""
        ct = create_card_type(category="MONTHLY", price_cents=30_000,
                              validity_days=30, visit_quota=0,
                              max_freeze_days=10,
                              transfer_fee_pct_bp=1_000,
                              renewal_discount_pct_bp=1_500,
                              refund_eligibility_days=7)
        assert_card_type(ct)
        assert ct["status"] == "ACTIVE", (
            "PRD §3.1: status begins at ACTIVE."
        )
        assert ct["category"] == "MONTHLY"
        assert ct["price_cents"] == 30_000


# ===========================================================================
# Retired card-type prevents issuance (PRD §3.1)
# ===========================================================================
class TestRetiredCardTypeBlocksIssuance:

    def test_issue_against_retired_card_type_rejected(self, api):
        """PRD §3.1: 'a RETIRED card type rejects new card issuance with
        ERR_CARD_TYPE_RETIRED.'"""
        ct = create_monthly_card_type(price_cents=30_000)
        # Retire it.
        patched = api.patch_card_type(
            ct["id"],
            {"version": ct["version"], "status": "RETIRED"},
            PA,
        )
        retired = validate_success(patched, expected_status=200)
        assert retired["status"] == "RETIRED"

        member = create_funded_member(wallet_balance_cents=50_000)
        res = api.issue_card(
            issue_card_payload(
                card_type_id=ct["id"],
                holder_member_id=member["id"],
            ),
            SO,
        )
        validate_error(res, ApiErrorId.ERR_CARD_TYPE_RETIRED.value)


# ===========================================================================
# Member registration shape
# ===========================================================================
class TestMemberRegistration:

    def test_member_minimal_shape(self, api):
        """PRD §3.1: 'Member registration captures full_name ..., phone
        ..., email ..., optional family_group_id ..., optional
        notification_channels ..., and optional auto_renew_authorized
        (defaulting to false).'"""
        m = create_member()
        assert_member(m)

    def test_default_auto_renew_false(self, api):
        """PRD §3.1: 'optional auto_renew_authorized (defaulting to
        false).'"""
        m = create_member()
        assert m.get("auto_renew_authorized") is False, (
            f"PRD §3.1: auto_renew_authorized defaults to false; got "
            f"{m.get('auto_renew_authorized')!r}"
        )

    def test_default_notification_channels_sms_email(self, api):
        """PRD §3.1: 'optional notification_channels (a subset of SMS,
        EMAIL, IM, and PUSH, defaulting to ["SMS", "EMAIL"]).'"""
        m = create_member()
        assert set(m.get("notification_channels", [])) == {"SMS", "EMAIL"}, (
            f"PRD §3.1: notification_channels defaults to ['SMS', 'EMAIL']; "
            f"got {m.get('notification_channels')!r}"
        )

    def test_initial_wallet_balances_zero(self, api):
        """PRD §3.1: 'wallet_balance_cents, bonus_balance_cents, and
        bonus_expires_at are server-computed from the ledger and start
        at zero, zero, and null respectively.'"""
        m = create_member()
        assert m.get("wallet_balance_cents") == 0
        assert m.get("bonus_balance_cents") == 0
        assert m.get("bonus_expires_at") is None
