"""Lifecycles that are not a straight line.

A meter carries two status dimensions that move independently of each other, and
a methodology change walks a loop that returns it to `DRAFT` while keeping the
revision counter that only the revision step may touch. Both shapes are what a
single linear state field cannot represent.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_success
from test_helpers.assertions import (
    expected_fill_rate,
    expected_impact_delta_pct,
    expected_impact_subscores,
    expected_impact_tier,
    expected_scan_health,
    expected_suspect_floor,
)
from test_helpers.constants import (
    BOOSTED_MULTIPLIER,
    LEAD_HOURS_MATERIAL,
    TIER_MATERIAL_THRESHOLD,
    UNBOOSTED_MULTIPLIER,
)
from test_helpers.factories import cell_population
from test_helpers.fixtures import WINDOW_MINUTES, PanelHarness

RECIPE_RULE_SET = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}

# The change's target and proposal, three thresholds apart in each direction.
TARGET_RULE_SET = {
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


def _scannable_run(panel: PanelHarness) -> dict:
    """One in-tab home reporting 350 of the window's 1440 minutes, and an OPEN run."""
    base = panel.panel_with_data(
        household_specs=[
            {
                "persons_count": 2,
                "intervals": [("2026-08-01T18:00:00Z", "2026-08-01T23:50:00Z", 350)],
            }
        ],
        cell_specs=[{"target_households": 1, "base_incentive_cents": 2000}],
        **RECIPE_RULE_SET,
    )
    base["run"] = panel.open_run_over(base)
    base["household"] = base["households"][0]["household"]
    base["tuner"] = base["households"][0]["tuner"]
    return base


