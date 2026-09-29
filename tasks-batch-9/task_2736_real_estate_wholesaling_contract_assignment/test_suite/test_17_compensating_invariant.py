"""
Quantities that must still balance after money and encumbrances have moved
twice: the four escrow buckets of one deposit, and one cash buyer's committed
capital returning to its pre-offer baseline.
"""

from test_helpers import (
    accept_offer,
    add_verified_buyer,
    adjudicate_dispute,
    assert_assignment_offer,
    assert_cash_buyer,
    assert_dispute_case,
    assert_earnest_money_deposit,
    assert_escrow_conserved,
    assert_nulls,
    assert_purchase_contract,
    assert_seller_lead,
    build_signed_contract,
    elect,
    factories,
    file_evidence,
    find_deposit,
    forfeit_deposit,
    make_seller_headers,
    make_wholesaler_headers,
    open_dispute,
    read_buyer,
    read_dispute,
    read_lead,
    read_offer,
    set_clock,
    submit_offer,
    validate_success,
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_1_USER_ID,
    TITLE_AGENT_1,
)

ODD_DEPOSIT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500001,
    "inspection_period_days": 7,
    "option_start_at": "2026-08-10T00:00:00Z",
    "closing_window_start_at": "2026-09-15T00:00:00Z",
    "closing_window_end_at": "2026-09-30T00:00:00Z",
}

SELLER_EVIDENCE_REF = "ev-seller-bank-statements-001"
WHOLESALER_EVIDENCE_REF = "ev-wholesaler-inspection-report-001"


def _forfeited_deposit_under_dispute(api):
    """
    An odd-cent deposit forfeited to the seller after the inspection period, with
    a dispute over that forfeiture standing at EVIDENCE_COMPLETE.
    """
    scenario = build_signed_contract(
        api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(ODD_DEPOSIT_TERMS)
    )
    assert_purchase_contract(
        scenario.contract,
        contract_status="SIGNED",
        earnest_money_cents=500001,
        signed_at="2026-08-10T00:00:00Z",
        inspection_deadline_at="2026-08-17T00:00:00Z",
    )
    set_clock(api, "2026-08-18T00:00:00Z")
    deposit = forfeit_deposit(
        api, scenario.deposit["id"], TITLE_AGENT_1
    )
    dispute = open_dispute(
        api,
        scenario.pc_id,
        scenario.lead_id,
        dispute_basis="EARNEST_MONEY_FORFEITURE",
        claimed_amount_cents=500001,
    )
    file_evidence(
        api, dispute["id"], SELLER_EVIDENCE_REF, make_seller_headers(scenario.lead_id)
    )
    dispute = file_evidence(
        api,
        dispute["id"],
        WHOLESALER_EVIDENCE_REF,
        make_wholesaler_headers(scenario.w_id),
    )
    return scenario, deposit, dispute


