"""Eligible population identification and hybrid sample drawing.

Covers inclusive age bounds, enrollment-gap allowance, the deterministic
systematic draw, the sample-size floor boundary, pre-draw exclusions, method
gating, the one-sample-per-run constraint, and list pagination.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_spec,
    create_and_open_season,
    create_exclusion_payload,
    create_run,
    create_sample_payload,
    get_run,
    identify_population,
    list_run_entries,
    register_enrolled_member,
    register_provider,
    setup_hybrid_sample,
    setup_populated_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["quality_admin_headers"]
ANALYST = TEST_USERS["quality_analyst_headers"]


class TestEligibilityAgeBounds:
    def test_eligibility_age_bounds_inclusive(self, api):
        """Whole-year age bounds are inclusive at the anchor date: exactly 50 and
        exactly 74 are eligible; 75 years and a day is not.

        PRD §3.3: "Age is computed as whole years between `birth_date` and
        `anchor_date`, and a member is skipped when that age is below `age_min` or
        above `age_max` — both bounds inclusive."
        PRD §2.3: "Where the minted order follows a business key, that order is used
        instead: population entries and chart chases list in `member_ref` ascending
        order."

        Design: Corner/calculations/eligibility_age_bounds_inclusive
        """
        season = create_and_open_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(
            api, season["id"], hedis_measure_code="AB", age_min=50, age_max=74
        )
        register_enrolled_member(api, "M-LO", birth_date="1975-12-31T00:00:00Z", gender="F")
        register_enrolled_member(api, "M-HI", birth_date="1951-12-31T00:00:00Z", gender="M")
        register_enrolled_member(api, "M-OUT", birth_date="1950-12-30T00:00:00Z", gender="F")
        run = create_run(api, season["id"], spec["id"])
        run = identify_population(api, run["id"])
        assert run["denominator_count"] == 2, (
            f"exactly-50 and exactly-74 must both be eligible; got {run['denominator_count']}"
        )
        entries, _ = list_run_entries(api, run["id"])
        assert [e["member_ref"] for e in entries] == ["M-HI", "M-LO"]


class TestEligibilityGapAllowance:
    def test_eligibility_gap_allowance_rules(self, api):
        """At most one enrollment gap of at most allowable_gap_days days is
        tolerated: one 45-day gap passes; one 46-day gap fails; two 10-day gaps fail.

        PRD §3.3: "a member is eligible exactly when there is at most one such gap and
        each gap's length is no more than `allowable_gap_days` days, where gap length
        is measured in whole days counting both the first and last uncovered day."

        Design: Corner/calculations/eligibility_gap_allowance_rules
        """
        season = create_and_open_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(
            api, season["id"], hedis_measure_code="GAP", allowable_gap_days=45
        )
        register_enrolled_member(
            api, "M-A",
            segments=[("2025-01-01T00:00:00Z", "2025-06-14T00:00:00Z"),
                      ("2025-07-30T00:00:00Z", "2025-12-31T00:00:00Z")],
        )
        register_enrolled_member(
            api, "M-B",
            segments=[("2025-01-01T00:00:00Z", "2025-06-13T00:00:00Z"),
                      ("2025-07-30T00:00:00Z", "2025-12-31T00:00:00Z")],
        )
        register_enrolled_member(
            api, "M-C",
            segments=[("2025-01-01T00:00:00Z", "2025-03-31T00:00:00Z"),
                      ("2025-04-11T00:00:00Z", "2025-06-30T00:00:00Z"),
                      ("2025-07-11T00:00:00Z", "2025-12-31T00:00:00Z")],
        )
        run = create_run(api, season["id"], spec["id"])
        run = identify_population(api, run["id"])
        assert run["denominator_count"] == 1, (
            f"only the single-45-day-gap member is eligible; got {run['denominator_count']}"
        )
        entries, _ = list_run_entries(api, run["id"])
        assert entries[0]["member_ref"] == "M-A"


class TestSystematicDraw:
    def test_systematic_draw_selection_indices(self, api):
        """The draw is deterministic: pool sorted member_ref ASC, step = pool/drawn,
        indices floor(i * step); chases inherit member_ref and attributed provider.

        PRD §3.4: "The pool is sorted by `member_ref` ascending (the business key is
        unique, so no further tie-break is needed and internal ids are never
        consulted). The `drawn_size` is the smaller of the specification's
        `sample_size_floor` and the pool size, and the `draw_step` is the pool size
        divided by `drawn_size` as a real number. Walking a zero-based counter from 0
        up to `drawn_size` minus 1, the draw selects the pool entry at the index given
        by the exact floor of the counter times `draw_step`."
        PRD §3.4: "Each selected entry's `is_sampled` flips to true, and one chart
        chase is minted per selected entry: status `REQUESTED`, `chase_round` 1, the
        chase's `member_ref` taken from the entry, and its `provider_ref` taken from
        the member's `attributed_provider_ref` — null when the member is unattributed."

        Design: Corner/calculations/systematic_draw_selection_indices
        """
        scenario = setup_hybrid_sample(
            api,
            member_refs=("M001", "M002", "M003", "M004"),
            floor=2,
            spec_overrides={"age_min": 0, "age_max": 100, "gender_requirement": "ANY"},
            season_overrides={"approved_supplemental_sources": []},
        )
        run = scenario["run"]
        sample = scenario["sample"]
        chases = scenario["chases"]
        assert run["denominator_count"] == 4
        assert sample["drawn_size"] == 2
        assert sample["draw_step"] == pytest.approx(2.0), (
            f"draw_step must be pool/drawn = 4/2; got {sample['draw_step']}"
        )
        entries, _ = list_run_entries(api, run["id"])
        assert [e["is_sampled"] for e in entries] == [True, False, True, False], (
            "indices floor(i * 4/2) = {0, 2} select M001 and M003"
        )
        assert [c["member_ref"] for c in chases] == ["M001", "M003"]
        assert chases[0]["provider_ref"] == "P1" and chases[1]["provider_ref"] == "P1"
        assert chases[0]["status"] == "REQUESTED" and chases[0]["chase_round"] == 1


class TestSampleFloorBoundary:
    def _two_run_floor_scenario(self, api):
        """One HYBRID floor-3 run with a pool of exactly 3, and a second whose pool
        drops to 2 after a valid pre-draw exclusion."""
        season = create_and_open_season(api, approved_supplemental_sources=["LAB_FEED"])
        spec = create_active_spec(
            api, season["id"], hedis_measure_code="BCS", collection_method="HYBRID",
            hybrid_policy="SAMPLE_ONLY", sample_size_floor=3,
            age_min=50, age_max=74, gender_requirement="F",
        )
        register_provider(api, "P1")
        for ref in ("M1", "M2", "M3"):
            register_enrolled_member(
                api, ref, provider_ref="P1",
                birth_date="1960-01-01T00:00:00Z", gender="F",
            )
        run1 = identify_population(api, create_run(api, season["id"], spec["id"])["id"])
        run2 = identify_population(api, create_run(api, season["id"], spec["id"])["id"])
        return season, spec, run1, run2

    def test_sample_draw_pool_exactly_at_floor_succeeds(self, api):
        """A pool whose size equals sample_size_floor satisfies the inclusive
        at-least gate.

        PRD §3.4: "the eligible pool — the run's population entries with `is_excluded`
        false — must number at least the specification's `sample_size_floor`, else
        `ERR_SAMPLE_BELOW_FLOOR`."
        PRD §3.4: "The `drawn_size` is the smaller of the specification's
        `sample_size_floor` and the pool size"

        Design: Difficulty/boundary_precision_check/sample_floor_boundary_exactly_at_floor
        """
        _season, _spec, run1, _run2 = self._two_run_floor_scenario(api)
        assert run1["denominator_count"] == 3
        sample = validate_success(api.create_sample(create_sample_payload(run1["id"]), ANALYST), 201)
        assert sample["drawn_size"] == 3

    def test_sample_draw_pool_below_floor_rejected(self, api):
        """After a valid pre-draw exclusion drops the pool to floor - 1, the draw is
        rejected.

        PRD §3.4: "the eligible pool — the run's population entries with `is_excluded`
        false — must number at least the specification's `sample_size_floor`, else
        `ERR_SAMPLE_BELOW_FLOOR`."
        PRD §3.3: "Exclusion is available on `ADMINISTRATIVE` runs and on `HYBRID`
        runs only before their sample exists"

        Design: Difficulty/boundary_precision_check/sample_floor_boundary_exactly_at_floor
        """
        _season, _spec, _run1, run2 = self._two_run_floor_scenario(api)
        entries, _ = list_run_entries(api, run2["id"])
        assert entries[2]["member_ref"] == "M3"
        validate_success(
            api.exclude_population_entry(
                entries[2]["id"], create_exclusion_payload("DISENROLLED"), ANALYST
            )
        )
        resp = api.create_sample(create_sample_payload(run2["id"]), ANALYST)
        validate_error(resp, ApiErrorId.ERR_SAMPLE_BELOW_FLOOR)


class TestPopulationEntryExclusion:
    def test_population_entry_exclude_action(self, api):
        """A pre-draw exclusion flips is_excluded, records the reason, and moves the
        run counters by exactly one.

        PRD §3.3: "The request carries a `reason`; the entry's `is_excluded` flips to
        true and `exclusion_reason` records the supplied text, the run's
        `exclusion_count` increments by 1 and its `denominator_count` decrements by 1,
        and both the entry's and the run's `version` increment."

        Design: Corner/endpoints/population_entry_exclude_action
        """
        scenario = setup_populated_run(
            api, member_refs=("M1", "M2"),
            season_overrides={"approved_supplemental_sources": []},
        )
        run = scenario["run"]
        entries, _ = list_run_entries(api, run["id"])
        assert entries[0]["member_ref"] == "M1"
        excluded = validate_success(
            api.exclude_population_entry(
                entries[0]["id"], create_exclusion_payload("DISENROLLED"), ANALYST
            )
        )
        assert excluded["is_excluded"] is True
        assert excluded["exclusion_reason"] == "DISENROLLED"
        run_after = get_run(api, run["id"])
        assert run_after["denominator_count"] == 1
        assert run_after["exclusion_count"] == 1

    def test_exclusion_after_draw_returns_422(self, api):
        """Once the hybrid run's sample exists, the exclusion endpoint rejects the
        attempt.

        PRD §3.3: "Exclusion is available on `ADMINISTRATIVE` runs and on `HYBRID`
        runs only before their sample exists; once a hybrid run's sample has been
        drawn, the exclusion attempt is rejected with `ERR_EXCLUSION_NOT_ALLOWED`."

        Design: Corner/validations/exclusion_after_draw_returns_422
        """
        scenario = setup_hybrid_sample(
            api, member_refs=("M001",), floor=1,
            spec_overrides={"age_min": 0, "age_max": 100},
            season_overrides={"approved_supplemental_sources": []},
        )
        entries, _ = list_run_entries(api, scenario["run"]["id"])
        resp = api.exclude_population_entry(
            entries[0]["id"], create_exclusion_payload("DISENROLLED"), ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_EXCLUSION_NOT_ALLOWED)


class TestSampleDrawGates:
    def test_method_gate_sample_on_admin_run_returns_422(self, api):
        """Drawing a sample on an ADMINISTRATIVE run is rejected by the method gate.

        PRD §3.4: "Three gates precede the draw: the run's `collection_method` must be
        `HYBRID` — drawing on an administrative run is rejected with
        `ERR_METHOD_NOT_HYBRID`"

        Design: Corner/validations/method_gate_sample_on_admin_run_returns_422
        """
        scenario = setup_populated_run(
            api, member_refs=("M1",),
            season_overrides={"approved_supplemental_sources": []},
        )
        assert scenario["run"]["collection_method"] == "ADMINISTRATIVE"
        resp = api.create_sample(create_sample_payload(scenario["run"]["id"]), ANALYST)
        validate_error(resp, ApiErrorId.ERR_METHOD_NOT_HYBRID)

    def test_sample_already_exists_returns_409(self, api):
        """At most one sample per run: the second draw is rejected.

        PRD §3.4: "at most one sample may exist per run — a second draw is rejected
        with `ERR_SAMPLE_ALREADY_EXISTS`"

        Design: Corner/validations/sample_already_exists_returns_409
        """
        scenario = setup_hybrid_sample(
            api, member_refs=("M001",), floor=1,
            spec_overrides={"age_min": 0, "age_max": 100},
            season_overrides={"approved_supplemental_sources": []},
        )
        resp = api.create_sample(create_sample_payload(scenario["run"]["id"]), ANALYST)
        validate_error(resp, ApiErrorId.ERR_SAMPLE_ALREADY_EXISTS)


class TestPopulationEntryPagination:
    def test_population_entries_list_pagination_envelope(self, api):
        """List endpoints honor limit/offset and report the pagination fields;
        population entries list in member_ref ascending order.

        PRD §2.3: "Paginated responses report `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object."
        PRD §2.3: "Where the minted order follows a business key, that order is used
        instead: population entries and chart chases list in `member_ref` ascending
        order."

        Design: Corner/endpoints/population_entries_list_pagination_envelope
        """
        scenario = setup_populated_run(
            api, member_refs=("M1", "M2", "M3"),
            season_overrides={"approved_supplemental_sources": []},
        )
        run_id = scenario["run"]["id"]
        page1, meta1 = validate_paginated(
            api.list_run_population_entries(run_id, ANALYST, params={"limit": 2})
        )
        assert [e["member_ref"] for e in page1] == ["M1", "M2"]
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_run_population_entries(
                run_id, ANALYST, params={"limit": 2, "offset": 2}
            )
        )
        assert [e["member_ref"] for e in page2] == ["M3"]
        assert meta2["has_more"] is False
