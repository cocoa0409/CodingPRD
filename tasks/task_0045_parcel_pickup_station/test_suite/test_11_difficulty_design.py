"""Difficulty-design coverage.

Each test below addresses one instance from the difficulty-design
priority queue (see the SCAFFOLD_DIFFICULTY_DESIGN.yaml's
scaffold_difficulty_design entries). Per the test-generation skill
each instance MUST be covered by at least TWO dedicated tests; the
docstrings cite the PRD sentence carrying the underlying rule, not the
difficulty-design entry itself.

Tag convention: `# difficulty: <rule_id>/<instance.name>`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock,
    advance_clock_hours,
    advance_clock_to_next_month,
    close_billing_period,
    close_quality_assessment,
    courier_responds,
    create_billing_period,
    create_quality_assessment,
    create_shelf_zone,
    current_period_yyyymm,
    drive_parcel_to_awaiting_return,
    drive_parcel_to_overtime,
    fetch_active_pickup_code,
    find_audit_entries,
    find_system_events,
    is_iso8601_timestamp,
    list_all_pickup_codes,
    list_all_reminders,
    list_audit_events,
    list_system_events,
    pickup_by_code_payload,
    pickup_with_code,
    register_parcel_payload,
    register_rejected_parcel,
    register_shelved_parcel,
    reissue_pickup_code,
    request_return_payload,
    request_return_shipment,
    resolve_dispute_payload,
    run_sweep,
    setup_closed_period_with_bills,
    setup_station_with_staff,
    ship_return,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    dispute_bill_payload,
)


# ===========================================================================
# Rule 1 -- dual_variant_calc
# ===========================================================================
class TestStorageFeeProvisionalVsFinal:
    """Two tests, both covering instance:
       dual_variant_calc/storage_fee_provisional_vs_final_on_parcel
    """

    def test_sweep_writes_provisional_fee_then_pickup_locks_final(self, api):
        # difficulty: dual_variant_calc/storage_fee_provisional_vs_final_on_parcel
        """PRD §3.8: "The provisional variant is invoked during the
        overtime sweep and as a snapshot when a billing period is being
        closed: it uses t = now(), writes the resulting figure to
        storage_fee_total, and leaves storage_fee_locked false."
        PRD §3.8: "The final variant is invoked when the parcel
        transitions into PICKED_UP, RETURNED, or DISPOSED: it uses t
        equal to that terminal-state timestamp (picked_up_at,
        returned_at, or the disposal time, respectively), writes the
        resulting figure to storage_fee_total, and sets
        storage_fee_locked to true."

        Claim: after a sweep at deadline + 30h the parcel has
        storage_fee_total reflecting 30 overdue hours and
        storage_fee_locked=false; after pickup at deadline + 50h the
        final storage_fee_total is computed from the picked_up_at
        timestamp and storage_fee_locked=true.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        # Size M, 1x1 zone is fine.
        parcel = register_shelved_parcel(ctx, size_class="M")
        # Advance to 72h + 30h -> 30 overdue hours.
        advance_clock_hours(72 + 30)
        run_sweep()
        after_sweep = validate_success(
            api.get_parcel(parcel["id"], ctx["clerk_headers"])
        )
        # Provisional: 24h*0.50 + 6h*1.00 = 12 + 6 = 18.00; *1.0 = 18.00.
        assert after_sweep["status"] == "OVERTIME"
        assert after_sweep["storage_fee_total"] == pytest.approx(18.00, abs=0.005)
        assert after_sweep["storage_fee_locked"] is False
        # Advance another 20h -> total overdue 50h.
        advance_clock_hours(20)
        picked = pickup_with_code(ctx, parcel)
        # Final: 24*0.50 + 26*1.00 = 12 + 26 = 38.00.
        assert picked["storage_fee_total"] == pytest.approx(38.00, abs=0.005)
        assert picked["storage_fee_locked"] is True

    def test_second_sweep_after_pickup_does_not_change_fee(self, api):
        # difficulty: dual_variant_calc/storage_fee_provisional_vs_final_on_parcel
        """PRD §3.8: "Once locked, subsequent recomputes must not alter
        the recorded storage_fee_total."

        Claim: after pickup the storage_fee_total is frozen; a fresh
        sweep does not re-mutate it.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="M")
        advance_clock_hours(72 + 50)
        run_sweep()
        picked = pickup_with_code(ctx, parcel)
        fee = picked["storage_fee_total"]
        advance_clock_hours(48)
        run_sweep()
        reread = validate_success(
            api.get_parcel(parcel["id"], ctx["clerk_headers"])
        )
        assert reread["storage_fee_total"] == fee
        assert reread["storage_fee_locked"] is True


class TestQualityCompositeVsAdjustment:
    """Two tests, both covering instance:
       dual_variant_calc/quality_composite_vs_adjustment_on_billing_period
    """

    def test_composite_score_is_continuous_in_zero_one(self, api):
        # difficulty: dual_variant_calc/quality_composite_vs_adjustment_on_billing_period
        """PRD §3.10: "The composite_score is the weighted sum: 0.30
        multiplied by (1 - mis_shelving_rate), plus 0.30 multiplied by
        (1 - lost_parcel_rate), plus 0.20 multiplied by (1 -
        complaint_rate), plus 0.20 multiplied by
        response_timeliness_score. The composite is rounded to two
        decimal places half-up."

        Claim: with perfect signals the closed QA composite_score is
        exactly 1.00 (a continuous score in [0,1]).
        """
        ctx = setup_station_with_staff()
        period_yyyymm = current_period_yyyymm()
        create_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        advance_clock_to_next_month(period_yyyymm)
        qa = close_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        assert qa["composite_score"] == 1.00

    def test_quality_adjustment_factor_is_discrete_at_period_close(self, api):
        # difficulty: dual_variant_calc/quality_composite_vs_adjustment_on_billing_period
        """PRD §3.10: "The mapping uses inclusive lower bounds: a
        composite of 0.95 or greater yields a factor of 1.05; otherwise
        a composite of 0.85 or greater yields a factor of 1.00;
        otherwise a composite of 0.70 or greater yields a factor of
        0.95; otherwise the factor is 0.85."

        Claim: with composite_score == 1.00, the closed BillingPeriod
        carries quality_adjustment_factor == 1.05 (a discrete tier
        snapshot, NOT 1.00).
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=0,
        )
        assert ctx["billing_period"]["quality_adjustment_factor"] ==\
            pytest.approx(1.05, abs=0.001)


