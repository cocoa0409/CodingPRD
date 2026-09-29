"""Compensating invariants: quantities a forward action and its undo must conserve.

Three separate conserved quantities are exercised here — committed incentive
money, the in-tab head-count together with the armed boost reserve, and
statistical weight mass. In each case the test drives the forward operation, then
its compensating counterpart, and pins the exact figure the PRD's own arithmetic
says both sides must land on, with a companion test showing the audit trail that
the compensation deliberately does *not* erase.
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


def _measurement_base(
    panel: PanelHarness,
    *,
    name: str,
    market_code: str,
    dma_rank: int,
    cell_specs,
    populations,
    **rule_overrides,
):
    """A market, its cells in creation order, a PUBLISHED rule set and vintage."""
    thresholds = dict(RULE_SET_THRESHOLDS)
    thresholds.update(rule_overrides)
    market = panel.create_market(
        name=name,
        market_code=market_code,
        dma_rank=dma_rank,
        incentive_budget_cents=1000000,
    )
    cells = [panel.create_quota_cell(market["id"], **spec) for spec in cell_specs]
    rule_set = panel.published_rule_set(label="RS-2026Q3", **thresholds)
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


# ----------------------------------------------------------------------
# DMA-519: the incentive ledger
# ----------------------------------------------------------------------

def _dma_519_active_home(panel: PanelHarness):
    """DMA-519: one ACTIVE home with a tuner and an out-of-home meter, 6 months in.

    Both devices are shipped before either is confirmed: PRD 3.3 shipping check 1
    admits only a `RECRUITED` or `INSTALL_SCHEDULED` household, and confirming the
    `TV_TUNER` moves the home straight to `ENUM_PENDING`.
    """
    market = panel.create_market(
        name="Metro Tau",
        market_code="DMA-519",
        dma_rank=19,
        incentive_budget_cents=1000000,
    )
    cell = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=1,
        base_incentive_cents=3000,
    )
    built = panel.active_household(
        market["id"],
        cell["id"],
        persons_count=2,
        recruitment_source="ADDRESS_SAMPLE",
        extra_meter_types=("PORTABLE_OOH",),
    )
    household = built["household"]
    assert household["status"] == "ACTIVE"
    assert household["recruited_at"] == "2026-08-01T00:00:00.000Z"

    cell_after = panel.read_quota_cell(cell["id"])
    assert cell_after["quota_status"] == "FILLED"
    assert cell_after["effective_incentive_multiplier"] == 1.00
    assert panel.read_market(market["id"])["incentive_budget_reserved_cents"] == 0

    # The rolling rate is a stored snapshot refreshed on ingest, so it is taken
    # while the clock still sits inside the reported day's 30-day window.
    panel.set_clock("2027-02-14T00:00:00Z")
    panel.ingest_interval(
        built["tuner"]["id"],
        household["id"],
        "2027-02-13T18:00:00Z",
        "2027-02-13T23:50:00Z",
        350,
        source_methodology="INHOME_TUNER",
        station_code="WXYZ",
    )
    panel.set_clock("2027-02-15T00:00:00Z")
    return {
        "market": market,
        "cell": cell,
        "household": household,
        "tuner": built["tuner"],
        "meters": built["meters"],
    }


class TestAccrualReversalConservesIncentiveLedger:
    """PRD 3.4: a reversal returns both balances to their exact pre-accrual value."""

    def test_ledger_is_empty_and_the_rolling_rate_is_snapshotted_before_the_accrual(
        self, panel: PanelHarness
    ):
        """Control: the pre-accrual state both balances must be restored to.

        PRD 3.2: "`incentive_accrued_cents` at 0 with an empty `accrual_periods`
        array". PRD 3.6: "The figure is stored, not derived at read time: it is
        recomputed on interval ingest and on a fault-detection scan, so a stored
        value is a snapshot as of the clock at the last ingest or scan and does not
        silently age."

        Design: Difficulty/compensating_invariant/accrual_reversal_conserves_incentive_ledger
        """
        base = _dma_519_active_home(panel)

        household = panel.read_household(base["household"]["id"])
        assert household["recruited_at"] == "2026-08-01T00:00:00.000Z"
        assert household["compliance_rate_rolling_30"] == 1.0000
        assert household["incentive_accrued_cents"] == 0
        assert household["accrual_periods"] == []

        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_committed_cents"] == 0
        assert market["incentive_budget_reserved_cents"] == 0

    def test_accrual_commits_3632_cents_on_both_sides_of_the_ledger(
        self, panel: PanelHarness
    ):
        """198 days of tenure, a full rolling rate and an out-of-home meter make 3632.

        PRD 3.4: "The amount is computed in nine numbered steps, and **each step
        rounds to whole cents before the next step reads its result**." Cell base
        3000 x 1.00 = 3000; tenure floor(198 days / 30 days) = 6 months so the
        multiplier is 1.075 and the tenure amount is 3225; the compliance bonus is
        8.55 percent of 3225 = 276; the out-of-home supplement is 4.05 percent of
        3225 = 131; the gross 3632 carries no fault penalty and sits under the
        5000-cent per-period cap.

        Design: Difficulty/compensating_invariant/accrual_reversal_conserves_incentive_ledger
        """
        base = _dma_519_active_home(panel)

        accrued = validate_success(
            panel.client.accrue_incentive(
                panel.ops, base["household"]["id"], period_label="2027-02"
            ),
            200,
        )
        assert accrued["incentive_accrued_cents"] == 3632
        assert accrued["accrual_periods"] == [
            {"period_label": "2027-02", "accrued_cents": 3632, "reversed": False}
        ]
        assert (
            panel.read_market(base["market"]["id"])["incentive_budget_committed_cents"]
            == 3632
        )

    def test_reversal_returns_both_balances_to_zero_and_keeps_the_entry(
        self, panel: PanelHarness
    ):
        """The compensation is exact on both sides and erases nothing.

        PRD 3.4: "The matching entry's `reversed` flag becomes true and it keeps its
        `accrued_cents` for the audit trail — nothing is ever deleted from the
        ledger. The household's `incentive_accrued_cents` falls by exactly that
        entry's amount and the market's `incentive_budget_committed_cents` falls by
        the same, so both figures return to their pre-accrual values with no drift."

        Design: Difficulty/compensating_invariant/accrual_reversal_conserves_incentive_ledger
        """
        base = _dma_519_active_home(panel)
        panel.accrue(base["household"]["id"], period_label="2027-02")

        reversed_row = validate_success(
            panel.client.reverse_accrual(
                panel.ops,
                base["household"]["id"],
                period_label="2027-02",
                memo="Compliance figure restated by audit",
            ),
            200,
        )
        assert reversed_row["incentive_accrued_cents"] == 0
        assert reversed_row["accrual_periods"] == [
            {"period_label": "2027-02", "accrued_cents": 3632, "reversed": True}
        ]
        assert (
            panel.read_market(base["market"]["id"])["incentive_budget_committed_cents"]
            == 0
        )

    def test_reversed_period_label_becomes_accruable_again_for_the_same_cent(
        self, panel: PanelHarness
    ):
        """The freed label is re-accruable and a fresh computation reproduces 3632.

        PRD 3.4: "A period that was accrued and then reversed becomes accruable
        again." And: "a re-accrual is computed fresh from the household's current
        tenure, compliance and equipment — it is not a replay of the reversed
        figure."

        Design: Difficulty/compensating_invariant/accrual_reversal_conserves_incentive_ledger
        """
        base = _dma_519_active_home(panel)
        first = panel.accrue(base["household"]["id"], period_label="2027-02")
        panel.reverse(
            base["household"]["id"],
            period_label="2027-02",
            memo="Compliance figure restated by audit",
        )

        again = validate_success(
            panel.client.accrue_incentive(
                panel.ops, base["household"]["id"], period_label="2027-02"
            ),
            200,
        )
        assert again["incentive_accrued_cents"] == 3632
        assert again["incentive_accrued_cents"] == first["incentive_accrued_cents"]
        assert (
            panel.read_market(base["market"]["id"])["incentive_budget_committed_cents"]
            == 3632
        )

    def test_balance_counts_only_the_unreversed_entry_of_the_two_on_file(
        self, panel: PanelHarness
    ):
        """Two ledger entries, one balance: 3632 and never the 7264 of both.

        PRD 3.4: "nothing is ever deleted from the ledger." PRD 3.2: "unreversed
        entries in `accrual_periods` stay on the ledger".

        Design: Difficulty/compensating_invariant/accrual_reversal_conserves_incentive_ledger
        """
        base = _dma_519_active_home(panel)
        panel.accrue(base["household"]["id"], period_label="2027-02")
        panel.reverse(
            base["household"]["id"],
            period_label="2027-02",
            memo="Compliance figure restated by audit",
        )
        panel.accrue(base["household"]["id"], period_label="2027-02")

        household = panel.read_household(base["household"]["id"])
        entries = household["accrual_periods"]
        assert len(entries) == 2
        assert [entry["reversed"] for entry in entries] == [True, False]
        assert [entry["accrued_cents"] for entry in entries] == [3632, 3632]
        unreversed = sum(
            entry["accrued_cents"] for entry in entries if not entry["reversed"]
        )
        assert household["incentive_accrued_cents"] == unreversed == 3632
        assert household["incentive_accrued_cents"] != 7264

    def test_a_second_unreversed_accrual_of_the_same_label_is_refused(
        self, panel: PanelHarness
    ):
        """Control: without an intervening reversal the label is closed.

        PRD 3.4: "The household must hold no existing `accrual_periods` entry with
        the supplied `period_label` whose `reversed` flag is false, otherwise
        `ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED`."

        Design: Difficulty/compensating_invariant/accrual_reversal_conserves_incentive_ledger
        """
        base = _dma_519_active_home(panel)
        panel.accrue(base["household"]["id"], period_label="2027-02")

        response = panel.client.accrue_incentive(
            panel.ops, base["household"]["id"], period_label="2027-02"
        )
        validate_error(response, "ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED")

        household = panel.read_household(base["household"]["id"])
        assert household["incentive_accrued_cents"] == 3632
        assert len(household["accrual_periods"]) == 1
        assert (
            panel.read_market(base["market"]["id"])["incentive_budget_committed_cents"]
            == 3632
        )


# ----------------------------------------------------------------------
# DMA-520: the in-tab head-count and the armed boost reserve
# ----------------------------------------------------------------------

def _active_home(
    panel: PanelHarness,
    market_id: str,
    quota_cell_id: str,
    *,
    recruitment_source: str,
    persons_count: int,
    tv_sets_count: int,
    serial_no: str,
):
    """Recruit, meter, install and enumerate one home with an explicit set count.

    `PanelHarness.active_household` always submits one television set, and these
    recipes submit two and three, so the enumeration payload is spelled out here.
    """
    household = panel.recruit_household(
        market_id,
        quota_cell_id,
        recruitment_source=recruitment_source,
        persons_count=persons_count,
    )
    tuner = panel.installed_meter(
        household["id"], meter_type="TV_TUNER", serial_no=serial_no
    )
    household = panel.enumerate_household(
        household["id"],
        roster_persons_count=persons_count,
        tv_sets_count=tv_sets_count,
    )
    assert household["enumeration_verdict"] == "COMPLIANT"
    assert household["status"] == "ACTIVE"
    return {"household": household, "tuner": tuner}


def _dma_520_full_cell(panel: PanelHarness):
    """DMA-520: a cell of target 2 filled by two ACTIVE homes, boost disarmed."""
    market = panel.create_market(
        name="Metro Upsilon",
        market_code="DMA-520",
        dma_rank=20,
        incentive_budget_cents=1000000,
    )
    cell = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=2,
        base_incentive_cents=4000,
    )
    home_a = _active_home(
        panel,
        market["id"],
        cell["id"],
        recruitment_source="ADDRESS_SAMPLE",
        persons_count=2,
        tv_sets_count=1,
        serial_no="MT-001801",
    )
    home_b = _active_home(
        panel,
        market["id"],
        cell["id"],
        recruitment_source="RDD_PHONE",
        persons_count=3,
        tv_sets_count=2,
        serial_no="MT-001802",
    )
    return {"market": market, "cell": cell, "home_a": home_a, "home_b": home_b}


class TestFaultRepairConservesIntabCountAndReservedBoost:
    """PRD 3.3: fault then repair returns intab_count and the reserve exactly."""

    def test_the_pre_fault_cell_is_filled_with_no_reserve_and_a_closed_market(
        self, panel: PanelHarness
    ):
        """Control: the state both repairs must restore, computed from the cell alone.

        PRD 3.2: "`fill_rate` is then the in-tab count divided by
        `target_households`, rounded half up to 4 decimal places. The status follows
        from the rate: `FILLED` when the rate is 1.0000 or more". PRD 2.11 clause 2:
        "if the market has at least one quota cell and every one of its quota cells
        is `FILLED` ... the posture is `CLOSED`."

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 2
        assert cell["fill_rate"] == 1.0000
        assert cell["quota_status"] == "FILLED"
        assert cell["incentive_boost_active"] is False
        assert cell["effective_incentive_multiplier"] == 1.00

        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 0
        assert market["recruitment_posture"] == "CLOSED"

    def test_first_fault_drops_one_home_and_arms_the_reserve_at_2000(
        self, panel: PanelHarness
    ):
        """Links 1 to 5 fire once: intab 1, fill 0.5000, reserve 2000, posture OPEN.

        PRD 3.3 link 4: "the cell's `incentive_boost_active` becomes true,
        `effective_incentive_multiplier` becomes 1.25, and the market's
        `incentive_budget_reserved_cents` rises by `base_incentive_cents` multiplied
        by one quarter and by `target_households`, rounded half up to a whole cent."
        4000 x 0.25 x 2 = 2000.

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)

        faulted = validate_success(
            panel.client.report_meter_fault(
                panel.tech, base["home_a"]["tuner"]["id"], fault_code="NO_SIGNAL"
            ),
            200,
        )
        assert faulted["health_status"] == "FAULTED"
        assert faulted["last_fault_code"] == "NO_SIGNAL"
        assert (
            panel.read_household(base["home_a"]["household"]["id"])["status"]
            == "FAULT_HOLD"
        )

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == 0.5000
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == 1.25

        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 2000
        assert market["recruitment_posture"] == "OPEN"

    def test_second_fault_empties_the_cell_without_doubling_the_reserve(
        self, panel: PanelHarness
    ):
        """The reserve is armed once: it stays 2000 and never reaches 4000.

        PRD 3.3: "**Link 4** applies only when that re-grading actually moved the
        cell's `quota_status` to `UNDER_TARGET`". The cell was already
        `UNDER_TARGET`, so no second reservation is added.

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)
        panel.client.report_meter_fault(
            panel.tech, base["home_a"]["tuner"]["id"], fault_code="NO_SIGNAL"
        )

        faulted_b = validate_success(
            panel.client.report_meter_fault(
                panel.tech, base["home_b"]["tuner"]["id"], fault_code="POWER_LOSS"
            ),
            200,
        )
        assert faulted_b["health_status"] == "FAULTED"
        assert (
            panel.read_household(base["home_b"]["household"]["id"])["status"]
            == "FAULT_HOLD"
        )

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == 0.0000
        assert cell["quota_status"] == "UNDER_TARGET"

        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 2000
        assert market["incentive_budget_reserved_cents"] != 4000

    def test_first_repair_restores_one_home_and_holds_the_reserve_at_2000(
        self, panel: PanelHarness
    ):
        """Coming back to one in-tab home leaves the cell UNDER_TARGET and the reserve armed.

        PRD 3.3: "When the repaired device is a `TV_TUNER` with `install_status`
        `INSTALLED`, the household is in `FAULT_HOLD`, and the household's
        `enumeration_verdict` is still `COMPLIANT`, the household returns to
        `ACTIVE`, its cell's `intab_count` rises by one and the cell is re-graded;
        when that re-grading moves the cell out of `UNDER_TARGET` ... the market's
        `incentive_budget_reserved_cents` falls by the same quarter-of-base figure".
        A rate of 0.5000 is still `UNDER_TARGET`, so the release does not fire yet.

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)
        panel.client.report_meter_fault(
            panel.tech, base["home_a"]["tuner"]["id"], fault_code="NO_SIGNAL"
        )
        panel.client.report_meter_fault(
            panel.tech, base["home_b"]["tuner"]["id"], fault_code="POWER_LOSS"
        )

        repaired = validate_success(
            panel.client.repair_meter(
                panel.tech,
                base["home_b"]["tuner"]["id"],
                repair_note="Power supply replaced",
            ),
            200,
        )
        assert repaired["health_status"] == "HEALTHY"
        assert repaired["last_fault_code"] is None
        assert (
            panel.read_household(base["home_b"]["household"]["id"])["status"] == "ACTIVE"
        )

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == 0.5000
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert (
            panel.read_market(base["market"]["id"])["incentive_budget_reserved_cents"]
            == 2000
        )

    def test_second_repair_returns_intab_and_reserve_to_the_pre_fault_values(
        self, panel: PanelHarness
    ):
        """The round trip closes exactly: intab 2, reserve 0, posture CLOSED again.

        PRD 3.3: "Because both directions compute the reservation from the cell's own
        stored numbers, a fault followed by a repair returns `intab_count` and
        `incentive_budget_reserved_cents` to precisely their pre-fault values."

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)
        panel.client.report_meter_fault(
            panel.tech, base["home_a"]["tuner"]["id"], fault_code="NO_SIGNAL"
        )
        panel.client.report_meter_fault(
            panel.tech, base["home_b"]["tuner"]["id"], fault_code="POWER_LOSS"
        )
        panel.client.repair_meter(
            panel.tech, base["home_b"]["tuner"]["id"], repair_note="Power supply replaced"
        )

        repaired = validate_success(
            panel.client.repair_meter(
                panel.tech,
                base["home_a"]["tuner"]["id"],
                repair_note="Tuner board replaced",
            ),
            200,
        )
        assert repaired["health_status"] == "HEALTHY"
        assert (
            panel.read_household(base["home_a"]["household"]["id"])["status"] == "ACTIVE"
        )

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 2
        assert cell["fill_rate"] == 1.0000
        assert cell["quota_status"] == "FILLED"
        assert cell["incentive_boost_active"] is False
        assert cell["effective_incentive_multiplier"] == 1.00

        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 0
        assert market["recruitment_posture"] == "CLOSED"

    def test_lifetime_fault_counters_are_the_one_thing_the_repair_does_not_undo(
        self, panel: PanelHarness
    ):
        """Each device keeps `fault_count` 1 with `missing_minutes_last_scan` still 0.

        PRD 3.3: "What it does **not** do is undo `fault_count`, which is a lifetime
        counter and only ever rises." And: "The repair sets `health_status` to
        `HEALTHY`, clears `last_fault_code` back to null and resets
        `missing_minutes_last_scan` to 0."

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)
        for tuner_id, code in (
            (base["home_a"]["tuner"]["id"], "NO_SIGNAL"),
            (base["home_b"]["tuner"]["id"], "POWER_LOSS"),
        ):
            panel.client.report_meter_fault(panel.tech, tuner_id, fault_code=code)
        panel.client.repair_meter(
            panel.tech, base["home_b"]["tuner"]["id"], repair_note="Power supply replaced"
        )
        panel.client.repair_meter(
            panel.tech, base["home_a"]["tuner"]["id"], repair_note="Tuner board replaced"
        )

        for tuner_id in (base["home_a"]["tuner"]["id"], base["home_b"]["tuner"]["id"]):
            meter = panel.read_meter(tuner_id)
            assert meter["health_status"] == "HEALTHY"
            assert meter["last_fault_code"] is None
            assert meter["fault_count"] == 1
            assert meter["missing_minutes_last_scan"] == 0

    def test_a_second_fault_report_without_a_repair_is_refused(
        self, panel: PanelHarness
    ):
        """Control: the cascade cannot fire twice off one device, so the reserve is safe.

        PRD 3.3: "The device's `health_status` must be `HEALTHY` or `SUSPECT`,
        otherwise `ERR_METER_ALREADY_FAULTED` — the same fault cannot be reported
        twice without an intervening repair."

        Design: Difficulty/compensating_invariant/fault_repair_conserves_intab_count_and_reserved_boost
        """
        base = _dma_520_full_cell(panel)
        panel.client.report_meter_fault(
            panel.tech, base["home_a"]["tuner"]["id"], fault_code="NO_SIGNAL"
        )

        response = panel.client.report_meter_fault(
            panel.tech, base["home_a"]["tuner"]["id"], fault_code="TAMPER"
        )
        validate_error(response, "ERR_METER_ALREADY_FAULTED")

        meter = panel.read_meter(base["home_a"]["tuner"]["id"])
        assert meter["fault_count"] == 1
        assert meter["last_fault_code"] == "NO_SIGNAL"
        assert panel.read_quota_cell(base["cell"]["id"])["intab_count"] == 1
        assert (
            panel.read_market(base["market"]["id"])["incentive_budget_reserved_cents"]
            == 2000
        )


# ----------------------------------------------------------------------
# DMA-521: total weight mass
# ----------------------------------------------------------------------

DMA_521_CELLS = (
    {
        "age_band": "P18_34",
        "income_band": "LOW",
        "geo_zone": "URBAN",
        "target_households": 1,
        "base_incentive_cents": 2000,
    },
    {
        "age_band": "P18_34",
        "income_band": "MID",
        "geo_zone": "SUBURBAN",
        "target_households": 1,
        "base_incentive_cents": 2000,
    },
    {
        "age_band": "P35_54",
        "income_band": "MID",
        "geo_zone": "RURAL",
        "target_households": 1,
        "base_incentive_cents": 2000,
    },
    {
        "age_band": "P55_PLUS",
        "income_band": "HIGH",
        "geo_zone": "URBAN",
        "target_households": 1,
        "base_incentive_cents": 2000,
    },
)

# The fourth cell is the population outlier that the cap has to trim.
DMA_521_POPULATIONS = ((100000, 250000), (30000, 70000), (80000, 180000), (1100000, 2400000))

# Recruitment source, persons, television sets, serial and reported minutes per home,
# listed in the household `created_at` order every tie-break in PRD 3.7 depends on.
DMA_521_HOMES = (
    ("ADDRESS_SAMPLE", 2, 1, "MT-001901", "2026-08-10T18:00:00Z", "2026-08-10T23:50:00Z", 350),
    ("ADDRESS_SAMPLE", 2, 1, "MT-001902", "2026-08-10T06:00:00Z", "2026-08-10T18:10:00Z", 730),
    ("RDD_PHONE", 1, 1, "MT-001903", "2026-08-10T20:00:00Z", "2026-08-10T21:00:00Z", 60),
    (
        "ONLINE_PANEL_TRANSFER",
        4,
        3,
        "MT-001904",
        "2026-08-10T06:00:00Z",
        "2026-08-10T21:00:00Z",
        900,
    ),
)


def _dma_521_edited_run(panel: PanelHarness):
    """DMA-521: four one-home cells over the 2026-08-10 day, edited but not weighted."""
    base = _measurement_base(
        panel,
        name="Metro Phi",
        market_code="DMA-521",
        dma_rank=21,
        cell_specs=list(DMA_521_CELLS),
        populations=list(DMA_521_POPULATIONS),
    )
    homes = []
    for cell, spec in zip(base["cells"], DMA_521_HOMES):
        source, persons, tv_sets, serial, _start, _end, _minutes = spec
        homes.append(
            _active_home(
                panel,
                base["market"]["id"],
                cell["id"],
                recruitment_source=source,
                persons_count=persons,
                tv_sets_count=tv_sets,
                serial_no=serial,
            )
        )

    # A run may not process a window that has not finished, so the clock moves first.
    panel.set_clock("2026-08-11T00:00:00Z")
    for home, spec in zip(homes, DMA_521_HOMES):
        _source, _persons, _tv, _serial, start_iso, end_iso, minutes = spec
        panel.ingest_interval(
            home["tuner"]["id"],
            home["household"]["id"],
            start_iso,
            end_iso,
            minutes,
            source_methodology="INHOME_TUNER",
            station_code="WXYZ",
        )

    run = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso="2026-08-10T00:00:00Z",
        window_end_iso="2026-08-11T00:00:00Z",
    )
    assert run["window_minutes"] == 1440
    assert run["intab_snapshot_count"] == 4
    edited = panel.edit_run(run["id"])
    base["homes"] = homes
    base["run"] = run
    base["edited"] = edited
    return base


def _weight_rows_by_household(panel: PanelHarness, run_id: str):
    """The run's weight rows keyed by household, plus the ordered household ids."""
    rows, meta = validate_paginated(
        panel.client.list_household_weights(
            panel.statistician, processing_run_id=run_id, limit=100
        )
    )
    assert meta["total_count"] == len(rows)
    return {row["household_id"]: row for row in rows}, [row["household_id"] for row in rows]


