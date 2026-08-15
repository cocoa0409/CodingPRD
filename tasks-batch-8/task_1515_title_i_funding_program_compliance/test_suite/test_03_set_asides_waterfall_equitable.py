"""Set-aside minimums, the equitable-services share variants, and the
school-allocation waterfall (PRD §3.3, §3.4)."""

from test_helpers import (
    ALLOC_AMOUNTS_VERIFIED,
    PER_PUPIL_VERIFIED,
    SCHOOL_POOL_VERIFIED,
    ApiErrorId,
    api_client,
    assert_set_aside,
    build_user_headers,
    finalize_allocations,
    get_allocation_for,
    list_set_asides_for,
    setup_allocated,
    setup_equitable_scenario,
    setup_ranking_locked,
    validate_error,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")


class TestSetAsideMinimums:

    def test_set_aside_floor_and_threshold_interaction(self):
        """PRD §3.4: "The `PARENT_ENGAGEMENT` minimum is one percent of the
        grant's `total_allocation_cents`, rounded half up to a whole cent —
        but only when `total_allocation_cents` is strictly greater than
        $500,000.00; a grant at or below that threshold has a
        parent-engagement minimum of zero."
        PRD §3.4: "The `HOMELESS_SERVICES` minimum is the greater of a
        $5,000.00 floor and one-half of one percent of `net_allocable_cents`,
        the rate portion rounded half up to a whole cent."
        PRD §3.4: "The `PROFESSIONAL_DEVELOPMENT` minimum is five percent of
        `net_allocable_cents`, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/set_aside_floor_and_threshold_interaction
        """
        # At exactly $500,000.00 the parent-engagement minimum stays zero.
        ctx2 = setup_allocated(2028, [(40, 100)],
                               total_allocation_cents=50_000_000)
        sa2 = ctx2["set_asides"]
        assert sa2["PARENT_ENGAGEMENT"]["minimum_cents"] == 0, \
            "total == 50000000 is NOT strictly greater than the threshold"
        assert sa2["HOMELESS_SERVICES"]["minimum_cents"] == 500_000, \
            "the $5,000.00 floor beats 0.5% of net (250000)"
        assert sa2["PROFESSIONAL_DEVELOPMENT"]["minimum_cents"] == 2_500_000

        # One dollar over the threshold turns the one-percent rule on.
        # The second grant reuses the first scenario's roster: nces_id is
        # unique and every certified snapshot must cover every active school
        # exactly once (PRD §3.2).
        ctx2b = setup_allocated(2034, [(40, 100)],
                                total_allocation_cents=50_000_100,
                                schools=ctx2["schools"])
        sa2b = ctx2b["set_asides"]
        assert sa2b["PARENT_ENGAGEMENT"]["minimum_cents"] == 500_001, \
            "round_half_up(0.01 * 50000100)"
        assert sa2b["HOMELESS_SERVICES"]["minimum_cents"] == 500_000, \
            "floor still beats round_half_up(0.005 * 50000100) == 250001"
        assert sa2b["PROFESSIONAL_DEVELOPMENT"]["minimum_cents"] == 2_500_005

    def test_set_asides_initialized_to_minimum_and_share_zero(self):
        """PRD §3.4: "Finalization creates four `SetAside` rows for the grant,
        one per `category`: `PARENT_ENGAGEMENT`, `HOMELESS_SERVICES`,
        `PROFESSIONAL_DEVELOPMENT`, and `EQUITABLE_SERVICES`. Each row's
        `minimum_cents` is the regulatory floor, and its `reserved_cents` is
        initialized to that floor"
        PRD §3.4: "The `EQUITABLE_SERVICES` minimum is then the residual base
        multiplied by the private count and divided by the sum of the public
        and private counts, rounded half up to a whole cent; when the private
        count is zero, the minimum is zero."

        Design: Difficulty/combinatorial_formula/set_aside_floor_and_threshold_interaction
        """
        ctx = setup_allocated(2035, [(40, 100)],
                              total_allocation_cents=50_000_000)
        rows = list_set_asides_for(ctx["grant"]["id"])
        assert sorted(r["category"] for r in rows) == [
            "EQUITABLE_SERVICES", "HOMELESS_SERVICES", "PARENT_ENGAGEMENT",
            "PROFESSIONAL_DEVELOPMENT"]
        for row in rows:
            assert_set_aside(row)
            assert row["reserved_cents"] == row["minimum_cents"], \
                "reserved_cents is initialized to the floor at finalization"
        # No private schools exist, so the private count is zero.
        assert ctx["set_asides"]["EQUITABLE_SERVICES"]["minimum_cents"] == 0

    def test_pe_school_distribution_recompute_on_adjust(self):
        """PRD §3.4: "The `PARENT_ENGAGEMENT` row carries one further derived
        field: `school_distributed_minimum_cents`, ninety percent of its
        `reserved_cents` rounded half up to a whole cent — the share that must
        flow down to schools rather than stay at the district level. For the
        other three categories this field is always zero. It is recomputed
        every time `reserved_cents` changes, whether through a set-aside
        adjustment or through an amendment approval or void that touches the
        parent-engagement row."

        Design: Corner/calculations/pe_school_distribution_recompute_on_adjust
        """
        # total 60,000,000 > $500,000.00 threshold: PE min = 1% = 600,000.
        ctx = setup_allocated(2061, [(100, 100)],
                              total_allocation_cents=60_000_000)
        pe = ctx["set_asides"]["PARENT_ENGAGEMENT"]
        assert pe["minimum_cents"] == 600_000
        assert pe["reserved_cents"] == 600_000
        assert pe["school_distributed_minimum_cents"] == 540_000, \
            "round_half_up(0.90 * 600000)"
        adjusted = validate_success(api_client.adjust_set_aside(
            pe["id"], {"reserved_cents": 800_000}, DIRECTOR))
        assert adjusted["reserved_cents"] == 800_000
        assert adjusted["school_distributed_minimum_cents"] == 720_000, \
            "recomputed on adjust: round_half_up(0.90 * 800000)"
        for category, row in ctx["set_asides"].items():
            if category != "PARENT_ENGAGEMENT":
                fresh = validate_success(
                    api_client.get_set_aside(row["id"], DIRECTOR))
                assert fresh["school_distributed_minimum_cents"] == 0

    def test_set_aside_below_minimum_rejected(self):
        """PRD §3.4: "After finalization, the director may adjust any
        set-aside by supplying a new `reserved_cents` — upward without bound,
        downward only to the floor: a value below `minimum_cents` is rejected
        with `ERR_SET_ASIDE_BELOW_MINIMUM`."

        Design: Corner/errors/set_aside_below_minimum_rejected
        """
        # PD minimum: five percent of net 10,000,000 == 500,000.
        ctx = setup_allocated(2089, [(100, 100)],
                              total_allocation_cents=10_000_000)
        pd = ctx["set_asides"]["PROFESSIONAL_DEVELOPMENT"]
        assert pd["minimum_cents"] == 500_000
        resp = api_client.adjust_set_aside(pd["id"],
                                           {"reserved_cents": 499_999},
                                           DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SET_ASIDE_BELOW_MINIMUM)
        ok = validate_success(api_client.adjust_set_aside(
            pd["id"], {"reserved_cents": 500_000}, DIRECTOR))
        assert ok["reserved_cents"] == 500_000, \
            "the floor is inclusive: exactly the minimum is allowed"


class TestEquitableShareVariants:

    def test_equitable_share_variant_divergence(self):
        """PRD §3.4: "Second, the private-school low-income count is
        determined by the grant's `equitable_count_method`: under
        `CONSULTATION_AGREED` it is the sum of `agreed_low_income_count`
        across this grant's consultations in `AFFIRMATION_SIGNED` status, with
        unsigned consultations contributing zero; under `VERIFIED_COUNT` it is
        the sum of `low_income_resident_count` across all private schools with
        `nonprofit_verified` set, consultation status irrelevant."
        PRD §3.4: "The `EQUITABLE_SERVICES` minimum is then the residual base
        multiplied by the private count and divided by the sum of the public
        and private counts, rounded half up to a whole cent; when the private
        count is zero, the minimum is zero."

        Design: Difficulty/dual_variant_calc/equitable_share_variant_divergence
        """
        verified_ctx = setup_equitable_scenario(
            fiscal_year=2027, equitable_count_method="VERIFIED_COUNT")
        agreed_ctx = setup_equitable_scenario(
            fiscal_year=2032, equitable_count_method="CONSULTATION_AGREED",
            signed_agreed_counts=[55, 30], registry=verified_ctx)
        eq_v = verified_ctx["set_asides"]["EQUITABLE_SERVICES"]
        eq_c = agreed_ctx["set_asides"]["EQUITABLE_SERVICES"]
        # Identical financial inputs (total 100,000,000, reserve 5,000,000,
        # same four schools); only the count-method variant differs.
        # P = 95,000,000 - 6,250,000 = 88,750,000; LIpub = 1,095.
        assert eq_v["minimum_cents"] == 6_042_553, \
            "VERIFIED_COUNT: round_half_up(88750000 * 80 / 1175)"
        assert eq_c["minimum_cents"] == 6_393_008, \
            "CONSULTATION_AGREED: round_half_up(88750000 * 85 / 1180)"
        assert eq_v["reserved_cents"] == eq_v["minimum_cents"]
        assert eq_c["reserved_cents"] == eq_c["minimum_cents"]
        assert eq_v["minimum_cents"] != eq_c["minimum_cents"], \
            "the variant choice alone moves the minimum"

    def test_verified_count_ignores_signed_agreements(self):
        """PRD §3.4: "under `VERIFIED_COUNT` it is the sum of
        `low_income_resident_count` across all private schools with
        `nonprofit_verified` set, consultation status irrelevant."

        Design: Difficulty/dual_variant_calc/equitable_share_variant_divergence
        """
        # A VERIFIED_COUNT grant with signed consultations on record (agreed
        # counts 55 and 30) must still use the resident counts 50 + 30 = 80.
        ctx = setup_equitable_scenario(
            fiscal_year=2036, equitable_count_method="VERIFIED_COUNT",
            signed_agreed_counts=[55, 30])
        eq = ctx["set_asides"]["EQUITABLE_SERVICES"]
        assert eq["minimum_cents"] == 6_042_553, (
            "signed agreed counts (85) are irrelevant under VERIFIED_COUNT; "
            "the resident counts (80) drive round_half_up(88750000*80/1175)"
        )


class TestEquitableShareEvaluationOrder:

    def test_equitable_share_evaluation_order_pinned(self):
        """PRD §3.4: "The share is deliberately computed on the residual base
        — net of the three non-equitable set-asides — not on
        `net_allocable_cents` directly and not on the post-share school pool."

        Design: Difficulty/combinatorial_formula/equitable_share_evaluation_order_pinned
        """
        ctx = setup_equitable_scenario(fiscal_year=2027,
                                       equitable_count_method="VERIFIED_COUNT")
        eq = ctx["set_asides"]["EQUITABLE_SERVICES"]
        # Residual base P = 95,000,000 - (1,000,000 + 500,000 + 4,750,000)
        # = 88,750,000; share = round_half_up(88,750,000 * 80 / 1,175).
        assert eq["minimum_cents"] == 6_042_553
        assert eq["minimum_cents"] != 6_468_085, (
            "6,468,085 is the value the wrong order (share computed on "
            "net_allocable_cents directly) would produce"
        )

    def test_evaluation_order_pins_the_school_pool(self):
        """PRD §3.4: "The school pool is the residual base minus the
        equitable-services minimum. The share is deliberately computed on the
        residual base — net of the three non-equitable set-asides — not on
        `net_allocable_cents` directly and not on the post-share school pool."
        PRD §3.4: "when the private count is zero, the minimum is zero."

        Design: Difficulty/combinatorial_formula/equitable_share_evaluation_order_pinned
        """
        # No private schools registered: share is zero and the whole residual
        # base flows to the two served schools.
        ctx = setup_allocated(
            2038, [(400, 500), (195, 500)],
            total_allocation_cents=100_000_000, admin_reserve_cents=5_000_000,
            equitable_count_method="VERIFIED_COUNT")
        assert ctx["set_asides"]["EQUITABLE_SERVICES"]["minimum_cents"] == 0
        total_distributed = sum(
            a["allocation_amount_cents"] for a in ctx["allocations"].values())
        # school pool == residual base == 95,000,000 - 6,250,000 == 88,750,000
        assert total_distributed == 88_750_000, \
            "remainder reconciliation lands the pool exactly on the base"


class TestSchoolAllocationWaterfall:

    def test_waterfall_per_school_rounding_then_remainder(self):
        """PRD §3.4: "Each served school's `per_pupil_cents` is the unit value
        multiplied by its own weight, rounded half up to a whole cent — this
        per-school rounding happens before any reconciliation — and its
        `allocation_amount_cents` is exactly `per_pupil_cents` multiplied by
        its `low_income_student_count`. Per-school rounding rarely sums to the
        pool exactly, so a remainder is reconciled one cent at a time: when
        the allocated total falls short of the pool, cents are added cycling
        through the served allocations in `rank_position` ascending order;
        when it overshoots, cents are removed cycling in `rank_position`
        descending order."

        Design: Difficulty/combinatorial_formula/waterfall_per_school_rounding_then_remainder
        """
        ctx = setup_equitable_scenario(fiscal_year=2027,
                                       equitable_count_method="VERIFIED_COUNT",
                                       include_fifth_school=True)
        allocations = list(ctx["allocations"].values())
        by_rank = sorted(allocations, key=lambda a: a["rank_position"])
        assert [a["per_pupil_cents"] for a in by_rank[:4]] == \
            list(PER_PUPIL_VERIFIED)
        assert [a["allocation_amount_cents"] for a in by_rank[:4]] == \
            list(ALLOC_AMOUNTS_VERIFIED)
        # Per-school rounding overshoots by 128 cents; the negative remainder
        # cycles 32 times through the four served rows in descending rank.
        served_total = sum(a["allocation_amount_cents"] for a in by_rank[:4])
        assert served_total == SCHOOL_POOL_VERIFIED, \
            "the remainder is fully reconciled onto the school pool"

    def test_waterfall_unserved_schools_keep_zero_amounts(self):
        """PRD §3.4: "Unserved allocations keep `per_pupil_cents` and
        `allocation_amount_cents` at zero."
        PRD §3.3: "An allocation counts as `served` when its
        `eligibility_flag` is anything other than `BELOW_THRESHOLD` or when it
        was elected."

        Design: Difficulty/combinatorial_formula/waterfall_per_school_rounding_then_remainder
        """
        ctx = setup_equitable_scenario(fiscal_year=2027,
                                       equitable_count_method="VERIFIED_COUNT",
                                       include_fifth_school=True)
        fifth = ctx["allocations"][ctx["schools"][4]["id"]]
        assert fifth["poverty_pct_bp"] == 2000  # 100/500
        assert fifth["eligibility_flag"] == "BELOW_THRESHOLD"
        assert fifth["serve_elected"] is False
        assert fifth["served"] is False
        assert fifth["per_pupil_cents"] == 0
        assert fifth["allocation_amount_cents"] == 0

    def test_elected_below_threshold_school_125pct_weight(self):
        """PRD §3.3: "The director may optionally pass
        `serve_below_threshold_school_ids`, a list of allocation school ids
        below the eligibility threshold to elect into the served set; each
        elected row is flagged `serve_elected` and treated as served."
        PRD §3.4: "Each served school carries a weight: 150 for a `MUST_SERVE`
        school, 125 for a school at or above the schoolwide threshold but
        below must-serve (4000 to 7499 basis points), 100 for a
        targeted-assistance school (3500 to 3999 basis points), and 125 for a
        `serve_elected` school below the threshold — the elected weight
        deliberately sits above the targeted-assistance weight, overriding the
        otherwise non-increasing schedule within the elected band only."

        Design: Corner/state_machines/elected_below_threshold_school_125pct_weight
        """
        ctx = setup_ranking_locked(2036, [(100, 100), (30, 100)],
                                   total_allocation_cents=10_000_000)
        grant_id = ctx["grant"]["id"]
        sa, sb = ctx["schools"]
        finalize_allocations(grant_id,
                             serve_below_threshold_school_ids=[sb["id"]])
        aa = get_allocation_for(grant_id, sa["id"])
        ab = get_allocation_for(grant_id, sb["id"])
        # pool = 10,000,000 - 500,000 (homeless) - 500,000 (PD) = 9,000,000;
        # raw = 150*100 + 125*30 = 18,750; unit = 480 exactly.
        assert ab["serve_elected"] is True and ab["served"] is True
        assert ab["per_pupil_cents"] == 60_000, "480 * 125 (elected weight)"
        assert ab["allocation_amount_cents"] == 1_800_000
        assert aa["per_pupil_cents"] == 72_000, "480 * 150 (must-serve weight)"
        assert aa["allocation_amount_cents"] == 7_200_000
        assert aa["allocation_amount_cents"] + ab["allocation_amount_cents"] \
            == 9_000_000