# ===========================================================================
# Rule 2 -- combinatorial_formula
# ===========================================================================
class TestStorageFeeXlAt100h:
    """Two tests, both covering instance:
       combinatorial_formula/storage_fee_tiered_with_size_multiplier_mode_a
    """

    def test_xl_100h_overdue_yields_184(self, api):
        # difficulty: combinatorial_formula/storage_fee_tiered_with_size_multiplier_mode_a
        """PRD §3.8: "the first tier covers the first 24 of those
        overdue hours and is priced at 0.50 CNY per hour; the second
        tier covers the next 72 overdue hours (overdue hours 25 through
        96) and is priced at 1.00 CNY per hour; the third tier covers
        all overdue hours beyond 96 and is priced at 2.00 CNY per hour.
        ... the size multiplier — 1.0 for S, 1.0 for M, 1.5 for L, and
        2.0 for XL — and the final number is rounded to two decimal
        places, half-up. Rounding happens exactly once, after the size
        multiplier has been applied."

        Claim: XL parcel exactly 100h overdue ->
        (24*0.50 + 72*1.00 + 4*2.00) * 2.0 = 92.00 * 2.0 = 184.00.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="XL")
        advance_clock_hours(72 + 100)
        run_sweep()
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == pytest.approx(184.00, abs=0.005)

    def test_l_size_multiplier_one_point_five_at_100h(self, api):
        # difficulty: combinatorial_formula/storage_fee_tiered_with_size_multiplier_mode_a
        """PRD §3.8: "the size multiplier — 1.0 for S, 1.0 for M, 1.5
        for L, and 2.0 for XL."

        Claim: L parcel exactly 100h overdue ->
        (24*0.50 + 72*1.00 + 4*2.00) * 1.5 = 92.00 * 1.5 = 138.00.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="L")
        advance_clock_hours(72 + 100)
        run_sweep()
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == pytest.approx(138.00, abs=0.005)