class TestEscrowBucketsConserveTheDepositAmount:
    """Two dispositions on one odd amount, and not a cent minted or lost."""

    def test_split_award_re_buckets_the_whole_amount_and_keeps_the_odd_cent(self, api):
        """
        "Under `SPLIT_50_50`, the seller's share is the deposit's `amount_cents`
        divided by two and taken to the floor; `forfeited_to_seller_cents` is set
        to that share, `refunded_to_wholesaler_cents` is set to `amount_cents` less
        that share, `award_seller_cents` equals the share and
        `award_wholesaler_cents` equals `amount_cents` less the share — so an odd
        deposit amount leaves the extra cent with the wholesaler."

        "The deposit's status moves `FORFEITED_TO_SELLER → SPLIT_SETTLED`, which is
        terminal. Every one of the three outcomes increments
        `disposition_event_count` by exactly one."

        "Its four buckets — `held_cents`, `refunded_to_wholesaler_cents`,
        `forfeited_to_seller_cents` and `applied_at_closing_cents` — always sum to
        exactly `amount_cents`, and no bucket is ever negative."

        "The officer's `X-User-ID` is recorded as the dispute's
        `adjudicated_by_user_id`."

        Design: Difficulty/compensating_invariant/escrow_disposition_buckets_conserve_deposit_amount
        """
        scenario, _, dispute = _forfeited_deposit_under_dispute(api)

        ruled = adjudicate_dispute(
            api, dispute["id"], "SPLIT_50_50", COMPLIANCE_OFFICER_1
        )

        # floor(500001 / 2) == 250000 to the seller, 250001 to the wholesaler.
        assert_dispute_case(
            ruled,
            status="ADJUDICATED",
            award="SPLIT_50_50",
            award_seller_cents=250000,
            award_wholesaler_cents=250001,
            adjudicated_by_user_id=COMPLIANCE_OFFICER_1_USER_ID,
        )
        settled = find_deposit(api, scenario.pc_id, scenario.w_id)
        assert_earnest_money_deposit(
            settled,
            status="SPLIT_SETTLED",
            amount_cents=500001,
            held_cents=0,
            refunded_to_wholesaler_cents=250001,
            forfeited_to_seller_cents=250000,
            applied_at_closing_cents=0,
            disposition_event_count=2,
        )
        assert_escrow_conserved(settled)
        assert (
            ruled["award_seller_cents"] + ruled["award_wholesaler_cents"]
            == settled["amount_cents"]
        ), f"the two award halves must exhaust the deposit: {ruled}"

    def test_every_checkpoint_before_the_award_already_balances(self, api):
        """
        "**Escrow conservation.** An earnest money deposit's `amount_cents` is
        fixed at signing and never mutates."

        "Every disposition is a transfer between buckets, never a mint and never a
        burn, and every applied disposition increments `disposition_event_count` by
        exactly one."

        "Supplying a `forfeiture_reason`, the agent drives the deposit from `HELD`
        to `FORFEITED_TO_SELLER`, transferring the whole of `held_cents` into
        `forfeited_to_seller_cents` and incrementing `disposition_event_count`."

        "The case enters status `OPENED` with `seller_evidence_ref` and
        `wholesaler_evidence_ref` both null and `award`, `award_seller_cents`,
        `award_wholesaler_cents` and `adjudicated_by_user_id` all null."

        "The second filing, made while the other party's reference is already
        present, drives `EVIDENCE_PARTIAL → EVIDENCE_COMPLETE`; that is the join,
        and it is defined by both references being non-null."

        Design: Difficulty/compensating_invariant/escrow_disposition_buckets_conserve_deposit_amount
        """
        scenario = build_signed_contract(
            api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(ODD_DEPOSIT_TERMS)
        )
        # Creation is not a disposition event.
        at_signing = find_deposit(api, scenario.pc_id, scenario.w_id)
        assert_earnest_money_deposit(
            at_signing,
            status="HELD",
            amount_cents=500001,
            held_cents=500001,
            refunded_to_wholesaler_cents=0,
            forfeited_to_seller_cents=0,
            applied_at_closing_cents=0,
            disposition_event_count=0,
        )
        assert_escrow_conserved(at_signing)

        set_clock(api, "2026-08-18T00:00:00Z")
        forfeited = forfeit_deposit(api, at_signing["id"], TITLE_AGENT_1)
        assert_earnest_money_deposit(
            forfeited,
            status="FORFEITED_TO_SELLER",
            amount_cents=500001,
            held_cents=0,
            forfeited_to_seller_cents=500001,
            refunded_to_wholesaler_cents=0,
            applied_at_closing_cents=0,
            disposition_event_count=1,
        )
        assert_escrow_conserved(forfeited)

        opened = open_dispute(
            api,
            scenario.pc_id,
            scenario.lead_id,
            dispute_basis="EARNEST_MONEY_FORFEITURE",
            claimed_amount_cents=500001,
        )
        assert_dispute_case(
            opened, status="OPENED", claimed_amount_cents=500001
        )
        assert_nulls(
            opened,
            "seller_evidence_ref",
            "wholesaler_evidence_ref",
            "award",
            "award_seller_cents",
            "award_wholesaler_cents",
            "adjudicated_by_user_id",
            label="dispute_case",
        )

        partial = file_evidence(
            api,
            opened["id"],
            SELLER_EVIDENCE_REF,
            make_seller_headers(scenario.lead_id),
        )
        assert_dispute_case(
            partial,
            status="EVIDENCE_PARTIAL",
            seller_evidence_ref=SELLER_EVIDENCE_REF,
            wholesaler_evidence_ref=None,
        )
        complete = file_evidence(
            api,
            opened["id"],
            WHOLESALER_EVIDENCE_REF,
            make_wholesaler_headers(scenario.w_id),
        )
        assert_dispute_case(
            complete,
            status="EVIDENCE_COMPLETE",
            seller_evidence_ref=SELLER_EVIDENCE_REF,
            wholesaler_evidence_ref=WHOLESALER_EVIDENCE_REF,
        )
        # Prosecuting the dispute moved no money at all.
        untouched = find_deposit(api, scenario.pc_id, scenario.w_id)
        assert_earnest_money_deposit(
            untouched,
            status="FORFEITED_TO_SELLER",
            forfeited_to_seller_cents=500001,
            disposition_event_count=1,
        )
        assert_escrow_conserved(untouched)
        assert_dispute_case(
            read_dispute(api, opened["id"], scenario.w_id), status="EVIDENCE_COMPLETE"
        )


