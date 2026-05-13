"""SCAFFOLD_DIFFICULTY_DESIGN coverage — every difficulty-design
instance is exercised by at least TWO tests tagged `# difficulty:
<rule_id>/<instance.name>` per skill §2.1.A.

Test recipes are translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml;
assertions cite the PRD prose that states the underlying rule.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_density_posture_matches,
    bike_fault_report_payload,
    cancel_transfer,
    complete_transfer,
    create_bike,
    create_funded_rider,
    create_geofence,
    create_loss_record,
    create_region,
    create_rider,
    create_ride_payload,
    create_transfer,
    create_transfer_payload,
    create_workorder,
    credit_wallet,
    dispatch_transfer,
    dispute_ride,
    end_ride,
    end_ride_payload,
    find_workorder_for_bike,
    get_bike,
    get_region,
    get_region_loss_rate,
    get_rider,
    get_ride,
    grant_free_minutes,
    list_workorders,
    make_rider_headers,
    make_square_polygon,
    patch_bike,
    recall_bike,
    run_full_ride,
    setup_basic_ride_scenario,
    setup_region_at_posture,
    setup_region_with_allowed_parking,
    setup_region_with_bikes,
    setup_region_with_exact_available,
    setup_region_with_restricted_zone,
    setup_transfer_cascade_three_hop,
    settle_ride_and_dispute,
    settle_simple_standard_ride,
    shelf_bike_off,
    shelf_bike_on,
    shelf_payload,
    start_ride,
    validate_error,
    validate_success,
    void_ride,
    ADMIN,
    NON_EXISTENT_UUID,
    OPERATOR,
)


# ===========================================================================
# Rule 1: dual_variant_calc / ride_fare_per_minute_vs_daily_cap
# ===========================================================================
class TestDualVariantFareCap:
    """SCAFFOLD_DIFFICULTY_DESIGN dual_variant_calc /
    ride_fare_per_minute_vs_daily_cap.

    PRD §3.4 backs the rule: 'A daily cap is then applied. The cap for
    a STANDARD bike is 1500 cents (DAILY_CAP_STD_CENTS); for an E_BIKE
    it is 3000 cents (DAILY_CAP_EBIKE_CENTS). If base_fare_cents is
    greater than or equal to the applicable cap, it is clamped to the
    cap and the ride's settlement_variant is recorded as DAILY_CAP;
    otherwise base_fare_cents is left as computed and the variant is
    PER_MINUTE.'
    """

    def test_per_minute_variant_at_short_ride(self, api):
        """PRD §3.4: 'otherwise base_fare_cents is left as computed and
        the variant is PER_MINUTE.'

        20 chargeable minutes on STANDARD: 20*30 = 600 < 1500 → PER_MINUTE.
        """
        # difficulty: dual_variant_calc/ride_fare_per_minute_vs_daily_cap
        ctx = settle_simple_standard_ride(duration_minutes=20)
        ride = ctx["ride"]
        assert ride["settlement_variant"] == "PER_MINUTE"
        assert ride["final_fare_cents"] == 600

    def test_daily_cap_variant_at_long_ride(self, api):
        """PRD §3.4: 'If base_fare_cents is greater than or equal to
        the applicable cap, it is clamped to the cap and the ride's
        settlement_variant is recorded as DAILY_CAP.'

        60 chargeable on STANDARD: 30*30 + 30*50 = 2400 ≥ 1500 → DAILY_CAP.
        """
        # difficulty: dual_variant_calc/ride_fare_per_minute_vs_daily_cap
        ctx = settle_simple_standard_ride(duration_minutes=60)
        ride = ctx["ride"]
        assert ride["settlement_variant"] == "DAILY_CAP"
        assert ride["final_fare_cents"] == 1500


# ===========================================================================
# Rule 1: dual_variant_calc / region_loss_rate_provisional_vs_attributed
# ===========================================================================
class TestDualVariantLossRate:
    """SCAFFOLD_DIFFICULTY_DESIGN dual_variant_calc /
    region_loss_rate_provisional_vs_attributed.

    PRD §3.11 backs the rule: 'provisional_loss_rate is loss_count
    divided by deployed_lifetime and counts every loss record
    regardless of responsibility; attributed_loss_rate is the count of
    loss records whose responsibility is not UNKNOWN, divided by the
    same deployed_lifetime.'
    """

    def test_provisional_counts_unknown_attributed_excludes(self, api):
        """PRD §3.11: 'The two ratios differ exactly when at least one
        loss record carries responsibility UNKNOWN.'"""
        # difficulty: dual_variant_calc/region_loss_rate_provisional_vs_attributed
        region, bikes = setup_region_with_bikes(num_bikes=40)
        # 1 UNKNOWN/ABANDONED, 2 RIDER/DAMAGE, 1 OPERATOR/DAMAGE
        # PRD §3.11: 'responsible_party_id ... is the Rider.id when
        # responsibility is RIDER' — supply real Rider entities.
        rider_x = create_rider()
        rider_y = create_rider()
        create_loss_record(
            bike_id=bikes[0]["id"], cause="ABANDONED",
            responsibility="UNKNOWN", financial_impact_cents=5000,
        )
        create_loss_record(
            bike_id=bikes[1]["id"], cause="DAMAGE",
            responsibility="RIDER", responsible_party_id=rider_x["id"],
            financial_impact_cents=5000,
        )
        create_loss_record(
            bike_id=bikes[2]["id"], cause="DAMAGE",
            responsibility="RIDER", responsible_party_id=rider_y["id"],
            financial_impact_cents=5000,
        )
        create_loss_record(
            bike_id=bikes[3]["id"], cause="DAMAGE",
            responsibility="OPERATOR", responsible_party_id="op-x",
            financial_impact_cents=5000,
        )
        out = get_region_loss_rate(region["id"])
        assert out["loss_count"] == 4
        assert out["deployed_lifetime"] == 40
        assert out["provisional_loss_rate"] == pytest.approx(0.1, abs=1e-4)
        assert out["attributed_loss_rate"] == pytest.approx(0.075, abs=1e-4)

    def test_provisional_equals_attributed_when_no_unknown(self, api):
        """PRD §3.11: 'The two ratios differ exactly when at least one
        loss record carries responsibility UNKNOWN.' Corollary: when
        every record is attributed, the two ratios are equal."""
        # difficulty: dual_variant_calc/region_loss_rate_provisional_vs_attributed
        region, bikes = setup_region_with_bikes(num_bikes=10)
        # PRD §3.11: 'responsible_party_id ... is the Rider.id when
        # responsibility is RIDER' — supply a real Rider entity.
        rider = create_rider()
        create_loss_record(
            bike_id=bikes[0]["id"], cause="DAMAGE",
            responsibility="RIDER", responsible_party_id=rider["id"],
            financial_impact_cents=5000,
        )
        create_loss_record(
            bike_id=bikes[1]["id"], cause="DAMAGE",
            responsibility="OPERATOR", responsible_party_id="op-1",
            financial_impact_cents=5000,
        )
        out = get_region_loss_rate(region["id"])
        assert out["provisional_loss_rate"] == out["attributed_loss_rate"]


