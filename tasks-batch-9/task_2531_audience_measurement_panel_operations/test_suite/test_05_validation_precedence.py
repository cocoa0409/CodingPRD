"""Validation precedence: which of two simultaneously violated gates is reported.

Every scenario in this file arranges a request that breaks two ordered checks at
once and pins the error the PRD's stated check order demands, together with a
control that shows the lower-priority rule firing on its own once the
higher-priority condition is lifted.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.factories import cell_population
from test_helpers.fixtures import PanelHarness

RULE_SET_THRESHOLDS = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}


def _error_id(response) -> str:
    """The `error_id` carried by a 4xx envelope."""
    return response.json()["data"]["error_id"]


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


def _dma_509_filled_market(panel: PanelHarness):
    """DMA-509: one cell of target 1 filled by one ACTIVE home, so intake is CLOSED."""
    market = panel.create_market(
        name="Metro Iota",
        market_code="DMA-509",
        dma_rank=9,
        incentive_budget_cents=1000000,
    )
    cell = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=1,
        base_incentive_cents=2000,
    )
    built = panel.active_household(market["id"], cell["id"], persons_count=2)
    return market, cell, built


class TestRecruitmentClosedOutranksQuotaCellFilled:
    """PRD 3.2 check 1 (posture) is evaluated before check 3 (cell fill)."""

    def test_closed_market_reports_recruitment_closed_not_quota_cell_filled(
        self, panel: PanelHarness
    ):
        """A CLOSED market pointing at a FILLED cell reports the posture gate.

        PRD 3.2: "The market's `recruitment_posture` must be neither `CLOSED` nor
        `FROZEN`; otherwise intake stops with `ERR_RECRUITMENT_CLOSED`. A fully
        filled market and a market under accreditation audit are both closed to
        intake, and this gate fires before any cell-level consideration."

        Design: Difficulty/priority_pair_validation_conflict/recruitment_closed_outranks_quota_cell_filled
        """
        market, cell, _built = _dma_509_filled_market(panel)

        assert panel.read_market(market["id"])["recruitment_posture"] == "CLOSED"
        assert panel.read_quota_cell(cell["id"])["quota_status"] == "FILLED"

        response = panel.client.create_household(
            panel.ops,
            market_id=market["id"],
            quota_cell_id=cell["id"],
            recruitment_source="RDD_PHONE",
            persons_count=1,
        )
        validate_error(response, "ERR_RECRUITMENT_CLOSED")
        assert _error_id(response) != "ERR_QUOTA_CELL_FILLED"

    def test_rejected_recruitment_into_a_closed_market_leaves_no_trace(
        self, panel: PanelHarness
    ):
        """The refused intake writes nothing: the cell and the collection are untouched.

        PRD 3.2: "The market's `recruitment_posture` must be neither `CLOSED` nor
        `FROZEN`; otherwise intake stops with `ERR_RECRUITMENT_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/recruitment_closed_outranks_quota_cell_filled
        """
        market, cell, _built = _dma_509_filled_market(panel)

        response = panel.client.create_household(
            panel.ops,
            market_id=market["id"],
            quota_cell_id=cell["id"],
            recruitment_source="RDD_PHONE",
            persons_count=1,
        )
        validate_error(response, "ERR_RECRUITMENT_CLOSED")

        after = panel.read_quota_cell(cell["id"])
        assert after["intab_count"] == 1
        assert after["quota_status"] == "FILLED"
        _rows, meta = validate_paginated(
            panel.client.list_households(panel.ops, market_id=market["id"])
        )
        assert meta["total_count"] == 1

    def test_quota_cell_filled_fires_alone_while_the_market_is_still_open(
        self, panel: PanelHarness
    ):
        """Control: with a second empty cell the posture gate passes and check 3 fires.

        PRD 3.2: "The referenced cell's `quota_status` must not be `FILLED`,
        otherwise `ERR_QUOTA_CELL_FILLED`. A cell at `ON_TARGET` still has room; a
        cell at `FILLED` does not."

        Design: Difficulty/priority_pair_validation_conflict/recruitment_closed_outranks_quota_cell_filled
        """
        market = panel.create_market(
            name="Metro Iota",
            market_code="DMA-509",
            dma_rank=9,
            incentive_budget_cents=1000000,
        )
        filled = panel.create_quota_cell(
            market["id"],
            age_band="P18_34",
            income_band="MID",
            geo_zone="URBAN",
            target_households=1,
            base_incentive_cents=2000,
        )
        spare = panel.create_quota_cell(
            market["id"],
            age_band="P35_54",
            income_band="MID",
            geo_zone="SUBURBAN",
            target_households=1,
            base_incentive_cents=2000,
        )
        panel.active_household(market["id"], filled["id"], persons_count=2)

        assert panel.read_quota_cell(filled["id"])["quota_status"] == "FILLED"
        assert panel.read_quota_cell(spare["id"])["quota_status"] == "UNDER_TARGET"
        assert panel.read_market(market["id"])["recruitment_posture"] == "OPEN"

        response = panel.client.create_household(
            panel.ops,
            market_id=market["id"],
            quota_cell_id=filled["id"],
            recruitment_source="RDD_PHONE",
            persons_count=1,
        )
        validate_error(response, "ERR_QUOTA_CELL_FILLED")
        assert _error_id(response) != "ERR_RECRUITMENT_CLOSED"


def _dma_510_frozen_market_with_hold(panel: PanelHarness, *, fault_the_tuner: bool):
    """DMA-510: a NONCOMPLIANT_HOLD home in a market frozen by an open audit."""
    base = _measurement_base(
        panel,
        name="Metro Kappa",
        market_code="DMA-510",
        dma_rank=10,
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
    market = base["market"]
    cell = base["cells"][0]

    household = panel.recruit_household(
        market["id"],
        cell["id"],
        recruitment_source="ADDRESS_SAMPLE",
        persons_count=2,
    )
    tuner = panel.installed_meter(household["id"], meter_type="TV_TUNER")
    # Roster 3 against persons_count 2 fails the roster test: NONCOMPLIANT.
    household = panel.enumerate_household(
        household["id"], roster_persons_count=3, tv_sets_count=1
    )
    assert household["status"] == "NONCOMPLIANT_HOLD"
    assert household["enumeration_verdict"] == "NONCOMPLIANT"

    if fault_the_tuner:
        faulted = validate_success(
            panel.client.report_meter_fault(panel.tech, tuner["id"], fault_code="NO_SIGNAL"),
            200,
        )
        assert faulted["health_status"] == "FAULTED"

    audit = panel.open_audit(
        market["id"],
        base["rule_set"]["id"],
        auditor_note="Annual methodology review of DMA-510",
    )
    frozen = panel.read_market(market["id"])
    assert frozen["open_audit_count"] == 1
    assert frozen["recruitment_posture"] == "FROZEN"
    base["household"] = household
    base["tuner"] = tuner
    base["audit"] = audit
    return base


class TestMeterFaultedOutranksMarketFrozen:
    """PRD 3.2 enumeration check 3 (tuner health) precedes check 4 (market freeze)."""

    def test_faulted_tuner_in_a_frozen_market_reports_meter_faulted(
        self, panel: PanelHarness
    ):
        """Both the health gate and the freeze gate hold; the health gate is reported.

        PRD 3.2: "At least one of those installed tuners must have `health_status`
        `HEALTHY`, otherwise `ERR_METER_FAULTED`. A home whose only tuner is
        `FAULTED` or `SUSPECT` must be repaired first, because a compliant verdict
        would otherwise place a blind household in tab."

        Design: Difficulty/priority_pair_validation_conflict/meter_faulted_outranks_market_frozen_on_enumeration
        """
        base = _dma_510_frozen_market_with_hold(panel, fault_the_tuner=True)

        response = panel.client.create_enumeration(
            panel.tech,
            base["household"]["id"],
            roster_persons_count=2,
            tv_sets_count=1,
        )
        validate_error(response, "ERR_METER_FAULTED")
        assert _error_id(response) != "ERR_MARKET_FROZEN"
        assert panel.read_market(base["market"]["id"])["recruitment_posture"] == "FROZEN"

    def test_refused_enumeration_visit_is_not_recorded(self, panel: PanelHarness):
        """The rejected visit leaves `enumeration_count`, status and in-tab count alone.

        PRD 3.2: "Whatever the verdict, `enumeration_count` rises by one and
        `roster_persons_count`, `tv_sets_count`, `enumeration_verdict` and
        `last_enumeration_at` are refreshed from the submission and the clock."

        Design: Difficulty/priority_pair_validation_conflict/meter_faulted_outranks_market_frozen_on_enumeration
        """
        base = _dma_510_frozen_market_with_hold(panel, fault_the_tuner=True)

        response = panel.client.create_enumeration(
            panel.tech,
            base["household"]["id"],
            roster_persons_count=2,
            tv_sets_count=1,
        )
        validate_error(response, "ERR_METER_FAULTED")

        after = panel.read_household(base["household"]["id"])
        assert after["status"] == "NONCOMPLIANT_HOLD"
        assert after["enumeration_count"] == 1
        assert panel.read_quota_cell(base["cells"][0]["id"])["intab_count"] == 0

    def test_market_frozen_fires_alone_when_the_tuner_is_healthy(
        self, panel: PanelHarness
    ):
        """Control: with a HEALTHY tuner check 3 passes and the freeze gate fires.

        PRD 3.2: "The market's `recruitment_posture` must not be `FROZEN`, otherwise
        `ERR_MARKET_FROZEN`. An open accreditation audit stops movement in *both*
        directions: while the market is frozen no household may be enumerated into
        tab and none may be enumerated out of it."

        Design: Difficulty/priority_pair_validation_conflict/meter_faulted_outranks_market_frozen_on_enumeration
        """
        base = _dma_510_frozen_market_with_hold(panel, fault_the_tuner=False)
        assert panel.read_meter(base["tuner"]["id"])["health_status"] == "HEALTHY"

        response = panel.client.create_enumeration(
            panel.tech,
            base["household"]["id"],
            roster_persons_count=2,
            tv_sets_count=1,
        )
        validate_error(response, "ERR_MARKET_FROZEN")
        assert _error_id(response) != "ERR_METER_FAULTED"
        assert panel.read_household(base["household"]["id"])["enumeration_count"] == 1


def _dma_511_open_run_and_basic_client(panel: PanelHarness):
    """DMA-511: a run left in OPEN plus a BASIC subscriber whose quota is 0."""
    base = _measurement_base(
        panel,
        name="Metro Lambda",
        market_code="DMA-511",
        dma_rank=11,
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
    # A run may not process a window that has not finished, so the clock moves first.
    panel.set_clock("2026-08-11T00:00:00Z")
    run = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso="2026-08-10T00:00:00Z",
        window_end_iso="2026-08-11T00:00:00Z",
    )
    assert run["state"] == "OPEN"
    subscriber = panel.create_client(
        [base["market"]["id"]], name="Lambda Local Sales", tier="BASIC"
    )
    base["run"] = run
    base["subscriber"] = subscriber
    return base


class TestRunNotPublishedOutranksCustomAnalysisQuota:
    """PRD 3.8 custom-analysis check 3 (run state) precedes check 4 (quota)."""

    def test_open_run_reports_run_not_published_not_the_quota_error(
        self, panel: PanelHarness
    ):
        """A BASIC client filing against an OPEN run gets the state error, not the fiscal one.

        PRD 3.8: "the run's `state` must be `PUBLISHED`, otherwise
        `ERR_RUN_NOT_PUBLISHED`; and the client's `custom_analysis_used` must be
        strictly below its `custom_analysis_quota`, otherwise
        `ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED`. A `BASIC` client has a quota of 0 and
        can therefore never file one."

        Design: Difficulty/priority_pair_validation_conflict/run_not_published_outranks_custom_analysis_quota
        """
        base = _dma_511_open_run_and_basic_client(panel)

        subscriber = panel.read_client(base["subscriber"]["id"])
        assert subscriber["tier_base_fee_cents"] == 25000
        assert subscriber["delivery_sla_hours"] == 168
        assert subscriber["custom_analysis_quota"] == 0

        response = panel.client.create_custom_analysis(
            panel.rep,
            client_id=base["subscriber"]["id"],
            processing_run_id=base["run"]["id"],
            question="Average audience for the 2026-08-10 window by cell",
            requested_cell_count=3,
        )
        validate_error(response, "ERR_RUN_NOT_PUBLISHED")
        assert _error_id(response) != "ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED"

    def test_refused_custom_analysis_consumes_nothing(self, panel: PanelHarness):
        """No row is created and `custom_analysis_used` is not raised by a refusal.

        PRD 3.8: "The row is created with `kind` `CUSTOM_ANALYSIS` and `state`
        `REQUESTED` — not the machine's declared initial state — its `due_at` set to
        the logical clock plus the client's `delivery_sla_hours`, and the client's
        `custom_analysis_used` raised by one."

        Design: Difficulty/priority_pair_validation_conflict/run_not_published_outranks_custom_analysis_quota
        """
        base = _dma_511_open_run_and_basic_client(panel)

        response = panel.client.create_custom_analysis(
            panel.rep,
            client_id=base["subscriber"]["id"],
            processing_run_id=base["run"]["id"],
            question="Average audience for the 2026-08-10 window by cell",
            requested_cell_count=3,
        )
        validate_error(response, "ERR_RUN_NOT_PUBLISHED")

        assert panel.read_client(base["subscriber"]["id"])["custom_analysis_used"] == 0
        _rows, meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, client_id=base["subscriber"]["id"]
            )
        )
        assert meta["total_count"] == 0
        assert panel.read_run(base["run"]["id"])["state"] == "OPEN"

    def test_quota_exceeded_fires_alone_against_a_published_run(
        self, panel: PanelHarness
    ):
        """Control: once the run is PUBLISHED check 3 passes and the quota gate fires.

        PRD 3.8: "the client's `custom_analysis_used` must be strictly below its
        `custom_analysis_quota`, otherwise `ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/run_not_published_outranks_custom_analysis_quota
        """
        base = panel.subscribed_published_run(tier="BASIC")
        assert base["run"]["state"] == "PUBLISHED"
        assert panel.read_client(base["client"]["id"])["custom_analysis_quota"] == 0

        response = panel.client.create_custom_analysis(
            panel.rep,
            client_id=base["client"]["id"],
            processing_run_id=base["run"]["id"],
            question="Average audience for the published window by cell",
            requested_cell_count=3,
        )
        validate_error(response, "ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED")
        assert _error_id(response) != "ERR_RUN_NOT_PUBLISHED"
        assert panel.read_client(base["client"]["id"])["custom_analysis_used"] == 0
