"""Cascades that travel several entities deep from a single call.

One fault report walks meter to household to quota cell to boost reservation to
market posture, and one methodology activation walks rule set to processing run
to client deliverable to client counters. Both are asserted at every link,
including the conditional links that must not fire.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_success
from test_helpers.assertions import (
    expected_boost_reservation,
    expected_fill_rate,
    round_half_up_to_int,
)
from test_helpers.constants import (
    BOOSTED_MULTIPLIER,
    HOLD_CREDIT_PCT,
    STANDARD_BASE_FEE_CENTS,
    UNBOOSTED_MULTIPLIER,
)
from test_helpers.factories import cell_population
from test_helpers.fixtures import PanelHarness

RECIPE_RULE_SET = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}
PROPOSED_RULE_SET = {
    "missing_interval_ascription_minutes": 30,
    "invalid_tuning_max_minutes": 600,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.0,
    "fault_missing_minutes_threshold": 1440,
}


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC stamp whether or not it carries fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _filled_single_cell_market(panel: PanelHarness, extra_meter_types: tuple = ()) -> dict:
    """A market whose only cell is FILLED by one in-tab home, at the startup clock.

    Nothing here advances the clock, so every stamp the cascade writes is
    2026-08-01T00:00:00Z and the market's posture stands at `CLOSED` under
    clause 2 before the fault is filed.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 1, "base_incentive_cents": 2000}], incentive_budget_cents=1000000
    )
    household = panel.recruit_household(market["id"], cells[0]["id"], persons_count=2)
    tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
    extras = [
        panel.ship_meter(household["id"], meter_type=meter_type)
        for meter_type in extra_meter_types
    ]
    panel.install_meter(tuner["id"])
    for meter in extras:
        panel.install_meter(meter["id"])
    panel.enumerate_household(household["id"], roster_persons_count=2, tv_sets_count=1)
    return {
        "market": market,
        "cell": cells[0],
        "household": panel.read_household(household["id"]),
        "tuner": tuner,
        "extras": extras,
    }