# ===========================================================================
# Rule 2: combinatorial_formula / ride_fare_pinned_evaluation_order
# ===========================================================================
class TestPinnedFareEvaluationOrder:
    """SCAFFOLD_DIFFICULTY_DESIGN combinatorial_formula /
    ride_fare_pinned_evaluation_order.

    PRD §3.4 backs the rule: 'The order of arithmetic within a single
    ride settlement is fixed and material: per-minute charge, then
    segment sum, then daily-cap clamp, then penalty added on top of
    the (possibly capped) base, with the reward credited separately to
    the wallet rather than netted against the fare.' AND §3.4 free →
    pass → segment pinning, plus the 'STANDARD only' pass coverage.
    """

    def test_free_consumed_before_pass_then_segment_then_penalty(self, api):
        """PRD §3.4: 'The rider's free_minutes_remaining is consumed
        first ... Whatever remains after free coverage is examined
        against the monthly pass ... The remainder after free and pass
        coverage is chargeable_minutes.' AND 'final_fare_cents is the
        (possibly capped) base_fare_cents plus penalty_cents.'

        STANDARD bike, 40-min ride with 10 free + active pass + ending
        in a RESTRICTED zone (penalty=200):
          applied_free = min(10, 40) = 10
          pass_covered = 40 - 10 = 30 (STANDARD + pass active)
          chargeable = 0
          base = 0
          settlement_variant = PER_MINUTE (0 < 1500)
          penalty added AFTER cap = 200
          final = 0 + 200 = 200
        """
        # difficulty: combinatorial_formula/ride_fare_pinned_evaluation_order
        from test_helpers import setup_rider_with_monthly_pass
        ctx = setup_region_with_restricted_zone(
            center_lat=30.5, center_lng=120.5, side=0.05,
            out_of_zone_penalty_cents=200,
            num_bikes=1,
        )
        # Rider: 10 free minutes + active monthly pass + wallet 10000
        rider = setup_rider_with_monthly_pass(
            wallet_balance_cents=10000, free_minutes=10,
        )
        ride = start_ride(rider, ctx["bikes"][0])
        advance_clock(40)
        settled = end_ride(ride, end_lat=ctx["restricted_lat"],
                           end_lng=ctx["restricted_lng"],
                           rider_id=rider["id"])
        assert settled["applied_free_minutes"] == 10
        assert settled["pass_covered_minutes"] == 30
        assert settled["chargeable_minutes"] == 0
        assert settled["base_fare_cents"] == 0
        assert settled["penalty_cents"] == 200
        assert settled["final_fare_cents"] == 200, (
            "PRD §3.4: penalty added on top of the (possibly capped) base"
        )
        assert settled["settlement_variant"] == "PER_MINUTE"

    def test_pass_does_not_cover_ebike_so_chargeable_is_full(self, api):
        """PRD §3.4: 'the pass covers minutes only on STANDARD bikes —
        it never covers any minute on an E_BIKE.' With free already
        exhausted and pass active but bike = E_BIKE: chargeable equals
        duration."""
        # difficulty: combinatorial_formula/ride_fare_pinned_evaluation_order
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="E_BIKE", battery_pct=100)
        shelf_bike_on(region["id"], bike["id"])
        bike = get_bike(bike["id"])
        from test_helpers import setup_rider_with_monthly_pass
        rider = setup_rider_with_monthly_pass(wallet_balance_cents=10000,
                                              free_minutes=0)
        ride = start_ride(rider, bike)
        advance_clock(25)
        settled = end_ride(ride, end_lat=10.0, end_lng=10.0,
                           rider_id=rider["id"])
        assert settled["pass_covered_minutes"] == 0, (
            "PRD §3.4: pass does not cover any minute on an E_BIKE"
        )
        assert settled["chargeable_minutes"] == 25
        # E_BIKE first-segment rate: 25 * 60 = 1500
        assert settled["base_fare_cents"] == 1500


