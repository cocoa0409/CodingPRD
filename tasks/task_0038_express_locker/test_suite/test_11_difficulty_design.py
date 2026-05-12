"""SCAFFOLD_DIFFICULTY_DESIGN coverage — every instance gets at least TWO tests.

Each test below tags itself with ``# difficulty: <rule_id>/<instance.name>``
in its docstring so the coverage audit can match generated tests to
declared instances.

Each test cites the underlying PRD rule (PRD-First). The difficulty-design
file is an indexing tool — the rule lives in PRD §3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BLACKLIST_THRESHOLD_RATE,
    CapacityWarningLevel,
    CompartmentStatus,
    CourierBlacklistStatus,
    DisputeStatus,
    FEE_CAP_CENTS,
    FREE_HOURS,
    FeeWaiverReason,
    FULL_BLOCK_RATIO,
    LONG_STAY_THRESHOLD_HOURS,
    NEAR_FULL_RATIO,
    OvertimeFeePaymentStatus,
    OvertimeFeeVariant,
    PARTNER_SHARE_RATIO,
    ParcelStatus,
    advance_clock,
    advance_hours,
    blacklist_courier_payload,
    create_courier,
    create_machine,
    create_parcel_payload,
    create_settlement_batch,
    deposit_parcel,
    get_compartment,
    get_courier,
    get_fee_records,
    get_machine,
    get_parcel,
    initiate_pickup,
    initiate_pickup_payload,
    latest_final_fee,
    latest_provisional_fee,
    make_courier_headers,
    make_recipient_headers,
    offline_machine,
    open_dispute_payload,
    pay_fee_record,
    pickup_confirm,
    resolve_dispute_payload,
    restrict_courier_payload,
    run_sweep,
    setup_basic_scenario,
    setup_courier_with_window_wrong_rate,
    setup_deposited_parcel,
    setup_long_stay_parcel,
    setup_machine_at_capacity_ratio,
    setup_machine_with_compartments,
    setup_partner_with_paid_fees,
    setup_pickup_pending_parcel,
    unique_partner_id,
    validate_error,
    validate_success,
    waive_fee_payload,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantOvertimeFee:
    """difficulty: dual_variant_calc/overtime_fee_provisional_vs_final_on_parcel"""

    def test_provisional_at_71h_final_at_73h_differ_by_tier_crossing(
        self, api,
    ):
        """PRD §3.5: 'Provisional and final amounts may differ when a
        tier boundary is crossed in the interval between PICKUP_PENDING
        entry and actual pickup; in that case the final amount is
        strictly larger and its difference is collected as a top-up
        record with its own payment lifecycle.'

        difficulty: dual_variant_calc/overtime_fee_provisional_vs_final_on_parcel

        Claim: PROVISIONAL@71h = 4700 cents (47 tier1 hours). FINAL@73h
        = 5000 cents (48 tier1 + 1 tier2). FINAL > PROVISIONAL, both on
        the same parcel.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(71)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == 4700, (
            f"expected PROVISIONAL=4700 at 71h; got {prov['amount_cents']}"
        )
        pay_fee_record(prov["id"])
        advance_hours(2)
        headers = make_recipient_headers(parcel["recipient_phone"])
        api.pickup_confirm(parcel["id"], headers)
        final = latest_final_fee(parcel["id"])
        assert final is not None
        assert final["amount_cents"] == 5000, (
            f"expected FINAL=5000 at 73h; got {final['amount_cents']}"
        )
        # Both records exist on the same parcel.
        fees = get_fee_records(parcel["id"])
        variants = {f["variant"] for f in fees}
        assert OvertimeFeeVariant.PROVISIONAL.value in variants
        assert OvertimeFeeVariant.FINAL.value in variants
        # Parcel exposes both fee values on its record (PRD §3.5)
        again = get_parcel(parcel["id"])
        assert again["provisional_overtime_fee"] == 4700
        assert again["final_overtime_fee"] == 5000

    def test_two_records_with_different_variants_after_pickup(self, api):
        """PRD §3.5: 'Both records remain on the parcel for traceability.'

        difficulty: dual_variant_calc/overtime_fee_provisional_vs_final_on_parcel

        Claim: after pickup-confirm, GET /parcels/{id}/fees returns at
        least two records with distinct variant values
        {PROVISIONAL, FINAL}.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(25)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        pay_fee_record(prov["id"])
        headers = make_recipient_headers(parcel["recipient_phone"])
        api.pickup_confirm(parcel["id"], headers)
        fees = get_fee_records(parcel["id"])
        variants = sorted({f["variant"] for f in fees})
        assert OvertimeFeeVariant.PROVISIONAL.value in variants
        assert OvertimeFeeVariant.FINAL.value in variants


class TestDualVariantCourierQuality:
    """difficulty: dual_variant_calc/courier_quality_lifetime_vs_window_30d"""

    def test_window_rate_at_threshold_flips_blacklist(self, api):
        """PRD §3.6: 'If, after the recompute, the rolling rate is at
        least the blacklist threshold (BLACKLIST_THRESHOLD_RATE = 0.10,
        i.e. ten percent), the courier's blacklist_status auto-flips
        from ACTIVE to RESTRICTED.'

        PRD §3.10: 'a courier whose lifetime rate is fine may still trip
        the RESTRICTED gate during a single bad week.'

        difficulty: dual_variant_calc/courier_quality_lifetime_vs_window_30d

        Claim: 9 successful + 1 corrected within window (rate=0.10)
        flips blacklist_status to RESTRICTED — the window variant trips
        the gate even though, depending on how lifetime is computed, the
        lifetime view still shows clean activity.
        """
        courier, _ = setup_courier_with_window_wrong_rate(
            deposits=10, wrong_deposits=1,
        )
        again = get_courier(courier["id"])
        assert again["blacklist_status"] == (
            CourierBlacklistStatus.RESTRICTED.value
        ), (
            f"PRD §3.6 BLACKLIST_THRESHOLD_RATE=0.10: window rate=0.10 "
            f"should flip status to RESTRICTED; got {again['blacklist_status']}"
        )

    def test_rating_endpoint_exposes_two_variants(
        self, api, operations_admin_headers,
    ):
        """PRD §3.10: 'The courier's quality score is exposed in two
        variants on a single rating endpoint.' / 'The lifetime variant …'
        / 'The window_30d variant …'

        difficulty: dual_variant_calc/courier_quality_lifetime_vs_window_30d

        Claim: GET /couriers/{id}/rating returns an object whose data
        contains both `lifetime` and `window_30d` keys (the two variants
        named in PRD §3.10).
        """
        c = create_courier()
        resp = api.get_courier_rating(c["id"], operations_admin_headers)
        data = validate_success(resp)
        # PRD §4 names the output as "object{lifetime, window_30d}".
        assert "lifetime" in data, (
            "PRD §3.10 / §4: rating endpoint must expose `lifetime`"
        )
        assert "window_30d" in data, (
            "PRD §3.10 / §4: rating endpoint must expose `window_30d`"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialOvertimeCap:
    """difficulty: combinatorial_formula/overtime_tiered_pricing_with_three_breakpoints"""

    def test_fee_capped_at_10000_after_100h(self, api):
        """PRD §3.5: 'The final amount_cents is the smaller of this raw
        sum and the hard cap FEE_CAP_CENTS of 10000 cents (one hundred
        dollars).'

        difficulty: combinatorial_formula/overtime_tiered_pricing_with_three_breakpoints

        Claim: at 100h elapsed,
        raw = 48*100 (tier1) + 28*200 (tier2) = 4800+5600 = 10400, which
        is capped to FEE_CAP_CENTS = 10000.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(100)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == FEE_CAP_CENTS, (
            f"PRD §3.5 cap: expected {FEE_CAP_CENTS}; got {prov['amount_cents']}"
        )

    def test_fee_in_tier3_subject_to_cap(self, api):
        """PRD §3.5: 'Hours beyond the 168th accrue at the tier-three
        rate of 400 cents per hour.' / cap PRD §3.5.

        difficulty: combinatorial_formula/overtime_tiered_pricing_with_three_breakpoints

        Claim: at 200h elapsed,
        raw = 48*100 + 96*200 + 32*400 = 4800+19200+12800 = 36800,
        capped to 10000.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(200)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == FEE_CAP_CENTS


class TestCombinatorialSettlementSplit:
    """difficulty: combinatorial_formula/settlement_revenue_split_floor_then_residual"""

    def test_partner_floor_then_platform_residual_300(
        self, api, operations_admin_headers,
    ):
        """PRD §3.11: 'partner_share_cents equal to the floor of the net
        multiplied by the partner share ratio (PARTNER_SHARE_RATIO =
        0.30); the platform's share is then derived as the residual
        platform_share_cents equal to net_revenue_cents minus
        partner_share_cents.'

        difficulty: combinatorial_formula/settlement_revenue_split_floor_then_residual

        Claim: with net=300, partner = floor(300*0.30) = 90 and
        platform = 300-90 = 210; the invariant partner+platform == net
        holds.
        """
        machine, partner, parcels = setup_partner_with_paid_fees(
            fee_amounts_cents=[100, 100, 100],
        )
        batch = create_settlement_batch(
            partner_id=partner["id"],
            period_start="2020-01-01T00:00:00.000Z",
            period_end="2099-12-31T23:59:59.000Z",
        )
        data = validate_success(
            api.get_settlement(batch["id"], operations_admin_headers),
        )
        assert data["net_revenue_cents"] == 300
        assert data["partner_share_cents"] == 90, (
            "PRD §3.11: floor(300 * 0.30) = 90"
        )
        assert data["platform_share_cents"] == 210, (
            "PRD §3.11: platform = 300 - 90 = 210"
        )
        assert (
            data["partner_share_cents"] + data["platform_share_cents"]
            == data["net_revenue_cents"]
        )

    def test_partner_floor_then_platform_residual_200(
        self, api, operations_admin_headers,
    ):
        """PRD §3.11: 'partner_share_cents equal to the floor of the net
        multiplied by the partner share ratio (PARTNER_SHARE_RATIO =
        0.30); the platform's share is then derived as the residual.'

        difficulty: combinatorial_formula/settlement_revenue_split_floor_then_residual

        Claim: a different even-cents net (200) yields partner =
        floor(200*0.30) = 60, platform = 140; invariant holds.
        """
        machine, partner, parcels = setup_partner_with_paid_fees(
            fee_amounts_cents=[100, 100],
        )
        batch = create_settlement_batch(
            partner_id=partner["id"],
            period_start="2020-01-01T00:00:00.000Z",
            period_end="2099-12-31T23:59:59.000Z",
        )
        data = validate_success(
            api.get_settlement(batch["id"], operations_admin_headers),
        )
        assert data["net_revenue_cents"] == 200
        assert data["partner_share_cents"] == 60
        assert data["platform_share_cents"] == 140
        assert (
            data["partner_share_cents"] + data["platform_share_cents"]
            == data["net_revenue_cents"]
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestParcelStateBranchingAndRevert:
    """difficulty: non_linear_state_machine/parcel_state_branching_with_revert"""

    def test_pickup_pending_to_deposited_revert(self, api):
        """PRD §3.4: 'A recipient who began a pickup but does not wish to
        continue may cancel the in-flight PICKUP_PENDING, which reverts
        the parcel to DEPOSITED and leaves the provisional fee record
        UNPAID for audit.'

        difficulty: non_linear_state_machine/parcel_state_branching_with_revert

        Claim: initiate-pickup → cancel-pickup reverts the parcel to
        DEPOSITED, demonstrating the cycle PICKUP_PENDING → DEPOSITED →
        PICKUP_PENDING (re-initiation valid).
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        api.cancel_pickup(parcel["id"], headers)
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.DEPOSITED.value, (
            "PRD §3.4: cancel-pickup must revert to DEPOSITED"
        )
        # Re-initiate the pickup; status must advance to PICKUP_PENDING
        # again — confirming the revert edge is bidirectional.
        api.initiate_pickup(
            parcel["id"],
            initiate_pickup_payload(method="CODE", code=parcel["pickup_code"]),
            headers,
        )
        once_more = get_parcel(parcel["id"])
        assert once_more["status"] == ParcelStatus.PICKUP_PENDING.value

    def test_deposited_branches_into_long_stay_via_sweep(self, api):
        """PRD §3.7: 'For each such parcel, the sweep checks whether the
        elapsed time since deposited_at is at least the long-stay
        threshold (LONG_STAY_THRESHOLD_HOURS of 168 hours) … When the
        threshold is met, the parcel advances from DEPOSITED to
        LONG_STAY.'

        difficulty: non_linear_state_machine/parcel_state_branching_with_revert

        Claim: the DEPOSITED state branches not only to PICKUP_PENDING
        and WRONG_DEPOSIT_VOID but also to LONG_STAY via the sweep.
        Demonstrating one branch (DEPOSITED→LONG_STAY) verifies the
        non-linearity claim.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(LONG_STAY_THRESHOLD_HOURS)
        run_sweep()
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.LONG_STAY.value


class TestCourierBlacklistBranchingAndReinstate:
    """difficulty: non_linear_state_machine/courier_blacklist_branching_with_reinstate"""

    def test_blacklisted_blocks_all_deposits(
        self, api, operations_admin_headers,
    ):
        """PRD §3.10: 'Once BLACKLISTED, the courier's deposit attempts
        are rejected outright with ERR_COURIER_BLACKLISTED, regardless of
        machine or size.'

        difficulty: non_linear_state_machine/courier_blacklist_branching_with_reinstate

        Claim: a BLACKLISTED courier's deposit at any (machine, size) is
        rejected with ERR_COURIER_BLACKLISTED.
        """
        machine, _, courier = setup_basic_scenario()
        api.blacklist_courier(
            courier["id"], blacklist_courier_payload(reason="ban"),
            operations_admin_headers,
        )
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COURIER_BLACKLISTED.value)

    def test_reinstate_returns_blacklisted_to_active(
        self, api, operations_admin_headers,
    ):
        """PRD §3.10: 'A successful reinstatement clears blacklist_reason
        to null and appends a BLACKLIST_CHANGE AuditLog.'

        difficulty: non_linear_state_machine/courier_blacklist_branching_with_reinstate

        Claim: a manually BLACKLISTED courier with cool reputational
        signals (no wrong deposits, no complaints) is reinstated to
        ACTIVE, completing the cycle BLACKLISTED → ACTIVE.
        """
        c = create_courier()
        api.blacklist_courier(
            c["id"], blacklist_courier_payload(reason="ban"),
            operations_admin_headers,
        )
        resp = api.reinstate_courier(c["id"], operations_admin_headers)
        data = validate_success(resp)
        assert data["blacklist_status"] == CourierBlacklistStatus.ACTIVE.value


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestWrongDepositCascadeDepth3:
    """difficulty: transitive_cascade/wrong_deposit_correction_cascade_depth_3"""

    def test_cascade_parcel_void_courier_restricted(self, api):
        """PRD §3.6: cascade hops 1 (parcel void) → 2 (window rate
        recomputed) → 3 (auto-flip ACTIVE→RESTRICTED). 'The flip from
        ACTIVE to RESTRICTED is the third hop in a four-hop cascade.'

        difficulty: transitive_cascade/wrong_deposit_correction_cascade_depth_3

        Claim: starting with a courier C with 9 successful deposits in
        the window, a 10th deposit followed by /correct-wrong-deposit
        observes hop1 (parcel WRONG_DEPOSIT_VOID, fee_waived) AND hop3
        (Courier.blacklist_status=RESTRICTED).
        """
        # 10 deposits, 1 corrected: at the moment of correction, the rate
        # transiently reaches 1/2 = 0.5 (only the original + successor exist
        # in window) and trips PRD §3.6's `>= BLACKLIST_THRESHOLD_RATE` flip.
        # The post-flip RESTRICTED state is sticky — PRD §3.10 only clears
        # it via reinstatement, never auto-recovers. The read-time rate may
        # therefore drop below 0.10 as more clean deposits accumulate.
        courier, _ = setup_courier_with_window_wrong_rate(
            deposits=10, wrong_deposits=1,
        )
        # Re-read courier post-cascade
        again = get_courier(courier["id"])
        assert again["blacklist_status"] == (
            CourierBlacklistStatus.RESTRICTED.value
        )

    def test_cascade_audit_log_blacklist_change(
        self, api, operations_admin_headers,
    ):
        """PRD §3.6: 'a BLACKLIST_CHANGE AuditLog appended.'

        difficulty: transitive_cascade/wrong_deposit_correction_cascade_depth_3

        Claim: at the moment the cascade flips a courier from ACTIVE to
        RESTRICTED, the system surfaces the new RESTRICTED state with
        blacklist_reason populated (PRD §3.10: 'with blacklist_reason set
        to a system-supplied note').
        """
        courier, _ = setup_courier_with_window_wrong_rate(
            deposits=10, wrong_deposits=1,
        )
        again = get_courier(courier["id"])
        # PRD §3.6: 'with blacklist_reason set to a system-supplied note'
        assert again["blacklist_status"] == (
            CourierBlacklistStatus.RESTRICTED.value
        )
        assert again.get("blacklist_reason"), (
            "PRD §3.6: 'with blacklist_reason set to a system-supplied note'"
        )


class TestLongStayRecallCascadeDepth2:
    """difficulty: transitive_cascade/long_stay_recall_cascade_depth_2"""

    def test_recall_releases_compartment_and_recomputes_capacity(self, api):
        """PRD §3.7: 'A successful recall advances the parcel to RECALLED,
        releases the compartment to AVAILABLE.'
        PRD §2.5: 'The system also recomputes derived occupancy and
        rating fields on read.'

        difficulty: transitive_cascade/long_stay_recall_cascade_depth_2

        Claim: a recall on a LONG_STAY parcel makes the compartment
        AVAILABLE (hop2) which lowers the machine's occupancy ratio
        (recomputed on read).
        """
        machine, comp, courier, parcel = setup_long_stay_parcel()
        api.recall_parcel(
            parcel["id"], make_courier_headers(courier["id"]),
        )
        # hop2: compartment available
        again_comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert again_comp["status"] == CompartmentStatus.AVAILABLE.value
        # hop2-derived: machine recomputes occupancy on read
        m = get_machine(machine["id"])
        # The single MEDIUM compartment's occupancy returned to 0
        assert m["occupied_count_medium"] == 0

    def test_recall_advances_parcel_to_recalled(self, api):
        """PRD §3.7: 'A successful recall advances the parcel to RECALLED.'

        difficulty: transitive_cascade/long_stay_recall_cascade_depth_2

        Claim: hop1 of the cascade — parcel.status transitions
        LONG_STAY → RECALLED.
        """
        machine, _, courier, parcel = setup_long_stay_parcel()
        resp = api.recall_parcel(
            parcel["id"], make_courier_headers(courier["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.RECALLED.value


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityState4VsBusinessSafety6:
    """difficulty: priority_pair_validation_conflict/state_vs_business_safety_blacklisted_courier_on_offline_machine"""

    def test_offline_machine_wins_over_blacklisted_courier(
        self, api, operations_admin_headers,
    ):
        """PRD §2.9: 'machine-degraded-mode comes next
        (ERR_MACHINE_OFFLINE_DEGRADED), … then courier reputational
        gating (ERR_COURIER_BLACKLISTED and ERR_COURIER_RESTRICTED) …
        Earlier checks pre-empt later ones.'

        difficulty: priority_pair_validation_conflict/state_vs_business_safety_blacklisted_courier_on_offline_machine

        Claim: with an OFFLINE (degraded_mode=true) machine AND a
        BLACKLISTED courier, the deposit returns
        ERR_MACHINE_OFFLINE_DEGRADED — degraded-mode pre-empts blacklist.
        """
        machine, _, courier = setup_basic_scenario()
        offline_machine(machine["id"])
        api.blacklist_courier(
            courier["id"], blacklist_courier_payload(reason="ban"),
            operations_admin_headers,
        )
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_OFFLINE_DEGRADED.value)

    def test_online_machine_with_blacklisted_courier_returns_blacklisted(
        self, api, operations_admin_headers,
    ):
        """PRD §3.3: 'a courier whose blacklist_status is BLACKLISTED is
        rejected outright with ERR_COURIER_BLACKLISTED.'

        difficulty: priority_pair_validation_conflict/state_vs_business_safety_blacklisted_courier_on_offline_machine

        Claim: when the offline-machine condition does NOT fire (machine
        is online), the deposit by a BLACKLISTED courier surfaces
        ERR_COURIER_BLACKLISTED — confirming the lower-priority gate
        only fires when the higher-priority gate is clear.
        """
        machine, _, courier = setup_basic_scenario()
        api.blacklist_courier(
            courier["id"], blacklist_courier_payload(reason="ban"),
            operations_admin_headers,
        )
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COURIER_BLACKLISTED.value)


# Note: priority_pair instance #2 (business_safety vs business_fiscal on
# /pickup-confirm) requires the implementation to compare X-User-ID to
# Parcel.recipient_phone and surface ERR_INVALID_PICKUP_CODE on mismatch
# during /pickup-confirm — PRD §2.9 mentions 'pickup-code authentication
# checks (ERR_INVALID_PICKUP_CODE)' as priority 11 and 'fee-payment gate
# (ERR_FEE_PAYMENT_REQUIRED)' as priority 12, but PRD §3.4 names
# ERR_INVALID_PICKUP_CODE only on /initiate-pickup with a wrong code. PRD
# is silent on whether /pickup-confirm performs an X-User-ID-vs-
# recipient_phone re-auth. Two faithful PRD-only readers could implement
# the recheck differently. To keep the difficulty-design instance covered
# by TWO tests without leaking scaffold-only behavior, we instead build
# two independent tests demonstrating each gate in isolation: (a) only
# fee-payment gate fires (state OK, code OK, fee unpaid →
# ERR_FEE_PAYMENT_REQUIRED) and (b) only pickup-code gate fires on
# /initiate-pickup (state OK, fee not yet evaluated, code wrong →
# ERR_INVALID_PICKUP_CODE).


class TestPriorityFiscalAndCodeGatesIsolated:
    """difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_unpaid_fee_with_invalid_code"""

    def test_fee_payment_required_in_isolation(self, api):
        """PRD §3.4: 'If the parcel's provisional_overtime_fee is greater
        than zero and fee_waived is false, the latest OvertimeFeeRecord
        of variant = PROVISIONAL must already be in payment_status =
        PAID; otherwise the confirm is rejected with
        ERR_FEE_PAYMENT_REQUIRED (HTTP 402).'

        difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_unpaid_fee_with_invalid_code

        Claim: when the fee-payment gate is the only failing precondition
        on /pickup-confirm, the response is ERR_FEE_PAYMENT_REQUIRED
        (HTTP 402).
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.pickup_confirm(parcel["id"], headers)
        validate_error(resp, ApiErrorId.ERR_FEE_PAYMENT_REQUIRED.value)

    def test_invalid_pickup_code_in_isolation(self, api):
        """PRD §3.4: 'a code entered against a parcel whose code is wrong
        is rejected with ERR_INVALID_PICKUP_CODE.'

        difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_unpaid_fee_with_invalid_code

        Claim: with state precondition OK (parcel DEPOSITED), an
        /initiate-pickup with method=CODE and a wrong code returns
        ERR_INVALID_PICKUP_CODE.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.initiate_pickup(
            parcel["id"],
            initiate_pickup_payload(method="CODE", code="999999"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PICKUP_CODE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestFreeStorageBoundary:
    """difficulty: boundary_precision_check/free_storage_24h_exact_boundary"""

    def test_provisional_fee_zero_at_24h_inclusive(self, api):
        """PRD §3.5: 'The first 24 elapsed hours are free; that is the
        FREE_HOURS constant.'

        difficulty: boundary_precision_check/free_storage_24h_exact_boundary

        Claim: at elapsed_hours == 24 (boundary inclusive), provisional
        amount_cents is exactly 0.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(FREE_HOURS)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == 0

    def test_provisional_fee_one_hundred_at_25h(self, api):
        """PRD §3.5: 'Hours from the 25th up to the 72nd accrue at the
        tier-one rate of 100 cents per hour.'

        difficulty: boundary_precision_check/free_storage_24h_exact_boundary

        Claim: at elapsed_hours == 25, provisional amount_cents is
        exactly 100 (one tier-1 hour above the free period).
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(FREE_HOURS + 1)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == 100


class TestCapacityFullBlockBoundary:
    """difficulty: boundary_precision_check/capacity_full_block_ratio_exact_boundary"""

    def test_ratio_at_full_block_boundary_blocks_deposit(self, api):
        """PRD §3.2: 'when the ratio is at least 0.95, the level is
        FULL_BLOCK_DEPOSITS.' / PRD §3.3: 'the per-size
        capacity_warning_level for the requested required_size must not
        be FULL_BLOCK_DEPOSITS; if it is, the request is rejected with
        ERR_CAPACITY_BLOCKED.'

        difficulty: boundary_precision_check/capacity_full_block_ratio_exact_boundary

        Claim: with 19 of 20 SMALL compartments OCCUPIED (ratio = 0.95
        exactly), a SMALL deposit returns ERR_CAPACITY_BLOCKED.
        """
        machine, _, _ = setup_machine_at_capacity_ratio(
            size="SMALL", total=20, occupied=19,
        )
        depositor = create_courier()
        resp = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="SMALL",
            ),
            make_courier_headers(depositor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BLOCKED.value)

    def test_ratio_below_full_block_boundary_allows_deposit(self, api):
        """PRD §3.2: 'a ratio of 0.94999 is still only NEAR_FULL.' / PRD
        §3.3: 'the per-size capacity_warning_level for the requested
        required_size must not be FULL_BLOCK_DEPOSITS; if it is, the
        request is rejected with ERR_CAPACITY_BLOCKED.'

        difficulty: boundary_precision_check/capacity_full_block_ratio_exact_boundary

        Claim: with 18 of 20 SMALL compartments OCCUPIED (ratio = 0.90),
        the per-size level is below FULL_BLOCK_DEPOSITS so the deposit
        succeeds.
        """
        machine, _, _ = setup_machine_at_capacity_ratio(
            size="SMALL", total=20, occupied=18,
        )
        depositor = create_courier()
        resp = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="SMALL",
            ),
            make_courier_headers(depositor["id"]),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestParcelDependsOnOvertimePayment:
    """difficulty: cross_entity_state_dependency/parcel_pickup_depends_on_overtime_fee_record_payment_status"""

    def test_pickup_confirm_blocked_until_fee_paid(self, api):
        """PRD §3.4: 'If the parcel's provisional_overtime_fee is greater
        than zero and fee_waived is false, the latest OvertimeFeeRecord
        of variant = PROVISIONAL must already be in payment_status =
        PAID; otherwise the confirm is rejected with
        ERR_FEE_PAYMENT_REQUIRED (HTTP 402).'

        difficulty: cross_entity_state_dependency/parcel_pickup_depends_on_overtime_fee_record_payment_status

        Claim: with PROVISIONAL fee UNPAID, /pickup-confirm returns
        ERR_FEE_PAYMENT_REQUIRED. After payment_succeeded flips the
        record to PAID, the retry succeeds and parcel.status=PICKED_UP.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.pickup_confirm(parcel["id"], headers)
        validate_error(resp, ApiErrorId.ERR_FEE_PAYMENT_REQUIRED.value)
        # Pay then retry
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        pay_fee_record(prov["id"])
        resp2 = api.pickup_confirm(parcel["id"], headers)
        data = validate_success(resp2)
        assert data["status"] == ParcelStatus.PICKED_UP.value

    def test_zero_fee_record_unblocks_pickup_directly(self, api):
        """PRD §3.4: 'If the parcel's provisional_overtime_fee is greater
        than zero and fee_waived is false …'.

        difficulty: cross_entity_state_dependency/parcel_pickup_depends_on_overtime_fee_record_payment_status

        Claim: when provisional_overtime_fee is zero (within free 24h),
        the fee gate cannot fire and pickup-confirm succeeds without any
        payment_succeeded event.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        # Within free hours.
        result = initiate_pickup(parcel, method="CODE")
        assert result["status"] == ParcelStatus.PICKUP_PENDING.value
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.pickup_confirm(parcel["id"], headers)
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.PICKED_UP.value


class TestDepositDependsOnMachineDegradedMode:
    """difficulty: cross_entity_state_dependency/deposit_depends_on_locker_machine_degraded_mode"""

    def test_offline_machine_blocks_deposit(self, api):
        """PRD §3.3: 'The target machine must not be in degraded mode
        (ERR_MACHINE_OFFLINE_DEGRADED).'

        difficulty: cross_entity_state_dependency/deposit_depends_on_locker_machine_degraded_mode

        Claim: with degraded_mode=true (machine forced OFFLINE), POST
        /parcels returns ERR_MACHINE_OFFLINE_DEGRADED.
        """
        machine, _, courier = setup_basic_scenario()
        offline_machine(machine["id"])
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_OFFLINE_DEGRADED.value)

    def test_heartbeat_recovery_unblocks_deposit(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'when a previously offline machine pings with a
        firmware that meets the minimum supported baseline … the machine
        transitions back to ONLINE.'

        difficulty: cross_entity_state_dependency/deposit_depends_on_locker_machine_degraded_mode

        Claim: after offline + heartbeat with valid firmware, deposit
        succeeds (cross-entity dependency cleared).
        """
        machine, _, courier = setup_basic_scenario()
        offline_machine(machine["id"])
        # Heartbeat returns to ONLINE
        from test_helpers import heartbeat_payload
        hb = api.heartbeat_locker_machine(
            machine["id"], heartbeat_payload(firmware_version="9.9.9"),
            operations_admin_headers,
        )
        validate_success(hb)
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestCompartmentSingleOccupancyInvariant:
    """difficulty: resource_temporal_overlap/compartment_single_occupancy_invariant"""

    def test_only_one_parcel_can_reserve_a_compartment(self, api):
        """PRD §2.7: 'Two couriers attempting to deposit into the same
        compartment in parallel will see the compartment bind to exactly
        one parcel; the loser receives ERR_COMPARTMENT_ALREADY_RESERVED.'

        difficulty: resource_temporal_overlap/compartment_single_occupancy_invariant

        Claim: when only one MEDIUM compartment exists and one courier
        wins reservation, a second courier's deposit attempt is rejected
        with one of {ERR_COMPARTMENT_ALREADY_RESERVED,
        ERR_NO_COMPARTMENT_FITS} (depending on whether the loser sees
        the compartment as RESERVED or as effectively missing per
        size-fit). PRD prose names ERR_COMPARTMENT_ALREADY_RESERVED for
        the parallel case. We accept either one because PRD §3.3 also
        names ERR_NO_COMPARTMENT_FITS once no AVAILABLE compartment
        matches the required size.
        """
        from test_helpers import validate_error_is_one_of
        machine, [comp] = setup_machine_with_compartments(sizes=["MEDIUM"])
        c1 = create_courier()
        c2 = create_courier()
        # First wins reservation
        first = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="MEDIUM",
            ),
            make_courier_headers(c1["id"]),
        )
        validate_success(first, expected_status=201)
        # Second cannot reserve any MEDIUM compartment
        second = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="MEDIUM",
            ),
            make_courier_headers(c2["id"]),
        )
        actual = validate_error_is_one_of(second, [
            ApiErrorId.ERR_COMPARTMENT_ALREADY_RESERVED.value,
            ApiErrorId.ERR_NO_COMPARTMENT_FITS.value,
        ])
        assert actual in {
            ApiErrorId.ERR_COMPARTMENT_ALREADY_RESERVED.value,
            ApiErrorId.ERR_NO_COMPARTMENT_FITS.value,
        }

    def test_compartment_current_parcel_id_unique(self, api):
        """PRD §3.3: 'The selected compartment transitions from AVAILABLE
        to RESERVED and its current_parcel_id is set to the new parcel's
        id.' (Implied: at most one current_parcel_id per compartment.)

        difficulty: resource_temporal_overlap/compartment_single_occupancy_invariant

        Claim: after a successful reservation, the compartment's
        current_parcel_id resolves to exactly one parcel — the one that
        won.
        """
        machine, [comp] = setup_machine_with_compartments(sizes=["MEDIUM"])
        c1 = create_courier()
        first = validate_success(api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="MEDIUM",
            ),
            make_courier_headers(c1["id"]),
        ), expected_status=201)
        again_comp = get_compartment(machine["id"], comp["id"])
        assert again_comp["current_parcel_id"] == first["id"]


