"""Wallet ledger: idempotency, refund-floor, adjustment-balance,
reversal invariant. Covers PRD §3.8, §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_balance_state_consistent,
    assert_wallet_transaction,
    create_wallet_tx_payload,
    get_advertiser,
    reverse_wallet_tx_payload,
    setup_active_advertiser,
    validate_error,
    validate_success,
)


# ===========================================================================
# Idempotency (PRD §3.8)
# ===========================================================================
class TestIdempotency:

    def test_repeat_idempotency_key_returns_conflict(self, api):
        """PRD §3.8: "A re-submitted transaction with the same
        (advertiser_id, tx_type, idempotency_key) triple as an existing
        one is rejected with ERR_IDEMPOTENCY_CONFLICT (HTTP 409); the
        balance is only credited once."

        Claim: two RECHARGEs with the same idempotency_key under one
        advertiser -> second returns ERR_IDEMPOTENCY_CONFLICT; balance
        reflects exactly one recharge.
        """
        bundle = setup_active_advertiser(initial_recharge_cents=100000)
        adv = bundle["advertiser"]
        balance_before = adv["balance_cents"]
        key = "idem-repeat-1"
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=50000,
                idempotency_key=key,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        # Second submission with same key.
        res = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=50000,
                idempotency_key=key,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value)
        # Balance reflects exactly one credit.
        adv_after = get_advertiser(adv["id"])
        assert adv_after["balance_cents"] == balance_before + 50000


# ===========================================================================
# Refund floor (PRD §3.8)
# ===========================================================================
class TestRefundFloor:

    def test_refund_below_credit_floor_rejected(self, api):
        """PRD §3.8: "The refund-floor protection applies to a REFUND
        transaction or to any reversal of a settled wallet transaction:
        the resulting balance_cents MUST NOT drop below the negative of
        credit_line_cents, expressed as balance_cents + amount_cents >=
        -credit_line_cents. A violation is rejected with
        ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR (HTTP 409)."

        Claim: PREPAY advertiser (credit_line=0) with balance=100; a
        REFUND of -500 would push balance to -400, breaching the
        floor of 0; rejected.
        """
        bundle = setup_active_advertiser(initial_recharge_cents=100)
        adv = bundle["advertiser"]
        # REFUND outflow must respect floor. amount_cents per PRD §3.8
        # is signed positive for REFUND inflows; but a reversal of a
        # settled tx that would push below the floor is the canonical
        # case. We construct it explicitly: first an ADJUSTMENT
        # debit that puts the account near the floor, then attempt to
        # reverse it but only after a CONSUMPTION drives balance down.
        # Simpler: directly create a settled CONSUMPTION-equivalent via
        # ADJUSTMENT to consume to 0, then try to REVERSE the
        # ADJUSTMENT — that would credit +100, but if we first issue
        # another debit ADJUSTMENT we'd hit ERR_INSUFFICIENT_BALANCE
        # (priority 19) on the second debit, not the reverse path.
        #
        # Cleanest is the explicit REFUND outflow case: under PRD §3.8
        # a REFUND has positive amount_cents (it's an inflow). For the
        # refund-floor to fire on a positive-amount tx, the "resulting
        # balance" must somehow drop — that only happens on the REVERSAL
        # of a positive REFUND already settled.
        #
        # Therefore: create an ADJUSTMENT inflow of +500 (settles +500
        # to balance=600), then reverse it (subtract 500), then try to
        # reverse a CONSUMPTION-equivalent that puts balance to -credit.
        # That's complex; instead exercise the WALLET tx REVERSE path
        # which is documented in §3.8 last paragraph: "A reversal of an
        # already-settled wallet transaction by a FinanceOfficer
        # requires a non-empty note, applies the inverse amount to the
        # balance ... " — same refund-floor predicate applies.
        #
        # Build: balance starts at 100; recharge +500 -> 600; consume
        # via debit ADJUSTMENT -550 -> 50. Now try to REVERSE the
        # RECHARGE (subtract 500). Resulting balance = 50 - 500 = -450;
        # credit_line=0; floor = -0; -450 < 0 -> ERR_REFUND_WOULD_BREACH.
        rch = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=500,
                idempotency_key="rch-floor-1",
            ),
            TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-550,
                note="drain", idempotency_key="adj-floor-1",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        adv_mid = get_advertiser(adv["id"])
        assert adv_mid["balance_cents"] == 50, (
            f"Setup error: expected balance=50, got {adv_mid['balance_cents']}"
        )
        # Reverse the RECHARGE — would push balance to -450.
        res = api.reverse_wallet_tx(
            adv["id"], rch["id"],
            reverse_wallet_tx_payload(note="cancel recharge"),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(
            res, ApiErrorId.ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR.value,
        )


# ===========================================================================
# Adjustment balance check (PRD §3.8)
# ===========================================================================
class TestAdjustmentBalance:

    def test_negative_adjustment_below_zero_rejected_with_insufficient_balance(
        self, api,
    ):
        """PRD §3.8: "The adjustment-balance check applies to a debit
        ADJUSTMENT (a negative amount_cents): the same predicate must
        hold, but the rejection is ERR_INSUFFICIENT_BALANCE (HTTP 402)."

        Claim: PREPAY advertiser (credit_line=0) with balance=100; a
        debit ADJUSTMENT of -500 would push to -400; rejected with
        ERR_INSUFFICIENT_BALANCE (NOT ERR_REFUND_WOULD_BREACH).
        """
        bundle = setup_active_advertiser(initial_recharge_cents=100)
        adv = bundle["advertiser"]
        res = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-500,
                note="excessive debit",
                idempotency_key="adj-insuf-1",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)

    def test_positive_adjustment_settles_and_updates_balance(self, api):
        """PRD §3.8: "A RECHARGE, REFUND, or ADJUSTMENT auto-settles
        synchronously."

        Claim: positive ADJUSTMENT -> SETTLED, balance += amount.
        """
        bundle = setup_active_advertiser(initial_recharge_cents=1000)
        adv = bundle["advertiser"]
        balance_before = adv["balance_cents"]
        res = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=500,
                note="goodwill credit",
                idempotency_key="adj-pos-1",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_wallet_transaction(data)
        assert data["status"] == "SETTLED"
        adv_after = get_advertiser(adv["id"])
        assert adv_after["balance_cents"] == balance_before + 500


# ===========================================================================
# Reversal — net-zero invariant (PRD §2.9, §3.8)
# ===========================================================================
class TestWalletReversal:

    def test_recharge_then_reverse_leaves_balance_unchanged(self, api):
        """PRD §3.8: "the forward-plus-reverse pair leaves balance_cents
        unchanged in net."

        Claim: recharge +X then reverse leaves balance_cents at its
        original pre-recharge value.
        """
        bundle = setup_active_advertiser(initial_recharge_cents=1000)
        adv = bundle["advertiser"]
        balance_before = adv["balance_cents"]
        rch = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=5000,
                idempotency_key="rch-rev-1",
            ),
            TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        api.reverse_wallet_tx(
            adv["id"], rch["id"],
            reverse_wallet_tx_payload(note="revert charge"),
            TEST_USERS["platform_admin_headers"],
        )
        adv_after = get_advertiser(adv["id"])
        assert adv_after["balance_cents"] == balance_before, (
            f"PRD §3.8 net-zero: forward+reverse leaves balance "
            f"unchanged; before={balance_before}, after="
            f"{adv_after['balance_cents']}"
        )

    def test_reverse_requires_non_empty_note(self, api):
        """PRD §3.8: "A reversal of an already-settled wallet
        transaction by a FinanceOfficer requires a non-empty note."

        Claim: missing/empty note -> ERR_INVALID_REQUEST.
        """
        bundle = setup_active_advertiser(initial_recharge_cents=10000)
        adv = bundle["advertiser"]
        rch = api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="RECHARGE", amount_cents=500,
                idempotency_key="rch-note-1",
            ),
            TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        res = api.reverse_wallet_tx(
            adv["id"], rch["id"], {"note": ""},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Balance state derivation (PRD §3.9)
# ===========================================================================
class TestBalanceStateDerivation:

    def test_balance_state_consistent_after_recharge_and_drain(self, api):
        """PRD §3.9: "If balance_cents is at most 0, balance_state is
        ZERO_BALANCE. If balance_cents is strictly greater than 0 and
        at most low_balance_threshold_cents, balance_state is
        LOW_BALANCE. Otherwise — strictly greater than
        low_balance_threshold_cents — balance_state is HEALTHY."

        Claim: balance_state is consistent at each intermediate balance
        (HEALTHY -> LOW_BALANCE -> ZERO_BALANCE).
        """
        bundle = setup_active_advertiser(
            initial_recharge_cents=100000,
        )  # threshold default 10000
        adv = get_advertiser(bundle["advertiser"]["id"])
        assert_balance_state_consistent(adv)
        # Bring to exactly threshold = LOW_BALANCE boundary.
        # 100000 - 90000 = 10000 (== threshold). PRD: <= threshold = LOW.
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-90000,
                note="to-low",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        adv_low = get_advertiser(adv["id"])
        assert adv_low["balance_cents"] == 10000
        assert adv_low["balance_state"] == "LOW_BALANCE", (
            f"PRD §3.9: balance==threshold -> LOW_BALANCE, got "
            f"{adv_low['balance_state']!r}"
        )
        assert_balance_state_consistent(adv_low)
        # Drain to zero.
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-10000,
                note="to-zero",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        adv_zero = get_advertiser(adv["id"])
        assert adv_zero["balance_cents"] == 0
        assert adv_zero["balance_state"] == "ZERO_BALANCE"
        assert_balance_state_consistent(adv_zero)


# ===========================================================================
# Pause-on-zero (PRD §3.9)
# ===========================================================================
class TestPauseOnZero:

    def test_zero_balance_pauses_running_campaign_and_ad_group(self, api):
        """PRD §3.9: "When the system crosses into ZERO_BALANCE, every
        RUNNING Campaign belonging to the advertiser is paused, and so
        is every RUNNING AdGroup under those campaigns — this is the
        pause-on-zero protection."

        Claim: drain balance to 0 -> ACTIVE Campaign moves to PAUSED;
        RUNNING AdGroup moves to PAUSED.
        """
        from test_helpers import setup_active_campaign_with_approved_creative
        setup = setup_active_campaign_with_approved_creative(
            initial_recharge_cents=100,
        )
        adv = setup["advertiser"]
        # Drain to 0 via ADJUSTMENT -100.
        api.create_wallet_tx(
            adv["id"],
            create_wallet_tx_payload(
                tx_type="ADJUSTMENT", amount_cents=-100,
                note="drain to zero",
            ),
            TEST_USERS["platform_admin_headers"],
        )
        # Refresh.
        camp_list = api_client.list_campaigns(
            adv["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        camp = next(c for c in camp_list if c["id"] == setup["campaign"]["id"])
        assert camp["status"] == "PAUSED", (
            f"PRD §3.9 pause-on-zero: ACTIVE Campaign must move to "
            f"PAUSED, got {camp['status']!r}"
        )
        ag_list = api_client.list_ad_groups(
            adv["id"], camp["id"], TEST_USERS["platform_admin_headers"],
        ).json()["data"]
        ag = next(a for a in ag_list if a["id"] == setup["ad_group"]["id"])
        assert ag["status"] == "PAUSED"