# ===========================================================================
# Rule 2: combinatorial_formula / density_posture_inclusive_thresholds
# ===========================================================================
class TestDensityPostureInclusiveThresholds:
    """SCAFFOLD_DIFFICULTY_DESIGN combinatorial_formula /
    density_posture_inclusive_thresholds.

    PRD §2.7 backs the rule: 'The posture is LOW when available_count
    is less than or equal to low_density_threshold, HIGH when
    available_count is greater than or equal to high_density_threshold,
    and NORMAL otherwise. The inclusive boundaries on both ends are
    deliberate: equal to the low threshold is LOW, equal to the high
    threshold is HIGH.'
    """

    def test_low_threshold_inclusive(self, api):
        """PRD §2.7: 'equal to the low threshold is LOW.'"""
        # difficulty: combinatorial_formula/density_posture_inclusive_thresholds
        region, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=3, high_density_threshold=10,
            available_count_override=3,
        )
        assert_density_posture_matches(region, "LOW")

    def test_high_threshold_inclusive(self, api):
        """PRD §2.7: 'equal to the high threshold is HIGH.'"""
        # difficulty: combinatorial_formula/density_posture_inclusive_thresholds
        region, _ = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=3, high_density_threshold=10,
            available_count_override=10,
        )
        assert_density_posture_matches(region, "HIGH")


# ===========================================================================
# Rule 3: non_linear_state_machine / bike_status_parallel_dimensions
# ===========================================================================
class TestBikeParallelStateDimensions:
    """SCAFFOLD_DIFFICULTY_DESIGN non_linear_state_machine /
    bike_status_parallel_dimensions.

    PRD §3.2, §3.4, §3.7 collectively pin that Bike carries two
    independent state dimensions (shelf_state and status). Each axis
    transitions on different triggers.
    """

    def test_unlock_changes_status_not_shelf_state(self, api):
        """PRD §3.4: 'On success the bike transitions AVAILABLE → IN_USE
        and LOCKED → UNLOCKED.' shelf_state stays ON_SHELF — only the
        status axis moved."""
        # difficulty: non_linear_state_machine/bike_status_parallel_dimensions
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        before = get_bike(ctx["bike"]["id"])
        assert before["shelf_state"] == "ON_SHELF"
        assert before["status"] == "AVAILABLE"
        start_ride(ctx["rider"], ctx["bike"])
        after = get_bike(ctx["bike"]["id"])
        assert after["shelf_state"] == "ON_SHELF", (
            "PRD §3.4: shelf_state unchanged on unlock"
        )
        assert after["status"] == "IN_USE"

    def test_recall_changes_status_not_shelf_state(self, api):
        """PRD §3.7: 'On success the bike's status is set to RECALL.'
        shelf_state stays ON_SHELF — only the status axis moved."""
        # difficulty: non_linear_state_machine/bike_status_parallel_dimensions
        region, bikes = setup_region_with_bikes(num_bikes=1)
        recall_bike(bikes[0]["id"])
        bike = get_bike(bikes[0]["id"])
        assert bike["shelf_state"] == "ON_SHELF"
        assert bike["status"] == "RECALL"


# ===========================================================================
# Rule 3: non_linear_state_machine /
#         ride_branching_settle_or_void_with_dispute_revert
# ===========================================================================
class TestRideBranchingAndDisputeRevert:
    """SCAFFOLD_DIFFICULTY_DESIGN non_linear_state_machine /
    ride_branching_settle_or_void_with_dispute_revert.

    PRD §3.4, §3.10 pin: ACTIVE branches to SETTLED (end-of-ride) or
    VOIDED (admin void), and SETTLED has a revisit edge to DISPUTED
    that returns to SETTLED via adjust.
    """

    def test_path_a_settle_dispute_adjust_back_to_settled(self, api):
        """PRD §3.10: 'On success the ride advances SETTLED → DISPUTED'
        and 'the ride moves DISPUTED → SETTLED.'"""
        # difficulty: non_linear_state_machine/ride_branching_settle_or_void_with_dispute_revert
        from test_helpers import adjust_ride
        ctx = settle_simple_standard_ride(duration_minutes=10)
        disputed = dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        assert disputed["status"] == "DISPUTED"
        adjusted = adjust_ride(ctx["ride"]["id"], new_final_fare_cents=100)
        assert adjusted["status"] == "SETTLED"
        assert adjusted["final_fare_cents"] == 100

    def test_path_b_active_to_voided(self, api):
        """PRD §3.10: 'On success the ride moves ACTIVE → VOIDED,
        final_fare_cents is set to 0, the bike returns to AVAILABLE,
        and no money moves at all.'"""
        # difficulty: non_linear_state_machine/ride_branching_settle_or_void_with_dispute_revert
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        voided = void_ride(ride["id"])
        assert voided["status"] == "VOIDED"
        assert voided["final_fare_cents"] == 0
        bike_after = get_bike(ctx["bike"]["id"])
        assert bike_after["status"] == "AVAILABLE"
        rider_after = get_rider(ctx["rider"]["id"])
        assert rider_after["wallet_balance_cents"] == 10000


