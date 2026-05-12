"""Dedicated coverage for every difficulty-design instance.

Each test in this file is tagged with a `# difficulty: <rule_id>/<name>`
comment so the coverage check can verify each instance has at least TWO
tests. Tests in earlier files that incidentally cover an instance are also
tagged with the same marker; this file ensures that the per-instance
minimum-coverage rule is satisfied even if those incidental tests change.
"""
from __future__ import annotations
import base64
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_charge_breakdown_pay_per_session,
    assert_charge_breakdown_package,
    assert_refund_breakdown_full_pps,
    assert_refund_breakdown_partial_pps,
    bring_counselor_to_active,
    cancel_appointment,
    confirm_appointment,
    create_appointment_in_hold,
    create_appointment_payload,
    create_availability_slot_payload,
    create_client,
    create_counseling_record_payload,
    create_counselor,
    create_slot,
    create_supervision_session_payload,
    DEFAULT_LIST_PRICE_CENTS,
    DEFAULT_T0,
    disqualify_counselor,
    find_audit_entries,
    find_ledger_row,
    find_ledger_rows_for_appointment,
    get_appointment,
    get_client,
    get_counselor,
    handover_crisis,
    list_audit_log,
    list_settlement_ledger,
    list_settlement_ledger_for_appointment,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    make_crisis_responder_headers,
    notify_emergency,
    parse_iso,
    iso_z,
    resolve_crisis,
    schedule_follow_up,
    setup_appointment_at_24h_boundary,
    setup_confirmed_appointment,
    setup_counselor_and_completed_client,
    setup_counselor_with_seven_60min_slots_same_local_day,
    setup_three_package_appointments_for_refund_branches,
    setup_two_confirmed_appointments_pps_and_package,
    setup_two_confirmed_for_disqualify_chain,
    shift,
    sweep_recert,
    sweep_holds,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestRefundEstimateVsFinalBoundary:
    """difficulty: dual_variant_calc/refund_estimate_vs_final_boundary_at_24h"""

    def test_estimate_at_24h_says_partial(self, api):
        """PRD §3.5: "the forward estimate uses STRICT > so reports
        PARTIAL"; quoted PRD: "at hours-to-start of exactly 24.0, the
        forward estimate reports `PARTIAL_REFUNDED` while the actual
        cancellation transition would land on `FULL_REFUNDED`."

        difficulty: dual_variant_calc/refund_estimate_vs_final_boundary_at_24h
        """
        counselor, client, confirmed = setup_appointment_at_24h_boundary(
            payment_mode="PAY_PER_SESSION", revenue_share_bps=7000,
        )
        res = api.get_refund_estimate(
            confirmed["id"], make_client_headers(client["id"]),
        )
        body = validate_success(res, expected_status=200)
        assert body["refund_state"] == "PARTIAL_REFUNDED"

    def test_cancel_at_24h_yields_full_refund_with_correct_breakdown(self, api):
        """PRD §3.5: "if the reason is `CLIENT_CANCEL`, hours-to-start at
        least twenty-four yields `FULL_REFUNDED` with gross equal to
        `list_price_cents`..."

        difficulty: dual_variant_calc/refund_estimate_vs_final_boundary_at_24h
        """
        counselor, client, confirmed = setup_appointment_at_24h_boundary(
            payment_mode="PAY_PER_SESSION", revenue_share_bps=7000,
        )
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "FULL_REFUNDED"
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        refund = find_ledger_row(rows, confirmed["id"], "REFUND")
        assert refund is not None
        # PRD §3.5: gross = list_price_cents (12000); tax = 1050; counselor = 8400; platform = 3600.
        assert refund["gross_amount_cents"] == -12000
        assert refund["tax_cents"] == -1050
        assert refund["counselor_share_cents"] == -8400
        assert refund["platform_share_cents"] == -3600