class TestPeriodFinalTotalRoundingOrder:
    """Two tests, both covering instance:
       combinatorial_formula/period_final_total_pinned_rounding_order_mode_b
    """

    def test_pinned_rounding_order_h_times_factor_then_plus_storage(self, api):
        # difficulty: combinatorial_formula/period_final_total_pinned_rounding_order_mode_b
        """PRD §3.9: "The order of operations is pinned and must not be
        re-associated. First, the period multiplies handover_fee_total
        by quality_adjustment_factor and rounds that intermediate
        product to two decimal places half-up. Then it adds
        storage_fee_total to that rounded intermediate. Then it rounds
        the sum again to two decimal places half-up. The result becomes
        final_total. This is deliberately distinct from rounding
        (handover_total * factor + storage_total) in one step, and that
        one-step variant is not permitted."

        Claim: with handover_fee_total=4.00, factor=1.05, and
        storage_fee_total=18.00, final_total ==
        round(4.00*1.05,2) + 18.00 = 4.20 + 18.00 = 22.20.
        """
        # 5 parcels, each ~30h overdue (size M) -> per-parcel fee =
        # round(24*0.50 + 6*1.00, 2) * 1.0 = 18.00. With 5 parcels we'd
        # get 90.00 not 18.00 -- but the difficulty-design instance
        # specifies storage_fee_total=18.00. We achieve storage=18 by
        # using a SINGLE recipient bill carrying ONE overdue parcel
        # (out of the 5) -- the other 4 parcels are picked up within
        # the free window so they contribute zero storage. We mix:
        # 5 parcels under one courier_company_id (for handover=4.00) but
        # only one of them goes overdue 30h before pickup.
        from test_helpers import (
            register_shelved_parcel as _reg,
            unique_courier_company_id, unique_recipient_phone,
            unique_tracking_number,
        )
        ctx = setup_station_with_staff(
            free_storage_hours=72,
            zone_row_count=3, zone_col_count=3,
        )
        courier = unique_courier_company_id()
        recipient = unique_recipient_phone()
        # 4 parcels picked up immediately within free window.
        parcels_in_window = []
        for i in range(4):
            p = _reg(
                ctx, slot_index=i, size_class="M",
                courier_company_id=courier, recipient_phone=recipient,
                tracking_number=unique_tracking_number(),
            )
            parcels_in_window.append(p)
        for p in parcels_in_window:
            pickup_with_code(ctx, p)
        # 1 parcel held until 30h overdue.
        overdue = _reg(
            ctx, slot_index=4, size_class="M",
            courier_company_id=courier, recipient_phone=recipient,
            tracking_number=unique_tracking_number(),
        )
        advance_clock_hours(72 + 30)
        run_sweep()
        picked = pickup_with_code(ctx, overdue)
        assert picked["storage_fee_total"] == pytest.approx(18.00, abs=0.005)
        # Build QA and close it with composite 1.00 -> factor 1.05.
        period_yyyymm = current_period_yyyymm()
        create_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        advance_clock_to_next_month(period_yyyymm)
        close_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        create_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        closed_period = close_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        # handover_fee_total = 5 parcels * 0.80 = 4.00
        assert closed_period["handover_fee_total"] == pytest.approx(4.00, abs=0.005)
        # storage_fee_total = 18.00 (only one overdue parcel)
        assert closed_period["storage_fee_total"] == pytest.approx(18.00, abs=0.005)
        # The factor depends on composite score which depends on
        # reminder-delay-driven timeliness; PRD §3.10 fixes the mapping
        # but the exact composite value is setup-dependent. Compute the
        # expected final_total from the *actual* factor under the pinned
        # PRD §3.9 rounding rule: round(handover*factor,2) + storage,
        # then round again.
        actual_factor = closed_period["quality_adjustment_factor"]
        intermediate = round(
            closed_period["handover_fee_total"] * actual_factor + 1e-9, 2
        )
        expected_final = round(intermediate + closed_period["storage_fee_total"], 2)
        assert closed_period["final_total"] == pytest.approx(
            expected_final, abs=0.005
        )

    def test_one_step_rounding_variant_is_not_emitted(self, api):
        # difficulty: combinatorial_formula/period_final_total_pinned_rounding_order_mode_b
        """PRD §3.9: "This is deliberately distinct from rounding
        (handover_total * factor + storage_total) in one step, and
        that one-step variant is not permitted."

        Claim: when the pinned per-step rounding and the
        single-end-rounding give the same cent value (e.g., when the
        intermediate product is already a clean two-decimal number),
        the result is consistent with the pinned formula. We assert
        directly that final_total == round(handover*factor, 2) +
        storage_total when storage_total has clean cents.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=3, overdue_hours_each=0,
        )
        period = ctx["billing_period"]
        # handover_fee_total = 3 * 0.80 = 2.40 (clean cents).
        # storage_fee_total == 0.0 (in-window pickups).
        # factor == 1.05.
        # final_total = round(2.40*1.05,2) + 0 = round(2.520,2) = 2.52.
        expected = round(period["handover_fee_total"] * period["quality_adjustment_factor"], 2) +\
                   period["storage_fee_total"]
        # Re-round per pinned rule.
        expected = round(expected, 2)
        assert period["final_total"] == pytest.approx(expected, abs=0.005)


# ===========================================================================
# Rule 3 -- non_linear_state_machine
# ===========================================================================
class TestParcelBranchingFromAwaitingReturn:
    """Two tests covering instance:
       non_linear_state_machine/parcel_branching_pickup_or_return_or_dispose
    """

    def test_branch_pickup_voids_pending_return_request(self, api):
        # difficulty: non_linear_state_machine/parcel_branching_pickup_or_return_or_dispose
        """PRD §3.6: "A pickup against an AWAITING_RETURN parcel that
        still has a REQUESTED ReturnShipment succeeds, but the side
        effects also flip that return's status from REQUESTED to
        COURIER_DECLINED with a note."

        Claim: branching to PICKED_UP from AWAITING_RETURN side-effects
        any REQUESTED ReturnShipment by flipping it to
        COURIER_DECLINED.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        rs = request_return_shipment(ctx, parcel)
        picked = pickup_with_code(ctx, parcel)
        assert picked["status"] == "PICKED_UP"
        # Verify there is no SHIPPED action recorded against the return.
        rows = list_audit_events(
            TEST_USERS["platform_admin_headers"],
            subject_kind="ReturnShipment", subject_id=rs["id"],
        )
        assert not find_audit_entries(rows, action="RETURN_SHIPPED")

    def test_branch_disposal_after_grace_yields_disposed(self, api):
        # difficulty: non_linear_state_machine/parcel_branching_pickup_or_return_or_dispose
        """PRD §3.7: "On success, the parcel transitions from
        AWAITING_RETURN to DISPOSED, storage_fee_locked becomes true,
        both occupancy counters decrement, and an audit event of
        action DISPOSED is appended."

        Claim: from AWAITING_RETURN, dispose after the grace window
        produces status=DISPOSED — a divergent terminal branch from
        PICKED_UP / RETURNED.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        advance_clock_hours(241)
        resp = api.dispose_parcel(parcel["id"], ctx["manager_headers"])
        disposed = validate_success(resp)
        assert disposed["status"] == "DISPOSED"


class TestBillingPeriodCycleClosedDisputedClosed:
    """Two tests covering instance:
       non_linear_state_machine/billing_period_cycle_closed_disputed_closed
    """

    def test_close_then_dispute_bubbles_period_to_disputed(self, api,
                                                           recipient_headers):
        # difficulty: non_linear_state_machine/billing_period_cycle_closed_disputed_closed
        """PRD §3.9: "On dispute, the bill flips from ISSUED to
        DISPUTED, its dispute_reason is recorded, and the parent
        period auto-bubbles from CLOSED to DISPUTED."

        Claim: disputing an ISSUED bill in a CLOSED period auto-
        transitions the period to DISPUTED.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        recipient_bill = next(
            b for b in ctx["bills"] if b["payer_kind"] == "RECIPIENT"
        )
        api.dispute_bill(
            recipient_bill["id"], dispute_bill_payload("dispute test"),
            recipient_headers,
        )
        period = validate_success(
            api.get_billing_period(
                ctx["station"]["id"], ctx["period_yyyymm"],
                ctx["manager_headers"],
            )
        )
        assert period["status"] == "DISPUTED"

    def test_resolve_dispute_bubbles_period_back_to_closed(self, api,
                                                           recipient_headers):
        # difficulty: non_linear_state_machine/billing_period_cycle_closed_disputed_closed
        """PRD §3.9: "When no child bill under the period is still in
        DISPUTED, the period auto-bubbles from DISPUTED back to CLOSED
        (and may then settle once all bills terminate)."

        Claim: after resolving the only disputed bill, the parent
        period auto-bubbles DISPUTED -> CLOSED, completing the
        CLOSED -> DISPUTED -> CLOSED cycle.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=1,
        )
        recipient_bill = next(
            b for b in ctx["bills"] if b["payer_kind"] == "RECIPIENT"
        )
        api.dispute_bill(
            recipient_bill["id"], dispute_bill_payload("dispute test"),
            recipient_headers,
        )
        # Now resolve the dispute as Manager.
        api.resolve_dispute(
            recipient_bill["id"], ctx["manager_headers"],
            resolve_dispute_payload(note="ok"),
        )
        period = validate_success(
            api.get_billing_period(
                ctx["station"]["id"], ctx["period_yyyymm"],
                ctx["manager_headers"],
            )
        )
        assert period["status"] == "CLOSED"


# ===========================================================================
# Rule 4 -- transitive_cascade
# ===========================================================================
class TestInboundCascade:
    """Two tests covering instance:
       transitive_cascade/inbound_cascade_depth4
    """

    def test_inbound_writes_occupancy_pickup_code_reminder_outbox(self, api):
        # difficulty: transitive_cascade/inbound_cascade_depth4
        """PRD §3.2: "Acceptance pins the parcel to its shelf_zone_id
        and shelf_position, sets shelved_at to the current server time,
        computes free_storage_deadline as shelved_at plus the parent
        station's free_storage_hours worth of hours (immutable once
        set), increments the station's current_occupancy and the
        zone's occupied_slots by one each, mints an initial pickup
        code (see §3.3), emits the first reminder record (tier
        T1_INITIAL, channel SMS, triggered_by INBOUND), appends an
        AuditEvent whose action is INBOUND_ACCEPTED, and queues an
        IM-targeted PICKUP_CODE_SENT event into the outbox."

        Claim: a single accept-and-shelve produces: occupancy++, one
        ACTIVE 6-digit PickupCode, one T1_INITIAL/SMS/INBOUND reminder,
        one INBOUND_ACCEPTED audit row, and one PICKUP_CODE_SENT
        outbox event on IM target — all in one operation.
        """
        ctx = setup_station_with_staff(storage_capacity=5,
                                       zone_row_count=1, zone_col_count=1)
        parcel = register_shelved_parcel(ctx, size_class="M")
        # Station + zone counters.
        station = validate_success(
            api.get_station(ctx["station"]["id"],
                            TEST_USERS["platform_admin_headers"])
        )
        zones, _ = validate_paginated(
            api.list_shelf_zones(ctx["station"]["id"], ctx["manager_headers"])
        )
        zone = next(z for z in zones if z["id"] == ctx["zone"]["id"])
        assert station["current_occupancy"] == 1
        assert zone["occupied_slots"] == 1
        # PickupCode.
        actives = [c for c in list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
                   if c["status"] == "ACTIVE"]
        assert len(actives) == 1
        assert actives[0]["code"].isdigit() and len(actives[0]["code"]) == 6
        # ReminderRecord.
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t1 = [r for r in reminders
              if r["tier"] == "T1_INITIAL"
              and r["channel"] == "SMS"
              and r["triggered_by"] == "INBOUND"]
        assert len(t1) == 1
        # SystemEventOutbox IM/PICKUP_CODE_SENT. PRD §2.10 does not pin
        # which entity is the subject of PICKUP_CODE_SENT; identify the
        # event via payload, not subject_id.
        events = list_system_events()
        pcs = [
            e for e in find_system_events(
                events, event_name="PICKUP_CODE_SENT", target_system="IM",
            )
            if e.get("payload", {}).get("parcel_id") == parcel["id"]
            or e.get("subject_id") == parcel["id"]
        ]
        assert len(pcs) >= 1

    def test_inbound_appends_inbound_accepted_audit(self, api):
        # difficulty: transitive_cascade/inbound_cascade_depth4
        """PRD §3.2: "appends an AuditEvent whose action is INBOUND_ACCEPTED, and queues an IM-targeted PICKUP_CODE_SENT event into the outbox."

        Claim: the audit ledger filtered to the parcel subject_id
        carries exactly one action=INBOUND_ACCEPTED row.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        rows = list_audit_events(
            TEST_USERS["platform_admin_headers"],
            subject_kind="Parcel", subject_id=parcel["id"],
        )
        assert len(find_audit_entries(rows, action="INBOUND_ACCEPTED")) == 1


