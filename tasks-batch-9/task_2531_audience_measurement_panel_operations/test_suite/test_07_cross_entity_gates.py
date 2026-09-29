"""Cross-entity state dependencies: an operation refused by a sibling entity's state.

Each scenario here holds the acting entity perfectly ready and blocks it from a
neighbour it does not itself reference - a run blocked by its market's accreditation
outcome, a methodology change blocked by its own notification rows - and then lifts
only the neighbour's state so that the identical call succeeds.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.factories import cell_population
from test_helpers.fixtures import PanelHarness
from test_helpers.test_users import STATISTICIAN_PUBLISHER_USER_ID

RULE_SET_THRESHOLDS = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}

WINDOW_0810_START = "2026-08-10T00:00:00Z"
WINDOW_0810_END = "2026-08-11T00:00:00Z"


def _measurement_base(
    panel: PanelHarness,
    *,
    name: str,
    market_code: str,
    dma_rank: int,
    cell_specs,
    populations,
    rule_set_label: str = "RS-2026Q3",
    **rule_overrides,
):
    """A market, its cells, a PUBLISHED rule set and a PUBLISHED 2026Q3 vintage."""
    thresholds = dict(RULE_SET_THRESHOLDS)
    thresholds.update(rule_overrides)
    market = panel.create_market(
        name=name,
        market_code=market_code,
        dma_rank=dma_rank,
        incentive_budget_cents=1000000,
    )
    cells = [panel.create_quota_cell(market["id"], **spec) for spec in cell_specs]
    rule_set = panel.published_rule_set(label=rule_set_label, **thresholds)
    universe = panel.published_universe(
        market["id"],
        [cell["id"] for cell in cells],
        vintage_label="2026Q3",
        cell_populations=[
            cell_population(cell["id"], households, persons)
            for cell, (households, persons) in zip(cells, populations)
        ],
    )
    return {
        "market": market,
        "cells": cells,
        "rule_set": rule_set,
        "universe": universe,
    }


def _single_cell_weighted_run(panel: PanelHarness, *, name: str, market_code: str, dma_rank: int):
    """One market, one home, one 350-minute block and a run weighted FINAL."""
    base = _measurement_base(
        panel,
        name=name,
        market_code=market_code,
        dma_rank=dma_rank,
        cell_specs=[
            {
                "age_band": "P18_34",
                "income_band": "MID",
                "geo_zone": "URBAN",
                "target_households": 1,
                "base_incentive_cents": 2000,
            }
        ],
        populations=[(120000, 300000)],
    )
    built = panel.active_household(
        base["market"]["id"], base["cells"][0]["id"], persons_count=2
    )
    panel.set_clock("2026-08-11T00:00:00Z")
    panel.ingest_interval(
        built["tuner"]["id"],
        built["household"]["id"],
        "2026-08-10T18:00:00Z",
        "2026-08-10T23:50:00Z",
        350,
        station_code="WXYZ",
    )
    run = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=WINDOW_0810_START,
        window_end_iso=WINDOW_0810_END,
    )
    panel.edit_run(run["id"])
    run = panel.weight_run(run["id"], weight_variant="FINAL")
    # 120000 / 1 contributor, uncapped, times 350 / 1440 is 29166.67 -> 29167.
    assert run["state"] == "WEIGHTED"
    assert run["total_weight_mass"] == 120000.0000
    assert run["projected_average_audience"] == 29167
    assert run["limitation_disclosures"] == []
    base["built"] = built
    base["run"] = run
    return base


def _dma_515_denied_market(panel: PanelHarness):
    """DMA-515: a WEIGHTED run whose market has just been denied accreditation."""
    base = _single_cell_weighted_run(
        panel, name="Metro Omicron", market_code="DMA-515", dma_rank=15
    )
    audit = panel.open_audit(
        base["market"]["id"],
        base["rule_set"]["id"],
        auditor_note="Initial accreditation review of DMA-515",
    )
    finalized = panel.finalize_audit(
        audit["id"], outcome="DENIED", limitation_disclosures=["SMALL_CELL_SAMPLE"]
    )
    assert finalized["outcome"] == "DENIED"
    base["audit"] = audit
    return base


class TestRunPublishBlockedByDeniedMarketAccreditation:
    """A run cannot publish itself out of its market's accreditation verdict."""

    def test_a_denied_market_blocks_publication_of_a_ready_run(
        self, panel: PanelHarness
    ):
        """The run is WEIGHTED and unfrozen, yet publication is refused by the market.

        PRD 3.7: "The market's `publication_blocked` must be false, otherwise
        `ERR_PUBLICATION_BLOCKED`. A denied accreditation outcome bars publication
        regardless of the run's readiness."

        Design: Difficulty/cross_entity_state_dependency/run_publish_blocked_by_denied_market_accreditation
        """
        base = _dma_515_denied_market(panel)

        market = panel.read_market(base["market"]["id"])
        assert market["accreditation_status"] == "DENIED"
        assert market["publication_blocked"] is True
        assert market["open_audit_count"] == 0
        assert market["recruitment_posture"] == "CLOSED"
        assert market["limitation_disclosures"] == ["SMALL_CELL_SAMPLE"]

        response = panel.client.publish_processing_run(
            panel.publisher, base["run"]["id"]
        )
        validate_error(response, "ERR_PUBLICATION_BLOCKED")

        after = panel.read_run(base["run"]["id"])
        assert after["state"] == "WEIGHTED"
        assert after["published_by_user_id"] is None
        assert after["published_at"] is None

    def test_a_reopened_audit_reports_the_freeze_ahead_of_the_block(
        self, panel: PanelHarness
    ):
        """With both gates standing, check 1 is reported and check 3 is not reached.

        PRD 3.7: "The market's `recruitment_posture` must not be `FROZEN`, otherwise
        `ERR_MARKET_FROZEN`. An open accreditation audit stops publication."

        Design: Difficulty/cross_entity_state_dependency/run_publish_blocked_by_denied_market_accreditation
        """
        base = _dma_515_denied_market(panel)

        panel.open_audit(
            base["market"]["id"],
            base["rule_set"]["id"],
            auditor_note="Re-review after remediation",
        )
        reopened = panel.read_market(base["market"]["id"])
        assert reopened["open_audit_count"] == 1
        assert reopened["recruitment_posture"] == "FROZEN"
        assert reopened["publication_blocked"] is True

        response = panel.client.publish_processing_run(
            panel.publisher, base["run"]["id"]
        )
        validate_error(response, "ERR_MARKET_FROZEN")
        assert response.json()["data"]["error_id"] != "ERR_PUBLICATION_BLOCKED"
        assert panel.read_run(base["run"]["id"])["state"] == "WEIGHTED"

    def test_publication_succeeds_once_a_later_audit_accredits_the_market(
        self, panel: PanelHarness
    ):
        """Nothing about the run changes; the market's flag flips and the call is accepted.

        PRD 3.9: "`ACCREDITED` sets `publication_blocked` to false and leaves the
        market's `limitation_disclosures` exactly as it was."

        Design: Difficulty/cross_entity_state_dependency/run_publish_blocked_by_denied_market_accreditation
        """
        base = _dma_515_denied_market(panel)
        validate_error(
            panel.client.publish_processing_run(panel.publisher, base["run"]["id"]),
            "ERR_PUBLICATION_BLOCKED",
        )

        second = panel.open_audit(
            base["market"]["id"],
            base["rule_set"]["id"],
            auditor_note="Re-review after remediation",
        )
        panel.finalize_audit(
            second["id"], outcome="ACCREDITED", limitation_disclosures=[]
        )
        cleared = panel.read_market(base["market"]["id"])
        assert cleared["accreditation_status"] == "ACCREDITED"
        assert cleared["publication_blocked"] is False
        assert cleared["open_audit_count"] == 0
        assert cleared["recruitment_posture"] == "CLOSED"

        published = validate_success(
            panel.client.publish_processing_run(panel.publisher, base["run"]["id"]), 200
        )
        assert published["state"] == "PUBLISHED"
        assert published["published_by_user_id"] == STATISTICIAN_PUBLISHER_USER_ID

    def test_a_recorded_disclosure_survives_the_clean_audit_and_travels_with_the_run(
        self, panel: PanelHarness
    ):
        """The denied audit's caveat is still on the market and is copied onto the run.

        PRD 2.11: "those disclosures are permanent: a later clean `ACCREDITED` audit
        leaves the accumulated list exactly as it was, so a limitation once recorded
        is never erased."

        Design: Difficulty/cross_entity_state_dependency/run_publish_blocked_by_denied_market_accreditation
        """
        base = _dma_515_denied_market(panel)

        second = panel.open_audit(
            base["market"]["id"],
            base["rule_set"]["id"],
            auditor_note="Re-review after remediation",
        )
        panel.finalize_audit(
            second["id"], outcome="ACCREDITED", limitation_disclosures=[]
        )
        assert panel.read_market(base["market"]["id"])["limitation_disclosures"] == [
            "SMALL_CELL_SAMPLE"
        ]

        published = validate_success(
            panel.client.publish_processing_run(panel.publisher, base["run"]["id"]), 200
        )
        assert published["limitation_disclosures"] == ["SMALL_CELL_SAMPLE"]

    def test_the_runs_own_figures_never_move_across_the_gate(self, panel: PanelHarness):
        """29167 and 120000.0000 before the refusal, after it, and after publication.

        PRD 3.7: "`weight_variant`, `total_weight_mass`, `projected_average_audience`,
        `intab_snapshot_count` and `excluded_cell_count` are **overwritten rather than
        accumulated**".

        Design: Difficulty/cross_entity_state_dependency/run_publish_blocked_by_denied_market_accreditation
        """
        base = _dma_515_denied_market(panel)
        run_id = base["run"]["id"]

        validate_error(
            panel.client.publish_processing_run(panel.publisher, run_id),
            "ERR_PUBLICATION_BLOCKED",
        )
        refused = panel.read_run(run_id)
        assert refused["projected_average_audience"] == 29167
        assert refused["total_weight_mass"] == 120000.0000

        second = panel.open_audit(
            base["market"]["id"],
            base["rule_set"]["id"],
            auditor_note="Re-review after remediation",
        )
        panel.finalize_audit(
            second["id"], outcome="ACCREDITED", limitation_disclosures=[]
        )
        published = validate_success(
            panel.client.publish_processing_run(panel.publisher, run_id), 200
        )
        assert published["projected_average_audience"] == 29167
        assert published["total_weight_mass"] == 120000.0000
        assert published["weight_variant"] == "FINAL"


