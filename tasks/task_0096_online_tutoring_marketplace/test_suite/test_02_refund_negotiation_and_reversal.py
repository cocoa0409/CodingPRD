"""Refund negotiation, arbitration, and settlement reversal.

Covers the negotiated-vs-arbitrated grant divergence, the pinned-order
settlement reversal with clawback, the cyclic negotiation loop, and the
money-conservation invariant across settle + full refund.
"""
from test_helpers import (
    TEST_USERS,
    consume_trial_slot,
    create_booking,
    deliver_booking,
    open_refund_case,
    settlement_for_session,
    setup_confirmed_standard_session,
    setup_marketplace,
    setup_open_refund_case,
    validate_success,
)


class TestNegotiatedVsArbitratedGrant:
    def test_negotiated_grant_equals_tutor_offer(self, api):
        """PRD §3.9: "When the case is `TUTOR_COUNTERED`, the parent accepting the
        counter advances it to `AGREED` and sets `granted_amount_cents` to
        `tutor_offer_cents`."

        Design: Difficulty/dual_variant_calc/negotiated_vs_arbitrated_refund_grant_diverges
        """
        mk, std_session, case = setup_open_refund_case(claimed_amount_cents=2000)
        countered = validate_success(
            api.counter_refund_case(
                case["id"],
                {"counter_amount_cents": 1000, "expected_refund_case_version": case["version"]},
                mk["tutor_headers"],
            )
        )
        agreed = validate_success(
            api.accept_counter_refund_case(
                case["id"], {"expected_refund_case_version": countered["version"]}, mk["parent_headers"]
            )
        )
        assert agreed["granted_amount_cents"] == 1000

    def test_arbitrated_grant_equals_award_and_penalizes_tutor(self, api):
        """PRD §3.9: "A `ruling` of `REFUND` requires an `awarded_amount_cents`
        strictly greater than zero and no greater than the current
        `parent_offer_cents`; it sets `granted_amount_cents` to the awarded amount,
        applies the settlement reversal, advances the case to the terminal
        `RESOLVED_REFUND`, and applies an acute reliability penalty to the tutor
        that the negotiated path does not impose."

        Design: Difficulty/dual_variant_calc/negotiated_vs_arbitrated_refund_grant_diverges
        """
        # Negotiated case A first (no penalty), capture reliability.
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        consume_trial_slot(mk)
        # Create both standard bookings BEFORE advancing the clock past their starts.
        book_a = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=60)
        book_b = create_booking(mk, "2026-06-03T12:00:00Z", planned_minutes=60)
        sess_a = deliver_booking(mk, book_a["id"], 60, "2026-06-03T14:00:00Z")
        validate_success(api.confirm_session(sess_a["id"], mk["parent_headers"]))
        sess_b = deliver_booking(mk, book_b["id"], 60, "2026-06-03T14:00:00Z")
        validate_success(api.confirm_session(sess_b["id"], mk["parent_headers"]))

        case_a = open_refund_case(mk, sess_a["id"], 2000)
        countered_a = validate_success(
            api.counter_refund_case(case_a["id"], {"counter_amount_cents": 1000, "expected_refund_case_version": case_a["version"]}, mk["tutor_headers"])
        )
        validate_success(
            api.accept_counter_refund_case(case_a["id"], {"expected_refund_case_version": countered_a["version"]}, mk["parent_headers"])
        )
        tutor_after_a = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))

        # Arbitrated case B. PRD §3.9: a round is "a parent proposal followed by a
        # tutor counter", round_count increments on re-proposal, and escalation is
        # allowed only "provided round_count is at least 1". One bare counter leaves
        # round_count at 0 (cf. test_counter_sets_tutor_offer_and_advances_state), so
        # drive counter -> re-propose (round_count -> 1) before escalating.
        case_b = open_refund_case(mk, sess_b["id"], 2000)
        countered_b = validate_success(
            api.counter_refund_case(case_b["id"], {"counter_amount_cents": 800, "expected_refund_case_version": case_b["version"]}, mk["tutor_headers"])
        )
        # Re-propose within [tutor_offer=800, parent_offer=2000]; this completes one
        # round and returns the case to PARENT_PROPOSED with round_count == 1.
        reproposed_b = validate_success(
            api.repropose_refund_case(case_b["id"], {"new_offer_cents": 1600, "expected_refund_case_version": countered_b["version"]}, mk["parent_headers"])
        )
        assert reproposed_b["round_count"] == 1
        validate_success(api.escalate_refund_case(case_b["id"], mk["parent_headers"]))
        # Arbitration award 1500 stays at/under the current parent_offer_cents (1600).
        arbitrated = validate_success(
            api.arbitrate_refund_case(
                case_b["id"], {"ruling": "REFUND", "awarded_amount_cents": 1500}, TEST_USERS["arbiter_headers"]
            )
        )
        assert arbitrated["granted_amount_cents"] == 1500

        tutor_after_b = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        # Arbitrated REFUND applies an acute penalty the negotiated path did not.
        assert tutor_after_b["reliability_score"] < tutor_after_a["reliability_score"]


