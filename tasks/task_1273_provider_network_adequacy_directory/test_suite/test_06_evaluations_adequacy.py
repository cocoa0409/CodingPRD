"""Adequacy evaluation finalize: ratio variants, boundaries, penalties (PRD §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_result, assert_evaluation,
    create_evaluation_payload, create_probe_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, create_probe, create_evaluation,
    finalize_evaluation, get_only_result, list_results, list_deficiencies,
    get_only_deficiency, get_deficiency, get_evaluation, setup_listed_network,
    setup_provider_with_n_listings, setup_open_deficiency,
)

NM = TEST_USERS["network_manager_headers"]


def _setup_one_provider_two_locations():
    """One EFFECTIVE provider LISTED at two OPEN locations in a 2400-member region."""
    return setup_provider_with_n_listings(
        2, county_fips="06001", enrolled_member_count=2400,
        location_overrides_list=[{"address_line": "1 Main St"},
                                 {"address_line": "2 Oak Ave"}])


def _finalize(period="2026-Q2", start="2026-06-01", end="2026-06-11"):
    ev = create_evaluation(measurement_period=period, period_start_date=start,
                           period_end_date=end)
    return finalize_evaluation(ev["id"])


class TestRatioHeadcountVsListingCount:
    def test_provider_count_counts_distinct_providers(self, api):
        """PRD §3.7: "It then computes the counted provider set: distinct providers in
        `EFFECTIVE` status who hold at least one `LISTED` listing of this specialty
        whose location is in this region and whose location's `panel_status` is `OPEN`.
        `provider_count` is the size of that set. A separate `listing_count` variant
        counts the `LISTED` listings themselves — a provider listed at two locations
        counts twice — so that a regulatory filing can cross-check the official
        headcount against the listing base."

        Design: Difficulty/dual_variant_calc/ratio_headcount_vs_listing_count_divergence
        """
        ctx = _setup_one_provider_two_locations()
        ev = _finalize()
        row = get_only_result(ev["id"], ctx["region"]["id"])
        assert_result(row)
        assert row["provider_count"] == 1, "headcount variant counts the provider once"
        assert row["listing_count"] == 2, "listing variant counts both listings"
        assert row["ratio_members_per_provider"] == pytest.approx(2400.0, abs=0.01)

    def test_official_headcount_governs_overall_status(self, api):
        """PRD §3.7: "`ratio_ok` is the integer comparison of `member_count` against the
        standard's `max_members_per_provider` multiplied by `provider_count`; it is
        false whenever `provider_count` is zero and `member_count` is positive."
        PRD §3.7: "The row's `overall_status` is `COMPLIANT` when `member_count` is
        zero, or when `ratio_ok`, `time_distance_compliant`, and `wait_time_compliant`
        are all true."

        Design: Difficulty/dual_variant_calc/ratio_headcount_vs_listing_count_divergence
        """
        ctx = _setup_one_provider_two_locations()
        ev = _finalize()
        row = get_only_result(ev["id"], ctx["region"]["id"])
        assert row["ratio_ok"] is False, "2400 > 1200 * 1 on the official headcount"
        assert row["overall_status"] == "DEFICIENT", (
            "the official headcount governs even though the listing-base ratio "
            "(2400 / 2 = 1200) would comply")


class TestWaitTimeMeanVsP90:
    def _setup_five_probes(self):
        ctx = setup_listed_network(county_fips="06003", enrolled_member_count=500,
                                   listing_overrides={"display_name": "Heart Three",
                                                      "phone": "555-0103"})
        set_clock("2026-06-02T09:00:00Z")
        probes = [create_probe(ctx["listing"]["id"], requested_date="2026-06-02")
                  for _ in range(5)]
        set_clock("2026-06-22T09:00:00Z")
        offered = ["2026-06-05", "2026-06-07", "2026-06-08", "2026-06-09", "2026-06-22"]
        for probe, offered_date in zip(probes, offered):
            validate_success(api_client.record_probe(
                probe["id"], {"outcome": "KEPT", "offered_appointment_date": offered_date}, NM))
        return ctx

    def test_mean_and_p90_computed_from_same_sample(self, api):
        """PRD §3.7: "`mean_wait_days` is the mean of `days_to_appointment` over that
        probed set, rounded half-up to 2 decimal places, null when the set is empty.
        `p90_wait_days` is reported alongside for the filing: the probed
        `days_to_appointment` values are sorted ascending and the value at the 1-based
        index equal to the ceiling of nine-tenths of the sample size is taken; null when
        empty."

        Design: Difficulty/dual_variant_calc/wait_time_mean_vs_p90_divergence
        """
        ctx = self._setup_five_probes()
        ev = _finalize(period="2026-06", start="2026-06-01", end="2026-06-30")
        row = get_only_result(ev["id"], ctx["region"]["id"])
        assert row["mean_wait_days"] == pytest.approx(8.2, abs=0.001), "mean of 3,5,6,7,20"
        assert row["p90_wait_days"] == pytest.approx(20, abs=0.001), (
            "sorted ASC, 1-based index ceil(0.9 * 5) == 5")

    def test_p90_reported_but_does_not_gate(self, api):
        """PRD §3.7: "`wait_time_compliant` — the official gate — is true when the
        probed set is empty, and otherwise is whether `mean_wait_days` is at or below
        the standard's `max_wait_days_routine`. Only `ROUTINE` probes feed the official
        gate; `URGENT` probes are excluded. The `p90_wait_days` reading is reported but
        does not gate, so a tail-heavy sample may pass the mean while flagging on the
        p90 reading."

        Design: Difficulty/dual_variant_calc/wait_time_mean_vs_p90_divergence
        """
        ctx = self._setup_five_probes()
        ev = _finalize(period="2026-06", start="2026-06-01", end="2026-06-30")
        row = get_only_result(ev["id"], ctx["region"]["id"])
        assert row["wait_time_compliant"] is True, "official mean gate: 8.2 <= 15"
        assert row["overall_status"] == "COMPLIANT", (
            "p90 reading 20 > 15 is reported but must not gate overall_status")


class TestRatioBoundary:
    def _setup_two_regions(self):
        set_clock("2026-05-01T00:00:00Z")
        reg1 = create_region(county_fips="06025", name="Lassen", enrolled_member_count=2400)
        reg2 = create_region(county_fips="06027", name="Madera", enrolled_member_count=2401)
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        for i, reg in enumerate((reg1, reg2)):
            for j in range(2):
                provider = create_provider(legal_name=f"P {'AB'[i]}{j + 1}")
                loc = create_location(provider["id"], reg["id"],
                                      address_line=f"{j + 1} {'AB'[i]} St")
                publish_listing(create_listing(provider["id"], loc["id"],
                                               display_name=f"{'AB'[i]}{j + 1}",
                                               phone=f"555-02{i}{j}")["id"])
        return reg1, reg2

    def test_ratio_exactly_at_max_boundary_compliant(self, api):
        """PRD §3.7: "`ratio_ok` is the integer comparison of `member_count` against the
        standard's `max_members_per_provider` multiplied by `provider_count`; it is
        false whenever `provider_count` is zero and `member_count` is positive."
        PRD §3.1: "`max_travel_minutes` and `max_travel_miles` (per-location time and
        distance standards, both inclusive upper bounds), and `max_wait_days_routine`
        and `max_wait_days_urgent` (the appointment-availability ceilings for `ROUTINE`
        and `URGENT` probes respectively, also inclusive)."

        Design: Difficulty/boundary_precision_check/ratio_exactly_at_max_boundary_compliant_vs_one_over_deficient
        """
        reg1, _reg2 = self._setup_two_regions()
        ev = _finalize(period="B1")
        row = get_only_result(ev["id"], reg1["id"])
        assert row["provider_count"] == 2
        assert row["ratio_members_per_provider"] == pytest.approx(1200.0, abs=0.01)
        assert row["ratio_ok"] is True, "2400 <= 1200 * 2 — boundary is inclusive"
        assert row["overall_status"] == "COMPLIANT"

    def test_one_member_over_boundary_deficient(self, api):
        """PRD §3.7: "`ratio_ok` is the integer comparison of `member_count` against the
        standard's `max_members_per_provider` multiplied by `provider_count`; it is
        false whenever `provider_count` is zero and `member_count` is positive."
        PRD §3.7: "For each pair whose `overall_status` came out `DEFICIENT`: if no
        `OPEN` or `EXCUSED` `DeficiencyRecord` exists for the `(region_id, specialty)`
        pair, one is created in `OPEN` with `opened_date` set to this evaluation's
        `period_start_date` and `prior_closure_count` snapshotted to the count of
        `CLOSED` records for the same pair at the moment of creation."

        Design: Difficulty/boundary_precision_check/ratio_exactly_at_max_boundary_compliant_vs_one_over_deficient
        """
        reg1, reg2 = self._setup_two_regions()
        ev = _finalize(period="B1")
        row = get_only_result(ev["id"], reg2["id"])
        assert row["ratio_members_per_provider"] == pytest.approx(1200.5, abs=0.01)
        assert row["ratio_ok"] is False, "2401 > 1200 * 2 — one member over flips the verdict"
        assert row["overall_status"] == "DEFICIENT"
        deficiencies = list_deficiencies({"evaluation_id": ev["id"]})
        assert len(deficiencies) == 1, "exactly one deficiency opens — for the over-boundary region"
        assert deficiencies[0]["region_id"] == reg2["id"]


class TestTimeDistanceBoundary:
    def test_ninety_percent_boundary_inclusive(self, api):
        """PRD §3.7: "`time_distance_compliant` is evaluated in integer arithmetic as
        ten times `compliant_location_count` being at least nine times
        `counted_location_count` — so the 90% boundary is inclusive and exact, with no
        float tolerance — and is false when `counted_location_count` is zero and
        `member_count` is positive."

        Design: Difficulty/boundary_precision_check/time_distance_exactly_ninety_percent_boundary
        """
        overrides = ([{"avg_travel_minutes": 10, "avg_travel_miles": 5}] * 9
                     + [{"avg_travel_minutes": 45, "avg_travel_miles": 5}])
        ctx = setup_provider_with_n_listings(10, county_fips="06031",
                                             enrolled_member_count=100,
                                             location_overrides_list=overrides)
        ev = _finalize(period="TD")
        row = get_only_result(ev["id"], ctx["region"]["id"])
        assert row["counted_location_count"] == 10
        assert row["compliant_location_count"] == 9
        assert row["time_distance_compliant"] is True, "10 * 9 >= 9 * 10 (boundary inclusive)"
        assert row["overall_status"] == "COMPLIANT"

    def test_eighty_percent_fails_the_gate(self, api):
        """PRD §3.7: "`time_distance_compliant` is evaluated in integer arithmetic as
        ten times `compliant_location_count` being at least nine times
        `counted_location_count` — so the 90% boundary is inclusive and exact, with no
        float tolerance — and is false when `counted_location_count` is zero and
        `member_count` is positive."

        Design: Difficulty/boundary_precision_check/time_distance_exactly_ninety_percent_boundary
        """
        overrides = ([{"avg_travel_minutes": 10, "avg_travel_miles": 5}] * 8
                     + [{"avg_travel_minutes": 45, "avg_travel_miles": 5}] * 2)
        ctx = setup_provider_with_n_listings(10, county_fips="06032",
                                             enrolled_member_count=100,
                                             location_overrides_list=overrides)
        ev = _finalize(period="TD2")
        row = get_only_result(ev["id"], ctx["region"]["id"])
        assert row["counted_location_count"] == 10
        assert row["compliant_location_count"] == 8
        assert row["time_distance_compliant"] is False, "10 * 8 < 9 * 10 — below the boundary"
        assert row["overall_status"] == "DEFICIENT"


class TestFinalizeCascadeChain:
    def _setup(self):
        return setup_open_deficiency(county_fips="06017", measurement_period="E1")

    def test_finalize_creates_deficient_result_row_and_opens_deficiency(self, api):
        """PRD §3.7: "Link 1 computes the per-pair result rows. For every
        `ServiceRegion` crossed with every specialty for which a `NetworkStandard`
        exists for `(specialty, region.geo_class)`, a `RegionSpecialtyResult` row is
        created."
        PRD §3.7: "For each pair whose `overall_status` came out `DEFICIENT`: if no
        `OPEN` or `EXCUSED` `DeficiencyRecord` exists for the `(region_id, specialty)`
        pair, one is created in `OPEN` with `opened_date` set to this evaluation's
        `period_start_date` and `prior_closure_count` snapshotted to the count of
        `CLOSED` records for the same pair at the moment of creation."

        Design: Difficulty/transitive_cascade/finalize_result_deficiency_accrual_rollup_chain
        """
        ctx = self._setup()
        row = get_only_result(ctx["evaluation"]["id"], ctx["region"]["id"])
        assert row["overall_status"] == "DEFICIENT"
        assert row["provider_count"] == 0
        deficiency = ctx["deficiency"]
        assert deficiency["status"] == "OPEN"
        assert deficiency["opened_date"] == "2026-06-01"

    def test_finalize_accrues_penalty_and_updates_rollup(self, api):
        """PRD §3.7: "The raw accrual is the base daily penalty of 9,999 cents
        multiplied by the day count, multiplied by the tier multiplier, multiplied by
        the repeat multiplier. The per-event accrual is the smaller of 5,000,000 cents
        (the cap) and the raw accrual rounded half-up to integer cents."
        PRD §3.7: "The sum lands on the evaluation's `total_penalty_cents`. The
        evaluation's `finalized_at` is stamped, `status` transitions to `FINALIZED`, and
        `version` increments by 1."

        Design: Difficulty/transitive_cascade/finalize_result_deficiency_accrual_rollup_chain
        """
        ctx = self._setup()
        deficiency = ctx["deficiency"]
        # 9999 * 10 days * tier 1.5 (12000 members) * repeat 1.0 = 149985
        assert deficiency["last_accrual_cents"] == 149985
        assert deficiency["outstanding_penalty_cents"] == 149985
        evaluation = ctx["evaluation"]
        assert_evaluation(evaluation)
        assert evaluation["status"] == "FINALIZED"
        assert evaluation["finalized_at"] is not None
        assert evaluation["total_penalty_cents"] == 149985


class TestPenaltyTierRepeatInterplay:
    def _setup_reopened_pair(self):
        """D1 opened by E1 (deficient), closed by E2 (compliant), D2 opened by E3."""
        ctx = setup_open_deficiency(county_fips="06007", measurement_period="E1")
        d1 = ctx["deficiency"]
        provider = create_provider(legal_name="Derm One", specialty="DERMATOLOGY")
        location = create_location(provider["id"], ctx["region"]["id"],
                                   address_line="9 Birch Rd", avg_travel_minutes=20,
                                   avg_travel_miles=10)
        publish_listing(create_listing(provider["id"], location["id"],
                                       specialty="DERMATOLOGY", display_name="Derm One",
                                       phone="555-0107")["id"])
        ev2 = create_evaluation(measurement_period="E2", period_start_date="2026-06-12",
                                period_end_date="2026-06-21")
        finalize_evaluation(ev2["id"])
        validate_success(api_client.patch_provider(provider["id"],
                                                   {"to_status": "TERMINATED"}, NM))
        ev3 = create_evaluation(measurement_period="E3", period_start_date="2026-06-22",
                                period_end_date="2026-07-01")
        finalized3 = finalize_evaluation(ev3["id"])
        d2 = get_only_deficiency(ev3["id"], ctx["region"]["id"])
        # Re-fetch D1: E2's compliant finalize closed it server-side, so the
        # snapshot taken at E1 finalize is stale for status/closed_date.
        d1 = get_deficiency(d1["id"])
        return ctx, d1, finalized3, d2

    def test_first_accrual_uses_tier_without_repeat_uplift(self, api):
        """PRD §3.7: "The tier multiplier is 2.0 when the region's
        `enrolled_member_count` is at least 50,000; otherwise 1.5 when it is at least
        10,000; otherwise 1.0. The repeat multiplier is 1 plus 0.5 times the smaller of
        the deficiency's `prior_closure_count` and 3 — so the repeat uplift caps at 2.5
        times for a fourth-or-later deficiency on the same pair."

        Design: Difficulty/combinatorial_formula/deficiency_penalty_tier_repeat_interplay
        """
        ctx, d1, _ev3, _d2 = self._setup_reopened_pair()
        # D1: 9999 * 10 days (06-01..06-11) * tier 1.5 (12000 members) * repeat 1.0
        assert d1["accrued_penalty_cents"] == 149985
        assert d1["status"] == "CLOSED", "the compliant E2 finalize closes D1"
        assert d1["closed_date"] == "2026-06-21"

    def test_reopened_deficiency_stacks_tier_and_repeat_multipliers(self, api):
        """PRD §3.7: "For each pair whose `overall_status` came out `DEFICIENT`: if no
        `OPEN` or `EXCUSED` `DeficiencyRecord` exists for the `(region_id, specialty)`
        pair, one is created in `OPEN` with `opened_date` set to this evaluation's
        `period_start_date` and `prior_closure_count` snapshotted to the count of
        `CLOSED` records for the same pair at the moment of creation."
        PRD §3.7: "The raw accrual is the base daily penalty of 9,999 cents multiplied
        by the day count, multiplied by the tier multiplier, multiplied by the repeat
        multiplier. The per-event accrual is the smaller of 5,000,000 cents (the cap)
        and the raw accrual rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/deficiency_penalty_tier_repeat_interplay
        """
        _ctx, _d1, ev3, d2 = self._setup_reopened_pair()
        assert d2["prior_closure_count"] == 1, "one CLOSED record for the pair at creation"
        # 9999 * 9 days (06-22..07-01) * 1.5 tier * 1.5 repeat = 202479.75 -> 202480
        assert d2["last_accrual_cents"] == 202480
        assert ev3["total_penalty_cents"] == 202480


class TestRollupRoundingOrder:
    def _setup_two_deficient_regions(self):
        set_clock("2026-05-01T00:00:00Z")
        reg1 = create_region(county_fips="06009", name="Del Norte",
                             enrolled_member_count=11000)
        reg2 = create_region(county_fips="06011", name="Fresno",
                             enrolled_member_count=12000)
        create_standard(specialty="DERMATOLOGY", geo_class="URBAN",
                        max_members_per_provider=15000, max_travel_minutes=45,
                        max_travel_miles=30, max_wait_days_routine=20,
                        max_wait_days_urgent=3)
        ev = create_evaluation(measurement_period="R1", period_start_date="2026-06-01",
                               period_end_date="2026-06-04")
        finalized = finalize_evaluation(ev["id"])
        return reg1, reg2, finalized

    def test_each_row_rounded_half_up_before_summing(self, api):
        """PRD §2.5: "Per-deficiency penalty accruals are rounded half-up to integer
        cents per accrual event before any summation; summing raw fractional cents and
        rounding once at the end is forbidden because the two orders yield different
        totals."

        Design: Difficulty/combinatorial_formula/evaluation_rollup_round_per_row_then_sum
        """
        reg1, reg2, _ev = self._setup_two_deficient_regions()
        for reg in (reg1, reg2):
            d = get_only_deficiency(_ev["id"], reg["id"])
            # raw = 9999 * 3 * 1.5 = 44995.5 -> 44996 per row (round_half_up)
            assert d["last_accrual_cents"] == 44996

    def test_rollup_sums_the_per_row_rounded_amounts(self, api):
        """PRD §3.7: "The deficiency component is the sum over this evaluation's accrual
        events of each event's round-half-up-to-integer-cents amount — per-event
        rounding happens before summation, not after."

        Design: Difficulty/combinatorial_formula/evaluation_rollup_round_per_row_then_sum
        """
        _reg1, _reg2, ev = self._setup_two_deficient_regions()
        assert ev["total_penalty_cents"] == 89992, (
            "44996 + 44996; sum-then-round would yield 89991")


class TestPenaltyCapAndEmptySet:
    def test_penalty_cap_binds_per_accrual_event(self, api):
        """PRD §3.7: "The raw accrual is the base daily penalty of 9,999 cents
        multiplied by the day count, multiplied by the tier multiplier, multiplied by
        the repeat multiplier. The per-event accrual is the smaller of 5,000,000 cents
        (the cap) and the raw accrual rounded half-up to integer cents."

        Design: Corner/calculations/penalty_cap_binds_per_accrual_event
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06071", name="Yolo",
                               enrolled_member_count=60000)
        create_standard(specialty="DERMATOLOGY", geo_class="URBAN",
                        max_members_per_provider=150000, max_travel_minutes=45,
                        max_travel_miles=30, max_wait_days_routine=20,
                        max_wait_days_urgent=3)
        ev = create_evaluation(measurement_period="CAP", period_start_date="2026-01-01",
                               period_end_date="2026-12-31")
        finalize_evaluation(ev["id"])
        deficiency = get_only_deficiency(ev["id"], region["id"])
        # raw 9999 * 364 * 2.0 = 7,279,272 -> capped at 5,000,000
        assert deficiency["last_accrual_cents"] == 5000000

    def test_zero_member_region_with_no_providers_is_compliant(self, api):
        """PRD §3.7: "The row's `overall_status` is `COMPLIANT` when `member_count` is
        zero, or when `ratio_ok`, `time_distance_compliant`, and `wait_time_compliant`
        are all true."
        PRD §3.7: "`ratio_members_per_provider` is `member_count` divided by
        `provider_count`, rounded half-up to 2 decimal places, null when `provider_count`
        is zero."

        Design: Corner/calculations/zero_member_region_with_no_providers_is_compliant
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06073", name="Yuba", enrolled_member_count=0)
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        ev = create_evaluation(measurement_period="Z")
        finalize_evaluation(ev["id"])
        row = get_only_result(ev["id"], region["id"])
        assert row["overall_status"] == "COMPLIANT"
        assert row["provider_count"] == 0
        assert row["ratio_members_per_provider"] is None
        assert list_deficiencies({"evaluation_id": ev["id"], "region_id": region["id"]}) == []

    def test_suppressed_listings_excluded_from_adequacy_input_set(self, api):
        """PRD §3.7: "It then computes the counted provider set: distinct providers in
        `EFFECTIVE` status who hold at least one `LISTED` listing of this specialty
        whose location is in this region and whose location's `panel_status` is `OPEN`.
        `provider_count` is the size of that set."

        Design: Corner/calculations/suppressed_listings_excluded_from_adequacy_input_set
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06075", name="Amador",
                               enrolled_member_count=2400)
        create_standard(specialty="CARDIOLOGY", geo_class="URBAN")
        pa = create_provider(legal_name="P59")
        pb = create_provider(legal_name="P60")
        la = create_location(pa["id"], region["id"], address_line="59 A St")
        lb = create_location(pb["id"], region["id"], address_line="60 A St")
        publish_listing(create_listing(pa["id"], la["id"], display_name="L59",
                                       phone="555-0159")["id"])
        sb = publish_listing(create_listing(pb["id"], lb["id"], display_name="L60",
                                            phone="555-0160")["id"])
        validate_success(api_client.patch_listing(
            sb["id"], {"expected_listing_version": sb["version"],
                       "to_status": "SUPPRESSED", "suppress_reason": "MANUAL"}, NM))
        ev = create_evaluation(measurement_period="ISF")
        finalize_evaluation(ev["id"])
        row = get_only_result(ev["id"], region["id"])
        assert row["provider_count"] == 1, (
            "the SUPPRESSED listing drops its provider out of the counted set")
        assert row["overall_status"] == "DEFICIENT", "2400 > 1200 * 1"