class TestChargeBreakdownPpsVsPackage:
    """difficulty: dual_variant_calc/charge_breakdown_pay_per_session_vs_package_same_session"""

    def test_pps_charge_breakdown(self):
        """PRD §3.8: "For `PAY_PER_SESSION`, `gross_amount_cents` equals
        the appointment's frozen `list_price_cents` (default 12000 cents).
        The tax component `tax_cents` is `gross_amount_cents` multiplied
        by the basis-points tax rate `TAX_BPS` of 875 divided by 10000,
        rounded half up. The counselor's portion `counselor_share_cents`
        is `gross_amount_cents` multiplied by the counselor's
        `revenue_share_bps` divided by 10000, rounded half up."

        difficulty: dual_variant_calc/charge_breakdown_pay_per_session_vs_package_same_session
        """
        counselor, client_pps, client_pkg, confirmed_pps, confirmed_pkg = \
            setup_two_confirmed_appointments_pps_and_package(revenue_share_bps=7000)
        rows_pps = list_settlement_ledger_for_appointment(confirmed_pps["id"])
        charge_pps = find_ledger_row(rows_pps, confirmed_pps["id"], "CHARGE")
        assert charge_pps is not None
        assert charge_pps["gross_amount_cents"] == 12000
        assert charge_pps["tax_cents"] == 1050
        assert charge_pps["counselor_share_cents"] == 8400
        assert charge_pps["platform_share_cents"] == 3600

    def test_package_charge_breakdown(self):
        """PRD §3.8: "For `PACKAGE`, the consumer has already paid for the
        session through the prepaid package, so the ledger's
        `gross_amount_cents` is zero and `tax_cents` is zero. The counselor
        still earns a share, however, computed against an imputed shadow
        rate `SHADOW_PACKAGE_RATE` of 9000 cents per session:
        `counselor_share_cents` equals 9000 multiplied by `revenue_share_bps`
        divided by 10000, rounded half up. Because there is no concurrent
        gross to draw from, the platform absorbs that share from prior
        package revenue, so `platform_share_cents` equals the negative of
        `counselor_share_cents`."

        difficulty: dual_variant_calc/charge_breakdown_pay_per_session_vs_package_same_session
        """
        counselor, client_pps, client_pkg, confirmed_pps, confirmed_pkg = \
            setup_two_confirmed_appointments_pps_and_package(revenue_share_bps=7000)
        rows_pkg = list_settlement_ledger_for_appointment(confirmed_pkg["id"])
        charge_pkg = find_ledger_row(rows_pkg, confirmed_pkg["id"], "CHARGE")
        assert charge_pkg is not None
        assert charge_pkg["gross_amount_cents"] == 0
        assert charge_pkg["tax_cents"] == 0
        assert charge_pkg["counselor_share_cents"] == 6300
        assert charge_pkg["platform_share_cents"] == -6300

    def test_package_balance_decremented_after_confirm(self):
        """PRD §3.4: "if the payment mode is `PACKAGE` the client's
        `package_balance_sessions` is decremented by one."

        difficulty: dual_variant_calc/charge_breakdown_pay_per_session_vs_package_same_session
        """
        counselor, client_pps, client_pkg, confirmed_pps, confirmed_pkg = \
            setup_two_confirmed_appointments_pps_and_package(revenue_share_bps=7000)
        client_after = get_client(client_pkg["id"])
        # client_pkg was credited 5 packages and consumed 1 -> balance = 4.
        assert client_after["package_balance_sessions"] == 4


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestRefundThreeInputBranches:
    """difficulty: combinatorial_formula/refund_three_input_nested_branches"""

    def test_below_2h_yields_non_refundable(self):
        """PRD §3.5: "hours-to-start less than two yields `NON_REFUNDABLE`
        with gross of zero."

        difficulty: combinatorial_formula/refund_three_input_nested_branches
        """
        counselor, client, appts = setup_three_package_appointments_for_refund_branches()
        a1 = appts[0]
        # Anchor clock at start_at - 1h (well under 2h).
        appt_after = get_appointment(a1["id"])
        slot_id = appt_after["slot_id"]
        slot_resp = api_client.list_availability_slots(
            make_counselor_headers(counselor["id"]),
            params={"counselor_id": counselor["id"], "limit": 100},
        ).json()
        start_at = next(s["start_at"] for s in slot_resp["data"] if s["id"] == slot_id)
        balance_before = get_client(client["id"])["package_balance_sessions"]
        advance_clock(shift(start_at, hours=-1))
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=a1, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "NON_REFUNDABLE"
        # PRD §3.5: refund credit-back applies only to FULL/PARTIAL.
        balance_after = get_client(client["id"])["package_balance_sessions"]
        assert balance_after == balance_before, \
            "PRD §3.5: NON_REFUNDABLE does NOT credit package_balance_sessions"

    def test_between_2_and_24h_yields_partial(self):
        """PRD §3.5: "hours-to-start less than twenty-four but at least two
        yields `PARTIAL_REFUNDED`..."

        difficulty: combinatorial_formula/refund_three_input_nested_branches
        """
        counselor, client = setup_counselor_and_completed_client(
            package_balance_sessions=3,
        )
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        confirmed = confirm_appointment(client, appt)
        # Anchor clock at start_at - 5h (between 2h and 24h).
        advance_clock(shift(slot["start_at"], hours=-5))
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "PARTIAL_REFUNDED"

    def test_at_least_24h_yields_full(self):
        """PRD §3.5: "hours-to-start at least twenty-four yields
        `FULL_REFUNDED`..."

        difficulty: combinatorial_formula/refund_three_input_nested_branches
        """
        counselor, client = setup_counselor_and_completed_client(
            package_balance_sessions=3,
        )
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        confirmed = confirm_appointment(client, appt)
        # Don't advance clock; hours_to_start ~ 400h.
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "FULL_REFUNDED"


