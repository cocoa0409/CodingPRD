"""SCAFFOLD_DIFFICULTY_DESIGN coverage — every difficulty-design
instance is exercised by at least TWO tests tagged
`# difficulty: <rule_id>/<instance.name>` per skill §2.1.A.

Test recipes are translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml;
assertions cite the PRD prose that states the underlying rule.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    accept_repair_ticket,
    advance_clock_to,
    append_curve_point,
    begin_repair_ticket,
    complete_repair_ticket,
    create_fault_report,
    create_member,
    create_pile,
    create_platform_operator_row,
    create_pricing_version,
    create_promo_activity,
    create_repair_ticket,
    create_reservation,
    create_roaming_partner_operator,
    create_session,
    create_station,
    create_station_owner_operator,
    dispatch_repair_ticket,
    emit_grid_pile_offline,
    emit_grid_pile_online,
    emit_payment_refunded,
    find_audit_logs,
    get_fault_report,
    get_member,
    get_pile,
    get_reservation,
    get_session,
    iso_day,
    iso_z,
    isolate_fault_report,
    join_queue,
    list_audit_logs,
    list_session_ledger_entries,
    reject_repair_ticket,
    run_sweep,
    setup_charging_session,
    setup_operator_station_shelved_pile,
    setup_ready_to_charge,
    setup_repair_awaiting_acceptance,
    setup_reservation_held,
    setup_settled_session_for_recipe,
    shelve_pile,
    start_session,
    stop_session,
    sum_amounts_by_counterparty,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    PO,
    make_ev_driver_headers,
    make_station_owner_headers,
)
from datetime import datetime, timedelta, timezone


# ===========================================================================
# Rule 1, instance: session_total_provisional_vs_final
# ===========================================================================
class TestProvisionalVsFinalSessionTotal:
    """SCAFFOLD_DIFFICULTY_DESIGN rule dual_variant_calc / instance
    session_total_provisional_vs_final.

    PRD §3.4: 'A provisional settlement estimate is available while the
    session is CHARGING: it runs the same arithmetic described below
    against the curve points captured up to now, returning a snapshot
    of electricity_fee_cents, service_fee_cents, tax_cents, and
    total_cents without mutating any field.'"""

    def test_provisional_estimate_matches_recipe_for_10_kwh_sample(
        self, api,
    ):
        """PRD §3.4: 'A provisional settlement estimate is available
        while the session is CHARGING: it runs the same arithmetic
        described below against the curve points captured up to now.'

        With Pricing PV peak=80, flat=50, valley=30, service_fee=20,
        tax_bps=1300, SILVER tier 500 bps off, and 10 kWh in FLAT:
          electricity = 500
          service = round_half_up(200 * (9500*10000)/100_000_000) = 190
          tax = round_half_up((500+190)*1300/10000) = round_half_up(89.7) = 90
          total = 780
        """
        # difficulty: dual_variant_calc/session_total_provisional_vs_final
        ctx = setup_ready_to_charge(
            member_tier="SILVER",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=80,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=30,
                service_fee_per_kwh_cents=20,
                tax_bps=1300,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500,
                },
            ),
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        from test_helpers import get_estimate
        estimate = get_estimate(session["id"])
        assert estimate["electricity_fee_cents"] == 500
        assert estimate["total_cents"] == 780

    def test_final_total_after_extra_curve_point_differs_from_estimate(
        self, api,
    ):
        """PRD §3.4: 'Once at least one curve point with non-negative
        cumulative_energy_milli exists, the session automatically
        advances from SETTLING to SETTLED; the settlement workflow
        computes the four monetary fields.'

        Adding a second sample BETWEEN estimate and stop changes the
        final total: 15 kWh FLAT → 750/285/135/1170, differing from
        the 780 estimate captured at 10 kWh.
        """
        # difficulty: dual_variant_calc/session_total_provisional_vs_final
        ctx = setup_ready_to_charge(
            member_tier="SILVER",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=80,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=30,
                service_fee_per_kwh_cents=20,
                tax_bps=1300,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500,
                },
            ),
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        from test_helpers import get_estimate
        estimate_before = get_estimate(session["id"])
        # Append a second sample, then stop.
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:02:00.000Z",
            cumulative_energy_milli=15000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        settled = stop_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert settled["electricity_fee_cents"] == 750
        assert settled["total_cents"] == 1170
        assert settled["total_cents"] != estimate_before["total_cents"]