class TestWeightCapRedistributionConservesTotalWeightMass:
    """PRD 3.7: capping one row and sharing its excess conserves the whole mass."""

    def test_the_edit_pass_credits_all_four_homes_with_nothing_invalidated(
        self, panel: PanelHarness
    ):
        """900 minutes is not *above* the 900-minute ceiling, and no home passes 1200.

        PRD 3.6 step 2: "A claimed record whose `tuning_minutes` exceeds the rule
        set's `invalid_tuning_max_minutes` moves to `state` `INVALIDATED`". Step 6:
        "A household strictly exceeding the cap is an outlier household". Step 3:
        "`INHOME_TUNER` credits at 1.0".

        Design: Difficulty/compensating_invariant/weight_cap_redistribution_conserves_total_weight_mass
        """
        base = _dma_521_edited_run(panel)

        edited = base["edited"]
        assert edited["state"] == "EDITED"
        assert edited["contributing_household_count"] == 4
        assert edited["invalidated_interval_count"] == 0
        assert edited["outlier_household_count"] == 0
        assert edited["ascribed_interval_count"] == 0
        assert edited["limitation_disclosures"] == []

        rows, _meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician, processing_run_id=base["run"]["id"], limit=100
            )
        )
        assert sorted(row["usable_minutes"] for row in rows) == [60, 350, 730, 900]
        assert {row["state"] for row in rows} == {"EDITED"}

    def test_only_the_outlier_row_is_capped_at_the_run_mean_times_the_ratio(
        self, panel: PanelHarness
    ):
        """base_weight 1100000 is above the 818750 cap; the other three are not.

        PRD 3.7: "The mean base is the mass divided by the row count, rounded half up
        to 4 decimal places, and the cap is that mean base multiplied by the rule
        set's `outlier_weight_ratio_cap`". Under `FINAL` every denominator is 1, so
        the base weights are 100000.0000, 30000.0000, 80000.0000 and 1100000.0000,
        the mass is 1310000.0000, the mean base is 327500.0000 and the cap is
        818750.0000.

        Design: Difficulty/compensating_invariant/weight_cap_redistribution_conserves_total_weight_mass
        """
        base = _dma_521_edited_run(panel)
        panel.weight_run(base["run"]["id"], weight_variant="FINAL")

        by_household, ordered = _weight_rows_by_household(panel, base["run"]["id"])
        household_ids = [home["household"]["id"] for home in base["homes"]]
        assert ordered == household_ids
        assert [by_household[hid]["base_weight"] for hid in household_ids] == [
            100000.0000,
            30000.0000,
            80000.0000,
            1100000.0000,
        ]
        assert [by_household[hid]["capped"] for hid in household_ids] == [
            False,
            False,
            False,
            True,
        ]
        assert by_household[household_ids[3]]["adjusted_weight"] == 818750.0000
        assert {row["weight_variant"] for row in by_household.values()} == {"FINAL"}

    def test_the_drift_repair_lands_on_the_first_receiver_in_created_at_order(
        self, panel: PanelHarness
    ):
        """Only h1 carries the repaired fourth decimal: 233928.5715 against 233928.5714.

        PRD 3.7: "Each receiver's share is the excess multiplied by that receiver's
        `base_weight` and divided by the receiver mass, rounded half up to 4 decimal
        places". The excess is 281250.0000 over a receiver mass of 210000.0000, so
        the raw shares are 133928.5714, 40178.5714 and 107142.8571. "The drift is the
        original mass minus the sum of `adjusted_weight` across **all** rows, and it
        is added to the `adjusted_weight` of the **first** receiver in `created_at`
        ascending order." The four rows sum to 1309999.9999, so +0.0001 goes to h1.

        Design: Difficulty/compensating_invariant/weight_cap_redistribution_conserves_total_weight_mass
        """
        base = _dma_521_edited_run(panel)
        panel.weight_run(base["run"]["id"], weight_variant="FINAL")

        by_household, _ordered = _weight_rows_by_household(panel, base["run"]["id"])
        household_ids = [home["household"]["id"] for home in base["homes"]]
        assert [by_household[hid]["adjusted_weight"] for hid in household_ids] == [
            233928.5715,
            70178.5714,
            187142.8571,
            818750.0000,
        ]
        assert by_household[household_ids[0]]["adjusted_weight"] != 233928.5714

    def test_total_weight_mass_is_identical_to_the_pre_cap_mass(
        self, panel: PanelHarness
    ):
        """Redistribution conserved the whole mass to the last fourth-decimal unit.

        PRD 3.7: "Total weight mass is conserved exactly to the last fourth-decimal
        unit, and `total_weight_mass` is the conserved figure."

        Design: Difficulty/compensating_invariant/weight_cap_redistribution_conserves_total_weight_mass
        """
        base = _dma_521_edited_run(panel)
        weighted = panel.weight_run(base["run"]["id"], weight_variant="FINAL")

        assert weighted["state"] == "WEIGHTED"
        assert weighted["weight_variant"] == "FINAL"
        assert weighted["total_weight_mass"] == 1310000.0000
        assert weighted["excluded_cell_count"] == 0
        assert weighted["limitation_disclosures"] == ["WEIGHT_CAP_APPLIED"]

        by_household, _ordered = _weight_rows_by_household(panel, base["run"]["id"])
        assert (
            round(sum(row["adjusted_weight"] for row in by_household.values()), 4)
            == 1310000.0000
        )
        assert (
            round(sum(row["base_weight"] for row in by_household.values()), 4)
            == 1310000.0000
        )

    def test_the_projection_sums_the_already_rounded_contributions(
        self, panel: PanelHarness
    ):
        """56857.64 + 35576.64 + 7797.62 + 511718.75 = 611950.65, rounded once to 611951.

        PRD 3.7: "First, each household's `contribution` is its `adjusted_weight`
        multiplied by its summed usable minutes and divided by the run's
        `window_minutes`, rounded half up to 2 decimal places. Second, the raw total
        is the sum of those **already-rounded** contributions. Third,
        `projected_average_audience` is that raw total rounded half up to a whole
        household count."

        Design: Difficulty/compensating_invariant/weight_cap_redistribution_conserves_total_weight_mass
        """
        base = _dma_521_edited_run(panel)
        weighted = panel.weight_run(base["run"]["id"], weight_variant="FINAL")

        by_household, _ordered = _weight_rows_by_household(panel, base["run"]["id"])
        household_ids = [home["household"]["id"] for home in base["homes"]]
        assert [by_household[hid]["usable_minutes"] for hid in household_ids] == [
            350,
            730,
            60,
            900,
        ]
        assert [by_household[hid]["contribution"] for hid in household_ids] == [
            56857.64,
            35576.64,
            7797.62,
            511718.75,
        ]
        assert weighted["projected_average_audience"] == 611951
        assert {row["run_compliance_rate"] for row in by_household.values()} == {1.0000}