ASSIGNMENT_TERMS = {
    "purchase_price_cents": 18000000,
    "earnest_money_cents": 500000,
    "inspection_period_days": 7,
    "option_start_at": "2026-08-10T00:00:00Z",
    "closing_window_start_at": "2026-09-15T00:00:00Z",
    "closing_window_end_at": "2026-09-30T00:00:00Z",
}

SELLER_CANCELLATION_REASON = "Seller has decided to keep the property in the family"


def _buyer_at_baseline(api):
    """A verified buyer with no offers yet, on a contract ready to be marketed."""
    scenario = build_signed_contract(
        api, clock="2026-08-10T00:00:00Z", contract_kwargs=dict(ASSIGNMENT_TERMS)
    )
    scenario.contract = elect(api, scenario.pc_id, scenario.w_id, "ASSIGNMENT_ELECTED")
    add_verified_buyer(scenario)
    return scenario


def _seller_cancels(api, scenario):
    return validate_success(
        api.cancel_purchase_contract(
            scenario.pc_id,
            factories.cancel_payload(SELLER_CANCELLATION_REASON),
            make_seller_headers(scenario.lead_id),
        ),
        200,
    )


class TestBuyerCapitalReturnsToItsBaseline:
    """One offer encumbers the capital; the seller's walk-away releases it."""

    def test_seller_cancel_restores_committed_capital_exactly(self, api):
        """
        "The buyer's `committed_deposit_cents` is the sum of `buyer_deposit_cents`
        across their offers in a live negotiation status, `active_offer_count` is
        the count of those same offers, and `available_funds_cents` is verified
        funds less committed deposits."

        "`buyer_tier` is then `SUSPENDED` whenever `verified_funds_cents` is 0;
        otherwise it is `PRIORITY` when `available_funds_cents` is at least
        twenty-five million cents — two hundred and fifty thousand dollars, the
        threshold being inclusive — and `STANDARD` in every other case."

        "Three roles may cancel a contract — the `Wholesaler`, the `Seller`, and a
        `ComplianceOfficer` — and all three supply a single input, `reason`, which
        is recorded on the contract as `cancellation_reason`, alongside a
        `cancelled_at` stamped from the logical clock."

        "Seller-initiated and compliance-officer-initiated cancellation is not
        time-boxed at all; a seller may walk away, and a regulator may unwind a
        deal, at any point before it closes."

        Design: Difficulty/compensating_invariant/buyer_committed_capital_returns_to_baseline_after_seller_cancel
        """
        scenario = _buyer_at_baseline(api)
        baseline = read_buyer(api, scenario.buyer_id, scenario.w_id)
        assert_cash_buyer(
            baseline,
            verified_funds_cents=25500000,
            committed_deposit_cents=0,
            available_funds_cents=25500000,
            active_offer_count=0,
            buyer_tier="PRIORITY",
        )

        offer = submit_offer(
            api,
            scenario.pc_id,
            scenario.buyer_id,
            20000000,
            scenario.refresh_contract()["version"],
            buyer_deposit_cents=1000000,
        )
        # 24500000 is below the inclusive PRIORITY threshold of 25000000.
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            available_funds_cents=24500000,
            active_offer_count=1,
            buyer_tier="STANDARD",
        )
        accept_offer(api, offer["id"], scenario.w_id)
        # Acceptance alone releases nothing: ACCEPTED is still a live status.
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            available_funds_cents=24500000,
            active_offer_count=1,
            buyer_tier="STANDARD",
        )

        cancelled = _seller_cancels(api, scenario)

        assert_purchase_contract(
            cancelled,
            contract_status="CANCELLED",
            cancellation_reason=SELLER_CANCELLATION_REASON,
            cancelled_at="2026-08-10T00:00:00Z",
        )
        assert_assignment_offer(
            read_offer(api, offer["id"], scenario.w_id), status="LAPSED"
        )
        restored = read_buyer(api, scenario.buyer_id, scenario.w_id)
        assert_cash_buyer(
            restored,
            verified_funds_cents=25500000,
            committed_deposit_cents=0,
            available_funds_cents=25500000,
            active_offer_count=0,
            buyer_tier="PRIORITY",
        )
        for field in (
            "verified_funds_cents",
            "committed_deposit_cents",
            "available_funds_cents",
            "active_offer_count",
            "buyer_tier",
        ):
            assert restored[field] == baseline[field], (
                f"{field} drifted from its pre-offer baseline: "
                f"{baseline[field]!r} then {restored[field]!r}"
            )

    def test_the_cascade_moves_escrow_and_the_lead_but_never_verified_funds(self, api):
        """
        "The tier drives no pricing; it exists so that the desk can assert, after
        any cascade, that the buyer's capital picture is still coherent."

        "The earnest money deposit moves from `HELD` to
        `REFUNDED_TO_WHOLESALER`, transferring the whole of `held_cents` into
        `refunded_to_wholesaler_cents` and incrementing `disposition_event_count`
        by one — a wholesaler who cancels inside its inspection period gets its
        money back."

        "Finally, the owning lead returns from `UNDER_CONTRACT` to `SCREENED` when
        the cancelled contract was the lead's only non-terminal contract; where a
        non-overlapping backup contract remains live, the lead stays
        `UNDER_CONTRACT`."

        Design: Difficulty/compensating_invariant/buyer_committed_capital_returns_to_baseline_after_seller_cancel
        """
        scenario = _buyer_at_baseline(api)
        offer = submit_offer(
            api,
            scenario.pc_id,
            scenario.buyer_id,
            20000000,
            scenario.refresh_contract()["version"],
            buyer_deposit_cents=1000000,
        )
        accept_offer(api, offer["id"], scenario.w_id)
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="UNDER_CONTRACT"
        )
        verified_before = read_buyer(api, scenario.buyer_id, scenario.w_id)[
            "verified_funds_cents"
        ]

        _seller_cancels(api, scenario)

        deposit = find_deposit(api, scenario.pc_id, scenario.w_id)
        assert_earnest_money_deposit(
            deposit,
            status="REFUNDED_TO_WHOLESALER",
            amount_cents=500000,
            held_cents=0,
            refunded_to_wholesaler_cents=500000,
            forfeited_to_seller_cents=0,
            applied_at_closing_cents=0,
            disposition_event_count=1,
        )
        assert_escrow_conserved(deposit)
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="SCREENED"
        )
        after = read_buyer(api, scenario.buyer_id, scenario.w_id)
        assert_cash_buyer(after, verified_funds_cents=verified_before)
        assert after["verified_funds_cents"] == 25500000, (
            "the cascade recomputes committed and available capital but never "
            f"touches the verified figure: {after['verified_funds_cents']}"
        )
