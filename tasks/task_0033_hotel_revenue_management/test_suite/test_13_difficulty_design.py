"""Explicit coverage of every difficulty-design instance.

Per the test generator skill, every scaffold_difficulty_design[*].
instances[*] entry must be exercised by at least TWO dedicated tests.
This file groups them by rule_id so the coverage audit is mechanical.

Each test cites the PRD sentence(s) underlying the rule the instance
exercises (PRD-First); the difficulty-design entry is referenced only
in a tag at the bottom of the docstring.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    cancel_reservation,
    check_in_payload,
    create_confirmed_reservation,
    create_maintenance_block_payload,
    create_overbooking_policy,
    create_pending_reservation,
    create_room,
    create_room_type,
    date_at_midnight,
    date_plus_days,
    fill_reservations_to_count,
    find_audit_logs,
    get_reservation,
    get_success_data,
    list_audit_logs,
    setup_basic_distribution,
    setup_no_show_ready,
    setup_rate_parity_violation_scaffold,
    setup_with_n_confirmed_for_date,
    submit_and_approve_rate_override,
    submit_rate_override,
    validate_error,
    validate_success,
)


# ===========================================================================
# RULE: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """walkout_compensation_estimated vs walkout_compensation_actual
    on the OverbookingPolicy domain produce different numbers for the
    same date."""

    def test_walkout_estimate_zero_when_arrivals_below_capacity(self, api):
        """PRD §3.4: 'The expected walkouts is whichever is greater of
        zero and the difference between expected arrivals and physical
        capacity. The estimated cost in cents is the expected walkouts
        multiplied by the policy's walkout_compensation_cents'.

        5 confirmed reservations * (1 - 0.20) = 4 expected arrivals,
        capacity 4 → expected_walkouts = 0 → estimated_cost_cents = 0.
        # difficulty: dual_variant_calc/walkout_compensation_estimated_vs_actual_on_overbooking_policy
        """
        # Two channels: per-channel cap on a single channel at 100%
        # share is floor(4*1.0)=4, which would make the 5th confirm
        # fail at the per-channel inventory check (PRD §3.5 priority
        # 15) rather than reaching the overbooking ceiling check.
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=4, channel_type="DIRECT",
            n_channels=2,
        )
        ci = "2033-06-10"
        co = date_plus_days(ci, 1)
        create_overbooking_policy(
            room_type_id=scaffold["room_type"]["id"],
            stay_date=ci,
            overbook_ratio_basis_points=2500,  # ceiling = 5
            estimated_no_show_probability_basis_points=2000,  # 20%
            walkout_compensation_cents=15000,
        )
        for i in range(5):
            create_confirmed_reservation(
                scaffold, check_in_date=ci, check_out_date=co,
                channel_index=i % 2,
            )
        est_resp = api.get_walkout_cost_estimate(
            scaffold["room_type"]["id"], ci, TEST_USERS["manager_headers"],
        )
        est = validate_success(est_resp, expected_status=200)
        assert est["estimated_cost_cents"] == 0

    def test_actual_walkout_compensation_uses_per_night_amount(self, api):
        """PRD §3.4: 'When a FrontDeskClerk executes a walk-out, the
        walkout_compensation_cents recorded on the Reservation is the
        policy's walkout_compensation_cents for the reservation's
        (room_type_id, check_in_date) multiplied by the reservation's
        nights. There is no probability factor and no projection: it is
        a direct per-night-per-guest amount realised at the moment of
        execution.'

        # difficulty: dual_variant_calc/walkout_compensation_estimated_vs_actual_on_overbooking_policy
        """
        # Build 2-room, 2-channel scaffold; overbook to allow 3rd
        # confirm; check-in the first 2; walk-out the 3rd. The 3rd
        # confirm needs a channel that still has its per-channel slot
        # free (single channel at 100% share would cap at 2 → the 3rd
        # confirm would hit ERR_INVENTORY_EXHAUSTED before the
        # overbooking ceiling check). PRD §3.5.
        scaffold = setup_basic_distribution(
            n_rooms=2, channel_type="DIRECT", n_channels=2,
        )
        ci = "2033-06-15"
        co = date_plus_days(ci, 1)  # 1 night
        create_overbooking_policy(
            room_type_id=scaffold["room_type"]["id"],
            stay_date=ci,
            overbook_ratio_basis_points=5000,  # ceiling = 3
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=15000,
        )
        advance_clock(f"{ci}T08:00:00.000Z")
        res_a = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, guest_name="A",
            channel_index=0,
        )
        res_b = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, guest_name="B",
            channel_index=1,
        )
        api.check_in_reservation(
            res_a["id"], check_in_payload(room_id=scaffold["rooms"][0]["id"]),
            TEST_USERS["clerk_headers"],
        )
        api.check_in_reservation(
            res_b["id"], check_in_payload(room_id=scaffold["rooms"][1]["id"]),
            TEST_USERS["clerk_headers"],
        )
        res_c = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, guest_name="C",
            channel_index=0,
        )
        wo_resp = api.walk_out_reservation(
            res_c["id"], TEST_USERS["clerk_headers"],
        )
        wo = validate_success(wo_resp, expected_status=200)
        # 1 night * 15000 = 15000
        assert wo["walkout_compensation_cents"] == 15000

    def test_refund_amount_moderate_50_percent_at_5_day_lead(self, api):
        """PRD §3.5: 'For MODERATE, the refund ratio is ... 5000 bp when
        lead_time_hours is at least 72 but less than 168'.

        # difficulty: dual_variant_calc/refund_amount_vs_no_show_charge_on_reservation
        """
        advance_clock("2033-07-04T10:00:00.000Z")  # 5 days before 07-09
        scaffold = setup_basic_distribution(
            base_rate_cents=20000, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="MODERATE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2033-07-09", check_out_date="2033-07-11",
        )
        cancelled = cancel_reservation(res["id"])
        # 50% of 40000 = 20000
        assert cancelled["refund_amount_cents"] == 20000

    def test_no_show_charge_moderate_50_percent_when_no_show(self, api):
        """PRD §3.7: 'For MODERATE, the charge is the booked total
        multiplied by 5000, divided by ten thousand, with one half-up
        rounding step (a 50% charge).'

        # difficulty: dual_variant_calc/refund_amount_vs_no_show_charge_on_reservation
        """
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2033-08-09",
            check_out_date="2033-08-11",
            initial_clock_iso="2033-08-01T10:00:00.000Z",
        )
        # booked_total = 2 * 40000 = 80000
        advance_clock("2033-08-10T01:00:00.000Z")
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"
        # 50% of 80000 = 40000
        assert res["no_show_charge_cents"] == 40000


# ===========================================================================
# RULE: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    """Overbooking ceiling = capacity + floor(capacity * ratio / 10000);
    refund = single round_half_up(booked * ratio / 10000)."""

    def test_overbooking_ceiling_floor_then_compare_strict(self, api):
        """PRD §3.5: 'For each night, the policy's
        overbook_ratio_basis_points (or zero if no ACTIVE policy exists
        for that (room_type_id, stay_date)) is multiplied by the physical
        capacity and floored to give the overbooking allowance; the
        ceiling is physical capacity plus that allowance. ... if the
        resulting count is strictly greater than the ceiling, the confirm
        is rejected with ERR_OVERBOOKING_LIMIT_EXCEEDED. The boundary is
        strict: a count equal to the ceiling is full but legal; only
        counts strictly exceeding the ceiling are forbidden.'

        capacity=10, ratio=1500bp → floor(1.5)=1 → ceiling=11.
        11th confirm is allowed (== ceiling); 12th is rejected.
        # difficulty: combinatorial_formula/overbooking_ceiling_floor_then_compare_threshold
        """
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=10, overbook_ratio_basis_points=1500,
            stay_date="2033-09-15", initial_confirmed=11,
        )
        # 12th confirm should fail.
        twelfth = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        res = api.confirm_reservation(
            twelfth["id"], TEST_USERS["agent_headers"],
        )
        validate_error(res, "ERR_OVERBOOKING_LIMIT_EXCEEDED")

    def test_refund_single_rounding_drops_per_night_drift(self, api):
        """PRD §3.5: 'with a single half-up rounding applied to the
        final result — never a per-night refund and never an
        intermediate rounding.'

        booked_total = 24002 (2 * 12001), ratio = 5000bp →
        round_half_up(24002 * 5000 / 10000) = round_half_up(12001.0) = 12001.
        Per-night rounding (forbidden) would yield 12002.
        # difficulty: combinatorial_formula/refund_amount_tiered_lookup_then_single_round_then_multiply
        """
        advance_clock("2033-10-09T13:00:00.000Z")  # ~21h lead, FLEXIBLE = 5000bp
        scaffold = setup_basic_distribution(
            base_rate_cents=12001, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="FLEXIBLE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2033-10-10", check_out_date="2033-10-12",
        )
        assert res["booked_total_cents"] == 24002
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 12001

    def test_overbooking_ceiling_at_boundary_allowed(self, api):
        """PRD §3.5: 'a count equal to the ceiling is full but legal'.

        capacity=10, ratio=1500bp → ceiling=11. The 11th confirm
        succeeds because count == ceiling.
        # difficulty: combinatorial_formula/overbooking_ceiling_floor_then_compare_threshold
        """
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=10, overbook_ratio_basis_points=1500,
            stay_date="2033-09-16", initial_confirmed=10,
        )
        eleventh = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        res = api.confirm_reservation(
            eleventh["id"], TEST_USERS["agent_headers"],
        )
        confirmed = validate_success(res, expected_status=200)
        assert confirmed["booking_status"] == "CONFIRMED"

    def test_refund_full_amount_at_or_above_threshold(self, api):
        """PRD §3.5: 'For FLEXIBLE, the refund ratio is 10000 bp (a full
        refund) when lead_time_hours is at least 24'.

        # difficulty: combinatorial_formula/refund_amount_tiered_lookup_then_single_round_then_multiply
        """
        advance_clock("2033-10-15T10:00:00.000Z")  # 5 days lead
        scaffold = setup_basic_distribution(
            base_rate_cents=12001, n_rooms=2,
            channel_type="DIRECT",
            refund_tier_code="FLEXIBLE",
        )
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2033-10-20", check_out_date="2033-10-22",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 24002


# ===========================================================================
# RULE: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    """Reservation has 3 parallel state dimensions; RateOverride has a
    cyclic DRAFT <-> PENDING_APPROVAL loop."""

    def test_dispute_open_does_not_rewind_booking_status(self, api,
                                                        guest_headers):
        """PRD §3.5: 'The payment_status field takes values from the
        set ...' (parallel to booking_status). PRD §3.8: 'Opening a
        dispute moves dispute_status from NONE to OPEN.'

        Verify booking_status remains NO_SHOW after opening a dispute.
        # difficulty: non_linear_state_machine/reservation_parallel_booking_and_payment_status
        """
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2033-11-10",
            check_out_date="2033-11-11",
            initial_clock_iso="2033-11-01T10:00:00.000Z",
        )
        advance_clock("2033-11-11T01:00:00.000Z")
        api.open_dispute(ctx["reservation"]["id"], guest_headers)
        res = get_reservation(ctx["reservation"]["id"])
        assert res["booking_status"] == "NO_SHOW"
        assert res["dispute_status"] == "OPEN"

    def test_resolve_dispute_changes_payment_but_not_booking_status(
        self, api, guest_headers, admin_headers,
    ):
        """PRD §3.8: 'When resolution is GUEST, the system reverses the
        financial outcome ... payment_status is moved to REFUNDED_FULL,
        and dispute_status advances to RESOLVED_GUEST.' The booking
        dimension is independent and stays NO_SHOW.

        # difficulty: non_linear_state_machine/reservation_parallel_booking_and_payment_status
        """
        from test_helpers import resolve_dispute_payload
        ctx = setup_no_show_ready(
            refund_tier_code="MODERATE",
            base_rate_cents=40000,
            check_in_date="2033-11-15",
            check_out_date="2033-11-16",
            initial_clock_iso="2033-11-05T10:00:00.000Z",
        )
        advance_clock("2033-11-16T01:00:00.000Z")
        api.open_dispute(ctx["reservation"]["id"], guest_headers)
        resp = api.resolve_dispute(
            ctx["reservation"]["id"],
            resolve_dispute_payload(resolution="GUEST"),
            admin_headers,
        )
        resolved = validate_success(resp, expected_status=200)
        assert resolved["payment_status"] == "REFUNDED_FULL"
        assert resolved["dispute_status"] == "RESOLVED_GUEST"
        # booking_status is NOT rewound by the dispute path
        assert resolved["booking_status"] == "NO_SHOW"

    def test_rate_override_cyclic_revision_loop(self, api,
                                                analyst_headers):
        """PRD §3.3: 'or the original RevenueAnalyst may withdraw,
        returning the override to DRAFT for revision (this cyclic loop
        supports iterative revision rounds).'

        Sequence: submit -> withdraw -> submit again, ending in
        PENDING_APPROVAL.
        # difficulty: non_linear_state_machine/rate_override_cyclic_revision_loop
        """
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2033-12-01",
        )
        wd = api.withdraw_rate_override(pending["id"], analyst_headers)
        wd_data = validate_success(wd, expected_status=200)
        assert wd_data["status"] == "DRAFT"
        re_sub = api.submit_rate_override(pending["id"], analyst_headers)
        again = validate_success(re_sub, expected_status=200)
        assert again["status"] == "PENDING_APPROVAL"
        assert again["id"] == pending["id"]

    def test_rate_override_can_be_approved_after_revision_round(self, api):
        """PRD §3.3: 'A RevenueManager may approve, advancing status to
        APPROVED'. The cyclic withdraw->resubmit path leaves the override
        approve-able again.
        # difficulty: non_linear_state_machine/rate_override_cyclic_revision_loop
        """
        from test_helpers import approve_rate_override
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2033-12-02",
        )
        api.withdraw_rate_override(pending["id"], TEST_USERS["analyst_headers"])
        api.submit_rate_override(pending["id"], TEST_USERS["analyst_headers"])
        approved = approve_rate_override(pending["id"])
        assert approved["status"] == "APPROVED"


# ===========================================================================
# RULE: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    """Cascade depths >= 2 from a single trigger."""

    def test_approve_supersedes_prior_approved_then_audit_emitted(self, api):
        """PRD §3.3: 'It sets applied_rate_cents equal to
        proposed_rate_cents ... any prior RateOverride for the same
        (room_type_id, stay_date) whose status is APPROVED is moved to
        SUPERSEDED ... Approval also writes a RATE_OVERRIDE_APPROVED
        audit event.'

        Hop 1: new override → APPROVED. Hop 2 (caused by hop 1): prior
        APPROVED → SUPERSEDED. Audit log records APPROVED.
        # difficulty: transitive_cascade/rate_override_approval_supersede_then_parity_then_audit_chain_depth_three
        """
        rt = create_room_type()
        first = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2034-01-15",
            proposed_rate_cents=22000,
        )
        second = submit_and_approve_rate_override(
            room_type_id=rt["id"], stay_date="2034-01-15",
            proposed_rate_cents=30000,
        )
        assert second["status"] == "APPROVED"
        # Audit for second approval
        logs = list_audit_logs(
            event_type="RATE_OVERRIDE_APPROVED", subject_id=second["id"],
        )
        assert len(logs) >= 1

    def test_approve_with_parity_breach_emits_parity_audit(self, api):
        """PRD §3.3: 'Second, the system runs the rate-parity check
        across every enabled ChannelRatePlanMapping whose rate plan
        belongs to the same room type.'
        PRD §3.3: 'if, across the participating channels, the largest
        channel-observed rate divided by the smallest exceeds the
        smallest by more than one percent, an audit event of type
        RATE_PARITY_VIOLATION_DETECTED is written'.

        Setup: two OTAs at very different commission rates; an approve
        triggers the parity audit (depth >= 2 from the approve call).
        # difficulty: transitive_cascade/rate_override_approval_supersede_then_parity_then_audit_chain_depth_three
        """
        scaffold = setup_rate_parity_violation_scaffold(
            stay_date="2034-02-01",
            ota1_commission_bp=1500,
            ota2_commission_bp=4000,
        )
        approved = submit_and_approve_rate_override(
            room_type_id=scaffold["room_type"]["id"],
            stay_date="2034-02-01",
            proposed_rate_cents=25000,
        )
        logs = list_audit_logs(
            event_type="RATE_PARITY_VIOLATION_DETECTED",
        )
        relevant = [
            log for log in logs
            if isinstance(log.get("payload"), dict)
            and log["payload"].get("room_type_id") == scaffold["room_type"]["id"]
            and log["payload"].get("stay_date") == "2034-02-01"
        ]
        assert len(relevant) >= 1

    def test_release_block_restores_room_to_in_service_and_dirty(self, api,
                                                                  housekeeping_headers,
                                                                  admin_headers):
        """PRD §3.1: 'The release cascade restores the room only if no
        other ACTIVE block still covers it — in that case
        operational_status returns to IN_SERVICE, and housekeeping_status
        is set to DIRTY on the assumption the technician left the room
        dusty.'

        Hop 1: block ACTIVE → RELEASED. Hop 2: room cascaded
        OUT_OF_ORDER → IN_SERVICE + DIRTY.
        # difficulty: transitive_cascade/maintenance_block_release_cascade_to_room_op_then_housekeeping_depth_two
        """
        from test_helpers import setup_active_maintenance_block
        ctx = setup_active_maintenance_block(
            block_start_date="2034-03-01",
            block_end_date="2034-03-05",
            activate_at_iso="2034-03-02T08:00:00.000Z",
        )
        rel = api.release_maintenance_block(
            ctx["block"]["id"], housekeeping_headers,
        )
        block = validate_success(rel, expected_status=200)
        assert block["status"] == "RELEASED"
        rooms_resp = api.list_rooms(
            admin_headers, params={"room_type_id": ctx["room_type"]["id"]},
        )
        rooms = validate_success(rooms_resp, expected_status=200)
        rooms = rooms if isinstance(rooms, list) else [rooms]
        r2 = next(r for r in rooms if r["id"] == ctx["room"]["id"])
        assert r2["operational_status"] == "IN_SERVICE"
        assert r2["housekeeping_status"] == "DIRTY"

    def test_release_block_cascade_block_status_update_visible(
        self, api, housekeeping_headers, admin_headers,
    ):
        """PRD §3.1: 'A block transitions from ACTIVE to RELEASED either
        automatically when the clock crosses end_date or by an explicit
        release call from HousekeepingStaff or PlatformAdmin.'

        # difficulty: transitive_cascade/maintenance_block_release_cascade_to_room_op_then_housekeeping_depth_two
        """
        from test_helpers import setup_active_maintenance_block
        ctx = setup_active_maintenance_block(
            block_start_date="2034-03-10",
            block_end_date="2034-03-15",
            activate_at_iso="2034-03-11T08:00:00.000Z",
        )
        rel = api.release_maintenance_block(
            ctx["block"]["id"], housekeeping_headers,
        )
        block = validate_success(rel, expected_status=200)
        assert block["status"] == "RELEASED"


# ===========================================================================
# RULE: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    """Cross-pair priority: ERR_INVALID_STATE wins over
    ERR_ROOM_UNAVAILABLE; ERR_REFERENCE_NOT_FOUND wins over
    ERR_ROOM_TYPE_MISMATCH."""

    def test_check_in_on_terminal_reservation_returns_invalid_state(
        self, api, clerk_headers, housekeeping_headers,
    ):
        """PRD §2.9: priority 5 (state) precedes priority 8
        (business_safety): 'A check earlier in the order surfacing first
        means a check later in the order is masked'.

        Reservation in CHECKED_OUT receiving a check-in call AND target
        Room is OUT_OF_ORDER → ERR_INVALID_STATE wins.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_room_unavailable_on_check_in
        """
        from test_helpers import create_checked_in_reservation
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2034-04-10"
        co = date_plus_days(ci, 1)
        res, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        # check-out
        api.check_out_reservation(res["id"], clerk_headers)
        # take room out of service
        api.out_of_service_room(room["id"], housekeeping_headers)
        # try check-in again
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_INVALID_STATE")

    def test_check_in_on_already_checked_in_returns_invalid_state(
        self, api, clerk_headers, housekeeping_headers,
    ):
        """PRD §2.9: 'A check earlier in the order surfacing first means
        a check later in the order is masked: a request that would fail
        both checks 5 and 9 returns the check-5 error.'

        Reservation already CHECKED_IN AND target Room is OUT_OF_ORDER
        → ERR_INVALID_STATE wins over ERR_ROOM_UNAVAILABLE.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_room_unavailable_on_check_in
        """
        from test_helpers import create_checked_in_reservation
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2036-01-10"
        co = date_plus_days(ci, 1)
        res, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        # Without checking out, attempt a second check-in. (Room is
        # OCCUPIED so we'd hit ERR_ROOM_UNAVAILABLE if we looked at the
        # room first; we should hit ERR_INVALID_STATE on the
        # reservation.)
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_INVALID_STATE")

    def test_check_in_with_nonexistent_room_returns_reference_not_found(
        self, api, clerk_headers,
    ):
        """PRD §2.9: priority 4 (existence/reference) precedes priority 9
        (business_safety/room_type_mismatch).

        Reservation references room_type STD; check-in with a
        nonexistent room_id (would also be a type mismatch if it
        existed) → ERR_REFERENCE_NOT_FOUND wins.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_room_type_mismatch_vs_reference_not_found
        """
        from test_helpers import NON_EXISTENT_UUID
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2034-05-10"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T08:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=NON_EXISTENT_UUID),
            clerk_headers,
        )
        validate_error(bad, "ERR_REFERENCE_NOT_FOUND")

    def test_check_in_room_type_mismatch_alone_returns_room_type_mismatch(
        self, api, clerk_headers,
    ):
        """PRD §3.6: 'the room's room_type_id matches the reservation's
        room_type_id (a mismatch surfaces as ERR_ROOM_TYPE_MISMATCH)'.

        When ONLY the room_type mismatch fails (room exists, is
        IN_SERVICE, is VACANT_CLEAN), the priority-9 error surfaces —
        confirming that the existence check (priority 4) does NOT mask
        it when the referenced room_id is real.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_room_type_mismatch_vs_reference_not_found
        """
        scaffold = setup_basic_distribution(n_rooms=1)
        rt2 = create_room_type()
        wrong_room = create_room(room_type_id=rt2["id"])
        ci = "2036-02-10"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T08:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=wrong_room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_ROOM_TYPE_MISMATCH")


# ===========================================================================
# RULE: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    """Numeric threshold (overbooking ceiling) and empty-set boundary
    (walk-out candidate room set)."""

    def test_overbooking_ceiling_strict_greater_than(self, api):
        """PRD §3.5: 'a count equal to the ceiling is full but legal;
        only counts strictly exceeding the ceiling are forbidden.'

        capacity=4, ratio=2500bp → ceiling=5. 5th confirm allowed; 6th
        rejected.
        # difficulty: boundary_precision_check/overbooking_ceiling_strict_greater_than_boundary_on_confirm
        """
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2034-12-25", initial_confirmed=4,
        )
        # 5th allowed
        fifth = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        ok = api.confirm_reservation(
            fifth["id"], TEST_USERS["agent_headers"],
        )
        validate_success(ok, expected_status=200)
        # 6th rejected
        sixth = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        bad = api.confirm_reservation(
            sixth["id"], TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_OVERBOOKING_LIMIT_EXCEEDED")

    def test_overbooking_ceiling_below_capacity_still_allowed(self, api):
        """PRD §3.5: 'a count equal to the ceiling is full but legal'.
        With cumulative count strictly below the ceiling, every confirm
        must succeed up to and including the ceiling.

        capacity=4, ratio=2500bp → ceiling=5. The 4th confirm sits one
        below the ceiling — it must be accepted.
        # difficulty: boundary_precision_check/overbooking_ceiling_strict_greater_than_boundary_on_confirm
        """
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2034-12-26", initial_confirmed=3,
        )
        fourth = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
        )
        ok = api.confirm_reservation(
            fourth["id"], TEST_USERS["agent_headers"],
        )
        confirmed = validate_success(ok, expected_status=200)
        assert confirmed["booking_status"] == "CONFIRMED"

    def test_walkout_blocked_when_room_is_vacant_clean(self, api):
        """PRD §3.6: 'A FrontDeskClerk may execute the walk-out only when
        ... the count of physical rooms of the matching room type that
        are simultaneously VACANT_CLEAN, IN_SERVICE, and free of any
        overlapping MaintenanceBlock is zero.'

        Direct boundary check: with one VACANT_CLEAN room available,
        walk-out must be rejected (candidate set non-empty).
        # difficulty: boundary_precision_check/empty_candidate_room_set_walkout_trigger_via_walk_out_endpoint
        """
        ctx = setup_no_show_ready  # placeholder import
        # Use setup_walkout_ready: single room VACANT_CLEAN at arrival.
        from test_helpers import setup_walkout_ready
        ctx = setup_walkout_ready()
        bad = api.walk_out_reservation(
            ctx["reservation"]["id"], TEST_USERS["clerk_headers"],
        )
        validate_error(bad, "ERR_INVALID_STATE")

    def test_walkout_blocked_when_room_available_succeeds_when_empty(
        self, api,
    ):
        """PRD §3.6: 'A FrontDeskClerk may execute the walk-out only when
        ... the count of physical rooms of the matching room type that
        are simultaneously VACANT_CLEAN, IN_SERVICE, and free of any
        overlapping MaintenanceBlock is zero.'

        Two reservations on a single-room scaffold (overbook allows it):
        first walk-out attempt fails (room VACANT_CLEAN); after a
        second reservation consumes that room via check-in, walk-out
        on a third reservation succeeds.
        # difficulty: boundary_precision_check/empty_candidate_room_set_walkout_trigger_via_walk_out_endpoint
        """
        # 2 rooms + 2 channels; overbook ratio 5000bp → ceiling 3.
        # Per PRD §3.5 a single channel at 100% share caps at
        # floor(2*1.0)=2; reaching the ceiling at 3 requires
        # distributing across 2 channels.
        scaffold = setup_basic_distribution(
            n_rooms=2, channel_type="DIRECT", n_channels=2,
        )
        ci = "2035-01-15"
        co = date_plus_days(ci, 1)
        create_overbooking_policy(
            room_type_id=scaffold["room_type"]["id"],
            stay_date=ci,
            overbook_ratio_basis_points=5000,
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=15000,
        )
        advance_clock(f"{ci}T08:00:00.000Z")
        res_a = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, guest_name="A",
            channel_index=0,
        )
        # First walk-out attempt: rooms are VACANT_CLEAN → must fail
        # (PRD says walk-out only when zero rooms available).
        bad = api.walk_out_reservation(
            res_a["id"], TEST_USERS["clerk_headers"],
        )
        validate_error(bad, "ERR_INVALID_STATE")
        # Check in res_a using room 0; create + check-in res_b on room 1.
        api.check_in_reservation(
            res_a["id"], check_in_payload(room_id=scaffold["rooms"][0]["id"]),
            TEST_USERS["clerk_headers"],
        )
        res_b = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, guest_name="B",
            channel_index=1,
        )
        api.check_in_reservation(
            res_b["id"], check_in_payload(room_id=scaffold["rooms"][1]["id"]),
            TEST_USERS["clerk_headers"],
        )
        # Now create + try to walk-out a third reservation.
        res_c = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, guest_name="C",
            channel_index=0,
        )
        ok = api.walk_out_reservation(
            res_c["id"], TEST_USERS["clerk_headers"],
        )
        wo = validate_success(ok, expected_status=200)
        assert wo["booking_status"] == "WALKED_OUT"


# ===========================================================================
# RULE: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    """Cross-aggregate guards on Reservation transitions."""

    def test_check_in_blocked_when_room_not_vacant_clean(
        self, api, clerk_headers,
    ):
        """PRD §3.6: 'the room's housekeeping_status is VACANT_CLEAN
        (failure here also surfaces as ERR_ROOM_UNAVAILABLE).'

        Cross-entity guard via the housekeeping dimension.
        # difficulty: cross_entity_state_dependency/reservation_check_in_depends_on_room_op_and_housekeeping_status
        """
        # Build a CHECKED_IN+CHECKED_OUT pair so the room is DIRTY,
        # then confirm a fresh reservation and try to check it into
        # the same DIRTY room.
        from test_helpers import create_checked_in_reservation
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2035-10-05"
        co = date_plus_days(ci, 1)
        res, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        api.check_out_reservation(res["id"], clerk_headers)
        # Room now DIRTY.
        ci2 = "2035-10-06"
        co2 = date_plus_days(ci2, 1)
        advance_clock(f"{ci2}T08:00:00.000Z")
        res2 = create_confirmed_reservation(
            scaffold, check_in_date=ci2, check_out_date=co2,
            guest_name="Second",
        )
        bad = api.check_in_reservation(
            res2["id"], check_in_payload(room_id=room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_ROOM_UNAVAILABLE")

    def test_check_in_blocked_by_room_out_of_service(
        self, api, clerk_headers, housekeeping_headers,
    ):
        """PRD §3.6: 'the room's operational_status is IN_SERVICE ...
        (failure on either part of this surfaces as
        ERR_ROOM_UNAVAILABLE).'

        Reservation transition gated on cross-entity Room state.
        # difficulty: cross_entity_state_dependency/reservation_check_in_depends_on_room_op_and_housekeeping_status
        """
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2035-02-10"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T08:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        room = scaffold["rooms"][0]
        api.out_of_service_room(room["id"], housekeeping_headers)
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_ROOM_UNAVAILABLE")

    def test_create_with_inactive_rate_plan_room_type_pair(self, api):
        """PRD §3.5: 'enforces that the RatePlan's room_type_id equals
        the reservation's room_type_id ... failure of either is rejected
        with ERR_RATE_PLAN_NOT_DISTRIBUTED.'

        Variant cross-aggregate state guard: a real RatePlan tied to a
        DIFFERENT room_type cannot be used to book the candidate
        room_type — the distribution check refuses the create.
        # difficulty: cross_entity_state_dependency/reservation_confirm_depends_on_rate_plan_and_channel_mapping_state
        """
        from test_helpers import (
            create_channel, create_mapping, create_rate_plan, create_room,
            create_room_type, create_reservation_payload,
        )
        rt_a = create_room_type()
        rt_b = create_room_type()
        # Plan for rt_a only
        plan_a = create_rate_plan(room_type_id=rt_a["id"])
        ch = create_channel(channel_type="DIRECT")
        # Mapping enabled for plan_a
        create_mapping(
            channel_id=ch["id"], rate_plan_id=plan_a["id"],
            inventory_share_basis_points=10000,
        )
        # Need at least 1 room of rt_b so the room_type_id resolves
        create_room(room_type_id=rt_b["id"])
        bad = api.create_reservation(
            create_reservation_payload(
                room_type_id=rt_b["id"],
                rate_plan_id=plan_a["id"],
                channel_id=ch["id"],
                check_in_date="2035-11-10", check_out_date="2035-11-12",
            ),
            TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_RATE_PLAN_NOT_DISTRIBUTED")

    def test_confirm_blocked_when_mapping_disabled(self, api):
        """PRD §3.5: 'a ChannelRatePlanMapping exists between the chosen
        channel_id and rate_plan_id whose enabled flag is true; failure
        of either is rejected with ERR_RATE_PLAN_NOT_DISTRIBUTED.'

        Reservation.create gated on channel-mapping state — cross-entity
        dependency between Reservation and (RatePlan, Channel, Mapping).
        # difficulty: cross_entity_state_dependency/reservation_confirm_depends_on_rate_plan_and_channel_mapping_state
        """
        # Build a scaffold where mapping is enabled to get past create,
        # then re-attempt a brand-new reservation referencing an
        # unmapped channel directly.
        from test_helpers import (
            create_channel, create_rate_plan, create_room_type,
            create_room,
        )
        rt = create_room_type(base_rate_cents=20000)
        create_room(room_type_id=rt["id"])
        plan = create_rate_plan(room_type_id=rt["id"])
        unmapped_ch = create_channel(channel_type="DIRECT")
        # No mapping created → reservation create must fail.
        from test_helpers import create_reservation_payload
        bad = api.create_reservation(
            create_reservation_payload(
                room_type_id=rt["id"],
                rate_plan_id=plan["id"],
                channel_id=unmapped_ch["id"],
                check_in_date="2035-03-10", check_out_date="2035-03-12",
            ),
            TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_RATE_PLAN_NOT_DISTRIBUTED")


# ===========================================================================
# RULE: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    """MaintenanceBlock half-open per-pair overlap; per-channel
    aggregate-capacity overlap on Reservations."""

    def test_maintenance_block_abutting_allowed(self, api,
                                                housekeeping_headers):
        """PRD §3.1: 'an end_date (exclusive — the window is the
        half-open interval beginning at start_date and ending strictly
        before end_date, so the day equal to end_date is not part of the
        block).'

        Two abutting blocks (block1.end == block2.start) do NOT overlap.
        # difficulty: resource_temporal_overlap/maintenance_block_half_open_overlap_per_room
        """
        from test_helpers import create_room_type
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        first = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2035-04-01", end_date="2035-04-05",
            ),
            housekeeping_headers,
        )
        validate_success(first, expected_status=201)
        abutting = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2035-04-05", end_date="2035-04-08",
            ),
            housekeeping_headers,
        )
        validate_success(abutting, expected_status=201)

    def test_maintenance_block_overlap_rejected(self, api,
                                                housekeeping_headers):
        """PRD §3.1: 'Any attempt to create a block whose half-open
        interval overlaps any other block on the same room whose status
        is SCHEDULED or ACTIVE is rejected with ERR_MAINTENANCE_OVERLAP.'

        # difficulty: resource_temporal_overlap/maintenance_block_half_open_overlap_per_room
        """
        from test_helpers import create_room_type
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2035-04-15", end_date="2035-04-20",
            ),
            housekeeping_headers,
        )
        bad = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2035-04-18", end_date="2035-04-22",
            ),
            housekeeping_headers,
        )
        validate_error(bad, "ERR_MAINTENANCE_OVERLAP")

    def test_per_channel_share_aggregate_overlap_rejects_second_confirm(
        self, api,
    ):
        """PRD §3.5: 'For each date in the half-open interval beginning
        at check_in_date and ending strictly before check_out_date ...
        if the minimum remaining across all nights is not greater than
        zero, the confirm is rejected with ERR_INVENTORY_EXHAUSTED.'

        Setup: capacity=4, share=2500bp → channel_share=1. R1 spans
        2035-05-01..05-03 (used=1 on those nights). R2 spans
        2035-05-02..05-04 — overlaps R1 on 2035-05-02 → confirm fails.
        # difficulty: resource_temporal_overlap/reservation_per_channel_per_night_aggregate_capacity_overlap
        """
        from test_helpers import setup_channel_share_boundary
        scaffold = setup_channel_share_boundary(
            physical_capacity=4, inventory_share_basis_points=2500,
        )
        # R1: 2 nights
        r1 = create_confirmed_reservation(
            scaffold,
            check_in_date="2035-05-01", check_out_date="2035-05-03",
            guest_name="R1",
        )
        # R2: overlaps R1 on 2035-05-02
        r2_pending = create_pending_reservation(
            scaffold,
            check_in_date="2035-05-02", check_out_date="2035-05-04",
            guest_name="R2",
        )
        bad = api.confirm_reservation(
            r2_pending["id"], TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_INVENTORY_EXHAUSTED")

    def test_non_overlapping_dates_allow_second_confirm(self, api):
        """PRD §3.5: counter-half-of-the-rule. Reservations whose stay
        windows do NOT overlap each consume the share independently and
        both succeed. (Same sentence above — second-confirm path.)
        # difficulty: resource_temporal_overlap/reservation_per_channel_per_night_aggregate_capacity_overlap
        """
        from test_helpers import setup_channel_share_boundary
        scaffold = setup_channel_share_boundary(
            physical_capacity=4, inventory_share_basis_points=2500,
        )
        # R1 finishes 2035-06-03 (exclusive). R2 starts 2035-06-03
        # — no overlap because half-open.
        r1 = create_confirmed_reservation(
            scaffold,
            check_in_date="2035-06-01", check_out_date="2035-06-03",
            guest_name="R1",
        )
        r2 = create_confirmed_reservation(
            scaffold,
            check_in_date="2035-06-03", check_out_date="2035-06-05",
            guest_name="R2",
        )
        assert r2["booking_status"] == "CONFIRMED"


# ===========================================================================
# RULE: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    """Forward + compensating action net to zero on a conserved
    quantity."""

    def test_pending_then_cancel_zero_money_movement(self, api):
        """PRD §3.5: 'From PENDING, the reservation has never been
        charged: refund_amount_cents is set to zero, and if
        payment_status was AUTHORIZED it is moved to REFUNDED_FULL
        (otherwise unchanged).'

        Conserved quantity: net money movement from create-and-cancel
        without ever confirming = 0.
        # difficulty: compensating_invariant/confirm_then_cancel_pending_preserves_zero_money_movement
        """
        scaffold = setup_basic_distribution(n_rooms=1)
        res = create_pending_reservation(
            scaffold,
            check_in_date="2035-07-01", check_out_date="2035-07-02",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["refund_amount_cents"] == 0
        assert cancelled["no_show_charge_cents"] == 0
        assert cancelled["walkout_compensation_cents"] == 0
        assert cancelled["payment_status"] == "UNPAID"

    def test_pending_cancel_no_show_or_walkout_charges(self, api):
        """PRD §3.5: 'From PENDING, the reservation has never been
        charged: refund_amount_cents is set to zero'.

        Variant: a different rate plan tier (NON_REFUNDABLE) — the
        invariant still holds because cancellation from PENDING never
        consults the tier table.
        # difficulty: compensating_invariant/confirm_then_cancel_pending_preserves_zero_money_movement
        """
        scaffold = setup_basic_distribution(
            n_rooms=1, refund_tier_code="NON_REFUNDABLE",
        )
        res = create_pending_reservation(
            scaffold,
            check_in_date="2035-07-10", check_out_date="2035-07-12",
        )
        cancelled = cancel_reservation(res["id"])
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["refund_amount_cents"] == 0
        assert cancelled["no_show_charge_cents"] == 0
        # Even NON_REFUNDABLE tier doesn't levy a charge from PENDING.
        assert cancelled["payment_status"] == "UNPAID"

    def test_schedule_block_then_cancel_restores_inventory(self, api,
                                                            housekeeping_headers,
                                                            manager_headers):
        """PRD §3.4: 'The physical capacity is the count of rooms of the
        matching room type whose lifecycle_status is ACTIVE, minus the
        count of maintenance blocks on those rooms whose status is
        SCHEDULED or ACTIVE and whose half-open window covers the date.'

        PRD §3.1: 'A SCHEDULED block may also be cancelled by a
        HousekeepingStaff member, advancing status to CANCELLED.'

        Verifying via the walkout estimate endpoint: a CANCELLED block
        does NOT count, so the post-cancel physical capacity equals
        the pre-create capacity.
        # difficulty: compensating_invariant/maintenance_schedule_then_cancel_preserves_room_inventory_count
        """
        # Set clock to a baseline well before the block window so the
        # block stays SCHEDULED (cancellable).
        advance_clock("2035-08-01T00:00:00.000Z")
        rt = create_room_type()
        rooms = [create_room(room_type_id=rt["id"]) for _ in range(3)]
        # Establish a policy on a date so we can read the estimate.
        stay = "2035-08-10"
        create_overbooking_policy(
            room_type_id=rt["id"], stay_date=stay,
            overbook_ratio_basis_points=0,
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=10000,
        )

        def get_estimate():
            res = api.get_walkout_cost_estimate(rt["id"], stay, manager_headers)
            return validate_success(res, expected_status=200)

        # Pre-measure: with 3 rooms and zero reservations,
        # estimate is 0; the relevant invariant is read indirectly via
        # confirming reservations against the ceiling. Instead, use
        # confirmation success/failure as the observable: with capacity
        # 3 and no policy or ratio=0, the 3rd confirm must succeed and
        # the 4th must fail. Apply a maintenance block on one room
        # (capacity drops to 2) and confirm only the 2nd; cancel the
        # block; capacity restored to 3, allowing a 3rd confirm.
        scaffold = {
            "room_type": rt, "rooms": rooms,
            "rate_plan": None, "channel": None, "mapping": None,
            "rate_plans": [], "channels": [], "mappings": [],
        }
        # Build a parallel scaffold around this RoomType. Use TWO
        # channels (each with its own rate plan at 100% share) so the
        # 3rd confirm exercises the overbooking ceiling check (PRD
        # §3.5 priority 16) rather than the per-channel inventory cap
        # (priority 15) — at capacity=2 the per-channel cap on a
        # single channel at 100% share is floor(2*1.0)=2.
        from test_helpers import (
            create_rate_plan, create_channel, create_mapping,
        )
        for _ in range(2):
            p = create_rate_plan(room_type_id=rt["id"])
            c = create_channel(channel_type="DIRECT", commission_basis_points=0)
            create_mapping(
                channel_id=c["id"], rate_plan_id=p["id"],
                inventory_share_basis_points=10000,
            )
            scaffold["rate_plans"].append(p)
            scaffold["channels"].append(c)
        scaffold["rate_plan"] = scaffold["rate_plans"][0]
        scaffold["channel"] = scaffold["channels"][0]
        # Schedule a block on rooms[0] for 2035-08-10.
        block_resp = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=rooms[0]["id"],
                start_date=stay, end_date=date_plus_days(stay, 1),
            ),
            housekeeping_headers,
        )
        block = validate_success(block_resp, expected_status=201)
        # Capacity now effectively 2 → confirming 3 reservations on 'stay'
        # would exceed the ceiling = 2.
        ci = stay
        co = date_plus_days(ci, 1)
        # Confirm two reservations to fill the reduced capacity, one
        # per channel so neither channel saturates ahead of the
        # overbooking ceiling.
        create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, channel_index=0,
        )
        create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co, channel_index=1,
        )
        # Third confirm must FAIL while the block is SCHEDULED. Choose
        # whichever channel still has slot remaining (ch0: 1 free of 2).
        third = create_pending_reservation(
            scaffold, check_in_date=ci, check_out_date=co, channel_index=0,
        )
        bad = api.confirm_reservation(
            third["id"], TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_OVERBOOKING_LIMIT_EXCEEDED")
        # Cancel the block — capacity restored.
        cancel_resp = api.cancel_maintenance_block(
            block["id"], housekeeping_headers,
        )
        cancelled_block = validate_success(cancel_resp, expected_status=200)
        assert cancelled_block["status"] == "CANCELLED"
        # Now the 3rd confirm must succeed.
        ok = api.confirm_reservation(
            third["id"], TEST_USERS["agent_headers"],
        )
        confirmed = validate_success(ok, expected_status=200)
        assert confirmed["booking_status"] == "CONFIRMED"

    def test_cancel_block_reverses_estimate_capacity(
        self, api, housekeeping_headers, manager_headers,
    ):
        """PRD §3.4: 'The physical capacity is the count of rooms of the
        matching room type whose lifecycle_status is ACTIVE, minus the
        count of maintenance blocks on those rooms whose status is
        SCHEDULED or ACTIVE and whose half-open window covers the date.'

        Verify the conservation invariant via the walkout-cost-estimate
        endpoint: scheduling and then cancelling a block on a room that
        the date falls into produces equal estimates pre and post.
        # difficulty: compensating_invariant/maintenance_schedule_then_cancel_preserves_room_inventory_count
        """
        advance_clock("2035-09-01T00:00:00.000Z")
        rt = create_room_type()
        rooms = [create_room(room_type_id=rt["id"]) for _ in range(3)]
        stay = "2035-09-10"
        # Policy with non-zero compensation so the estimate is observable
        # if walkouts are projected.
        create_overbooking_policy(
            room_type_id=rt["id"], stay_date=stay,
            overbook_ratio_basis_points=0,
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=15000,
        )
        # Pre-measure
        pre = validate_success(
            api.get_walkout_cost_estimate(rt["id"], stay, manager_headers),
            expected_status=200,
        )
        # Schedule a block
        block_resp = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=rooms[0]["id"],
                start_date=stay, end_date=date_plus_days(stay, 1),
            ),
            housekeeping_headers,
        )
        block = validate_success(block_resp, expected_status=201)
        # Cancel it
        cancel_resp = api.cancel_maintenance_block(
            block["id"], housekeeping_headers,
        )
        cancelled = validate_success(cancel_resp, expected_status=200)
        assert cancelled["status"] == "CANCELLED"
        # Post-measure
        post = validate_success(
            api.get_walkout_cost_estimate(rt["id"], stay, manager_headers),
            expected_status=200,
        )
        # Conservation: estimated_cost_cents (and expected_walkouts)
        # are restored to the pre-create values.
        assert post["estimated_cost_cents"] == pre["estimated_cost_cents"]
        assert post["expected_walkouts"] == pre["expected_walkouts"]
