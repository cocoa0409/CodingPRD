"""Cross-cutting validation ordering: which rule wins when a request breaks several.

Every test in this file sets up a state in which more than one rule of a declared
check order would fire, and pins the one error the PRD says the caller must see —
plus the satisfaction case that proves the gate is data-dependent rather than
always-on.
"""

from datetime import datetime, timedelta

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    expected_contribution,
    expected_impact_delta_pct,
    expected_impact_tier,
    expected_projected_average_audience,
)
from test_helpers.constants import LEAD_HOURS_MINOR
from test_helpers.factories import cell_population, next_serial_no
from test_helpers.fixtures import (
    CLOCK_T1,
    VINTAGE_FROM,
    VINTAGE_TO,
    PanelHarness,
)
from test_helpers.test_users import DIRECTOR_USER_ID


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ======================================================================
# The incentive budget ceiling
# ======================================================================

def _ceiling_market(panel: PanelHarness) -> dict:
    """A 6000-cent market whose two armed cells already reserve 3000 cents.

    Cell A takes `round_half_up(2000 * 0.25 * 4, 0)` == 2000 and cell B takes
    `round_half_up(1000 * 0.25 * 4, 0)` == 1000. One ACTIVE household sits in
    cell A, whose fill rate is 1 / 4 == 0.2500, so cell A stays `UNDER_TARGET`
    with its boost armed and every accrual is priced at the boosted multiplier.
    """
    market = panel.create_market(incentive_budget_cents=6000)
    cell_a = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=4,
        base_incentive_cents=2000,
    )
    cell_b = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="SUBURBAN",
        target_households=4,
        base_incentive_cents=1000,
    )
    built = panel.active_household(market["id"], cell_a["id"], persons_count=2)
    return {
        "market": market,
        "cell_a": cell_a,
        "cell_b": cell_b,
        "household": built["household"],
    }


def _at_ceiling_market(panel: PanelHarness) -> dict:
    """The same market topped up to 9000 cents with two periods accrued.

    Committed is then 5000 cents and reserved is still 3000, so exactly 1000
    cents of headroom remain.
    """
    base = _ceiling_market(panel)
    panel.accrue(base["household"]["id"], period_label="2026-08")
    validate_success(
        panel.client.adjust_market_budget(
            panel.ops, base["market"]["id"], delta_cents=3000, memo="Q4 top-up"
        ),
        200,
    )
    panel.accrue(base["household"]["id"], period_label="2026-09")
    return base


class TestIncentiveBudgetCeiling:
    """The ceiling counts committed, reserved and the amount about to commit."""

    def test_an_accrual_clears_the_ceiling_with_only_reserved_money_in_the_way(
        self, panel: PanelHarness
    ):
        """An accrual passes while 3000 merely reserved cents sit against a 6000 budget.

        PRD 3.4: "The market's `incentive_budget_committed_cents` plus its
        `incentive_budget_reserved_cents` plus the amount about to be committed
        must not exceed `incentive_budget_cents`, otherwise
        `ERR_INCENTIVE_BUDGET_EXCEEDED`."

        PRD 3.4: "The cell base is the quota cell's `base_incentive_cents`
        multiplied by the cell's `effective_incentive_multiplier`, rounded to a
        whole cent." At tenure 0 the multiplier of step 2 is "1.000 for a tenure
        under 6 months", the compliance bonus needs a rolling rate of "0.90 or
        more" and there is neither a `PORTABLE_OOH` meter nor a faulted one, so
        the period amount is 2000 * 1.25 == 2500 cents.

        Design: Corner/validations/incentive_budget_ceiling_counts_committed_and_reserved_together
        """
        base = _ceiling_market(panel)

        accrued = panel.accrue(base["household"]["id"], period_label="2026-08")

        assert accrued["incentive_accrued_cents"] == 2500
        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 3000
        assert market["incentive_budget_committed_cents"] == 2500

    def test_a_second_accrual_is_refused_by_money_that_is_only_reserved(
        self, panel: PanelHarness
    ):
        """2500 committed + 3000 reserved + 2500 about to commit exceeds 6000.

        PRD 3.4: "The market's `incentive_budget_committed_cents` plus its
        `incentive_budget_reserved_cents` plus the amount about to be committed
        must not exceed `incentive_budget_cents`, otherwise
        `ERR_INCENTIVE_BUDGET_EXCEEDED`."

        PRD 2.9: "A market's `incentive_budget_reserved_cents` is, at all times,
        precisely the sum, over the market's quota cells whose
        `incentive_boost_active` is true, of the boost reservation for that
        cell." The 3000 blocking cents are therefore reserved by armed boosts —
        one of them on a cell this household does not even belong to — and not
        spent.

        Design: Corner/validations/incentive_budget_ceiling_counts_committed_and_reserved_together
        """
        base = _ceiling_market(panel)
        panel.accrue(base["household"]["id"], period_label="2026-08")

        response = panel.client.accrue_incentive(
            panel.ops, base["household"]["id"], period_label="2026-09"
        )

        validate_error(response, "ERR_INCENTIVE_BUDGET_EXCEEDED")
        household = panel.read_household(base["household"]["id"])
        assert household["incentive_accrued_cents"] == 2500
        assert len(household["accrual_periods"]) == 1

    def test_a_budget_top_up_lets_the_refused_accrual_through(self, panel: PanelHarness):
        """Raising the authorisation to 9000 admits the very same request.

        PRD 3.1: "The market's `incentive_budget_cents` moves by that delta and
        the market's `version` advances by one."

        PRD 3.4: "The market's `incentive_budget_committed_cents` plus its
        `incentive_budget_reserved_cents` plus the amount about to be committed
        must not exceed `incentive_budget_cents`, otherwise
        `ERR_INCENTIVE_BUDGET_EXCEEDED`." 2500 + 3000 + 2500 == 8000 is now
        inside the ceiling.

        Design: Corner/validations/incentive_budget_ceiling_counts_committed_and_reserved_together
        """
        base = _ceiling_market(panel)
        panel.accrue(base["household"]["id"], period_label="2026-08")
        before = panel.read_market(base["market"]["id"])

        adjusted = validate_success(
            panel.client.adjust_market_budget(
                panel.ops, base["market"]["id"], delta_cents=3000, memo="Q4 top-up"
            ),
            200,
        )

        assert adjusted["incentive_budget_cents"] == 9000
        assert adjusted["version"] == before["version"] + 1

        accrued = panel.accrue(base["household"]["id"], period_label="2026-09")

        assert accrued["incentive_accrued_cents"] == 5000
        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_committed_cents"] == 5000

    def test_a_new_cell_landing_exactly_on_the_ceiling_is_accepted(
        self, panel: PanelHarness
    ):
        """5000 committed + 3000 reserved + a 1000-cent reservation equals 9000 exactly.

        PRD 3.1: "first the incentive-budget headroom check described in §3.4,
        which rejects with `ERR_INCENTIVE_BUDGET_EXCEEDED` if the boost
        reservation the new cell is about to take would push the market's
        committed plus reserved cents past `incentive_budget_cents`".

        PRD 3.4: the rule is that the total "must not exceed
        `incentive_budget_cents`", so a total landing exactly on the ceiling is
        admitted.

        Design: Corner/validations/incentive_budget_ceiling_counts_committed_and_reserved_together
        """
        base = _at_ceiling_market(panel)

        cell = panel.create_quota_cell(
            base["market"]["id"],
            age_band="P35_54",
            income_band="HIGH",
            geo_zone="SUBURBAN",
            target_households=4,
            base_incentive_cents=1000,
        )

        assert cell["incentive_boost_active"] is True
        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 4000
        assert market["incentive_budget_committed_cents"] == 5000

    def test_a_new_cell_one_hundred_cents_over_the_ceiling_is_refused(
        self, panel: PanelHarness
    ):
        """A cell reserving only 100 cents is still refused once the ceiling is met.

        PRD 3.1: "first the incentive-budget headroom check described in §3.4,
        which rejects with `ERR_INCENTIVE_BUDGET_EXCEEDED` if the boost
        reservation the new cell is about to take would push the market's
        committed plus reserved cents past `incentive_budget_cents`".

        PRD 3.1: "`quota_cell_count` is the number of quota cells belonging to
        the market", so the refused cell was never created.

        Design: Corner/validations/incentive_budget_ceiling_counts_committed_and_reserved_together
        """
        base = _at_ceiling_market(panel)
        panel.create_quota_cell(
            base["market"]["id"],
            age_band="P35_54",
            income_band="HIGH",
            geo_zone="SUBURBAN",
            target_households=4,
            base_incentive_cents=1000,
        )

        response = panel.client.create_quota_cell(
            panel.ops,
            base["market"]["id"],
            age_band="P35_54",
            income_band="HIGH",
            geo_zone="URBAN",
            target_households=4,
            base_incentive_cents=100,
        )

        validate_error(response, "ERR_INCENTIVE_BUDGET_EXCEEDED")
        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_committed_cents"] == 5000
        assert market["incentive_budget_reserved_cents"] == 4000
        assert market["quota_cell_count"] == 3
        assert market["under_target_cell_count"] == 3