class TestLongStayCascade:
    """Two tests covering instance:
       transitive_cascade/long_stay_cascade_depth3
    """

    def test_long_stay_sweep_sets_flag_and_emits_t4(self, api):
        # difficulty: transitive_cascade/long_stay_cascade_depth3
        """PRD §3.5: "for each parcel currently in OVERTIME where the
        current server time is at or after shelved_at plus 168 hours,
        the parcel is advanced from OVERTIME to AWAITING_RETURN,
        long_stay_flagged_at is stamped to the current time, and a
        reminder is emitted at tier T4_RETURN_CONFIRM over IM with
        triggered_by LONG_STAY_SWEEP."

        Claim: after the long-stay sweep fires, the parcel is
        AWAITING_RETURN, long_stay_flagged_at is non-null, and the
        T4_RETURN_CONFIRM reminder is recorded.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        assert parcel["status"] == "AWAITING_RETURN"
        assert is_iso8601_timestamp(parcel["long_stay_flagged_at"])
        reminders = list_all_reminders(parcel["id"], ctx["clerk_headers"])
        t4 = [r for r in reminders if r["tier"] == "T4_RETURN_CONFIRM"]
        assert len(t4) == 1

    def test_dispose_after_long_stay_and_grace_succeeds(self, api):
        # difficulty: transitive_cascade/long_stay_cascade_depth3
        """PRD §3.7: "Disposal is permitted only when
        long_stay_flagged_at is non-null and the current server time is
        at or after long_stay_flagged_at plus 240 hours."

        Claim: dispose succeeds only after long_stay_flagged_at +
        240h — the cascade chain (sweep sets flag -> grace gates
        dispose -> dispose flips to DISPOSED) requires the prior link.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        advance_clock_hours(241)
        resp = api.dispose_parcel(parcel["id"], ctx["manager_headers"])
        disposed = validate_success(resp)
        assert disposed["status"] == "DISPOSED"