def _notification_of(panel: PanelHarness, change_id: str, client_id: str):
    """The single notification row a change created for one client."""
    rows, meta = validate_paginated(
        panel.client.list_client_notifications(
            panel.director, methodology_change_id=change_id, client_id=client_id
        )
    )
    assert meta["total_count"] == 1
    return rows[0]


def _read_notification(panel: PanelHarness, client_notification_id: str):
    """Re-read one notification row to inspect its state and stamp."""
    return validate_success(
        panel.client.get_client_notification(panel.director, client_notification_id), 200
    )


def _dma_516_notified_change(
    panel: PanelHarness, *, acknowledge_second: bool = False, at_deadline: bool = True
):
    """DMA-516: a NOTIFIED change with two SENT notifications, the first acknowledged."""
    base = _single_cell_weighted_run(
        panel, name="Metro Pi", market_code="DMA-516", dma_rank=16
    )
    run = panel.publish_run(base["run"]["id"])
    assert run["state"] == "PUBLISHED"
    proposed = panel.draft_rule_set(
        label="RS-2026Q4",
        missing_interval_ascription_minutes=60,
        invalid_tuning_max_minutes=840,
        outlier_household_minutes_cap=1200,
        outlier_weight_ratio_cap=2.5,
        fault_missing_minutes_threshold=1440,
    )
    assert proposed["status"] == "DRAFT"

    client_a = panel.create_client(
        [base["market"]["id"]], name="Pi National Buying", tier="STANDARD"
    )
    client_b = panel.create_client(
        [base["market"]["id"]], name="Pi Broadcast Group", tier="PREMIUM"
    )
    change = panel.draft_change(
        base["rule_set"]["id"],
        proposed["id"],
        [base["market"]["id"]],
        title="Tighten the invalid-tuning ceiling to 840 minutes",
    )

    panel.set_clock("2026-08-12T00:00:00Z")
    assessed = panel.assess_change(change["id"], run["id"])
    notified = panel.notify_change(change["id"])

    note_a = _notification_of(panel, change["id"], client_a["id"])
    note_b = _notification_of(panel, change["id"], client_b["id"])
    validate_success(
        panel.client.acknowledge_notification(
            panel.client_headers(client_a["id"]), note_a["id"]
        ),
        200,
    )
    if acknowledge_second:
        validate_success(
            panel.client.acknowledge_notification(
                panel.client_headers(client_b["id"]), note_b["id"]
            ),
            200,
        )
    if at_deadline:
        panel.set_clock("2026-08-26T00:00:00.000Z")

    base["run"] = run
    base["proposed"] = proposed
    base["client_a"] = client_a
    base["client_b"] = client_b
    base["change"] = change
    base["assessed"] = assessed
    base["notified"] = notified
    base["note_a"] = note_a
    base["note_b"] = note_b
    return base