# ======================================================================
# Universe drafting: cell coverage before the effectivity window
# ======================================================================

def _coverage_market(panel: PanelHarness) -> dict:
    """A market with two quota cells, plus a foreign market's cell to borrow."""
    market = panel.create_market()
    cell_a = panel.create_quota_cell(market["id"], geo_zone="URBAN")
    cell_b = panel.create_quota_cell(market["id"], geo_zone="SUBURBAN")
    other_market = panel.create_market()
    other_cell = panel.create_quota_cell(other_market["id"])
    return {
        "market": market,
        "cell_a": cell_a,
        "cell_b": cell_b,
        "other_market": other_market,
        "other_cell": other_cell,
    }


def _draft_attempt(panel: PanelHarness, market_id: str, cell_ids, **overrides):
    """Raw `POST /universe-estimates` carrying the market's current version."""
    overrides.setdefault("vintage_label", "2026Q3")
    overrides.setdefault("effective_from", VINTAGE_FROM)
    overrides.setdefault("effective_to", VINTAGE_TO)
    return panel.client.create_universe_estimate(
        panel.statistician,
        market_id=market_id,
        cell_populations=[cell_population(cell_id) for cell_id in cell_ids],
        expected_market_version=panel.market_version(market_id),
        **overrides,
    )


class TestUniverseCoverageOutranksTheWindow:
    """Coverage (check 2) is reported before the range order (check 3)."""

    def test_an_omitted_cell_outranks_a_reversed_effectivity_range(
        self, panel: PanelHarness
    ):
        """One cell named out of two, with `effective_from` after `effective_to`.

        PRD 3.5: "`cell_populations` must name every quota cell of the target
        market exactly once — no cell omitted, no duplicate `quota_cell_id`, and
        no cell belonging to another market — otherwise
        `ERR_UNIVERSE_CELL_COVERAGE`."

        PRD 3.5: "`effective_from` must be strictly before `effective_to`,
        otherwise `ERR_INVALID_WINDOW`." Coverage is check 2 and the range is
        check 3, so the coverage failure is the one reported.

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)

        response = _draft_attempt(
            panel,
            base["market"]["id"],
            [base["cell_a"]["id"]],
            effective_from=VINTAGE_TO,
            effective_to=VINTAGE_FROM,
        )

        validate_error(response, "ERR_UNIVERSE_CELL_COVERAGE")

    def test_a_duplicated_cell_id_is_a_coverage_failure(self, panel: PanelHarness):
        """Both cells named, but one of them twice.

        PRD 3.5: "`cell_populations` must name every quota cell of the target
        market exactly once — no cell omitted, no duplicate `quota_cell_id`, and
        no cell belonging to another market — otherwise
        `ERR_UNIVERSE_CELL_COVERAGE`."

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)

        response = _draft_attempt(
            panel,
            base["market"]["id"],
            [base["cell_a"]["id"], base["cell_b"]["id"], base["cell_b"]["id"]],
        )

        validate_error(response, "ERR_UNIVERSE_CELL_COVERAGE")

    def test_a_cell_belonging_to_another_market_is_a_coverage_failure(
        self, panel: PanelHarness
    ):
        """Both own cells named plus a foreign market's cell.

        PRD 3.5: "`cell_populations` must name every quota cell of the target
        market exactly once — no cell omitted, no duplicate `quota_cell_id`, and
        no cell belonging to another market — otherwise
        `ERR_UNIVERSE_CELL_COVERAGE`."

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)

        response = _draft_attempt(
            panel,
            base["market"]["id"],
            [base["cell_a"]["id"], base["cell_b"]["id"], base["other_cell"]["id"]],
        )

        validate_error(response, "ERR_UNIVERSE_CELL_COVERAGE")

    def test_a_reversed_range_is_refused_once_coverage_is_exact(
        self, panel: PanelHarness
    ):
        """With coverage satisfied the range order becomes the reported failure.

        PRD 3.5: "`effective_from` must be strictly before `effective_to`,
        otherwise `ERR_INVALID_WINDOW`."

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)

        response = _draft_attempt(
            panel,
            base["market"]["id"],
            [base["cell_a"]["id"], base["cell_b"]["id"]],
            effective_from=VINTAGE_TO,
            effective_to=VINTAGE_FROM,
        )

        validate_error(response, "ERR_INVALID_WINDOW")

    def test_an_empty_range_is_refused_because_from_must_be_strictly_before_to(
        self, panel: PanelHarness
    ):
        """A zero-length effectivity range fails the same check.

        PRD 3.5: "`effective_from` must be strictly before `effective_to`,
        otherwise `ERR_INVALID_WINDOW`."

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)

        response = _draft_attempt(
            panel,
            base["market"]["id"],
            [base["cell_a"]["id"], base["cell_b"]["id"]],
            effective_from=VINTAGE_FROM,
            effective_to=VINTAGE_FROM,
        )

        validate_error(response, "ERR_INVALID_WINDOW")

    def test_exact_coverage_and_an_ordered_range_drafts_the_vintage(
        self, panel: PanelHarness
    ):
        """The satisfaction case: both cells once each and an ordered range.

        PRD 3.5: "The draft is created with `status` `DRAFT`, `published_at` and
        `superseded_at` null, and `total_population_households` and
        `total_population_persons` summed from the array entries. Drafting also
        advances the parent market's `version` by one."

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)
        before = panel.market_version(base["market"]["id"])

        data = validate_success(
            _draft_attempt(
                panel,
                base["market"]["id"],
                [base["cell_a"]["id"], base["cell_b"]["id"]],
            ),
            201,
        )

        assert data["status"] == "DRAFT"
        assert data["published_at"] is None
        assert data["superseded_at"] is None
        assert data["total_population_households"] == 200000
        assert data["total_population_persons"] == 500000
        assert panel.market_version(base["market"]["id"]) == before + 1

    def test_a_repeated_vintage_label_collides_even_against_a_draft(
        self, panel: PanelHarness
    ):
        """The label uniqueness check sits below coverage and the range order.

        PRD 3.5: "The pair of market and `vintage_label` must be unique across
        universe estimates in **any** status, including `SUPERSEDED` ones,
        otherwise `ERR_UNIVERSE_VINTAGE_DUPLICATE`."

        Design: Corner/validations/universe_cell_coverage_outranks_the_window_check
        """
        base = _coverage_market(panel)
        cells = [base["cell_a"]["id"], base["cell_b"]["id"]]
        validate_success(_draft_attempt(panel, base["market"]["id"], cells), 201)

        response = _draft_attempt(panel, base["market"]["id"], cells)

        validate_error(response, "ERR_UNIVERSE_VINTAGE_DUPLICATE")


