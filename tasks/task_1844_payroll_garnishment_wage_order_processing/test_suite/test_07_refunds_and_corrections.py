"""Refunds and corrections: append-only REFUND events, remittance recompute
and auto-cancel, conserved order balance, refund bounds, audit chain growth."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_order_balance_conserved,
    get_order,
    get_remittance,
    get_success_data,
    list_order_events,
    refund_payload,
    setup_paid_single_order,
    setup_paid_two_orders,
    setup_pending_remittance,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import AUDITOR, MANAGER, SPECIALIST


class TestFullRefundAutoCancel:
    def _refund_full(self):
        base = setup_pending_remittance(
            order_overrides={"case_number": "CS-12", "amount_value": 10000},
        )
        refund = get_success_data(
            api_client.refund_order(
                base["order"]["id"],
                refund_payload(10000, base["run"]["id"]),
                MANAGER,
            )
        )
        return base, refund

    def test_full_refund_auto_cancels_pending_remittance(self, api):
        """PRD §3.8: "If the refunded `WITHHOLD` event had already been swept
        into a `PENDING` remittance, that remittance's `amount_due_cents` is
        recomputed, and if the effective total reaches zero the remittance
        auto-cancels to `CANCELLED` — the posture-driven path of §3.7."

        Design: Difficulty/non_linear_state_machine/remittance_posture_driven_cancel
        """
        base, refund = self._refund_full()
        assert refund["event_type"] == "REFUND"
        assert refund["amount_cents"] == -10000
        assert get_remittance(base["remittance"]["id"])["status"] == "CANCELLED"

    def test_full_refund_restores_order_ledger(self, api):
        """PRD §3.6: "Each order's `withheld_cents` accumulates its posted
        withholding, and its `remaining_balance_cents` is always the conserved
        ledger: `total_balance_cents` minus `withheld_cents` plus
        `refunded_cents`."
        Total 999999, withheld 10000, refunded 10000: remaining returns to
        999999 and the identity holds exactly.

        Design: Difficulty/non_linear_state_machine/remittance_posture_driven_cancel
        """
        base, refund = self._refund_full()
        order = get_order(base["order"]["id"])
        assert order["withheld_cents"] == 10000
        assert order["refunded_cents"] == 10000
        assert order["remaining_balance_cents"] == 999999
        assert_order_balance_conserved(order)


class TestPartialRefundCascade:
    def _setup_two_order_remittance_then_partial_refund(self):
        base = setup_paid_two_orders(
            order_a_overrides={"case_number": "CS-C", "amount_value": 4000},
            order_b_overrides={"case_number": "CS-D", "amount_value": 6000},
            statement_overrides={
                "gross_earnings_cents": 100000,
                "mandatory_deductions_cents": 20000,
            },
        )
        remittance = get_success_data(
            api_client.create_remittance(
                {
                    "employer_id": base["employer"]["id"],
                    "authority_id": base["authority"]["id"],
                    "payroll_run_id": base["run"]["id"],
                },
                SPECIALIST,
            )
        )
        assert remittance["amount_due_cents"] == 10000
        get_success_data(
            api_client.refund_order(
                base["order_a"]["id"],
                refund_payload(4000, base["run"]["id"]),
                MANAGER,
            )
        )
        return base, remittance

    def test_partial_refund_recomputes_amount_due(self, api):
        """PRD §3.8: "If the refunded `WITHHOLD` event had already been swept
        into a `PENDING` remittance, that remittance's `amount_due_cents` is
        recomputed, and if the effective total reaches zero the remittance
        auto-cancels to `CANCELLED` — the posture-driven path of §3.7."
        Only order C's 4000 is refunded out of a 10000 remittance: the
        effective total recomputes to 6000 and the remittance stays PENDING.

        Design: Difficulty/transitive_cascade/refund_cascade_breaks_remittance_and_audit
        """
        base, remittance = self._setup_two_order_remittance_then_partial_refund()
        rem = get_remittance(remittance["id"])
        assert rem["status"] == "PENDING"
        assert rem["amount_due_cents"] == 6000
        order_c = get_order(base["order_a"]["id"])
        assert order_c["withheld_cents"] == 4000
        assert order_c["refunded_cents"] == 4000
        assert_order_balance_conserved(order_c)

    def test_refund_extends_valid_audit_chain(self, api):
        """PRD §2.11: "Each entry stores a `prev_hash`: the `entry_hash` of the
        previous audit entry for that employer, or the literal `GENESIS` for
        the employer's first entry."
        PRD §2.11: "A caller may pass the `verify` query flag set to true on
        the employer-scoped audit listing to have the server recompute every
        `entry_hash` and re-walk every `prev_hash` link; the chain is valid
        only if every recomputed hash matches its stored value and every link
        points at its predecessor, and a mismatch is rejected with
        `ERR_AUDIT_CHAIN_BROKEN` (HTTP 409)."
        After the refund cascade (refund event + remittance recompute, each
        audited), the employer's chain still verifies and now includes
        order.refund entries.

        Design: Difficulty/transitive_cascade/refund_cascade_breaks_remittance_and_audit
        """
        base, remittance = self._setup_two_order_remittance_then_partial_refund()
        # The scenario writes 14 audit entries; fetch with an explicit limit
        # (PRD §2.3: limit defaults to 10, maximum 100) so the whole chain,
        # including the refund entry, is on the page under inspection.
        resp = api_client.list_employer_audit_log(
            base["employer"]["id"], AUDITOR,
            params={"verify": "true", "limit": 100},
        )
        entries, meta = validate_paginated(resp)
        assert entries, "audit log must not be empty"
        assert entries[0]["prev_hash"] == "GENESIS"
        for prev, cur in zip(entries, entries[1:]):
            assert cur["prev_hash"] == prev["entry_hash"], (
                "chain link broken between consecutive audit entries"
            )
        actions = [e["action"] for e in entries]
        assert "order.refund" in actions
        assert "remittance.create" in actions


class TestLumpSumConservation:
    def _setup_satisfied_lump_sum(self):
        return setup_paid_single_order(
            order_overrides={
                "case_number": "CS-M",
                "amount_model": "LUMP_SUM_BALANCE",
                "amount_value": 0,
                "total_balance_cents": 50000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 150000,
                "mandatory_deductions_cents": 30000,
            },
        )

    def test_lump_sum_pay_satisfies_order(self, api):
        """PRD §3.6: "a `LUMP_SUM_BALANCE` order demands its full
        `remaining_balance_cents`, unprorated."
        PRD §3.6: "When an award equals the order's remaining balance before
        the award, the order is satisfied on the spot: its `processing_status`
        becomes `SATISFIED`, its `remit_posture` closes, its final event
        carries the basis `FINAL_PARTIAL`, sibling orders on the same employee
        absorb the freed pool within the same waterfall pass without any
        re-run, and an audit entry (action `order.satisfy`) is appended."
        DE 120000, cap 60000, pool 72874 all exceed the 50000 balance: the
        award closes the order in one pass.

        Design: Difficulty/compensating_invariant/order_balance_conservation_under_withhold_and_refund
        """
        base = self._setup_satisfied_lump_sum()
        order = base["order"]
        assert order["processing_status"] == "SATISFIED"
        assert order["remit_posture"] == "CLOSED"
        assert order["withheld_cents"] == 50000
        assert order["remaining_balance_cents"] == 0
        assert_order_balance_conserved(order)
        events = list_order_events(order["id"])
        assert len(events) == 1
        assert events[0]["computation_proof"]["basis"] == "FINAL_PARTIAL"

    def test_refund_after_satisfaction_keeps_terminal_state(self, api):
        """PRD §3.8: "And if the order was already `SATISFIED`, the refund
        restores the conserved balance ledger but does not reopen the order:
        `SATISFIED` is terminal and stays so even when the refund pushes
        `remaining_balance_cents` back above zero."
        Refunding 20000 of the satisfied 50000 order: withheld stays 50000,
        refunded 20000, remaining 20000, and the identity
        total == withheld - refunded + remaining holds.

        Design: Difficulty/compensating_invariant/order_balance_conservation_under_withhold_and_refund
        """
        base = self._setup_satisfied_lump_sum()
        get_success_data(
            api_client.refund_order(
                base["order"]["id"],
                refund_payload(20000, base["run"]["id"]),
                MANAGER,
            )
        )
        order = get_order(base["order"]["id"])
        assert order["processing_status"] == "SATISFIED"
        assert order["withheld_cents"] == 50000
        assert order["refunded_cents"] == 20000
        assert order["remaining_balance_cents"] == 20000
        assert_order_balance_conserved(order)


class TestRefundBounds:
    def test_refund_exceeding_net_withheld_rejected(self, api):
        """PRD §3.8: "The amount may not exceed the order's net withheld — its
        `withheld_cents` minus its already-returned `refunded_cents` — and the
        order must have withheld something at all; either violation is rejected
        with `ERR_REFUND_EXCEEDS_WITHHELD` (HTTP 422)."
        Withheld 10000; a refund of 10001 is one cent over the bound.

        Design: Corner/validations/refund_exceeding_net_withheld_rejected
        """
        base = setup_paid_single_order(
            order_overrides={"case_number": "CS-RF", "amount_value": 10000}
        )
        assert base["order"]["withheld_cents"] == 10000
        resp = api_client.refund_order(
            base["order"]["id"],
            refund_payload(10001, base["run"]["id"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_WITHHELD)
        assert get_order(base["order"]["id"])["refunded_cents"] == 0


class TestOrderEventLog:
    def test_events_reverse_reachable_chronological(self, api):
        """PRD §3.8: "A refund appends a `REFUND` event to the order's log, its
        `amount_cents` recorded as a negative value, because the event log is
        append-only: a `WithholdingEvent` is never updated and never carries a
        `version`."
        PRD §3.8: "All events — withholdings and refunds alike — are
        retrievable per order, per run, per statement, or through a filtered
        listing accepting `garnishment_order_id`, `employer_id`,
        `payroll_run_id`, `pay_statement_id`, and `event_type`, with each
        event's `created_logical_at` recording when the logical clock stamped
        it."
        After a 10000 withhold and a 3000 refund, the order's event log reads
        [WITHHOLD +10000, REFUND -3000] in chronological order.

        Design: Corner/endpoints/order_events_reverse_reachable_chronological
        """
        base = setup_paid_single_order(
            order_overrides={"case_number": "CS-EV", "amount_value": 10000}
        )
        get_success_data(
            api_client.refund_order(
                base["order"]["id"],
                refund_payload(3000, base["run"]["id"]),
                MANAGER,
            )
        )
        events = list_order_events(base["order"]["id"])
        assert len(events) == 2
        assert events[0]["event_type"] == "WITHHOLD"
        assert events[0]["amount_cents"] == 10000
        assert events[1]["event_type"] == "REFUND"
        assert events[1]["amount_cents"] == -3000
        assert events[1]["created_logical_at"] >= events[0]["created_logical_at"]
        for e in events:
            assert "version" not in e
            assert "updated_at" not in e