class TestActivationBlockedUntilEveryNotificationAcknowledged:
    """A methodology change is held hostage by its own ClientNotification rows."""

    def test_one_unacknowledged_notification_blocks_activation(
        self, panel: PanelHarness
    ):
        """Both clients were notified, one answered, and the change cannot go effective.

        PRD 3.9: "`acknowledged_client_count` must equal `notified_client_count`,
        otherwise `ERR_ACKNOWLEDGEMENTS_MISSING`. Every notified client must have
        acknowledged."

        Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_notification_acknowledged
        """
        base = _dma_516_notified_change(panel)

        before = panel.read_change(base["change"]["id"])
        assert before["state"] == "NOTIFIED"
        assert before["notified_client_count"] == 2
        assert before["acknowledged_client_count"] == 1
        assert _read_notification(panel, base["note_a"]["id"])["state"] == "ACKNOWLEDGED"
        assert _read_notification(panel, base["note_b"]["id"])["state"] == "SENT"
        # PRD 2.3 orders the collection by `created_at` ascending, and the fan-out
        # walked the clients in that same order, so the STANDARD row comes first.
        rows, meta = validate_paginated(
            panel.client.list_client_notifications(
                panel.director, methodology_change_id=base["change"]["id"]
            )
        )
        assert meta["total_count"] == 2
        assert [row["client_id"] for row in rows] == [
            base["client_a"]["id"],
            base["client_b"]["id"],
        ]

        response = panel.client.activate_methodology_change(
            panel.activator, base["change"]["id"]
        )
        validate_error(response, "ERR_ACKNOWLEDGEMENTS_MISSING")
        # The clock sits exactly on the deadline, so check 4 would have passed.
        assert response.json()["data"]["error_id"] != "ERR_NOTIFICATION_PERIOD_OPEN"

        after = panel.read_change(base["change"]["id"])
        assert after["state"] == "NOTIFIED"
        assert after["activated_at"] is None
        assert panel.read_rule_set(base["proposed"]["id"])["status"] == "DRAFT"
        assert panel.read_rule_set(base["rule_set"]["id"])["status"] == "PUBLISHED"

    def test_the_impact_score_the_notifications_were_frozen_from(
        self, panel: PanelHarness
    ):
        """Only the tuning dimension moved: 0.35 times 0.2 is 0.0700, MODERATE, 336 hours.

        PRD 3.9: "`impact_delta_pct` is 0.40 times the cap sub-score plus 0.35 times
        the tuning sub-score plus 0.25 times the ascription sub-score, rounded half up
        to 4 decimal places."

        Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_notification_acknowledged
        """
        base = _dma_516_notified_change(panel, at_deadline=False)

        # |900 - 840| / 300 is 0.2; the cap and ascription bounds are identical.
        assert base["assessed"]["impact_delta_pct"] == 0.0700
        assert base["assessed"]["impact_tier"] == "MODERATE"
        assert base["assessed"]["notification_lead_hours"] == 336
        assert base["assessed"]["baseline_projected_average_audience"] == 29167
        assert base["notified"]["notified_client_count"] == 2
        # 2026-08-12T00:00:00Z plus 336 hours is exactly 2026-08-26T00:00:00Z.
        assert base["notified"]["notification_deadline_at"] == "2026-08-26T00:00:00.000Z"
        assert base["note_a"]["impact_tier"] == "MODERATE"
        assert base["note_a"]["disclosed_delta_pct"] == 0.0700
        assert base["note_b"]["impact_tier"] == "MODERATE"
        assert base["note_b"]["disclosed_delta_pct"] == 0.0700

    def test_the_second_acknowledgement_completes_the_set(self, panel: PanelHarness):
        """The last SENT row moves to ACKNOWLEDGED and lifts the counter to 2.

        PRD 3.9: "The notification moves to `ACKNOWLEDGED` with `acknowledged_at`
        stamped, and the change's `acknowledged_client_count` rises by one."

        Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_notification_acknowledged
        """
        base = _dma_516_notified_change(panel)

        acknowledged = validate_success(
            panel.client.acknowledge_notification(
                panel.client_headers(base["client_b"]["id"]), base["note_b"]["id"]
            ),
            200,
        )
        assert acknowledged["state"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_at"] == "2026-08-26T00:00:00.000Z"

        change = panel.read_change(base["change"]["id"])
        assert change["acknowledged_client_count"] == 2
        assert change["notified_client_count"] == 2
        assert change["state"] == "NOTIFIED"

    def test_the_identical_activate_call_succeeds_once_the_set_is_complete(
        self, panel: PanelHarness
    ):
        """Nothing about the change moved in between; only its notification rows did.

        PRD 3.9: "the change's `state` becomes `EFFECTIVE` - terminal - with
        `activated_at` stamped; the proposed rule set's `status` becomes `PUBLISHED`
        with `published_at` stamped; and the target rule set's `status` becomes
        `SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_notification_acknowledged
        """
        base = _dma_516_notified_change(panel)
        validate_error(
            panel.client.activate_methodology_change(
                panel.activator, base["change"]["id"]
            ),
            "ERR_ACKNOWLEDGEMENTS_MISSING",
        )

        validate_success(
            panel.client.acknowledge_notification(
                panel.client_headers(base["client_b"]["id"]), base["note_b"]["id"]
            ),
            200,
        )
        activated = validate_success(
            panel.client.activate_methodology_change(
                panel.activator, base["change"]["id"]
            ),
            200,
        )
        assert activated["state"] == "EFFECTIVE"
        assert activated["activated_at"] == "2026-08-26T00:00:00.000Z"
        assert activated["notified_client_count"] == 2
        assert activated["acknowledged_client_count"] == 2
        assert activated["revision_count"] == 0
        assert panel.read_rule_set(base["proposed"]["id"])["status"] == "PUBLISHED"
        assert panel.read_rule_set(base["rule_set"]["id"])["status"] == "SUPERSEDED"

    def test_a_published_run_pinned_to_the_superseded_target_is_left_alone(
        self, panel: PanelHarness
    ):
        """Link 2 only drags OPEN and EDITED runs into PENDING_REPIN.

        PRD 3.9: "every processing run whose `edit_rule_set_id` is the superseded
        target and whose `state` is `OPEN` or `EDITED` moves to `PENDING_REPIN` with
        `repin_required_reason` `RULE_SET_SUPERSEDED`".

        Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_notification_acknowledged
        """
        base = _dma_516_notified_change(panel, acknowledge_second=True)

        activated = validate_success(
            panel.client.activate_methodology_change(
                panel.activator, base["change"]["id"]
            ),
            200,
        )
        assert activated["state"] == "EFFECTIVE"

        run = panel.read_run(base["run"]["id"])
        assert run["state"] == "PUBLISHED"
        assert run["repin_required_reason"] is None
        assert run["projected_average_audience"] == 29167

    def test_the_notification_period_gate_fires_alone_before_the_deadline(
        self, panel: PanelHarness
    ):
        """Control: with both clients acknowledged early, check 3 passes and check 4 fires.

        PRD 3.9: "The current logical clock must have reached
        `notification_deadline_at`, otherwise `ERR_NOTIFICATION_PERIOD_OPEN`. The
        tier's lead time must have fully elapsed even when every client acknowledged
        early".

        Design: Difficulty/cross_entity_state_dependency/activation_blocked_until_every_notification_acknowledged
        """
        base = _dma_516_notified_change(
            panel, acknowledge_second=True, at_deadline=False
        )

        early = panel.read_change(base["change"]["id"])
        assert early["acknowledged_client_count"] == early["notified_client_count"] == 2
        assert early["notification_deadline_at"] == "2026-08-26T00:00:00.000Z"

        response = panel.client.activate_methodology_change(
            panel.activator, base["change"]["id"]
        )
        validate_error(response, "ERR_NOTIFICATION_PERIOD_OPEN")
        assert panel.read_change(base["change"]["id"])["state"] == "NOTIFIED"
        assert panel.read_rule_set(base["proposed"]["id"])["status"] == "DRAFT"
