"""Tournament settlement calculation: FCR variants, provisional vs final,
tiered formula, group averages, and OCC on recompute (PRD §3.5, §3.7, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_settlement,
    create_catch_crew_payload,
    create_contract_payload,
    create_grower_payload,
    create_settlement_group_payload,
    get_settlement_for_flock,
    get_success_data,
    harvest_tournament_flock,
    lock_group,
    place_flock,
    plan_flock,
    preview_settlement,
    record_feed,
    record_weight_ticket,
    schedule_catch,
    set_logical_clock,
    setup_harvested_flock,
    setup_two_grower_tournament,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
LIVEHAUL = TEST_USERS["livehaul_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestFcrRawVsAdjustedVariants:
    """Flock: 5000 head, 10000 lbs feed, 5000 lbs live weight, harvested."""

    def test_adjusted_fcr_subtracts_waste_credit(self, api):
        """PRD §3.5: "The adjusted ratio — the one that actually feeds the
        tournament — subtracts a standard feed-waste credit of 2,000 pounds
        from the delivered total before dividing by `live_weight_lbs`,
        recognizing that some feed is always lost to spillage and cleanout
        rather than consumed by birds."

        Design: Difficulty/dual_variant_calc/fcr_raw_vs_adjusted_variants_diverge
        """
        ctx = setup_harvested_flock(
            grower_code="G-FCR", full_name="FCR Grower", contract_no="C-FCR",
            group_code="WK-33", week_ending_date="2026-09-19", flock_no="F-FCR",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-FCR",
            weight_ticket_no="WT-FCR1")
        flock = ctx["flock"]
        assert flock["status"] == "HARVESTED"
        # (10000 - 2000) / 5000 = 1.6 — not the raw 10000 / 5000 = 2.0.
        assert flock["adj_fcr"] == pytest.approx(1.6, abs=1e-9)

    def test_persisted_adj_fcr_differs_from_raw_variant(self, api):
        """PRD §3.5: "Both the raw and adjusted values are rounded half-up to
        4 decimal places; the raw value exists for diagnostic reporting only
        and is strictly greater than the adjusted value whenever any delivery
        exists."
        PRD §3.5: "The adjusted ratio — the one that actually feeds the
        tournament — subtracts a standard feed-waste credit of 2,000 pounds
        from the delivered total before dividing by `live_weight_lbs`".

        Design: Difficulty/dual_variant_calc/fcr_raw_vs_adjusted_variants_diverge
        """
        ctx = setup_harvested_flock(
            grower_code="G-FCR", full_name="FCR Grower", contract_no="C-FCR",
            group_code="WK-33", week_ending_date="2026-09-19", flock_no="F-FCR",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-FCR",
            weight_ticket_no="WT-FCR1")
        raw_variant = 10000 / 5000  # 2.0
        adjusted = ctx["flock"]["adj_fcr"]
        assert adjusted == pytest.approx(1.6, abs=1e-9)
        assert adjusted < raw_variant, \
            "the persisted adj_fcr must use the waste-credit variant"


class TestProvisionalVsFinalAmountsDiverge:
    def test_provisional_amounts_while_second_member_still_growing(self, api):
        """PRD §3.7: "While the group is `OPEN`, a `SettlementAnalyst` may
        compute a provisional settlement for a harvested flock. This operation
        creates the flock's `Settlement` row in `PENDING` status with `variant`
        `PROVISIONAL` if none exists, or recomputes the amounts on the existing
        row."
        PRD §3.8: "A provisional computation ranks the flock over the
        currently-harvested members only, so provisional and final amounts
        differ whenever another member harvests after the preview."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_amounts_diverge
        """
        ctx = setup_two_grower_tournament()
        harvest_tournament_flock(ctx, "a")  # B still GROWING at preview time

        provisional = preview_settlement(ctx["flock_a"]["id"])
        assert_settlement(provisional)
        assert provisional["variant"] == "PROVISIONAL"
        assert provisional["status"] == "PENDING"
        # Sole harvested member: rank_pct 0 -> base 6 c/lb * 50000 = 300000;
        # adj_fcr 1.96 == group avg 1.96 -> bonus 0.25 c/lb = 12500;
        # condemnation 40/9700 under the 0.005 allowance -> 0;
        # repayment min(round(312500 * 0.15), 120000) = 46875.
        assert provisional["base_amount_cents"] == 300000
        assert provisional["fcr_bonus_cents"] == 12500
        assert provisional["condemnation_deduction_cents"] == 0
        assert provisional["loan_repayment_cents"] == 46875
        assert provisional["net_amount_cents"] == 265625

    def test_final_amounts_after_all_members_harvest_and_lock(self, api):
        """PRD §3.7: "on lock, every `PENDING` settlement in the group is
        recomputed per the full settlement-amount calculation and its `variant`
        is flipped from `PROVISIONAL` to `FINAL`."
        PRD §3.8: "A provisional computation ranks the flock over the
        currently-harvested members only, so provisional and final amounts
        differ whenever another member harvests after the preview."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_amounts_diverge
        """
        ctx = setup_two_grower_tournament()
        harvest_tournament_flock(ctx, "a")
        provisional = preview_settlement(ctx["flock_a"]["id"])

        harvest_tournament_flock(ctx, "b")
        lock_group(ctx["group"]["id"])

        finals = get_settlement_for_flock(ctx["flock_a"]["id"])
        assert len(finals) == 1
        final = finals[0]
        assert_settlement(final)
        assert final["variant"] == "FINAL"
        assert final["rank_position"] == 1
        # Two harvested members: flock A ranks 1 of 2 -> rank_pct 0.5 ->
        # uplift 0.8 -> base 6.8 c/lb * 50000 = 340000; bonus still 12500;
        # repayment min(round(352500 * 0.15), 120000) = 52875.
        assert final["base_amount_cents"] == 340000
        assert final["fcr_bonus_cents"] == 12500
        assert final["condemnation_deduction_cents"] == 0
        assert final["loan_repayment_cents"] == 52875
        assert final["net_amount_cents"] == 299625
        assert provisional["net_amount_cents"] != final["net_amount_cents"], \
            "identical flock data must price differently once the group fills in"


class TestTieredFormula:
    """Same two-grower tournament, fully harvested and locked before reading."""

    def _locked_final_settlement_a(self, api):
        ctx = setup_two_grower_tournament()
        harvest_tournament_flock(ctx, "a")
        harvest_tournament_flock(ctx, "b")
        preview_settlement(ctx["flock_a"]["id"])
        lock_group(ctx["group"]["id"])
        settlements = get_settlement_for_flock(ctx["flock_a"]["id"])
        assert len(settlements) == 1
        return settlements[0]

    def test_tier_bonus_and_deduction_lines(self, api):
        """PRD §3.8: "The base pay rate is the contract's
        `base_pay_cents_per_lb` plus a tier uplift in cents per pound: 1.5
        cents when the percentile is at least 0.75, otherwise 0.8 cents when it
        is at least 0.50, otherwise 0.2 cents when it is at least 0.25,
        otherwise nothing."
        PRD §3.8: "`fcr_bonus_cents` is the flock's `live_weight_lbs`
        multiplied by a per-pound bonus of 0.5 cents when the flock's `adj_fcr`
        is at or below 98 percent of the group average, or 0.25 cents when it
        is merely at or below the group average, or zero otherwise — again
        rounded half-up to whole cents."
        PRD §3.8: "A flock at or under the allowance has no excess and no
        deduction."

        Design: Difficulty/combinatorial_formula/tournament_settlement_tiered_formula_mode_a
        """
        final = self._locked_final_settlement_a(api)
        assert_settlement(final)
        assert final["variant"] == "FINAL"
        assert final["rank_position"] == 1
        # rank 1 of 2 -> rank_pct 0.5 -> uplift 0.8 -> 6.8 c/lb * 50000.
        assert final["base_amount_cents"] == 340000
        # adj_fcr 1.96 <= group avg 1.98 but > 1.98 * 0.98 -> 0.25 c/lb.
        assert final["fcr_bonus_cents"] == 12500
        # 40/9700 ≈ 0.0041 is under the 0.005 allowance -> no deduction.
        assert final["condemnation_deduction_cents"] == 0

    def test_repayment_min_rule_and_net(self, api):
        """PRD §3.8: "When that subtotal is positive, the settlement diverts a
        share to loan repayment: `loan_repayment_cents` is the smaller of the
        subtotal multiplied by the loan's `recovery_pct` divided by 100
        (rounded half-up to whole cents) and the sum of `outstanding_cents`
        across the grower's loans still in `ISSUED` status."
        PRD §3.8: "The `net_amount_cents` is the positive subtotal minus the
        repayment."

        Design: Difficulty/combinatorial_formula/tournament_settlement_tiered_formula_mode_a
        """
        final = self._locked_final_settlement_a(api)
        # positive_subtotal 352500 -> min(round(352500 * 15 / 100), 120000)
        # = min(52875, 120000) = 52875.
        assert final["loan_repayment_cents"] == 52875
        assert final["net_amount_cents"] == 299625


class TestGroupAverages:
    def test_group_averages_exclude_non_harvested_members(self, api):
        """PRD §3.7: "the group maintains three running averages over its
        member flocks that have reached `HARVESTED` or `SETTLED`:
        `group_avg_fcr` (the mean of member `adj_fcr`),
        `group_avg_livability_pct`, and `group_avg_condemnation_pct`. These
        averages are recomputed on each member's harvest and start null while
        no member has harvested."

        Design: Corner/calculations/group_averages_exclude_non_harvested_members
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-AV",
                                                    full_name="Average Grower"),
                              ADMIN))
        house1 = get_success_data(
            api.create_house({"grower_id": grower["id"], "house_no": "H1",
                              "capacity_birds": 9000}, ADMIN))
        house2 = get_success_data(
            api.create_house({"grower_id": grower["id"], "house_no": "H2",
                              "capacity_birds": 9000}, ADMIN))
        contract = get_success_data(
            api.create_contract(
                create_contract_payload(grower["id"], contract_no="C-AV",
                                        committed_house_count=2), ADMIN))
        get_success_data(api.activate_contract(contract["id"], ADMIN))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-AV",
                                                week_ending_date="2026-12-31"),
                ANALYST))
        flock1 = plan_flock(house1["id"], contract["id"], group["id"], "F-AV1")
        flock2 = plan_flock(house2["id"], contract["id"], group["id"], "F-AV2")
        place_flock(flock1["id"], "2026-08-01", 5000)
        place_flock(flock2["id"], "2026-08-01", 5000)
        record_feed(flock1["id"], 10000, "2026-08-05", "STARTER", "FT-AV1")
        # The second flock posts feed (GROWING) but never harvests.
        record_feed(flock2["id"], 99000, "2026-08-05", "STARTER", "FT-AV2")
        crew = get_success_data(
            api.create_catch_crew(
                create_catch_crew_payload(crew_code="CREW-AV",
                                          max_catches_per_day=2), LIVEHAUL))
        set_logical_clock("2026-09-10T00:00:00Z")
        schedule = schedule_catch(flock1["id"], crew["id"], "2026-09-10")
        record_weight_ticket(flock1["id"], "WT-AV1", "2026-09-10T08:00:00Z",
                             5000)
        get_success_data(api.complete_catch(schedule["id"], LIVEHAUL))

        group_data = validate_success(
            api.get_settlement_group(group["id"], ANALYST))
        # Only the HARVESTED flock counts: (10000 - 2000) / 5000 = 1.6.
        assert group_data["group_avg_fcr"] == pytest.approx(1.6, abs=1e-9), \
            "the GROWING member with 99000 lbs feed posted must not move the average"


