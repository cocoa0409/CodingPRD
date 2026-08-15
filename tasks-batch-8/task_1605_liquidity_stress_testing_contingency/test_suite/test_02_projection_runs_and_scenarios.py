"""Projection runs: dual-variant divergence, OCC, supersede, finalize, breaches.

Difficulty instances covered: projection_contractual_vs_behavioral_divergence.
Corner instances: finalize_finalized_run_returns_invalid_state,
survival_days_limit_breach_on_finalize, run_create_supersede_and_stale_version,
scenario_retirement_guards.
"""
from test_helpers import (
    ApiErrorId,
    assert_limit_breach,
    assert_projection_run,
    create_board_limit_payload,
    create_projection_run_payload,
    create_scenario_payload,
    make_asset,
    make_funding_source,
    make_projection_run,
    make_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _funding_for_projection(api):
    """Retail 1e9 (non-maturity), W1 6e8 day 5, W2 4e8 day 12, LEVEL_1 5e8 buffer."""
    make_funding_source(counterparty_name="RetailPool", channel="RETAIL_DEPOSIT",
                        balance_cents=1_000_000_000)
    make_funding_source(counterparty_name="W1", channel="WHOLESALE_UNSECURED",
                        balance_cents=600_000_000, matures_in_days=5)
    make_funding_source(counterparty_name="W2", channel="WHOLESALE_SECURED",
                        balance_cents=400_000_000, matures_in_days=12)
    make_asset(asset_class="LEVEL_1", reference="BUF", market_value_cents=500_000_000)


def _moderate_scenario():
    return make_scenario(
        name="Mod", tier="MODERATE", deposit_runoff_pct=10,
        wholesale_renewal_pct=50, level2_addon_bps=500, horizon_days=10,
    )


class TestDualVariantProjection:
    def test_projection_contractual_totals(self, api, analyst_headers):
        """PRD §3.2: "Under the `CONTRACTUAL` variant, each funding source pays
        out its full `balance_cents` on the day it contractually matures: the
        outflow on a given day is the sum of balances over every source whose
        `matures_in_days` equals that day number."
        PRD §3.2: "Finalization also captures `hqla_available_cents` — the
        STRESS-variant adjusted value, under this run's scenario, of every
        asset currently `UNENCUMBERED` (§3.3) — and derives `survival_days`:
        the earliest day on which the cumulative net position plus
        `hqla_available_cents` falls strictly below zero, or `horizon_days`
        itself when the buffer never runs out."

        Design: Difficulty/dual_variant_calc/projection_contractual_vs_behavioral_divergence
        """
        scenario = _moderate_scenario()
        _funding_for_projection(api)

        run_c = make_projection_run(scenario["id"], "CONTRACTUAL", scenario["version"])
        resp = api.finalize_projection_run(run_c["id"], analyst_headers)
        finalized_c = validate_success(resp)
        assert_projection_run(finalized_c)
        assert finalized_c["status"] == "FINALIZED"
        # Only W1 (600000000, day 5) matures inside the 10-day horizon.
        assert finalized_c["total_outflows_cents"] == 600_000_000, (
            f"CONTRACTUAL outflows must be the full 600000000 of the day-5 maturity, "
            f"got {finalized_c['total_outflows_cents']}"
        )
        assert finalized_c["net_cumulative_gap_cents"] == -600_000_000
        # LEVEL_1 carries no add-on even under the STRESS variant.
        assert finalized_c["hqla_available_cents"] == 500_000_000
        # Day 5 cumulative net -600000000 + 500000000 < 0 -> survival at day 5.
        assert finalized_c["survival_days"] == 5, (
            f"survival_days must be 5 (day-5 cumulative breaches the buffer), "
            f"got {finalized_c['survival_days']}"
        )

    def test_projection_behavioral_totals_diverge(self, api, analyst_headers):
        """PRD §3.2: "Under the `BEHAVIORAL` variant the picture diverges on
        identical inputs."
        PRD §3.2: "each such source maturing on a given day contributes its
        balance multiplied by the non-renewing share (one hundred minus the
        scenario's `wholesale_renewal_pct`), divided by one hundred, and
        rounded down to whole cents."
        PRD §3.2: "each retail source, whatever its `matures_in_days` —
        including sources with no maturity at all — contributes on every day of
        the horizon an amount equal to its balance times the scenario's
        `deposit_runoff_pct`, divided by one hundred, then divided by the
        number of days in the horizon, rounded down to whole cents."
        PRD §3.2: "Sources maturing beyond the horizon, and non-maturity
        sources outside the retail runoff, contribute nothing to the outflows."

        Design: Difficulty/dual_variant_calc/projection_contractual_vs_behavioral_divergence
        """
        scenario = _moderate_scenario()
        _funding_for_projection(api)

        run_b = make_projection_run(scenario["id"], "BEHAVIORAL", scenario["version"])
        resp = api.finalize_projection_run(run_b["id"], analyst_headers)
        finalized_b = validate_success(resp)
        assert_projection_run(finalized_b)
        # W1 renewed at 50% -> 300000000 at day 5; retail runoff
        # floor(1000000000 * 10 / 100 / 10) = 10000000 per day x 10 days = 100000000;
        # W2 (day 12) matures beyond the horizon and contributes nothing.
        assert finalized_b["total_outflows_cents"] == 400_000_000, (
            f"BEHAVIORAL outflows must be 300000000 + 100000000 = 400000000, "
            f"got {finalized_b['total_outflows_cents']}"
        )
        assert finalized_b["net_cumulative_gap_cents"] == -400_000_000
        # Cumulative net never exceeds the 500000000 buffer -> horizon fallback.
        assert finalized_b["survival_days"] == 10, (
            f"survival_days must fall back to horizon_days 10, got {finalized_b['survival_days']}"
        )

        # Identical inputs, divergent variants: a CONTRACTUAL run over the same
        # data produces different totals.
        scenario_now = validate_success(api.get_scenario(scenario["id"], analyst_headers))
        run_c = make_projection_run(scenario["id"], "CONTRACTUAL", scenario_now["version"])
        finalized_c = validate_success(api.finalize_projection_run(run_c["id"], analyst_headers))
        assert finalized_c["total_outflows_cents"] == 600_000_000
        assert finalized_c["total_outflows_cents"] != finalized_b["total_outflows_cents"]


class TestFinalizeGuards:
    def test_finalize_finalized_run_returns_invalid_state(self, api, analyst_headers):
        """PRD §3.9: "Every transition in this section is available only from
        its named from-state; invoking one against a playbook or action
        standing in any other status is rejected with `ERR_INVALID_STATE`."
        PRD §3.2: "Finalization — a `TreasuryAnalyst` action moving a run
        `DRAFT` → `FINALIZED`".

        Design: Corner/state_machines/finalize_finalized_run_returns_invalid_state
        """
        scenario = _moderate_scenario()
        run = make_projection_run(scenario["id"], "CONTRACTUAL", scenario["version"])
        first = validate_success(api.finalize_projection_run(run["id"], analyst_headers))
        assert first["status"] == "FINALIZED"
        resp = api.finalize_projection_run(run["id"], analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSurvivalDaysBreach:
    def test_survival_days_limit_breach_on_finalize(self, api, analyst_headers, officer_headers):
        """PRD §3.2: "breach detection runs immediately against every board
        limit whose subject is `SURVIVAL_DAYS`, attributing any new breach to
        `source_type` `PROJECTION_FINALIZE` with `source_id` pointing at this
        run."
        PRD §3.7: "`BELOW_BREACHES` breaches only when strictly below".

        Design: Corner/calculations/survival_days_limit_breach_on_finalize
        """
        scenario = _moderate_scenario()
        _funding_for_projection(api)
        limit_resp = api.create_board_limit(
            create_board_limit_payload(
                subject="SURVIVAL_DAYS", direction="BELOW_BREACHES",
                limit_value=10, severity="REGULATORY",
            ),
            officer_headers,
        )
        limit = validate_success(limit_resp, expected_status=201)

        run = make_projection_run(scenario["id"], "CONTRACTUAL", scenario["version"])
        finalized = validate_success(api.finalize_projection_run(run["id"], analyst_headers))
        assert finalized["survival_days"] == 5

        breaches, meta = validate_paginated(api.list_limit_breaches(limit["id"], officer_headers))
        assert len(breaches) == 1, f"survival 5 below limit 10 must raise one breach, got {len(breaches)}"
        breach = breaches[0]
        assert_limit_breach(breach)
        assert breach["detected_value"] == 5, (
            f"detected_value must be the breaching survival_days 5, got {breach['detected_value']}"
        )
        assert breach["source_type"] == "PROJECTION_FINALIZE", (
            f"source_type must be PROJECTION_FINALIZE, got {breach['source_type']}"
        )
        assert breach["source_id"] == run["id"], "source_id must point at the finalized run"
        assert breach["status"] == "OPEN"


class TestRunCreateOccAndSupersede:
    def test_run_create_supersedes_draft_and_bumps_scenario(self, api, analyst_headers):
        """PRD §3.2: "Creation is superseding: any existing `DRAFT` run for the
        same scenario and the same variant becomes `DISCARDED` as part of the
        same request, so at most one draft ever exists per scenario-and-variant
        pair. Creation also advances the scenario's `run_count` by one and
        bumps the scenario's `version` by one."

        Design: Corner/cross_cutting_layers/run_create_supersede_and_stale_version
        """
        scenario = _moderate_scenario()
        assert scenario["version"] == 1
        run_a = make_projection_run(scenario["id"], "CONTRACTUAL", scenario["version"])

        scenario_now = validate_success(api.get_scenario(scenario["id"], analyst_headers))
        assert scenario_now["run_count"] == 1, (
            f"run_count must advance by one per created run, got {scenario_now['run_count']}"
        )
        assert scenario_now["version"] == 2, (
            f"scenario version must bump on run creation, got {scenario_now['version']}"
        )

        run_b = make_projection_run(scenario["id"], "CONTRACTUAL", scenario_now["version"])
        run_a_now = validate_success(api.get_projection_run(run_a["id"], analyst_headers))
        assert run_a_now["status"] == "DISCARDED", (
            f"the older same-variant draft must be DISCARDED, got {run_a_now['status']}"
        )
        assert run_b["status"] == "DRAFT"

    def test_run_create_with_stale_scenario_version_rejected(self, api, analyst_headers):
        """PRD §2.7: "A `POST /liquidity/stress-scenarios/{id}/projection-runs`
        request must carry `expected_scenario_version` equal to the scenario's
        current `version`. Run creation legitimately discards any existing
        draft run for the same scenario and model variant and advances the
        scenario's version through `run_count`, so a writer holding a stale
        scenario version would otherwise silently discard a draft it never
        observed; the mismatch is rejected instead."

        Design: Corner/cross_cutting_layers/run_create_supersede_and_stale_version
        """
        scenario = _moderate_scenario()
        stale_version = scenario["version"]
        make_projection_run(scenario["id"], "CONTRACTUAL", stale_version)
        # stale_version (1) is now behind the scenario's current version (2).
        resp = api.create_projection_run(
            scenario["id"],
            create_projection_run_payload(
                model_variant="BEHAVIORAL", as_of_date="2026-08-01",
                expected_scenario_version=stale_version,
            ),
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestScenarioRetirement:
    def test_scenario_retirement_guards(self, api, officer_headers, analyst_headers):
        """PRD §3.1: "The desk keeps at most one `ACTIVE` scenario per tier:
        creating a scenario for a tier that already has an active one is
        rejected with `ERR_DUPLICATE_ACTIVE_SCENARIO`."
        PRD §3.1: "A `BASELINE` scenario cannot be retired while it is the last
        active baseline — at least one other `ACTIVE` scenario of tier
        `BASELINE` must exist, or the request fails with
        `ERR_LAST_BASELINE_SCENARIO`. Independently, a scenario that still has
        a projection run in `DRAFT` status cannot be retired at all
        (`ERR_SCENARIO_IN_USE`); finalized history does not block retirement.
        Once retired, a scenario refuses further modeling use: creating a new
        projection run against it, or finalizing an existing draft run of it,
        is rejected with `ERR_SCENARIO_RETIRED`."

        Design: Corner/validations/scenario_retirement_guards
        """
        base = make_scenario(name="B", tier="BASELINE")
        mod = make_scenario(name="M", tier="MODERATE", deposit_runoff_pct=10,
                            wholesale_renewal_pct=50, level2_addon_bps=500, horizon_days=10)
        sev = make_scenario(name="S", tier="SEVERE", deposit_runoff_pct=25,
                            wholesale_renewal_pct=0, level2_addon_bps=1000)
        make_projection_run(sev["id"], "CONTRACTUAL", sev["version"])  # leaves a DRAFT on S

        # Last ACTIVE BASELINE cannot retire.
        resp = api.retire_scenario(base["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_LAST_BASELINE_SCENARIO)

        # A scenario holding a DRAFT run cannot retire.
        resp = api.retire_scenario(sev["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_SCENARIO_IN_USE)

        # MODERATE (not BASELINE, no DRAFT runs) retires cleanly.
        retired = validate_success(api.retire_scenario(mod["id"], officer_headers))
        assert retired["status"] == "RETIRED", f"got {retired['status']}"

        # A retired scenario refuses new runs (its version is unchanged by retirement).
        resp = api.create_projection_run(
            mod["id"],
            create_projection_run_payload(
                model_variant="CONTRACTUAL", as_of_date="2026-08-01",
                expected_scenario_version=retired["version"],
            ),
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCENARIO_RETIRED)

        # A second ACTIVE scenario for an occupied tier is rejected.
        resp = api.create_scenario(
            create_scenario_payload(name="B2", tier="BASELINE"), officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_SCENARIO)