# ===========================================================================
# Rule 4: transitive_cascade / transfer_completion_three_hop_cascade
# ===========================================================================
class TestTransferCompletionThreeHopCascade:
    """SCAFFOLD_DIFFICULTY_DESIGN transitive_cascade /
    transfer_completion_three_hop_cascade.

    PRD §3.8 cascade hops on POST /transfers/{id}/complete:
      hop 1 — bikes flip to ON_SHELF at to_region
      hop 2 — to_region.available_count and density_posture recomputed
      hop 3 — other PLANNED REPLENISH to same destination auto-cancelled
              if posture flips LOW → NORMAL or LOW → HIGH
    """

    def test_three_hop_cascade_full(self, api):
        """PRD §3.8 hop 1+2+3 covered in a single end-to-end pass.
        hop 1: 'On success each bike's region_id is set to to_region_id,
        shelf_state to ON_SHELF, and status to AVAILABLE.'
        hop 2: 'The destination region's counts and density_posture are
        recomputed (cascade hop 2).'
        hop 3: 'if the destination region's density_posture flips from
        LOW to NORMAL or from LOW to HIGH, any other PLANNED
        TransferOrder whose to_region_id is this same destination
        region and whose kind is REPLENISH is automatically transitioned
        to CANCELLED.'"""
        # difficulty: transitive_cascade/transfer_completion_three_hop_cascade
        ctx = setup_transfer_cascade_three_hop()
        complete_transfer(ctx["t1"]["id"])
        # Hop 1
        for bid in ctx["t1_bike_ids"]:
            b = get_bike(bid)
            assert b["region_id"] == ctx["r_low"]["id"]
            assert b["shelf_state"] == "ON_SHELF"
            assert b["status"] == "AVAILABLE"
        # Hop 2
        r_low = get_region(ctx["r_low"]["id"])
        assert r_low["available_count"] == 7
        assert r_low["density_posture"] == "NORMAL"
        # Hop 3
        from test_helpers import api_client
        from prd_bench_local_runner.testing import get_success_data
        t2_after = get_success_data(api_client.get_transfer(
            ctx["t2"]["id"], ADMIN,
        ))
        assert t2_after["status"] == "CANCELLED"

    def test_transfer_status_advances_to_completed(self, api):
        """PRD §3.8: 'The completing transfer advances IN_TRANSIT →
        COMPLETED, completed_minute is set to the current
        clock_minutes.'"""
        # difficulty: transitive_cascade/transfer_completion_three_hop_cascade
        ctx = setup_transfer_cascade_three_hop()
        completed = complete_transfer(ctx["t1"]["id"])
        assert completed["status"] == "COMPLETED"


# ===========================================================================
# Rule 4: transitive_cascade / bike_fault_isolation_two_hop_cascade
# ===========================================================================
class TestBikeFaultIsolationCascade:
    """SCAFFOLD_DIFFICULTY_DESIGN transitive_cascade /
    bike_fault_isolation_two_hop_cascade.

    PRD §3.5 + §2.7 pin: POST /bikes/{id}/fault-report flips bike's
    status (hop 1), and the count change in turn flips
    Region.density_posture (hop 2).
    """

    def test_fault_open_decrements_count_and_flips_posture(self, api):
        """PRD §3.5: 'On success the bike's status is flipped from
        AVAILABLE → FAULT ... the region's available_count decrements
        with density_posture recomputed accordingly.'"""
        # difficulty: transitive_cascade/bike_fault_isolation_two_hop_cascade
        region, bikes = setup_region_with_exact_available(
            available=5, low=4, high=10, deployment_quota=20,
        )
        assert region["density_posture"] == "NORMAL"
        from test_helpers import api_client
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(api_client.fault_report_bike(
            bikes[0]["id"], bike_fault_report_payload(category="FLAT_TIRE"),
            OPERATOR,
        ))
        # Hop 1
        bike = get_bike(bikes[0]["id"])
        assert bike["status"] == "FAULT"
        wo = find_workorder_for_bike(bikes[0]["id"], status="OPEN")
        assert wo["status"] == "OPEN"
        # Hop 2: 5 → 4, low=4 → LOW (inclusive)
        region = get_region(region["id"])
        assert region["available_count"] == 4
        assert region["density_posture"] == "LOW"

    def test_fault_open_creates_workorder_open_for_same_bike(self, api):
        """PRD §3.5: 'a new WorkOrder is opened with cause USER_REPORT,
        status OPEN.'"""
        # difficulty: transitive_cascade/bike_fault_isolation_two_hop_cascade
        region, bikes = setup_region_with_bikes(num_bikes=1)
        from test_helpers import api_client
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(api_client.fault_report_bike(
            bikes[0]["id"], bike_fault_report_payload(category="BRAKE"),
            OPERATOR,
        ))
        wo = find_workorder_for_bike(bikes[0]["id"], status="OPEN")
        assert wo["cause"] == "USER_REPORT"
        assert wo["bike_id"] == bikes[0]["id"]