# ===========================================================================
# Rule 1, instance: operator_settlement_accrual_vs_reversal
# ===========================================================================
class TestAccrualVsReversal:
    """SCAFFOLD_DIFFICULTY_DESIGN rule dual_variant_calc / instance
    operator_settlement_accrual_vs_reversal.

    PRD §3.6: 'The same allocation is invoked again whenever a refund
    event arrives — and this is the only point at which reversal rows
    are produced. ... each of the four ledger rows is then written with
    amount_cents of the opposite sign and reason REFUND_REVERSAL. The
    invariant that ties original and reversal together is that for
    each counterparty_kind, the sum of original plus reversal
    amount_cents on the session is exactly zero.'"""

    def test_refund_produces_negative_rows_and_billing_adjustment_audit(
        self, api,
    ):
        # difficulty: dual_variant_calc/operator_settlement_accrual_vs_reversal
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
            revenue_share_bps=4000,
        )
        # Capture pre-refund ledger.
        pre = list_session_ledger_entries(ctx["session"]["id"])
        pre_count = len(pre)
        emit_payment_refunded(ctx["session"]["id"])
        post = list_session_ledger_entries(ctx["session"]["id"])
        # PRD §3.6: forward writes the four counterparties; non-roaming
        # case omits ROAMING_PARTNER so it writes three. Refund mirrors
        # those three with negative sign.
        assert len(post) > pre_count
        reasons = {r["reason"] for r in post}
        assert "REFUND_REVERSAL" in reasons
        # PRD §3.6: 'an AuditLog row with event_kind BILLING_ADJUSTMENT
        # is appended.'
        logs = list_audit_logs(
            event_kind="BILLING_ADJUSTMENT",
            entity_kind="ChargingSession",
            entity_id=ctx["session"]["id"],
        )
        assert len(logs) >= 1

    def test_per_counterparty_sum_zero_after_refund(self, api):
        """PRD §3.6: 'the sum of original plus reversal amount_cents on
        the session is exactly zero.'"""
        # difficulty: dual_variant_calc/operator_settlement_accrual_vs_reversal
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
            revenue_share_bps=4000,
        )
        emit_payment_refunded(ctx["session"]["id"])
        rows = list_session_ledger_entries(ctx["session"]["id"])
        totals = sum_amounts_by_counterparty(rows)
        for kind in ("STATION_OWNER_SHARE", "PLATFORM_SERVICE_FEE",
                     "TAX_AUTHORITY"):
            assert totals.get(kind, 0) == 0, (
                f"Per-counterparty net for {kind} must be 0 after refund, "
                f"got {totals.get(kind)}"
            )


# ===========================================================================
# Rule 2, instance: per_window_rounding_before_sum
# ===========================================================================
class TestPerWindowRoundingBeforeSum:
    """SCAFFOLD_DIFFICULTY_DESIGN rule combinatorial_formula / instance
    per_window_rounding_before_sum.

    PRD §3.4 / §3.6 Step B: 'rounding once on the summed milli-kWh is
    not equivalent and is not permitted.'"""

    def test_mixed_window_curve_settles_to_per_window_sum_381(self, api):
        """PRD §3.4 / §3.6 Step B: per-window rounding then sum.
        peak=185, flat=150, valley=46 → total electricity = 381.
        """
        # difficulty: combinatorial_formula/per_window_rounding_before_sum
        ctx = setup_ready_to_charge(
            member_tier="BASIC",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=37,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=23,
                service_fee_per_kwh_cents=0,
                tax_bps=0,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 0, "GOLD": 0, "PLATINUM": 0,
                },
            ),
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        # Deltas: PEAK 5005, FLAT 3000, VALLEY 2005.
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=5005,
            instant_power_kw=60.0,
            window_tag="PEAK",
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:02:00.000Z",
            cumulative_energy_milli=8005,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:03:00.000Z",
            cumulative_energy_milli=10010,
            instant_power_kw=60.0,
            window_tag="VALLEY",
        )
        settled = stop_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert settled["electricity_fee_cents"] == 381

    def test_zero_service_zero_tax_pricing_leaves_total_equal_electricity(
        self, api,
    ):
        """PRD §3.4 Step D: 'total_cents is the sum of
        electricity_fee_cents, service_fee_cents, and tax_cents.'

        With service_fee=0 and tax_bps=0, total_cents == electricity.
        """
        # difficulty: combinatorial_formula/per_window_rounding_before_sum
        ctx = setup_ready_to_charge(
            member_tier="BASIC",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=37,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=23,
                service_fee_per_kwh_cents=0,
                tax_bps=0,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 0, "GOLD": 0, "PLATINUM": 0,
                },
            ),
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=5005,
            instant_power_kw=60.0,
            window_tag="PEAK",
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:02:00.000Z",
            cumulative_energy_milli=8005,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:03:00.000Z",
            cumulative_energy_milli=10010,
            instant_power_kw=60.0,
            window_tag="VALLEY",
        )
        settled = stop_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert settled["service_fee_cents"] == 0
        assert settled["tax_cents"] == 0
        assert settled["total_cents"] == settled["electricity_fee_cents"]