class TestFinalizeGuards:
    def test_finalize_blocked_while_period_probe_unrecorded(self, api):
        """PRD §3.7: "It is refused while any `AvailabilityProbe` remains in `SCHEDULED`
        with a `requested_date` inside the closed interval from `period_start_date` to
        `period_end_date` (rejected with `ERR_UNRECORDED_PROBES_EXIST`); the rationale
        is that finalizing over an incomplete probe set would silently undercount
        wait-time failures."

        Design: Corner/state_machines/finalize_blocked_while_period_probe_unrecorded
        """
        ctx = setup_listed_network(county_fips="06063", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L51",
                                                      "phone": "555-0151"})
        set_clock("2026-06-05T00:00:00Z")
        probe = create_probe(ctx["listing"]["id"], requested_date="2026-06-05")
        ev = create_evaluation(measurement_period="G1")
        blocked = api.finalize_evaluation(ev["id"], NM)
        validate_error(blocked, ApiErrorId.ERR_UNRECORDED_PROBES_EXIST)
        validate_success(api.record_probe(
            probe["id"], {"outcome": "KEPT", "offered_appointment_date": "2026-06-09"}, NM))
        finalized = validate_success(api.finalize_evaluation(ev["id"], NM))
        assert finalized["status"] == "FINALIZED"

    def test_second_open_evaluation_rejected(self, api):
        """PRD §3.7: "At most one evaluation may be `OPEN` at a time — a second open is
        rejected with `ERR_EVALUATION_ALREADY_OPEN`."

        Design: Corner/validations/second_open_evaluation_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        create_evaluation(measurement_period="FIRST")
        resp = api.create_evaluation(create_evaluation_payload(
            measurement_period="SECOND", period_start_date="2026-06-12",
            period_end_date="2026-06-21"), NM)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_ALREADY_OPEN)


class TestResultSnapshot:
    def test_result_rows_are_immutable_snapshots(self, api):
        """PRD §2.4: "`RegionSpecialtyResult` rows are immutable snapshots: they carry
        `id` and `created_at` only; both `updated_at` and `version` are absent."
        PRD §3.7: "The row snapshots `member_count` from the region's
        `enrolled_member_count` at finalize time."

        Design: Corner/entities/result_rows_are_immutable_snapshots
        """
        ctx = setup_listed_network(county_fips="06051", enrolled_member_count=2400,
                                   listing_overrides={"display_name": "L37",
                                                      "phone": "555-0137"})
        ev = _finalize(period="SNAP")
        before = get_only_result(ev["id"], ctx["region"]["id"])
        assert_result(before)
        assert before["provider_count"] == 1
        assert before["overall_status"] == "DEFICIENT"
        # Mutate the network after finalize: a second provider goes live.
        p2 = create_provider(legal_name="P38")
        l2 = create_location(p2["id"], ctx["region"]["id"], address_line="38 A St")
        publish_listing(create_listing(p2["id"], l2["id"], display_name="L38",
                                       phone="555-0138")["id"])
        after = get_only_result(ev["id"], ctx["region"]["id"])
        assert_result(after)
        assert after["provider_count"] == 1, "the stored snapshot must not change"
        assert after["overall_status"] == "DEFICIENT"

    def test_finalize_results_immediately_readable(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.7: "The sum lands on the evaluation's `total_penalty_cents`. The
        evaluation's `finalized_at` is stamped, `status` transitions to `FINALIZED`, and
        `version` increments by 1."
        PRD §3.7: "Link 1 computes the per-pair result rows. For every `ServiceRegion`
        crossed with every specialty for which a `NetworkStandard` exists for
        `(specialty, region.geo_class)`, a `RegionSpecialtyResult` row is created."

        Design: Corner/consistency_model/finalize_results_immediately_readable
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06125", name="Tehama2",
                               enrolled_member_count=12000)
        create_standard(specialty="DERMATOLOGY", geo_class="URBAN",
                        max_members_per_provider=15000, max_travel_minutes=45,
                        max_travel_miles=30, max_wait_days_routine=20,
                        max_wait_days_urgent=3)
        ev = create_evaluation(measurement_period="IC")
        finalized = validate_success(api.finalize_evaluation(ev["id"], NM))
        assert finalized["status"] == "FINALIZED"
        assert finalized["total_penalty_cents"] == 149985
        rows = list_results({"evaluation_id": ev["id"], "region_id": region["id"]})
        assert len(rows) == 1, "the result row is readable immediately after finalize"
        assert rows[0]["overall_status"] == "DEFICIENT"