# ======================================================================
# Run pinning: five gates in declared priority order
# ======================================================================

RUN_WINDOW_START = "2026-08-10T00:00:00Z"
RUN_WINDOW_END = "2026-08-11T00:00:00Z"
OUTSIDE_START = "2026-06-25T00:00:00Z"
OUTSIDE_END = "2026-06-26T00:00:00Z"


def _pinning_base(panel: PanelHarness) -> dict:
    """A market with a DRAFT vintage and a DRAFT rule set, plus a foreign vintage.

    `stale_version` is read before the draft vintage is created, and drafting
    "advances the parent market's `version` by one", so that token is exactly one
    behind the market once the helper returns.
    """
    market = panel.create_market()
    cell = panel.create_quota_cell(market["id"], target_households=1)
    stale_version = panel.market_version(market["id"])
    universe = panel.draft_universe(
        market["id"], [cell["id"]], expected_market_version=stale_version
    )
    rule_set = panel.draft_rule_set()
    other_market = panel.create_market()
    other_cell = panel.create_quota_cell(other_market["id"], target_households=1)
    foreign_universe = panel.published_universe(other_market["id"], [other_cell["id"]])
    return {
        "market": market,
        "cell": cell,
        "stale_version": stale_version,
        "universe": universe,
        "rule_set": rule_set,
        "foreign_universe": foreign_universe,
    }


def _run_attempt(panel: PanelHarness, market_id: str, universe_id: str, rule_set_id: str, **overrides):
    """Raw `POST /processing-runs` over the 2026-08-10 window."""
    overrides.setdefault("window_start_iso", RUN_WINDOW_START)
    overrides.setdefault("window_end_iso", RUN_WINDOW_END)
    version = overrides.pop("expected_market_version", None)
    if version is None:
        version = panel.market_version(market_id)
    return panel.client.create_processing_run(
        panel.statistician,
        market_id=market_id,
        universe_estimate_id=universe_id,
        edit_rule_set_id=rule_set_id,
        expected_market_version=version,
        **overrides,
    )


class TestRunPinningPriorityOrder:
    """One body walked through the seven ordered checks of run opening."""

    def test_a_stale_market_version_outranks_every_pinning_gate(
        self, panel: PanelHarness
    ):
        """A token one behind wins over a foreign vintage and an unpublished rule set.

        PRD 3.6: "1. The optimistic-concurrency check on
        `expected_market_version`, rejecting a stale read with
        `ERR_STALE_MARKET_VERSION`."

        PRD 2.7 places that check above the business gates, and the same body
        also names a vintage of another market (check 3) and a `DRAFT` rule set
        (check 5).

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)

        response = _run_attempt(
            panel,
            base["market"]["id"],
            base["foreign_universe"]["id"],
            base["rule_set"]["id"],
            expected_market_version=base["stale_version"],
        )

        validate_error(response, "ERR_STALE_MARKET_VERSION")

    def test_a_reversed_window_outranks_the_universe_and_rule_set_gates(
        self, panel: PanelHarness
    ):
        """Check 2 fires before the vintage's market and the rule set's status.

        PRD 3.6: "2. `window_start_iso` must be strictly before
        `window_end_iso`, otherwise `ERR_INVALID_WINDOW`."

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)

        response = _run_attempt(
            panel,
            base["market"]["id"],
            base["foreign_universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=OUTSIDE_END,
            window_end_iso=OUTSIDE_START,
        )

        validate_error(response, "ERR_INVALID_WINDOW")

    def test_a_foreign_vintage_outranks_an_unpublished_rule_set(
        self, panel: PanelHarness
    ):
        """A PUBLISHED vintage of the wrong market beats the DRAFT rule set below it.

        PRD 3.6: "3. The universe estimate's `market_id` must equal the run's
        `market_id`, otherwise `ERR_UNIVERSE_MARKET_MISMATCH`."

        PRD 3.6: "5. The edit rule set's `status` must be `PUBLISHED`, otherwise
        `ERR_RULE_SET_NOT_PUBLISHED`."

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)

        response = _run_attempt(
            panel,
            base["market"]["id"],
            base["foreign_universe"]["id"],
            base["rule_set"]["id"],
        )

        validate_error(response, "ERR_UNIVERSE_MARKET_MISMATCH")

    def test_an_unpublished_vintage_outranks_an_unpublished_rule_set(
        self, panel: PanelHarness
    ):
        """The right market's DRAFT vintage is the next failure down the ladder.

        PRD 3.6: "4. The universe estimate's `status` must be `PUBLISHED`,
        otherwise `ERR_UNIVERSE_NOT_PUBLISHED`. A draft universe is not a
        projection basis."

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)

        response = _run_attempt(
            panel,
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
        )

        validate_error(response, "ERR_UNIVERSE_NOT_PUBLISHED")

    def test_an_unpublished_rule_set_outranks_the_containment_rule(
        self, panel: PanelHarness
    ):
        """With both universe gates passed, the DRAFT rule set beats a window outside the vintage.

        PRD 3.6: "5. The edit rule set's `status` must be `PUBLISHED`, otherwise
        `ERR_RULE_SET_NOT_PUBLISHED`."

        PRD 3.6: "6. The run window must lie wholly inside the pinned universe
        vintage's effectivity range" — violated here too, at a lower priority.

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, base["universe"]["id"]
            ),
            200,
        )

        response = _run_attempt(
            panel,
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=OUTSIDE_START,
            window_end_iso=OUTSIDE_END,
        )

        validate_error(response, "ERR_RULE_SET_NOT_PUBLISHED")

    def test_a_window_entirely_before_the_vintage_fails_containment(
        self, panel: PanelHarness
    ):
        """With every gate above it satisfied, containment is the reported failure.

        PRD 3.6: "6. The run window must lie wholly inside the pinned universe
        vintage's effectivity range, treated as half-open: `window_start_iso` at
        or after `effective_from` and `window_end_iso` at or before
        `effective_to`, with `effective_to` itself exclusive. A violation is
        refused with `ERR_RUN_WINDOW_OUTSIDE_UNIVERSE`."

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, base["universe"]["id"]
            ),
            200,
        )
        validate_success(
            panel.client.publish_edit_rule_set(panel.statistician, base["rule_set"]["id"]),
            200,
        )

        response = _run_attempt(
            panel,
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=OUTSIDE_START,
            window_end_iso=OUTSIDE_END,
        )

        validate_error(response, "ERR_RUN_WINDOW_OUTSIDE_UNIVERSE")

    def test_a_contained_window_against_published_pins_opens_the_run(
        self, panel: PanelHarness
    ):
        """The satisfaction case: every gate passed and the run lands OPEN.

        PRD 3.6: "An opened run starts at `state` `OPEN` with
        `opened_by_user_id` recording the caller, `window_minutes` computed as
        the elapsed time from `window_start_iso` to `window_end_iso` divided by
        60 seconds, and `intab_snapshot_count` frozen at the number of `ACTIVE`
        households of the market at the moment of opening".

        PRD 3.6: "`window_end_iso` must also be at or before the current logical
        clock", so the clock is advanced to the window's end first.

        Design: Corner/validations/run_pinning_rules_fire_in_declared_priority_order
        """
        base = _pinning_base(panel)
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, base["universe"]["id"]
            ),
            200,
        )
        validate_success(
            panel.client.publish_edit_rule_set(panel.statistician, base["rule_set"]["id"]),
            200,
        )
        panel.set_clock(RUN_WINDOW_END)

        data = validate_success(
            _run_attempt(
                panel,
                base["market"]["id"],
                base["universe"]["id"],
                base["rule_set"]["id"],
            ),
            201,
        )

        assert data["state"] == "OPEN"
        assert data["window_minutes"] == 1440
        assert data["universe_estimate_id"] == base["universe"]["id"]
        assert data["edit_rule_set_id"] == base["rule_set"]["id"]
        assert data["intab_snapshot_count"] == 0
        assert data["contributing_household_count"] == 0
        assert data["total_weight_mass"] == 0