class TestMeterInstallAndHealthMoveIndependently:
    """`install_status` and `health_status` never constrain each other's value."""

    def test_coverage_scan_escalates_health_and_leaves_every_other_dimension_alone(
        self, panel: PanelHarness
    ):
        """A 1090-minute shortfall makes the device SUSPECT and moves nothing else.

        PRD 3.3: "Missing minutes at or above the suspect floor but below the
        threshold drive `health_status` to `SUSPECT`".

        Design: Difficulty/non_linear_state_machine/meter_install_and_health_dimensions_evolve_in_parallel
        """
        built = _scannable_run(panel)
        assert built["run"]["state"] == "OPEN"
        assert built["run"]["window_minutes"] == WINDOW_MINUTES

        validate_success(panel.client.detect_faults(panel.statistician, built["run"]["id"]), 200)

        # 1440 - 350 = 1090, at or above the floor of 1440 / 2 = 720 and below
        # the threshold of 1440 itself.
        assert expected_suspect_floor(1440) == 720
        assert expected_scan_health(1090, 1440, "HEALTHY") == "SUSPECT"
        meter = panel.read_meter(built["tuner"]["id"])
        assert meter["health_status"] == "SUSPECT"
        assert meter["missing_minutes_last_scan"] == 1090
        # The scan escalated health only: the install dimension, the lifetime
        # counter and the fault code are all untouched by a SUSPECT verdict.
        assert meter["install_status"] == "INSTALLED"
        assert meter["fault_count"] == 0
        assert meter["last_fault_code"] is None
        assert panel.read_household(built["household"]["id"])["status"] == "ACTIVE"
        assert panel.read_quota_cell(built["cells"][0]["id"])["intab_count"] == 1
        assert panel.read_run(built["run"]["id"])["state"] == "OPEN"

    def test_fault_report_moves_health_to_faulted_while_the_device_stays_installed(
        self, panel: PanelHarness
    ):
        """A hand-filed fault on a SUSPECT device leaves `install_status` INSTALLED.

        PRD 3.3: "Neither dimension constrains the other's stored value: a
        `REMOVED` meter retains whatever `health_status` it had when it was
        pulled, and a `FAULTED` meter is still `INSTALLED` until someone removes
        it."

        Design: Difficulty/non_linear_state_machine/meter_install_and_health_dimensions_evolve_in_parallel
        """
        built = _scannable_run(panel)
        validate_success(panel.client.detect_faults(panel.statistician, built["run"]["id"]), 200)
        assert panel.read_meter(built["tuner"]["id"])["health_status"] == "SUSPECT"

        validate_success(
            panel.client.report_meter_fault(panel.tech, built["tuner"]["id"], "NO_SIGNAL"), 200
        )

        meter = panel.read_meter(built["tuner"]["id"])
        assert meter["health_status"] == "FAULTED"
        assert meter["install_status"] == "INSTALLED"
        assert meter["fault_count"] == 1
        assert meter["last_fault_code"] == "NO_SIGNAL"
        # Links 2 and 3 of the cascade: the only healthy installed tuner is gone.
        household = panel.read_household(built["household"]["id"])
        assert household["status"] == "FAULT_HOLD"
        assert household["enumeration_verdict"] == "COMPLIANT"
        cell = panel.read_quota_cell(built["cells"][0]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == 0.0000
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER
        assert panel.read_run(built["run"]["id"])["state"] == "OPEN"

    def test_repair_returns_health_to_healthy_and_keeps_the_lifetime_fault_count(
        self, panel: PanelHarness
    ):
        """The repair clears health and the scan shortfall but never `fault_count`.

        PRD 3.3: "The repair sets `health_status` to `HEALTHY`, clears
        `last_fault_code` back to null and resets `missing_minutes_last_scan` to
        0. What it does **not** do is undo `fault_count`, which is a lifetime
        counter and only ever rises."

        Design: Difficulty/non_linear_state_machine/meter_install_and_health_dimensions_evolve_in_parallel
        """
        built = _scannable_run(panel)
        validate_success(panel.client.detect_faults(panel.statistician, built["run"]["id"]), 200)
        validate_success(
            panel.client.report_meter_fault(panel.tech, built["tuner"]["id"], "NO_SIGNAL"), 200
        )

        validate_success(
            panel.client.repair_meter(
                panel.tech, built["tuner"]["id"], "Replaced the aerial lead and re-tuned."
            ),
            200,
        )

        meter = panel.read_meter(built["tuner"]["id"])
        assert meter["health_status"] == "HEALTHY"
        assert meter["last_fault_code"] is None
        assert meter["missing_minutes_last_scan"] == 0
        assert meter["fault_count"] == 1
        assert meter["install_status"] == "INSTALLED"
        # The compensating counterpart of the cascade puts the home back in tab.
        assert panel.read_household(built["household"]["id"])["status"] == "ACTIVE"
        cell = panel.read_quota_cell(built["cells"][0]["id"])
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == expected_fill_rate(1, 1)
        assert cell["quota_status"] == "FILLED"
        assert cell["effective_incentive_multiplier"] == UNBOOSTED_MULTIPLIER
        assert panel.read_market(built["market"]["id"])["incentive_budget_reserved_cents"] == 0


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC stamp whether or not it carries fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _notified_change(panel: PanelHarness) -> dict:
    """A MATERIAL change, notified to one subscriber, over a PUBLISHED baseline run.

    The baseline run projects 120000 households over its single contributor and
    350 of the window's 1440 minutes, so its `projected_average_audience` is
    29167 - the figure the impact analysis copies for later disclosure.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 1, "base_incentive_cents": 2000}], incentive_budget_cents=1000000
    )
    target_rule_set = panel.published_rule_set(**TARGET_RULE_SET)
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
    run = panel.open_run(
        market["id"],
        universe["id"],
        target_rule_set["id"],
        window_start_iso="2026-08-10T00:00:00Z",
        window_end_iso="2026-08-11T00:00:00Z",
    )
    panel.edit_run(run["id"])
    panel.weight_run(run["id"], weight_variant="FINAL")
    panel.set_clock("2026-08-12T00:00:00Z")
    run = panel.publish_run(run["id"])
    client = panel.create_client([market["id"]], tier="STANDARD", name="Zeta Buying Group")
    change = panel.draft_change(
        target_rule_set["id"],
        proposed_rule_set["id"],
        [market["id"]],
        title="Retire the 2026Q3 editing thresholds",
    )
    return {
        "market": market,
        "cells": cells,
        "target_rule_set": target_rule_set,
        "proposed_rule_set": proposed_rule_set,
        "universe": universe,
        "run": run,
        "client": client,
        "change": change,
    }


class TestMethodologyChangeRevisionCycle:
    """DRAFT to IMPACT_ASSESSED to NOTIFIED and back to DRAFT, then round again."""

    def test_impact_analysis_scores_material_and_fixes_the_disclosure_lead(
        self, panel: PanelHarness
    ):
        """Three threshold moves score 0.5550, which is MATERIAL and owes 720 hours.

        PRD 3.9: "`impact_delta_pct` is 0.40 times the cap sub-score plus 0.35
        times the tuning sub-score plus 0.25 times the ascription sub-score,
        rounded half up to 4 decimal places."

        Design: Difficulty/non_linear_state_machine/methodology_change_revision_cycle_returns_to_draft
        """
        built = _notified_change(panel)
        assert built["change"]["state"] == "DRAFT"
        assert built["change"]["impact_delta_pct"] == 0.0000
        assert built["change"]["impact_tier"] is None
        assert built["change"]["revision_count"] == 0
        assert built["run"]["projected_average_audience"] == 29167

        change = panel.assess_change(built["change"]["id"], built["run"]["id"])

        # |2.0 - 2.5| / 2.5 = 0.2, |600 - 900| / 300 = 1.0 at the sub-score cap,
        # |30 - 60| / 60 = 0.5. 0.08 + 0.35 + 0.125 = 0.5550.
        subscores = expected_impact_subscores(built["target_rule_set"], built["proposed_rule_set"])
        assert float(subscores["cap"]) == 0.2
        assert float(subscores["tuning"]) == 1.0
        assert float(subscores["ascription"]) == 0.5
        assert change["state"] == "IMPACT_ASSESSED"
        assert change["impact_delta_pct"] == 0.5550
        assert change["impact_delta_pct"] == expected_impact_delta_pct(
            built["target_rule_set"], built["proposed_rule_set"]
        )
        assert change["impact_delta_pct"] >= TIER_MATERIAL_THRESHOLD
        assert change["impact_tier"] == "MATERIAL" == expected_impact_tier(0.5550)
        assert change["notification_lead_hours"] == LEAD_HOURS_MATERIAL == 720
        assert change["baseline_processing_run_id"] == built["run"]["id"]
        assert change["baseline_projected_average_audience"] == 29167
        assert change["revision_count"] == 0

        change = panel.notify_change(built["change"]["id"])

        assert change["state"] == "NOTIFIED"
        assert change["notified_client_count"] == 1
        assert change["acknowledged_client_count"] == 0
        assert _instant(change["notification_deadline_at"]) == _instant("2026-09-11T00:00:00Z")
        notifications = panel.notifications_of_change(built["change"]["id"])
        assert len(notifications) == 1
        assert notifications[0]["state"] == "SENT"
        assert notifications[0]["client_id"] == built["client"]["id"]
        assert notifications[0]["impact_tier"] == "MATERIAL"
        assert notifications[0]["disclosed_delta_pct"] == 0.5550

    def test_revision_returns_the_change_to_draft_and_cancels_the_sent_notification(
        self, panel: PanelHarness
    ):
        """The loop back to DRAFT clears the score, the deadline and both counters.

        PRD 3.9: "The change returns to `DRAFT` and `revision_count` rises by
        one; `impact_delta_pct`, `impact_tier`, `notification_lead_hours`,
        `notification_deadline_at`, `baseline_processing_run_id` and
        `baseline_projected_average_audience` are all cleared."

        Design: Difficulty/non_linear_state_machine/methodology_change_revision_cycle_returns_to_draft
        """
        built = _notified_change(panel)
        panel.assess_change(built["change"]["id"], built["run"]["id"])
        panel.notify_change(built["change"]["id"])

        validate_success(
            panel.client.request_methodology_change_revision(
                panel.director,
                built["change"]["id"],
                reason="The baseline run was the wrong window; re-score it.",
            ),
            200,
        )

        change = panel.read_change(built["change"]["id"])
        assert change["state"] == "DRAFT"
        assert change["revision_count"] == 1
        assert change["impact_tier"] is None
        assert change["notification_lead_hours"] is None
        assert change["notification_deadline_at"] is None
        assert change["baseline_processing_run_id"] is None
        assert change["baseline_projected_average_audience"] is None
        # The conditional cascade cancels the SENT row and rebuilds the counters
        # from what survives, so a cancelled notification counts toward neither.
        notifications = panel.notifications_of_change(built["change"]["id"])
        assert len(notifications) == 1
        assert notifications[0]["state"] == "CANCELLED"
        assert change["notified_client_count"] == 0
        assert change["acknowledged_client_count"] == 0

    def test_reassessment_after_a_revision_leaves_revision_count_at_one(
        self, panel: PanelHarness
    ):
        """A draft-assess-revise-assess round trip scores 0.5550 again and stops at 1.

        PRD 3.9: "It does **not** touch `revision_count`: that counter belongs
        exclusively to the revision operation, so a draft-assess-revise-assess
        round trip leaves `revision_count` at exactly 1."

        Design: Difficulty/non_linear_state_machine/methodology_change_revision_cycle_returns_to_draft
        """
        built = _notified_change(panel)
        panel.assess_change(built["change"]["id"], built["run"]["id"])
        panel.notify_change(built["change"]["id"])
        validate_success(
            panel.client.request_methodology_change_revision(
                panel.director,
                built["change"]["id"],
                reason="The baseline run was the wrong window; re-score it.",
            ),
            200,
        )

        change = panel.assess_change(built["change"]["id"], built["run"]["id"])

        assert change["state"] == "IMPACT_ASSESSED"
        assert change["impact_delta_pct"] == 0.5550
        assert change["impact_tier"] == "MATERIAL"
        assert change["notification_lead_hours"] == 720
        assert change["baseline_projected_average_audience"] == 29167
        assert change["revision_count"] == 1
        # The baseline the second analysis read is still terminal and untouched.
        assert panel.read_run(built["run"]["id"])["state"] == "PUBLISHED"