class TestFaultReportCascadeFiveLinksDeep:
    """One POST to a meter moves a household, a cell, a reservation and a posture."""

    def test_fault_report_drops_the_home_out_of_tab_and_empties_its_cell(
        self, panel: PanelHarness
    ):
        """Links 1 to 3: FAULTED device, FAULT_HOLD home, cell back to 0 in tab.

        PRD 3.3: "**Link 3**: the household's quota cell has `intab_count`
        reduced by one and the fill calculation re-grades the cell."

        Design: Difficulty/transitive_cascade/fault_report_cascade_meter_household_cell_boost_posture
        """
        built = _filled_single_cell_market(panel)
        cell = panel.read_quota_cell(built["cell"]["id"])
        market = panel.read_market(built["market"]["id"])
        assert built["household"]["status"] == "ACTIVE"
        assert cell["intab_count"] == 1
        assert cell["quota_status"] == "FILLED"
        assert cell["incentive_boost_active"] is False
        assert market["recruitment_posture"] == "CLOSED"
        assert market["incentive_budget_reserved_cents"] == 0

        validate_success(
            panel.client.report_meter_fault(panel.tech, built["tuner"]["id"], "POWER_LOSS"), 200
        )

        meter = panel.read_meter(built["tuner"]["id"])
        assert meter["health_status"] == "FAULTED"
        assert meter["last_fault_code"] == "POWER_LOSS"
        assert meter["fault_count"] == 1
        household = panel.read_household(built["household"]["id"])
        assert household["status"] == "FAULT_HOLD"
        # The verdict is a fact about the last enumeration and is not rewritten.
        assert household["enumeration_verdict"] == "COMPLIANT"
        cell = panel.read_quota_cell(built["cell"]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == 0.0000 == expected_fill_rate(0, 1)

    def test_fault_report_rearms_the_boost_and_reopens_recruitment(self, panel: PanelHarness):
        """Links 4 and 5: 500 cents reserved again and the posture back to OPEN.

        PRD 3.3: "the cell's `incentive_boost_active` becomes true,
        `effective_incentive_multiplier` becomes 1.25, and the market's
        `incentive_budget_reserved_cents` rises by `base_incentive_cents`
        multiplied by one quarter and by `target_households`, rounded half up to
        a whole cent."

        Design: Difficulty/transitive_cascade/fault_report_cascade_meter_household_cell_boost_posture
        """
        built = _filled_single_cell_market(panel)

        validate_success(
            panel.client.report_meter_fault(panel.tech, built["tuner"]["id"], "POWER_LOSS"), 200
        )

        cell = panel.read_quota_cell(built["cell"]["id"])
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER
        market = panel.read_market(built["market"]["id"])
        # 2000 * 0.25 * 1 = 500.
        assert market["incentive_budget_reserved_cents"] == 500
        assert market["incentive_budget_reserved_cents"] == expected_boost_reservation(2000, 1)
        assert market["filled_cell_count"] == 0
        assert market["under_target_cell_count"] == 1
        assert market["quota_cell_count"] == 1
        # Clause 2 no longer matches and clause 4 now does: CLOSED becomes OPEN.
        assert market["recruitment_posture"] == "OPEN"
        assert _instant(market["posture_changed_at"]) == _instant("2026-08-01T00:00:00Z")
        # Five links deep, and the install dimension never moved.
        assert panel.read_meter(built["tuner"]["id"])["install_status"] == "INSTALLED"

    def test_faulted_streaming_router_stops_the_cascade_dead_at_link_one(
        self, panel: PanelHarness
    ):
        """A router fault raises `fault_count` and touches nothing downstream.

        PRD 3.3: "A faulted streaming router, or a faulted tuner at a home that
        still has a second healthy installed tuner, stops the cascade dead at
        link 1."

        Design: Difficulty/transitive_cascade/fault_report_cascade_meter_household_cell_boost_posture
        """
        built = _filled_single_cell_market(panel, extra_meter_types=("STREAMING_ROUTER",))
        router = built["extras"][0]

        validate_success(
            panel.client.report_meter_fault(panel.tech, router["id"], "NO_SIGNAL"), 200
        )

        meter = panel.read_meter(router["id"])
        assert meter["health_status"] == "FAULTED"
        assert meter["fault_count"] == 1
        assert meter["install_status"] == "INSTALLED"
        # Link 2's condition names `TV_TUNER` only, so links 2 to 5 never fire.
        assert panel.read_household(built["household"]["id"])["status"] == "ACTIVE"
        cell = panel.read_quota_cell(built["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["quota_status"] == "FILLED"
        assert cell["incentive_boost_active"] is False
        assert cell["effective_incentive_multiplier"] == UNBOOSTED_MULTIPLIER
        market = panel.read_market(built["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 0
        assert market["recruitment_posture"] == "CLOSED"
        assert panel.read_meter(built["tuner"]["id"])["health_status"] == "HEALTHY"


def _acknowledged_change(panel: PanelHarness) -> dict:
    """A MATERIAL change past its notification deadline, with live downstream work.

    Run A is `PUBLISHED` and is the baseline of the impact analysis; run B is
    still `OPEN` on the same pinned rule set and carries a `SCHEDULED` dataset
    for the one contracted subscriber. The clock is left standing exactly on
    `notification_deadline_at`, which PRD 3.9 check 4 admits.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 1, "base_incentive_cents": 2000}], incentive_budget_cents=1000000
    )
    target_rule_set = panel.published_rule_set(**RECIPE_RULE_SET)
    proposed_rule_set = panel.draft_rule_set(**PROPOSED_RULE_SET)
    universe = panel.published_universe(
        market["id"],
        [cells[0]["id"]],
        cell_populations=[cell_population(cells[0]["id"], 120000, 300000)],
    )
    home = panel.active_household(market["id"], cells[0]["id"], persons_count=2)
    panel.set_clock("2026-08-11T00:00:00Z")
    panel.ingest_interval(
        home["tuner"]["id"],
        home["household"]["id"],
        "2026-08-10T18:00:00Z",
        "2026-08-10T23:50:00Z",
        350,
    )
    run_a = panel.open_run(
        market["id"],
        universe["id"],
        target_rule_set["id"],
        window_start_iso="2026-08-10T00:00:00Z",
        window_end_iso="2026-08-11T00:00:00Z",
    )
    panel.edit_run(run_a["id"])
    panel.weight_run(run_a["id"], weight_variant="FINAL")
    panel.set_clock("2026-08-12T00:00:00Z")
    run_a = panel.publish_run(run_a["id"])
    run_b = panel.open_run(
        market["id"],
        universe["id"],
        target_rule_set["id"],
        window_start_iso="2026-08-11T00:00:00Z",
        window_end_iso="2026-08-12T00:00:00Z",
    )
    client = panel.create_client([market["id"]], tier="STANDARD", name="Theta Agency")
    deliverable = panel.schedule_deliverable(client["id"], run_b["id"], requested_cell_count=4)
    change = panel.draft_change(
        target_rule_set["id"],
        proposed_rule_set["id"],
        [market["id"]],
        title="Promote the tightened 2026Q4 editing rules",
    )
    change = panel.assess_change(change["id"], run_a["id"])
    change = panel.notify_change(change["id"])
    panel.acknowledge_all(change["id"])
    panel.set_clock("2026-09-11T00:00:00Z")
    return {
        "market": market,
        "target_rule_set": target_rule_set,
        "proposed_rule_set": proposed_rule_set,
        "run_a": run_a,
        "run_b": run_b,
        "client": client,
        "deliverable": deliverable,
        "change": change,
    }


class TestMethodologyActivationCascadeFourLinksDeep:
    """One activation flips two rule sets, re-pins a run and holds a deliverable."""

    def test_activation_publishes_the_proposal_and_repins_only_the_live_run(
        self, panel: PanelHarness
    ):
        """Links 1 and 2: the target is superseded and the OPEN run needs re-pinning.

        PRD 3.9: "**Link 2**, caused by link 1's supersession: every processing
        run whose `edit_rule_set_id` is the superseded target and whose `state`
        is `OPEN` or `EDITED` moves to `PENDING_REPIN` with
        `repin_required_reason` `RULE_SET_SUPERSEDED`".

        Design: Difficulty/transitive_cascade/methodology_activation_cascade_rule_set_run_deliverable_hold
        """
        built = _acknowledged_change(panel)
        assert built["change"]["state"] == "NOTIFIED"
        assert built["change"]["impact_tier"] == "MATERIAL"
        assert _instant(built["change"]["notification_deadline_at"]) == _instant(
            "2026-09-11T00:00:00Z"
        )
        assert panel.read_run(built["run_b"]["id"])["state"] == "OPEN"

        change = panel.activate_change(built["change"]["id"])

        assert change["state"] == "EFFECTIVE"
        assert _instant(change["activated_at"]) == _instant("2026-09-11T00:00:00Z")
        proposed = panel.read_rule_set(built["proposed_rule_set"]["id"])
        assert proposed["status"] == "PUBLISHED"
        assert _instant(proposed["published_at"]) == _instant("2026-09-11T00:00:00Z")
        assert panel.read_rule_set(built["target_rule_set"]["id"])["status"] == "SUPERSEDED"

        run_b = panel.read_run(built["run_b"]["id"])
        assert run_b["state"] == "PENDING_REPIN"
        assert run_b["repin_required_reason"] == "RULE_SET_SUPERSEDED"
        # The baseline run is terminal, so link 2's state filter passes it over.
        run_a = panel.read_run(built["run_a"]["id"])
        assert run_a["state"] == "PUBLISHED"
        assert run_a["repin_required_reason"] is None

    def test_activation_holds_the_downstream_deliverable_and_credits_the_client(
        self, panel: PanelHarness
    ):
        """Links 3 and 4: the SCHEDULED dataset is held and 3250 cents are credited.

        PRD 3.9: "**Link 4**, caused by link 3's holds: for each held row the
        owning client's `held_deliverable_count` rises by one and its
        `delivery_sla_credit_cents` rises by 5 percent of that client's
        `tier_base_fee_cents`, rounded half up to a whole cent."

        Design: Difficulty/transitive_cascade/methodology_activation_cascade_rule_set_run_deliverable_hold
        """
        built = _acknowledged_change(panel)
        assert built["deliverable"]["state"] == "SCHEDULED"
        assert built["client"]["tier_base_fee_cents"] == STANDARD_BASE_FEE_CENTS
        assert built["client"]["held_deliverable_count"] == 0
        assert built["client"]["delivery_sla_credit_cents"] == 0

        change = panel.activate_change(built["change"]["id"])

        deliverable = panel.read_deliverable(built["deliverable"]["id"])
        assert deliverable["state"] == "HELD"
        assert deliverable["held_from_state"] == "SCHEDULED"
        assert deliverable["hold_reason"] == "UPSTREAM_RUN_REPIN"
        client = panel.read_client(built["client"]["id"])
        assert client["held_deliverable_count"] == 1
        # 5 percent of the STANDARD base fee of 65000 cents.
        assert client["delivery_sla_credit_cents"] == 3250
        assert client["delivery_sla_credit_cents"] == round_half_up_to_int(
            STANDARD_BASE_FEE_CENTS * HOLD_CREDIT_PCT
        )
        # The change kept the counters that let it through check 3.
        assert change["notified_client_count"] == 1
        assert change["acknowledged_client_count"] == 1
        assert change["revision_count"] == 0
