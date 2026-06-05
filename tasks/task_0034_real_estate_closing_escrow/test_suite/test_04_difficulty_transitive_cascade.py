"""Difficulty Rule 4 — transitive_cascade.

(A) EMD confirm → agreement funding threshold met → ACTIVE→UNDER_CONTRACT →
    EscrowAccount OPEN→FUNDED. Three causal hops, each link triggered by
    the previous (depth=3).
(B) Close transaction on a 1031 agreement → CLEARED_TO_CLOSE→CLOSED →
    linked ExchangeAccount IDENTIFIED→COMPLETED (depth=2).
"""
from test_helpers import (
    validate_success,
    setup_actors,
    setup_active_agreement,
    create_deposit,
    confirm_deposit,
    create_exchange_account,
    identify_exchange_account,
    setup_cleared_to_close,
    queue_disbursement,
    api_client,
)


class TestConfirmDepositCascadeEmdAgreementEscrow:
    """A single confirm call chains: EMD PENDING→CONFIRMED, agreement
    ACTIVE→UNDER_CONTRACT, EscrowAccount OPEN→FUNDED, all in one transaction.
    """

    def test_confirm_at_threshold_flips_emd_to_confirmed(self, api):
        """PRD §3.1: "When the funds clear at the originating bank, the officer confirms the deposit, supplying a ``confirmation_reference`` in the request body; the deposit advances from ``PENDING`` to ``CONFIRMED``."

        Design: Difficulty/transitive_cascade/confirm_deposit_chain_emd_to_agreement_to_escrow_depth3
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        deposit = create_deposit(
            actors, base["escrow"]["id"], amount_cents=1_000_000
        )
        confirmed = confirm_deposit(actors, deposit["id"])
        assert confirmed["status"] == "CONFIRMED", \
            f"confirm must flip EMD to CONFIRMED, got {confirmed['status']}"

    def test_confirm_at_threshold_cascades_agreement_and_escrow(self, api):
        """PRD §2.9: "When earnest money is confirmed and the agreement crosses its funding threshold, the cascade is: ``EarnestMoneyDeposit.status`` flips from ``PENDING`` to ``CONFIRMED``; ``PurchaseAgreement.earnest_money_received_cents`` is recomputed; if the new total reaches or exceeds ``earnest_money_required_cents`` and the agreement is in ``ACTIVE``, the agreement transitions to ``UNDER_CONTRACT`` and the escrow account transitions from ``OPEN`` to ``FUNDED``."

        Design: Difficulty/transitive_cascade/confirm_deposit_chain_emd_to_agreement_to_escrow_depth3
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        agreement = base["agreement"]
        escrow = base["escrow"]
        deposit = create_deposit(actors, escrow["id"], amount_cents=1_000_000)
        confirm_deposit(actors, deposit["id"])

        agr_after = validate_success(
            api.get_purchase_agreement(agreement["id"], actors["eo"]),
            expected_status=200,
        )
        assert agr_after["status"] == "UNDER_CONTRACT", \
            f"agreement must cascade to UNDER_CONTRACT, got {agr_after['status']}"
        assert agr_after["earnest_money_received_cents"] == 1_000_000, \
            f"recomputed earnest_money_received_cents=1000000 expected, got {agr_after['earnest_money_received_cents']}"

        esc_after = validate_success(
            api.get_escrow_account(escrow["id"], actors["eo"]),
            expected_status=200,
        )
        assert esc_after["status"] == "FUNDED", \
            f"escrow must cascade to FUNDED, got {esc_after['status']}"


class TestCloseCascadeAgreementToExchangeAccount:
    """When PA closes, the linked ExchangeAccount flips IDENTIFIED→COMPLETED
    inside the same transaction.
    """

    def _setup_close_ready_with_exchange(self):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        exchange = create_exchange_account(
            actors, relinquished_closing_date="2026-06-01T00:00:00Z"
        )
        identify_exchange_account(
            actors, exchange["id"], replacement_property_address="999 Replace St"
        )
        # Close a 1031 agreement before the 180-day exchange_deadline; total
        # disbursements (one EXCHANGE_FUNDS of the earnest money amount)
        # equal the escrow balance so the close passes fiscal sufficiency.
        ready = setup_cleared_to_close(
            actors=actors,
            purchase_price_cents=50_000_000,
            earnest_money_required_cents=1_000_000,
            exchange_account_id=exchange["id"],
            extra_wire_party="EXCHANGE_ACCOMMODATOR",
            extra_wire_callback_reference="VC-QI-CASCADE",
        )
        # Queue an EXCHANGE_FUNDS disbursement equal to escrow balance.
        queue_disbursement(
            ready["actors"],
            ready["escrow_id"],
            ready["extra_wire_id"],
            purpose="EXCHANGE_FUNDS",
            amount_cents=1_000_000,
        )
        return ready, exchange

    def test_close_flips_purchase_agreement_to_closed(self, api):
        """PRD §3.5: "Closing the agreement advances it from ``CLEARED_TO_CLOSE`` to ``CLOSED`` and runs the disbursement waterfall."
        PRD §3.5: "As the close transaction completes, the escrow account transitions from ``FUNDED`` through ``DISBURSED`` to ``CLOSED`` (so its ``version`` increments by exactly two, since two state writes happen back-to-back); if ``exchange_account_id`` on the agreement is non-null, the linked ``ExchangeAccount`` transitions from ``IDENTIFIED`` to ``COMPLETED``; and the agreement itself completes in ``CLOSED``."

        Design: Difficulty/transitive_cascade/close_chain_agreement_to_exchange_depth2
        """
        ready, _ = self._setup_close_ready_with_exchange()
        # Re-clear-to-close was already done; trigger the close.
        res = api.close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["eo"]
        )
        agr = validate_success(res, expected_status=200)
        assert agr["status"] == "CLOSED", \
            f"close must flip agreement to CLOSED, got {agr['status']}"

    def test_close_cascades_exchange_account_to_completed(self, api):
        """PRD §3.7: "The reciprocal success transition is system-driven: while the account is in ``IDENTIFIED``, when the corresponding ``PurchaseAgreement`` transitions to ``CLOSED`` inside the close transaction described in §3.5, the exchange account flips from ``IDENTIFIED`` to ``COMPLETED`` in the same transaction, provided the current UTC clock is at or before ``exchange_deadline``."

        Design: Difficulty/transitive_cascade/close_chain_agreement_to_exchange_depth2
        """
        ready, exchange = self._setup_close_ready_with_exchange()
        validate_success(
            api.close_purchase_agreement(
                ready["agreement_id"], ready["actors"]["eo"]
            ),
            expected_status=200,
        )
        ea_after = validate_success(
            api.get_exchange_account(exchange["id"], ready["actors"]["eo"]),
            expected_status=200,
        )
        assert ea_after["status"] == "COMPLETED", \
            f"linked ExchangeAccount must cascade to COMPLETED, got {ea_after['status']}"