class TestSettlementPerComponentRoundingOrder:
    """difficulty: combinatorial_formula/settlement_per_component_vs_sum_then_round"""

    def test_per_component_rounding_pinned(self):
        """PRD §2.8: "for the same gross amount, the result of 'round
        counselor share, then platform share = gross minus counselor share'
        can differ by one cent from the result of 'round platform share
        directly from the residual basis points', and the platform requires
        the former."

        For revenue_share_bps=6667, list_price_cents=12000:
        Method A (PRD-pinned): counselor = round_half_up(12000*6667/10000)
                              = round_half_up(8000.4) = 8000;
                              platform = 12000 - 8000 = 4000.

        difficulty: combinatorial_formula/settlement_per_component_vs_sum_then_round
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=6667,
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        charge = find_ledger_row(rows, confirmed["id"], "CHARGE")
        assert charge is not None
        assert charge["counselor_share_cents"] == 8000
        assert charge["platform_share_cents"] == 4000

    def test_charge_components_sum_to_gross(self):
        """PRD §2.8: "the platform share is then derived as the residual
        rather than recomputed from a complementary basis-points fraction."

        Invariant: counselor_share_cents + platform_share_cents == gross_amount_cents.

        difficulty: combinatorial_formula/settlement_per_component_vs_sum_then_round
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=6667,
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        charge = find_ledger_row(rows, confirmed["id"], "CHARGE")
        assert charge is not None
        assert charge["counselor_share_cents"] + charge["platform_share_cents"] \
            == charge["gross_amount_cents"]


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestCounselorCycleStateMachine:
    """difficulty: non_linear_state_machine/counselor_active_suspended_cycle"""

    def test_suspended_via_recert_sweep_after_window_expires(self):
        """PRD §3.2: "When current time crosses `window_end_at` while the
        cycle is still `OPEN`, a system-driven recertification sweep
        transitions the cycle to `EXPIRED` with `decided_at` set to current
        time and `decided_by_user_id` set to null. If at that instant the
        counselor is `ACTIVE`, the same sweep cascades into the counselor's
        own state machine and moves the counselor from `ACTIVE` to
        `SUSPENDED`."

        difficulty: non_linear_state_machine/counselor_active_suspended_cycle
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        assert counselor["status"] == "ACTIVE"
        # Cycle 2 was auto-created; advance the clock past its window_end_at.
        from test_helpers import fetch_open_cycle_for
        cycle2 = fetch_open_cycle_for(counselor["id"])
        # Advance to 1 sec after window_end_at.
        advance_clock(shift(cycle2["window_end_at"], seconds=1))
        sweep_recert()
        counselor_after = get_counselor(counselor["id"])
        assert counselor_after["status"] == "SUSPENDED"

    def test_audit_log_records_recert_decision_for_expired_cycle(self):
        """PRD §3.2: "an `AuditLogEntry` with action `RECERT_DECISION` is
        appended."

        difficulty: non_linear_state_machine/counselor_active_suspended_cycle
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        from test_helpers import fetch_open_cycle_for
        cycle2 = fetch_open_cycle_for(counselor["id"])
        advance_clock(shift(cycle2["window_end_at"], seconds=1))
        sweep_recert()
        entries = list_audit_log(action="RECERT_DECISION", target_id=cycle2["id"])
        assert any(e["action"] == "RECERT_DECISION"
                   and e["target_id"] == cycle2["id"] for e in entries)


class TestCrisisBranchingBySeverity:
    """difficulty: non_linear_state_machine/crisis_branching_severity_dependent_path"""

    def _make_in_session_appointment(self, base_t0=DEFAULT_T0):
        advance_clock(base_t0)
        counselor = bring_counselor_to_active()
        client = create_client()
        intake_start = shift(base_t0, hours=200)
        slot = create_slot(counselor=counselor, start_at=intake_start)
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        advance_clock(shift(intake_start, minutes=-4))
        from test_helpers import start_appointment
        return counselor, client, start_appointment(counselor, confirmed)

    def test_low_severity_skips_emergency_notification(self, api):
        """PRD §3.7: "Attempting the same notification when `severity` is
        `LOW` is rejected with `ERR_NOTIFY_NOT_REQUIRED` because the
        protocol skips emergency notification at low severity."
        Followed by PRD §3.7: "When `severity` is `LOW`, the responder
        skips notification and goes directly from `HANDED_OVER` to
        `FOLLOW_UP_SCHEDULED`, recording `follow_up_due_at`."

        difficulty: non_linear_state_machine/crisis_branching_severity_dependent_path
        """
        counselor, client, started = self._make_in_session_appointment()
        from test_helpers import create_crisis_incident
        incident = create_crisis_incident(
            counselor=counselor, appointment=started,
            detection_source="COUNSELOR_TRIGGERED",
        )
        handed = handover_crisis(incident, severity="LOW")
        # notify-emergency is rejected with ERR_NOTIFY_NOT_REQUIRED.
        res = api.notify_emergency(
            handed["id"], make_crisis_responder_headers("crisis-001"),
        )
        validate_error(res, "ERR_NOTIFY_NOT_REQUIRED", expected_status=422)
        # Schedule follow-up directly (skipping EMERGENCY_NOTIFIED).
        scheduled = schedule_follow_up(handed)
        assert scheduled["status"] == "FOLLOW_UP_SCHEDULED"
        assert scheduled["emergency_notified_at"] is None

    def test_high_severity_passes_through_emergency_notified(self, api):
        """PRD §3.7: "When `severity` is `MEDIUM` or `HIGH`, the responder
        is expected to dispatch the emergency-contact notification: the
        action transitions the incident from `HANDED_OVER` to
        `EMERGENCY_NOTIFIED`..."

        difficulty: non_linear_state_machine/crisis_branching_severity_dependent_path
        """
        counselor, client, started = self._make_in_session_appointment()
        from test_helpers import create_crisis_incident
        incident = create_crisis_incident(
            counselor=counselor, appointment=started,
            detection_source="COUNSELOR_TRIGGERED",
        )
        handed = handover_crisis(incident, severity="HIGH")
        notified = notify_emergency(handed)
        assert notified["status"] == "EMERGENCY_NOTIFIED"
        assert notified["emergency_notified_at"] is not None
        scheduled = schedule_follow_up(notified)
        assert scheduled["status"] == "FOLLOW_UP_SCHEDULED"


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestDisqualifyChainDepth3:
    """difficulty: transitive_cascade/disqualify_chain_depth_3"""

    def test_disqualify_cascades_to_pps_appointment_and_ledger(self):
        """PRD §3.2: "every `OPEN` and `HELD` availability slot of that
        counselor moves to `RELEASED`; every appointment in `HOLD` cancels
        with `cancellation_reason` of `COUNSELOR_CANCEL`; every `CONFIRMED`
        future appointment cancels with `cancellation_reason` of
        `COUNSELOR_CANCEL`, has `refund_state` set to `FULL_REFUNDED`, and
        gets a corresponding REFUND row written to `SettlementLedger`..."

        difficulty: transitive_cascade/disqualify_chain_depth_3
        """
        counselor, client, a1, a2 = setup_two_confirmed_for_disqualify_chain(
            revenue_share_bps=7000,
        )
        disqualify_counselor(counselor)
        a1_after = get_appointment(a1["id"])
        assert a1_after["status"] == "CANCELLED"
        assert a1_after["cancellation_reason"] == "COUNSELOR_CANCEL"
        assert a1_after["refund_state"] == "FULL_REFUNDED"
        rows_a1 = list_settlement_ledger_for_appointment(a1["id"])
        refund = find_ledger_row(rows_a1, a1["id"], "REFUND")
        assert refund is not None
        # PAY_PER_SESSION refund: gross=-12000, tax=-1050, counselor=-8400, platform=-3600.
        assert refund["gross_amount_cents"] == -12000
        assert refund["tax_cents"] == -1050
        assert refund["counselor_share_cents"] == -8400
        assert refund["platform_share_cents"] == -3600

    def test_disqualify_credits_package_balance_for_package_appointment(self):
        """PRD §3.5: "When `refund_state` is `FULL_REFUNDED` or
        `PARTIAL_REFUNDED` and the appointment had been paid by `PACKAGE`,
        the client's `package_balance_sessions` is incremented by one as
        part of the same operation."

        difficulty: transitive_cascade/disqualify_chain_depth_3
        """
        counselor, client, a1, a2 = setup_two_confirmed_for_disqualify_chain(
            revenue_share_bps=7000,
        )
        balance_before = get_client(client["id"])["package_balance_sessions"]
        disqualify_counselor(counselor)
        a2_after = get_appointment(a2["id"])
        assert a2_after["status"] == "CANCELLED"
        assert a2_after["refund_state"] == "FULL_REFUNDED"
        balance_after = get_client(client["id"])["package_balance_sessions"]
        # a2 was PACKAGE; refund credits +1.
        assert balance_after == balance_before + 1

    def test_disqualify_audit_log_emitted(self):
        """PRD §3.2: "an `AuditLogEntry` with action
        `COUNSELOR_DISQUALIFIED` is appended."

        difficulty: transitive_cascade/disqualify_chain_depth_3
        """
        counselor, client, a1, a2 = setup_two_confirmed_for_disqualify_chain()
        disqualify_counselor(counselor)
        entries = list_audit_log(
            action="COUNSELOR_DISQUALIFIED", target_id=counselor["id"],
        )
        assert any(e["target_id"] == counselor["id"] for e in entries)


