"""Rate determination, hybrid denominator reduction, gap-list generation, the
provider gap-burden computed read, and compute-rate guards.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    compute_rate,
    create_active_spec,
    create_and_open_season,
    create_chase_exclusion_payload,
    create_run,
    create_submitted_abstraction,
    get_run,
    identify_population,
    list_run_gaps,
    receive_chases,
    record_overread,
    register_enrolled_member,
    register_provider,
    run_hybrid_pipeline,
    set_clock,
    setup_accepted_batch,
    setup_hybrid_sample,
    setup_populated_run,
    setup_rate_computed_run,
    validate_error,
    validate_success,
    get_success_data,
)

ANALYST = TEST_USERS["quality_analyst_headers"]
RELATIONS = TEST_USERS["provider_relations_headers"]


def _dual_variant_scenario(api):
    """One season, two ACTIVE HYBRID specs differing only in hybrid_policy, members
    M001/M002, and one fully-pipelined run per spec with byte-identical evidence:
    chase abstractions M001 -> MISS, M002 -> HIT, plus one accepted in-window LAB_FEED
    MAMMO record for M001 per run."""
    set_clock(api, "2026-03-01T00:00:00Z")
    season = create_and_open_season(api, approved_supplemental_sources=["LAB_FEED"])
    base = dict(
        version_label="2025.1", collection_method="HYBRID", sample_size_floor=2,
        age_min=50, age_max=74, gender_requirement="F",
        continuous_enrollment_months=12, allowable_gap_days=45,
        anchor_date="2025-12-31T00:00:00Z",
    )
    spec_so = create_active_spec(
        api, season["id"], hedis_measure_code="BCS-SO", hybrid_policy="SAMPLE_ONLY", **base
    )
    spec_as = create_active_spec(
        api, season["id"], hedis_measure_code="BCS-AS", hybrid_policy="ADMIN_SUPPLEMENTED",
        **base,
    )
    register_provider(api, "P1")
    for ref in ("M001", "M002"):
        register_enrolled_member(
            api, ref, provider_ref="P1",
            birth_date="1960-01-01T00:00:00Z", gender="F",
        )
    results = ("MISS", "HIT")  # chases mint in member_ref ASC: M001 then M002
    records = [("M001", "2025-06-10T00:00:00Z", "MAMMO")]
    run_so = run_hybrid_pipeline(api, season["id"], spec_so["id"], results, records)
    run_as = run_hybrid_pipeline(api, season["id"], spec_as["id"], results, records)
    return {"season": season, "so": run_so, "as": run_as}


class TestHybridRateVariants:
    def test_sample_only_counts_only_abstraction_hits(self, api):
        """SAMPLE_ONLY: administrative evidence is ignored — the numerator counts
        only the M002 abstraction HIT, so the hybrid rate is 1/2 = 0.5.

        PRD §3.7: "Under the `SAMPLE_ONLY` variant a sampled entry counts toward the
        numerator only on a sample hit — administrative evidence is ignored; under the
        `ADMIN_SUPPLEMENTED` variant an entry counts on a sample hit or on
        `admin_compliant` true, so with identical evidence the numerator is at least
        as large as under `SAMPLE_ONLY` whenever any sampled member is
        administratively compliant without an abstraction hit."
        PRD §3.7: "The hybrid denominator is the sample's `drawn_size` minus the run's
        `sample_exclusion_count`, and the `hybrid_rate` is `sample_numerator_count`
        divided by that denominator, rounded half-up to 4 decimal places. The
        `final_rate` is the `admin_rate` for `ADMINISTRATIVE` runs and the
        `hybrid_rate` for `HYBRID` runs."
        PRD §2.3: "population entries and chart chases list in `member_ref` ascending
        order."

        Design: Difficulty/dual_variant_calc/hybrid_rate_sample_only_vs_admin_supplemented
        """
        scenario = _dual_variant_scenario(api)
        so = scenario["so"]
        assert [c["member_ref"] for c in so["chases"]] == ["M001", "M002"]
        assert so["run"]["denominator_count"] == 2
        assert so["sample"]["drawn_size"] == 2
        assert so["batch"]["accepted_record_count"] == 1, (
            "the M001 record is accepted in the SAMPLE_ONLY run too — evidence is identical"
        )
        assert so["sample"]["irr_ratio"] == pytest.approx(1.0)
        assert so["sample"]["irr_state"] == "PASSED"
        computed = so["run"]
        assert computed["admin_numerator_count"] == 1, (
            "admin numerator counts M001 in both variants"
        )
        assert computed["sample_numerator_count"] == 1, (
            "SAMPLE_ONLY counts only the M002 abstraction HIT"
        )
        assert computed["hybrid_rate"] == pytest.approx(0.5)
        assert computed["final_rate"] == pytest.approx(0.5)

    def test_admin_supplemented_ors_in_administrative_compliance(self, api):
        """ADMIN_SUPPLEMENTED: the numerator counts the sample hit OR
        admin_compliance — M001 (admin) and M002 (hit) both count, rate 2/2 = 1.0,
        diverging from SAMPLE_ONLY on identical evidence.

        PRD §3.7: "under the `ADMIN_SUPPLEMENTED` variant an entry counts on a sample
        hit or on `admin_compliant` true, so with identical evidence the numerator is
        at least as large as under `SAMPLE_ONLY` whenever any sampled member is
        administratively compliant without an abstraction hit."
        PRD §3.7: "The `final_rate` is the `admin_rate` for `ADMINISTRATIVE` runs and
        the `hybrid_rate` for `HYBRID` runs."

        Design: Difficulty/dual_variant_calc/hybrid_rate_sample_only_vs_admin_supplemented
        """
        scenario = _dual_variant_scenario(api)
        computed = scenario["as"]["run"]
        assert computed["sample_numerator_count"] == 2, (
            "ADMIN_SUPPLEMENTED counts M002's HIT OR M001's admin_compliant"
        )
        assert computed["admin_numerator_count"] == 1
        assert computed["hybrid_rate"] == pytest.approx(1.0)
        assert computed["final_rate"] == pytest.approx(1.0)
        assert computed["hybrid_rate"] != scenario["so"]["run"]["hybrid_rate"], (
            "identical evidence, divergent rates purely from the variant"
        )


class TestAdminRatePrecision:
    def test_admin_rate_four_decimal_rounding(self, api):
        """Rates are 4-decimal round_half_up: 1/3 computes to exactly 0.3333, and
        final_rate mirrors admin_rate for ADMINISTRATIVE runs.

        PRD §2.7: "All rates on a MeasureRun — `admin_rate`, `hybrid_rate`, and
        `final_rate` — and the sample's `irr_ratio` are reported to 4 decimal places,
        rounded half-up."
        PRD §3.7: "The `admin_numerator_count` is the number of non-excluded
        population entries with `admin_compliant` true, and the `admin_rate` is that
        count divided by `denominator_count`, rounded half-up to 4 decimal places."
        PRD §3.7: "The `final_rate` is the `admin_rate` for `ADMINISTRATIVE` runs and
        the `hybrid_rate` for `HYBRID` runs."

        Design: Corner/calculations/admin_rate_four_decimal_rounding
        """
        scenario = setup_populated_run(api, member_refs=("M1", "M2", "M3"))
        setup_accepted_batch(
            api, scenario["run"]["id"], [("M1", "2025-05-05T00:00:00Z", "A1C")]
        )
        computed = compute_rate(api, scenario["run"]["id"])
        assert computed["denominator_count"] == 3
        assert computed["admin_numerator_count"] == 1
        assert computed["admin_rate"] == pytest.approx(0.3333, abs=1e-9), (
            f"round_half_up(1/3, 4dp) must be 0.3333; got {computed['admin_rate']}"
        )
        assert computed["final_rate"] == pytest.approx(0.3333, abs=1e-9)


class TestHybridExclusionDenominator:
    def test_hybrid_exclusion_shrinks_denominator(self, api):
        """A valid chase exclusion reduces the hybrid denominator: drawn 2 minus 1
        exclusion leaves denominator 1, so the single HIT produces hybrid_rate 1.0.

        PRD §3.4: "Marking a chase excluded moves it from `REQUESTED`, `RECEIVED`, or
        `REJECTED_UNREADABLE` into the terminal `EXCLUDED_VALID` state; the request
        carries a `reason`."
        PRD §3.4: "Each valid exclusion increments the run's `sample_exclusion_count`
        by 1, which directly shrinks the hybrid denominator at rate time (§3.7)"
        PRD §3.7: "The hybrid denominator is the sample's `drawn_size` minus the run's
        `sample_exclusion_count`, and the `hybrid_rate` is `sample_numerator_count`
        divided by that denominator, rounded half-up to 4 decimal places."

        Design: Corner/calculations/hybrid_exclusion_shrinks_denominator
        """
        scenario = setup_hybrid_sample(
            api,
            member_refs=("M001", "M002", "M003", "M004"),
            floor=2,
            spec_overrides={"age_min": 0, "age_max": 100, "hybrid_policy": "SAMPLE_ONLY"},
        )
        c1, c3 = scenario["chases"]
        assert c1["member_ref"] == "M001" and c3["member_ref"] == "M003", (
            "draw indices 0 and 2 select M001 and M003"
        )
        excluded = validate_success(
            api.mark_chase_excluded(c3["id"], create_chase_exclusion_payload("DECEASED"), ANALYST)
        )
        assert excluded["status"] == "EXCLUDED_VALID"
        receive_chases(api, [c1])
        a1 = create_submitted_abstraction(api, c1["id"], "HIT")
        assert a1["requires_overread"] is True
        record_overread(api, a1["id"], "AGREE")
        get_success_data(api.evaluate_irr(scenario["sample"]["id"], ANALYST))
        finalized = validate_success(api.finalize_sample(scenario["sample"]["id"], ANALYST))
        assert finalized["status"] == "FINALIZED"
        computed = compute_rate(api, scenario["run"]["id"])
        assert computed["sample_exclusion_count"] == 1
        assert computed["sample_numerator_count"] == 1
        assert computed["hybrid_rate"] == pytest.approx(1.0), (
            "numerator 1 over hybrid denominator (drawn 2 - excluded 1) = 1"
        )
        assert computed["final_rate"] == pytest.approx(1.0)


def _burden_scenario(api):
    """Two ACTIVE ADMINISTRATIVE specs with reporting_weight 0.125; GPA admits the
    three male members, GPB the three female members; both runs computed with no
    evidence, so each mints 3 OPEN gaps — all attributed to P1."""
    set_clock(api, "2026-03-01T00:00:00Z")
    season = create_and_open_season(api, approved_supplemental_sources=["LAB_FEED"])
    spec_a = create_active_spec(
        api, season["id"], hedis_measure_code="GPA", reporting_weight=0.125,
        gender_requirement="M",
    )
    spec_b = create_active_spec(
        api, season["id"], hedis_measure_code="GPB", reporting_weight=0.125,
        gender_requirement="F",
    )
    provider = register_provider(api, "P1")
    for ref, gender in (("M01", "M"), ("M02", "M"), ("M03", "M"),
                        ("M04", "F"), ("M05", "F"), ("M06", "F")):
        register_enrolled_member(api, ref, provider_ref="P1", gender=gender)
    run_a = identify_population(api, create_run(api, season["id"], spec_a["id"])["id"])
    run_b = identify_population(api, create_run(api, season["id"], spec_b["id"])["id"])
    run_a = compute_rate(api, run_a["id"])
    run_b = compute_rate(api, run_b["id"])
    return {"season": season, "provider": provider, "run_a": run_a, "run_b": run_b}


class TestProviderGapBurdenRounding:
    def test_burden_counts_open_gaps_per_measure_line(self, api):
        """The burden read counts open gaps (OPEN or OUTREACH_DONE) per run and
        reports the unweighted total plus the number of contributing measure lines.

        PRD §3.7: "For every measure run of that season whose pinned specification is
        not `RETIRED` — regardless of the run's `reporting_status` — the read counts
        that run's gap items matching the provider's `provider_ref` in `OPEN` or
        `OUTREACH_DONE`"
        PRD §3.7: "its `open_gap_count` is the unweighted total of open gaps across
        those runs, and its `per_measure_lines` is the number of runs contributing at
        least one open gap."

        Design: Difficulty/combinatorial_formula/provider_gap_burden_per_line_rounding
        """
        scenario = _burden_scenario(api)
        assert scenario["run_a"]["denominator_count"] == 3
        assert scenario["run_b"]["denominator_count"] == 3
        burden = validate_success(
            api.get_provider_gap_burden(
                scenario["provider"]["id"], RELATIONS,
                params={"season_id": scenario["season"]["id"]},
            )
        )
        assert burden["open_gap_count"] == 6
        assert burden["per_measure_lines"] == 2

    def test_burden_rounds_per_line_then_sums(self, api):
        """Per-line rounding then summation: round_half_up(3 x 0.125, 2dp) = 0.38
        per line, summed to 0.76; the rejected sum-then-round order would give 0.75.

        PRD §3.7: "each run contributes a line equal to that open-gap count times the
        specification's `reporting_weight`, with the line rounded half-up to 2 decimal
        places before any summation. The response's `burden_score` is the sum of those
        rounded lines"
        PRD §2.7: "The per-line-then-sum order is pinned; computing the raw sum and
        rounding once at the end is the rejected alternative."

        Design: Difficulty/combinatorial_formula/provider_gap_burden_per_line_rounding
        """
        scenario = _burden_scenario(api)
        burden = validate_success(
            api.get_provider_gap_burden(
                scenario["provider"]["id"], RELATIONS,
                params={"season_id": scenario["season"]["id"]},
            )
        )
        assert burden["burden_score"] == pytest.approx(0.76), (
            f"per-line round_half_up(3 * 0.125 = 0.375, 2dp) = 0.38 twice = 0.76; "
            f"got {burden['burden_score']} (sum-then-round would give 0.75)"
        )


class TestProviderGapBurdenInputSet:
    def test_provider_gap_burden_excludes_closed_gaps(self, api):
        """A CLOSED_COMPLIANT gap leaves the {OPEN, OUTREACH_DONE} input set.

        PRD §3.7: "For every measure run of that season whose pinned specification is
        not `RETIRED` — regardless of the run's `reporting_status` — the read counts
        that run's gap items matching the provider's `provider_ref` in `OPEN` or
        `OUTREACH_DONE`"
        PRD §3.7: "each run contributes a line equal to that open-gap count times the
        specification's `reporting_weight`, with the line rounded half-up to 2 decimal
        places before any summation."

        Design: Corner/calculations/provider_gap_burden_excludes_closed_gaps
        """
        scenario = setup_rate_computed_run(
            api, member_refs=("M1", "M2"), provider_ref="P1"
        )
        gaps, _ = list_run_gaps(api, scenario["run"]["id"])
        assert len(gaps) == 2
        validate_success(api.mark_gap_outreach_done(gaps[0]["id"], RELATIONS))
        validate_success(
            api.close_gap(gaps[0]["id"], {"outcome": "CLOSED_COMPLIANT"}, RELATIONS)
        )
        burden = validate_success(
            api.get_provider_gap_burden(
                scenario["providers"]["P1"]["id"], RELATIONS,
                params={"season_id": scenario["season"]["id"]},
            )
        )
        assert burden["open_gap_count"] == 1
        assert burden["per_measure_lines"] == 1
        assert burden["burden_score"] == pytest.approx(1.0), (
            "round_half_up(1 * 1.0, 2dp) = 1.0"
        )


class TestGapWorkflow:
    def test_gap_outreach_happy_path_and_provider_counter(self, api):
        """OPEN -> OUTREACH_DONE -> CLOSED_COMPLIANT stamps MANUAL and decrements
        the attributed provider's open_gap_count by exactly 1.

        PRD §3.7: "Closing is possible from `OUTREACH_DONE` with an `outcome` of
        `CLOSED_COMPLIANT` or `CLOSED_NONCOMPLIANT`; both manual closures set
        `closure_source` to `MANUAL` and decrement the referenced provider's
        `open_gap_count` by 1, and each transition increments the gap item's
        `version`."

        Design: Corner/state_machines/gap_outreach_happy_path_and_provider_counter
        """
        scenario = setup_rate_computed_run(api, member_refs=("M1",), provider_ref="P1")
        gaps, _ = list_run_gaps(api, scenario["run"]["id"])
        assert len(gaps) == 1 and gaps[0]["provider_ref"] == "P1"
        provider_id = scenario["providers"]["P1"]["id"]
        provider = validate_success(api.get_provider(provider_id, ANALYST))
        assert provider["open_gap_count"] == 1
        outreach = validate_success(api.mark_gap_outreach_done(gaps[0]["id"], RELATIONS))
        assert outreach["status"] == "OUTREACH_DONE"
        closed = validate_success(
            api.close_gap(gaps[0]["id"], {"outcome": "CLOSED_COMPLIANT"}, RELATIONS)
        )
        assert closed["status"] == "CLOSED_COMPLIANT"
        assert closed["closure_source"] == "MANUAL"
        provider_after = validate_success(api.get_provider(provider_id, ANALYST))
        assert provider_after["open_gap_count"] == 0

    def test_gap_close_from_open_rejected(self, api):
        """Closing is possible only from OUTREACH_DONE; an OPEN gap cannot be
        closed directly.

        PRD §3.7: "A `ProviderRelations` coordinator marks outreach done, moving a gap
        from `OPEN` to `OUTREACH_DONE`. Closing is possible from `OUTREACH_DONE` with
        an `outcome` of `CLOSED_COMPLIANT` or `CLOSED_NONCOMPLIANT`"

        Design: Corner/state_machines/gap_close_from_open_rejected
        """
        scenario = setup_rate_computed_run(
            api, member_refs=("M1",),
            season_overrides={"approved_supplemental_sources": []},
        )
        gaps, _ = list_run_gaps(api, scenario["run"]["id"])
        assert gaps[0]["status"] == "OPEN"
        resp = api.close_gap(gaps[0]["id"], {"outcome": "CLOSED_COMPLIANT"}, RELATIONS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestComputeRateGuards:
    def test_denominator_zero_returns_422(self, api):
        """compute-rate with an empty eligible population is rejected.

        PRD §3.7: "Four guards apply: the run must be `POPULATED` (else
        `ERR_INVALID_STATE`); the request must carry `expected_measure_run_version`
        matching the run's current `version` (else `ERR_STALE_VERSION`, per §2.6); a
        `HYBRID` run's sample must be `FINALIZED` (a cross-entity guard, else
        `ERR_INVALID_STATE`); and `denominator_count` must exceed zero (else
        `ERR_DENOMINATOR_ZERO`)."

        Design: Corner/validations/denominator_zero_returns_422
        """
        season = create_and_open_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        run = identify_population(api, run["id"])
        assert run["denominator_count"] == 0, "no members exist, so no entries mint"
        resp = api.compute_rate(
            run["id"], {"expected_measure_run_version": run["version"]}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_DENOMINATOR_ZERO)

    def test_compute_rate_hybrid_requires_finalized_sample(self, api):
        """HYBRID compute-rate is guarded by the sample's FINALIZED state; with the
        sample still DRAWN the compute is rejected even though the run's own state
        and OCC version are valid.

        PRD §3.7: "a `HYBRID` run's sample must be `FINALIZED` (a cross-entity guard,
        else `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/compute_rate_hybrid_requires_finalized_sample
        """
        scenario = setup_hybrid_sample(api, member_refs=("M001",), floor=1)
        run = get_run(api, scenario["run"]["id"])
        assert run["reporting_status"] == "POPULATED"
        resp = api.compute_rate(
            run["id"], {"expected_measure_run_version": run["version"]}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