# ===========================================================================
# Rule 5: priority_pair_validation_conflict /
#         state_vs_fiscal_dual_failure_at_unlock
# ===========================================================================
class TestStateVsFiscalAtUnlock:
    """SCAFFOLD_DIFFICULTY_DESIGN priority_pair_validation_conflict /
    state_vs_fiscal_dual_failure_at_unlock.

    PRD §2.10 + §3.4 pin: when a rider POSTs /rides on a bike whose
    status != AVAILABLE AND wallet < MIN_UNLOCK_BALANCE_CENTS, the
    state error wins because §2.10 lists 'resource-state legality'
    before 'payment-capacity checks at unlock.'
    """

    def test_state_check_pre_empts_balance_check_when_both_would_fail(
        self, api,
    ):
        """PRD §2.10: 'then resource-state legality, then ... then
        payment-capacity checks at unlock and at settlement.' Hence
        a state failure wins over an insufficient-balance failure."""
        # difficulty: priority_pair_validation_conflict/state_vs_fiscal_dual_failure_at_unlock
        region, bikes = setup_region_with_bikes(num_bikes=1)
        # Park bike IN_USE by riding it with rider A
        rider_a = create_funded_rider()
        start_ride(rider_a, bikes[0])
        # Rider B has wallet 0 AND bike is now IN_USE — both checks fail.
        rider_b = create_rider()  # wallet defaults to 0
        # First confirm wallet is 0 (no top-up performed).
        assert rider_b["wallet_balance_cents"] == 0
        resp = api.create_ride(
            create_ride_payload(rider_id=rider_b["id"],
                                bike_id=bikes[0]["id"]),
            make_rider_headers(rider_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409)

    def test_state_check_pre_empts_balance_when_bike_in_recall(self, api):
        """PRD §2.10: state-band check (RECALL is not AVAILABLE) fires
        before payment-capacity. Reinforces the precedence."""
        # difficulty: priority_pair_validation_conflict/state_vs_fiscal_dual_failure_at_unlock
        region, bikes = setup_region_with_bikes(num_bikes=1)
        recall_bike(bikes[0]["id"])
        rider = create_rider()  # wallet 0
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"],
                                bike_id=bikes[0]["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409)


# ===========================================================================
# Rule 5: priority_pair_validation_conflict /
#         safety_vs_referential_dual_failure_on_transfer_dispatch
# ===========================================================================
class TestReferentialVsConstraintOnTransferPlan:
    """SCAFFOLD_DIFFICULTY_DESIGN priority_pair_validation_conflict /
    safety_vs_referential_dual_failure_on_transfer_dispatch.

    PRD §2.10 lists 'existence of body-referenced foreign keys' before
    'domain-specific business preconditions' (including transfer-kind
    posture matching). So a body FK lookup failure pre-empts a
    kind-mismatch.
    """

    def test_unresolvable_from_region_pre_empts_kind_check(self, api):
        """PRD §2.10: 'existence of body-referenced foreign keys' fires
        before 'domain-specific business preconditions ... transfer-kind
        posture matching.'"""
        # difficulty: priority_pair_validation_conflict/safety_vs_referential_dual_failure_on_transfer_dispatch
        r_real, r_real_bikes = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=999,
            available_count_override=4,
        )
        resp = api.create_transfer(
            create_transfer_payload(
                from_region_id=NON_EXISTENT_UUID,
                to_region_id=r_real["id"],
                bike_ids=[r_real_bikes[0]["id"]],
            ),
            OPERATOR,
        )
        validate_error(
            resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404,
        )

    def test_unresolvable_to_region_pre_empts_kind_check(self, api):
        """Same rule, mirror side: unresolvable to_region_id pre-empts
        the kind check."""
        # difficulty: priority_pair_validation_conflict/safety_vs_referential_dual_failure_on_transfer_dispatch
        r_real, r_real_bikes = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=999,
            available_count_override=4,
        )
        resp = api.create_transfer(
            create_transfer_payload(
                from_region_id=r_real["id"],
                to_region_id=NON_EXISTENT_UUID,
                bike_ids=[r_real_bikes[0]["id"]],
            ),
            OPERATOR,
        )
        validate_error(
            resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404,
        )


# ===========================================================================
# Rule 6: boundary_precision_check / daily_cap_inclusive_boundary_on_ride_end
# ===========================================================================
class TestDailyCapInclusiveBoundary:
    """SCAFFOLD_DIFFICULTY_DESIGN boundary_precision_check /
    daily_cap_inclusive_boundary_on_ride_end.

    PRD §3.4 pins inclusive >=: 'If base_fare_cents is greater than or
    equal to the applicable cap, it is clamped to the cap and the
    ride's settlement_variant is recorded as DAILY_CAP.'
    """

    def test_standard_cap_inclusive_at_42_minutes(self, api):
        """PRD §3.4 boundary: 42 chargeable on STANDARD = 30*30 + 12*50
        = 1500 (exact cap) → DAILY_CAP because >= is inclusive."""
        # difficulty: boundary_precision_check/daily_cap_inclusive_boundary_on_ride_end
        ctx = settle_simple_standard_ride(duration_minutes=42)
        ride = ctx["ride"]
        assert ride["base_fare_cents"] == 1500
        assert ride["settlement_variant"] == "DAILY_CAP"
        assert ride["final_fare_cents"] == 1500

    def test_standard_just_below_cap_is_per_minute_at_41_minutes(self, api):
        """PRD §3.4: 'otherwise base_fare_cents is left as computed and
        the variant is PER_MINUTE.' 41 chargeable = 30*30 + 11*50 =
        1450 < 1500 → PER_MINUTE."""
        # difficulty: boundary_precision_check/daily_cap_inclusive_boundary_on_ride_end
        ctx = settle_simple_standard_ride(duration_minutes=41)
        ride = ctx["ride"]
        assert ride["base_fare_cents"] == 1450
        assert ride["settlement_variant"] == "PER_MINUTE"