# ======================================================================
# Meter shipping: serial uniqueness before type occupancy
# ======================================================================

def _recruited_home(panel: PanelHarness) -> dict:
    """A market with one cell and a single household left in RECRUITED."""
    market = panel.create_market()
    cell = panel.create_quota_cell(market["id"], target_households=4, base_incentive_cents=1000)
    household = panel.recruit_household(market["id"], cell["id"], persons_count=2)
    return {"market": market, "cell": cell, "household": household}


def _home_with_removed_router(panel: PanelHarness) -> dict:
    """A household whose only STREAMING_ROUTER has been installed and pulled.

    Confirming a router "never changes the household `status`", so the home is
    still `INSTALL_SCHEDULED` and therefore inside the removable set.
    """
    base = _recruited_home(panel)
    router = panel.installed_meter(base["household"]["id"], meter_type="STREAMING_ROUTER")
    removed = validate_success(
        panel.client.remove_meter(
            panel.tech, router["id"], removal_note="Wrong model shipped"
        ),
        200,
    )
    base["router"] = router
    base["removed"] = removed
    return base


class TestMeterSerialOutranksTypeOccupancy:
    """Serial uniqueness is check 2 and type occupancy is check 3."""

    def test_a_duplicate_serial_outranks_a_duplicate_type_slot(
        self, panel: PanelHarness
    ):
        """A body repeating both the serial and the type reports the serial.

        PRD 3.3: "2. `serial_no` must be unique across every meter row ever
        created, including `REMOVED` ones, otherwise
        `ERR_METER_SERIAL_DUPLICATE`."

        PRD 3.3: "3. The household must hold no other meter of the same
        `meter_type` whose `install_status` is `SHIPPED` or `INSTALLED`,
        otherwise `ERR_METER_TYPE_ALREADY_PRESENT`."

        PRD 3.3: "Shipping is also the *only* thing that schedules an
        installation: when the household was `RECRUITED`, creating its first
        meter row moves the household to `INSTALL_SCHEDULED`."

        Design: Corner/validations/meter_serial_uniqueness_outranks_type_occupancy
        """
        base = _recruited_home(panel)

        first = panel.ship_meter(base["household"]["id"], meter_type="TV_TUNER")

        assert first["install_status"] == "SHIPPED"
        assert first["health_status"] == "HEALTHY"
        assert first["installed_at"] is None
        assert panel.read_household(base["household"]["id"])["status"] == "INSTALL_SCHEDULED"

        response = panel.client.create_meter(
            panel.tech,
            household_id=base["household"]["id"],
            meter_type="TV_TUNER",
            serial_no=first["serial_no"],
        )

        validate_error(response, "ERR_METER_SERIAL_DUPLICATE")

    def test_a_fresh_serial_reaches_the_type_occupancy_rule(self, panel: PanelHarness):
        """With the serial clean, the occupancy rule counts the merely SHIPPED device.

        PRD 3.3: "3. The household must hold no other meter of the same
        `meter_type` whose `install_status` is `SHIPPED` or `INSTALLED`,
        otherwise `ERR_METER_TYPE_ALREADY_PRESENT`."

        Design: Corner/validations/meter_serial_uniqueness_outranks_type_occupancy
        """
        base = _recruited_home(panel)
        panel.ship_meter(base["household"]["id"], meter_type="TV_TUNER")

        response = panel.client.create_meter(
            panel.tech,
            household_id=base["household"]["id"],
            meter_type="TV_TUNER",
            serial_no=next_serial_no(),
        )

        validate_error(response, "ERR_METER_TYPE_ALREADY_PRESENT")

    def test_a_removed_device_frees_its_type_slot(self, panel: PanelHarness):
        """A replacement of the very same type ships once the old one is REMOVED.

        PRD 3.3: "A `REMOVED` device of that type does not block a replacement,
        which is exactly how an equipment swap is performed."

        PRD 3.3: "Removal sets `install_status` to `REMOVED` and deliberately
        leaves `health_status` and `fault_count` exactly as they were — removal
        is not a repair."

        Design: Corner/validations/meter_serial_uniqueness_outranks_type_occupancy
        """
        base = _home_with_removed_router(panel)

        assert base["removed"]["install_status"] == "REMOVED"
        assert base["removed"]["health_status"] == "HEALTHY"
        assert base["removed"]["fault_count"] == 0
        assert panel.read_household(base["household"]["id"])["status"] == "INSTALL_SCHEDULED"

        replacement = validate_success(
            panel.client.create_meter(
                panel.tech,
                household_id=base["household"]["id"],
                meter_type="STREAMING_ROUTER",
                serial_no=next_serial_no(),
            ),
            201,
        )

        assert replacement["install_status"] == "SHIPPED"
        assert replacement["meter_type"] == "STREAMING_ROUTER"

    def test_a_removed_devices_serial_can_never_be_reused(self, panel: PanelHarness):
        """The freed slot does not free the serial number.

        PRD 3.3: "2. `serial_no` must be unique across every meter row ever
        created, including `REMOVED` ones, otherwise
        `ERR_METER_SERIAL_DUPLICATE`."

        Design: Corner/validations/meter_serial_uniqueness_outranks_type_occupancy
        """
        base = _home_with_removed_router(panel)

        response = panel.client.create_meter(
            panel.tech,
            household_id=base["household"]["id"],
            meter_type="STREAMING_ROUTER",
            serial_no=base["router"]["serial_no"],
        )

        validate_error(response, "ERR_METER_SERIAL_DUPLICATE")

    def test_removal_is_refused_while_the_household_is_in_tab(
        self, panel: PanelHarness
    ):
        """An ACTIVE home keeps its equipment until it leaves tab.

        PRD 3.3: "Two checks run in this order: the meter's `install_status` must
        be `INSTALLED`, otherwise `ERR_METER_NOT_INSTALLED`; and the owning
        household's `status` must be one of `INSTALL_SCHEDULED`, `ENUM_PENDING`,
        `NONCOMPLIANT_HOLD` or `FAULT_HOLD`, otherwise `ERR_HOUSEHOLD_IN_TAB`."

        Design: Corner/validations/meter_serial_uniqueness_outranks_type_occupancy
        """
        base = _recruited_home(panel)
        built = panel.active_household(
            base["market"]["id"], base["cell"]["id"], persons_count=2
        )
        assert built["household"]["status"] == "ACTIVE"

        response = panel.client.remove_meter(
            panel.tech, built["tuner"]["id"], removal_note="Household asked us to pull it"
        )

        validate_error(response, "ERR_HOUSEHOLD_IN_TAB")
        assert panel.read_meter(built["tuner"]["id"])["install_status"] == "INSTALLED"

    def test_a_removal_is_a_status_change_and_not_a_delete(self, panel: PanelHarness):
        """Both the pulled device and its replacement remain listed.

        PRD 3.3: "`install_status` describes where the device physically is and
        walks `SHIPPED` to `INSTALLED` to `REMOVED`, with `REMOVED` terminal."

        PRD 3.3: "The freed `meter_type` slot becomes available, so a replacement
        device of the same type may be shipped."

        Design: Corner/validations/meter_serial_uniqueness_outranks_type_occupancy
        """
        base = _home_with_removed_router(panel)
        validate_success(
            panel.client.create_meter(
                panel.tech,
                household_id=base["household"]["id"],
                meter_type="STREAMING_ROUTER",
                serial_no=next_serial_no(),
            ),
            201,
        )

        rows, meta = validate_paginated(
            panel.client.list_meters(panel.tech, household_id=base["household"]["id"])
        )

        assert meta["total_count"] == 2
        assert sorted(row["install_status"] for row in rows) == ["REMOVED", "SHIPPED"]


