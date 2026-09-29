"""Largest-remainder distribution splits, PMPM constants and the quality composite.

Every scenario here is built from scratch through the public API because the
harness restarts the server before each test.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    IPA_ADMIN_HEADERS,
    IpaApiClient,
    assert_allocation_is_exact,
    assert_created_at_ascending,
    assert_fields,
    assign_enrollee,
    build_final_scorecard,
    build_paid_claim,
    build_posted_file,
    close_incurral,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_pool,
    expected_composite_score_bps,
    expected_completion_factor_reserve,
    expected_pmpm_components,
    expected_pmpm_loss_ratio_reserve,
    expected_settlement_waterfall,
    largest_remainder_allocation,
    list_pool_distributions,
    propose_settlement,
    read_physician,
    read_pool,
    reserve_pool,
    set_clock,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _distribution_for(api: IpaApiClient, pool_id: str, physician_id: str) -> Json:
    """The single distribution of ``pool_id`` belonging to ``physician_id``."""
    rows = list_pool_distributions(api, pool_id, physician_id=physician_id)
    assert len(rows) == 1, f"expected exactly one distribution, got {len(rows)}"
    return rows[0]


def _list_scorecards(api: IpaApiClient, physician_id: str, **params: Any):
    query: Json = {"limit": 10, "offset": 0}
    query.update(params)
    response = api.list_physician_scorecards(physician_id, IPA_ADMIN_HEADERS, query)
    return validate_paginated(response)


def _build_two_participant_pool(api: IpaApiClient) -> Json:
    """Two participants with equal member months and different composites.

    Each physician holds one ``ADULT``/``HMO`` member at a ``risk_score_bps`` of
    10000 under a ``base_pmpm_cents`` of 20000, so the posted July month funds
    the professional pool with 40000 cents against 20000 basis points of member
    months. Two paid claims of 13520 each leave ``paid_claims_cents`` at 27040,
    and the pool is left ``RESERVED`` under ``COMPLETION_FACTOR``.
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Allocation Health",
        base_pmpm_cents=20000,
        reconciliation_method="ROSTER_SNAPSHOT",
        ibnr_method="COMPLETION_FACTOR",
        ibnr_completion_factor_bps=8000,
        target_claims_pmpm_cents=15000,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
    )
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")

    first = create_active_physician(
        api,
        agreement["id"],
        npi="4100000001",
        full_name="Alma Cheng",
        specialty="PRIMARY_CARE",
    )
    second = create_active_physician(
        api,
        agreement["id"],
        npi="4100000002",
        full_name="Bruno Castellani",
        specialty="PRIMARY_CARE",
    )

    first_member = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C1-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, first_member["id"], first["id"])
    second_member = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C1-0002",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, second_member["id"], second["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": "C1-0001",
                "physician_npi": "4100000001",
                "claimed_capitation_cents": 20000,
            },
            {
                "external_member_id": "C1-0002",
                "physician_npi": "4100000002",
                "claimed_capitation_cents": 20000,
            },
        ],
        coverage_month="2026-07",
    )

    for member, physician in ((first_member, first), (second_member, second)):
        build_paid_claim(
            api,
            agreement["id"],
            member["id"],
            physician["id"],
            13520,
            downstream_provider_name="Riverbend Orthopedics",
            service_date="2026-06-15T00:00:00Z",
        )

    build_final_scorecard(
        api,
        first["id"],
        measurement_period="2026",
        hedis_composite_bps=9000,
        access_score_bps=8000,
        patient_experience_bps=7000,
    )
    build_final_scorecard(
        api,
        second["id"],
        measurement_period="2026",
        hedis_composite_bps=7000,
        access_score_bps=7000,
        patient_experience_bps=7000,
    )

    set_clock(api, "2027-01-01T00:00:00Z")
    close_incurral(api, pool["id"])
    reserved = reserve_pool(api, pool["id"])
    return {
        "agreement": agreement,
        "pool": read_pool(api, pool["id"]),
        "reserved": reserved,
        "first": first,
        "second": second,
    }