# ===========================================================================
# Rule 6: boundary_precision_check / loss_rate_zero_deployment_empty_set
# ===========================================================================
class TestLossRateEmptySetEdge:
    """SCAFFOLD_DIFFICULTY_DESIGN boundary_precision_check /
    loss_rate_zero_deployment_empty_set.

    PRD §3.11 backs the rule: 'If deployed_lifetime is 0, both reported
    ratios are 0.0.'
    """

    def test_zero_deployed_zero_ratios(self, api):
        """PRD §3.11: 'If deployed_lifetime is 0, both reported ratios
        are 0.0.'"""
        # difficulty: boundary_precision_check/loss_rate_zero_deployment_empty_set
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        out = get_region_loss_rate(region["id"])
        assert out["provisional_loss_rate"] == 0.0
        assert out["attributed_loss_rate"] == 0.0
        assert out["loss_count"] == 0
        assert out["deployed_lifetime"] == 0

    def test_zero_deployed_anomaly_false(self, api):
        """PRD §3.11: 'An anomaly flag is reported as true when
        provisional_loss_rate is strictly greater than ... 0.05.'
        Zero deployed → 0.0 → strictly not greater → anomaly false."""
        # difficulty: boundary_precision_check/loss_rate_zero_deployment_empty_set
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        out = get_region_loss_rate(region["id"])
        assert out["anomaly"] is False


# ===========================================================================
# Rule 7: cross_entity_state_dependency /
#         bike_on_shelf_requires_no_open_workorder
# ===========================================================================
class TestOnShelfRequiresNoOpenWorkorder:
    """SCAFFOLD_DIFFICULTY_DESIGN cross_entity_state_dependency /
    bike_on_shelf_requires_no_open_workorder.

    PRD §3.2 backs the rule: 'The bike must not have any WorkOrder
    whose status is OPEN or ASSIGNED — otherwise
    ERR_BIKE_HAS_OPEN_WORKORDER.'
    """

    def test_on_shelf_with_open_workorder_rejected(self, api):
        """PRD §3.2: 'The bike must not have any WorkOrder whose status
        is OPEN or ASSIGNED — otherwise ERR_BIKE_HAS_OPEN_WORKORDER.'"""
        # difficulty: cross_entity_state_dependency/bike_on_shelf_requires_no_open_workorder
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="STANDARD")
        # Open a WorkOrder while the bike is OFF_SHELF.
        create_workorder(bike_id=bike["id"], cause="RECALL",
                         category="OTHER", sla_minutes=60)
        # Attempt on-shelf
        resp = api.shelf_bike(
            region["id"], bike["id"], shelf_payload(action="ON"),
            OPERATOR,
        )
        validate_error(
            resp, ApiErrorId.ERR_BIKE_HAS_OPEN_WORKORDER.value, 409,
        )

    # DELETED: test_release_recall_with_open_workorder_rejected — PRD
    # §2.10 lists 'resource-state legality' BEFORE 'open-work-order
    # presence' in the validation order, and §3.6 requires
    # WorkOrder-creation to flip the bike to FAULT (so it leaves RECALL).
    # Under any PRD-faithful state machine, a bike can never be in
    # status=RECALL while also having an OPEN work order — recall
    # requires AVAILABLE and WorkOrder creation forces FAULT. The
    # release-recall WO-check rule is therefore unreachable through
    # PRD-defined transitions; STEP 1b unique derivability fails.