# ======================================================================
# Tuning interval ingest: shape, methodology and recency
# ======================================================================

CLOCK_AUG_05 = "2026-08-05T00:00:00Z"


def _metered_home(panel: PanelHarness) -> dict:
    """One ACTIVE household whose only device is a TV_TUNER, clock at 2026-08-05.

    A second household is recruited into the same cell purely to supply a
    household id that is not the meter's own.
    """
    market = panel.create_market()
    cell = panel.create_quota_cell(market["id"], target_households=4, base_incentive_cents=1000)
    built = panel.active_household(market["id"], cell["id"], persons_count=2)
    other = panel.recruit_household(market["id"], cell["id"], persons_count=2)
    panel.set_clock(CLOCK_AUG_05)
    return {
        "market": market,
        "cell": cell,
        "household": built["household"],
        "tuner": built["tuner"],
        "other_household": other,
    }


def _ingest_attempt(panel: PanelHarness, base: dict, **overrides):
    """Raw `POST /tuning-intervals` for the tuner of `base`."""
    overrides.setdefault("household_id", base["household"]["id"])
    overrides.setdefault("source_methodology", "INHOME_TUNER")
    overrides.setdefault("start_iso", "2026-08-04T01:00:00Z")
    overrides.setdefault("end_iso", "2026-08-04T02:00:00Z")
    overrides.setdefault("station_code", "WAAA")
    overrides.setdefault("tuning_minutes", 60)
    return panel.client.create_tuning_interval(
        panel.statistician, meter_id=base["tuner"]["id"], **overrides
    )


class TestTuningIntervalShapeMethodologyAndRecency:
    """The two shape rules bind first; then the methodology and recency checks."""

    def test_a_methodology_that_does_not_match_the_meter_type_is_refused(
        self, panel: PanelHarness
    ):
        """`STREAMING_SDK` is illegal on a `TV_TUNER` even though the block is sound.

        PRD 3.6: "3. `source_methodology` must match the meter's `meter_type`
        under a fixed mapping — `TV_TUNER` collects `INHOME_TUNER`,
        `STREAMING_ROUTER` collects `STREAMING_SDK`, and `PORTABLE_OOH` collects
        `PORTABLE_OOH` — otherwise `ERR_METHODOLOGY_METER_MISMATCH`."

        Design: Corner/validations/tuning_interval_shape_methodology_and_recency_rules
        """
        base = _metered_home(panel)

        response = _ingest_attempt(panel, base, source_methodology="STREAMING_SDK")

        validate_error(response, "ERR_METHODOLOGY_METER_MISMATCH")

    def test_a_block_ending_after_the_clock_is_refused(self, panel: PanelHarness):
        """A block running to 2026-08-06 has not happened at a clock of 2026-08-05.

        PRD 3.6: "5. `end_iso` must be at or before the current logical clock,
        otherwise `ERR_INTERVAL_IN_FUTURE`. The panel cannot report viewing that
        has not happened yet."

        Design: Corner/validations/tuning_interval_shape_methodology_and_recency_rules
        """
        base = _metered_home(panel)

        response = _ingest_attempt(
            panel,
            base,
            start_iso="2026-08-05T23:00:00Z",
            end_iso="2026-08-06T00:00:00Z",
        )

        validate_error(response, "ERR_INTERVAL_IN_FUTURE")

    def test_more_tuning_than_the_block_contains_is_a_shape_failure(
        self, panel: PanelHarness
    ):
        """1441 minutes reported inside a 60-minute block never reaches a domain rule.

        PRD 3.6: "`tuning_minutes` must be at least 0 and must not exceed the
        wall length of the submitted block — the elapsed time from `start_iso` to
        `end_iso` divided by 60 seconds and floored to whole minutes. Either
        violation is refused with `ERR_INVALID_REQUEST`".

        Design: Corner/validations/tuning_interval_shape_methodology_and_recency_rules
        """
        base = _metered_home(panel)

        response = _ingest_attempt(panel, base, tuning_minutes=1441)

        validate_error(response, "ERR_INVALID_REQUEST")

    def test_a_household_id_that_is_not_the_meters_own_is_a_shape_failure(
        self, panel: PanelHarness
    ):
        """The shape rules bind ahead of the methodology mismatch in the same body.

        PRD 3.6: "Two shape rules bind the payload before any business check: the
        submitted `household_id` must equal the meter's own `household_id`, and
        `tuning_minutes` must be at least 0 and must not exceed the wall length
        of the submitted block".

        Design: Corner/validations/tuning_interval_shape_methodology_and_recency_rules
        """
        base = _metered_home(panel)

        response = _ingest_attempt(
            panel,
            base,
            household_id=base["other_household"]["id"],
            source_methodology="STREAMING_SDK",
        )

        validate_error(response, "ERR_INVALID_REQUEST")

    def test_a_matching_methodology_in_the_past_lands_a_raw_record(
        self, panel: PanelHarness
    ):
        """The satisfaction case: `INHOME_TUNER` on a tuner, wholly in the past.

        PRD 3.6: "An ingested record starts at `state` `RAW` with
        `usable_minutes` 0, `ascribed` false, and `processing_run_id` and
        `invalidation_reason` both null."

        Design: Corner/validations/tuning_interval_shape_methodology_and_recency_rules
        """
        base = _metered_home(panel)

        data = validate_success(_ingest_attempt(panel, base), 201)

        assert data["state"] == "RAW"
        assert data["household_id"] == base["household"]["id"]
        assert data["meter_id"] == base["tuner"]["id"]
        assert data["usable_minutes"] == 0
        assert data["ascribed"] is False
        assert data["processing_run_id"] is None
        assert data["invalidation_reason"] is None

    def test_a_block_ending_exactly_at_the_clock_is_accepted(self, panel: PanelHarness):
        """The recency rule is inclusive, so the boundary instant is reportable.

        PRD 3.6: "5. `end_iso` must be at or before the current logical clock,
        otherwise `ERR_INTERVAL_IN_FUTURE`."

        Design: Corner/validations/tuning_interval_shape_methodology_and_recency_rules
        """
        base = _metered_home(panel)

        data = validate_success(
            _ingest_attempt(
                panel,
                base,
                start_iso="2026-08-04T23:00:00Z",
                end_iso=CLOCK_AUG_05,
                station_code="WBBB",
            ),
            201,
        )

        assert data["state"] == "RAW"
        assert _instant(data["end_iso"]) == _instant(CLOCK_AUG_05)


# ======================================================================
# Methodology change drafting and the impact analysis gates
# ======================================================================

