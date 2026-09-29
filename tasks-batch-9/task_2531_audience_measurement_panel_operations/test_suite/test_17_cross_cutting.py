"""Cross-cutting corners: cascades that cross three aggregates at once.

Each class here walks one layer that no single endpoint owns. A universe
publication reaches from the vintage through runs and deliverables into a client's
money ledger (PRD 3.5, 3.8); a methodology activation supersedes a rule set
without disturbing the run that pinned it (PRD 3.9); the three optimistic
concurrency tokens of PRD 2.7 interleave on the same parents; and the incentive
boost of PRD 3.1 releases and re-arms on a threshold rather than latching.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_version_unchanged,
    expected_boost_reservation,
    expected_fill_rate,
    expected_impact_delta_pct,
    expected_impact_tier,
    round_half_up_to_int,
)
from test_helpers.constants import (
    BOOSTED_MULTIPLIER,
    HOLD_CREDIT_PCT,
    NOTIFICATION_LEAD_HOURS,
    UNBOOSTED_MULTIPLIER,
)
from test_helpers.factories import cell_population
from test_helpers.fixtures import PanelHarness

# The second vintage is published 29 whole days after the 2026Q3 vintage, which
# satisfies the 28-day spacing rule of PRD 3.5.
LATE_CLOCK = "2026-08-30T00:00:00Z"
SECOND_WINDOW_START = "2026-08-12T00:00:00Z"
SECOND_WINDOW_END = "2026-08-13T00:00:00Z"
SECOND_BLOCK_START = "2026-08-12T18:00:00Z"
SECOND_BLOCK_END = "2026-08-12T23:50:00Z"
SECOND_BLOCK_MINUTES = 350
SECOND_VINTAGE_FROM = "2026-08-01T00:00:00Z"
SECOND_VINTAGE_TO = "2026-11-01T00:00:00Z"


def _hold_credit_cents(tier_base_fee_cents: int) -> int:
    """"5 percent of the client's `tier_base_fee_cents`, rounded to a whole cent"."""
    return round_half_up_to_int(Decimal(tier_base_fee_cents) * Decimal(str(HOLD_CREDIT_PCT)))


def _supersession_world(panel: PanelHarness):
    """A published run, a second still-open run, two deliverables and a new vintage.

    The second run is pinned to the same 2026Q3 vintage as the first and holds one
    350-minute block, so it can be carried to publication after a re-pin. The
    scheduled dataset sits against that open run; the custom analysis sits against
    the already published one and must therefore survive the cascade untouched.
    """
    base = panel.published_run()
    market_id = base["market"]["id"]
    cell_ids = [cell["id"] for cell in base["cells"]]
    subscriber = panel.create_client([market_id], tier="STANDARD")
    panel.set_clock(LATE_CLOCK)
    later_run = panel.open_run(
        market_id,
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=SECOND_WINDOW_START,
        window_end_iso=SECOND_WINDOW_END,
    )
    home = base["households"][0]
    panel.ingest_interval(
        home["tuner"]["id"],
        home["household"]["id"],
        SECOND_BLOCK_START,
        SECOND_BLOCK_END,
        SECOND_BLOCK_MINUTES,
    )
    dataset = panel.schedule_deliverable(
        subscriber["id"], later_run["id"], requested_cell_count=0
    )
    analysis = panel.request_custom_analysis(
        subscriber["id"], base["run"]["id"], requested_cell_count=1
    )
    successor = panel.draft_universe(
        market_id,
        cell_ids,
        vintage_label="2026Q4",
        effective_from=SECOND_VINTAGE_FROM,
        effective_to=SECOND_VINTAGE_TO,
    )
    return {
        "base": base,
        "subscriber": subscriber,
        "later_run": later_run,
        "dataset": dataset,
        "analysis": analysis,
        "successor": successor,
    }


class TestUniverseSupersessionCascade:
    """PRD 3.5's double cascade, carried into PRD 3.8's client ledger."""

    def test_publishing_a_second_vintage_cascades_into_runs_deliverables_and_the_ledger(
        self, panel: PanelHarness
    ):
        """One publication supersedes, repins, holds and credits in a single call.

        PRD 3.5: "The supersession then cascades twice: every processing run of
        that market still pinned to a now-superseded estimate and standing in
        `OPEN`, `EDITED` or `WEIGHTED` is forced to `PENDING_REPIN` with
        `repin_required_reason` `UNIVERSE_SUPERSEDED`; and every client deliverable
        of one of those runs standing in a non-terminal state is moved to `HELD`
        with `hold_reason` `UPSTREAM_RUN_REPIN`."

        Design: Corner/cross_cutting_complexity_layers/universe_supersession_cascade_runs_deliverables_and_client_ledger
        """
        world = _supersession_world(panel)
        published = validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, world["successor"]["id"]
            ),
            200,
        )
        assert published["status"] == "PUBLISHED"
        assert published["published_at"].startswith("2026-08-30T00:00:00")
        # Level 1: the earlier vintage, whose effective_from is earlier, is retired.
        superseded = panel.read_universe(world["base"]["universe"]["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_at"].startswith("2026-08-30T00:00:00")
        # Level 2: the open run is stalled; the published run is terminal and untouched.
        stalled = panel.read_run(world["later_run"]["id"])
        assert stalled["state"] == "PENDING_REPIN"
        assert stalled["repin_required_reason"] == "UNIVERSE_SUPERSEDED"
        finished = panel.read_run(world["base"]["run"]["id"])
        assert finished["state"] == "PUBLISHED"
        assert finished["repin_required_reason"] is None
        # Level 3: only the deliverable of the stalled run is held.
        held = panel.read_deliverable(world["dataset"]["id"])
        assert held["state"] == "HELD"
        assert held["hold_reason"] == "UPSTREAM_RUN_REPIN"
        assert held["held_from_state"] == "SCHEDULED"
        untouched = panel.read_deliverable(world["analysis"]["id"])
        assert untouched["state"] == "REQUESTED"
        assert untouched["hold_reason"] is None
        # Level 4: "A service-level credit of 5 percent of the client's
        # `tier_base_fee_cents`, rounded to a whole cent, is added to
        # `delivery_sla_credit_cents` **only** when the `hold_reason` is
        # `UPSTREAM_RUN_REPIN`" (PRD 3.8).
        subscriber = panel.read_client(world["subscriber"]["id"])
        assert subscriber["tier_base_fee_cents"] == 65000
        assert subscriber["held_deliverable_count"] == 1
        assert subscriber["delivery_sla_credit_cents"] == _hold_credit_cents(65000) == 3250

    def test_a_repin_returns_the_run_to_open_without_lifting_the_hold(
        self, panel: PanelHarness
    ):
        """Re-pinning clears the run's artefacts but leaves the deliverable held.

        PRD 3.8: "The pinned run's `state` must be `PUBLISHED`, otherwise
        `ERR_RUN_NOT_PUBLISHED` — a run still in `PENDING_REPIN` blocks release,
        which is the whole point of the upstream hold".

        Design: Corner/cross_cutting_complexity_layers/universe_supersession_cascade_runs_deliverables_and_client_ledger
        """
        world = _supersession_world(panel)
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, world["successor"]["id"]
            ),
            200,
        )
        repinned = validate_success(
            panel.client.repin_processing_run(
                panel.statistician,
                world["later_run"]["id"],
                universe_estimate_id=world["successor"]["id"],
            ),
            200,
        )
        assert repinned["state"] == "OPEN"
        assert repinned["universe_estimate_id"] == world["successor"]["id"]
        assert repinned["repin_required_reason"] is None
        assert repinned["contributing_household_count"] == 0
        assert repinned["total_weight_mass"] == 0
        assert repinned["projected_average_audience"] is None
        # The hold is not lifted by the repair of its upstream run.
        assert panel.read_deliverable(world["dataset"]["id"])["state"] == "HELD"
        validate_error(
            panel.client.release_deliverable(panel.rep, world["dataset"]["id"]),
            "ERR_RUN_NOT_PUBLISHED",
        )
        assert panel.read_client(world["subscriber"]["id"])["held_deliverable_count"] == 1

    def test_a_row_held_at_publication_misses_the_due_at_fan_out_and_keeps_its_credit(
        self, panel: PanelHarness
    ):
        """Release restores SCHEDULED with a null `due_at`, and the credit stands.

        PRD 3.7: "every client deliverable already pinned to this run and standing
        in `SCHEDULED` becomes due, its `due_at` set to the current logical clock
        plus that client's `delivery_sla_hours`".

        Design: Corner/cross_cutting_complexity_layers/universe_supersession_cascade_runs_deliverables_and_client_ledger
        """
        world = _supersession_world(panel)
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, world["successor"]["id"]
            ),
            200,
        )
        run_id = world["later_run"]["id"]
        validate_success(
            panel.client.repin_processing_run(
                panel.statistician, run_id, universe_estimate_id=world["successor"]["id"]
            ),
            200,
        )
        panel.edit_run(run_id)
        panel.weight_run(run_id)
        republished = panel.publish_run(run_id)
        assert republished["state"] == "PUBLISHED"
        # The row was HELD and not SCHEDULED when the run published, so the
        # commercial clock never started for it.
        still_held = panel.read_deliverable(world["dataset"]["id"])
        assert still_held["state"] == "HELD"
        assert still_held["due_at"] is None
        released = validate_success(
            panel.client.release_deliverable(panel.rep, world["dataset"]["id"]), 200
        )
        assert released["state"] == "SCHEDULED"
        assert released["hold_reason"] is None
        assert released["held_from_state"] is None
        assert released["due_at"] is None
        # "The credit is **not** reversed: `delivery_sla_credit_cents` only ever
        # rises" (PRD 3.8).
        subscriber = panel.read_client(world["subscriber"]["id"])
        assert subscriber["held_deliverable_count"] == 0
        assert subscriber["delivery_sla_credit_cents"] == 3250


# The successor rule set differs from the reference set only in its ascription
# minutes: |36 - 30| / 60 = 0.1 capped sub-score, weighted 0.25, so
# impact_delta_pct is 0.0250 and the tier is MINOR with a 72-hour lead.
SUCCESSOR_ASCRIPTION_MINUTES = 36
ACTIVATION_CLOCK = "2026-08-05T00:00:00Z"
THIRD_WINDOW_START = "2026-08-03T00:00:00Z"
THIRD_WINDOW_END = "2026-08-04T00:00:00Z"


def _governed_supersession(panel: PanelHarness):
    """A published run whose rule set is about to be retired by an activation.

    The change is drafted, assessed against the published run, notified to the one
    contracted client, acknowledged, and the clock is advanced to the notification
    deadline so that activation check 4 is satisfied. The caller receives the run
    as it stood immediately before activation so the two can be compared.
    """
    base = panel.published_run()
    market_id = base["market"]["id"]
    target = base["rule_set"]
    proposed = panel.draft_rule_set(
        missing_interval_ascription_minutes=SUCCESSOR_ASCRIPTION_MINUTES
    )
    subscriber = panel.create_client([market_id], tier="STANDARD")
    dataset = panel.schedule_deliverable(
        subscriber["id"], base["run"]["id"], requested_cell_count=0
    )
    change = panel.draft_change(target["id"], proposed["id"], [market_id])
    panel.assess_change(change["id"], base["run"]["id"])
    notified = panel.notify_change(change["id"])
    rows, _meta = validate_paginated(
        panel.client.list_client_notifications(
            panel.director, methodology_change_id=change["id"], limit=100
        )
    )
    assert len(rows) == 1
    notification = validate_success(
        panel.client.acknowledge_notification(
            panel.client_headers(rows[0]["client_id"]), rows[0]["id"]
        ),
        200,
    )
    run_before = panel.read_run(base["run"]["id"])
    panel.set_clock(ACTIVATION_CLOCK)
    return {
        "base": base,
        "target": target,
        "proposed": proposed,
        "subscriber": subscriber,
        "dataset": dataset,
        "change": change,
        "notified": notified,
        "notification": notification,
        "run_before": run_before,
    }


class TestPinnedRuleSetSurvivesItsOwnSupersession:
    """A governed activation retires a rule set without rewriting published output."""

    def test_activation_supersedes_the_rule_set_but_leaves_the_published_run_pinned(
        self, panel: PanelHarness
    ):
        """Link 2 reaches OPEN and EDITED runs only, so a PUBLISHED run is immune.

        PRD 3.9: "every processing run whose `edit_rule_set_id` is the superseded
        target and whose `state` is `OPEN` or `EDITED` moves to `PENDING_REPIN` with
        `repin_required_reason` `RULE_SET_SUPERSEDED`".

        Design: Corner/cross_cutting_complexity_layers/pinned_rule_set_survives_its_own_supersession_on_a_published_run
        """
        world = _governed_supersession(panel)
        assert world["notified"]["notification_lead_hours"] == NOTIFICATION_LEAD_HOURS["MINOR"]
        assert world["notified"]["notification_deadline_at"].startswith("2026-08-05T00:00:00")
        activated = panel.activate_change(world["change"]["id"])
        # Link 1 in full.
        assert activated["state"] == "EFFECTIVE"
        assert activated["activated_at"].startswith("2026-08-05T00:00:00")
        promoted = panel.read_rule_set(world["proposed"]["id"])
        assert promoted["status"] == "PUBLISHED"
        assert promoted["published_at"].startswith("2026-08-05T00:00:00")
        retired = panel.read_rule_set(world["target"]["id"])
        assert retired["status"] == "SUPERSEDED"
        # The published run keeps the pin to the now-superseded set and every
        # figure it published under it.
        after = panel.read_run(world["base"]["run"]["id"])
        assert after["state"] == "PUBLISHED"
        assert after["edit_rule_set_id"] == world["target"]["id"]
        assert after["repin_required_reason"] is None
        assert after["projected_average_audience"] == world["run_before"]["projected_average_audience"]
        assert after["projected_average_audience"] is not None
        assert after["total_weight_mass"] == world["run_before"]["total_weight_mass"]
        # Link 3 and link 4 never fire, because link 2 caught no run.
        assert panel.read_deliverable(world["dataset"]["id"])["state"] == "SCHEDULED"
        subscriber = panel.read_client(world["subscriber"]["id"])
        assert subscriber["held_deliverable_count"] == 0
        assert subscriber["delivery_sla_credit_cents"] == 0

    def test_the_published_runs_weights_and_intervals_survive_the_activation(
        self, panel: PanelHarness
    ):
        """Only a run caught in EDITED loses its weights; a published one keeps them.

        PRD 3.9: "A run caught in `EDITED` additionally has every household weight
        row deleted, `total_weight_mass` reset to 0 and `projected_average_audience`
        reset to null."

        Design: Corner/cross_cutting_complexity_layers/pinned_rule_set_survives_its_own_supersession_on_a_published_run
        """
        world = _governed_supersession(panel)
        run_id = world["base"]["run"]["id"]
        weights_before, _ = validate_paginated(
            panel.client.list_household_weights(panel.ops, processing_run_id=run_id, limit=100)
        )
        intervals_before, _ = validate_paginated(
            panel.client.list_tuning_intervals(panel.ops, processing_run_id=run_id, limit=100)
        )
        assert len(weights_before) >= 1
        assert len(intervals_before) >= 1
        panel.activate_change(world["change"]["id"])
        weights_after, _ = validate_paginated(
            panel.client.list_household_weights(panel.ops, processing_run_id=run_id, limit=100)
        )
        intervals_after, _ = validate_paginated(
            panel.client.list_tuning_intervals(panel.ops, processing_run_id=run_id, limit=100)
        )
        assert [row["id"] for row in weights_after] == [row["id"] for row in weights_before]
        assert [row["adjusted_weight"] for row in weights_after] == [
            row["adjusted_weight"] for row in weights_before
        ]
        assert [row["id"] for row in intervals_after] == [row["id"] for row in intervals_before]
        assert all(row["processing_run_id"] == run_id for row in intervals_after)

    def test_the_superseded_set_cannot_be_pinned_again_but_its_successor_can(
        self, panel: PanelHarness
    ):
        """A refused pin is inert: the market's version does not move.

        PRD 3.6: "The edit rule set's `status` must be `PUBLISHED`, otherwise
        `ERR_RULE_SET_NOT_PUBLISHED`."

        Design: Corner/cross_cutting_complexity_layers/pinned_rule_set_survives_its_own_supersession_on_a_published_run
        """
        world = _governed_supersession(panel)
        panel.activate_change(world["change"]["id"])
        market_id = world["base"]["market"]["id"]
        universe_id = world["base"]["universe"]["id"]
        before = panel.read_market(market_id)
        refused = panel.client.create_processing_run(
            panel.statistician,
            market_id=market_id,
            universe_estimate_id=universe_id,
            edit_rule_set_id=world["target"]["id"],
            window_start_iso=THIRD_WINDOW_START,
            window_end_iso=THIRD_WINDOW_END,
            expected_market_version=before["version"],
        )
        validate_error(refused, "ERR_RULE_SET_NOT_PUBLISHED")
        assert_version_unchanged(before, panel.read_market(market_id))
        # The successor, published by link 1, is a legal pin.
        opened = panel.open_run(
            market_id,
            universe_id,
            world["proposed"]["id"],
            window_start_iso=THIRD_WINDOW_START,
            window_end_iso=THIRD_WINDOW_END,
        )
        assert opened["state"] == "OPEN"
        assert opened["edit_rule_set_id"] == world["proposed"]["id"]
        assert opened["repin_required_reason"] is None


OCC_CLOCK = "2026-08-11T00:00:00Z"
FOURTH_WINDOW_START = "2026-08-09T00:00:00Z"
FOURTH_WINDOW_END = "2026-08-10T00:00:00Z"
BUDGET_DELTA_CENTS = 100000
LATER_VINTAGE_FROM = "2026-11-01T00:00:00Z"
LATER_VINTAGE_TO = "2027-02-01T00:00:00Z"


class TestStaleParentVersionsOnEveryOccEndpoint:
    """The three tokens of PRD 2.7, interleaved on the same two parents."""

    def test_the_market_token_moves_with_every_declared_bump_and_both_holders_refuse_a_stale_one(
        self, panel: PanelHarness
    ):
        """A budget move and a universe draft each advance the token by one.

        PRD 2.7: "Opening a processing run requires a non-optional
        `expected_market_version` input carrying the client's last observed
        `version` of the target `Market`. If that value does not equal the market's
        current `version`, the request is rejected with `ERR_STALE_MARKET_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_refused_on_every_declared_occ_endpoint
        """
        base = panel.published_run()
        panel.set_clock(OCC_CLOCK)
        market_id = base["market"]["id"]
        cell_id = base["cells"][0]["id"]
        before = panel.read_market(market_id)
        mv_a = before["version"]
        # "The market's `incentive_budget_cents` moves by that delta and the
        # market's `version` advances by one" (PRD 3.1).
        adjusted = validate_success(
            panel.client.adjust_market_budget(
                panel.ops,
                market_id,
                delta_cents=BUDGET_DELTA_CENTS,
                memo="Top up the suburban cell before the autumn recruitment push.",
            ),
            200,
        )
        mv_b = adjusted["version"]
        assert mv_b == mv_a + 1
        assert (
            adjusted["incentive_budget_cents"]
            == before["incentive_budget_cents"] + BUDGET_DELTA_CENTS
        )
        populations = [cell_population(cell_id, 110000, 275000)]
        stale_draft = panel.client.create_universe_estimate(
            panel.statistician,
            market_id=market_id,
            vintage_label="2026Q4",
            effective_from=SECOND_VINTAGE_FROM,
            effective_to=SECOND_VINTAGE_TO,
            cell_populations=populations,
            expected_market_version=mv_a,
        )
        validate_error(stale_draft, "ERR_STALE_MARKET_VERSION")
        assert panel.market_version(market_id) == mv_b
        drafted = validate_success(
            panel.client.create_universe_estimate(
                panel.statistician,
                market_id=market_id,
                vintage_label="2026Q4",
                effective_from=SECOND_VINTAGE_FROM,
                effective_to=SECOND_VINTAGE_TO,
                cell_populations=populations,
                expected_market_version=mv_b,
            ),
            201,
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["total_population_households"] == 110000
        assert drafted["total_population_persons"] == 275000
        # "Drafting also advances the parent market's `version` by one" (PRD 3.5).
        mv_c = panel.market_version(market_id)
        assert mv_c == mv_b + 1
        # The run opener now holds a token one behind, and is refused in turn.
        stale_run = panel.client.create_processing_run(
            panel.statistician,
            market_id=market_id,
            universe_estimate_id=base["universe"]["id"],
            edit_rule_set_id=base["rule_set"]["id"],
            window_start_iso=FOURTH_WINDOW_START,
            window_end_iso=FOURTH_WINDOW_END,
            expected_market_version=mv_b,
        )
        validate_error(stale_run, "ERR_STALE_MARKET_VERSION")
        assert panel.market_version(market_id) == mv_c
        opened = validate_success(
            panel.client.create_processing_run(
                panel.statistician,
                market_id=market_id,
                universe_estimate_id=base["universe"]["id"],
                edit_rule_set_id=base["rule_set"]["id"],
                window_start_iso=FOURTH_WINDOW_START,
                window_end_iso=FOURTH_WINDOW_END,
                expected_market_version=mv_c,
            ),
            201,
        )
        assert opened["state"] == "OPEN"
        assert opened["window_minutes"] == 1440

    def test_publishing_a_vintage_leaves_the_market_token_where_it_was(
        self, panel: PanelHarness
    ):
        """No market field moves at publication, so a held token stays usable.

        PRD 2.5: "`version` — an integer that starts at 1 on creation and increments
        by exactly 1 on every mutation of the row."

        Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_refused_on_every_declared_occ_endpoint
        """
        base = panel.published_run()
        market_id = base["market"]["id"]
        cell_id = base["cells"][0]["id"]
        successor = panel.draft_universe(
            market_id,
            [cell_id],
            vintage_label="2026Q4",
            effective_from=SECOND_VINTAGE_FROM,
            effective_to=SECOND_VINTAGE_TO,
        )
        panel.set_clock(LATE_CLOCK)
        before = panel.read_market(market_id)
        validate_success(
            panel.client.publish_universe_estimate(panel.statistician, successor["id"]), 200
        )
        after = panel.read_market(market_id)
        assert_version_unchanged(before, after)
        # A caller who read the market before the publication still holds a live
        # token, because publication mutated no market field.
        accepted = validate_success(
            panel.client.create_universe_estimate(
                panel.statistician,
                market_id=market_id,
                vintage_label="2027Q1",
                effective_from=LATER_VINTAGE_FROM,
                effective_to=LATER_VINTAGE_TO,
                cell_populations=[cell_population(cell_id)],
                expected_market_version=before["version"],
            ),
            201,
        )
        assert accepted["status"] == "DRAFT"
        assert panel.market_version(market_id) == before["version"] + 1

    def test_the_impact_analysis_token_is_the_changes_own_version(
        self, panel: PanelHarness
    ):
        """The third token guards a different parent with a different error id.

        PRD 2.7: "Running an impact analysis on a methodology change requires a
        non-optional `expected_methodology_change_version` input matching that
        `MethodologyChange` row's current `version`; a mismatch is rejected with
        `ERR_STALE_METHODOLOGY_CHANGE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_refused_on_every_declared_occ_endpoint
        """
        base = panel.published_run()
        target = base["rule_set"]
        proposed = panel.draft_rule_set(
            missing_interval_ascription_minutes=SUCCESSOR_ASCRIPTION_MINUTES
        )
        change = panel.draft_change(target["id"], proposed["id"], [base["market"]["id"]])
        change_version = change["version"]
        assert change_version == 1
        assert change["impact_tier"] is None
        mismatched = panel.client.create_impact_analysis(
            panel.director,
            change["id"],
            baseline_processing_run_id=base["run"]["id"],
            expected_methodology_change_version=change_version + 1,
        )
        validate_error(mismatched, "ERR_STALE_METHODOLOGY_CHANGE_VERSION")
        refused = panel.read_change(change["id"])
        assert refused["version"] == change_version
        assert refused["state"] == "DRAFT"
        get_success_data(
            panel.client.create_impact_analysis(
                panel.director,
                change["id"],
                baseline_processing_run_id=base["run"]["id"],
                expected_methodology_change_version=change_version,
            )
        )
        assessed = panel.read_change(change["id"])
        assert assessed["state"] == "IMPACT_ASSESSED"
        # "moves the change to `IMPACT_ASSESSED`, and advances the change's
        # `version` by one" (PRD 3.9).
        assert assessed["version"] == change_version + 1
        expected_delta = expected_impact_delta_pct(target, proposed)
        assert assessed["impact_delta_pct"] == expected_delta == 0.025
        assert assessed["impact_tier"] == expected_impact_tier(expected_delta) == "MINOR"
        assert assessed["notification_lead_hours"] == NOTIFICATION_LEAD_HOURS["MINOR"]


BOOST_CELL_TARGET = 5
BOOST_CELL_BASE_CENTS = 2000
ON_TARGET_CLOCK = "2026-08-05T00:00:00Z"
RETIREMENT_CLOCK = "2026-08-06T00:00:00Z"


def _five_slot_cell(panel: PanelHarness):
    """One cell of five slots holding three in-tab homes and a fourth waiting.

    The fourth home is recruited and metered at the startup clock but not yet
    enumerated, so it sits in `ENUM_PENDING` and outside the in-tab count. A single
    later enumeration therefore takes the cell from 3/5 to exactly 4/5.
    """
    market, cells = panel.market_with_cells(
        [
            {
                "target_households": BOOST_CELL_TARGET,
                "base_incentive_cents": BOOST_CELL_BASE_CENTS,
            }
        ]
    )
    cell = cells[0]
    homes = [
        panel.active_household(market["id"], cell["id"], persons_count=2)
        for _ in range(3)
    ]
    pending = panel.recruit_household(market["id"], cell["id"], persons_count=2)
    pending_tuner = panel.installed_meter(pending["id"], meter_type="TV_TUNER")
    return {
        "market": market,
        "cell": cell,
        "homes": homes,
        "pending": pending,
        "pending_tuner": pending_tuner,
    }


class TestIncentiveBoostReleasesAtEightTenthsAndReArms:
    """The boost is a threshold, not a latch: it tracks the graded stance."""

    def test_three_of_five_slots_leaves_the_boost_armed_and_the_reservation_standing(
        self, panel: PanelHarness
    ):
        """0.6000 grades UNDER_TARGET, so the quarter-of-base reservation stands.

        PRD 3.1: "When the graded status is `UNDER_TARGET` and the cell's boost is
        not already armed, `incentive_boost_active` becomes true,
        `effective_incentive_multiplier` becomes 1.25, and the market's
        `incentive_budget_reserved_cents` rises by the cell's `base_incentive_cents`
        multiplied by one quarter and by `target_households`, rounded half up to a
        whole cent."

        Design: Corner/cross_cutting_complexity_layers/incentive_boost_releases_at_exactly_eight_tenths_fill_and_re_arms_on_retirement
        """
        world = _five_slot_cell(panel)
        cell = panel.read_quota_cell(world["cell"]["id"])
        assert cell["intab_count"] == 3
        assert cell["fill_rate"] == expected_fill_rate(3, BOOST_CELL_TARGET) == 0.6
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER
        reservation = expected_boost_reservation(BOOST_CELL_BASE_CENTS, BOOST_CELL_TARGET)
        assert reservation == 2500
        market = panel.read_market(world["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == reservation
        assert market["under_target_cell_count"] == 1
        assert market["filled_cell_count"] == 0
        # Clause 4 of the posture walk, stamped when the first cell was created.
        assert market["recruitment_posture"] == "OPEN"
        assert market["posture_changed_at"].startswith("2026-08-01T00:00:00")
        assert panel.read_household(world["pending"]["id"])["status"] == "ENUM_PENDING"

    def test_the_fourth_home_lands_exactly_on_eight_tenths_and_releases_the_boost(
        self, panel: PanelHarness
    ):
        """A rate of exactly 0.8000 is ON_TARGET, which disarms the boost.

        PRD 3.1: "`FILLED` when the rate is 1.0000 or more, `ON_TARGET` when the
        rate is 0.8000 or more but below 1.0000, and `UNDER_TARGET` in every other
        case."

        Design: Corner/cross_cutting_complexity_layers/incentive_boost_releases_at_exactly_eight_tenths_fill_and_re_arms_on_retirement
        """
        world = _five_slot_cell(panel)
        panel.set_clock(ON_TARGET_CLOCK)
        activated = panel.enumerate_household(
            world["pending"]["id"], roster_persons_count=2, tv_sets_count=1
        )
        assert activated["enumeration_verdict"] == "COMPLIANT"
        assert activated["status"] == "ACTIVE"
        cell = panel.read_quota_cell(world["cell"]["id"])
        assert cell["intab_count"] == 4
        assert cell["fill_rate"] == expected_fill_rate(4, BOOST_CELL_TARGET) == 0.8
        assert cell["quota_status"] == "ON_TARGET"
        # "When the graded status is anything other than `UNDER_TARGET` and the
        # cell's boost is currently armed, `incentive_boost_active` becomes false,
        # `effective_incentive_multiplier` returns to 1.00, and the market's
        # `incentive_budget_reserved_cents` falls by that same figure" (PRD 3.1).
        assert cell["incentive_boost_active"] is False
        assert cell["effective_incentive_multiplier"] == UNBOOSTED_MULTIPLIER
        market = panel.read_market(world["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 0
        assert market["under_target_cell_count"] == 0
        assert market["filled_cell_count"] == 0
        # Clause 3 now matches, so the posture moves and the stamp moves with it.
        assert market["recruitment_posture"] == "RESTRICTED"
        assert market["posture_changed_at"].startswith("2026-08-05T00:00:00")

    def test_retiring_an_active_home_re_arms_the_boost_as_an_exact_inverse(
        self, panel: PanelHarness
    ):
        """Falling back under target re-arms the same reservation to the cent.

        PRD 3.1: "Because the reservation is recomputed from the cell's own
        `base_incentive_cents` and `target_households` each time, arming and
        disarming are exact inverses."

        Design: Corner/cross_cutting_complexity_layers/incentive_boost_releases_at_exactly_eight_tenths_fill_and_re_arms_on_retirement
        """
        world = _five_slot_cell(panel)
        panel.set_clock(ON_TARGET_CLOCK)
        panel.enumerate_household(
            world["pending"]["id"], roster_persons_count=2, tv_sets_count=1
        )
        assert panel.read_quota_cell(world["cell"]["id"])["incentive_boost_active"] is False
        panel.set_clock(RETIREMENT_CLOCK)
        retired_home = world["homes"][0]["household"]
        retired = validate_success(
            panel.client.retire_household(
                panel.ops,
                retired_home["id"],
                retired_reason="Household moved out of the market area.",
            ),
            200,
        )
        assert retired["status"] == "RETIRED"
        assert retired["retired_reason"] == "Household moved out of the market area."
        # "If, and only if, the household was `ACTIVE` at the moment of retirement,
        # its cell's `intab_count` falls by one, the cell is re-graded and the
        # market posture is recomputed" (PRD 3.2).
        cell = panel.read_quota_cell(world["cell"]["id"])
        assert cell["intab_count"] == 3
        assert cell["fill_rate"] == expected_fill_rate(3, BOOST_CELL_TARGET) == 0.6
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER
        market = panel.read_market(world["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == expected_boost_reservation(
            BOOST_CELL_BASE_CENTS, BOOST_CELL_TARGET
        )
        assert market["under_target_cell_count"] == 1
        assert market["recruitment_posture"] == "OPEN"
        assert market["posture_changed_at"].startswith("2026-08-06T00:00:00")
        # "every meter of the household whose `install_status` is `INSTALLED` moves
        # to `REMOVED`" (PRD 3.2).
        assert panel.read_meter(world["homes"][0]["tuner"]["id"])["install_status"] == "REMOVED"
        # Retirement claws back no money.
        assert market["incentive_budget_committed_cents"] == 0