# ===========================================================================
# Rule 7: cross_entity_state_dependency /
#         transfer_dispatch_depends_on_region_density_posture
# ===========================================================================
class TestTransferDispatchDependsOnDensityPosture:
    """SCAFFOLD_DIFFICULTY_DESIGN cross_entity_state_dependency /
    transfer_dispatch_depends_on_region_density_posture.

    PRD §3.8 backs the rule: 'The transfer's frozen kind must still
    match current postures at dispatch time: REPLENISH requires the
    destination's density_posture to still be LOW; CLEARANCE requires
    the source's density_posture to still be HIGH — otherwise
    ERR_TRANSFER_KIND_MISMATCH.'
    """

    def test_replenish_dispatch_blocked_when_destination_no_longer_low(
        self, api,
    ):
        """PRD §3.8: 'REPLENISH requires the destination's
        density_posture to still be LOW.'"""
        # difficulty: cross_entity_state_dependency/transfer_dispatch_depends_on_region_density_posture
        # Build: LOW destination + HIGH source, plan a REPLENISH, then
        # bring destination out of LOW before dispatch.
        r_low, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        # Plan transfer (kind frozen = REPLENISH)
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_low["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        assert t["kind"] == "REPLENISH"
        # Push r_low above LOW by deploying additional bikes
        for _ in range(5):
            b = create_bike(model="STANDARD")
            shelf_bike_on(r_low["id"], b["id"])
        r_low_after = get_region(r_low["id"])
        assert r_low_after["density_posture"] != "LOW"
        # Dispatch should now fail
        resp = api.dispatch_transfer(t["id"], OPERATOR)
        validate_error(
            resp, ApiErrorId.ERR_TRANSFER_KIND_MISMATCH.value, 409,
        )

    def test_clearance_dispatch_blocked_when_source_no_longer_high(
        self, api,
    ):
        """PRD §3.8: 'CLEARANCE requires the source's density_posture
        to still be HIGH.'"""
        # difficulty: cross_entity_state_dependency/transfer_dispatch_depends_on_region_density_posture
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        r_dst, _ = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=10,
            available_count_override=5,
        )
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_dst["id"],
            bike_ids=[src_bikes[0]["id"]],
        )
        assert t["kind"] == "CLEARANCE"
        # Take 2 bikes off-shelf at the source to drop posture below HIGH:
        # 6 available, drop 2 → 4 < 5 high threshold → NORMAL
        for b in src_bikes[1:3]:
            shelf_bike_off(r_src["id"], b["id"])
        r_src_after = get_region(r_src["id"])
        assert r_src_after["density_posture"] != "HIGH"
        resp = api.dispatch_transfer(t["id"], OPERATOR)
        validate_error(
            resp, ApiErrorId.ERR_TRANSFER_KIND_MISMATCH.value, 409,
        )


# ===========================================================================
# Rule 8: resource_temporal_overlap / rider_at_most_one_active_ride
# ===========================================================================
class TestRiderSingleActiveRide:
    """SCAFFOLD_DIFFICULTY_DESIGN resource_temporal_overlap /
    rider_at_most_one_active_ride.

    PRD §3.4 backs the rule: 'The rider must be ACTIVE and must have
    no other ACTIVE Ride — otherwise ERR_RIDER_HAS_ACTIVE_RIDE.'
    """

    def test_second_concurrent_ride_attempt_rejected(self, api):
        """PRD §3.4: 'The rider must be ACTIVE and must have no other
        ACTIVE Ride — otherwise ERR_RIDER_HAS_ACTIVE_RIDE.'"""
        # difficulty: resource_temporal_overlap/rider_at_most_one_active_ride
        region, bikes = setup_region_with_bikes(num_bikes=2)
        rider = create_funded_rider()
        start_ride(rider, bikes[0])
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bikes[1]["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_RIDER_HAS_ACTIVE_RIDE.value, 409,
        )

    def test_new_ride_after_ending_previous_succeeds(self, api):
        """PRD §3.4: implicit corollary — once the prior ride is no
        longer ACTIVE the constraint releases."""
        # difficulty: resource_temporal_overlap/rider_at_most_one_active_ride
        region, bikes = setup_region_with_bikes(num_bikes=2)
        rider = create_funded_rider()
        ride1 = start_ride(rider, bikes[0])
        end_ride(ride1, end_lat=10.0, end_lng=10.0, rider_id=rider["id"])
        # Now start a new ride on a different bike
        ride2 = start_ride(rider, bikes[1])
        assert ride2["status"] == "ACTIVE"