def _build_tie_weighted_pool(api: IpaApiClient) -> Json:
    """Two participants with identical weights splitting a three-cent pool.

    The first-created physician deliberately carries the larger ``npi`` so that
    a tie broken by ``npi`` alone would award the leftover cent to the wrong
    participant. A ``target_claims_pmpm_cents`` of 19996 against 20000 basis
    points of member months leaves a raw surplus of 8 cents.
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Leftover Cent Health",
        base_pmpm_cents=20000,
        reconciliation_method="ROSTER_SNAPSHOT",
        ibnr_method="PMPM_LOSS_RATIO",
        ibnr_completion_factor_bps=8000,
        target_claims_pmpm_cents=19996,
        professional_pool_share_bps=10000,
        institutional_pool_share_bps=0,
        quality_withhold_bps=0,
    )
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")

    earlier = create_active_physician(
        api,
        agreement["id"],
        npi="4799999999",
        full_name="Dr Earlier Larger Npi",
        specialty="PRIMARY_CARE",
    )
    later = create_active_physician(
        api,
        agreement["id"],
        npi="4700000001",
        full_name="Dr Later Smaller Npi",
        specialty="INTERNAL_MEDICINE",
    )

    earlier_member = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C8-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, earlier_member["id"], earlier["id"])
    later_member = create_enrollee(
        api,
        agreement["id"],
        external_member_id="C8-0002",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=10000,
    )
    assign_enrollee(api, later_member["id"], later["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    build_posted_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": "C8-0001",
                "physician_npi": "4799999999",
                "claimed_capitation_cents": 20000,
            },
            {
                "external_member_id": "C8-0002",
                "physician_npi": "4700000001",
                "claimed_capitation_cents": 20000,
            },
        ],
        coverage_month="2026-07",
    )
    build_paid_claim(
        api,
        agreement["id"],
        earlier_member["id"],
        earlier["id"],
        10000,
        downstream_provider_name="Leftover Labs LLC",
        service_date="2026-07-15T00:00:00Z",
    )

    for physician in (earlier, later):
        build_final_scorecard(
            api,
            physician["id"],
            measurement_period="2026",
            hedis_composite_bps=7000,
            access_score_bps=7000,
            patient_experience_bps=7000,
        )

    set_clock(api, "2027-01-01T00:00:00Z")
    close_incurral(api, pool["id"])
    reserved = reserve_pool(api, pool["id"])
    return {
        "agreement": agreement,
        "pool": read_pool(api, pool["id"]),
        "reserved": reserved,
        "earlier": earlier,
        "later": later,
    }


# ---------------------------------------------------------------------------
# Instance: pool_distribution_largest_remainder_across_two_participants
# ---------------------------------------------------------------------------


class TestLargestRemainderAcrossTwoParticipants:
    def test_the_leftover_cent_lands_on_the_larger_fractional_part(self, api):
        """PRD §3.8: "The floors are 1806 and 1541, summing to 3347 and leaving one cent over; the larger fractional part, sixteen nineteenths against three nineteenths, belongs to the second participant, so the final allocation is 1806 and 1542, summing to exactly 3348."

        Design: Corner/calculations/pool_distribution_largest_remainder_across_two_participants
        """
        built = _build_two_participant_pool(api)
        proposed = propose_settlement(api, built["pool"]["id"])
        assert proposed["shared_savings_pool_cents"] == 3348

        first = _distribution_for(api, built["pool"]["id"], built["first"]["id"])
        second = _distribution_for(api, built["pool"]["id"], built["second"]["id"])

        assert first["shared_savings_cents"] == 1806
        assert second["shared_savings_cents"] == 1542
        # Neither the leftover-to-the-first-participant answer nor the
        # dropped-leftover answer is admissible.
        assert (first["shared_savings_cents"], second["shared_savings_cents"]) != (1807, 1541)
        assert (first["shared_savings_cents"], second["shared_savings_cents"]) != (1806, 1541)

    def test_the_two_shared_savings_shares_resum_to_the_pool_exactly(self, api):
        """PRD §3.8: "The procedure is exact by construction: the allocated shares always sum to precisely the total being distributed."

        Design: Corner/calculations/pool_distribution_largest_remainder_across_two_participants
        """
        built = _build_two_participant_pool(api)
        proposed = propose_settlement(api, built["pool"]["id"])

        first = _distribution_for(api, built["pool"]["id"], built["first"]["id"])
        second = _distribution_for(api, built["pool"]["id"], built["second"]["id"])

        allocated = [first["shared_savings_cents"], second["shared_savings_cents"]]
        assert_allocation_is_exact(proposed["shared_savings_pool_cents"], allocated)
        assert allocated == largest_remainder_allocation(
            proposed["shared_savings_pool_cents"],
            [
                first["panel_member_months_bps"] * first["composite_score_bps_snapshot"],
                second["panel_member_months_bps"] * second["composite_score_bps_snapshot"],
            ],
        )

    def test_the_shared_savings_weighting_is_member_months_times_composite(self, api):
        """PRD §3.8: "Two weightings are then derived from those figures: the withhold weighting is `panel_member_months_bps` on its own, and the shared-savings weighting is `panel_member_months_bps` multiplied by `composite_score_bps_snapshot`."

        Design: Corner/calculations/pool_distribution_largest_remainder_across_two_participants
        """
        built = _build_two_participant_pool(api)
        propose_settlement(api, built["pool"]["id"])

        first = _distribution_for(api, built["pool"]["id"], built["first"]["id"])
        second = _distribution_for(api, built["pool"]["id"], built["second"]["id"])

        assert_fields(
            first,
            {
                "panel_member_months_bps": 10000,
                "composite_score_bps_snapshot": expected_composite_score_bps(9000, 8000, 7000),
                "withhold_release_bps_snapshot": 7500,
                "withhold_share_cents": 0,
                "withhold_release_cents": 0,
                "net_distribution_cents": 1806,
                "status": "PROPOSED",
            },
        )
        assert_fields(
            second,
            {
                "panel_member_months_bps": 10000,
                "composite_score_bps_snapshot": expected_composite_score_bps(7000, 7000, 7000),
                "withhold_release_bps_snapshot": 7500,
                "withhold_share_cents": 0,
                "withhold_release_cents": 0,
                "net_distribution_cents": 1542,
                "status": "PROPOSED",
            },
        )
        # Equal member months with unequal composites is what makes the weights
        # differ at all: 82000000 against 70000000.
        assert first["composite_score_bps_snapshot"] == 8200
        assert second["composite_score_bps_snapshot"] == 7000

    def test_the_pool_reaches_3348_through_the_pre_fee_tier(self, api):
        """PRD §3.8: "Step nine computes `shared_savings_pool_cents` as `distributable_surplus_cents` multiplied by the tier's shared-savings share — 0 basis points for `NONE`, 4000 for `TIER_1`, 5000 for `TIER_2` and 6000 for `TIER_3` — as a proportion of 10000, rounded half up to whole cents."

        Design: Corner/calculations/pool_distribution_largest_remainder_across_two_participants
        """
        built = _build_two_participant_pool(api)
        assert built["reserved"]["ibnr_reserve_cents"] == expected_completion_factor_reserve(
            27040, 8000
        )
        assert built["reserved"]["ibnr_reserve_cents"] == 6760

        proposed = propose_settlement(api, built["pool"]["id"])
        waterfall = expected_settlement_waterfall(40000, 27040, 0, 6760)
        assert_fields(
            proposed,
            {
                "funded_cents": 40000,
                "paid_claims_cents": 27040,
                "raw_surplus_cents": 6200,
                "surplus_tier": "TIER_3",
                "admin_fee_cents": 620,
                "distributable_surplus_cents": 5580,
                "shared_savings_pool_cents": 3348,
            },
        )
        assert proposed["shared_savings_pool_cents"] == waterfall["shared_savings_pool_cents"]


# ---------------------------------------------------------------------------
# Instance: member_pmpm_constants_applied_across_age_bands_and_tiers
# ---------------------------------------------------------------------------


class TestMemberPmpmConstants:
    def _agreement(self, api):
        set_clock(api, "2026-08-01T00:00:00Z")
        return create_active_agreement(
            api,
            payer_name="Corner Constants Health",
            base_pmpm_cents=30000,
            quality_withhold_bps=700,
        )

    def test_each_age_band_factor_and_tier_add_on_lands_on_its_own_gross(self, api):
        """PRD §3.3: "To that single rounded figure add the flat benefit-tier add-on for the member's `benefit_tier`: nothing at all for `HMO`, 1200 cents for `POS`, and 2500 cents for `HMO_PLUS`."

        Design: Corner/calculations/member_pmpm_constants_applied_across_age_bands_and_tiers
        """
        agreement = self._agreement(api)

        adult = create_enrollee(
            api,
            agreement["id"],
            external_member_id="C3-0001",
            age_band="ADULT",
            benefit_tier="HMO",
            risk_score_bps=12500,
        )
        senior_plus = create_enrollee(
            api,
            agreement["id"],
            external_member_id="C3-0002",
            age_band="SENIOR",
            benefit_tier="HMO_PLUS",
            risk_score_bps=20000,
        )
        senior_pos = create_enrollee(
            api,
            agreement["id"],
            external_member_id="C3-0003",
            age_band="SENIOR",
            benefit_tier="POS",
            risk_score_bps=10000,
        )

        assert_fields(
            adult,
            {"gross_pmpm_cents": 37500, "withhold_cents": 2625, "net_pmpm_cents": 34875},
        )
        assert_fields(
            senior_plus,
            {"gross_pmpm_cents": 89500, "withhold_cents": 6265, "net_pmpm_cents": 83235},
        )
        assert_fields(
            senior_pos,
            {"gross_pmpm_cents": 44700, "withhold_cents": 3129, "net_pmpm_cents": 41571},
        )
        for enrollee, age_band, tier, risk in (
            (adult, "ADULT", "HMO", 12500),
            (senior_plus, "SENIOR", "HMO_PLUS", 20000),
            (senior_pos, "SENIOR", "POS", 10000),
        ):
            gross, withhold, net = expected_pmpm_components(30000, age_band, tier, risk, 700)
            assert (
                enrollee["gross_pmpm_cents"],
                enrollee["withhold_cents"],
                enrollee["net_pmpm_cents"],
            ) == (gross, withhold, net)

    def test_the_tier_add_on_is_never_risk_adjusted_or_age_adjusted(self, api):
        """PRD §3.3: "The tier add-on is a flat cent amount that is never risk-adjusted and never age-adjusted, and it is applied after the rounding, not before."

        Design: Corner/calculations/member_pmpm_constants_applied_across_age_bands_and_tiers
        """
        agreement = self._agreement(api)

        senior_pos = create_enrollee(
            api,
            agreement["id"],
            external_member_id="C3-0010",
            age_band="SENIOR",
            benefit_tier="POS",
            risk_score_bps=10000,
        )

        # 30000 at the SENIOR factor of 14500 basis points is 43500 cents, and
        # the flat POS add-on of 1200 is added to that already rounded figure.
        assert senior_pos["gross_pmpm_cents"] == 43500 + 1200
        # Folding the add-on into the multiplicands instead would have produced
        # (30000 + 1200) * 1.45, which is 45240 cents.
        assert senior_pos["gross_pmpm_cents"] != 45240

        senior_hmo = create_enrollee(
            api,
            agreement["id"],
            external_member_id="C3-0011",
            age_band="SENIOR",
            benefit_tier="HMO",
            risk_score_bps=10000,
        )
        assert senior_hmo["gross_pmpm_cents"] == 43500
        assert senior_pos["gross_pmpm_cents"] - senior_hmo["gross_pmpm_cents"] == 1200

    def test_none_of_the_three_members_is_clamped(self, api):
        """PRD §3.3: "First the raw amount is raised to the floor of 8000 cents if it falls below that floor; the floored value is then reduced to the ceiling of 95000 cents if it exceeds that ceiling."

        Design: Corner/calculations/member_pmpm_constants_applied_across_age_bands_and_tiers
        """
        agreement = self._agreement(api)

        grosses = []
        for member_id, age_band, tier, risk in (
            ("C3-0021", "ADULT", "HMO", 12500),
            ("C3-0022", "SENIOR", "HMO_PLUS", 20000),
            ("C3-0023", "SENIOR", "POS", 10000),
        ):
            enrollee = create_enrollee(
                api,
                agreement["id"],
                external_member_id=member_id,
                age_band=age_band,
                benefit_tier=tier,
                risk_score_bps=risk,
            )
            grosses.append(enrollee["gross_pmpm_cents"])

        assert grosses == [37500, 89500, 44700]
        for gross in grosses:
            assert 8000 < gross < 95000


# ---------------------------------------------------------------------------
# Instance: quality_composite_weights_accumulate_without_rounding_drift
# ---------------------------------------------------------------------------


class TestQualityCompositeAccumulatesUnrounded:
    def _physician(self, api):
        set_clock(api, "2026-08-01T00:00:00Z")
        agreement = create_active_agreement(
            api,
            payer_name="Corner Weighted Scoring Health",
            professional_pool_share_bps=10000,
            institutional_pool_share_bps=0,
            quality_withhold_bps=700,
        )
        physician = create_active_physician(
            api,
            agreement["id"],
            npi="4600000001",
            full_name="Dr Weighted",
            specialty="PEDIATRICS",
        )
        return agreement, physician

    def test_the_three_weighted_terms_are_rounded_once_at_the_end(self, api):
        """PRD §3.8: "Finalisation computes `composite_score_bps` as a weighted blend of the three inputs, with weights that add to exactly 10000 basis points: HEDIS carries 5000 basis points of weight, patient experience 3000, and access 2000."

        Design: Corner/calculations/quality_composite_weights_accumulate_without_rounding_drift
        """
        _agreement, physician = self._physician(api)

        scorecard = build_final_scorecard(
            api,
            physician["id"],
            measurement_period="2026",
            hedis_composite_bps=8333,
            access_score_bps=6667,
            patient_experience_bps=5555,
        )

        # 4166.5 plus 1666.5 plus 1333.4 accumulates to 7166.4 basis points.
        assert scorecard["composite_score_bps"] == 7166
        # Rounding each term first would have accumulated 4167 plus 1667 plus
        # 1333, a one-basis-point drift.
        assert scorecard["composite_score_bps"] != 7167
        assert scorecard["composite_score_bps"] == expected_composite_score_bps(8333, 6667, 5555)
        assert scorecard["withhold_release_bps"] == 7500
        assert read_physician(api, physician["id"])["quality_composite_bps"] == 7166

    def test_equal_inputs_pass_through_unchanged_and_release_the_full_withhold(self, api):
        """PRD §3.8: "A scorecard reading 8500 on all three inputs composites to exactly 8500 and therefore releases 10000."

        Design: Corner/calculations/quality_composite_weights_accumulate_without_rounding_drift
        """
        _agreement, physician = self._physician(api)

        first = build_final_scorecard(
            api,
            physician["id"],
            measurement_period="2026",
            hedis_composite_bps=8333,
            access_score_bps=6667,
            patient_experience_bps=5555,
        )
        second = build_final_scorecard(
            api,
            physician["id"],
            measurement_period="2027",
            hedis_composite_bps=8500,
            access_score_bps=8500,
            patient_experience_bps=8500,
        )

        assert second["composite_score_bps"] == 8500
        assert second["withhold_release_bps"] == 10000
        assert first["status"] == "FINAL"
        assert second["status"] == "FINAL"

        rows, meta = _list_scorecards(api, physician["id"], status="FINAL")
        assert meta["total_count"] == 2
        assert len(rows) == 2

    def test_the_physician_mirror_takes_the_most_recent_finalised_composite(self, api):
        """PRD §3.2: "`quality_composite_bps` holds the `composite_score_bps` of that physician's most recently finalised scorecard, selected by taking the scorecards whose `status` is `FINAL` and ordering them by `measurement_period` descending and then by `created_at` descending; when the physician has no `FINAL` scorecard at all the field reads 0."

        Design: Corner/calculations/quality_composite_weights_accumulate_without_rounding_drift
        """
        _agreement, physician = self._physician(api)
        assert physician["quality_composite_bps"] == 0

        build_final_scorecard(
            api,
            physician["id"],
            measurement_period="2026",
            hedis_composite_bps=8333,
            access_score_bps=6667,
            patient_experience_bps=5555,
        )
        assert read_physician(api, physician["id"])["quality_composite_bps"] == 7166

        build_final_scorecard(
            api,
            physician["id"],
            measurement_period="2027",
            hedis_composite_bps=8500,
            access_score_bps=8500,
            patient_experience_bps=8500,
        )
        assert read_physician(api, physician["id"])["quality_composite_bps"] == 8500


# ---------------------------------------------------------------------------
# Instance: distribution_leftover_cent_tie_broken_by_created_at_not_npi
# ---------------------------------------------------------------------------


class TestLeftoverCentTieBreak:
    def test_the_tied_leftover_cent_follows_created_at_rather_than_npi(self, api):
        """PRD §3.8: "The leftover — the total less the sum of those floors — is then handed out one cent at a time to the participants with the largest fractional parts of their exact shares, ties broken by the participant ordering above, `created_at` ascending and then `npi` ascending, never by identifier and never randomly."

        Design: Corner/calculations/distribution_leftover_cent_tie_broken_by_created_at_not_npi
        """
        built = _build_tie_weighted_pool(api)
        proposed = propose_settlement(api, built["pool"]["id"])
        assert proposed["shared_savings_pool_cents"] == 3

        earlier = _distribution_for(api, built["pool"]["id"], built["earlier"]["id"])
        later = _distribution_for(api, built["pool"]["id"], built["later"]["id"])

        assert earlier["panel_member_months_bps"] == 10000
        assert later["panel_member_months_bps"] == 10000
        assert earlier["composite_score_bps_snapshot"] == later["composite_score_bps_snapshot"]

        # Exact shares of 1.5 and 1.5: the floors are 1 and 1 and the single
        # leftover cent goes to the first-created participant, whose npi is the
        # larger of the two.
        assert built["earlier"]["npi"] > built["later"]["npi"]
        assert earlier["shared_savings_cents"] == 2
        assert later["shared_savings_cents"] == 1
        assert earlier["net_distribution_cents"] == 2
        assert later["net_distribution_cents"] == 1

    def test_the_three_cent_pool_is_distributed_without_dropping_a_cent(self, api):
        """PRD §2.6: "Second, the largest-remainder allocation that splits withhold and shared savings among physicians takes the floor of each participant's exact share and then distributes the leftover cents one at a time, so the allocation sums exactly to the amount being distributed with no rounding drift."

        Design: Corner/calculations/distribution_leftover_cent_tie_broken_by_created_at_not_npi
        """
        built = _build_tie_weighted_pool(api)
        proposed = propose_settlement(api, built["pool"]["id"])

        rows = list_pool_distributions(api, built["pool"]["id"])
        assert len(rows) == 2
        assert_created_at_ascending(rows)
        assert rows[0]["physician_id"] == built["earlier"]["id"]
        assert rows[1]["physician_id"] == built["later"]["id"]

        assert_allocation_is_exact(
            proposed["shared_savings_pool_cents"],
            [row["shared_savings_cents"] for row in rows],
        )
        assert [row["shared_savings_cents"] for row in rows] == largest_remainder_allocation(
            proposed["shared_savings_pool_cents"],
            [
                row["panel_member_months_bps"] * row["composite_score_bps_snapshot"]
                for row in rows
            ],
        )
        for row in rows:
            assert row["status"] == "PROPOSED"
            assert row["withhold_share_cents"] == 0

    def test_the_eight_cent_surplus_reaches_tier_one_and_a_three_cent_pool(self, api):
        """PRD §3.8: "Step six looks up the administrative fee rate for the tier: 0 basis points for `NONE`, 300 for `TIER_1`, 600 for `TIER_2` and 1000 for `TIER_3`."

        Design: Corner/calculations/distribution_leftover_cent_tie_broken_by_created_at_not_npi
        """
        built = _build_tie_weighted_pool(api)
        assert built["reserved"]["ibnr_reserve_cents"] == expected_pmpm_loss_ratio_reserve(
            10000, 19996, 20000
        )
        assert built["reserved"]["ibnr_reserve_cents"] == 29992

        proposed = propose_settlement(api, built["pool"]["id"])
        assert_fields(
            proposed,
            {
                "funded_cents": 40000,
                "paid_claims_cents": 10000,
                "ibnr_reserve_cents": 29992,
                "raw_surplus_cents": 8,
                "surplus_tier": "TIER_1",
                "admin_fee_cents": 0,
                "distributable_surplus_cents": 8,
                "shared_savings_pool_cents": 3,
            },
        )
        assert proposed["shared_savings_pool_cents"] == expected_settlement_waterfall(
            40000, 10000, 0, 29992
        )["shared_savings_pool_cents"]