class TestSettlementReversalOrder:
    def test_full_refund_short_balance_yields_clawback(self, api):
        """PRD §3.9.1: "the amount debited from the tutor's balance is the smaller
        of the granted amount and the tutor's current `payout_balance_cents`, read
        before any mutation in this reversal. Third, the clawback is the granted
        amount minus that debited amount — the remainder owed when the balance was
        short."
        PRD §3.9.1: "the settlement's `status` becomes `REVERSED` when
        `refunded_cents` has reached the full `gross_amount_cents`".

        Design: Difficulty/combinatorial_formula/settlement_reversal_order_pinned_clawback
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000, wallet_cents=100000)
        # Trial slot consumed by a NO_SHOW booking (never settles -> no balance).
        no_show_booking = create_booking(mk, "2026-06-02T08:00:00Z", planned_minutes=30)
        validate_success(api.set_clock({"to_iso8601": "2026-06-02T09:00:00Z"}, TEST_USERS["platform_admin_headers"]))
        validate_success(api.mark_no_show(no_show_booking["id"], mk["tutor_headers"]))

        # One standard session settled: gross 6000, net 4500; payout_balance == 4500.
        std_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=60)
        std_session = deliver_booking(mk, std_booking["id"], 60, "2026-06-03T11:00:00Z")
        validate_success(api.confirm_session(std_session["id"], mk["parent_headers"]))

        parent_before = validate_success(api.get_parent_account(mk["parent"]["id"], mk["parent_headers"]))

        case = open_refund_case(mk, std_session["id"], 6000)
        accepted = validate_success(
            api.accept_offer_refund_case(case["id"], {"expected_refund_case_version": case["version"]}, mk["tutor_headers"])
        )
        assert accepted["granted_amount_cents"] == 6000

        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        # debit = min(6000, 4500) = 4500 -> balance 0; clawback = 6000 - 4500 = 1500.
        assert tutor["payout_balance_cents"] == 0
        assert tutor["clawback_owed_cents"] == 1500

        settle = settlement_for_session(std_session["id"])
        assert settle["refunded_cents"] == 6000
        assert settle["status"] == "REVERSED"

        parent_after = validate_success(api.get_parent_account(mk["parent"]["id"], mk["parent_headers"]))
        assert parent_after["wallet_balance_cents"] - parent_before["wallet_balance_cents"] == 6000

    def test_partial_refund_within_balance_no_clawback(self, api):
        """PRD §3.9.1: "the tutor's `payout_balance_cents` decreases by the debited
        amount, and the tutor's `clawback_owed_cents` increases by the clawback."
        PRD §3.9.1: "the settlement's `refunded_cents` increases by the granted
        amount, and the settlement's `status` becomes `REVERSED` when
        `refunded_cents` has reached the full `gross_amount_cents` and
        `PARTIALLY_REVERSED` otherwise."

        Design: Difficulty/combinatorial_formula/settlement_reversal_order_pinned_clawback
        """
        # Standard session settled, gross 6000, net 4500. Refund only 2000 (< balance).
        mk, std_booking, std_session = setup_confirmed_standard_session(std_planned_minutes=60, std_actual_minutes=60)
        case = open_refund_case(mk, std_session["id"], 2000)
        validate_success(
            api.accept_offer_refund_case(case["id"], {"expected_refund_case_version": case["version"]}, mk["tutor_headers"])
        )
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        # debit = min(2000, balance) = 2000; clawback 0.
        assert tutor["clawback_owed_cents"] == 0
        settle = settlement_for_session(std_session["id"])
        assert settle["refunded_cents"] == 2000
        assert settle["status"] == "PARTIALLY_REVERSED"


class TestCyclicNegotiationLoop:
    def test_repropose_loops_back_to_parent_proposed(self, api):
        """PRD §3.9: "Re-proposing supplies `new_offer_cents`, which must be at
        least the current `tutor_offer_cents` and at most the current
        `parent_offer_cents` ... advances the case back to `PARENT_PROPOSED`, sets
        `parent_offer_cents` to the new offer, and increments `round_count`".

        Design: Difficulty/non_linear_state_machine/refund_case_cyclic_negotiation_loop
        """
        mk, std_session, case = setup_open_refund_case(claimed_amount_cents=2000)
        countered = validate_success(
            api.counter_refund_case(case["id"], {"counter_amount_cents": 800, "expected_refund_case_version": case["version"]}, mk["tutor_headers"])
        )
        looped = validate_success(
            api.repropose_refund_case(case["id"], {"new_offer_cents": 1500, "expected_refund_case_version": countered["version"]}, mk["parent_headers"])
        )
        assert looped["status"] == "PARENT_PROPOSED"
        assert looped["round_count"] == 1
        assert looped["parent_offer_cents"] == 1500

    def test_counter_sets_tutor_offer_and_advances_state(self, api):
        """PRD §3.9: "a counter supplies `counter_amount_cents`, which must be less
        than or equal to the current `parent_offer_cents`, advances the case to
        `TUTOR_COUNTERED`, sets `tutor_offer_cents`".

        Design: Difficulty/non_linear_state_machine/refund_case_cyclic_negotiation_loop
        """
        mk, std_session, case = setup_open_refund_case(claimed_amount_cents=2000)
        countered = validate_success(
            api.counter_refund_case(case["id"], {"counter_amount_cents": 800, "expected_refund_case_version": case["version"]}, mk["tutor_headers"])
        )
        assert countered["status"] == "TUTOR_COUNTERED"
        assert countered["tutor_offer_cents"] == 800
        assert countered["round_count"] == 0


class TestMoneyConservation:
    def test_full_refund_conserves_money_no_clawback(self, api):
        """PRD §2.9: "Every booking hold, settlement debit, payout credit, and
        refund reversal moves money between these balances such that no cent is
        created or destroyed."
        PRD §3.9.1: "the parent's `wallet_balance_cents` increases by the parent
        credit, the tutor's `payout_balance_cents` decreases by the debited amount".

        Design: Difficulty/compensating_invariant/wallet_money_conserved_across_settle_and_full_refund
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000, wallet_cents=100000)
        # Trial settled: gross 3000, net 1500 (commission 1500).
        trial_booking = create_booking(mk, "2026-06-02T08:00:00Z", planned_minutes=30)
        trial_session = deliver_booking(mk, trial_booking["id"], 30, "2026-06-02T09:00:00Z")
        validate_success(api.confirm_session(trial_session["id"], mk["parent_headers"]))
        # Standard settled: gross 6000, net 4500 (commission 1500). Tutor balance 6000.
        std_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=60)
        std_session = deliver_booking(mk, std_booking["id"], 60, "2026-06-03T11:00:00Z")
        validate_success(api.confirm_session(std_session["id"], mk["parent_headers"]))

        case = open_refund_case(mk, std_session["id"], 6000)
        validate_success(
            api.accept_offer_refund_case(case["id"], {"expected_refund_case_version": case["version"]}, mk["tutor_headers"])
        )

        parent = validate_success(api.get_parent_account(mk["parent"]["id"], mk["parent_headers"]))
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        # 100000 - 3000 - 6000 + 6000 refund == 97000.
        assert parent["wallet_balance_cents"] == 97000
        # Full 6000 refund covered by 6000 balance: clawback 0, balance 0.
        assert tutor["payout_balance_cents"] == 0
        assert tutor["clawback_owed_cents"] == 0
        # Conservation: parent_wallet + tutor_balance + commission_retained(3000) - clawback == 100000.
        commission_retained = 1500 + 1500
        assert (
            parent["wallet_balance_cents"]
            + tutor["payout_balance_cents"]
            + commission_retained
            - tutor["clawback_owed_cents"]
        ) == 100000

    def test_full_refund_marks_settlement_reversed_and_session_refunded(self, api):
        """PRD §3.9.1: "the settlement's `refunded_cents` increases by the granted
        amount, and the settlement's `status` becomes `REVERSED` when
        `refunded_cents` has reached the full `gross_amount_cents`".
        PRD §3.9.1: "the linked session's `settlement_status` is moved to
        `REFUNDED` when the settlement has been fully reversed".

        Design: Difficulty/compensating_invariant/wallet_money_conserved_across_settle_and_full_refund
        """
        # Standard session gross 6000, net 4500; tutor balance 6000 (trial 1500 + std 4500).
        mk = setup_marketplace(base_hourly_rate_cents=6000, wallet_cents=100000)
        trial_booking = create_booking(mk, "2026-06-02T08:00:00Z", planned_minutes=30)
        trial_session = deliver_booking(mk, trial_booking["id"], 30, "2026-06-02T09:00:00Z")
        validate_success(api.confirm_session(trial_session["id"], mk["parent_headers"]))
        std_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=60)
        std_session = deliver_booking(mk, std_booking["id"], 60, "2026-06-03T11:00:00Z")
        validate_success(api.confirm_session(std_session["id"], mk["parent_headers"]))

        case = open_refund_case(mk, std_session["id"], 6000)
        validate_success(
            api.accept_offer_refund_case(case["id"], {"expected_refund_case_version": case["version"]}, mk["tutor_headers"])
        )
        settle = settlement_for_session(std_session["id"])
        assert settle["refunded_cents"] == 6000
        assert settle["status"] == "REVERSED"
        session_after = validate_success(api.get_session(std_session["id"], mk["parent_headers"]))
        assert session_after["settlement_status"] == "REFUNDED"