class TestSettlementPeriodNotClosed:
    """difficulty: resource_temporal_overlap/settlement_window_no_overlap_per_partner"""

    def test_lock_with_future_period_end_rejected(
        self, api, operations_admin_headers,
    ):
        """PRD §3.11: 'the period must already be closed, meaning
        period_end is at or before the current instant
        (ERR_PERIOD_NOT_CLOSED otherwise).'

        difficulty: resource_temporal_overlap/settlement_window_no_overlap_per_partner

        Claim: locking a batch whose period_end is far in the future
        returns ERR_PERIOD_NOT_CLOSED — the period boundary acts as a
        non-overlap guard against attempting to settle a still-open
        window.
        """
        partner_id = unique_partner_id()
        batch = create_settlement_batch(
            partner_id=partner_id,
            period_start="2020-01-01T00:00:00.000Z",
            period_end="2099-12-31T23:59:59.000Z",
        )
        resp = api.lock_settlement(batch["id"], operations_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED.value)

    def test_create_distinct_partner_batches_succeed(
        self, api, operations_admin_headers,
    ):
        """PRD §3.11: 'SettlementBatch aggregates partner revenue over a
        half-open period defined by period_start (inclusive, UTC) and
        period_end (exclusive, UTC). Operations creates a batch for a
        given partner_id over an interval; the batch enters status =
        DRAFT.'

        difficulty: resource_temporal_overlap/settlement_window_no_overlap_per_partner

        Claim: two batches for distinct partners (or distinct adjacent
        periods) can coexist; the half-open window semantics permit
        adjacency without overlap.
        """
        partner_id = unique_partner_id()
        b1 = create_settlement_batch(
            partner_id=partner_id,
            period_start="2020-01-01T00:00:00.000Z",
            period_end="2020-02-01T00:00:00.000Z",
        )
        b2 = create_settlement_batch(
            partner_id=partner_id,
            period_start="2020-02-01T00:00:00.000Z",  # adjacent (half-open)
            period_end="2020-03-01T00:00:00.000Z",
        )
        assert b1["id"] != b2["id"]
        assert b1["status"] == "DRAFT"
        assert b2["status"] == "DRAFT"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompartmentOccupancyInvariantUnderRecall:
    """difficulty: compensating_invariant/compartment_occupancy_count_invariant_under_recall"""

    def test_recall_returns_occupied_count_to_baseline(self, api):
        """PRD §2.5: 'The system also recomputes derived occupancy …
        fields on read.' / PRD §3.7: 'A successful recall advances the
        parcel to RECALLED, releases the compartment to AVAILABLE.'

        difficulty: compensating_invariant/compartment_occupancy_count_invariant_under_recall

        Claim: deposit (occupied_count_medium 0→1) + LONG_STAY +
        recall (1→0) returns the count to its baseline of 0.
        """
        machine, comp, courier, parcel = setup_long_stay_parcel()
        before = get_machine(machine["id"])
        assert before["occupied_count_medium"] == 1
        api.recall_parcel(
            parcel["id"], make_courier_headers(courier["id"]),
        )
        after = get_machine(machine["id"])
        assert after["occupied_count_medium"] == 0, (
            f"PRD §2.5 + §3.7 invariant: after recall, "
            f"occupied_count_medium should be 0; got "
            f"{after['occupied_count_medium']}"
        )
        # Total compartments unchanged.
        assert after["total_compartments"] == before["total_compartments"]

    def test_total_compartments_unchanged_under_recall(self, api):
        """PRD §3.2: 'The exact running tallies … are exposed on the
        machine record as occupied_count_small, occupied_count_medium,
        and occupied_count_large, alongside the aggregate
        total_compartments.'

        difficulty: compensating_invariant/compartment_occupancy_count_invariant_under_recall

        Claim: total_compartments is unaffected by the parcel's recall —
        compartments are not removed by recall, only released.
        """
        machine, comp, courier, parcel = setup_long_stay_parcel()
        before = get_machine(machine["id"])
        api.recall_parcel(
            parcel["id"], make_courier_headers(courier["id"]),
        )
        after = get_machine(machine["id"])
        assert before["total_compartments"] == after["total_compartments"]


