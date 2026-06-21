"""Difficulty Rule 9 — compensating_invariant.

(A) Earnest-refund-sum invariant on PA terminate (per-line conservation):
    sum(EMD.amount_cents flipped to REFUNDED) ==
    sum(Disbursement.amount_cents emitted with purpose=EARNEST_REFUND).
(B) Close balance invariant (aggregate conservation):
    EscrowAccount.balance_cents at entry =
    EscrowAccount.balance_cents at exit + sum(DISBURSED Disbursement.amount_cents).
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    setup_actors,
    setup_active_agreement,
    create_deposit,
    setup_locked_wire,
    queue_disbursement,
    setup_cleared_to_close,
    terminate_purchase_agreement_payload,
    api_client,
)


class TestEarnestRefundSumPreservedOnTerminate:
    """Two PENDING deposits totaling 2_500_000 cents → terminate from
    ACTIVE → two EARNEST_REFUND Disbursements totaling 2_500_000 cents.
    """

    def _setup_two_pending_deposits_then_terminate(self, api):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors,
            purchase_price_cents=50_000_000,
            earnest_money_required_cents=5_000_000,  # so both deposits stay PENDING and ACTIVE
        )
        agreement = base["agreement"]
        escrow = base["escrow"]
        d1 = create_deposit(actors, escrow["id"], amount_cents=1_500_000)
        d2 = create_deposit(actors, escrow["id"], amount_cents=1_000_000)
        # BUYER wire LOCKED so refunds can route per PRD §3.6.
        setup_locked_wire(
            actors, agreement["id"], party="BUYER",
            voice_callback_reference="VC-INV",
        )
        validate_success(
            api.terminate_purchase_agreement(
                agreement["id"],
                terminate_purchase_agreement_payload(terminated_reason="Deal off."),
                actors["eo"],
            ),
            expected_status=200,
        )
        return actors, escrow, d1, d2

    def test_each_pending_deposit_flips_refunded_on_terminate(self, api):
        """PRD §3.6: "The compensating action flips every ``PENDING`` earnest money deposit on the agreement's escrow to ``REFUNDED``, transitions the escrow from ``OPEN`` to ``CLOSED``, sets ``terminated_reason`` on the agreement, and bumps both the escrow's and the agreement's ``version`` by one each."

        Design: Difficulty/compensating_invariant/earnest_refund_invariant_sum_preserved_on_terminate
        """
        actors, escrow, d1, d2 = self._setup_two_pending_deposits_then_terminate(api)
        emd1 = validate_success(
            api.get_earnest_money_deposit(d1["id"], actors["eo"]),
            expected_status=200,
        )
        emd2 = validate_success(
            api.get_earnest_money_deposit(d2["id"], actors["eo"]),
            expected_status=200,
        )
        assert emd1["status"] == "REFUNDED", \
            f"deposit 1 must be REFUNDED, got {emd1['status']}"
        assert emd2["status"] == "REFUNDED", \
            f"deposit 2 must be REFUNDED, got {emd2['status']}"

    def test_earnest_refund_disbursements_match_deposit_sum_per_line(self, api):
        """PRD §3.6: "For each earnest money deposit that flips to ``REFUNDED`` in either from-state, the system emits one ``Disbursement`` with ``purpose`` of ``EARNEST_REFUND``, ``amount_cents`` equal to that deposit's ``amount_cents``, and ``wire_instruction_id`` pointing to the agreement's ``BUYER`` wire instruction in status ``LOCKED``."
        PRD §3.6: "The compensating invariant is that the sum of ``amount_cents`` across deposits flipping to ``REFUNDED`` equals the sum of ``amount_cents`` across the refund disbursements emitted in the same transaction."

        Design: Difficulty/compensating_invariant/earnest_refund_invariant_sum_preserved_on_terminate
        """
        actors, escrow, d1, d2 = self._setup_two_pending_deposits_then_terminate(api)
        data, meta = validate_paginated(
            api.list_disbursements(actors["eo"], params={"escrow_account_id": escrow["id"]})
        )
        refunds = [
            row for row in data
            if row["purpose"] == "EARNEST_REFUND"
        ]
        assert len(refunds) == 2, \
            f"two PENDING deposits → two EARNEST_REFUND disbursements expected, got {len(refunds)}"
        total = sum(r["amount_cents"] for r in refunds)
        assert total == 2_500_000, \
            f"sum of refund disbursements must equal 1500000+1000000 = 2500000, got {total}"


class TestCloseBalanceInvariantEscrowDrainEqualsDisbursements:
    """Pre-close balance == post-close balance + sum of DISBURSED amounts.
    """

    def _setup_close_with_single_seller_disbursement(self, api):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        ready = setup_cleared_to_close(
            actors=actors,
            purchase_price_cents=100_000_000,
            earnest_money_required_cents=100_000_000,
            scheduled_closing_date="2026-08-01T00:00:00Z",
        )
        # Queue a single SELLER_PROCEEDS disbursement matching escrow balance.
        seller_wire_id = ready["seller_wire_id"]
        disb = queue_disbursement(
            ready["actors"], ready["escrow_id"], seller_wire_id,
            purpose="SELLER_PROCEEDS", amount_cents=100_000_000,
        )
        return ready, disb

    def test_close_drives_disbursement_to_disbursed(self, api):
        """PRD §3.5: "For each disbursement in that order, if the running remaining balance is at least the disbursement's ``amount_cents``, the disbursement advances from ``QUEUED`` to ``DISBURSED``, its ``version`` increments by one, and the remaining balance is reduced by ``amount_cents``."

        Design: Difficulty/compensating_invariant/close_balance_invariant_escrow_drain_equals_disbursements
        """
        ready, disb = self._setup_close_with_single_seller_disbursement(api)
        validate_success(
            api.close_purchase_agreement(
                ready["agreement_id"], ready["actors"]["eo"]
            ),
            expected_status=200,
        )
        disb_after = validate_success(
            api.get_disbursement(disb["id"], ready["actors"]["eo"]),
            expected_status=200,
        )
        assert disb_after["status"] == "DISBURSED", \
            f"queued disbursement must be DISBURSED after close, got {disb_after['status']}"

    def test_close_zeroes_escrow_balance_when_disbursements_match(self, api):
        """PRD §3.5: "The compensating-invariant is that the sum of ``amount_cents`` across queued disbursements at entry equals the sum across disbursed disbursements at exit, and the escrow account's ``balance_cents`` at exit equals its ``balance_cents`` at entry minus that sum."

        Design: Difficulty/compensating_invariant/close_balance_invariant_escrow_drain_equals_disbursements
        """
        ready, disb = self._setup_close_with_single_seller_disbursement(api)
        validate_success(
            api.close_purchase_agreement(
                ready["agreement_id"], ready["actors"]["eo"]
            ),
            expected_status=200,
        )
        esc_after = validate_success(
            api.get_escrow_account(ready["escrow_id"], ready["actors"]["eo"]),
            expected_status=200,
        )
        # entry balance = 100_000_000; disbursed = 100_000_000; exit = 0.
        assert esc_after["balance_cents"] == 0, \
            f"escrow balance must drain to 0 (entry 100000000 - disbursed 100000000), got {esc_after['balance_cents']}"