class TestCycleExpiryChainDepth3:
    """difficulty: transitive_cascade/cycle_expiry_chain_depth_3"""

    def test_cycle_expiry_cascades_to_counselor_and_open_slots(self):
        """PRD §3.2: "If at that instant the counselor is `ACTIVE`, the
        same sweep cascades into the counselor's own state machine and
        moves the counselor from `ACTIVE` to `SUSPENDED`. ... The
        `ACTIVE` to `SUSPENDED` cascade has its own consequences: every
        `OPEN` availability slot of that counselor auto-transitions to
        `BLOCKED`..."

        difficulty: transitive_cascade/cycle_expiry_chain_depth_3
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        # Create an OPEN slot.
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=300))
        from test_helpers import fetch_open_cycle_for
        cycle2 = fetch_open_cycle_for(counselor["id"])
        # Advance past cycle2.window_end_at.
        advance_clock(shift(cycle2["window_end_at"], seconds=1))
        sweep_recert()
        counselor_after = get_counselor(counselor["id"])
        assert counselor_after["status"] == "SUSPENDED"
        # The OPEN slot must be BLOCKED now.
        slots_after = api_client.list_availability_slots(
            make_admin_headers(),
            params={"counselor_id": counselor["id"], "limit": 100},
        ).json()
        target = next(s for s in slots_after["data"] if s["id"] == slot["id"])
        assert target["status"] == "BLOCKED"

    def test_cycle_expiry_cancels_hold_appointments(self):
        """PRD §3.2: "every appointment of that counselor still in `HOLD`
        auto-cancels with `cancellation_reason` set to `COUNSELOR_CANCEL`..."

        difficulty: transitive_cascade/cycle_expiry_chain_depth_3
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=300))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        from test_helpers import fetch_open_cycle_for
        cycle2 = fetch_open_cycle_for(counselor["id"])
        advance_clock(shift(cycle2["window_end_at"], seconds=1))
        sweep_recert()
        appt_after = get_appointment(appt["id"])
        assert appt_after["status"] == "CANCELLED"
        assert appt_after["cancellation_reason"] == "COUNSELOR_CANCEL"


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityStateOverBusinessSafety:
    """difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_record_create"""

    def test_invalid_state_wins_over_keyword_detection(self, api):
        """PRD §2.7: "validations are applied in a fixed priority order,
        lowest priority number first, and the first failing rule
        determines the response. The order is: (1) authentication header
        presence (`ERR_AUTH_MISSING`), (2) role authorisation
        (`ERR_FORBIDDEN`), (3) path-parameter existence (`ERR_NOT_FOUND`),
        (4) body-referenced foreign-key existence (`ERR_REF_NOT_FOUND`),
        then (5) state validity for the requested transition
        (`ERR_INVALID_STATE`), then (6) the counselor-must-be-`ACTIVE`
        gate ... then the safety, eligibility, channel, temporal, fiscal
        and concurrency rules in numbered priority."

        Counseling-record create with a HOLD (not COMPLETED) appointment
        AND a risk keyword: state check (P5) wins over business_safety
        (P7).

        difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_record_create
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        # Appointment is in HOLD — record creation requires COMPLETED (PRD §3.6).
        # Note also contains the keyword 'suicide' (P7).
        ciphertext = base64.b64encode(b"contains suicide reference").decode()
        res = api.create_counseling_record(
            create_counseling_record_payload(
                appointment_id=appt["id"],
                encrypted_note_blob=ciphertext,
            ),
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_keyword_alone_when_state_ok_returns_crisis_auto_raised(self, api):
        """PRD §3.6: "When any keyword matches and `crisis_acknowledged`
        is not `true`, the platform refuses the write ... returning HTTP
        422 with `error_id` of `ERR_CRISIS_AUTO_RAISED`."

        Confirms that with the state precondition satisfied, the keyword
        check fires (i.e., the state-check did not preempt it spuriously).

        difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_record_create
        """
        # Walk to COMPLETED appointment.
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        intake_start = shift(DEFAULT_T0, hours=200)
        slot = create_slot(counselor=counselor, start_at=intake_start)
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        advance_clock(shift(intake_start, minutes=-4))
        from test_helpers import start_appointment
        started = start_appointment(counselor, confirmed)
        ciphertext = base64.b64encode(b"contains suicide reference").decode()
        res = api.create_counseling_record(
            create_counseling_record_payload(
                appointment_id=started["id"],
                encrypted_note_blob=ciphertext,
            ),
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_CRISIS_AUTO_RAISED", expected_status=422)


class TestPriorityTemporalOverFiscal:
    """difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_confirm"""

    def test_booking_too_late_wins_over_insufficient_balance(self, api):
        """PRD §2.7 priority ordering puts business_temporal (P17:
        ERR_BOOKING_TOO_LATE) before business_fiscal (P20:
        ERR_INSUFFICIENT_PACKAGE_BALANCE).

        Note: PRD §3.4 booking-window rule is for POST /appointments
        (P17 in the scaffold), and PACKAGE balance check is on
        POST /appointments/{id}/confirm. Both must apply on the same
        endpoint to compete. Here we use confirm with a hold whose slot
        is < 1 hour from now AND payment_mode=PACKAGE with 0 balance.

        Two-reader test: PRD §3.4 says `ERR_BOOKING_TOO_LATE` is the error
        for `POST /counseling/appointments` (booking creation), not for
        confirm. PRD §3.4 confirm narrative does not mention the booking
        window — instead it has `ERR_HOLD_EXPIRED`. So on `confirm`, the
        only error in PRD prose for time-related rejection is
        ERR_HOLD_EXPIRED. We therefore assert the response is one of
        {ERR_BOOKING_TOO_LATE, ERR_HOLD_EXPIRED, ERR_INVALID_STATE} —
        not ERR_INSUFFICIENT_PACKAGE_BALANCE — because an
        implementer faithful to PRD prose puts the temporal check before
        fiscal.

        difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_confirm
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        # Walk client through INTAKE -> COMPLETED so STANDARD/PACKAGE works.
        intake_start = shift(DEFAULT_T0, hours=200)
        intake_slot = create_slot(counselor=counselor, start_at=intake_start)
        intake_appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=intake_slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirm_appointment(client, intake_appt)
        advance_clock(shift(intake_start, minutes=-4))
        from test_helpers import start_appointment, complete_appointment, create_counseling_record
        started = start_appointment(counselor, intake_appt)
        create_counseling_record(
            counselor=counselor, appointment=started,
            encrypted_note_blob="aW50YWtlLW5vdGUtY2lwaGVydGV4dA==",
        )
        complete_appointment(counselor, started)

        # Slot 2h from intake_start (booking window passes at create).
        slot_start = shift(intake_start, hours=2)
        slot = create_slot(counselor=counselor, start_at=slot_start)
        # Client has 0 package balance.
        client = get_client(client["id"])
        assert client["package_balance_sessions"] == 0
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        # Now advance the clock to within the 1-hour buffer of slot_start.
        advance_clock(shift(slot_start, minutes=-30))
        res = api.confirm_appointment(
            appt["id"], make_client_headers(client["id"]),
        )
        # PRD prose for confirm does not name ERR_BOOKING_TOO_LATE; it
        # names ERR_HOLD_EXPIRED for time issues. ERR_INVALID_STATE is
        # also faithful (priority 5 < priority 20). The wrong outcome is
        # ERR_INSUFFICIENT_PACKAGE_BALANCE (P20).
        validate_error_is_one_of(
            res, ["ERR_HOLD_EXPIRED", "ERR_INVALID_STATE", "ERR_BOOKING_TOO_LATE"],
        )

    def test_temporal_rejection_does_not_debit_balance(self, api):
        """PRD §3.4: "if the payment mode is `PACKAGE` the client's
        `package_balance_sessions` is decremented by one." — but only on
        successful confirm. If confirm is rejected on a temporal/state
        check (priority < 20), no debit may occur.

        difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_confirm
        """
        counselor, client = setup_counselor_and_completed_client(
            package_balance_sessions=3,
        )
        balance_before = client["package_balance_sessions"]
        slot_start = shift(DEFAULT_T0, hours=400)
        slot = create_slot(counselor=counselor, start_at=slot_start)
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        # Force hold expiry by advancing past held_until.
        advance_clock(shift(DEFAULT_T0, hours=300))   # past 15-min hold window
        res = api.confirm_appointment(
            appt["id"], make_client_headers(client["id"]),
        )
        assert res.status_code >= 400
        balance_after = get_client(client["id"])["package_balance_sessions"]
        assert balance_after == balance_before, \
            "Failed confirm must not debit package balance"


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestRefundBoundary24hInclusive:
    """difficulty: boundary_precision_check/refund_boundary_24h_inclusive"""

    def test_24h_exactly_full_refund(self):
        """PRD §3.5: "hours-to-start at least twenty-four yields
        `FULL_REFUNDED`..." (final transition uses >=).

        difficulty: boundary_precision_check/refund_boundary_24h_inclusive
        """
        counselor, client, confirmed = setup_appointment_at_24h_boundary()
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "FULL_REFUNDED"

    def test_just_below_24h_partial_refund(self):
        """PRD §3.5: "hours-to-start less than twenty-four but at least
        two yields `PARTIAL_REFUNDED`..."

        difficulty: boundary_precision_check/refund_boundary_24h_inclusive
        """
        counselor, client = setup_counselor_and_completed_client()
        slot_start = shift(DEFAULT_T0, hours=400)
        slot = create_slot(counselor=counselor, start_at=slot_start)
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        # Anchor clock at start_at - 23h59m (just under 24h).
        advance_clock(shift(slot_start, hours=-23, minutes=-59))
        cancelled = cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        assert cancelled["refund_state"] == "PARTIAL_REFUNDED"