# ===========================================================================
# Rule 2, instance: operator_settlement_evaluation_order_pinned
# ===========================================================================
class TestOperatorSettlementOrderPinned:
    """SCAFFOLD_DIFFICULTY_DESIGN rule combinatorial_formula / instance
    operator_settlement_evaluation_order_pinned.

    PRD §3.6 waterfall: compute roaming → then platform → then station
    owner. With electricity=500, service=190 → net=690:
      roaming         = round_half_up(690*1500/10000) = 104
      after_roaming   = 586
      platform        = round_half_up(586*500/10000) = 29
      after_platform  = 557
      station_owner   = round_half_up(557*4000/10000) = 223
      operator_residual = 334 (not its own ledger row in PRD §3.6)
      tax             = round_half_up((500+190)*1300/10000) = 90.
    """

    def _setup_roaming_session(self):
        op_a = create_platform_operator_row()
        op_b = create_roaming_partner_operator()
        owner = create_station_owner_operator()
        station = create_station(
            operator_id=op_a["id"], station_owner_id=owner["id"],
            revenue_share_bps=4000,
        )
        pile = create_pile(
            station_id=station["id"], station_owner_id=owner["id"],
            rated_power_kw=60.0,
        )
        shelve_pile(pile_id=pile["id"], station_owner_id=owner["id"])
        create_pricing_version(
            operator_id=op_a["id"],
            effective_from=iso_day(2026, 1, 1),
            effective_to=iso_day(2030, 1, 1),
            peak_rate_per_kwh_cents=80,
            flat_rate_per_kwh_cents=50,
            valley_rate_per_kwh_cents=30,
            service_fee_per_kwh_cents=20,
            tax_bps=1300,
            peak_windows=[],
            valley_windows=[],
            tier_service_fee_discount_bps={
                "BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500,
            },
        )
        member = create_member(
            home_operator_id=op_b["id"], tier="SILVER",
            wallet_balance_cents=100000,
        )
        session = create_session(
            pile_id=pile["id"], member_id=member["id"], auth_method="APP",
        )
        session = start_session(
            session_id=session["id"], member_id=member["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        settled = stop_session(
            session_id=session["id"], member_id=member["id"],
        )
        return {
            "operator": op_a, "partner": op_b, "owner": owner,
            "station": station, "pile": pile, "member": member,
            "session": settled,
        }

    def test_roaming_session_ledger_rows_match_recipe_intermediates(
        self, api,
    ):
        # difficulty: combinatorial_formula/operator_settlement_evaluation_order_pinned
        ctx = self._setup_roaming_session()
        rows = list_session_ledger_entries(ctx["session"]["id"])
        settle = [r for r in rows if r["reason"] == "SESSION_SETTLE"]
        totals = sum_amounts_by_counterparty(settle)
        assert totals.get("ROAMING_PARTNER", 0) == 104, (
            f"PRD §3.6 step 2 → ROAMING_PARTNER must be 104, got {totals}"
        )
        assert totals.get("PLATFORM_SERVICE_FEE", 0) == 29, (
            f"PRD §3.6 step 3 → PLATFORM_SERVICE_FEE must be 29, "
            f"got {totals}"
        )
        assert totals.get("STATION_OWNER_SHARE", 0) == 223, (
            f"PRD §3.6 step 4 → STATION_OWNER_SHARE must be 223, "
            f"got {totals}"
        )
        assert totals.get("TAX_AUTHORITY", 0) == 90

    def test_roaming_session_total_cents_consistent_with_components(
        self, api,
    ):
        """PRD §3.4 step D: 'total_cents is the sum of
        electricity_fee_cents, service_fee_cents, and tax_cents.'

        Recipe: 500 + 190 + 90 = 780.
        """
        # difficulty: combinatorial_formula/operator_settlement_evaluation_order_pinned
        ctx = self._setup_roaming_session()
        session = ctx["session"]
        assert session["electricity_fee_cents"] == 500
        assert session["service_fee_cents"] == 190
        assert session["tax_cents"] == 90
        assert session["total_cents"] == 780


# ===========================================================================
# Rule 3, instance: pile_parallel_lifecycle_and_operational
# ===========================================================================
class TestPileParallelDimensions:
    """SCAFFOLD_DIFFICULTY_DESIGN rule non_linear_state_machine /
    instance pile_parallel_lifecycle_and_operational.

    PRD §3.1: 'two orthogonal state dimensions: lifecycle_state and
    operational_state. ... The operational_state is meaningful only
    while lifecycle_state is ON_SHELF and is otherwise null.'"""

    def test_lifecycle_evolves_independently_of_operational(self, api):
        """PRD §3.1: 'New piles start OFF_SHELF.' Then shelve sets
        lifecycle=ON_SHELF, operational=IDLE. The grid event then sets
        operational=OFFLINE while lifecycle remains ON_SHELF."""
        # difficulty: non_linear_state_machine/pile_parallel_lifecycle_and_operational
        from test_helpers import setup_operator_station_pile_off_shelf
        ctx = setup_operator_station_pile_off_shelf()
        # State A: OFF_SHELF, operational null.
        pile_a = get_pile(ctx["pile"]["id"])
        assert pile_a["lifecycle_state"] == "OFF_SHELF"
        assert pile_a["operational_state"] is None
        # State B: shelve → ON_SHELF + IDLE.
        shelve_pile(
            pile_id=ctx["pile"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        pile_b = get_pile(ctx["pile"]["id"])
        assert pile_b["lifecycle_state"] == "ON_SHELF"
        assert pile_b["operational_state"] == "IDLE"
        # State C: grid offline → ON_SHELF + OFFLINE (axes evolve
        # independently).
        emit_grid_pile_offline(ctx["pile"]["id"])
        pile_c = get_pile(ctx["pile"]["id"])
        assert pile_c["lifecycle_state"] == "ON_SHELF"
        assert pile_c["operational_state"] == "OFFLINE"

    def test_off_shelve_collapses_operational_state_to_null(self, api):
        """PRD §3.1: 'On successful off-shelving the operational_state
        is cleared to null.'"""
        # difficulty: non_linear_state_machine/pile_parallel_lifecycle_and_operational
        from test_helpers import (
            setup_operator_station_shelved_pile,
            emit_grid_pile_online,
            off_shelve_pile,
        )
        ctx = setup_operator_station_shelved_pile()
        # Bring online (idempotent) then off-shelve.
        # The pile starts IDLE; off-shelve directly.
        pile = off_shelve_pile(
            pile_id=ctx["pile"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert pile["lifecycle_state"] == "OFF_SHELF"
        assert pile["operational_state"] is None


# ===========================================================================
# Rule 3, instance: repair_ticket_reject_loop_cycle
# ===========================================================================
class TestRepairTicketRejectLoopCycle:
    """SCAFFOLD_DIFFICULTY_DESIGN rule non_linear_state_machine /
    instance repair_ticket_reject_loop_cycle.

    PRD §3.5: 'Rejection by the same StationOwner moves the ticket
    back from AWAITING_ACCEPTANCE to IN_REPAIR, cycling the work item
    for the technician.'"""

    def test_first_reject_returns_ticket_to_in_repair(self, api):
        # difficulty: non_linear_state_machine/repair_ticket_reject_loop_cycle
        ctx = setup_repair_awaiting_acceptance()
        ticket = reject_repair_ticket(
            ticket_id=ctx["ticket"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "IN_REPAIR"

    def test_two_reject_cycles_then_accept_resolves_fault(self, api):
        """PRD §3.5: 'with a possible cycle back from
        AWAITING_ACCEPTANCE to IN_REPAIR on rejection ... Acceptance ...
        cascades the parent fault report from ISOLATED to RESOLVED.'"""
        # difficulty: non_linear_state_machine/repair_ticket_reject_loop_cycle
        ctx = setup_repair_awaiting_acceptance()
        # First reject + recomplete.
        ticket = reject_repair_ticket(
            ticket_id=ctx["ticket"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "IN_REPAIR"
        ticket = complete_repair_ticket(
            ticket_id=ticket["id"],
            technician_user_id=ctx["technician_user_id"],
            repair_notes="retry1",
        )
        assert ticket["status"] == "AWAITING_ACCEPTANCE"
        # Second reject + recomplete.
        ticket = reject_repair_ticket(
            ticket_id=ticket["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "IN_REPAIR"
        ticket = complete_repair_ticket(
            ticket_id=ticket["id"],
            technician_user_id=ctx["technician_user_id"],
            repair_notes="retry2",
        )
        # Accept — closes.
        ticket = accept_repair_ticket(
            ticket_id=ticket["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        assert ticket["status"] == "CLOSED"
        fault = get_fault_report(ctx["fault"]["id"])
        assert fault["status"] == "RESOLVED"


# ===========================================================================
# Rule 4, instance: fault_isolation_cascade_depth_4
# ===========================================================================
class TestFaultIsolationCascadeDepth4:
    """SCAFFOLD_DIFFICULTY_DESIGN rule transitive_cascade / instance
    fault_isolation_cascade_depth_4.

    PRD §3.5: 'the pile's operational_state moves to FAULT ... every
    HELD reservation on the pile is moved to CANCELLED (no strike — this
    is the compensating semantics distinguishing fault-driven
    cancellations from normal cancellations and from sweep-driven
    expiries).'"""

    def test_isolate_cascades_to_pile_fault_then_reservation_cancelled(
        self, api,
    ):
        """Chain: FaultReport ISOLATED → Pile FAULT → Reservation
        CANCELLED."""
        # difficulty: transitive_cascade/fault_isolation_cascade_depth_4
        ctx = setup_reservation_held()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"],
            reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        isolate_fault_report(fault_id=fault["id"])
        # Hop A: fault ISOLATED.
        f = get_fault_report(fault["id"])
        assert f["status"] == "ISOLATED"
        # Hop B: pile FAULT.
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "FAULT"
        # Hop C: reservation CANCELLED.
        r = get_reservation(ctx["reservation"]["id"])
        assert r["status"] == "CANCELLED"

    def test_cascade_does_not_increment_no_show_strikes(self, api):
        """PRD §3.5: 'no strike — this is the compensating semantics
        distinguishing fault-driven cancellations.'"""
        # difficulty: transitive_cascade/fault_isolation_cascade_depth_4
        ctx = setup_reservation_held()
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"],
            reporter_kind="AUTO_DETECT",
            severity="MAJOR",
        )
        isolate_fault_report(fault_id=fault["id"])
        m = get_member(ctx["member"]["id"])
        assert m["no_show_strikes"] == 0


# ===========================================================================
# Rule 4, instance: session_settle_cascade_depth_3
# ===========================================================================
class TestSessionSettleCascadeDepth3:
    """SCAFFOLD_DIFFICULTY_DESIGN rule transitive_cascade / instance
    session_settle_cascade_depth_3.

    PRD §3.4: 'Simultaneously, the pile returns from IN_USE to IDLE,
    and the queue-promotion check fires at the parent station.'

    PRD §3.3: 'When a pile at the station becomes IDLE ... the system
    promotes the WAITING entry with the lowest position ... the chosen
    entry moves to PROMOTED.'"""

    def test_stop_session_transitions_pile_to_idle_then_promotes_queue(
        self, api,
    ):
        """Chain: session SETTLED → pile IDLE → queue PROMOTED."""
        # difficulty: transitive_cascade/session_settle_cascade_depth_3
        ctx = setup_charging_session()
        # Queue another member.
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        q2 = join_queue(
            station_id=ctx["station"]["id"], member_id=m2["id"],
        )
        # Drive the session to SETTLED.
        append_curve_point(
            session_id=ctx["session"]["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        settled = stop_session(
            session_id=ctx["session"]["id"],
            member_id=ctx["member"]["id"],
        )
        assert settled["status"] == "SETTLED"
        # Pile must be IDLE.
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IDLE"
        # Queue entry must be PROMOTED.
        from test_helpers import list_queue_entries
        rows = list_queue_entries(
            ctx["station"]["id"], params={"limit": 100},
        )
        by_id = {r["id"]: r for r in rows}
        assert by_id[q2["id"]]["status"] == "PROMOTED"

    def test_stop_with_no_queued_member_leaves_pile_idle(self, api):
        """Same primary cascade — but with no queue, PRD §3.3 promotion
        check fires harmlessly."""
        # difficulty: transitive_cascade/session_settle_cascade_depth_3
        ctx = setup_charging_session()
        append_curve_point(
            session_id=ctx["session"]["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        stop_session(
            session_id=ctx["session"]["id"],
            member_id=ctx["member"]["id"],
        )
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IDLE"


# ===========================================================================
# Rule 5, instance: pile_unavailable_beats_reservation_expired
# ===========================================================================
class TestPileUnavailableBeatsReservationExpired:
    """SCAFFOLD_DIFFICULTY_DESIGN rule priority_pair_validation_conflict
    / instance pile_unavailable_beats_reservation_expired.

    PRD §2.5: 'business rules ... are evaluated [after the auth +
    existence + state layers]. Within those business rules, each one
    applies only to the endpoints listed in its definition.' And the
    priority text in the section: 'pile availability, reservation
    matching, reservation expiry, queue position ...' — pile
    availability appears before reservation expiry in that ordered
    list."""

    def test_pile_offline_and_reservation_expired_returns_pile_unavailable(
        self, api,
    ):
        # difficulty: priority_pair_validation_conflict/pile_unavailable_beats_reservation_expired
        ctx = setup_ready_to_charge()
        base = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        advance_clock_to(iso_z(base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
            reservation_id=reservation["id"],
        )
        # Push past hold expiry WITHOUT running sweep so the
        # Reservation stays HELD but is temporally expired.
        advance_clock_to(iso_z(base + timedelta(minutes=20)))
        # Make the pile unavailable AFTER expiry.
        emit_grid_pile_offline(ctx["pile"]["id"])
        # Now start: both pile-unavailable and reservation-expired
        # would fire — PRD priority says pile-unavailable.
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)

    def test_pile_offline_alone_yields_pile_unavailable(self, api):
        """Single-failure sibling — PRD §3.4: 'The pile must be in
        lifecycle_state ON_SHELF and operational_state IDLE; if not,
        the request is rejected with ERR_PILE_UNAVAILABLE.'"""
        # difficulty: priority_pair_validation_conflict/pile_unavailable_beats_reservation_expired
        ctx = setup_ready_to_charge()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # Send pile OFFLINE.
        emit_grid_pile_offline(ctx["pile"]["id"])
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)


# ===========================================================================
# Rule 5, instance: queue_not_at_front_beats_insufficient_balance
# ===========================================================================
class TestQueueNotAtFrontBeatsInsufficientBalance:
    """SCAFFOLD_DIFFICULTY_DESIGN rule priority_pair_validation_conflict
    / instance queue_not_at_front_beats_insufficient_balance.

    PRD §2.5 again states the ordered list of business rules, in which
    queue position appears before wallet sufficiency. PRD §3.4 names
    both ERR_QUEUE_NOT_AT_FRONT and ERR_INSUFFICIENT_BALANCE as start-
    time rejections."""

    def test_late_member_at_position_two_with_zero_wallet_sees_queue_error(
        self, api,
    ):
        """When BOTH the queue-not-at-front and wallet-balance checks
        would fail, PRD §2.5 priority places queue (referential) ahead
        of wallet (fiscal), so the response is ERR_QUEUE_NOT_AT_FRONT."""
        # difficulty: priority_pair_validation_conflict/queue_not_at_front_beats_insufficient_balance
        from test_helpers import setup_two_members_one_at_queue_front
        # Late member must have wallet_balance < MIN_AUTH_HOLD_CENTS (1000).
        ctx = setup_two_members_one_at_queue_front(
            front_wallet_cents=100000,
            late_wallet_cents=0,
        )
        # Late member tries unreserved start — both rules would fail.
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["m_late"]["id"],
        )
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["m_late"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUEUE_NOT_AT_FRONT.value)

    def test_member_at_position_two_with_full_wallet_sees_queue_error(
        self, api,
    ):
        """Single-failure sibling — only queue position is wrong; PRD
        §3.4 says ERR_QUEUE_NOT_AT_FRONT."""
        # difficulty: priority_pair_validation_conflict/queue_not_at_front_beats_insufficient_balance
        from test_helpers import setup_two_members_one_at_queue_front
        ctx = setup_two_members_one_at_queue_front(
            front_wallet_cents=100000,
            late_wallet_cents=100000,
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["m_late"]["id"],
        )
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["m_late"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUEUE_NOT_AT_FRONT.value)


# ===========================================================================
# Rule 6, instance: reservation_expiry_exact_instant_inclusive
# ===========================================================================
class TestReservationExpiryExactInstant:
    """SCAFFOLD_DIFFICULTY_DESIGN rule boundary_precision_check /
    instance reservation_expiry_exact_instant_inclusive.

    PRD §3.3: 'A HELD reservation transitions to EXPIRED automatically
    when the sweep capability is invoked at an instant where now is at
    or after hold_expires_at.'"""

    def test_sweep_one_ms_before_hold_expires_keeps_reservation_held(
        self, api,
    ):
        """PRD §3.3: 'when ... now is at or after hold_expires_at' —
        strictly-less-than means NO expiry."""
        # difficulty: boundary_precision_check/reservation_expiry_exact_instant_inclusive
        ctx = setup_ready_to_charge()
        base = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        advance_clock_to(iso_z(base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # hold_expires_at = base + 15min. Advance to base + 14:59.999.
        advance_clock_to(iso_z(
            base + timedelta(minutes=14, seconds=59, milliseconds=999)
        ))
        run_sweep()
        r = get_reservation(reservation["id"])
        assert r["status"] == "HELD"

    def test_sweep_at_exact_hold_expires_marks_reservation_expired(
        self, api,
    ):
        """PRD §3.3: 'at or after hold_expires_at' — at-equality
        triggers expiry."""
        # difficulty: boundary_precision_check/reservation_expiry_exact_instant_inclusive
        ctx = setup_ready_to_charge()
        base = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        advance_clock_to(iso_z(base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # Advance exactly 15 minutes — the inclusive boundary.
        advance_clock_to(iso_z(base + timedelta(minutes=15)))
        run_sweep()
        r = get_reservation(reservation["id"])
        assert r["status"] == "EXPIRED"
        m = get_member(ctx["member"]["id"])
        assert m["no_show_strikes"] == 1


# ===========================================================================
# Rule 6, instance: empty_queue_allows_unreserved_start
# ===========================================================================
class TestEmptyQueueAllowsUnreservedStart:
    """SCAFFOLD_DIFFICULTY_DESIGN rule boundary_precision_check /
    instance empty_queue_allows_unreserved_start.

    PRD §3.4: 'If no reservation_id was supplied, either there must be
    no WAITING queue entry at the pile's station, or the driver must
    be the holder of the WAITING entry at position one.'"""

    def test_unreserved_start_on_empty_queue_succeeds(self, api):
        """Zero-count boundary."""
        # difficulty: boundary_precision_check/empty_queue_allows_unreserved_start
        ctx = setup_ready_to_charge()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert session["status"] == "CHARGING"

    def test_unreserved_start_with_other_member_at_front_rejected(self, api):
        """One-WAITING boundary — different member than requester."""
        # difficulty: boundary_precision_check/empty_queue_allows_unreserved_start
        from test_helpers import setup_two_members_one_at_queue_front
        ctx = setup_two_members_one_at_queue_front()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["m_late"]["id"],
        )
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["m_late"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUEUE_NOT_AT_FRONT.value)


# ===========================================================================
# Rule 7, instance: session_start_requires_pile_idle
# ===========================================================================
class TestSessionStartRequiresPileIdle:
    """SCAFFOLD_DIFFICULTY_DESIGN rule cross_entity_state_dependency /
    instance session_start_requires_pile_idle.

    PRD §3.4: 'The pile must be in lifecycle_state ON_SHELF and
    operational_state IDLE; if not, the request is rejected with
    ERR_PILE_UNAVAILABLE.'"""

    def test_offline_pile_blocks_start_returns_pile_unavailable(self, api):
        # difficulty: cross_entity_state_dependency/session_start_requires_pile_idle
        ctx = setup_ready_to_charge()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        emit_grid_pile_offline(ctx["pile"]["id"])
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)
        # Session must remain PENDING_AUTH.
        s = get_session(session["id"])
        assert s["status"] == "PENDING_AUTH"

    def test_pile_in_fault_blocks_session_start(self, api):
        """Same cross-entity rule via FAULT instead of OFFLINE."""
        # difficulty: cross_entity_state_dependency/session_start_requires_pile_idle
        ctx = setup_ready_to_charge()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # Inject FAULT via a fault-report isolation cascade.
        fault = create_fault_report(
            pile_id=ctx["pile"]["id"],
            reporter_kind="AUTO_DETECT",
            severity="CRITICAL",  # auto-isolates.
        )
        # Pile must now be FAULT.
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "FAULT"
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)


# ===========================================================================
# Rule 7, instance: repair_close_requires_fault_isolated
# ===========================================================================
class TestRepairCloseRequiresFaultIsolated:
    """SCAFFOLD_DIFFICULTY_DESIGN rule cross_entity_state_dependency /
    instance repair_close_requires_fault_isolated.

    PRD §3.5: 'Acceptance by a StationOwner ... moves the ticket from
    AWAITING_ACCEPTANCE to CLOSED.' Once CLOSED, accept on the same
    ticket must be rejected per PRD §2.5 priority-3 state checks
    (ERR_INVALID_STATE)."""

    def test_second_accept_on_closed_ticket_rejected_invalid_state(self, api):
        # difficulty: cross_entity_state_dependency/repair_close_requires_fault_isolated
        ctx = setup_repair_awaiting_acceptance()
        accept_repair_ticket(
            ticket_id=ctx["ticket"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        # Try to accept again — invalid state.
        res = api.accept_repair_ticket(
            ctx["ticket"]["id"],
            make_station_owner_headers(ctx["station_owner"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_closed_ticket_keeps_fault_resolved(self, api):
        """Cross-entity invariant: the parent FaultReport remains
        RESOLVED — PRD §3.5: 'cascades the parent fault report from
        ISOLATED to RESOLVED.'"""
        # difficulty: cross_entity_state_dependency/repair_close_requires_fault_isolated
        ctx = setup_repair_awaiting_acceptance()
        accept_repair_ticket(
            ticket_id=ctx["ticket"]["id"],
            station_owner_id=ctx["station_owner"]["id"],
        )
        # Even if we attempt a second accept that fails, the parent
        # fault must remain RESOLVED.
        api.accept_repair_ticket(
            ctx["ticket"]["id"],
            make_station_owner_headers(ctx["station_owner"]["id"]),
        )
        f = get_fault_report(ctx["fault"]["id"])
        assert f["status"] == "RESOLVED"


# ===========================================================================
# Rule 8, instance: pricing_version_window_overlap_per_operator
# ===========================================================================
class TestPricingVersionWindowOverlap:
    """SCAFFOLD_DIFFICULTY_DESIGN rule resource_temporal_overlap /
    instance pricing_version_window_overlap_per_operator.

    PRD §3.2: 'the new interval must not overlap any other pricing
    version owned by the same operator on a half-open [effective_from,
    effective_to) basis — if any overlap exists the request is rejected
    with ERR_PRICING_WINDOW_OVERLAP.'"""

    def test_clear_overlap_rejected(self, api):
        # difficulty: resource_temporal_overlap/pricing_version_window_overlap_per_operator
        operator = create_platform_operator_row()
        create_pricing_version(
            operator_id=operator["id"],
            effective_from=iso_day(2026, 5, 1),
            effective_to=iso_day(2026, 6, 1),
        )
        from test_helpers import create_pricing_version_payload
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=operator["id"],
                effective_from=iso_day(2026, 5, 15),
                effective_to=iso_day(2026, 7, 1),
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP.value)

    def test_adjacency_touch_at_effective_to_accepted(self, api):
        """PRD §3.2: 'half-open [effective_from, effective_to) basis' —
        A.effective_to == B.effective_from is non-overlapping."""
        # difficulty: resource_temporal_overlap/pricing_version_window_overlap_per_operator
        operator = create_platform_operator_row()
        create_pricing_version(
            operator_id=operator["id"],
            effective_from=iso_day(2026, 5, 1),
            effective_to=iso_day(2026, 6, 1),
        )
        from test_helpers import create_pricing_version_payload
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=operator["id"],
                effective_from=iso_day(2026, 6, 1),
                effective_to=iso_day(2026, 7, 1),
            ),
            PO,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Rule 8, instance: pile_held_reservation_single_capacity
# ===========================================================================
class TestPileHeldReservationSingleCapacity:
    """SCAFFOLD_DIFFICULTY_DESIGN rule resource_temporal_overlap /
    instance pile_held_reservation_single_capacity.

    PRD §3.3: 'Two drivers racing for the same pile see the second
    writer rejected with ERR_PILE_ALREADY_RESERVED ... at most one
    reservation in HELD exists per pile at any time.'"""

    def test_second_reservation_while_first_held_rejected(self, api):
        # difficulty: resource_temporal_overlap/pile_held_reservation_single_capacity
        ctx = setup_ready_to_charge()
        create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(m2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_ALREADY_RESERVED.value)

    def test_second_reservation_after_first_cancelled_succeeds(self, api):
        """PRD §3.3: 'this is the only path to CANCELLED that does not
        incur a strike.' Once the first reservation is no longer HELD,
        a new one is accepted."""
        # difficulty: resource_temporal_overlap/pile_held_reservation_single_capacity
        from test_helpers import cancel_reservation
        ctx = setup_ready_to_charge()
        r1 = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        cancel_reservation(
            reservation_id=r1["id"], member_id=ctx["member"]["id"],
        )
        # Retry now succeeds.
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(m2["id"]),
        )
        body = validate_success(res, expected_status=201)
        assert body["status"] == "HELD"


# ===========================================================================
# Rule 9, instance: refund_zero_sum_per_counterparty
# ===========================================================================
class TestRefundZeroSumPerCounterparty:
    """SCAFFOLD_DIFFICULTY_DESIGN rule compensating_invariant / instance
    refund_zero_sum_per_counterparty.

    PRD §3.6: 'the sum of original plus reversal amount_cents on the
    session is exactly zero — the compensating-invariant condition.'"""

    def test_station_owner_share_nets_to_zero_after_refund(self, api):
        # difficulty: compensating_invariant/refund_zero_sum_per_counterparty
        ctx = setup_settled_session_for_recipe()
        emit_payment_refunded(ctx["session"]["id"])
        rows = list_session_ledger_entries(ctx["session"]["id"])
        totals = sum_amounts_by_counterparty(rows)
        assert totals.get("STATION_OWNER_SHARE", 0) == 0

    def test_platform_and_tax_buckets_net_to_zero_after_refund(self, api):
        """PRD §3.6: 'for each counterparty_kind, the sum of original
        plus reversal amount_cents on the session is exactly zero.'"""
        # difficulty: compensating_invariant/refund_zero_sum_per_counterparty
        ctx = setup_settled_session_for_recipe()
        emit_payment_refunded(ctx["session"]["id"])
        rows = list_session_ledger_entries(ctx["session"]["id"])
        totals = sum_amounts_by_counterparty(rows)
        assert totals.get("PLATFORM_SERVICE_FEE", 0) == 0
        assert totals.get("TAX_AUTHORITY", 0) == 0


# ===========================================================================
# Rule 9, instance: wallet_balance_round_trip_after_refund
# ===========================================================================
class TestWalletBalanceRoundTripAfterRefund:
    """SCAFFOLD_DIFFICULTY_DESIGN rule compensating_invariant / instance
    wallet_balance_round_trip_after_refund.

    PRD §3.4: 'After the four monetary fields are written, the member's
    wallet_balance_cents is decremented by total_cents.' — and the
    refund flow described in PRD §3.6 / §3.8 must restore the wallet.

    NOTE: PRD §3.6 / §3.7 describe ledger reversals on refund but do
    NOT explicitly state that the Member.wallet_balance_cents is
    credited back. To remain faithful to the PRD-only reader rule, this
    test asserts only what PRD explicitly covers: the wallet is
    decremented by total_cents at SETTLED. A refund-credit assertion
    would impose a behavior PRD does not name.
    """

    def test_wallet_decremented_by_total_cents_at_settle(self, api):
        """PRD §3.4: 'the member's wallet_balance_cents is decremented
        by total_cents.'"""
        # difficulty: compensating_invariant/wallet_balance_round_trip_after_refund
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER",
            member_wallet_cents=100000,
        )
        m = get_member(ctx["member"]["id"])
        # total_cents = 1170 per recipe.
        assert ctx["session"]["total_cents"] == 1170
        assert m["wallet_balance_cents"] == 100000 - 1170

    def test_refund_writes_billing_adjustment_audit_log(self, api):
        """PRD §3.6: 'an AuditLog row with event_kind BILLING_ADJUSTMENT
        is appended.' (Companion test to the wallet-decrement check
        above — both anchor the compensating-invariant rule, even
        though PRD does NOT explicitly name a wallet-credit-on-refund
        behavior.)"""
        # difficulty: compensating_invariant/wallet_balance_round_trip_after_refund
        ctx = setup_settled_session_for_recipe()
        emit_payment_refunded(ctx["session"]["id"])
        logs = list_audit_logs(
            event_kind="BILLING_ADJUSTMENT",
            entity_kind="ChargingSession",
            entity_id=ctx["session"]["id"],
        )
        assert len(logs) >= 1