def _governance_base(panel: PanelHarness) -> dict:
    """A PUBLISHED run over the canonical window plus two DRAFT rule sets.

    `proposed` differs from the published set only in
    `missing_interval_ascription_minutes`, so the ascription sub-score is the
    only non-zero dimension.
    """
    base = panel.published_run()
    base["proposed"] = panel.draft_rule_set(missing_interval_ascription_minutes=36)
    base["other_draft"] = panel.draft_rule_set(invalid_tuning_max_minutes=800)
    base["foreign_market"] = panel.create_market()
    return base


class TestImpactAnalysisGates:
    """A bad rule-set pair, a foreign baseline and the two-sided state gate."""

    def test_an_identical_target_and_proposed_pair_is_not_distinct(
        self, panel: PanelHarness
    ):
        """Naming the same rule set on both sides is refused.

        PRD 3.9: "The `proposed_edit_rule_set_id` must differ from the
        `target_edit_rule_set_id` **and** the named target must be the currently
        `PUBLISHED` rule set, otherwise `ERR_RULE_SET_NOT_DISTINCT`."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)

        response = panel.client.create_methodology_change(
            panel.director,
            title="No-op change",
            target_edit_rule_set_id=base["rule_set"]["id"],
            proposed_edit_rule_set_id=base["rule_set"]["id"],
            affected_market_ids=[base["market"]["id"]],
        )

        validate_error(response, "ERR_RULE_SET_NOT_DISTINCT")

    def test_a_target_that_is_not_the_published_set_is_not_distinct(
        self, panel: PanelHarness
    ):
        """Two different DRAFT sets still fail: the target must be the published one.

        PRD 3.9: "The `proposed_edit_rule_set_id` must differ from the
        `target_edit_rule_set_id` **and** the named target must be the currently
        `PUBLISHED` rule set, otherwise `ERR_RULE_SET_NOT_DISTINCT`."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)

        response = panel.client.create_methodology_change(
            panel.director,
            title="Draft to draft",
            target_edit_rule_set_id=base["other_draft"]["id"],
            proposed_edit_rule_set_id=base["proposed"]["id"],
            affected_market_ids=[base["market"]["id"]],
        )

        validate_error(response, "ERR_RULE_SET_NOT_DISTINCT")

    def test_a_sound_pair_drafts_a_change_at_a_zero_delta(self, panel: PanelHarness):
        """The accepted draft carries no score yet, only a drafter.

        PRD 3.9: "The change starts in `DRAFT` with `created_by_user_id` stamped
        from `X-User-ID`, `impact_delta_pct` at 0.0000, `impact_tier` null and
        `revision_count` 0."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)

        change = panel.draft_change(
            base["rule_set"]["id"], base["proposed"]["id"], [base["market"]["id"]]
        )

        assert change["state"] == "DRAFT"
        assert change["impact_delta_pct"] == 0.0
        assert change["impact_tier"] is None
        assert change["revision_count"] == 0
        assert change["created_by_user_id"] == DIRECTOR_USER_ID
        assert change["version"] == 1

    def test_a_baseline_run_from_an_unaffected_market_is_invalid(
        self, panel: PanelHarness
    ):
        """A perfectly valid PUBLISHED run is still not a legal baseline here.

        PRD 3.9: "4. The baseline run must be pinned to the change's target rule
        set and its `market_id` must be an element of `affected_market_ids`,
        otherwise `ERR_BASELINE_RUN_INVALID`."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)
        change = panel.draft_change(
            base["rule_set"]["id"],
            base["proposed"]["id"],
            [base["foreign_market"]["id"]],
            title="Ascription 30 -> 36, wrong market list",
        )

        response = panel.client.create_impact_analysis(
            panel.director,
            change["id"],
            baseline_processing_run_id=base["run"]["id"],
            expected_methodology_change_version=change["version"],
        )

        validate_error(response, "ERR_BASELINE_RUN_INVALID")

    def test_request_revision_refuses_a_change_that_is_still_a_draft(
        self, panel: PanelHarness
    ):
        """The same state gate fires from the opposite direction.

        PRD 3.9: "The change's `state` must be `IMPACT_ASSESSED` or `NOTIFIED`,
        otherwise `ERR_CHANGE_NOT_DRAFT`."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)
        change = panel.draft_change(
            base["rule_set"]["id"], base["proposed"]["id"], [base["market"]["id"]]
        )

        response = panel.client.request_methodology_change_revision(
            panel.director, change["id"], reason="Fix the market list"
        )

        validate_error(response, "ERR_CHANGE_NOT_DRAFT")

    def test_a_sound_pair_and_baseline_scores_the_change(self, panel: PanelHarness):
        """The satisfaction case: only the ascription dimension moves.

        PRD 3.9: "the ascription sub-score is the absolute difference between
        their `missing_interval_ascription_minutes` divided by 60.
        `impact_delta_pct` is 0.40 times the cap sub-score plus 0.35 times the
        tuning sub-score plus 0.25 times the ascription sub-score, rounded half
        up to 4 decimal places."

        PRD 3.9: "`MINOR` below 0.0500" and the lead time is "72 hours for
        `MINOR`", so 0.25 * (6 / 60) == 0.0250 is a MINOR change.

        PRD 3.9: "The analysis records `baseline_processing_run_id` and copies
        the baseline run's `projected_average_audience` into
        `baseline_projected_average_audience` for later disclosure, moves the
        change to `IMPACT_ASSESSED`, and advances the change's `version` by one."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)
        change = panel.draft_change(
            base["rule_set"]["id"], base["proposed"]["id"], [base["market"]["id"]]
        )

        assessed = panel.assess_change(change["id"], base["run"]["id"])

        assert assessed["state"] == "IMPACT_ASSESSED"
        assert assessed["impact_delta_pct"] == 0.025
        assert assessed["impact_delta_pct"] == expected_impact_delta_pct(
            base["rule_set"], base["proposed"]
        )
        assert assessed["impact_tier"] == "MINOR"
        assert assessed["impact_tier"] == expected_impact_tier(
            assessed["impact_delta_pct"]
        )
        assert assessed["notification_lead_hours"] == LEAD_HOURS_MINOR
        assert assessed["baseline_processing_run_id"] == base["run"]["id"]
        assert (
            assessed["baseline_projected_average_audience"]
            == base["run"]["projected_average_audience"]
        )
        assert assessed["version"] == change["version"] + 1
        assert assessed["revision_count"] == 0

    def test_a_second_analysis_is_refused_by_the_state_gate(self, panel: PanelHarness):
        """With the version pin current, the state gate is what rejects the re-run.

        PRD 3.9: "3. The change's `state` must be `DRAFT`, otherwise
        `ERR_CHANGE_NOT_DRAFT`."

        Design: Corner/validations/impact_analysis_gates_reject_a_non_distinct_target_or_a_foreign_baseline
        """
        base = _governance_base(panel)
        change = panel.draft_change(
            base["rule_set"]["id"], base["proposed"]["id"], [base["market"]["id"]]
        )
        assessed = panel.assess_change(change["id"], base["run"]["id"])

        response = panel.client.create_impact_analysis(
            panel.director,
            change["id"],
            baseline_processing_run_id=base["run"]["id"],
            expected_methodology_change_version=assessed["version"],
        )

        validate_error(response, "ERR_CHANGE_NOT_DRAFT")


# ======================================================================
# Weighting: at least one contributing household
# ======================================================================

AUG_09_START = "2026-08-09T00:00:00Z"