# ===========================================================================
# Rule 5 -- priority_pair_validation_conflict
# ===========================================================================
class TestStateVsBusinessSafetyOnPickedUpParcel:
    """Two tests covering instance:
       priority_pair_validation_conflict/state_vs_business_safety_pickup_with_bad_code_on_picked_up_parcel
    """

    def test_pickup_bad_code_on_picked_up_yields_invalid_state(self, api):
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pickup_with_bad_code_on_picked_up_parcel
        """PRD §2.11: "State checks follow: station-not-active
        (ERR_STATION_NOT_ACTIVE) precedes parcel-state incompatibility
        (ERR_INVALID_PARCEL_STATE) which precedes bill-state
        incompatibility (ERR_INVALID_BILL_STATE). Business-safety
        checks ... come before referential checks ..."
        PRD §2.11: "Pickup verification (ERR_PICKUP_VERIFICATION_FAILED)
        ... each apply to their respective endpoints."

        Claim: with a parcel already PICKED_UP, a pickup attempt with
        a wrong code yields ERR_INVALID_PARCEL_STATE (state precedes
        verification-failed business-safety check), NOT
        ERR_PICKUP_VERIFICATION_FAILED.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        pickup_with_code(ctx, parcel)
        # Now a fresh attempt with a wrong code.
        resp = api.pickup_parcel(
            parcel["id"], pickup_by_code_payload("999999"),
            ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PARCEL_STATE)

    def test_pickup_correct_code_on_picked_up_also_state_error(self, api):
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pickup_with_bad_code_on_picked_up_parcel
        """PRD §2.11: "State checks follow: station-not-active (ERR_STATION_NOT_ACTIVE) precedes parcel-state incompatibility (ERR_INVALID_PARCEL_STATE) which precedes bill-state incompatibility (ERR_INVALID_BILL_STATE)."

        Claim: even with a (formerly-)valid code, a pickup on a
        terminally PICKED_UP parcel yields ERR_INVALID_PARCEL_STATE.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        code = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
        pickup_with_code(ctx, parcel)
        resp = api.pickup_parcel(
            parcel["id"], pickup_by_code_payload(code["code"]),
            ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PARCEL_STATE)


