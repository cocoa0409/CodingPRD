"""Specification lifecycle, season transitions, and optimistic concurrency.

Covers retire guards, double-open rejection, clock-driven auto-close, OCC on
spec load and rate computation, and the validation-band ordering between them.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_spec,
    create_and_open_season,
    create_run,
    create_season,
    create_spec_payload,
    get_season,
    identify_population,
    load_spec,
    register_enrolled_member,
    set_clock,
    setup_populated_run,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["quality_admin_headers"]
ANALYST = TEST_USERS["quality_analyst_headers"]


class TestSeasonTransitions:
    def test_season_double_open_rejected(self, api):
        """Open is legal only from DRAFT; the second open is rejected and the season
        stays OPEN.

        PRD §3.1: "Opening the season transitions it from `DRAFT` to `OPEN`; the
        transition is only legal from `DRAFT` and otherwise fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/season_double_open_rejected
        """
        season = create_and_open_season(api, approved_supplemental_sources=[])
        resp = api.open_season(season["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_season(api, season["id"])
        assert after["status"] == "OPEN", f"season must stay OPEN, got {after['status']}"

    def test_season_auto_close_on_clock_advance_past_deadline(self, api):
        """Advancing the clock to exactly the deadline does not close the season
        (the rule is strictly-earlier); advancing one day past it does.

        PRD §2.5: "Advancing the clock has one system-wide side effect: any season in
        `OPEN` status whose `submission_deadline` is strictly earlier than the new
        clock instant auto-transitions to `SUBMISSION_CLOSED`, with the season's
        `version` incremented by 1."

        Design: Corner/state_machines/season_auto_close_on_clock_advance_past_deadline
        """
        season = create_and_open_season(
            api,
            submission_deadline="2026-06-15T00:00:00Z",
            approved_supplemental_sources=[],
        )
        set_clock(api, "2026-06-15T00:00:00Z")
        at = get_season(api, season["id"])
        assert at["status"] == "OPEN", (
            f"deadline equal to clock is not strictly earlier; season is {at['status']}"
        )
        set_clock(api, "2026-06-16T00:00:00Z")
        past = get_season(api, season["id"])
        assert past["status"] == "SUBMISSION_CLOSED", (
            f"clock past deadline must auto-close the season; got {past['status']}"
        )


class TestSpecRetireGuards:
    def test_spec_retire_guarded_by_active_runs(self, api):
        """A LOADED spec with no runs retires; an ACTIVE spec with a
        POPULATION_PENDING run cannot.

        PRD §3.1: "retiring from `ACTIVE` is blocked while any run pinned to that
        specification still has `reporting_status` in `POPULATION_PENDING`,
        `POPULATED`, `RATE_COMPUTED`, or `SUBMITTED` (a run that has reached
        `CERTIFIED` or `CERTIFICATION_FAILED` no longer blocks), whereas retiring from
        `LOADED` has no such guard."

        Design: Corner/state_machines/spec_retire_guarded_by_active_runs
        """
        season = create_season(api, approved_supplemental_sources=[])
        free_spec = load_spec(api, season["id"], hedis_measure_code="FREEBIE")
        cbp_spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], cbp_spec["id"])
        assert run["reporting_status"] == "POPULATION_PENDING"

        resp_free = api.retire_spec(free_spec["id"], ADMIN)
        retired = validate_success(resp_free)
        assert retired["status"] == "RETIRED"

        resp_cbp = api.retire_spec(cbp_spec["id"], ADMIN)
        validate_error(resp_cbp, ApiErrorId.ERR_INVALID_STATE)


class TestRunPopulationGuard:
    def test_identify_population_twice_rejected(self, api):
        """Population identification is not idempotent: the second call finds the
        run no longer POPULATION_PENDING.

        PRD §3.3: "Two preconditions guard it: the run must still be
        `POPULATION_PENDING`, and — a version-pinning revalidation — the run's pinned
        specification must still be `ACTIVE`; either failure is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/identify_population_twice_rejected
        """
        scenario = setup_populated_run(api, member_refs=("M1",),
                                       season_overrides={"approved_supplemental_sources": []})
        run = scenario["run"]
        assert run["reporting_status"] == "POPULATED"
        resp = api.identify_population(run["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOptimisticConcurrency:
    def test_occ_stale_spec_load_returns_412(self, api):
        """A spec load carrying the season version observed before another load is
        rejected as stale.

        PRD §2.6: "If the season's current `version` has advanced since — for example
        because another specification was loaded into the same season in the meantime,
        or the season was opened — the load is rejected with `ERR_STALE_VERSION`
        (HTTP 412), forcing the client to re-read the season before writing."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_spec_load_returns_412
        """
        season = create_season(api, approved_supplemental_sources=[])
        stale_version = season["version"]
        first = load_spec(api, season["id"], hedis_measure_code="BCS")
        assert first["status"] == "LOADED"
        payload = create_spec_payload(
            season["id"], stale_version, hedis_measure_code="CBP"
        )
        resp = api.create_spec(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_spec_load_success_increments_season_version(self, api):
        """A spec load carrying the current season version succeeds and the season
        version advances by exactly one.

        PRD §3.1: "The load must also carry `expected_season_version` under the
        optimistic-concurrency rule of §2.6, because the load itself increments the
        season's `version` by 1 — a client holding a stale season view is rejected
        with `ERR_STALE_VERSION`."
        PRD §3.1: "A freshly loaded specification sits in `LOADED` status."

        Design: Corner/cross_cutting_complexity_layers/occ_spec_load_success_increments_season_version
        """
        season = create_season(api, approved_supplemental_sources=[])
        version_before = season["version"]
        spec = load_spec(api, season["id"], hedis_measure_code="BCS")
        assert spec["status"] == "LOADED"
        season_after = get_season(api, season["id"])
        assert season_after["version"] == version_before + 1, (
            f"season version must increment by exactly 1 per load: "
            f"{version_before} -> {season_after['version']}"
        )

    def test_occ_stale_compute_rate_returns_412(self, api):
        """Compute-rate carrying the run version observed before
        identify-population is rejected as stale.

        PRD §2.6: "If the run's current `version` has advanced since — because
        population was identified, an exclusion was applied, a supplemental batch was
        accepted, or any other run mutation landed — the recompute is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_compute_rate_returns_412
        """
        season = create_and_open_season(api, approved_supplemental_sources=[])
        spec = create_active_spec(api, season["id"], hedis_measure_code="CBP")
        register_enrolled_member(api, "M1")
        run = create_run(api, season["id"], spec["id"])
        stale_version = run["version"]
        identify_population(api, run["id"])
        resp = api.compute_rate(
            run["id"], {"expected_measure_run_version": stale_version}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_checked_before_state_returns_412(self, api):
        """A stale expected version is reported before the state-machine violation
        on the same request: the run is POPULATION_PENDING (compute-rate invalid)
        and the version is stale, and the stale-version error wins.

        PRD §2.9: "A stale run version surfaces before a state-machine violation on
        the same request; a submission from a non-`RATE_COMPUTED` run surfaces
        `ERR_RUN_NOT_SUBMITTABLE` even when the season is also closed; a batch from an
        unapproved source surfaces `ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE` even when its
        records also reference strangers to the denominator."

        Design: Corner/validations/occ_checked_before_state_returns_412
        """
        season = create_season(api, approved_supplemental_sources=[])
        spec = load_spec(api, season["id"], hedis_measure_code="CBP")
        run = create_run(api, season["id"], spec["id"])
        assert run["reporting_status"] == "POPULATION_PENDING"
        resp = api.compute_rate(
            run["id"], {"expected_measure_run_version": run["version"] - 1}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