class TestDailyCapBoundary480Strict:
    """difficulty: boundary_precision_check/daily_cap_boundary_480_strict_exceed"""

    def test_eighth_slot_at_480_minutes_allowed(self):
        """PRD §2.11: "The thresholds are applied with strict greater-than-
        cap rejection: a day total landing exactly on eight hours is
        permitted, eight hours and one minute is not."

        difficulty: boundary_precision_check/daily_cap_boundary_480_strict_exceed
        """
        counselor, slots = setup_counselor_with_seven_60min_slots_same_local_day()
        # 7 slots already; 8th brings total to 480 (== cap, allowed).
        eighth_start = shift("2026-06-01T17:00:00.000Z", minutes=75 * 7)
        eighth = create_slot(counselor=counselor, start_at=eighth_start)
        assert eighth["status"] == "OPEN"

    def test_ninth_slot_at_540_minutes_rejected(self, api):
        """PRD §2.11: "a day total landing exactly on eight hours is
        permitted, eight hours and one minute is not." — 9th slot brings
        total to 540 > 480, must be rejected with ERR_DAILY_CAP_EXCEEDED.

        difficulty: boundary_precision_check/daily_cap_boundary_480_strict_exceed
        """
        counselor, slots = setup_counselor_with_seven_60min_slots_same_local_day()
        # Add 8th, then attempt 9th.
        eighth_start = shift("2026-06-01T17:00:00.000Z", minutes=75 * 7)
        create_slot(counselor=counselor, start_at=eighth_start)
        ninth_start = shift("2026-06-01T17:00:00.000Z", minutes=75 * 8)
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=ninth_start,
            end_at=shift(ninth_start, minutes=60),
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_DAILY_CAP_EXCEEDED", expected_status=422)


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestAppointmentConfirmDependsOnCounselorActive:
    """difficulty: cross_entity_state_dependency/appointment_confirm_depends_on_counselor_active"""

    def test_confirm_after_counselor_disqualified_rejects(self, api):
        """PRD §2.12: "When a counselor disqualification completes while an
        appointment confirm is in flight, the in-flight confirm is
        rejected with `ERR_COUNSELOR_NOT_ACTIVE` and HTTP 409 because the
        counselor is no longer `ACTIVE` at the moment the confirm reaches
        its state check."

        Sequential surrogate (the implementer-test harness can't truly
        race): we disqualify the counselor BEFORE the client invokes
        confirm. PRD prose still requires ERR_COUNSELOR_NOT_ACTIVE.

        Two-reader: PRD §3.2 disqualify also cascades the appointment to
        CANCELLED, in which case ERR_INVALID_STATE is also a faithful
        outcome. Accept either.

        difficulty: cross_entity_state_dependency/appointment_confirm_depends_on_counselor_active
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        # Disqualify before confirm.
        disqualify_counselor(counselor)
        res = api.confirm_appointment(
            appt["id"], make_client_headers(client["id"]),
        )
        validate_error_is_one_of(
            res, ["ERR_COUNSELOR_NOT_ACTIVE", "ERR_INVALID_STATE"],
        )

    def test_start_after_suspension_rejected(self, api):
        """PRD §3.5: "the transition from `CONFIRMED` to `IN_SESSION` is
        admitted only while ... the counselor is `ACTIVE`."

        difficulty: cross_entity_state_dependency/appointment_confirm_depends_on_counselor_active
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        # Drive cycle 2 to expire (suspends the counselor).
        from test_helpers import fetch_open_cycle_for
        cycle2 = fetch_open_cycle_for(counselor["id"])
        advance_clock(shift(cycle2["window_end_at"], seconds=1))
        sweep_recert()
        # Counselor is now SUSPENDED. Attempt to start.
        # First anchor clock back to slot.start_at - 4m (within window).
        # Clock is monotonic; advance to slot.start - 4m if it's in the future.
        anchor = shift(slot["start_at"], minutes=-4)
        if parse_iso(anchor) > parse_iso(cycle2["window_end_at"]):
            advance_clock(anchor)
        res = api.start_appointment(
            confirmed["id"], make_counselor_headers(counselor["id"]),
        )
        validate_error_is_one_of(
            res, ["ERR_COUNSELOR_NOT_ACTIVE", "ERR_INVALID_STATE"],
        )