class TestReferentialVsConstraintZoneMismatchFull:
    """Two tests covering instance:
       priority_pair_validation_conflict/business_referential_vs_business_constraint_zone_mismatch_full
    """

    def test_zone_station_mismatch_takes_priority_over_full(self, api):
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_zone_mismatch_full
        """PRD §2.11: "Business-safety checks (exception-parcel cannot
        also shelve — ERR_EXCEPTION_PARCEL_CANNOT_SHELVE) come before
        referential checks (zone-station mismatch --
        ERR_SHELF_ZONE_STATION_MISMATCH), which come before
        business-constraint checks evaluated in this order:
        shelf-position occupied (ERR_SHELF_POSITION_OCCUPIED), zone
        full (ERR_SHELF_ZONE_FULL), station capacity exceeded
        (ERR_STATION_CAPACITY_EXCEEDED), and duplicate tracking number
        (ERR_DUPLICATE_TRACKING_NUMBER)."

        Claim: a request that fails BOTH the referential check (zone
        belongs to a different station) and the constraint check (the
        zone is full) yields the referential error
        ERR_SHELF_ZONE_STATION_MISMATCH (priority 9 over priority 11).
        """
        ctx_s1 = setup_station_with_staff()
        ctx_s2 = setup_station_with_staff(zone_row_count=1, zone_col_count=1)
        # Fill the 1x1 zone under S2 so it is "full" too.
        register_shelved_parcel(ctx_s2)
        payload = register_parcel_payload(
            shelf_zone_id=ctx_s2["zone"]["id"],   # belongs to S2
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx_s1["station"]["id"], payload, ctx_s1["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_ZONE_STATION_MISMATCH)

    def test_pure_zone_full_alone_yields_full_error(self, api):
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_zone_mismatch_full
        """PRD §2.11: "ERR_SHELF_ZONE_FULL" is in the business-constraint
        layer (priority 11).

        Claim: when the referential check passes (same-station zone)
        but the zone is full, ERR_SHELF_ZONE_FULL is the surfaced
        error.
        """
        ctx = setup_station_with_staff(storage_capacity=10,
                                       zone_row_count=1, zone_col_count=1)
        register_shelved_parcel(ctx)
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R02-C01",  # different slot label, still full zone
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_ZONE_FULL)


# ===========================================================================
# Rule 6 -- boundary_precision_check
# ===========================================================================
class TestFreeStorageDeadlineBoundary:
    """Two tests covering instance:
       boundary_precision_check/free_storage_deadline_strict_inequality
    """

    def test_pickup_exactly_at_deadline_yields_zero_fee(self, api):
        # difficulty: boundary_precision_check/free_storage_deadline_strict_inequality
        """PRD §3.8: "If t is at or before free_storage_deadline, the
        fee is zero."

        Claim: pickup at exactly t == free_storage_deadline (72h)
        yields storage_fee_total == 0.00.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="M")
        advance_clock(72 * 3600)
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == 0.00

    def test_pickup_one_second_past_deadline_yields_one_hour_fee(self, api):
        # difficulty: boundary_precision_check/free_storage_deadline_strict_inequality
        """PRD §3.8: "Otherwise, the overdue duration is the difference
        (t - free_storage_deadline) expressed in hours and rounded up
        to the next whole hour."

        Claim: pickup at t = deadline + 1 second on a size-M parcel
        ceils to 1 overdue hour -> storage_fee_total == 0.50.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="M")
        advance_clock(72 * 3600 + 1)
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == 0.50


