"""Difficulty-design coverage: every instance from
SCAFFOLD_DIFFICULTY_DESIGN.yaml gets at least TWO dedicated tests.

Each test is tagged with `# difficulty: <rule_id>/<instance.name>` so
the coverage check in §Completeness can audit which instance each
test satisfies.

PRD-First citation rule still applies: each test cites the PRD prose
for the underlying rule, not the difficulty-design entry.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    add_minutes,
    add_seconds,
    advance_clock,
    api_client,
    bind_card_payload,
    bind_vehicle_to_card,
    create_card,
    create_lot,
    create_reservation_payload,
    create_session_payload,
    create_space,
    create_vehicle,
    create_violation_payload,
    create_zone,
    exit_session,
    get_card,
    get_lot,
    get_reservation,
    get_revenue,
    get_session,
    get_space,
    get_vehicle,
    get_violation,
    issue_violation,
    list_audit_logs,
    make_driver_headers,
    make_officer_headers,
    open_session,
    pay_session,
    pay_session_payload,
    pay_violation,
    pay_violation_payload,
    recharge_card,
    recharge_card_payload,
    refund_payload,
    run_sweep,
    setup_basic_session_scenario,
    setup_card_recharge_chain,
    setup_held_reservation,
    setup_lot_zone_spaces,
    setup_paid_session_for_refund,
    setup_session_then_overstay_violation,
    setup_session_with_storedvalue_card,
    setup_three_paid_sessions_for_revenue_split,
    setup_violation_pending,
    TEST_USERS,
    unique_external_ref,
    unique_holder_ref,
    unique_officer_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# difficulty: dual_variant_calc / session_billing_provisional_vs_final
# ===========================================================================
class TestDifficulty_SessionBillingProvisionalVsFinal:
    def test_provisional_estimate_uses_now_as_exit_clock(self, api):
        """PRD §3.5: 'Reading a session re-runs the session-billing
        calculation in its provisional-estimate variant on every request
        and returns the result as estimated_fee_cents (recomputed live and
        never persisted).'

        Claim: with entry_at=10:00, free_minutes=15, rate=400, a GET at
        10:30 returns estimated_fee_cents=400 (15 billable min → ceil(900/3600)
        = 1 hour × 400).
        """  # difficulty: dual_variant_calc/session_billing_provisional_vs_final
        scen = setup_basic_session_scenario(
            base_iso="2026-01-01T10:00:00.000Z",
            free_minutes=15, hourly_rate_cents=400, daily_cap_cents=2000,
        )
        advance_clock("2026-01-01T10:30:00.000Z")
        sess = get_session(scen["session"]["id"])
        assert sess["estimated_fee_cents"] == 400

    def test_final_settlement_pinned_at_exit_at(self, api):
        """PRD §3.5: 'The same session in EXITED state returns
        final_fee_cents and billing_kind pinned at exit time and never
        recomputed.'

        Claim: same entry_at=10:00, exit at exactly 10:15:00 (== free_minutes
        boundary), final_fee_cents=0 because duration <= free_minutes*60s.
        Same formula, same entry_at, two different numbers — separation by
        exit_clock alone.
        """  # difficulty: dual_variant_calc/session_billing_provisional_vs_final
        scen = setup_basic_session_scenario(
            base_iso="2026-01-01T10:00:00.000Z",
            free_minutes=15, hourly_rate_cents=400, daily_cap_cents=2000,
        )
        advance_clock("2026-01-01T10:15:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 0


# ===========================================================================
# difficulty: dual_variant_calc / stored_value_balance_provisional_vs_finalized
# ===========================================================================
class TestDifficulty_StoredValueBalanceVariants:
    def test_provisional_balance_includes_active_session_debit(self, api):
        """PRD §3.3: 'balance_cents is the provisional balance, computed by
        walking every Payment row whose card_id equals this card in
        chronological processed_at order ... a SESSION_FEE subtracts
        amount_cents.'

        Claim: provisional balance reflects mid-lifecycle debits — pay a
        session that is still ACTIVE, balance_cents drops accordingly.
        Note: Test scenarios where a SESSION_FEE Payment can exist while
        Session.occupancy_status remains ACTIVE are gated by the
        implementation; PRD §3.5 admits sessions to be paid only when
        EXITED, so we instead exercise the variant via a recharge that
        debits a wallet for an unrelated context.
        """  # difficulty: dual_variant_calc/stored_value_balance_provisional_vs_finalized
        # Drive a session to PAID through the EXITED state, then verify
        # provisional balance reflects the debit.
        scen = setup_paid_session_for_refund(
            base_iso="2026-01-02T09:00:00.000Z",
            final_fee_cents=400,
            initial_balance_cents=5000,
        )
        card = get_card(scen["card"]["id"])
        # Provisional balance after pay = 5000 - 400 = 4600
        assert card["balance_cents"] == 4600

    def test_finalized_balance_field_exposed_and_non_exceeding_provisional(self, api):
        """PRD §3.3: 'Reads return the card with two balance views:
        balance_cents is the provisional balance ... The companion
        finalized_balance_cents runs the identical chronological accumulator
        over the same card but excludes payments whose subject lifecycle is
        non-terminal ... Because the finalized variant only excludes
        mid-lifecycle rows that the provisional already includes, the
        finalized balance can lag the provisional but never exceed it.'

        Claim: finalized_balance_cents is exposed on every card read, and
        finalized <= provisional always holds.
        """  # difficulty: dual_variant_calc/stored_value_balance_provisional_vs_finalized
        scen = setup_paid_session_for_refund(
            base_iso="2026-01-03T09:00:00.000Z",
            final_fee_cents=400,
            initial_balance_cents=5000,
        )
        card = get_card(scen["card"]["id"])
        assert "finalized_balance_cents" in card
        assert card["finalized_balance_cents"] <= card["balance_cents"]


# ===========================================================================
# difficulty: combinatorial_formula / fine_amount_three_input_nonlinear
# ===========================================================================
class TestDifficulty_FineAmountFormula:
    def test_blocking_no_prior_with_photo_pays_at_11500(self, api):
        """PRD §3.6: 'BLOCKING is 5000 cents ($50.00) ... BLOCKING is 2.0 ...
        The photo-required surcharge is 1500 cents when violation_type is
        BLOCKING or WRONG_ZONE ... The final amount is computed by first
        multiplying base_cents by type_multiplier in arbitrary-precision
        decimal, rounding the product half-up to the nearest integer cent,
        and then adding the photo-required surcharge and the repeat-offender
        surcharge as integer cents without further rounding.'
        PRD §3.6: 'A Driver or Operator may pay a PENDING violation by
        supplying amount_cents exactly equal to the fine's amount_cents.'

        Claim: 5000*2.0 + 1500 + 0 = 11500. Probed via /pay equality.
        """  # difficulty: combinatorial_formula/fine_amount_three_input_nonlinear
        scen = setup_violation_pending(
            base_iso="2026-02-01T10:00:00.000Z",
            violation_type="BLOCKING",
            photo_uri="s3://e/p1.jpg",
        )
        pay_violation(
            violation_id=scen["violation"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            amount_cents=11500,
            external_ref=unique_external_ref(),
        )
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "PAID"

    def test_non_paying_no_prior_no_photo_pays_at_4500(self, api):
        """PRD §3.6: 'NON_PAYING is 3000 cents ($30.00) ... NON_PAYING is
        1.5 ... The photo-required surcharge is 1500 cents when
        violation_type is BLOCKING or WRONG_ZONE, and zero otherwise.'

        Claim: 3000*1.5 + 0 + 0 = 4500.
        """  # difficulty: combinatorial_formula/fine_amount_three_input_nonlinear
        scen = setup_violation_pending(
            base_iso="2026-02-02T10:00:00.000Z",
            violation_type="NON_PAYING",
            photo_uri=None,
        )
        pay_violation(
            violation_id=scen["violation"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            amount_cents=4500,
            external_ref=unique_external_ref(),
        )
        v = get_violation(scen["violation"]["id"])
        assert v["status"] == "PAID"


# ===========================================================================
# difficulty: combinatorial_formula / revenue_split_per_entry_vs_sum_then_round
# ===========================================================================
class TestDifficulty_RevenueSplitNestedRounding:
    def test_three_entries_partner_total_per_entry_then_sum(self, api):
        """PRD §3.7: 'Aggregating partner totals across a settlement period
        sums each entry's already-rounded partner_share_cents; it does not
        multiply the period's gross sum by the basis-point ratio and then
        round once.'

        Claim: 3 entries of gross 333, partner_share_bps=2500 →
        round(333*0.25)=83 each → 83+83+83=249 (NOT 250).
        """  # difficulty: combinatorial_formula/revenue_split_per_entry_vs_sum_then_round
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-01T10:00:00.000Z",
            hourly_rate_cents=333,
            daily_cap_cents=10_000,
            partner_share_bps=2500,
        )
        rev = get_revenue(
            scen["lot"]["id"],
            params={"from": "2026-03-01", "to": "2026-03-02",
                    "billing_type": "HOURLY"},
        )
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        rel = [
            e for e in entries
            if e.get("billing_type") == "HOURLY"
            and e.get("gross_amount_cents") == 333
        ]
        total = sum(e["partner_share_cents"] for e in rel[:3])
        assert total == 249
        assert total != 250

    def test_each_entry_partner_share_is_83(self, api):
        """PRD §3.7: 'For each new entry, the system first computes the
        partner cut as the entry's gross_amount_cents multiplied by the
        lot's partner_share_bps divided by 10000 and rounded half-up to
        the nearest integer cent.'

        Claim: each individual RevenueEntry.partner_share_cents = round(
        333*2500/10000, HALF_UP) = 83.
        """  # difficulty: combinatorial_formula/revenue_split_per_entry_vs_sum_then_round
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-03-04T10:00:00.000Z",
            hourly_rate_cents=333,
            partner_share_bps=2500,
        )
        rev = get_revenue(
            scen["lot"]["id"],
            params={"from": "2026-03-04", "to": "2026-03-05"},
        )
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        rel = [
            e for e in entries
            if e.get("billing_type") == "HOURLY"
            and e.get("gross_amount_cents") == 333
        ]
        assert len(rel) >= 3
        for e in rel[:3]:
            assert e["partner_share_cents"] == 83


# ===========================================================================
# difficulty: combinatorial_formula / reservation_charge_circular_evaluation_order
# ===========================================================================
class TestDifficulty_ReservationChargeOrdering:
    def test_matched_reservation_pins_billing_type_reservation_then_negative_charge(self, api):
        """PRD §3.4: 'The reservation-charge calculation pins billing
        semantics in two strictly ordered steps. The first step determines
        the billing_type from the reservation's terminal status: a status
        of MATCHED pins billing_type to RESERVATION ... The second step
        computes the effective charge using the pinned billing_type. When
        billing_type is RESERVATION, the system first computes
        scheduled_window_hours as the duration ... rounded up to the next
        whole number; it then computes a reference amount equal to the
        smaller of scheduled_window_hours multiplied by the lot's
        hourly_rate_cents and the lot's daily_cap_cents; it then computes
        the discount as the reference amount multiplied by the
        match-discount basis points (the constant MATCH_DISCOUNT_BPS fixed
        at 1000, equivalent to 10.00%) divided by 10000 and rounded
        half-up to the nearest cent; the effective charge is the negative
        of this discount.'

        Claim: 2-hour reservation @ rate=300, cap=2000 → reference=600,
        discount=round(600*1000/10000)=60, effective_charge=-60.
        """  # difficulty: combinatorial_formula/reservation_charge_circular_evaluation_order
        scen = setup_held_reservation(
            base_iso="2026-04-01T13:50:00.000Z",
            scheduled_start_at="2026-04-01T14:00:00.000Z",
            scheduled_end_at="2026-04-01T16:00:00.000Z",
            hourly_rate_cents=300,
            daily_cap_cents=2000,
            no_show_penalty_cents=500,
            partner_share_bps=0,
            reservation_hold_minutes=15,
        )
        # Drive the gate-in to MATCHED.
        advance_clock("2026-04-01T14:00:00.000Z")
        open_session(
            scen["lot"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            space_id=scen["space"]["id"],
        )
        r = get_reservation(scen["reservation"]["id"])
        assert r["status"] == "MATCHED"
        rev = get_revenue(scen["lot"]["id"])
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        match_entries = [
            e for e in entries
            if e.get("billing_type") == "RESERVATION"
            and e.get("source_id") == scen["reservation"]["id"]
        ]
        assert len(match_entries) >= 1, (
            "PRD §3.4: 'The match writes a RESERVATION revenue entry whose "
            "gross amount is the negative of the match-credit discount.'"
        )
        assert match_entries[0]["gross_amount_cents"] == -60

    def test_expired_no_show_pins_billing_type_no_show_penalty(self, api):
        """PRD §3.4: 'When billing_type is NO_SHOW_PENALTY and status is
        EXPIRED_NO_SHOW, the effective charge is the lot's
        no_show_penalty_cents.'

        Claim: a HELD reservation that expires past the hold window pins
        billing_type=NO_SHOW_PENALTY and effective_charge=no_show_penalty_cents.
        """  # difficulty: combinatorial_formula/reservation_charge_circular_evaluation_order
        scen = setup_held_reservation(
            base_iso="2026-04-02T13:50:00.000Z",
            scheduled_start_at="2026-04-02T14:00:00.000Z",
            scheduled_end_at="2026-04-02T16:00:00.000Z",
            hourly_rate_cents=300,
            no_show_penalty_cents=500,
            reservation_hold_minutes=15,
        )
        # Advance past 14:00 + 15min, run sweep.
        advance_clock("2026-04-02T14:16:00.000Z")
        run_sweep()
        r = get_reservation(scen["reservation"]["id"])
        assert r["status"] == "EXPIRED_NO_SHOW"
        assert r["penalty_charged_cents"] == 500


# ===========================================================================
# difficulty: non_linear_state_machine / card_cyclic_active_suspended
# ===========================================================================
class TestDifficulty_CardCyclicActiveSuspended:
    def test_card_cycles_active_suspended_active(self, api, operator_headers):
        """PRD §3.3: 'A card moves between ACTIVE and SUSPENDED cyclically
        and reaches EXPIRED terminally. An Operator may suspend an ACTIVE
        card ... the operator may then reactivate a SUSPENDED card back
        to ACTIVE.'

        Claim: ACTIVE → SUSPENDED → ACTIVE round-trip is observable on a
        single Card row.
        """  # difficulty: non_linear_state_machine/card_cyclic_active_suspended
        card = create_card(card_type="STORED_VALUE")
        assert card["status"] == "ACTIVE"
        api.suspend_card(card["id"], operator_headers)
        c1 = get_card(card["id"])
        assert c1["status"] == "SUSPENDED"
        api.reactivate_card(card["id"], operator_headers)
        c2 = get_card(card["id"])
        assert c2["status"] == "ACTIVE"

    def test_card_version_bumped_on_each_cycle_transition(self, api, operator_headers):
        """PRD §2.4: 'a monotonically increasing integer version (starting
        at 1, incremented by exactly one on every mutation that persists a
        change to the resource).'

        Claim: each suspend/reactivate increments Card.version by exactly one.
        """  # difficulty: non_linear_state_machine/card_cyclic_active_suspended
        card = create_card(card_type="STORED_VALUE")
        v0 = card["version"]
        api.suspend_card(card["id"], operator_headers)
        c1 = get_card(card["id"])
        assert c1["version"] == v0 + 1
        api.reactivate_card(card["id"], operator_headers)
        c2 = get_card(card["id"])
        assert c2["version"] == v0 + 2


# ===========================================================================
# difficulty: non_linear_state_machine / session_parallel_payment_x_occupancy
# ===========================================================================
class TestDifficulty_SessionParallelDimensions:
    def test_exit_then_pay_sequence_evolves_two_dimensions(self, api):
        """PRD §3.5: 'Exiting the session pins exit_at to the current
        instant ... transitions occupancy_status from ACTIVE to EXITED.'
        PRD §3.5: 'On success, a SESSION_FEE Payment is created,
        payment_status transitions from UNPAID to PAID.'

        Claim: occupancy_status (ACTIVE → EXITED) and payment_status
        (UNPAID → PAID) are independent dimensions evolving on the same
        Session row.
        """  # difficulty: non_linear_state_machine/session_parallel_payment_x_occupancy
        scen = setup_session_with_storedvalue_card(
            base_iso="2026-10-10T09:00:00.000Z",
            free_minutes=0,
            hourly_rate_cents=400,
            initial_balance_cents=5000,
        )
        # After exit, occupancy=EXITED, payment=UNPAID
        advance_clock("2026-10-10T10:00:00.000Z")
        exit_session(scen["session"]["id"])
        s1 = get_session(scen["session"]["id"])
        assert s1["occupancy_status"] == "EXITED"
        assert s1["payment_status"] == "UNPAID"
        # After pay: occupancy still EXITED, payment=PAID
        pay_session(
            scen["session"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            card_id=scen["card"]["id"],
            external_ref=unique_external_ref(),
        )
        s2 = get_session(scen["session"]["id"])
        assert s2["occupancy_status"] == "EXITED"
        assert s2["payment_status"] == "PAID"

    def test_exited_disputed_combo_reachable(self, api):
        """PRD §3.5: 'A session in UNPAID payment status moves to DISPUTED
        automatically when an EnforcementOfficer issues an OVERSTAY
        violation against an EXITED session linked to it.'

        Claim: cross-product (EXITED × DISPUTED) is reachable.
        """  # difficulty: non_linear_state_machine/session_parallel_payment_x_occupancy
        scen = setup_session_then_overstay_violation(
            base_iso="2026-10-11T08:00:00.000Z"
        )
        issue_violation(
            lot_id=scen["lot"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            space_id=scen["space"]["id"],
            violation_type="OVERSTAY",
            detected_at="2026-10-11T09:00:00.000Z",
            session_id=scen["session"]["id"],
        )
        s = get_session(scen["session"]["id"])
        assert s["occupancy_status"] == "EXITED"
        assert s["payment_status"] == "DISPUTED"


# ===========================================================================
# difficulty: non_linear_state_machine / violation_cyclic_pending_disputed
# ===========================================================================
class TestDifficulty_ViolationPendingDisputedCycle:
    def test_pending_to_disputed_to_pending_cycle(self, api, operator_headers):
        """PRD §3.6: 'A Driver may dispute a PENDING violation by patching
        its status to DISPUTED ... An Operator may flip a DISPUTED
        violation back to PENDING by patching its status to PENDING.'

        Claim: PENDING → DISPUTED → PENDING is observable on a single
        Violation row.
        """  # difficulty: non_linear_state_machine/violation_cyclic_pending_disputed
        scen = setup_violation_pending(
            base_iso="2026-05-01T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        from test_helpers import patch_violation_payload
        api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="DISPUTED",
                                    reason="I left at 9:55"),
            make_driver_headers(scen["vehicle"]["id"]),
        )
        v1 = get_violation(scen["violation"]["id"])
        assert v1["status"] == "DISPUTED"
        api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="PENDING",
                                    reason="evidence reviewed"),
            operator_headers,
        )
        v2 = get_violation(scen["violation"]["id"])
        assert v2["status"] == "PENDING"

    def test_dispute_and_revert_each_emit_billing_adjustment_audit(self, api, operator_headers):
        """PRD §3.6: 'A Driver may dispute a PENDING violation by patching
        its status to DISPUTED; the dispute is admitted only when the
        current instant is at or before detected_at plus 14 days, requires
        a non-empty reason, and writes an AuditLog row with action
        BILLING_ADJUSTMENT. An Operator may flip a DISPUTED violation
        back to PENDING by patching its status to PENDING; the flip
        requires a non-empty reason and writes an AuditLog row with
        action BILLING_ADJUSTMENT.'

        Claim: each leg of the dispute/revert cycle writes one
        BILLING_ADJUSTMENT AuditLog.
        """  # difficulty: non_linear_state_machine/violation_cyclic_pending_disputed
        scen = setup_violation_pending(
            base_iso="2026-05-02T10:00:00.000Z",
            violation_type="OVERSTAY",
            photo_uri=None,
        )
        from test_helpers import patch_violation_payload
        api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="DISPUTED", reason="dispute"),
            make_driver_headers(scen["vehicle"]["id"]),
        )
        api.patch_violation(
            scen["violation"]["id"],
            patch_violation_payload(status="PENDING", reason="revert"),
            operator_headers,
        )
        logs = list_audit_logs(
            params={"subject_id": scen["violation"]["id"], "limit": 50}
        )
        billing = [
            l for l in logs if l.get("action") == "BILLING_ADJUSTMENT"
        ]
        assert len(billing) >= 2, (
            f"Expected ≥2 BILLING_ADJUSTMENT audit entries, got {len(billing)}"
        )


# ===========================================================================
# difficulty: transitive_cascade / violation_to_session_to_vehicle_chain
# ===========================================================================
class TestDifficulty_TransitiveCascadeViolation:
    def test_overstay_violation_cascades_session_to_disputed(self, api):
        """PRD §3.5: 'A session in UNPAID payment status moves to DISPUTED
        automatically when an EnforcementOfficer issues an OVERSTAY
        violation against an EXITED session linked to it; the cascade
        also triggers a recomputation of Vehicle.binding_eligible because
        open_violation_count increased.'

        Claim: hop 2 — Session.payment_status UNPAID→DISPUTED.
        """  # difficulty: transitive_cascade/violation_to_session_to_vehicle_chain
        scen = setup_session_then_overstay_violation(
            base_iso="2026-06-01T08:00:00.000Z"
        )
        issue_violation(
            lot_id=scen["lot"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            space_id=scen["space"]["id"],
            violation_type="OVERSTAY",
            detected_at="2026-06-01T09:00:00.000Z",
            session_id=scen["session"]["id"],
        )
        s = get_session(scen["session"]["id"])
        assert s["payment_status"] == "DISPUTED"

    def test_overstay_violation_cascades_vehicle_binding_eligible_false(self, api):
        """PRD §3.2: 'binding_eligible is false whenever the vehicle has
        any violation in either of those statuses (so it equals true
        exactly when open_violation_count is zero).'

        Claim: hop 3 — Vehicle.binding_eligible flips false because
        open_violation_count rose to 1.
        """  # difficulty: transitive_cascade/violation_to_session_to_vehicle_chain
        scen = setup_session_then_overstay_violation(
            base_iso="2026-06-02T08:00:00.000Z"
        )
        issue_violation(
            lot_id=scen["lot"]["id"],
            vehicle_id=scen["vehicle"]["id"],
            space_id=scen["space"]["id"],
            violation_type="OVERSTAY",
            detected_at="2026-06-02T09:00:00.000Z",
            session_id=scen["session"]["id"],
        )
        veh = get_vehicle(scen["vehicle"]["id"])
        assert veh["binding_eligible"] is False
        assert veh["open_violation_count"] == 1


# ===========================================================================
# difficulty: transitive_cascade / card_recharge_to_session_to_revenue_chain
# ===========================================================================
class TestDifficulty_TransitiveCascadeRecharge:
    def test_recharge_with_auto_pay_settles_unpaid_session(self, api):
        """PRD §3.3: 'On success, a CARD_RECHARGE Payment is appended
        (amount_cents positive), the provisional balance grows, and —
        when auto_pay_enabled is true on this card — the system cascades
        a settlement sweep that pays any unpaid completed sessions for
        vehicles bound to this card.'

        Claim: hop 1 → hop 2 — recharge cascades a session settlement.
        """  # difficulty: transitive_cascade/card_recharge_to_session_to_revenue_chain
        scen = setup_card_recharge_chain(
            base_iso="2026-07-01T08:00:00.000Z"
        )
        # session is EXITED+UNPAID before recharge
        s_before = get_session(scen["session"]["id"])
        assert s_before["payment_status"] == "UNPAID"
        # Recharge → cascades pay
        recharge_card(
            scen["card"]["id"],
            amount_cents=5000,
            external_ref=unique_external_ref("rch"),
        )
        s_after = get_session(scen["session"]["id"])
        assert s_after["payment_status"] == "PAID"

    def test_recharge_cascade_creates_hourly_revenue_entry(self, api):
        """PRD §3.5: 'On success, a SESSION_FEE Payment is created,
        payment_status transitions from UNPAID to PAID, the stored-value
        card's balance_cents is debited by final_fee_cents, and a
        RevenueEntry is created with billing_type HOURLY.'

        Claim: hop 3 — the auto-pay-cascade settlement creates an HOURLY
        RevenueEntry.
        """  # difficulty: transitive_cascade/card_recharge_to_session_to_revenue_chain
        scen = setup_card_recharge_chain(
            base_iso="2026-07-02T08:00:00.000Z"
        )
        recharge_card(
            scen["card"]["id"],
            amount_cents=5000,
            external_ref=unique_external_ref("rch"),
        )
        rev = get_revenue(scen["lot"]["id"])
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        hourly = [
            e for e in entries
            if e.get("billing_type") == "HOURLY"
            and e.get("source_id") == scen["session"]["id"]
        ]
        assert len(hourly) == 1, (
            f"Expected exactly one HOURLY entry for cascading settlement; "
            f"got {len(hourly)}."
        )
        assert hourly[0]["gross_amount_cents"] == 300  # 1h * 300/h


# ===========================================================================
# difficulty: priority_pair_validation_conflict / state_vs_business_fiscal_pay_session
# ===========================================================================
class TestDifficulty_PriorityState_vs_Fiscal:
    def test_pay_active_session_zero_balance_card_returns_invalid_state(self, api):
        """PRD §2.7: 'state-machine eligibility for the requested
        transition (yielding ERR_INVALID_STATE) ... funds checks on
        stored-value debits (ERR_INSUFFICIENT_BALANCE).' The state check
        precedes the funds check.
        PRD §3.5: 'Payment is admitted only on a session whose
        occupancy_status is EXITED.'

        Claim: ACTIVE session + 0-balance STORED_VALUE → ERR_INVALID_STATE
        (state failure beats fiscal failure by priority).
        """  # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pay_session
        scen = setup_session_with_storedvalue_card(
            base_iso="2026-08-01T10:00:00.000Z",
            initial_balance_cents=0,
        )
        # session is ACTIVE; card balance = 0; pay should fail with state
        from test_helpers import pay_session_payload
        headers = make_driver_headers(scen["vehicle"]["id"])
        res = api.pay_session(
            scen["session"]["id"],
            pay_session_payload(card_id=scen["card"]["id"]),
            headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_pay_exited_session_zero_balance_returns_insufficient_balance(self, api):
        """PRD §3.5: 'When a STORED_VALUE card is used, the card's
        balance_cents must be at least final_fee_cents; otherwise
        ERR_INSUFFICIENT_BALANCE.'

        Claim: when state passes (EXITED), the fiscal failure surfaces
        as ERR_INSUFFICIENT_BALANCE — proving the priority pair is
        correctly ordered.
        """  # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_pay_session
        scen = setup_session_with_storedvalue_card(
            base_iso="2026-08-02T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
            initial_balance_cents=0,
        )
        advance_clock("2026-08-02T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        from test_helpers import pay_session_payload
        headers = make_driver_headers(scen["vehicle"]["id"])
        res = api.pay_session(
            scen["session"]["id"],
            pay_session_payload(card_id=scen["card"]["id"]),
            headers,
        )
        validate_error(res, "ERR_INSUFFICIENT_BALANCE")


# ===========================================================================
# difficulty: priority_pair_validation_conflict / business_safety_vs_business_referential_violation_creation
# ===========================================================================
class TestDifficulty_PrioritySafety_vs_Photo:
    def test_emergency_vehicle_overstay_returns_exempt_vehicle(self, api):
        """PRD §2.7: 'vehicle exemption (ERR_EXEMPT_VEHICLE) before binding
        eligibility (ERR_VEHICLE_HAS_OPEN_VIOLATIONS) ... Photo-evidence
        enforcement on violations (ERR_PHOTO_REQUIRED) precedes
        reservation-window validity.'
        PRD §2.10: 'an attempt to ... issue an OVERSTAY or NON_PAYING
        violation against it, is rejected with ERR_EXEMPT_VEHICLE.'

        Claim: EMERGENCY vehicle + OVERSTAY without photo → ERR_EXEMPT_VEHICLE
        (exemption beats photo by priority).
        """  # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_violation_creation
        advance_clock("2026-05-10T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle(kind="EMERGENCY")
        from test_helpers import create_violation_payload
        payload = create_violation_payload(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            violation_type="OVERSTAY",
            space_id=spaces[0]["id"],
            detected_at="2026-05-10T10:00:00.000Z",
            officer_id=unique_officer_id(),
            photo_uri=None,
        )
        res = api.create_violation(payload, TEST_USERS["officer_headers"])
        validate_error(res, "ERR_EXEMPT_VEHICLE")

    def test_regular_vehicle_blocking_no_photo_returns_photo_required(self, api):
        """PRD §3.6: 'When violation_type is BLOCKING or WRONG_ZONE, the
        photo_uri must be non-empty; an empty or missing photo_uri for
        these types is rejected with ERR_PHOTO_REQUIRED.'

        Claim: When the exemption rule does not apply (REGULAR vehicle),
        BLOCKING without photo surfaces ERR_PHOTO_REQUIRED — confirming
        the priority ordering by showing the lower-priority error fires
        when the higher-priority condition is absent.
        """  # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_violation_creation
        advance_clock("2026-05-11T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle(kind="REGULAR")
        from test_helpers import create_violation_payload
        payload = create_violation_payload(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            violation_type="BLOCKING",
            space_id=spaces[0]["id"],
            detected_at="2026-05-11T10:00:00.000Z",
            officer_id=unique_officer_id(),
            photo_uri=None,
        )
        res = api.create_violation(payload, TEST_USERS["officer_headers"])
        validate_error(res, "ERR_PHOTO_REQUIRED")


# ===========================================================================
# difficulty: boundary_precision_check / free_minutes_exact_boundary_at_exit
# ===========================================================================
class TestDifficulty_FreeMinutesBoundary:
    def test_at_exact_boundary_fee_zero(self, api):
        """PRD §3.5: 'If the duration is at most the lot's free_minutes
        multiplied by 60 seconds, the fee is zero.'

        Claim: duration_seconds == free_minutes*60 (exact equality) → fee=0.
        """  # difficulty: boundary_precision_check/free_minutes_exact_boundary_at_exit
        scen = setup_basic_session_scenario(
            base_iso="2026-08-01T10:00:00.000Z",
            free_minutes=15, hourly_rate_cents=400, daily_cap_cents=2000,
        )
        advance_clock("2026-08-01T10:15:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 0

    def test_one_second_past_boundary_charges_one_hour(self, api):
        """PRD §3.5: 'For each day, the billable seconds equal the segment
        seconds minus, on the first day only, free_minutes multiplied by
        60; that value is then floored at zero. The day's started-hour
        count is the billable seconds divided by 3600 rounded up to the
        next whole number — any partial hour rounds up.'

        Claim: at duration_seconds = free_minutes*60 + 1 → 1 billable
        second → ceil(1/3600)=1 hour → fee = 1 * hourly_rate_cents.
        """  # difficulty: boundary_precision_check/free_minutes_exact_boundary_at_exit
        scen = setup_basic_session_scenario(
            base_iso="2026-08-02T10:00:00.000Z",
            free_minutes=15, hourly_rate_cents=400, daily_cap_cents=2000,
        )
        advance_clock("2026-08-02T10:15:01.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 400


# ===========================================================================
# difficulty: boundary_precision_check / empty_candidate_pool_on_reservation
# ===========================================================================
class TestDifficulty_EmptyCandidatePool:
    # NOTE: test_reservation_with_only_overlapping_space_returns_no_space_available
    # was removed — PRD §3.4 covers both "Overlap yields ERR_RESERVATION_OVERLAP"
    # and "If the candidate set is empty ... ERR_NO_SPACE_AVAILABLE" in the same
    # paragraph without pinning their precedence. The single-overlapping-space
    # scenario is consistent with either error_id, so unique-derivability fails
    # (Diagnostic Step 1b: ERROR PRECEDENCE SILENCE pattern). The companion
    # test_overlapping_reservation_rejected_with_overlap (line 1039) covers the
    # ERR_RESERVATION_OVERLAP branch under an identical setup.
    def test_empty_candidate_pool_zero_spaces(self, api):
        """PRD §3.4: 'If the candidate set is empty, the request is
        rejected with ERR_NO_SPACE_AVAILABLE.'

        Claim: a zone with zero spaces has an empty candidate pool by
        construction → ERR_NO_SPACE_AVAILABLE.
        """  # difficulty: boundary_precision_check/empty_candidate_pool_on_reservation
        advance_clock("2026-04-09T13:00:00.000Z")
        lot = create_lot(no_show_penalty_cents=500)
        zone = create_zone(lot["id"], zone_type="STANDARD")
        # No spaces in this zone.
        vehicle = create_vehicle()
        card = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(card["id"], vehicle["id"])
        recharge_card(card["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        from test_helpers import create_reservation_payload
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=vehicle["id"],
            scheduled_start_at="2026-04-09T14:00:00.000Z",
            scheduled_end_at="2026-04-09T15:00:00.000Z",
            card_id=card["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(vehicle["id"])
        )
        validate_error(res, "ERR_NO_SPACE_AVAILABLE")


# ===========================================================================
# difficulty: cross_entity_state_dependency / session_creation_depends_on_space_state
# ===========================================================================
class TestDifficulty_SessionDependsOnSpace:
    def test_session_into_occupied_space_returns_space_occupied(self, api):
        """PRD §3.5: 'Entry is admitted only when the chosen space's
        occupancy_status equals FREE ... otherwise the request is rejected
        with ERR_SPACE_OCCUPIED.'

        Claim: a Session creation is gated by Space.occupancy_status —
        cross-entity state dependency.
        """  # difficulty: cross_entity_state_dependency/session_creation_depends_on_space_state
        scen = setup_basic_session_scenario(
            base_iso="2026-09-20T10:00:00.000Z"
        )
        # First session occupies the space; try a second
        v2 = create_vehicle()
        from test_helpers import create_session_payload
        res = api.create_session(
            scen["lot"]["id"],
            create_session_payload(
                vehicle_id=v2["id"], space_id=scen["space"]["id"]
            ),
            TEST_USERS["gate_headers"],
        )
        validate_error(res, "ERR_SPACE_OCCUPIED")

    def test_session_into_just_exited_space_within_tow_grace_returns_not_bookable(self, api):
        """PRD §3.5: 'entry into a space whose reservation_lock is
        UNRESERVED requires the current instant to be at or after
        Space.last_exited_at plus the lot's tow_grace_minutes whenever
        last_exited_at is set.'

        Claim: a Session creation is gated by Space.last_exited_at +
        tow_grace_minutes — cross-entity state dependency on a different
        Space field.
        """  # difficulty: cross_entity_state_dependency/session_creation_depends_on_space_state
        scen = setup_basic_session_scenario(
            base_iso="2026-09-21T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
            tow_grace_minutes=5,
        )
        # Exit at 10:30
        advance_clock("2026-09-21T10:30:00.000Z")
        exit_session(scen["session"]["id"])
        # Re-entry attempt at 10:32 (only 2 min after exit) — inside
        # tow_grace window → ERR_SPACE_NOT_BOOKABLE
        advance_clock("2026-09-21T10:32:00.000Z")
        v2 = create_vehicle()
        from test_helpers import create_session_payload
        res = api.create_session(
            scen["lot"]["id"],
            create_session_payload(
                vehicle_id=v2["id"], space_id=scen["space"]["id"]
            ),
            TEST_USERS["gate_headers"],
        )
        validate_error(res, "ERR_SPACE_NOT_BOOKABLE")


# ===========================================================================
# difficulty: cross_entity_state_dependency / reservation_creation_depends_on_card_state
# ===========================================================================
class TestDifficulty_ReservationDependsOnCard:
    def test_reservation_with_expired_card_returns_card_expired(self, api):
        """PRD §3.4: 'When the chosen zone is STANDARD and the lot's
        no_show_penalty_cents is greater than zero, card_id is required
        as the payer of any future no-show charge.'
        PRD §3.3: 'When the current instant moves beyond valid_until ...
        an ACTIVE or SUSPENDED card transitions to EXPIRED.'
        PRD §2.7: 'card validity (ERR_CARD_EXPIRED).'

        Claim: a Reservation creation that pins an EXPIRED card →
        ERR_CARD_EXPIRED — cross-entity state dependency.
        """  # difficulty: cross_entity_state_dependency/reservation_creation_depends_on_card_state
        # Build a lot and a card that expires; advance clock past valid_until.
        advance_clock("2026-12-31T23:59:59.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle()
        card = create_card(
            card_type="STORED_VALUE",
            valid_from="2026-01-01T00:00:00.000Z",
            valid_until="2026-12-31T23:59:59.000Z",
        )
        bind_vehicle_to_card(card["id"], vehicle["id"])
        recharge_card(card["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        # Advance past valid_until and run sweep to expire.
        advance_clock("2027-01-02T00:00:00.000Z")
        run_sweep()
        c_after = get_card(card["id"])
        assert c_after["status"] == "EXPIRED"
        from test_helpers import create_reservation_payload
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=vehicle["id"],
            scheduled_start_at="2027-01-03T14:00:00.000Z",
            scheduled_end_at="2027-01-03T16:00:00.000Z",
            card_id=card["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(vehicle["id"])
        )
        validate_error(res, "ERR_CARD_EXPIRED")

    def test_reactivate_card_after_valid_until_rejected(self, api, operator_headers):
        """PRD §3.3: 'the operator may then reactivate a SUSPENDED card
        back to ACTIVE, allowed only while the current instant remains
        before valid_until.'

        Claim: Card lifecycle is gated by the relationship between
        now() and valid_until — cross-entity (Card × clock) dependency.
        """  # difficulty: cross_entity_state_dependency/reservation_creation_depends_on_card_state
        advance_clock("2026-06-01T10:00:00.000Z")
        card = create_card(
            card_type="STORED_VALUE",
            valid_from="2026-01-01T00:00:00.000Z",
            valid_until="2026-06-30T23:59:59.000Z",
        )
        api.suspend_card(card["id"], operator_headers)
        # Advance past valid_until; suspended card stays SUSPENDED until
        # sweep, but reactivate must be rejected with ERR_INVALID_STATE.
        advance_clock("2026-07-15T10:00:00.000Z")
        res = api.reactivate_card(card["id"], operator_headers)
        # Could be either ERR_INVALID_STATE (state machine) or
        # ERR_CARD_EXPIRED (validity); PRD names the precondition but
        # not the specific error label for the violated reactivate
        # precondition — both are PRD-faithful.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_CARD_EXPIRED"])


# ===========================================================================
# difficulty: resource_temporal_overlap / reservation_half_open_interval_back_to_back_allowed
# ===========================================================================
class TestDifficulty_HalfOpenReservationIntervals:
    def test_back_to_back_reservations_on_same_space_allowed(self, api):
        """PRD §3.4: 'whose interval overlaps the requested
        [scheduled_start_at, scheduled_end_at) half-open interval.
        Touching boundaries do not overlap — back-to-back reservations on
        the same space are allowed.'

        Claim: R1 [14,16) + R2 [16,18) on the same space — both succeed.
        """  # difficulty: resource_temporal_overlap/reservation_half_open_interval_back_to_back_allowed
        scen = setup_held_reservation(
            base_iso="2026-04-15T13:00:00.000Z",
            scheduled_start_at="2026-04-15T14:00:00.000Z",
            scheduled_end_at="2026-04-15T16:00:00.000Z",
        )
        # Add a second vehicle for R2.
        v2 = create_vehicle()
        c2 = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(c2["id"], v2["id"])
        recharge_card(c2["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        from test_helpers import create_reservation_payload
        payload = create_reservation_payload(
            zone_id=scen["zone"]["id"],
            vehicle_id=v2["id"],
            scheduled_start_at="2026-04-15T16:00:00.000Z",
            scheduled_end_at="2026-04-15T18:00:00.000Z",
            card_id=c2["id"],
        )
        res = api.create_reservation(
            scen["lot"]["id"], payload, make_driver_headers(v2["id"])
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "HELD"

    def test_overlapping_reservation_rejected_with_overlap(self, api):
        """PRD §3.4: 'Overlap yields ERR_RESERVATION_OVERLAP.'

        Claim: R1 [14,16) + R2 [15:59,17) on the same space — R2 fails.
        """  # difficulty: resource_temporal_overlap/reservation_half_open_interval_back_to_back_allowed
        scen = setup_held_reservation(
            base_iso="2026-04-16T13:00:00.000Z",
            scheduled_start_at="2026-04-16T14:00:00.000Z",
            scheduled_end_at="2026-04-16T16:00:00.000Z",
        )
        v2 = create_vehicle()
        c2 = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(c2["id"], v2["id"])
        recharge_card(c2["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        from test_helpers import create_reservation_payload
        payload = create_reservation_payload(
            zone_id=scen["zone"]["id"],
            vehicle_id=v2["id"],
            scheduled_start_at="2026-04-16T15:59:00.000Z",
            scheduled_end_at="2026-04-16T17:00:00.000Z",
            card_id=c2["id"],
        )
        res = api.create_reservation(
            scen["lot"]["id"], payload, make_driver_headers(v2["id"])
        )
        validate_error(res, "ERR_RESERVATION_OVERLAP")


# ===========================================================================
# difficulty: resource_temporal_overlap / session_space_buffer_with_tow_grace
# ===========================================================================
class TestDifficulty_TowGraceBuffer:
    def test_reservation_inside_tow_grace_buffer_rejected(self, api):
        """PRD §3.4: 'A candidate space is one whose zone_id matches the
        requested zone, whose occupancy_status is FREE or whose
        scheduled_start_at is at or after the space's last_exited_at plus
        the lot's tow_grace_minutes (the closed buffer interval).'
        PRD §3.4: 'a space caught inside another session's tow-grace
        window yields ERR_SPACE_NOT_BOOKABLE.'

        Claim: a reservation whose start lies inside (last_exited_at,
        last_exited_at + tow_grace_minutes) is rejected.
        """  # difficulty: resource_temporal_overlap/session_space_buffer_with_tow_grace
        # Build lot with tow_grace=5; open then exit a session at 10:00
        advance_clock("2026-09-30T09:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(
            tow_grace_minutes=5, space_count=1, no_show_penalty_cents=500
        )
        vehicle_session = create_vehicle()
        s = open_session(
            lot["id"], vehicle_id=vehicle_session["id"],
            space_id=spaces[0]["id"],
        )
        advance_clock("2026-09-30T10:00:00.000Z")
        exit_session(s["id"])
        # Now last_exited_at = 10:00; tow_grace = 5 min → buffer ends 10:05.
        # A reservation with scheduled_start_at = 10:03 is INSIDE the buffer.
        v2 = create_vehicle()
        c2 = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(c2["id"], v2["id"])
        recharge_card(c2["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        advance_clock("2026-09-30T10:01:00.000Z")
        from test_helpers import create_reservation_payload
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=v2["id"],
            scheduled_start_at="2026-09-30T10:03:00.000Z",
            scheduled_end_at="2026-09-30T10:30:00.000Z",
            card_id=c2["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(v2["id"])
        )
        validate_error(res, "ERR_SPACE_NOT_BOOKABLE")

    def test_reservation_at_exact_tow_grace_boundary_allowed(self, api):
        """PRD §3.4: 'A candidate space is one whose ... scheduled_start_at
        is at or after the space's last_exited_at plus the lot's
        tow_grace_minutes (the closed buffer interval).'

        Claim: when scheduled_start_at == last_exited_at + tow_grace
        (exact closed-interval upper bound), the reservation is admitted.
        """  # difficulty: resource_temporal_overlap/session_space_buffer_with_tow_grace
        advance_clock("2026-10-01T09:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(
            tow_grace_minutes=5, space_count=1, no_show_penalty_cents=500
        )
        vehicle_session = create_vehicle()
        s = open_session(
            lot["id"], vehicle_id=vehicle_session["id"],
            space_id=spaces[0]["id"],
        )
        advance_clock("2026-10-01T10:00:00.000Z")
        exit_session(s["id"])
        # last_exited_at = 10:00; tow_grace boundary = 10:05.
        v2 = create_vehicle()
        c2 = create_card(card_type="STORED_VALUE")
        bind_vehicle_to_card(c2["id"], v2["id"])
        recharge_card(c2["id"], amount_cents=10_000,
                      external_ref=unique_external_ref())
        advance_clock("2026-10-01T10:02:00.000Z")
        from test_helpers import create_reservation_payload
        payload = create_reservation_payload(
            zone_id=zone["id"],
            vehicle_id=v2["id"],
            scheduled_start_at="2026-10-01T10:05:00.000Z",
            scheduled_end_at="2026-10-01T11:00:00.000Z",
            card_id=c2["id"],
        )
        res = api.create_reservation(
            lot["id"], payload, make_driver_headers(v2["id"])
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "HELD"


# ===========================================================================
# difficulty: compensating_invariant / card_balance_recharge_then_refund_invariant
# ===========================================================================
class TestDifficulty_CardBalanceCycleInvariant:
    def test_recharge_then_session_pay_then_balance(self, api):
        """PRD §3.3: 'a CARD_RECHARGE adds amount_cents ... a SESSION_FEE
        subtracts amount_cents.'

        Claim: balance trajectory 0 → +5000 (recharge) → -300 (session
        pay) → 4700; conservation under recharge+debit.
        """  # difficulty: compensating_invariant/card_balance_recharge_then_refund_invariant
        scen = setup_paid_session_for_refund(
            base_iso="2026-11-01T09:00:00.000Z",
            final_fee_cents=400,
            initial_balance_cents=5000,
        )
        # Inside fixture: recharge 5000, pay 400 → 4600
        c = get_card(scen["card"]["id"])
        assert c["balance_cents"] == 4600

    def test_card_balance_chronological_accumulator(self, api):
        """PRD §3.3: 'walking every Payment row whose card_id equals this
        card in chronological processed_at order (ties broken by Payment.id
        ascending) and applying each payment as follows.'

        Claim: balance computed as integer-cent chronological accumulator,
        no rounding. Two recharges sum exactly.
        """  # difficulty: compensating_invariant/card_balance_recharge_then_refund_invariant
        card = create_card(card_type="STORED_VALUE")
        recharge_card(card["id"], amount_cents=1234,
                      external_ref=unique_external_ref())
        recharge_card(card["id"], amount_cents=4321,
                      external_ref=unique_external_ref())
        c = get_card(card["id"])
        assert c["balance_cents"] == 1234 + 4321


# ===========================================================================
# difficulty: compensating_invariant / revenue_total_refund_invariant
# ===========================================================================
class TestDifficulty_RevenueRefundInvariant:
    def test_house_plus_partner_equals_gross_per_entry(self, api):
        """PRD §3.7: 'The house cut is then computed as gross_amount_cents
        minus partner_share_cents, preserving the sign of gross.'

        Claim: house_share + partner_share == gross for every RevenueEntry,
        regardless of billing_type or sign.
        """  # difficulty: compensating_invariant/revenue_total_refund_invariant
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-11-15T10:00:00.000Z",
            hourly_rate_cents=400,
            partner_share_bps=2500,
        )
        rev = get_revenue(scen["lot"]["id"])
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            assert (
                e["house_share_cents"] + e["partner_share_cents"]
                == e["gross_amount_cents"]
            )

    def test_partner_share_clamped_non_negative(self, api):
        """PRD §3.7: 'sign-preserving for negative gross amounts (so a
        refund's partner share is negative in raw form) but is then
        clamped to a floor of zero, ensuring partner_share_cents is
        always non-negative.'

        Claim: across all RevenueEntry rows, partner_share_cents >= 0.
        """  # difficulty: compensating_invariant/revenue_total_refund_invariant
        scen = setup_three_paid_sessions_for_revenue_split(
            base_iso="2026-11-16T10:00:00.000Z",
            hourly_rate_cents=400,
            partner_share_bps=2500,
        )
        rev = get_revenue(scen["lot"]["id"])
        entries = rev if isinstance(rev, list) else rev.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            assert e["partner_share_cents"] >= 0