class TestSlotHoldDependsOnAssessment:
    """difficulty: cross_entity_state_dependency/slot_hold_depends_on_client_assessment"""

    def test_pending_client_standard_booking_rejected(self, api):
        """PRD §3.3: "a client whose `assessment_status` is `PENDING` and
        who attempts to book a `STANDARD` or `FOLLOW_UP` appointment is
        rejected with `ERR_INTAKE_REQUIRED`."

        difficulty: cross_entity_state_dependency/slot_hold_depends_on_client_assessment
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        assert client["assessment_status"] == "PENDING"
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot["id"],
            appointment_type="STANDARD",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_INTAKE_REQUIRED", expected_status=422)
        # Slot must remain OPEN.
        slots_after = api_client.list_availability_slots(
            make_admin_headers(),
            params={"counselor_id": counselor["id"], "limit": 100},
        ).json()
        target = next(s for s in slots_after["data"] if s["id"] == slot["id"])
        assert target["status"] == "OPEN"

    def test_in_progress_client_second_intake_rejected(self, api):
        """PRD §3.3: "a client whose `assessment_status` is `IN_PROGRESS`
        ... may not book a second `INTAKE` — the request is rejected with
        `ERR_INTAKE_ALREADY_IN_PROGRESS`."

        difficulty: cross_entity_state_dependency/slot_hold_depends_on_client_assessment
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot1 = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        appt1 = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot1,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirm_appointment(client, appt1)
        # Now client.assessment_status == IN_PROGRESS.
        slot2 = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=300))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot2["id"],
            appointment_type="INTAKE",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_INTAKE_ALREADY_IN_PROGRESS", expected_status=422)


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestSlotOverlapAndRestInterval:
    """difficulty: resource_temporal_overlap/slot_overlap_with_pre_buffer_rest_interval"""

    def test_adjacent_zero_gap_allowed(self):
        """PRD §2.11: "two slots that touch end-to-start at exactly the
        same instant are adjacent, not overlapping."

        difficulty: resource_temporal_overlap/slot_overlap_with_pre_buffer_rest_interval
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)
        s2 = create_slot(counselor=counselor, start_at=shift(s1_start, minutes=60))
        assert s2["status"] == "OPEN"

    def test_overlap_inside_existing_slot_rejected(self, api):
        """PRD §2.11: "the proposed slot must not overlap any other slot
        of the same counselor in `OPEN`, `HELD`, or `BOOKED` status."

        difficulty: resource_temporal_overlap/slot_overlap_with_pre_buffer_rest_interval
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)
        # Overlap: 30 minutes inside the first.
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=shift(s1_start, minutes=30),
            end_at=shift(s1_start, minutes=90),
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_SLOT_OVERLAP", expected_status=422)

    def test_rest_interval_violation_rejected(self, api):
        """PRD §2.11: "any gap strictly greater than zero and strictly less
        than fifteen minutes violates the rest interval."

        difficulty: resource_temporal_overlap/slot_overlap_with_pre_buffer_rest_interval
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        s1_start = shift(DEFAULT_T0, hours=200)
        create_slot(counselor=counselor, start_at=s1_start)
        # 10-minute gap.
        payload = create_availability_slot_payload(
            counselor_id=counselor["id"],
            start_at=shift(s1_start, minutes=70),
            end_at=shift(s1_start, minutes=130),
        )
        res = api.create_availability_slot(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_REST_INTERVAL", expected_status=422)


class TestSupervisionSymmetricBuffer:
    """difficulty: resource_temporal_overlap/supervision_symmetric_30m_buffer"""

    def test_overlapping_supervisions_rejected(self, api):
        """PRD §3.10: "the proposed supervision must not collide with
        another non-`REJECTED` SupervisionSession for the same
        `supervisor_id` whose 30-minute symmetric buffer overlaps. The
        buffer for both rows is the half-open interval starting at
        `scheduled_at` minus 30 minutes and ending strictly before
        `scheduled_at` plus 30 minutes; an intersection with another such
        buffer surfaces as `ERR_INVALID_STATE`."

        difficulty: resource_temporal_overlap/supervision_symmetric_30m_buffer
        """
        # Need a counselor with a COMPLETED appointment to use as case.
        counselor, client = setup_counselor_and_completed_client()
        from test_helpers import start_appointment, complete_appointment, create_counseling_record
        # Build a COMPLETED appointment to use as case_appointment_id.
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        advance_clock(shift(slot["start_at"], minutes=-4))
        started = start_appointment(counselor, confirmed)
        from test_helpers import create_counseling_record as ccr
        ccr(counselor=counselor, appointment=started,
            encrypted_note_blob="aGVsbG8td29ybGQ=")
        complete_appointment(counselor, started)

        # Create a supervisor with overlapping specialty.
        supervisor = create_counselor(
            specialty_tags=["ANXIETY", "DEPRESSION", "TRAUMA"],
        )
        scheduled1 = shift(DEFAULT_T0, hours=500)
        # First supervision succeeds.
        first = validate_success(
            api.create_supervision_session(
                create_supervision_session_payload(
                    counselor_id=counselor["id"],
                    supervisor_id=supervisor["id"],
                    case_appointment_id=started["id"],
                    scheduled_at=scheduled1,
                    duration_hours=1.0,
                ),
                make_counselor_headers(counselor["id"]),
            ),
            expected_status=201,
        )
        # Second supervision 25 minutes later — overlaps the symmetric
        # 30-minute buffer.
        scheduled2 = shift(scheduled1, minutes=25)
        res = api.create_supervision_session(
            create_supervision_session_payload(
                counselor_id=counselor["id"],
                supervisor_id=supervisor["id"],
                case_appointment_id=started["id"],
                scheduled_at=scheduled2,
                duration_hours=1.0,
            ),
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_non_overlapping_supervisions_allowed(self, api):
        """PRD §3.10: 30-minute buffer is symmetric; gap of >= 60m allows
        both. Validates the upper-side of the buffer.

        difficulty: resource_temporal_overlap/supervision_symmetric_30m_buffer
        """
        counselor, client = setup_counselor_and_completed_client()
        from test_helpers import start_appointment, complete_appointment, create_counseling_record
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        advance_clock(shift(slot["start_at"], minutes=-4))
        started = start_appointment(counselor, confirmed)
        create_counseling_record(
            counselor=counselor, appointment=started,
            encrypted_note_blob="aGVsbG8td29ybGQ=",
        )
        complete_appointment(counselor, started)

        supervisor = create_counselor(
            specialty_tags=["ANXIETY", "DEPRESSION", "TRAUMA"],
        )
        scheduled1 = shift(DEFAULT_T0, hours=500)
        validate_success(
            api.create_supervision_session(
                create_supervision_session_payload(
                    counselor_id=counselor["id"],
                    supervisor_id=supervisor["id"],
                    case_appointment_id=started["id"],
                    scheduled_at=scheduled1,
                    duration_hours=1.0,
                ),
                make_counselor_headers(counselor["id"]),
            ),
            expected_status=201,
        )
        # 90 minutes apart — outside the 30-min symmetric buffer.
        scheduled2 = shift(scheduled1, minutes=90)
        validate_success(
            api.create_supervision_session(
                create_supervision_session_payload(
                    counselor_id=counselor["id"],
                    supervisor_id=supervisor["id"],
                    case_appointment_id=started["id"],
                    scheduled_at=scheduled2,
                    duration_hours=1.0,
                ),
                make_counselor_headers(counselor["id"]),
            ),
            expected_status=201,
        )


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestPackageBalanceInvariantUnderFullRefund:
    """difficulty: compensating_invariant/package_balance_invariant_under_full_refund"""

    def test_round_trip_preserves_package_balance(self):
        """PRD §3.4: "if the payment mode is `PACKAGE` the client's
        `package_balance_sessions` is decremented by one." (forward action)
        PRD §3.5: "When `refund_state` is `FULL_REFUNDED` or
        `PARTIAL_REFUNDED` and the appointment had been paid by `PACKAGE`,
        the client's `package_balance_sessions` is incremented by one as
        part of the same operation." (compensating action)

        Invariant: round-trip leaves balance unchanged.

        difficulty: compensating_invariant/package_balance_invariant_under_full_refund
        """
        counselor, client = setup_counselor_and_completed_client(
            package_balance_sessions=5,
        )
        slot_start = shift(DEFAULT_T0, hours=400)
        slot = create_slot(counselor=counselor, start_at=slot_start)
        balance_before = get_client(client["id"])["package_balance_sessions"]
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        confirmed = confirm_appointment(client, appt)
        # Hours-to-start ~ 400h, FULL refund.
        cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        balance_after = get_client(client["id"])["package_balance_sessions"]
        assert balance_after == balance_before, \
            "PRD §3.4 + §3.5: package balance round-trip must net to zero change"

    # Deletion note (STEP 1b unique-derivability failure): PRD §3.8 fixes
    # the PACKAGE CHARGE counselor_share at SHADOW_PACKAGE_RATE (9000) *
    # revenue_share_bps / 10000 while PRD §3.5 fixes the FULL refund
    # counselor_share at list_price_cents (12000) * revenue_share_bps /
    # 10000. The two formulas are PRD-asymmetric for PACKAGE round trips,
    # so a faithful PRD-only implementer cannot produce a zero net for the
    # counselor_share component (the platform absorbs the gap by design,
    # PRD §3.8 "platform absorbs that share from prior package revenue").
    # Net for default share (7000 bps): 6300 - 8400 = -2100, not zero.

class TestCashLedgerInvariantUnderFullRefund:
    """difficulty: compensating_invariant/cash_ledger_invariant_under_full_refund"""

    def test_round_trip_components_sum_to_zero(self):
        """PRD §3.8: "For `PAY_PER_SESSION`, `gross_amount_cents` equals
        the appointment's frozen `list_price_cents`..." (CHARGE)
        PRD §3.5: "All three components are recorded with negative sign
        on the REFUND row of `SettlementLedger`." (REFUND)

        Invariant: per-component sums net to zero.

        difficulty: compensating_invariant/cash_ledger_invariant_under_full_refund
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=7000,
        )
        cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        assert sum(r["gross_amount_cents"] for r in rows) == 0
        assert sum(r["tax_cents"] for r in rows) == 0
        assert sum(r["counselor_share_cents"] for r in rows) == 0
        assert sum(r["platform_share_cents"] for r in rows) == 0

    def test_round_trip_emits_exactly_two_rows(self):
        """PRD §3.4: "a CHARGE row is written to `SettlementLedger`..."
        PRD §3.5: "All three components are recorded with negative sign on
        the REFUND row..."

        difficulty: compensating_invariant/cash_ledger_invariant_under_full_refund
        """
        counselor, client, _slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
            revenue_share_bps=7000,
        )
        cancel_appointment(
            actor_headers=make_client_headers(client["id"]),
            appointment=confirmed, reason="CLIENT_CANCEL",
        )
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        directions = sorted(r["direction"] for r in rows)
        assert directions == ["CHARGE", "REFUND"]