def _two_window_panel(panel: PanelHarness) -> dict:
    """One household with two blocks: 200 minutes on 08-10 and 90 minutes on 08-09.

    The rule set's `invalid_tuning_max_minutes` is 100, so the 08-10 record is
    invalidated by the edit pass while the 08-09 record survives; the ascription
    window is 0 minutes, so no synthetic record is ever created.
    """
    market = panel.create_market()
    cell = panel.create_quota_cell(
        market["id"], target_households=1, base_incentive_cents=2000
    )
    built = panel.active_household(market["id"], cell["id"], persons_count=2)
    rule_set = panel.published_rule_set(
        missing_interval_ascription_minutes=0,
        invalid_tuning_max_minutes=100,
        outlier_household_minutes_cap=1200,
        outlier_weight_ratio_cap=2.5,
        fault_missing_minutes_threshold=1440,
    )
    universe = panel.published_universe(market["id"], [cell["id"]])
    panel.set_clock(RUN_WINDOW_END)
    over_maximum = panel.ingest_interval(
        built["tuner"]["id"],
        built["household"]["id"],
        "2026-08-10T15:00:00Z",
        "2026-08-10T19:00:00Z",
        200,
        station_code="WAAA",
    )
    under_maximum = panel.ingest_interval(
        built["tuner"]["id"],
        built["household"]["id"],
        "2026-08-09T18:00:00Z",
        "2026-08-09T19:30:00Z",
        90,
        station_code="WBBB",
    )
    return {
        "market": market,
        "cell": cell,
        "household": built["household"],
        "tuner": built["tuner"],
        "rule_set": rule_set,
        "universe": universe,
        "over_maximum": over_maximum,
        "under_maximum": under_maximum,
    }


class TestWeightingRequiresContributors:
    """Check 2 of the weighting pass is a real, data-dependent gate."""

    def test_an_all_invalidated_window_still_edits_to_zero_contributors(
        self, panel: PanelHarness
    ):
        """The edit pass succeeds and simply leaves nothing to project.

        PRD 3.6: "**Invalid tuning.** A claimed record whose `tuning_minutes`
        exceeds the rule set's `invalid_tuning_max_minutes` moves to `state`
        `INVALIDATED` with `invalidation_reason` `OVER_MAX_TUNING` and
        `usable_minutes` 0."

        PRD 3.6: "The pass moves the run's `state` from `OPEN` to `EDITED` and
        creates **no** household weight rows — weighting is a separate act."

        Design: Corner/validations/weighting_requires_at_least_one_contributing_household
        """
        base = _two_window_panel(panel)
        run = panel.open_run(
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=RUN_WINDOW_START,
            window_end_iso=RUN_WINDOW_END,
        )

        edited = panel.edit_run(run["id"])

        assert edited["state"] == "EDITED"
        assert edited["invalidated_interval_count"] == 1
        assert edited["ascribed_interval_count"] == 0
        assert edited["outlier_household_count"] == 0
        assert edited["contributing_household_count"] == 0
        assert panel.weights_of_run(run["id"]) == []

    def test_weighting_a_window_with_no_contributors_is_refused(
        self, panel: PanelHarness
    ):
        """The gate fires and the rejected pass writes nothing at all.

        PRD 3.7: "2. The run's `contributing_household_count` must be at least 1,
        otherwise `ERR_NO_CONTRIBUTING_HOUSEHOLDS`. A window in which every
        interval was invalidated cannot be projected."

        PRD 3.6: "`contributing_household_count`, `ascribed_interval_count`,
        `invalidated_interval_count`, `outlier_household_count`,
        `excluded_cell_count` and `total_weight_mass` all start at 0;
        `weight_variant`, `projected_average_audience`, `published_at`,
        `published_by_user_id`, `repin_required_reason` and
        `superseded_by_run_id` all start null".

        Design: Corner/validations/weighting_requires_at_least_one_contributing_household
        """
        base = _two_window_panel(panel)
        run = panel.open_run(
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=RUN_WINDOW_START,
            window_end_iso=RUN_WINDOW_END,
        )
        panel.edit_run(run["id"])

        response = panel.client.weight_processing_run(
            panel.statistician, run["id"], weight_variant="FINAL"
        )

        validate_error(response, "ERR_NO_CONTRIBUTING_HOUSEHOLDS")
        after = panel.read_run(run["id"])
        assert after["state"] == "EDITED"
        assert after["total_weight_mass"] == 0
        assert after["projected_average_audience"] is None
        assert after["weight_variant"] is None

    def test_the_neighbouring_window_weights_because_it_has_a_contributor(
        self, panel: PanelHarness
    ):
        """The same gate passes over the window whose record survived editing.

        PRD 3.7: "2. The run's `contributing_household_count` must be at least 1,
        otherwise `ERR_NO_CONTRIBUTING_HOUSEHOLDS`."

        PRD 3.7: "Under `FINAL`, the denominator is the number of households of
        that cell that actually contributed at least one `EDITED` or `ASCRIBED`
        interval to **this** run with `usable_minutes` above 0."

        PRD 3.7: "First, each household's `contribution` is its `adjusted_weight`
        multiplied by its summed usable minutes and divided by the run's
        `window_minutes`, rounded half up to 2 decimal places." With one row of
        100000.0000 over 90 of 1440 minutes the projection is 6250.

        Design: Corner/validations/weighting_requires_at_least_one_contributing_household
        """
        base = _two_window_panel(panel)
        run = panel.open_run(
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=AUG_09_START,
            window_end_iso=RUN_WINDOW_START,
        )

        edited = panel.edit_run(run["id"])

        assert edited["state"] == "EDITED"
        assert edited["invalidated_interval_count"] == 0
        assert edited["contributing_household_count"] == 1

        weighted = panel.weight_run(run["id"], weight_variant="FINAL")

        assert weighted["state"] == "WEIGHTED"
        assert weighted["total_weight_mass"] == 100000.0
        assert weighted["projected_average_audience"] == 6250
        assert weighted["projected_average_audience"] == expected_projected_average_audience(
            [expected_contribution(100000.0, 90, 1440)]
        )

    def test_the_surviving_household_gets_one_weight_row(self, panel: PanelHarness):
        """The row the blocked run never produced is written here.

        PRD 3.7: "One `HouseholdWeight` row is written per household holding at
        least one tuning interval of this run in `state` `EDITED` or `ASCRIBED`
        with `usable_minutes` above 0."

        PRD 3.7: "Rows whose `base_weight` is **strictly greater** than the cap
        are the capped rows; a row exactly at the cap is not capped." The single
        row is exactly the mean, so it is not capped.

        Design: Corner/validations/weighting_requires_at_least_one_contributing_household
        """
        base = _two_window_panel(panel)
        run = panel.open_run(
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            window_start_iso=AUG_09_START,
            window_end_iso=RUN_WINDOW_START,
        )
        panel.edit_run(run["id"])
        panel.weight_run(run["id"], weight_variant="FINAL")

        rows = panel.weights_of_run(run["id"])

        assert len(rows) == 1
        row = rows[0]
        assert row["household_id"] == base["household"]["id"]
        assert row["weight_variant"] == "FINAL"
        assert row["base_weight"] == 100000.0
        assert row["adjusted_weight"] == 100000.0
        assert row["usable_minutes"] == 90
        assert row["contribution"] == 6250.00
        assert row["capped"] is False
        assert row["run_compliance_rate"] == 1.0


# ======================================================================
# Notification and activation: five gates in priority order
# ======================================================================