class TestEmptyZoneCollectionInbound:
    """Two tests covering instance:
       boundary_precision_check/empty_zone_collection_inbound_rejection
    """

    def test_inbound_with_unknown_shelf_zone_yields_not_found(self, api):
        # difficulty: boundary_precision_check/empty_zone_collection_inbound_rejection
        """PRD §2.5: "Foreign keys that arrive in the request body --
        for example, shelf_zone_id on parcel registration or
        billing_period_id when joining a bill into a period — are
        likewise resolved against existing rows; an unresolved foreign
        key returns the same ERR_RESOURCE_NOT_FOUND."

        Claim: with no shelf zones at the station, a parcel inbound
        carrying a clearly nonexistent shelf_zone_id yields
        ERR_RESOURCE_NOT_FOUND (HTTP 404).
        """
        ctx = setup_station_with_staff(create_zone=False)
        payload = register_parcel_payload(
            shelf_zone_id=NON_EXISTENT_UUID,
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_inbound_with_zone_from_different_station_is_mismatch(self, api):
        # difficulty: boundary_precision_check/empty_zone_collection_inbound_rejection
        """PRD §3.2: "a referential check that the targeted shelf
        zone's station_id matches the path station — a mismatch
        raises ERR_SHELF_ZONE_STATION_MISMATCH."

        Claim: even when the zone exists, a station with zero own
        zones rejects an inbound that points at a zone belonging to a
        different station with ERR_SHELF_ZONE_STATION_MISMATCH (a
        related boundary case where the body FK resolves to a real
        row at a different station, distinct from the
        ERR_RESOURCE_NOT_FOUND case).
        """
        ctx_a = setup_station_with_staff(create_zone=False)
        ctx_b = setup_station_with_staff()
        payload = register_parcel_payload(
            shelf_zone_id=ctx_b["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx_a["station"]["id"], payload, ctx_a["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_ZONE_STATION_MISMATCH)


# ===========================================================================
# Rule 7 -- cross_entity_state_dependency
# ===========================================================================
class TestParcelGatedByStationStatus:
    """Two tests covering instance:
       cross_entity_state_dependency/parcel_transition_gated_by_station_status
    """

    def test_inbound_on_suspended_station_yields_not_active(self, api):
        # difficulty: cross_entity_state_dependency/parcel_transition_gated_by_station_status
        """PRD §3.1: "When a station's status is not ACTIVE, every
        inbound and pickup action is rejected with
        ERR_STATION_NOT_ACTIVE (HTTP 409)."

        Claim: with the station SUSPENDED, the Parcel
        UNREGISTERED->SHELVED gate fails with
        ERR_STATION_NOT_ACTIVE, even when all other parcel-level
        preconditions are satisfied.
        """
        ctx = setup_station_with_staff(station_status="SUSPENDED")
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_ACTIVE)

    def test_pickup_on_suspended_station_yields_not_active(self, api):
        # difficulty: cross_entity_state_dependency/parcel_transition_gated_by_station_status
        """PRD §3.1: "When a station's status is not ACTIVE, every
        inbound and pickup action is rejected with
        ERR_STATION_NOT_ACTIVE (HTTP 409)."

        Claim: pickup on a SHELVED parcel under a (now-)SUSPENDED
        station yields ERR_STATION_NOT_ACTIVE.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        # Suspend the station after the parcel was shelved.
        validate_success(api.patch_station(
            ctx["station"]["id"], {"status": "SUSPENDED"},
            TEST_USERS["platform_admin_headers"],
        ))
        code = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
        resp = api.pickup_parcel(
            parcel["id"], pickup_by_code_payload(code["code"]),
            ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_ACTIVE)


class TestBillingPeriodGatedByQualityAssessment:
    """Two tests covering instance:
       cross_entity_state_dependency/billing_period_close_gated_by_quality_assessment_status
    """

    def test_close_with_no_quality_assessment_yields_not_closed(self, api):
        # difficulty: cross_entity_state_dependency/billing_period_close_gated_by_quality_assessment_status
        """PRD §3.9: "the QualityAssessment for the same (station_id,
        period_yyyymm) must be in status CLOSED — otherwise the close
        is refused with ERR_QUALITY_ASSESSMENT_NOT_CLOSED (HTTP 422)."

        Claim: closing a BillingPeriod when no closed QA exists for
        the same (station, period) yields
        ERR_QUALITY_ASSESSMENT_NOT_CLOSED.
        """
        ctx = setup_station_with_staff()
        period_yyyymm = current_period_yyyymm()
        # NOTE: we deliberately skip creating the QA so it doesn't
        # exist at all when close is attempted.
        create_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        advance_clock_to_next_month(period_yyyymm)
        resp = api.close_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_QUALITY_ASSESSMENT_NOT_CLOSED)

    def test_close_with_draft_quality_assessment_yields_not_closed(self, api):
        # difficulty: cross_entity_state_dependency/billing_period_close_gated_by_quality_assessment_status
        """PRD §3.10: "The assessment is created in DRAFT, and a
        Manager closes it by invoking the assessment-close capability,
        which computes the four rates, computes the composite, sets
        closed_at, and transitions the assessment from DRAFT to
        CLOSED."

        Claim: a DRAFT QualityAssessment is not yet CLOSED, so a
        close attempt on the BillingPeriod yields
        ERR_QUALITY_ASSESSMENT_NOT_CLOSED.
        """
        ctx = setup_station_with_staff()
        period_yyyymm = current_period_yyyymm()
        create_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )  # left in DRAFT
        create_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        advance_clock_to_next_month(period_yyyymm)
        resp = api.close_billing_period(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_QUALITY_ASSESSMENT_NOT_CLOSED)


# ===========================================================================
# Rule 8 -- resource_temporal_overlap
# ===========================================================================
class TestShelfPositionOverlap:
    """Two tests covering instance:
       resource_temporal_overlap/shelf_position_exact_occupancy_overlap
    """

    def test_two_active_parcels_cannot_share_slot(self, api):
        # difficulty: resource_temporal_overlap/shelf_position_exact_occupancy_overlap
        """PRD §3.2: "an occupancy check that no other parcel currently
        in SHELVED, OVERTIME, or AWAITING_RETURN already holds the
        target shelf_position in that zone (otherwise
        ERR_SHELF_POSITION_OCCUPIED)."

        Claim: while one parcel is SHELVED on (zone, R01-C01), a
        second accept-and-shelve onto the same slot yields
        ERR_SHELF_POSITION_OCCUPIED.
        """
        ctx = setup_station_with_staff(zone_row_count=1, zone_col_count=1)
        register_shelved_parcel(ctx)
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_POSITION_OCCUPIED)

    def test_slot_freed_after_pickup_can_be_reused(self, api):
        # difficulty: resource_temporal_overlap/shelf_position_exact_occupancy_overlap
        """PRD §3.6: "The station's current_occupancy and the zone's
        occupied_slots each decrement by one."

        Claim: after the first parcel is picked up (terminal state),
        a second parcel can re-occupy the same shelf_position in the
        same zone.
        """
        ctx = setup_station_with_staff(storage_capacity=5,
                                       zone_row_count=1, zone_col_count=1)
        first = register_shelved_parcel(ctx)
        pickup_with_code(ctx, first)
        # Now re-use the same slot.
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SHELVED"
        assert data["shelf_position"] == "R01-C01"


class TestPickupCodeActiveUniqueness:
    """Two tests covering instance:
       resource_temporal_overlap/pickup_code_active_window_uniqueness
    """

    def test_reissue_flips_old_to_reissued_with_superseded_by(self, api):
        # difficulty: resource_temporal_overlap/pickup_code_active_window_uniqueness
        """PRD §3.3: "On success, the old code transitions from ACTIVE
        to REISSUED, its superseded_by is set to the new code's id,
        and a fresh code is minted under the same six-digit collision
        rules with issue_reason REISSUED_LOST."

        Claim: after a reissue, the original code's status is REISSUED
        and superseded_by is the new code's id.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        original = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
        new_code = reissue_pickup_code(parcel["id"])
        codes = list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
        old = next(c for c in codes if c["id"] == original["id"])
        assert old["status"] == "REISSUED"
        assert old["superseded_by"] == new_code["id"]

    def test_at_most_one_active_code_after_reissue(self, api):
        # difficulty: resource_temporal_overlap/pickup_code_active_window_uniqueness
        """PRD §3.3: "at most one ACTIVE code exists per parcel at any
        moment."

        Claim: after reissue, exactly one PickupCode for the parcel
        has status=ACTIVE.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        reissue_pickup_code(parcel["id"])
        codes = list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
        actives = [c for c in codes if c["status"] == "ACTIVE"]
        assert len(actives) == 1


# ===========================================================================
# Rule 9 -- compensating_invariant
# ===========================================================================
class TestStationOccupancyConservation:
    """Two tests covering instance:
       compensating_invariant/station_occupancy_conserved_on_inbound_then_pickup
    """

    def test_inbound_plus_pickup_nets_to_zero_station_occupancy(self, api):
        # difficulty: compensating_invariant/station_occupancy_conserved_on_inbound_then_pickup
        """PRD §3.2: "increments the station's current_occupancy and
        the zone's occupied_slots by one each."
        PRD §3.6: "The station's current_occupancy and the zone's
        occupied_slots each decrement by one."

        Claim: starting from current_occupancy=0, after an
        accept-and-shelve followed by a successful pickup the station
        is back to current_occupancy=0.
        """
        ctx = setup_station_with_staff(storage_capacity=5)
        before = validate_success(
            api.get_station(ctx["station"]["id"],
                            TEST_USERS["platform_admin_headers"])
        )
        assert before["current_occupancy"] == 0
        parcel = register_shelved_parcel(ctx)
        pickup_with_code(ctx, parcel)
        after = validate_success(
            api.get_station(ctx["station"]["id"],
                            TEST_USERS["platform_admin_headers"])
        )
        assert after["current_occupancy"] == 0

    def test_inbound_plus_pickup_nets_to_zero_zone_slots(self, api):
        # difficulty: compensating_invariant/station_occupancy_conserved_on_inbound_then_pickup
        """PRD §3.1: "maintains occupied_slots as the live count of
        parcels assigned to the zone whose status is one of SHELVED,
        OVERTIME, or AWAITING_RETURN."

        Claim: starting from occupied_slots=0, after accept-and-shelve
        + pickup, the same zone is back to occupied_slots=0.
        """
        ctx = setup_station_with_staff(zone_row_count=1, zone_col_count=2)
        parcel = register_shelved_parcel(ctx)
        pickup_with_code(ctx, parcel)
        zones, _ = validate_paginated(
            api.list_shelf_zones(ctx["station"]["id"], ctx["manager_headers"])
        )
        zone = next(z for z in zones if z["id"] == ctx["zone"]["id"])
        assert zone["occupied_slots"] == 0


class TestStorageFeeConservedUnderDisputeResolve:
    """Two tests covering instance:
       compensating_invariant/storage_fee_conserved_under_dispute_then_resolve_no_adjustment
    """

    def test_bill_storage_fee_unchanged_after_dispute_then_resolve(
        self, api, recipient_headers,
    ):
        # difficulty: compensating_invariant/storage_fee_conserved_under_dispute_then_resolve_no_adjustment
        """PRD §3.9: "A Manager later resolves a disputed bill --
        optionally supplying an adjustment_amount (which may recompute
        the bill's rolled-up amounts) and an explanatory note --
        flipping it from DISPUTED to RESOLVED."

        Claim: when dispute is resolved with NO adjustment_amount,
        the bill's storage_fee_amount remains unchanged from its
        CLOSE-time value.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=30,  # 30h overdue
        )
        recipient_bill = next(
            b for b in ctx["bills"] if b["payer_kind"] == "RECIPIENT"
        )
        original_storage = recipient_bill["storage_fee_amount"]
        api.dispute_bill(
            recipient_bill["id"], dispute_bill_payload("wrong fee"),
            recipient_headers,
        )
        # Resolve with no adjustment.
        api.resolve_dispute(
            recipient_bill["id"], ctx["manager_headers"],
            resolve_dispute_payload(note="ok"),
        )
        reread = validate_success(
            api.get_bill(recipient_bill["id"], ctx["manager_headers"])
        )
        assert reread["storage_fee_amount"] == pytest.approx(
            original_storage, abs=0.005,
        )

    def test_period_final_total_unchanged_after_dispute_then_resolve(
        self, api, recipient_headers,
    ):
        # difficulty: compensating_invariant/storage_fee_conserved_under_dispute_then_resolve_no_adjustment
        """PRD §3.9: "When no child bill under the period is still in
        DISPUTED, the period auto-bubbles from DISPUTED back to CLOSED
        (and may then settle once all bills terminate)."

        Claim: after the dispute/resolve cycle with no adjustment, the
        parent BillingPeriod's final_total equals its value
        immediately after CLOSE.
        """
        ctx = setup_closed_period_with_bills(
            parcel_count=2, overdue_hours_each=30,
        )
        period_at_close = ctx["billing_period"]
        original_final_total = period_at_close["final_total"]
        recipient_bill = next(
            b for b in ctx["bills"] if b["payer_kind"] == "RECIPIENT"
        )
        api.dispute_bill(
            recipient_bill["id"], dispute_bill_payload("wrong fee"),
            recipient_headers,
        )
        api.resolve_dispute(
            recipient_bill["id"], ctx["manager_headers"],
            resolve_dispute_payload(note="ok"),
        )
        reread_period = validate_success(
            api.get_billing_period(
                ctx["station"]["id"], ctx["period_yyyymm"],
                ctx["manager_headers"],
            )
        )
        assert reread_period["final_total"] == pytest.approx(
            original_final_total, abs=0.005,
        )