# ===========================================================================
# Rule 8: resource_temporal_overlap /
#         bike_single_concurrent_rider_with_buffer_of_zero
# ===========================================================================
class TestBikeSingleConcurrentRider:
    """SCAFFOLD_DIFFICULTY_DESIGN resource_temporal_overlap /
    bike_single_concurrent_rider_with_buffer_of_zero.

    PRD §3.13 backs the rule: 'Two riders attempting to unlock the
    same AVAILABLE bike at the same moment: at most one ride is
    created.'
    """

    def test_only_one_rider_can_hold_bike_at_a_time(self, api):
        """PRD §3.4 + §3.13: a second rider attempting on an IN_USE
        bike is rejected with ERR_BIKE_NOT_AVAILABLE."""
        # difficulty: resource_temporal_overlap/bike_single_concurrent_rider_with_buffer_of_zero
        region, bikes = setup_region_with_bikes(num_bikes=1)
        rider_a = create_funded_rider()
        rider_b = create_funded_rider()
        start_ride(rider_a, bikes[0])
        resp = api.create_ride(
            create_ride_payload(rider_id=rider_b["id"],
                                bike_id=bikes[0]["id"]),
            make_rider_headers(rider_b["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409,
        )

    def test_two_concurrent_unlocks_one_wins(self, api):
        """PRD §3.13: 'at most one ride is created' — concurrent path."""
        # difficulty: resource_temporal_overlap/bike_single_concurrent_rider_with_buffer_of_zero
        from test_helpers import run_race
        region, bikes = setup_region_with_bikes(num_bikes=1)
        rider_a = create_funded_rider()
        rider_b = create_funded_rider()
        bike = bikes[0]

        def call_a():
            return api.create_ride(
                create_ride_payload(rider_id=rider_a["id"],
                                    bike_id=bike["id"]),
                make_rider_headers(rider_a["id"]),
            )

        def call_b():
            return api.create_ride(
                create_ride_payload(rider_id=rider_b["id"],
                                    bike_id=bike["id"]),
                make_rider_headers(rider_b["id"]),
            )

        results = run_race(call_a, call_b)
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1
        assert len(failures) == 1
        validate_error(
            failures[0], ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409,
        )


# ===========================================================================
# Rule 9: compensating_invariant / wallet_invariant_under_dispute_and_adjust
# ===========================================================================
class TestWalletInvariantUnderDisputeAndAdjust:
    """SCAFFOLD_DIFFICULTY_DESIGN compensating_invariant /
    wallet_invariant_under_dispute_and_adjust.

    PRD §3.10 backs the rule: 'On success the difference (current
    final_fare_cents minus new_final_fare_cents) is credited back to
    the rider's wallet_balance_cents.' Identity adjustment (new =
    current) means refund = 0 → wallet unchanged.
    """

    def test_identity_adjust_leaves_wallet_unchanged(self, api):
        """PRD §3.10: 'On success the difference (current
        final_fare_cents minus new_final_fare_cents) is credited back.'
        new = original → difference 0 → wallet unchanged."""
        # difficulty: compensating_invariant/wallet_invariant_under_dispute_and_adjust
        from test_helpers import adjust_ride
        ctx = settle_simple_standard_ride(duration_minutes=20)
        # Settled fare = 600
        wallet_after_settle = get_rider(
            ctx["rider"]["id"],
        )["wallet_balance_cents"]
        assert wallet_after_settle == 10000 - 600
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        adjust_ride(ctx["ride"]["id"], new_final_fare_cents=600)
        wallet_final = get_rider(
            ctx["rider"]["id"],
        )["wallet_balance_cents"]
        assert wallet_final == wallet_after_settle, (
            "PRD §3.10: identity adjust (new=current) → refund=0 → "
            "wallet unchanged"
        )

    def test_partial_adjust_credits_exact_difference(self, api):
        """PRD §3.10: 'the difference ... is credited back to the
        rider's wallet_balance_cents.' Verify the exact difference."""
        # difficulty: compensating_invariant/wallet_invariant_under_dispute_and_adjust
        from test_helpers import adjust_ride
        ctx = settle_simple_standard_ride(duration_minutes=20)
        wallet_after_settle = get_rider(
            ctx["rider"]["id"],
        )["wallet_balance_cents"]
        # final_fare_cents = 600 after 20 min STANDARD; adjust to 250
        dispute_ride(ctx["ride"], rider_id=ctx["rider"]["id"])
        adjust_ride(ctx["ride"]["id"], new_final_fare_cents=250)
        # Refund = 600 - 250 = 350
        wallet_final = get_rider(
            ctx["rider"]["id"],
        )["wallet_balance_cents"]
        assert wallet_final == wallet_after_settle + 350


# ===========================================================================
# Rule 9: compensating_invariant /
#         deployed_count_invariant_under_transfer_cancel_in_transit
# ===========================================================================
class TestDeployedCountUnderTransferCancelInTransit:
    """SCAFFOLD_DIFFICULTY_DESIGN compensating_invariant /
    deployed_count_invariant_under_transfer_cancel_in_transit.

    PRD §3.8 backs the rule: 'Cancelling an IN_TRANSIT transfer
    restores each bike's region_id to from_region_id, shelf_state to
    ON_SHELF, and status to AVAILABLE, then recomputes the source
    region's counts and density_posture.'
    """

    def test_dispatch_then_cancel_restores_source_deployed_count(self, api):
        """PRD §3.8: dispatch removes bikes from source; in-transit
        cancel restores them — source.deployed_count must equal the
        pre-dispatch value."""
        # difficulty: compensating_invariant/deployed_count_invariant_under_transfer_cancel_in_transit
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        r_dst, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        # snapshot pre-dispatch
        before = get_region(r_src["id"])
        assert before["deployed_count"] == 6
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_dst["id"],
            bike_ids=[b["id"] for b in src_bikes[:3]],
        )
        dispatch_transfer(t["id"])
        mid = get_region(r_src["id"])
        assert mid["deployed_count"] == 3, (
            "PRD §3.8: dispatch removes bikes from source"
        )
        cancel_transfer(t["id"])
        after = get_region(r_src["id"])
        assert after["deployed_count"] == 6, (
            "PRD §3.8: in-transit cancel restores bikes to source"
        )

    def test_each_bike_restored_to_on_shelf_available_at_source(self, api):
        """PRD §3.8: 'Cancelling an IN_TRANSIT transfer restores each
        bike's region_id to from_region_id, shelf_state to ON_SHELF,
        and status to AVAILABLE.'"""
        # difficulty: compensating_invariant/deployed_count_invariant_under_transfer_cancel_in_transit
        r_src, src_bikes = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=0, high_density_threshold=5,
            available_count_override=6,
        )
        r_dst, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=4, high_density_threshold=10,
            available_count_override=2,
        )
        bike_ids = [b["id"] for b in src_bikes[:3]]
        t = create_transfer(
            from_region_id=r_src["id"], to_region_id=r_dst["id"],
            bike_ids=bike_ids,
        )
        dispatch_transfer(t["id"])
        cancel_transfer(t["id"])
        for bid in bike_ids:
            b = get_bike(bid)
            assert b["region_id"] == r_src["id"]
            assert b["shelf_state"] == "ON_SHELF"
            assert b["status"] == "AVAILABLE"