def _clock_string(moment: datetime) -> str:
    """Render an aware UTC datetime the way the clock endpoint expects it."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _assessed_change(panel: PanelHarness) -> dict:
    """A MINOR change in IMPACT_ASSESSED, drafted by one director, clock at T1."""
    base = _governance_base(panel)
    change = panel.draft_change(
        base["rule_set"]["id"], base["proposed"]["id"], [base["market"]["id"]]
    )
    base["change"] = panel.assess_change(change["id"], base["run"]["id"])
    return base


def _notified_change(panel: PanelHarness) -> dict:
    """The same change fanned out to one contracted client."""
    base = _assessed_change(panel)
    base["client"] = panel.create_client([base["market"]["id"]])
    base["change"] = panel.notify_change(base["change"]["id"])
    return base


class TestNotifyAndActivateGates:
    """Segregation of duties, the state gates, acknowledgements and the clock."""

    def test_segregation_of_duties_outranks_the_state_gate(self, panel: PanelHarness):
        """The drafter is refused before anyone looks at the change's state.

        PRD 3.9: "1. The acting `X-User-ID` must differ from the change's
        `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The director
        who drafted a change may not be the one who makes it effective."

        PRD 3.9: "2. The change's `state` must be `NOTIFIED`, otherwise
        `ERR_CHANGE_NOT_NOTIFIED`." That gate is violated too, at lower priority.

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _assessed_change(panel)

        response = panel.client.activate_methodology_change(
            panel.director, base["change"]["id"]
        )

        validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    def test_a_distinct_activator_reaches_the_state_gate(self, panel: PanelHarness):
        """A second director clears rule 1 and is stopped by rule 2.

        PRD 3.9: "2. The change's `state` must be `NOTIFIED`, otherwise
        `ERR_CHANGE_NOT_NOTIFIED`."

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _assessed_change(panel)

        response = panel.client.activate_methodology_change(
            panel.activator, base["change"]["id"]
        )

        validate_error(response, "ERR_CHANGE_NOT_NOTIFIED")

    def test_notify_is_refused_when_no_client_is_contracted(self, panel: PanelHarness):
        """There is nobody to disclose to, so the fan-out is refused.

        PRD 3.9: "at least one client must hold a `contract_market_ids` element
        that appears in the change's `affected_market_ids`, otherwise
        `ERR_NO_AFFECTED_CLIENTS` — a change must never become effective with
        nobody informed."

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _assessed_change(panel)

        response = panel.client.notify_methodology_change(
            panel.director, base["change"]["id"]
        )

        validate_error(response, "ERR_NO_AFFECTED_CLIENTS")

    def test_notify_fans_out_and_stamps_the_deadline_from_the_clock(
        self, panel: PanelHarness
    ):
        """The deadline is set at notify time, not at assessment time.

        PRD 3.9: "The change moves to `NOTIFIED`, `notified_client_count` is set
        to the number of rows created, `acknowledged_client_count` is 0, and
        `notification_deadline_at` is set to the current logical clock plus
        `notification_lead_hours`."

        PRD 3.9: "Each notification starts in `state` `SENT` with `sent_at`
        stamped, `acknowledged_at` null, and `impact_tier` and
        `disclosed_delta_pct` copied from the change at that instant".

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _notified_change(panel)

        assert base["change"]["state"] == "NOTIFIED"
        assert base["change"]["notified_client_count"] == 1
        assert base["change"]["acknowledged_client_count"] == 0
        assert _instant(base["change"]["notification_deadline_at"]) == _instant(
            CLOCK_T1
        ) + timedelta(hours=LEAD_HOURS_MINOR)

        rows = panel.notifications_of_change(base["change"]["id"])

        assert len(rows) == 1
        assert rows[0]["state"] == "SENT"
        assert rows[0]["client_id"] == base["client"]["id"]
        assert rows[0]["impact_tier"] == "MINOR"
        assert rows[0]["disclosed_delta_pct"] == 0.025
        assert rows[0]["acknowledged_at"] is None
        assert _instant(rows[0]["sent_at"]) == _instant(CLOCK_T1)

    def test_notify_is_not_idempotent(self, panel: PanelHarness):
        """A second fan-out is refused by the notification state gate.

        PRD 3.9: "Two checks run in this order: the change's `state` must be
        `IMPACT_ASSESSED`, otherwise `ERR_CHANGE_NOT_ASSESSED`".

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _notified_change(panel)

        response = panel.client.notify_methodology_change(
            panel.director, base["change"]["id"]
        )

        validate_error(response, "ERR_CHANGE_NOT_ASSESSED")

    def test_the_acknowledgement_gate_outranks_the_waiting_period(
        self, panel: PanelHarness
    ):
        """Both gate 3 and gate 4 are violated and gate 3 is what is reported.

        PRD 3.9: "3. `acknowledged_client_count` must equal
        `notified_client_count`, otherwise `ERR_ACKNOWLEDGEMENTS_MISSING`. Every
        notified client must have acknowledged."

        PRD 3.9: "4. The current logical clock must have reached
        `notification_deadline_at`, otherwise `ERR_NOTIFICATION_PERIOD_OPEN`."

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _notified_change(panel)

        response = panel.client.activate_methodology_change(
            panel.activator, base["change"]["id"]
        )

        validate_error(response, "ERR_ACKNOWLEDGEMENTS_MISSING")

    def test_the_waiting_period_is_the_last_gate_standing(self, panel: PanelHarness):
        """Once everyone has acknowledged, only the clock still blocks activation.

        PRD 3.9: "4. The current logical clock must have reached
        `notification_deadline_at`, otherwise `ERR_NOTIFICATION_PERIOD_OPEN`. The
        tier's lead time must have fully elapsed even when every client
        acknowledged early".

        PRD 3.9: "The notification moves to `ACKNOWLEDGED` with
        `acknowledged_at` stamped, and the change's `acknowledged_client_count`
        rises by one."

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _notified_change(panel)

        acknowledged = panel.acknowledge_all(base["change"]["id"])

        assert len(acknowledged) == 1
        assert acknowledged[0]["state"] == "ACKNOWLEDGED"
        assert panel.read_change(base["change"]["id"])["acknowledged_client_count"] == 1

        response = panel.client.activate_methodology_change(
            panel.activator, base["change"]["id"]
        )

        validate_error(response, "ERR_NOTIFICATION_PERIOD_OPEN")

    def test_activation_at_exactly_the_deadline_swaps_the_rule_sets(
        self, panel: PanelHarness
    ):
        """The clock comparison is inclusive, so the deadline instant activates.

        PRD 3.9: "the change's `state` becomes `EFFECTIVE` — terminal — with
        `activated_at` stamped; the proposed rule set's `status` becomes
        `PUBLISHED` with `published_at` stamped; and the target rule set's
        `status` becomes `SUPERSEDED`."

        PRD 3.9: "**Link 2**, caused by link 1's supersession: every processing
        run whose `edit_rule_set_id` is the superseded target and whose `state`
        is `OPEN` or `EDITED` moves to `PENDING_REPIN`", so the PUBLISHED
        baseline run is untouched.

        Design: Corner/validations/notify_and_activate_gates_run_in_declared_priority_order
        """
        base = _notified_change(panel)
        panel.acknowledge_all(base["change"]["id"])
        deadline = _instant(base["change"]["notification_deadline_at"])
        panel.set_clock(_clock_string(deadline))

        activated = panel.activate_change(base["change"]["id"])

        assert activated["state"] == "EFFECTIVE"
        assert _instant(activated["activated_at"]) == deadline
        assert panel.read_rule_set(base["rule_set"]["id"])["status"] == "SUPERSEDED"
        proposed = panel.read_rule_set(base["proposed"]["id"])
        assert proposed["status"] == "PUBLISHED"
        assert _instant(proposed["published_at"]) == deadline
        run = panel.read_run(base["run"]["id"])
        assert run["state"] == "PUBLISHED"
        assert run["repin_required_reason"] is None