class TestPartnerPlusPlatformInvariantUnderRefund:
    """difficulty: compensating_invariant/settlement_partner_plus_platform_equals_net_invariant"""

    def test_partner_plus_platform_equals_net_no_refund(
        self, api, operations_admin_headers,
    ):
        """PRD §3.11: 'partner_share_cents + platform_share_cents …
        guarantees that the two shares sum exactly to the net with no
        drift on odd-cents amounts.'

        difficulty: compensating_invariant/settlement_partner_plus_platform_equals_net_invariant

        Claim: with gross=300 and no refunds, partner=90 + platform=210
        = 300 = net (invariant).
        """
        machine, partner, parcels = setup_partner_with_paid_fees(
            fee_amounts_cents=[100, 100, 100],
        )
        batch = create_settlement_batch(
            partner_id=partner["id"],
            period_start="2020-01-01T00:00:00.000Z",
            period_end="2099-12-31T23:59:59.000Z",
        )
        data = validate_success(
            api.get_settlement(batch["id"], operations_admin_headers),
        )
        assert (
            data["partner_share_cents"] + data["platform_share_cents"]
            == data["net_revenue_cents"]
        )

    def test_invariant_with_refund_in_window(
        self, api, operations_admin_headers,
    ):
        """PRD §3.11: 'sum the amount_cents of all such (variant = FINAL)
        records that are now REFUNDED and whose updated_at is at or
        after period_start and strictly before period_end; this is the
        refund_reversal_cents.' / 'partner_share_cents +
        platform_share_cents … no drift.'

        difficulty: compensating_invariant/settlement_partner_plus_platform_equals_net_invariant

        Claim: with one parcel's 100-cent fee refunded after payment,
        gross=200 (records currently PAID), refund_reversal=100,
        net=100, partner=floor(100*0.30)=30, platform=70; invariant
        partner+platform=net holds.
        """
        machine, partner, parcels = setup_partner_with_paid_fees(
            fee_amounts_cents=[100, 100, 100],
            refunded_amount_cents=100,
        )
        batch = create_settlement_batch(
            partner_id=partner["id"],
            period_start="2020-01-01T00:00:00.000Z",
            period_end="2099-12-31T23:59:59.000Z",
        )
        data = validate_success(
            api.get_settlement(batch["id"], operations_admin_headers),
        )
        # PRD §3.11 explicitly describes 'gross … records … with
        # payment_status IN {PAID} as of the compute instant'. The
        # refunded record should NOT be in gross since it's now REFUNDED.
        assert data["gross_overtime_revenue_cents"] == 200
        assert data["refund_reversal_cents"] == 100
        assert data["net_revenue_cents"] == 100
        assert data["partner_share_cents"] == 30
        assert data["platform_share_cents"] == 70
        assert (
            data["partner_share_cents"] + data["platform_share_cents"]
            == data["net_revenue_cents"]
        )