class TestSettlementReverseReachability:
    def test_flock_settlement_list_empty_then_singleton(self, api):
        """PRD §3.7: "While the group is `OPEN`, a `SettlementAnalyst` may
        compute a provisional settlement for a harvested flock. This operation
        creates the flock's `Settlement` row in `PENDING` status with `variant`
        `PROVISIONAL` if none exists, or recomputes the amounts on the existing
        row."

        Design: Corner/endpoints/flock_settlement_reverse_reachability
        """
        ctx = setup_harvested_flock(grower_code="G-E1", full_name="Endpoint One",
                                    contract_no="C-E1", group_code="WK-E1",
                                    flock_no="F-E1",
                                    set_clock_to="2026-08-01T00:00:00Z",
                                    crew_code="CREW-E1", weight_ticket_no="WT-E1")

        before = get_settlement_for_flock(ctx["flock"]["id"])
        assert before == [], "no settlement row exists before the first recompute"

        preview_settlement(ctx["flock"]["id"])
        after = get_settlement_for_flock(ctx["flock"]["id"])
        assert len(after) == 1
        assert_settlement(after[0])
        assert after[0]["variant"] == "PROVISIONAL"
        assert after[0]["status"] == "PENDING"


class TestOccStaleFlockVersionOnRecompute:
    def _setup_harvested(self, api):
        return setup_harvested_flock(
            grower_code="G-OCC1", full_name="Occ One", contract_no="C-OCC1",
            group_code="WK-OCC1", flock_no="F-OCC1",
            set_clock_to="2026-08-01T00:00:00Z", crew_code="CREW-OCC1",
            weight_ticket_no="WT-OCC1")

    def test_stale_flock_version_rejected(self, api, analyst_headers):
        """PRD §2.7: "If the flock's current `version` has advanced since that
        observation (for example because a weight ticket was just posted,
        changing `live_weight_lbs` and therefore the harvest-time
        calculations), the request is rejected with `ERR_STALE_FLOCK_VERSION`
        (HTTP 412) and the client must re-read the flock and retry with the
        fresh version."
        PRD §3.5: "Every ticket adds its `live_weight_lbs` into the flock's
        aggregate `live_weight_lbs` and increments the flock's `version`".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_flock_version_on_recompute
        """
        ctx = self._setup_harvested(api)
        flock_id = ctx["flock"]["id"]
        observed_version = validate_success(
            api.get_flock(flock_id, analyst_headers))["version"]
        # A late weight ticket advances the flock's version.
        record_weight_ticket(flock_id, "WT-OCC2", "2026-09-10T09:00:00Z", 1000)

        resp = api.recompute_settlement(
            flock_id, {"expected_flock_version": observed_version},
            analyst_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_FLOCK_VERSION)

    def test_fresh_version_retry_succeeds_with_updated_amounts(
            self, api, analyst_headers):
        """PRD §2.7: "If the flock's current `version` has advanced since that
        observation (for example because a weight ticket was just posted,
        changing `live_weight_lbs` and therefore the harvest-time
        calculations), the request is rejected with `ERR_STALE_FLOCK_VERSION`
        (HTTP 412) and the client must re-read the flock and retry with the
        fresh version."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_flock_version_on_recompute
        """
        ctx = self._setup_harvested(api)
        flock_id = ctx["flock"]["id"]
        observed_version = validate_success(
            api.get_flock(flock_id, analyst_headers))["version"]
        record_weight_ticket(flock_id, "WT-OCC2", "2026-09-10T09:00:00Z", 1000)
        validate_error(
            api.recompute_settlement(
                flock_id, {"expected_flock_version": observed_version},
                analyst_headers),
            ApiErrorId.ERR_STALE_FLOCK_VERSION)

        fresh_version = validate_success(
            api.get_flock(flock_id, analyst_headers))["version"]
        settlement = validate_success(
            api.recompute_settlement(
                flock_id, {"expected_flock_version": fresh_version},
                analyst_headers))
        assert_settlement(settlement)
        # live_weight now 6000: base 6 c/lb * 6000 = 36000; single-member
        # group (adj_fcr == group average) -> bonus 0.25 c/lb = 1500.
        assert settlement["net_amount_cents"] == 37500
