"""State-machine transitions, terminal-state lockdowns and cascade round trips.

Every test in this module translates exactly one instance of the
``state_machines`` section of the Queue B corner-case design index: the
household lifecycle, the meter's two independent status dimensions, the
processing-run walk and its only loop, the forked deliverable lifecycle,
client suspension, notification acknowledgement, accreditation audits and the
publication state machines of universe vintages and editing rule sets.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.factories import cell_population, edit_rule_set_payload
from test_helpers.fixtures import CLOCK_T0, PanelHarness
from test_helpers.test_users import (
    AUDITOR_FINALIZER_USER_ID,
    STATISTICIAN_PUBLISHER_USER_ID,
    STATISTICIAN_THIRD_USER_ID,
    STATISTICIAN_USER_ID,
    make_statistician_headers,
)

# ---------------------------------------------------------------------------
# Local helpers
#
# PRD 2.5 renders every business-event timestamp "in the same ISO 8601 UTC
# form" as `created_at`, which carries three fractional digits, so an instant
# the design index writes as `2026-08-01T00:00:00Z` may legitimately be
# rendered `2026-08-01T00:00:00.000Z`. These helpers compare the instant
# itself rather than the rendering, which is the assertion the PRD makes.
# ---------------------------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse one ISO 8601 UTC rendering into the instant it names."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant(actual: str, expected: str) -> None:
    """Assert that `actual` names exactly the instant `expected` names."""
    assert _instant(actual) == _instant(expected), (
        f"expected the instant {expected!r}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# The design index's reusable fixture chains, rebuilt from scratch in-process.
#
# The harness restarts the server before every test, so every chain below is
# built through PRD endpoints inside the test that needs it.
#
# CHAIN A - a market with one quota cell.
# CHAIN B - CHAIN A plus one ACTIVE (in-tab) household with an INSTALLED,
#           HEALTHY TV_TUNER.
# CHAIN C - CHAIN B with target_households 1 and base_incentive_cents 2000,
#           plus a PUBLISHED rule set, a PUBLISHED 2026Q3 vintage of 100000
#           households, one 350-minute block on 2026-08-10 and a run over
#           [2026-08-10, 2026-08-11).
# ---------------------------------------------------------------------------

CHAIN_C_CLOCK = "2026-08-11T00:00:00Z"
CHAIN_C_WINDOW_START = "2026-08-10T00:00:00Z"
CHAIN_C_WINDOW_END = "2026-08-11T00:00:00Z"
CHAIN_C_BLOCK_START = "2026-08-10T18:00:00Z"
CHAIN_C_BLOCK_END = "2026-08-10T23:50:00Z"
CHAIN_C_TUNING_MINUTES = 350
CHAIN_C_POPULATION_HOUSEHOLDS = 100000
CHAIN_C_POPULATION_PERSONS = 250000

# The rule set every chain-C run is pinned to: {60, 900, 1200, 2.5, 1440}.
CHAIN_C_RULE_SET = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}


def build_chain_b(
    panel: PanelHarness,
    dma_rank: int = 120,
    target_households: int = 2,
    base_incentive_cents: int = 1000,
    persons_count: int = 2,
    tv_sets_count: int = 1,
):
    """CHAIN B: a market, one cell, and one ACTIVE household with a tuner."""
    market = panel.create_market(dma_rank=dma_rank, incentive_budget_cents=500000)
    cell = panel.create_quota_cell(
        market["id"],
        target_households=target_households,
        base_incentive_cents=base_incentive_cents,
    )
    household = panel.recruit_household(market["id"], cell["id"], persons_count=persons_count)
    tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
    tuner = validate_success(panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200)
    household = validate_success(
        panel.client.create_enumeration(
            panel.tech,
            household["id"],
            roster_persons_count=persons_count,
            tv_sets_count=tv_sets_count,
        ),
        200,
    )
    return {"market": market, "cell": cell, "household": household, "tuner": tuner}


def build_chain_c_open(panel: PanelHarness, dma_rank: int = 133):
    """CHAIN C carried to step C9: an OPEN run over one 350-minute block."""
    base = build_chain_b(
        panel,
        dma_rank=dma_rank,
        target_households=1,
        base_incentive_cents=2000,
        persons_count=2,
    )
    rule_set = panel.published_rule_set(**CHAIN_C_RULE_SET)
    universe = panel.published_universe(
        base["market"]["id"],
        [base["cell"]["id"]],
        cell_populations=[
            cell_population(
                base["cell"]["id"],
                population_households=CHAIN_C_POPULATION_HOUSEHOLDS,
                population_persons=CHAIN_C_POPULATION_PERSONS,
            )
        ],
    )
    panel.set_clock(CHAIN_C_CLOCK)
    interval = panel.ingest_interval(
        base["tuner"]["id"],
        base["household"]["id"],
        CHAIN_C_BLOCK_START,
        CHAIN_C_BLOCK_END,
        CHAIN_C_TUNING_MINUTES,
    )
    run = panel.open_run(
        base["market"]["id"],
        universe["id"],
        rule_set["id"],
        window_start_iso=CHAIN_C_WINDOW_START,
        window_end_iso=CHAIN_C_WINDOW_END,
    )
    base.update({"rule_set": rule_set, "universe": universe, "interval": interval, "run": run})
    return base


def build_chain_c_edited(panel: PanelHarness, dma_rank: int = 135):
    """CHAIN C carried to step C10: the run is EDITED with one claimed block."""
    base = build_chain_c_open(panel, dma_rank=dma_rank)
    base["run"] = panel.edit_run(base["run"]["id"])
    return base


def build_chain_c_published(panel: PanelHarness, dma_rank: int = 134):
    """CHAIN C complete: a PUBLISHED run, the clock at 2026-08-11T00:00:00Z."""
    base = build_chain_c_edited(panel, dma_rank=dma_rank)
    base["run"] = panel.weight_run(base["run"]["id"], weight_variant="FINAL")
    base["run"] = panel.publish_run(base["run"]["id"])
    return base


class TestHouseholdLifecycle:
    """RECRUITED -> INSTALL_SCHEDULED -> ENUM_PENDING -> ACTIVE and its loops."""

    def test_tuner_install_confirmation_opens_enumeration(self, panel: PanelHarness):
        """The TV_TUNER confirmation is what carries the home to ENUM_PENDING.

        PRD 3.3: "The dimension moves to `INSTALLED` and `installed_at` is
        stamped from the logical clock. Only a `TV_TUNER` advances the home:
        when the confirmed device is a `TV_TUNER` and the household is
        `INSTALL_SCHEDULED`, the household moves to `ENUM_PENDING` and
        enumeration becomes possible."

        PRD 3.3: "Installation alone never puts a household in tab, so no
        `intab_count` moves here."

        Design: Corner/state_machines/household_lifecycle_reaches_active_and_moves_intab
        """
        market = panel.create_market(dma_rank=120, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=4, base_incentive_cents=1000
        )
        household = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        assert household["status"] == "RECRUITED"

        tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
        assert panel.read_household(household["id"])["status"] == "INSTALL_SCHEDULED"

        confirmed = validate_success(
            panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200
        )
        assert confirmed["install_status"] == "INSTALLED"
        assert_instant(confirmed["installed_at"], CLOCK_T0)

        assert panel.read_household(household["id"])["status"] == "ENUM_PENDING"
        assert panel.read_quota_cell(cell["id"])["intab_count"] == 0

    def test_compliant_first_enumeration_activates_the_household(self, panel: PanelHarness):
        """ENUM_PENDING plus a COMPLIANT verdict is the only route to ACTIVE.

        PRD 3.2: "`ENUM_PENDING` with a `COMPLIANT` verdict moves the household
        to `ACTIVE`."

        PRD 3.2: "Whatever the verdict, `enumeration_count` rises by one and
        `roster_persons_count`, `tv_sets_count`, `enumeration_verdict` and
        `last_enumeration_at` are refreshed from the submission and the clock."

        Design: Corner/state_machines/household_lifecycle_reaches_active_and_moves_intab
        """
        market = panel.create_market(dma_rank=120, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=4, base_incentive_cents=1000
        )
        household = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
        validate_success(panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200)

        enumerated = validate_success(
            panel.client.create_enumeration(
                panel.tech, household["id"], roster_persons_count=3, tv_sets_count=2
            ),
            200,
        )
        assert enumerated["status"] == "ACTIVE"
        assert enumerated["enumeration_verdict"] == "COMPLIANT"
        assert enumerated["enumeration_count"] == 1
        assert enumerated["roster_persons_count"] == 3
        assert enumerated["tv_sets_count"] == 2
        assert_instant(enumerated["last_enumeration_at"], CLOCK_T0)

    def test_activation_moves_intab_count_and_leaves_the_boost_armed(self, panel: PanelHarness):
        """Only the terminal step touches intab_count; 1/4 stays UNDER_TARGET.

        PRD 3.2: "Its cell's `intab_count` rises by one, the fill calculation
        re-grades the cell, and the market's posture is recomputed."

        PRD 3.1: "`fill_rate` is then the in-tab count divided by
        `target_households`, rounded half up to 4 decimal places. The status
        follows from the rate: `FILLED` when the rate is 1.0000 or more,
        `ON_TARGET` when the rate is 0.8000 or more but below 1.0000, and
        `UNDER_TARGET` in every other case."

        Design: Corner/state_machines/household_lifecycle_reaches_active_and_moves_intab
        """
        market = panel.create_market(dma_rank=120, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=4, base_incentive_cents=1000
        )
        household = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
        validate_success(panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200)
        validate_success(
            panel.client.create_enumeration(
                panel.tech, household["id"], roster_persons_count=3, tv_sets_count=2
            ),
            200,
        )

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 1
        assert graded["fill_rate"] == 0.25
        assert graded["quota_status"] == "UNDER_TARGET"
        assert graded["incentive_boost_active"] is True
        assert graded["effective_incentive_multiplier"] == 1.25

    def test_noncompliant_roster_holds_the_household_and_drops_it_out_of_tab(
        self, panel: PanelHarness
    ):
        """An ACTIVE home with a disagreeing roster leaves the in-tab sample.

        PRD 3.2: "`ACTIVE` with a `NONCOMPLIANT` verdict moves the household to
        `NONCOMPLIANT_HOLD`, drops its cell's `intab_count` by one, re-grades the
        cell, and recomputes the market posture."

        PRD 3.2: "The roster test passes when the submitted
        `roster_persons_count` equals the household's recorded `persons_count`
        exactly."

        Design: Corner/state_machines/household_noncompliant_hold_then_recovers_to_active
        """
        base = build_chain_b(
            panel, dma_rank=121, target_households=4, base_incentive_cents=1000, persons_count=3
        )
        assert base["household"]["status"] == "ACTIVE"
        panel.set_clock("2026-10-01T00:00:00Z")

        held = validate_success(
            panel.client.create_enumeration(
                panel.tech, base["household"]["id"], roster_persons_count=5, tv_sets_count=1
            ),
            200,
        )
        assert held["status"] == "NONCOMPLIANT_HOLD"
        assert held["enumeration_verdict"] == "NONCOMPLIANT"
        assert held["enumeration_count"] == 2
        assert held["roster_persons_count"] == 5

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == 0.0

    def test_recovering_enumeration_returns_the_household_to_active_with_no_drift(
        self, panel: PanelHarness
    ):
        """A third, agreeing visit two months late still restores ACTIVE and in-tab.

        PRD 3.2: "`NONCOMPLIANT_HOLD` with a `COMPLIANT` verdict returns the
        household to `ACTIVE` — again requiring at least one `INSTALLED` and
        `HEALTHY` `TV_TUNER` — raising the cell's `intab_count` by one, re-grading
        the cell and recomputing the posture. The cycle `ACTIVE →
        NONCOMPLIANT_HOLD → ACTIVE` therefore returns `intab_count` to precisely
        its pre-hold value."

        PRD 3.2: "Every later submission passes the timeliness test
        unconditionally, because re-enumerations carry no due date."

        Design: Corner/state_machines/household_noncompliant_hold_then_recovers_to_active
        """
        base = build_chain_b(
            panel, dma_rank=121, target_households=4, base_incentive_cents=1000, persons_count=3
        )
        panel.set_clock("2026-10-01T00:00:00Z")
        validate_success(
            panel.client.create_enumeration(
                panel.tech, base["household"]["id"], roster_persons_count=5, tv_sets_count=1
            ),
            200,
        )

        recovered = validate_success(
            panel.client.create_enumeration(
                panel.tech, base["household"]["id"], roster_persons_count=3, tv_sets_count=1
            ),
            200,
        )
        assert recovered["status"] == "ACTIVE"
        assert recovered["enumeration_verdict"] == "COMPLIANT"
        assert recovered["enumeration_count"] == 3
        assert recovered["roster_persons_count"] == 3
        # PRD 3.2 refreshes roster_persons_count from the submission and never
        # rewrites the recruited persons_count.
        assert recovered["persons_count"] == 3

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == 0.25

    def test_retirement_from_active_never_claws_back_the_incentive_ledger(
        self, panel: PanelHarness
    ):
        """RETIRED is reached from ACTIVE and the cooperation ledger survives.

        PRD 3.2: "The household's `status` becomes `RETIRED`".

        PRD 3.2: "What retirement never does is claw money back: unreversed
        entries in `accrual_periods` stay on the ledger, `incentive_accrued_cents`
        is left exactly as it stands".

        Design: Corner/state_machines/household_retire_from_active_cascades_meter_removal_and_intab
        """
        base = build_retirement_fixture(panel)
        accrued_before = base["accrued"]["incentive_accrued_cents"]
        assert accrued_before > 0

        retired = validate_success(
            panel.client.retire_household(
                panel.ops, base["household"]["id"], retired_reason="MOVED_OUT_OF_MARKET"
            ),
            200,
        )
        assert retired["status"] == "RETIRED"
        assert retired["retired_reason"] == "MOVED_OUT_OF_MARKET"
        assert retired["incentive_accrued_cents"] == accrued_before
        assert any(
            entry["period_label"] == "2026-08" and entry["reversed"] is False
            for entry in retired["accrual_periods"]
        )

    def test_retirement_cascade_removes_only_the_installed_meter(self, panel: PanelHarness):
        """The cascade is conditional: the INSTALLED tuner moves, the SHIPPED router does not.

        PRD 3.2: "every meter of the household whose `install_status` is
        `INSTALLED` moves to `REMOVED` — a conditional cascade, so meters still
        `SHIPPED` and meters already `REMOVED` are untouched. If, and only if, the
        household was `ACTIVE` at the moment of retirement, its cell's
        `intab_count` falls by one, the cell is re-graded and the market posture is
        recomputed."

        PRD 3.3: "a `REMOVED` meter retains whatever `health_status` it had when
        it was pulled".

        Design: Corner/state_machines/household_retire_from_active_cascades_meter_removal_and_intab
        """
        base = build_retirement_fixture(panel)
        validate_success(
            panel.client.retire_household(
                panel.ops, base["household"]["id"], retired_reason="MOVED_OUT_OF_MARKET"
            ),
            200,
        )

        tuner = panel.read_meter(base["tuner"]["id"])
        assert tuner["install_status"] == "REMOVED"
        assert tuner["health_status"] == "HEALTHY"

        router = panel.read_meter(base["router"]["id"])
        assert router["install_status"] == "SHIPPED"

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == 0.0
        assert cell["quota_status"] == "UNDER_TARGET"


def build_retirement_fixture(panel: PanelHarness):
    """An ACTIVE household with an INSTALLED tuner, a SHIPPED router and one accrual.

    The design index ships the second meter after the tuner's install
    confirmation, but PRD 3.3 check 1 only admits a shipment while the household
    is `RECRUITED` or `INSTALL_SCHEDULED`, so both devices are shipped before the
    confirmation. The resulting post-state is the one the recipe describes.
    """
    market = panel.create_market(dma_rank=122, incentive_budget_cents=500000)
    cell = panel.create_quota_cell(market["id"], target_households=2, base_incentive_cents=1000)
    household = panel.recruit_household(market["id"], cell["id"], persons_count=2)
    tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
    router = panel.ship_meter(household["id"], meter_type="STREAMING_ROUTER")
    tuner = validate_success(panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200)
    household = validate_success(
        panel.client.create_enumeration(
            panel.tech, household["id"], roster_persons_count=2, tv_sets_count=1
        ),
        200,
    )
    assert household["status"] == "ACTIVE"
    accrued = validate_success(
        panel.client.accrue_incentive(panel.ops, household["id"], period_label="2026-08"), 200
    )
    return {
        "market": market,
        "cell": cell,
        "household": household,
        "tuner": tuner,
        "router": router,
        "accrued": accrued,
    }


class TestRetiredHouseholdTerminal:
    """RETIRED is terminal on four surfaces, each with its own error id."""

    def test_second_retirement_is_refused(self, panel: PanelHarness):
        """RECRUITED -> RETIRED is a legal edge; retiring twice is not.

        PRD 3.2: "Retirement is admitted from any status except `RETIRED` itself;
        a household already in the terminal status is refused with
        `ERR_HOUSEHOLD_ALREADY_RETIRED`."

        Design: Corner/state_machines/retired_household_rejects_every_further_trigger
        """
        market = panel.create_market(dma_rank=123, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=2, base_incentive_cents=1000
        )
        household = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="RDD_PHONE", persons_count=2
        )
        first = validate_success(
            panel.client.retire_household(
                panel.ops, household["id"], retired_reason="REFUSED_CONTINUATION"
            ),
            200,
        )
        assert first["status"] == "RETIRED"

        validate_error(
            panel.client.retire_household(
                panel.ops, household["id"], retired_reason="REFUSED_CONTINUATION"
            ),
            "ERR_HOUSEHOLD_ALREADY_RETIRED",
        )
        assert panel.read_household(household["id"])["status"] == "RETIRED"

    def test_retired_household_takes_no_meter_and_consumes_no_serial(self, panel: PanelHarness):
        """The shipment is refused and the serial it named stays claimable.

        PRD 3.3: "The household's `status` must be `RECRUITED` or
        `INSTALL_SCHEDULED`, otherwise `ERR_HOUSEHOLD_NOT_ACCEPTING_METERS`."

        PRD 3.3: "`serial_no` must be unique across every meter row ever created,
        including `REMOVED` ones, otherwise `ERR_METER_SERIAL_DUPLICATE`."

        Design: Corner/state_machines/retired_household_rejects_every_further_trigger
        """
        market = panel.create_market(dma_rank=123, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=2, base_incentive_cents=1000
        )
        retired = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="RDD_PHONE", persons_count=2
        )
        validate_success(
            panel.client.retire_household(
                panel.ops, retired["id"], retired_reason="REFUSED_CONTINUATION"
            ),
            200,
        )

        validate_error(
            panel.client.create_meter(
                panel.tech, retired["id"], meter_type="TV_TUNER", serial_no="MT-002024"
            ),
            "ERR_HOUSEHOLD_NOT_ACCEPTING_METERS",
        )

        # No meter row was written, so MT-002024 is still unique and a later
        # household may claim it.
        other = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="RDD_PHONE", persons_count=2
        )
        claimed = validate_success(
            panel.client.create_meter(
                panel.tech, other["id"], meter_type="TV_TUNER", serial_no="MT-002024"
            ),
            201,
        )
        assert claimed["serial_no"] == "MT-002024"

    def test_retired_household_rejects_enumeration_and_accrual(self, panel: PanelHarness):
        """Two more surfaces refuse a RETIRED home, each with its own error id.

        PRD 3.2: "The household's `status` must be `ENUM_PENDING`, `ACTIVE` or
        `NONCOMPLIANT_HOLD`, otherwise `ERR_HOUSEHOLD_NOT_ENUMERABLE`."

        PRD 3.2: "`RETIRED` is terminal in the strict sense — no later
        enumeration, incentive accrual, meter shipment or meter removal is
        accepted against the household."

        Design: Corner/state_machines/retired_household_rejects_every_further_trigger
        """
        market = panel.create_market(dma_rank=123, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=2, base_incentive_cents=1000
        )
        household = panel.recruit_household(
            market["id"], cell["id"], recruitment_source="RDD_PHONE", persons_count=2
        )
        validate_success(
            panel.client.retire_household(
                panel.ops, household["id"], retired_reason="REFUSED_CONTINUATION"
            ),
            200,
        )

        # ERR_HOUSEHOLD_NOT_ENUMERABLE outranks the missing-tuner check.
        validate_error(
            panel.client.create_enumeration(
                panel.tech, household["id"], roster_persons_count=2, tv_sets_count=1
            ),
            "ERR_HOUSEHOLD_NOT_ENUMERABLE",
        )
        validate_error(
            panel.client.accrue_incentive(panel.ops, household["id"], period_label="2026-08"),
            "ERR_HOUSEHOLD_NOT_ACTIVE",
        )

        after = panel.read_household(household["id"])
        assert after["status"] == "RETIRED"
        assert after["enumeration_count"] == 0
        assert after["incentive_accrued_cents"] == 0


def build_enum_pending_with_removed_tuner(panel: PanelHarness, dma_rank: int, serial_no: str):
    """A household in ENUM_PENDING whose only tuner has been REMOVED."""
    market = panel.create_market(dma_rank=dma_rank, incentive_budget_cents=500000)
    cell = panel.create_quota_cell(market["id"], target_households=2, base_incentive_cents=1000)
    household = panel.recruit_household(market["id"], cell["id"], persons_count=2)
    tuner = validate_success(
        panel.client.create_meter(
            panel.tech, household["id"], meter_type="TV_TUNER", serial_no=serial_no
        ),
        201,
    )
    validate_success(panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200)
    assert panel.read_household(household["id"])["status"] == "ENUM_PENDING"
    return {"market": market, "cell": cell, "household": household, "tuner": tuner}


class TestMeterInstallDimension:
    """SHIPPED -> INSTALLED -> REMOVED, with REMOVED terminal."""

    def test_removal_moves_only_the_install_dimension(self, panel: PanelHarness):
        """INSTALLED -> REMOVED leaves health, the household and in-tab alone.

        PRD 3.3: "Removal sets `install_status` to `REMOVED` and deliberately
        leaves `health_status` and `fault_count` exactly as they were — removal is
        not a repair. No household `status` and no `intab_count` moves".

        Design: Corner/state_machines/enumeration_after_tuner_removal_is_rejected
        """
        base = build_enum_pending_with_removed_tuner(panel, 124, "MT-002025")

        removed = validate_success(
            panel.client.remove_meter(
                panel.tech,
                base["tuner"]["id"],
                removal_note="Device recalled before first enumeration",
            ),
            200,
        )
        assert removed["install_status"] == "REMOVED"
        assert removed["health_status"] == "HEALTHY"

        assert panel.read_household(base["household"]["id"])["status"] == "ENUM_PENDING"
        assert panel.read_quota_cell(base["cell"]["id"])["intab_count"] == 0

    def test_enumeration_without_an_installed_tuner_is_rejected(self, panel: PanelHarness):
        """ENUM_PENDING passes check 1, so the missing-tuner check is the first to fire.

        PRD 3.2: "The household must hold at least one meter whose `meter_type` is
        `TV_TUNER` and whose `install_status` is `INSTALLED`, otherwise
        `ERR_NO_INSTALLED_METER`."

        Design: Corner/state_machines/enumeration_after_tuner_removal_is_rejected
        """
        base = build_enum_pending_with_removed_tuner(panel, 124, "MT-002025")
        validate_success(
            panel.client.remove_meter(
                panel.tech,
                base["tuner"]["id"],
                removal_note="Device recalled before first enumeration",
            ),
            200,
        )

        validate_error(
            panel.client.create_enumeration(
                panel.tech, base["household"]["id"], roster_persons_count=2, tv_sets_count=1
            ),
            "ERR_NO_INSTALLED_METER",
        )
        after = panel.read_household(base["household"]["id"])
        assert after["status"] == "ENUM_PENDING"
        assert after["enumeration_count"] == 0

    def test_removed_meter_is_never_repairable(self, panel: PanelHarness):
        """A REMOVED device is refused a repair even though its health is HEALTHY.

        PRD 3.3: "The device's `health_status` must be `FAULTED` or `SUSPECT` and
        its `install_status` must not be `REMOVED`, otherwise
        `ERR_METER_NOT_FAULTED` — a healthy device has nothing to repair."

        Design: Corner/state_machines/removed_meter_rejects_repairs_intervals_and_a_second_removal
        """
        base = build_enum_pending_with_removed_tuner(panel, 127, "MT-002027")
        validate_success(
            panel.client.remove_meter(
                panel.tech, base["tuner"]["id"], removal_note="End of deployment"
            ),
            200,
        )

        validate_error(
            panel.client.repair_meter(
                panel.tech, base["tuner"]["id"], repair_note="Attempted bench repair"
            ),
            "ERR_METER_NOT_FAULTED",
        )
        after = panel.read_meter(base["tuner"]["id"])
        assert after["install_status"] == "REMOVED"
        assert after["health_status"] == "HEALTHY"
        assert after["fault_count"] == 0

    def test_removed_meter_rejects_ingest_and_a_second_removal(self, panel: PanelHarness):
        """Both the ingest gate and the removals gate answer ERR_METER_NOT_INSTALLED.

        PRD 3.6: "The referenced meter's `install_status` must be `INSTALLED`,
        otherwise `ERR_METER_NOT_INSTALLED`. Shipped and removed devices produce no
        data."

        PRD 3.3: "the meter's `install_status` must be `INSTALLED`, otherwise
        `ERR_METER_NOT_INSTALLED`".

        Design: Corner/state_machines/removed_meter_rejects_repairs_intervals_and_a_second_removal
        """
        base = build_enum_pending_with_removed_tuner(panel, 127, "MT-002027")
        validate_success(
            panel.client.remove_meter(
                panel.tech, base["tuner"]["id"], removal_note="End of deployment"
            ),
            200,
        )

        validate_error(
            panel.client.create_tuning_interval(
                panel.statistician,
                meter_id=base["tuner"]["id"],
                household_id=base["household"]["id"],
                source_methodology="INHOME_TUNER",
                start_iso="2026-07-31T18:00:00Z",
                end_iso="2026-07-31T19:00:00Z",
                station_code="WXYZ",
                tuning_minutes=60,
            ),
            "ERR_METER_NOT_INSTALLED",
        )
        _rows, meta = validate_paginated(
            panel.client.list_tuning_intervals(panel.statistician, meter_id=base["tuner"]["id"])
        )
        assert meta["total_count"] == 0

        validate_error(
            panel.client.remove_meter(
                panel.tech, base["tuner"]["id"], removal_note="Second removal attempt"
            ),
            "ERR_METER_NOT_INSTALLED",
        )

    def test_removed_meter_cannot_be_walked_back_to_installed(self, panel: PanelHarness):
        """REMOVED is terminal on the install dimension: no re-confirmation.

        PRD 3.3: "`install_status` describes where the device physically is and
        walks `SHIPPED` to `INSTALLED` to `REMOVED`, with `REMOVED` terminal."

        PRD 3.3: "The meter's `install_status` must be `SHIPPED`, otherwise
        `ERR_METER_NOT_SHIPPED`."

        Design: Corner/state_machines/removed_meter_rejects_repairs_intervals_and_a_second_removal
        """
        base = build_enum_pending_with_removed_tuner(panel, 127, "MT-002027")
        validate_success(
            panel.client.remove_meter(
                panel.tech, base["tuner"]["id"], removal_note="End of deployment"
            ),
            200,
        )

        validate_error(
            panel.client.confirm_meter_install(panel.tech, base["tuner"]["id"]),
            "ERR_METER_NOT_SHIPPED",
        )
        after = panel.read_meter(base["tuner"]["id"])
        assert after["install_status"] == "REMOVED"
        assert after["health_status"] == "HEALTHY"
        assert after["fault_count"] == 0

    def test_second_install_confirmation_is_refused(self, panel: PanelHarness):
        """The repeat confirmation is rejected rather than silently re-applied.

        PRD 3.3: "The meter's `install_status` must be `SHIPPED`, otherwise
        `ERR_METER_NOT_SHIPPED`."

        Design: Corner/state_machines/meter_install_confirmation_repeated_is_rejected
        """
        market = panel.create_market(dma_rank=126, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=2, base_incentive_cents=1000
        )
        household = panel.recruit_household(market["id"], cell["id"], persons_count=2)
        tuner = validate_success(
            panel.client.create_meter(
                panel.tech, household["id"], meter_type="TV_TUNER", serial_no="MT-002026"
            ),
            201,
        )
        validate_success(panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200)
        panel.set_clock("2026-08-05T00:00:00Z")

        validate_error(
            panel.client.confirm_meter_install(panel.tech, tuner["id"]),
            "ERR_METER_NOT_SHIPPED",
        )
        assert panel.read_meter(tuner["id"])["install_status"] == "INSTALLED"
        assert panel.read_household(household["id"])["status"] == "ENUM_PENDING"
        assert panel.read_quota_cell(cell["id"])["intab_count"] == 0

    def test_installed_at_keeps_the_first_confirmation_instant(self, panel: PanelHarness):
        """The rejected second confirmation leaves installed_at and the home untouched.

        PRD 3.3: "The dimension moves to `INSTALLED` and `installed_at` is stamped
        from the logical clock."

        PRD 2.5: "Timestamps that record a business event rather than a row edit —
        `recruited_at`, `installed_at`, ... — are all read from the logical clock at
        the moment the event occurs".

        Design: Corner/state_machines/meter_install_confirmation_repeated_is_rejected
        """
        market = panel.create_market(dma_rank=126, incentive_budget_cents=500000)
        cell = panel.create_quota_cell(
            market["id"], target_households=2, base_incentive_cents=1000
        )
        household = panel.recruit_household(market["id"], cell["id"], persons_count=2)
        tuner = validate_success(
            panel.client.create_meter(
                panel.tech, household["id"], meter_type="TV_TUNER", serial_no="MT-002026"
            ),
            201,
        )
        confirmed = validate_success(
            panel.client.confirm_meter_install(panel.tech, tuner["id"]), 200
        )
        assert_instant(confirmed["installed_at"], CLOCK_T0)
        panel.set_clock("2026-08-05T00:00:00Z")
        validate_error(
            panel.client.confirm_meter_install(panel.tech, tuner["id"]),
            "ERR_METER_NOT_SHIPPED",
        )

        after = panel.read_meter(tuner["id"])
        assert_instant(after["installed_at"], CLOCK_T0)
        assert _instant(after["installed_at"]) != _instant("2026-08-05T00:00:00Z")
        assert after["install_status"] == "INSTALLED"
        assert panel.read_household(household["id"])["status"] == "ENUM_PENDING"


def build_two_run_scan_fixture(panel: PanelHarness, dma_rank: int):
    """An ACTIVE household with a 400-minute day and two disjoint OPEN runs.

    R1 covers [2026-08-10, 2026-08-11) = 1440 window minutes with 400 covered,
    R2 covers [2026-08-11, 2026-08-13) = 2880 window minutes with none covered.
    """
    base = build_chain_b(
        panel, dma_rank=dma_rank, target_households=2, base_incentive_cents=1000, persons_count=2
    )
    rule_set = panel.published_rule_set(**CHAIN_C_RULE_SET)
    universe = panel.published_universe(
        base["market"]["id"],
        [base["cell"]["id"]],
        cell_populations=[
            cell_population(
                base["cell"]["id"],
                population_households=CHAIN_C_POPULATION_HOUSEHOLDS,
                population_persons=CHAIN_C_POPULATION_PERSONS,
            )
        ],
    )
    panel.set_clock("2026-08-13T00:00:00Z")
    panel.ingest_interval(
        base["tuner"]["id"],
        base["household"]["id"],
        "2026-08-10T00:00:00Z",
        "2026-08-10T12:00:00Z",
        400,
    )
    run_a = panel.open_run(
        base["market"]["id"],
        universe["id"],
        rule_set["id"],
        window_start_iso="2026-08-10T00:00:00Z",
        window_end_iso="2026-08-11T00:00:00Z",
    )
    run_b = panel.open_run(
        base["market"]["id"],
        universe["id"],
        rule_set["id"],
        window_start_iso="2026-08-11T00:00:00Z",
        window_end_iso="2026-08-13T00:00:00Z",
    )
    base.update({"rule_set": rule_set, "universe": universe, "run_a": run_a, "run_b": run_b})
    return base


class TestMeterHealthDimension:
    """HEALTHY / SUSPECT / FAULTED, its escalations, repairs and cascades."""

    def test_second_fault_report_is_refused_and_never_double_counts(self, panel: PanelHarness):
        """A FAULTED device refuses a second report and keeps the first code.

        PRD 3.3: "The device's `health_status` must be `HEALTHY` or `SUSPECT`,
        otherwise `ERR_METER_ALREADY_FAULTED` — the same fault cannot be reported
        twice without an intervening repair."

        PRD 3.3: "`health_status` becomes `FAULTED`, `fault_count` rises by one,
        and `last_fault_code` is set to the submitted code."

        Design: Corner/state_machines/fault_report_on_an_already_faulted_meter_is_rejected
        """
        base = build_chain_b(
            panel, dma_rank=128, target_households=2, base_incentive_cents=1000, persons_count=2
        )
        faulted = validate_success(
            panel.client.report_meter_fault(panel.tech, base["tuner"]["id"], fault_code="NO_SIGNAL"),
            200,
        )
        assert faulted["health_status"] == "FAULTED"

        validate_error(
            panel.client.report_meter_fault(panel.tech, base["tuner"]["id"], fault_code="TAMPER"),
            "ERR_METER_ALREADY_FAULTED",
        )
        after = panel.read_meter(base["tuner"]["id"])
        assert after["fault_count"] == 1
        assert after["last_fault_code"] == "NO_SIGNAL"
        assert after["install_status"] == "INSTALLED"

    def test_rejected_second_fault_report_leaves_one_hold_and_one_eviction(
        self, panel: PanelHarness
    ):
        """One fault, one hold: the refused report cascades nothing.

        PRD 3.3: "When both hold and the household is `ACTIVE`, the household
        moves to `FAULT_HOLD`."

        PRD 3.3: "**Link 3**: the household's quota cell has `intab_count` reduced
        by one and the fill calculation re-grades the cell."

        Design: Corner/state_machines/fault_report_on_an_already_faulted_meter_is_rejected
        """
        base = build_chain_b(
            panel, dma_rank=128, target_households=2, base_incentive_cents=1000, persons_count=2
        )
        validate_success(
            panel.client.report_meter_fault(panel.tech, base["tuner"]["id"], fault_code="NO_SIGNAL"),
            200,
        )
        validate_error(
            panel.client.report_meter_fault(panel.tech, base["tuner"]["id"], fault_code="TAMPER"),
            "ERR_METER_ALREADY_FAULTED",
        )

        assert panel.read_household(base["household"]["id"])["status"] == "FAULT_HOLD"
        assert panel.read_quota_cell(base["cell"]["id"])["intab_count"] == 0

    def test_repair_of_a_healthy_meter_is_refused(self, panel: PanelHarness):
        """Repair is undefined on a HEALTHY device, so it cannot force a home in tab.

        PRD 3.3: "The device's `health_status` must be `FAULTED` or `SUSPECT` and
        its `install_status` must not be `REMOVED`, otherwise
        `ERR_METER_NOT_FAULTED` — a healthy device has nothing to repair."

        Design: Corner/state_machines/repair_of_a_healthy_meter_is_rejected
        """
        base = build_chain_b(
            panel, dma_rank=129, target_households=2, base_incentive_cents=1000, persons_count=2
        )
        assert base["tuner"]["health_status"] == "HEALTHY"

        validate_error(
            panel.client.repair_meter(
                panel.tech, base["tuner"]["id"], repair_note="Preventive maintenance"
            ),
            "ERR_METER_NOT_FAULTED",
        )
        assert panel.read_quota_cell(base["cell"]["id"])["intab_count"] == 1
        after = panel.read_meter(base["tuner"]["id"])
        assert after["health_status"] == "HEALTHY"
        assert after["fault_count"] == 0

    def test_first_scan_drives_the_tuner_to_suspect_without_evicting_the_home(
        self, panel: PanelHarness
    ):
        """1040 missing minutes sit in [720, 1440), so the device is SUSPECT only.

        PRD 3.3: "The missing minutes are the run's `window_minutes` less the
        covered minutes, floored at 0 ... The suspect floor is the rule set's
        `fault_missing_minutes_threshold` divided by two and rounded half up to a
        whole number."

        PRD 3.3: "Missing minutes at or above the suspect floor but below the
        threshold drive `health_status` to `SUSPECT`".

        Design: Corner/state_machines/suspect_meter_escalates_to_faulted_on_a_later_scan
        """
        base = build_two_run_scan_fixture(panel, 130)

        scanned = validate_success(
            panel.client.detect_faults(panel.statistician, base["run_a"]["id"]), 200
        )
        assert scanned["state"] == "OPEN"

        meter = panel.read_meter(base["tuner"]["id"])
        assert meter["missing_minutes_last_scan"] == 1040
        assert meter["health_status"] == "SUSPECT"
        assert meter["fault_count"] == 0
        assert meter["last_fault_code"] is None

        household = panel.read_household(base["household"]["id"])
        assert household["status"] == "ACTIVE"
        assert household["compliance_rate_rolling_30"] == 1.0

    def test_second_scan_escalates_suspect_to_faulted(self, panel: PanelHarness):
        """A wholly uncovered 2880-minute window faults the already SUSPECT device.

        PRD 3.3: "Missing minutes at or above `fault_missing_minutes_threshold`
        drive `health_status` to `FAULTED` with `last_fault_code` set to
        `MISSING_INTERVALS` and `fault_count` raised by one".

        PRD 3.3: "The scan's `state` self-transition leaves the run in `OPEN` —
        nothing about the run itself moves".

        Design: Corner/state_machines/suspect_meter_escalates_to_faulted_on_a_later_scan
        """
        base = build_two_run_scan_fixture(panel, 130)
        validate_success(panel.client.detect_faults(panel.statistician, base["run_a"]["id"]), 200)
        assert panel.read_meter(base["tuner"]["id"])["health_status"] == "SUSPECT"

        rescanned = validate_success(
            panel.client.detect_faults(panel.statistician, base["run_b"]["id"]), 200
        )
        assert rescanned["state"] == "OPEN"

        meter = panel.read_meter(base["tuner"]["id"])
        assert meter["missing_minutes_last_scan"] == 2880
        assert meter["health_status"] == "FAULTED"
        assert meter["last_fault_code"] == "MISSING_INTERVALS"
        assert meter["fault_count"] == 1

    def test_only_the_faulted_escalation_cascades_into_the_household(self, panel: PanelHarness):
        """The FAULTED step, not the SUSPECT step, is what drops the home out of tab.

        PRD 3.3: "every meter it drives to `FAULTED` fires cascade links 2 through
        5 exactly as a hand-filed fault report would."

        PRD 3.3: "When both hold and the household is `ACTIVE`, the household
        moves to `FAULT_HOLD`."

        Design: Corner/state_machines/suspect_meter_escalates_to_faulted_on_a_later_scan
        """
        base = build_two_run_scan_fixture(panel, 130)
        validate_success(panel.client.detect_faults(panel.statistician, base["run_a"]["id"]), 200)
        assert panel.read_household(base["household"]["id"])["status"] == "ACTIVE"
        assert panel.read_quota_cell(base["cell"]["id"])["intab_count"] == 1

        validate_success(panel.client.detect_faults(panel.statistician, base["run_b"]["id"]), 200)

        household = panel.read_household(base["household"]["id"])
        assert household["status"] == "FAULT_HOLD"
        assert household["enumeration_verdict"] == "COMPLIANT"

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == 0.0

    def test_repair_out_of_suspect_returns_the_device_to_healthy(self, panel: PanelHarness):
        """SUSPECT -> HEALTHY clears the scan shortfall and never touches fault_count.

        PRD 3.3: "The repair sets `health_status` to `HEALTHY`, clears
        `last_fault_code` back to null and resets `missing_minutes_last_scan` to 0.
        What it does **not** do is undo `fault_count`, which is a lifetime counter
        and only ever rises."

        Design: Corner/state_machines/repair_of_a_suspect_meter_returns_it_to_healthy
        """
        base = build_two_run_scan_fixture(panel, 131)
        validate_success(panel.client.detect_faults(panel.statistician, base["run_a"]["id"]), 200)
        suspect = panel.read_meter(base["tuner"]["id"])
        assert suspect["health_status"] == "SUSPECT"
        assert suspect["missing_minutes_last_scan"] == 1040

        repaired = validate_success(
            panel.client.repair_meter(
                panel.tech,
                base["tuner"]["id"],
                repair_note="Replaced antenna feed; back-fill not possible",
            ),
            200,
        )
        assert repaired["health_status"] == "HEALTHY"
        assert repaired["missing_minutes_last_scan"] == 0
        assert repaired["fault_count"] == 0
        assert repaired["install_status"] == "INSTALLED"
        assert repaired["last_fault_code"] is None

    def test_repair_out_of_suspect_fires_no_household_cascade(self, panel: PanelHarness):
        """The home never left ACTIVE, so the repair's compensating cascade is skipped.

        PRD 3.3: "When the repaired device is a `TV_TUNER` with `install_status`
        `INSTALLED`, the household is in `FAULT_HOLD`, and the household's
        `enumeration_verdict` is still `COMPLIANT`, the household returns to
        `ACTIVE`, its cell's `intab_count` rises by one and the cell is re-graded".

        Design: Corner/state_machines/repair_of_a_suspect_meter_returns_it_to_healthy
        """
        base = build_two_run_scan_fixture(panel, 131)
        validate_success(panel.client.detect_faults(panel.statistician, base["run_a"]["id"]), 200)
        assert panel.read_household(base["household"]["id"])["status"] == "ACTIVE"

        validate_success(
            panel.client.repair_meter(
                panel.tech,
                base["tuner"]["id"],
                repair_note="Replaced antenna feed; back-fill not possible",
            ),
            200,
        )

        assert panel.read_household(base["household"]["id"])["status"] == "ACTIVE"
        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True


class TestProcessingRunLifecycle:
    """OPEN -> EDITED -> WEIGHTED -> PUBLISHED, plus the single repin loop."""

    def test_edit_pass_moves_the_open_run_to_edited(self, panel: PanelHarness):
        """The single claimed block survives every edit step and is tallied once.

        PRD 3.6: "The pass moves the run's `state` from `OPEN` to `EDITED` and
        creates **no** household weight rows — weighting is a separate act."

        PRD 3.6: "`contributing_household_count` is the number of distinct
        households whose `status` is `ACTIVE` and which still hold at least one
        record of this run in `state` `EDITED` or `ASCRIBED` with `usable_minutes`
        above 0".

        Design: Corner/state_machines/run_edit_weight_publish_happy_path
        """
        base = build_chain_c_open(panel, dma_rank=133)
        assert base["run"]["state"] == "OPEN"

        edited = validate_success(
            panel.client.edit_processing_run(panel.statistician, base["run"]["id"]), 200
        )
        assert edited["state"] == "EDITED"
        assert edited["contributing_household_count"] == 1
        assert edited["invalidated_interval_count"] == 0
        assert edited["ascribed_interval_count"] == 0
        assert edited["outlier_household_count"] == 0

    def test_weight_pass_projects_the_single_household(self, panel: PanelHarness):
        """EDITED -> WEIGHTED under FINAL yields a 100000 base weight and 24306 households.

        PRD 3.7: "Under `FINAL`, the denominator is the number of households of
        that cell that actually contributed at least one `EDITED` or `ASCRIBED`
        interval to **this** run with `usable_minutes` above 0."

        PRD 3.7: "each household's `contribution` is its `adjusted_weight`
        multiplied by its summed usable minutes and divided by the run's
        `window_minutes`, rounded half up to 2 decimal places. Second, the raw
        total is the sum of those **already-rounded** contributions. Third,
        `projected_average_audience` is that raw total rounded half up to a whole
        household count."

        Design: Corner/state_machines/run_edit_weight_publish_happy_path
        """
        base = build_chain_c_edited(panel, dma_rank=133)

        weighted = validate_success(
            panel.client.weight_processing_run(
                panel.statistician, base["run"]["id"], weight_variant="FINAL"
            ),
            200,
        )
        assert weighted["state"] == "WEIGHTED"
        assert weighted["weight_variant"] == "FINAL"
        assert weighted["total_weight_mass"] == 100000.0
        assert weighted["projected_average_audience"] == 24306

        rows, meta = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician, processing_run_id=base["run"]["id"]
            )
        )
        assert meta["total_count"] == 1
        row = rows[0]
        assert row["base_weight"] == 100000.0
        assert row["adjusted_weight"] == 100000.0
        assert row["capped"] is False
        assert row["usable_minutes"] == 350
        assert row["contribution"] == 24305.56
        assert row["run_compliance_rate"] == 1.0

    def test_publication_requires_and_stamps_a_second_statistician(self, panel: PanelHarness):
        """WEIGHTED -> PUBLISHED records the publisher next to the opener.

        PRD 3.7: "The run's `state` becomes `PUBLISHED`, which is terminal, and
        `published_by_user_id` is stamped from `X-User-ID`."

        PRD 3.7: "The market's current `limitation_disclosures` are appended to the
        run's own `limitation_disclosures`".

        Design: Corner/state_machines/run_edit_weight_publish_happy_path
        """
        base = build_chain_c_edited(panel, dma_rank=133)
        weighted = panel.weight_run(base["run"]["id"], weight_variant="FINAL")
        assert weighted["window_minutes"] == 1440

        published = validate_success(
            panel.client.publish_processing_run(panel.publisher, base["run"]["id"]), 200
        )
        assert published["state"] == "PUBLISHED"
        assert published["published_by_user_id"] == STATISTICIAN_PUBLISHER_USER_ID
        assert published["opened_by_user_id"] == STATISTICIAN_USER_ID
        assert published["window_minutes"] == 1440
        assert published["limitation_disclosures"] == []
        assert_instant(published["published_at"], CHAIN_C_CLOCK)

    def test_publication_starts_the_commercial_clock_on_a_pinned_deliverable(
        self, panel: PanelHarness
    ):
        """A SCHEDULED row pinned to an unpublished run has no due date until publication.

        PRD 3.7: "publication starts the commercial clock: every client deliverable
        already pinned to this run and standing in `SCHEDULED` becomes due, its
        `due_at` set to the current logical clock plus that client's
        `delivery_sla_hours`".

        PRD 3.8: "`STANDARD` sets `tier_base_fee_cents` to 65000,
        `delivery_sla_hours` to 72 and `custom_analysis_quota` to 3."

        Design: Corner/state_machines/run_edit_weight_publish_happy_path
        """
        base = build_chain_c_open(panel, dma_rank=133)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Riverbend Broadcasting", tier="STANDARD"
        )
        assert subscriber["delivery_sla_hours"] == 72
        deliverable = panel.schedule_deliverable(
            subscriber["id"], base["run"]["id"], requested_cell_count=1
        )
        assert deliverable["due_at"] is None

        panel.edit_run(base["run"]["id"])
        panel.weight_run(base["run"]["id"], weight_variant="FINAL")
        panel.publish_run(base["run"]["id"])

        after = panel.read_deliverable(deliverable["id"])
        assert after["state"] == "SCHEDULED"
        assert_instant(after["due_at"], "2026-08-14T00:00:00Z")

    def test_published_run_rejects_edit_and_fault_detection(self, panel: PanelHarness):
        """Both OPEN-only endpoints answer ERR_RUN_NOT_OPEN on a PUBLISHED run.

        PRD 3.6: "A `MethodologyStatistician` runs the edit pass against a run
        whose `state` is `OPEN`, otherwise `ERR_RUN_NOT_OPEN`".

        PRD 3.3: "the run's `state` must be `OPEN`, otherwise `ERR_RUN_NOT_OPEN`."

        Design: Corner/state_machines/published_run_rejects_edit_weight_publish_and_repin
        """
        base = build_chain_c_published(panel, dma_rank=134)
        assert base["run"]["state"] == "PUBLISHED"

        validate_error(
            panel.client.edit_processing_run(panel.statistician, base["run"]["id"]),
            "ERR_RUN_NOT_OPEN",
        )
        validate_error(
            panel.client.detect_faults(panel.statistician, base["run"]["id"]),
            "ERR_RUN_NOT_OPEN",
        )

    def test_published_run_rejects_reweighting_and_repinning(self, panel: PanelHarness):
        """PUBLISHED cannot be re-weighted with the other variant nor re-pinned.

        PRD 3.7: "The run's `state` must be `EDITED`, or it must be `WEIGHTED` with
        the submitted `weight_variant` **different** from the variant already
        applied, otherwise `ERR_RUN_NOT_EDITED`. A run in `OPEN`, `PENDING_REPIN`,
        `PUBLISHED` or `SUPERSEDED` cannot be weighted at all".

        PRD 3.7: "The run's `state` must be `PENDING_REPIN`, otherwise
        `ERR_RUN_NOT_PENDING_REPIN`."

        Design: Corner/state_machines/published_run_rejects_edit_weight_publish_and_repin
        """
        base = build_chain_c_published(panel, dma_rank=134)

        validate_error(
            panel.client.weight_processing_run(
                panel.statistician, base["run"]["id"], weight_variant="DESIGN"
            ),
            "ERR_RUN_NOT_EDITED",
        )
        validate_error(
            panel.client.repin_processing_run(panel.statistician, base["run"]["id"]),
            "ERR_RUN_NOT_PENDING_REPIN",
        )

    def test_published_run_state_check_outranks_segregation_of_duties(
        self, panel: PanelHarness
    ):
        """Republishing a PUBLISHED run reports the state gate at priority 42.

        PRD 3.7: "The run's `state` must be `WEIGHTED`, otherwise
        `ERR_RUN_NOT_WEIGHTED`. There is no route to publication that skips
        weighting."

        PRD 3.7: "The acting `X-User-ID` must differ from the run's
        `opened_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/published_run_rejects_edit_weight_publish_and_repin
        """
        base = build_chain_c_published(panel, dma_rank=134)

        third = make_statistician_headers(user_id=STATISTICIAN_THIRD_USER_ID)
        validate_error(
            panel.client.publish_processing_run(third, base["run"]["id"]),
            "ERR_RUN_NOT_WEIGHTED",
        )
        # The state check is check 2 and the segregation-of-duties check is
        # check 4, so the opener - who violates both - still sees the state gate.
        validate_error(
            panel.client.publish_processing_run(panel.statistician, base["run"]["id"]),
            "ERR_RUN_NOT_WEIGHTED",
        )

        after = panel.read_run(base["run"]["id"])
        assert after["state"] == "PUBLISHED"
        assert after["projected_average_audience"] == 24306
        assert after["weight_variant"] == "FINAL"


def build_universe_supersede_fixture(panel: PanelHarness):
    """An EDITED run plus a BASIC subscriber, and a DRAFT 2026Q4 vintage ready to publish.

    The clock is moved to 2026-08-30T00:00:00Z, 29 whole days after the 2026Q3
    vintage was published, so the 28-day floor of PRD 3.5 is satisfied.
    """
    base = build_chain_c_edited(panel, dma_rank=135)
    subscriber = panel.create_client(
        [base["market"]["id"]], name="Lakeshore Cable", tier="BASIC"
    )
    deliverable = panel.schedule_deliverable(
        subscriber["id"], base["run"]["id"], requested_cell_count=0
    )
    panel.set_clock("2026-08-30T00:00:00Z")
    next_vintage = panel.draft_universe(
        base["market"]["id"],
        [base["cell"]["id"]],
        vintage_label="2026Q4",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        cell_populations=[
            cell_population(
                base["cell"]["id"], population_households=120000, population_persons=300000
            )
        ],
    )
    base.update(
        {"subscriber": subscriber, "deliverable": deliverable, "next_vintage": next_vintage}
    )
    return base


class TestUniverseSupersessionAndRepin:
    """The universe-driven repin cascade and the compensating repin undo."""

    def test_publishing_a_newer_vintage_pends_the_edited_run(self, panel: PanelHarness):
        """The older vintage is superseded and its non-terminal run is pulled back.

        PRD 3.5: "every other universe estimate of the same market whose `status`
        is `PUBLISHED` and whose `effective_from` is earlier than this estimate's
        `effective_from` moves to `SUPERSEDED` with `superseded_at` stamped."

        PRD 3.5: "every processing run of that market still pinned to a
        now-superseded estimate and standing in `OPEN`, `EDITED` or `WEIGHTED` is
        forced to `PENDING_REPIN` with `repin_required_reason`
        `UNIVERSE_SUPERSEDED`".

        Design: Corner/state_machines/universe_supersede_pends_the_repin_and_repin_restores_raw_intervals
        """
        base = build_universe_supersede_fixture(panel)

        published = validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, base["next_vintage"]["id"]
            ),
            200,
        )
        assert published["status"] == "PUBLISHED"

        old = panel.read_universe(base["universe"]["id"])
        assert old["status"] == "SUPERSEDED"
        assert_instant(old["superseded_at"], "2026-08-30T00:00:00Z")

        run = panel.read_run(base["run"]["id"])
        assert run["state"] == "PENDING_REPIN"
        assert run["repin_required_reason"] == "UNIVERSE_SUPERSEDED"

    def test_the_cascade_holds_the_deliverable_and_blocks_its_release(
        self, panel: PanelHarness
    ):
        """A held row whose run is PENDING_REPIN cannot be released from the commercial side.

        PRD 3.5: "every client deliverable of one of those runs standing in a
        non-terminal state is moved to `HELD` with `hold_reason`
        `UPSTREAM_RUN_REPIN`."

        PRD 3.8: "The hold records `held_from_state` as the state the row occupied
        immediately before the hold, sets `state` to `HELD`, and raises the client's
        `held_deliverable_count` by one."

        PRD 3.8: "The pinned run's `state` must be `PUBLISHED`, otherwise
        `ERR_RUN_NOT_PUBLISHED` — a run still in `PENDING_REPIN` blocks release,
        which is the whole point of the upstream hold".

        Design: Corner/state_machines/universe_supersede_pends_the_repin_and_repin_restores_raw_intervals
        """
        base = build_universe_supersede_fixture(panel)
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, base["next_vintage"]["id"]
            ),
            200,
        )

        held = panel.read_deliverable(base["deliverable"]["id"])
        assert held["state"] == "HELD"
        assert held["hold_reason"] == "UPSTREAM_RUN_REPIN"
        assert held["held_from_state"] == "SCHEDULED"
        assert panel.read_client(base["subscriber"]["id"])["held_deliverable_count"] == 1

        validate_error(
            panel.client.release_deliverable(panel.rep, base["deliverable"]["id"]),
            "ERR_RUN_NOT_PUBLISHED",
        )

    def test_repin_returns_the_run_to_open_and_every_interval_to_raw(
        self, panel: PanelHarness
    ):
        """PENDING_REPIN -> OPEN throws away every downstream artefact.

        PRD 3.7: "Re-pinning returns the run to `OPEN` and clears
        `repin_required_reason` to null, and it deliberately throws away every
        downstream artefact so that the new rules see untouched data: every tuning
        interval whose `processing_run_id` is this run returns to `state` `RAW` with
        `processing_run_id` null, `usable_minutes` 0 and `invalidation_reason` null".

        PRD 3.7: "A run forced to `PENDING_REPIN` by an upstream supersession is
        repaired by a `MethodologyStatistician` supplying a new
        `universe_estimate_id`, a new `edit_rule_set_id`, or both; an omitted pin is
        left as it was."

        Design: Corner/state_machines/universe_supersede_pends_the_repin_and_repin_restores_raw_intervals
        """
        base = build_universe_supersede_fixture(panel)
        claimed = panel.read_interval(base["interval"]["id"])
        assert claimed["usable_minutes"] == 350
        assert claimed["processing_run_id"] == base["run"]["id"]
        validate_success(
            panel.client.publish_universe_estimate(
                panel.statistician, base["next_vintage"]["id"]
            ),
            200,
        )

        repinned = validate_success(
            panel.client.repin_processing_run(
                panel.statistician,
                base["run"]["id"],
                universe_estimate_id=base["next_vintage"]["id"],
            ),
            200,
        )
        assert repinned["state"] == "OPEN"
        assert repinned["repin_required_reason"] is None
        assert repinned["universe_estimate_id"] == base["next_vintage"]["id"]
        assert repinned["edit_rule_set_id"] == base["rule_set"]["id"]
        assert repinned["contributing_household_count"] == 0
        assert repinned["invalidated_interval_count"] == 0
        assert repinned["ascribed_interval_count"] == 0
        assert repinned["total_weight_mass"] == 0
        assert repinned["projected_average_audience"] is None
        assert repinned["limitation_disclosures"] == []

        interval = panel.read_interval(base["interval"]["id"])
        assert interval["state"] == "RAW"
        assert interval["processing_run_id"] is None
        assert interval["usable_minutes"] == 0
        assert interval["invalidation_reason"] is None

        # Re-pinning is a run-side repair and never releases a commercial hold.
        assert panel.read_deliverable(base["deliverable"]["id"])["state"] == "HELD"


class TestScheduledDatasetDispatch:
    """Branch A: SCHEDULED straight to DELIVERED, and DELIVERED is then terminal."""

    def test_dispatch_delivers_without_an_analyst_narrative(self, panel: PanelHarness):
        """A PREMIUM row created after publication is due in 24 hours and dispatches at once.

        PRD 3.8: "A `ClientServiceRep` dispatches a scheduled dataset straight from
        `SCHEDULED` to `DELIVERED`, skipping the analyst step entirely."

        PRD 3.8: "The billing calculation runs, `delivered_at` is stamped from the
        clock, and `findings_summary` stays null — a dispatched dataset never
        carries an analyst narrative."

        Design: Corner/state_machines/scheduled_dataset_dispatch_delivers_and_then_locks_down
        """
        base = build_chain_c_published(panel, dma_rank=136)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Summit Advertising", tier="PREMIUM"
        )
        assert subscriber["tier_base_fee_cents"] == 120000
        assert subscriber["delivery_sla_hours"] == 24
        row = panel.schedule_deliverable(
            subscriber["id"], base["run"]["id"], requested_cell_count=0
        )
        assert row["kind"] == "SCHEDULED_DATASET"
        assert row["question"] is None
        assert_instant(row["due_at"], "2026-08-12T00:00:00Z")
        panel.set_clock("2026-08-11T12:00:00Z")

        delivered = validate_success(
            panel.client.dispatch_deliverable(panel.rep, row["id"]), 200
        )
        assert delivered["state"] == "DELIVERED"
        assert_instant(delivered["delivered_at"], "2026-08-11T12:00:00Z")
        assert delivered["findings_summary"] is None

    def test_dispatch_prices_the_item_through_the_seven_billing_steps(
        self, panel: PanelHarness
    ):
        """120000 gross lands in the 0.10 discount bracket and is not yet late.

        PRD 3.8: "`gross_cents` is the client's `tier_base_fee_cents` plus
        `requested_cell_count` multiplied by the per-cell surcharge of 5000 cents."

        PRD 3.8: "The volume discount rate is 0.00 when `gross_cents` is below
        80000, 0.10 when it is at least 80000 but below 150000, and 0.15 when it is
        150000 or more."

        PRD 3.8: "`total_cents` is `gross_cents` less `discount_cents` less
        `late_penalty_cents`, floored at 0."

        Design: Corner/state_machines/scheduled_dataset_dispatch_delivers_and_then_locks_down
        """
        base = build_chain_c_published(panel, dma_rank=136)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Summit Advertising", tier="PREMIUM"
        )
        row = panel.schedule_deliverable(
            subscriber["id"], base["run"]["id"], requested_cell_count=0
        )
        panel.set_clock("2026-08-11T12:00:00Z")

        delivered = validate_success(
            panel.client.dispatch_deliverable(panel.rep, row["id"]), 200
        )
        assert delivered["gross_cents"] == 120000
        assert delivered["days_late"] == 0
        assert delivered["discount_cents"] == 12000
        assert delivered["late_penalty_cents"] == 0
        assert delivered["total_cents"] == 108000

    def test_delivered_dataset_refuses_a_second_dispatch_and_any_revision(
        self, panel: PanelHarness
    ):
        """DELIVERED is terminal for a SCHEDULED_DATASET on both surfaces.

        PRD 3.8: "the row's `state` must be `SCHEDULED` with `kind`
        `SCHEDULED_DATASET`, otherwise `ERR_DELIVERABLE_NOT_DELIVERABLE`."

        PRD 3.8: "The row's `state` must be `DELIVERED`, its `kind` must be
        `CUSTOM_ANALYSIS`, and its `revision_count` must be below the limit of 2,
        otherwise `ERR_REVISION_LIMIT_REACHED`."

        Design: Corner/state_machines/scheduled_dataset_dispatch_delivers_and_then_locks_down
        """
        base = build_chain_c_published(panel, dma_rank=136)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Summit Advertising", tier="PREMIUM"
        )
        row = panel.schedule_deliverable(
            subscriber["id"], base["run"]["id"], requested_cell_count=0
        )
        panel.set_clock("2026-08-11T12:00:00Z")
        validate_success(panel.client.dispatch_deliverable(panel.rep, row["id"]), 200)

        validate_error(
            panel.client.dispatch_deliverable(panel.rep, row["id"]),
            "ERR_DELIVERABLE_NOT_DELIVERABLE",
        )
        validate_error(
            panel.client.request_deliverable_revision(
                panel.client_headers(subscriber["id"]),
                row["id"],
                reason="Please add the 55+ break",
            ),
            "ERR_REVISION_LIMIT_REACHED",
        )
        after = panel.read_deliverable(row["id"])
        assert after["state"] == "DELIVERED"
        assert after["revision_count"] == 0
        # The 5-percent held credit accrues only to an UPSTREAM_RUN_REPIN hold,
        # and delivery added only the (zero) late penalty.
        assert panel.read_client(subscriber["id"])["delivery_sla_credit_cents"] == 0


class TestCustomAnalysisRevisionCycle:
    """Branch B and its one legal revision loop back into IN_PROGRESS."""

    def test_analyst_path_walks_requested_to_in_progress_to_delivered(
        self, panel: PanelHarness
    ):
        """A STANDARD custom analysis of 2 cells prices at 75000 with no discount.

        PRD 3.8: "The row is created with `kind` `CUSTOM_ANALYSIS` and `state`
        `REQUESTED` — not the machine's declared initial state — its `due_at` set to
        the logical clock plus the client's `delivery_sla_hours`".

        PRD 3.8: "A `ClientServiceRep` starts a custom analysis, moving it from
        `REQUESTED` or `REVISION_REQUESTED` to `IN_PROGRESS`".

        Design: Corner/state_machines/custom_analysis_revision_cycle_returns_to_in_progress
        """
        base = build_chain_c_published(panel, dma_rank=137)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Harborview Analytics", tier="STANDARD"
        )
        row = validate_success(
            panel.client.create_custom_analysis(
                panel.rep,
                client_id=subscriber["id"],
                processing_run_id=base["run"]["id"],
                question="Average audience for P18-34 by daypart",
                requested_cell_count=2,
            ),
            201,
        )
        assert row["kind"] == "CUSTOM_ANALYSIS"
        assert row["state"] == "REQUESTED"
        assert row["revision_count"] == 0
        assert_instant(row["due_at"], "2026-08-14T00:00:00Z")

        started = validate_success(panel.client.start_deliverable(panel.rep, row["id"]), 200)
        assert started["state"] == "IN_PROGRESS"

        delivered = validate_success(
            panel.client.deliver_deliverable(
                panel.rep, row["id"], findings_summary="P18-34 average audience 24306 households"
            ),
            200,
        )
        assert delivered["state"] == "DELIVERED"
        assert_instant(delivered["delivered_at"], CHAIN_C_CLOCK)
        assert delivered["gross_cents"] == 75000
        assert delivered["discount_cents"] == 0
        assert delivered["days_late"] == 0
        assert delivered["late_penalty_cents"] == 0
        assert delivered["total_cents"] == 75000

    def test_revision_request_unprices_the_item_and_counts_one_revision(
        self, panel: PanelHarness
    ):
        """DELIVERED -> REVISION_REQUESTED clears the delivery and its billing.

        PRD 3.8: "The row returns to `REVISION_REQUESTED`, `revision_count` rises by
        one, `delivered_at` is cleared to null and `gross_cents`, `discount_cents`,
        `late_penalty_cents` and `total_cents` are reset to 0 — the item is unpriced
        until it is delivered again."

        Design: Corner/state_machines/custom_analysis_revision_cycle_returns_to_in_progress
        """
        base = build_chain_c_published(panel, dma_rank=137)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Harborview Analytics", tier="STANDARD"
        )
        row = panel.delivered_custom_analysis(
            subscriber["id"],
            base["run"]["id"],
            question="Average audience for P18-34 by daypart",
            requested_cell_count=2,
        )
        assert row["total_cents"] == 75000

        revised = validate_success(
            panel.client.request_deliverable_revision(
                panel.client_headers(subscriber["id"]),
                row["id"],
                reason="Split the estimate by daypart",
            ),
            200,
        )
        assert revised["state"] == "REVISION_REQUESTED"
        assert revised["revision_count"] == 1
        assert revised["delivered_at"] is None
        assert revised["gross_cents"] == 0
        assert revised["discount_cents"] == 0
        assert revised["late_penalty_cents"] == 0
        assert revised["total_cents"] == 0

    def test_the_loop_reprices_on_redelivery_without_recharging_the_quota(
        self, panel: PanelHarness
    ):
        """REVISION_REQUESTED -> IN_PROGRESS -> DELIVERED repriced two days late.

        PRD 3.8: "`days_late` is the elapsed time from the row's `due_at` to the
        current logical clock, divided by 86400 seconds, rounded **up** to a whole
        day and floored at 0."

        PRD 3.8: "The penalty rate is 0.000 when `gross_cents` is below 80000".

        PRD 3.8: "That counter is never given back, not by a revision, not by a hold
        and not by a tier change."

        Design: Corner/state_machines/custom_analysis_revision_cycle_returns_to_in_progress
        """
        base = build_chain_c_published(panel, dma_rank=137)
        subscriber = panel.create_client(
            [base["market"]["id"]], name="Harborview Analytics", tier="STANDARD"
        )
        row = panel.delivered_custom_analysis(
            subscriber["id"],
            base["run"]["id"],
            question="Average audience for P18-34 by daypart",
            requested_cell_count=2,
        )
        validate_success(
            panel.client.request_deliverable_revision(
                panel.client_headers(subscriber["id"]),
                row["id"],
                reason="Split the estimate by daypart",
            ),
            200,
        )

        restarted = validate_success(panel.client.start_deliverable(panel.rep, row["id"]), 200)
        assert restarted["state"] == "IN_PROGRESS"
        assert restarted["revision_count"] == 1

        panel.set_clock("2026-08-16T00:00:00Z")
        redelivered = validate_success(
            panel.client.deliver_deliverable(
                panel.rep, row["id"], findings_summary="Daypart split appended"
            ),
            200,
        )
        assert redelivered["state"] == "DELIVERED"
        assert_instant(redelivered["delivered_at"], "2026-08-16T00:00:00Z")
        assert redelivered["days_late"] == 2
        assert redelivered["gross_cents"] == 75000
        assert redelivered["late_penalty_cents"] == 0
        assert redelivered["total_cents"] == 75000

        after = panel.read_client(subscriber["id"])
        assert after["custom_analysis_used"] == 1
        assert after["delivery_sla_credit_cents"] == 0


def build_held_deliverable_fixture(panel: PanelHarness, dma_rank: int, tier: str = "STANDARD"):
    """A PUBLISHED run plus one SCHEDULED dataset row of a subscriber of that market."""
    base = build_chain_c_published(panel, dma_rank=dma_rank)
    subscriber = panel.create_client([base["market"]["id"]], name="Cedar Park Media", tier=tier)
    row = panel.schedule_deliverable(subscriber["id"], base["run"]["id"], requested_cell_count=1)
    base.update({"subscriber": subscriber, "deliverable": row})
    return base


class TestDeliverableHoldAndRelease:
    """held_from_state is what makes a hold reversible, and only once."""

    def test_manual_hold_cannot_borrow_the_cascade_reason(self, panel: PanelHarness):
        """UPSTREAM_RUN_REPIN is reserved to the system, so the shape check refuses it.

        PRD 3.8: "Supplying `UPSTREAM_RUN_REPIN` by hand is refused with
        `ERR_INVALID_REQUEST`, that reason being reserved for the system cascade; the
        shape check precedes the state check."

        Design: Corner/state_machines/deliverable_hold_and_release_round_trip_restores_held_from_state
        """
        base = build_held_deliverable_fixture(panel, 138)

        validate_error(
            panel.client.hold_deliverable(
                panel.rep, base["deliverable"]["id"], hold_reason="UPSTREAM_RUN_REPIN"
            ),
            "ERR_INVALID_REQUEST",
        )
        after = panel.read_deliverable(base["deliverable"]["id"])
        assert after["state"] == "SCHEDULED"
        assert after["hold_reason"] is None
        assert panel.read_client(base["subscriber"]["id"])["held_deliverable_count"] == 0

    def test_hold_and_release_round_trip_restores_the_recorded_state(
        self, panel: PanelHarness
    ):
        """SCHEDULED -> HELD -> SCHEDULED, driven entirely by held_from_state.

        PRD 3.8: "The hold records `held_from_state` as the state the row occupied
        immediately before the hold, sets `state` to `HELD`, and raises the client's
        `held_deliverable_count` by one."

        PRD 3.8: "Releasing a hold restores exactly `held_from_state` ... On release,
        `held_from_state` and `hold_reason` are cleared to null and the client's
        `held_deliverable_count` falls by one."

        Design: Corner/state_machines/deliverable_hold_and_release_round_trip_restores_held_from_state
        """
        base = build_held_deliverable_fixture(panel, 138)

        held = validate_success(
            panel.client.hold_deliverable(
                panel.rep, base["deliverable"]["id"], hold_reason="DATA_QUALITY_REVIEW"
            ),
            200,
        )
        assert held["state"] == "HELD"
        assert held["held_from_state"] == "SCHEDULED"
        assert held["hold_reason"] == "DATA_QUALITY_REVIEW"
        assert panel.read_client(base["subscriber"]["id"])["held_deliverable_count"] == 1

        released = validate_success(
            panel.client.release_deliverable(panel.rep, base["deliverable"]["id"]), 200
        )
        assert released["state"] == "SCHEDULED"
        assert released["held_from_state"] is None
        assert released["hold_reason"] is None

    def test_second_release_is_refused_and_the_counter_never_goes_negative(
        self, panel: PanelHarness
    ):
        """The counter round-trips to zero and the refused release does not push it to -1.

        PRD 3.8: "the row's `state` must be `HELD`, otherwise
        `ERR_DELIVERABLE_NOT_HELD`."

        Design: Corner/state_machines/deliverable_hold_and_release_round_trip_restores_held_from_state
        """
        base = build_held_deliverable_fixture(panel, 138)
        validate_success(
            panel.client.hold_deliverable(
                panel.rep, base["deliverable"]["id"], hold_reason="DATA_QUALITY_REVIEW"
            ),
            200,
        )
        validate_success(
            panel.client.release_deliverable(panel.rep, base["deliverable"]["id"]), 200
        )

        validate_error(
            panel.client.release_deliverable(panel.rep, base["deliverable"]["id"]),
            "ERR_DELIVERABLE_NOT_HELD",
        )
        assert panel.read_client(base["subscriber"]["id"])["held_deliverable_count"] == 0


def build_suspension_fixture(panel: PanelHarness, dma_rank: int = 139):
    """CHAIN C complete plus a STANDARD client holding two open deliverables.

    The dataset row lands in `SCHEDULED` and the custom analysis in
    `REQUESTED`, so the suspension fan-out has two distinct
    `held_from_state` values to record.
    """
    base = build_chain_c_published(panel, dma_rank=dma_rank)
    subscriber = panel.create_client(
        [base["market"]["id"]], name="Great Plains Networks", tier="STANDARD"
    )
    dataset = panel.schedule_deliverable(
        subscriber["id"], base["run"]["id"], requested_cell_count=1
    )
    analysis = panel.request_custom_analysis(
        subscriber["id"],
        base["run"]["id"],
        question="Share of viewing by income band",
        requested_cell_count=3,
    )
    base.update({"subscriber": subscriber, "dataset": dataset, "analysis": analysis})
    return base


class TestClientSuspension:
    """Suspension fans out over open deliverables; reinstatement is not its inverse."""

    def test_suspension_holds_both_open_rows_recording_each_held_from_state(
        self, panel: PanelHarness
    ):
        """One suspension holds the SCHEDULED and the REQUESTED row, each remembering its own state.

        PRD 3.8: "The client's `status` becomes `SUSPENDED` and every deliverable it
        owns standing in `SCHEDULED`, `REQUESTED`, `IN_PROGRESS` or
        `REVISION_REQUESTED` moves to `HELD` with `hold_reason` `CLIENT_REQUESTED`
        and `held_from_state` recording exactly where it stood;
        `held_deliverable_count` is set to the number of holds now standing."

        PRD 3.8: "A service-level credit of 5 percent of the client's
        `tier_base_fee_cents`, rounded to a whole cent, is added to
        `delivery_sla_credit_cents` **only** when the `hold_reason` is
        `UPSTREAM_RUN_REPIN`".

        Design: Corner/state_machines/client_suspension_holds_every_open_deliverable_and_reinstate_does_not_release
        """
        base = build_suspension_fixture(panel, 139)

        suspended = validate_success(
            panel.client.suspend_client(
                panel.rep, base["subscriber"]["id"], suspended_reason="Invoice 90 days past due"
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspended_reason"] == "Invoice 90 days past due"
        assert suspended["held_deliverable_count"] == 2
        assert suspended["delivery_sla_credit_cents"] == 0

        rows, meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, client_id=base["subscriber"]["id"], state="HELD"
            )
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        dataset = by_id[base["dataset"]["id"]]
        analysis = by_id[base["analysis"]["id"]]
        assert dataset["state"] == "HELD"
        assert dataset["held_from_state"] == "SCHEDULED"
        assert dataset["hold_reason"] == "CLIENT_REQUESTED"
        assert analysis["state"] == "HELD"
        assert analysis["held_from_state"] == "REQUESTED"
        assert analysis["hold_reason"] == "CLIENT_REQUESTED"

    def test_suspended_client_cannot_file_another_custom_analysis(self, panel: PanelHarness):
        """The suspension check is the first of the four and the quota is never charged.

        PRD 3.8: "Four checks run in this order: the client must not be `SUSPENDED`
        (`ERR_CLIENT_SUSPENDED`)".

        PRD 3.8: "That counter is never given back, not by a revision, not by a hold
        and not by a tier change."

        Design: Corner/state_machines/client_suspension_holds_every_open_deliverable_and_reinstate_does_not_release
        """
        base = build_suspension_fixture(panel, 139)
        validate_success(
            panel.client.suspend_client(
                panel.rep, base["subscriber"]["id"], suspended_reason="Invoice 90 days past due"
            ),
            200,
        )

        validate_error(
            panel.client.create_custom_analysis(
                panel.rep,
                base["subscriber"]["id"],
                base["run"]["id"],
                question="One more cut",
                requested_cell_count=1,
            ),
            "ERR_CLIENT_SUSPENDED",
        )
        assert panel.read_client(base["subscriber"]["id"])["custom_analysis_used"] == 1

    def test_reinstatement_clears_the_status_but_leaves_every_hold_standing(
        self, panel: PanelHarness
    ):
        """Reinstatement restores ACTIVE and nothing else; only an explicit release decrements.

        PRD 3.8: "Reinstatement returns a client to `ACTIVE` and clears
        `suspended_reason`; the client's `status` must be `SUSPENDED`, otherwise
        `ERR_CLIENT_NOT_SUSPENDED`."

        PRD 3.8: "Reinstatement deliberately does **not** auto-release anything:
        `held_deliverable_count` is left exactly as it was and each hold must be
        released one at a time, so a reinstated client's backlog is reviewed item by
        item."

        Design: Corner/state_machines/client_suspension_holds_every_open_deliverable_and_reinstate_does_not_release
        """
        base = build_suspension_fixture(panel, 139)
        validate_success(
            panel.client.suspend_client(
                panel.rep, base["subscriber"]["id"], suspended_reason="Invoice 90 days past due"
            ),
            200,
        )

        reinstated = validate_success(
            panel.client.reinstate_client(panel.rep, base["subscriber"]["id"]), 200
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspended_reason"] is None
        assert reinstated["held_deliverable_count"] == 2

        validate_error(
            panel.client.reinstate_client(panel.rep, base["subscriber"]["id"]),
            "ERR_CLIENT_NOT_SUSPENDED",
        )

        released = validate_success(
            panel.client.release_deliverable(panel.rep, base["dataset"]["id"]), 200
        )
        assert released["state"] == "SCHEDULED"
        assert panel.read_client(base["subscriber"]["id"])["held_deliverable_count"] == 1


def build_notified_change_fixture(panel: PanelHarness, dma_rank: int = 140):
    """A NOTIFIED methodology change with exactly one notified subscriber.

    The proposed rule set differs from the published one in a single
    dimension - `missing_interval_ascription_minutes` 66 instead of 60 - so
    the cap and tuning sub-scores are 0, the ascription sub-score is
    min(1.0, 6/60) = 0.1 and `impact_delta_pct` is 0.25 * 0.1 = 0.0250.
    """
    base = build_chain_c_published(panel, dma_rank=dma_rank)
    subscriber = panel.create_client(
        [base["market"]["id"]], name="Blue Ridge Television", tier="STANDARD"
    )
    proposed = panel.draft_rule_set(
        **dict(CHAIN_C_RULE_SET, missing_interval_ascription_minutes=66)
    )
    change = panel.draft_change(
        base["rule_set"]["id"],
        proposed["id"],
        [base["market"]["id"]],
        title="Lengthen ascription window to 66 minutes",
    )
    assessed = panel.assess_change(change["id"], base["run"]["id"])
    notified = panel.notify_change(change["id"])
    rows, meta = validate_paginated(
        panel.client.list_client_notifications(
            panel.director, methodology_change_id=change["id"]
        )
    )
    base.update(
        {
            "subscriber": subscriber,
            "proposed": proposed,
            "change": change,
            "assessed": assessed,
            "notified": notified,
            "notifications": rows,
            "notifications_meta": meta,
        }
    )
    return base


class TestNotificationAcknowledgement:
    """SENT to ACKNOWLEDGED is a one-way door, and the notification freezes its own disclosure."""

    def test_notification_freezes_the_minor_tier_and_delta_at_send_time(
        self, panel: PanelHarness
    ):
        """A 6-minute ascription move scores 0.0250, lands MINOR, and is disclosed as sent.

        PRD 3.9: "the ascription sub-score is the absolute difference between their
        `missing_interval_ascription_minutes` divided by 60. `impact_delta_pct` is
        0.40 times the cap sub-score plus 0.35 times the tuning sub-score plus 0.25
        times the ascription sub-score, rounded half up to 4 decimal places."

        PRD 3.9: "The tier fixes the disclosure lead time in
        `notification_lead_hours` - 72 hours for `MINOR`, 336 hours for `MODERATE`
        and 720 hours for `MATERIAL`".

        PRD 3.9: "Each notification starts in `state` `SENT` with `sent_at` stamped,
        `acknowledged_at` null, and `impact_tier` and `disclosed_delta_pct` copied
        from the change at that instant - a frozen copy, so a later re-analysis does
        not silently rewrite what a client was told."

        Design: Corner/state_machines/acknowledged_notification_rejects_a_second_acknowledge
        """
        base = build_notified_change_fixture(panel, 140)

        assessed = base["assessed"]
        assert assessed["state"] == "IMPACT_ASSESSED"
        assert assessed["impact_delta_pct"] == 0.0250
        assert assessed["impact_tier"] == "MINOR"
        assert assessed["notification_lead_hours"] == 72
        assert assessed["baseline_projected_average_audience"] == 24306

        notified = base["notified"]
        assert notified["state"] == "NOTIFIED"
        assert notified["notified_client_count"] == 1
        assert notified["acknowledged_client_count"] == 0
        assert_instant(notified["notification_deadline_at"], "2026-08-14T00:00:00Z")

        assert base["notifications_meta"]["total_count"] == 1
        row = base["notifications"][0]
        assert row["client_id"] == base["subscriber"]["id"]
        assert row["state"] == "SENT"
        assert row["impact_tier"] == "MINOR"
        assert row["disclosed_delta_pct"] == 0.0250
        assert row["acknowledged_at"] is None
        assert_instant(row["sent_at"], CHAIN_C_CLOCK)

    def test_the_subscriber_acknowledges_its_own_row_and_is_counted_once(
        self, panel: PanelHarness
    ):
        """The acknowledgement stamps the row and lifts the change's counter to one.

        PRD 3.9: "The notification moves to `ACKNOWLEDGED` with `acknowledged_at`
        stamped, and the change's `acknowledged_client_count` rises by one."

        Design: Corner/state_machines/acknowledged_notification_rejects_a_second_acknowledge
        """
        base = build_notified_change_fixture(panel, 140)
        notification = base["notifications"][0]

        acknowledged = validate_success(
            panel.client.acknowledge_notification(
                panel.client_headers(base["subscriber"]["id"]), notification["id"]
            ),
            200,
        )
        assert acknowledged["state"] == "ACKNOWLEDGED"
        assert_instant(acknowledged["acknowledged_at"], CHAIN_C_CLOCK)
        assert panel.read_change(base["change"]["id"])["acknowledged_client_count"] == 1

    def test_second_acknowledge_is_refused_and_never_inflates_the_counter(
        self, panel: PanelHarness
    ):
        """ACKNOWLEDGED is terminal, so a client that clicks twice is still counted once.

        PRD 3.9: "The notification's `state` must be `SENT`, otherwise
        `ERR_NOTIFICATION_NOT_SENT` - an already-acknowledged or cancelled row cannot
        be acknowledged again".

        PRD 3.9: "`ACKNOWLEDGED` and `CANCELLED` are both terminal."

        Design: Corner/state_machines/acknowledged_notification_rejects_a_second_acknowledge
        """
        base = build_notified_change_fixture(panel, 140)
        notification = base["notifications"][0]
        headers = panel.client_headers(base["subscriber"]["id"])
        validate_success(panel.client.acknowledge_notification(headers, notification["id"]), 200)

        validate_error(
            panel.client.acknowledge_notification(headers, notification["id"]),
            "ERR_NOTIFICATION_NOT_SENT",
        )

        change = panel.read_change(base["change"]["id"])
        assert change["acknowledged_client_count"] == 1
        assert change["notified_client_count"] == 1
        assert change["state"] == "NOTIFIED"


def build_open_audit_fixture(panel: PanelHarness, dma_rank: int = 142):
    """CHAIN A plus a PUBLISHED rule set and one OPEN audit freezing the market."""
    market = panel.create_market(dma_rank=dma_rank, incentive_budget_cents=500000)
    cell = panel.create_quota_cell(market["id"], target_households=2, base_incentive_cents=1000)
    rule_set = panel.published_rule_set(**CHAIN_C_RULE_SET)
    audit = panel.open_audit(
        market["id"], rule_set["id"], auditor_note="Scheduled review of DMA-642 methodology"
    )
    return {"market": market, "cell": cell, "rule_set": rule_set, "audit": audit}


def build_second_audit_fixture(panel: PanelHarness, dma_rank: int = 143):
    """A market whose first audit already finalized QUALIFIED, with a second audit OPEN."""
    base = build_open_audit_fixture(panel, dma_rank=dma_rank)
    base["first_finalized"] = panel.finalize_audit(
        base["audit"]["id"],
        outcome="QUALIFIED",
        limitation_disclosures=["STREAMING_SDK_BETA"],
    )
    base["market_after_first"] = panel.read_market(base["market"]["id"])
    base["second_audit_response"] = panel.client.create_accreditation_audit(
        panel.auditor,
        market_id=base["market"]["id"],
        scope_edit_rule_set_id=base["rule_set"]["id"],
        auditor_note="Second review of DMA-643",
    )
    base["second_audit"] = validate_success(base["second_audit_response"], 201)
    return base


class TestAccreditationAudit:
    """OPEN to FINALIZED is one-shot; the outcome writes disjoint effects on the market."""

    def test_qualified_outcome_demands_at_least_one_disclosure(self, panel: PanelHarness):
        """An empty disclosure list is refused for QUALIFIED and leaves the freeze standing.

        PRD 3.9: "When the `outcome` is `QUALIFIED` or `DENIED`,
        `limitation_disclosures` must hold at least one element, otherwise
        `ERR_DISCLOSURE_REQUIRED`. A qualified or denied methodology must say what is
        wrong with it."

        PRD 3.9: "Opening it raises the market's `open_audit_count` by one, which
        fires the first clause of the posture calculation and drives
        `recruitment_posture` to `FROZEN` with `posture_changed_at` updated —
        overriding every cell-level consideration."

        Design: Corner/state_machines/audit_finalize_qualified_appends_disclosures_and_unfreezes_the_market
        """
        base = build_open_audit_fixture(panel, 142)

        validate_error(
            panel.client.finalize_accreditation_audit(
                panel.finalizer, base["audit"]["id"], outcome="QUALIFIED",
                limitation_disclosures=[],
            ),
            "ERR_DISCLOSURE_REQUIRED",
        )

        audit = panel.read_audit(base["audit"]["id"])
        assert audit["state"] == "OPEN"
        assert audit["outcome"] is None
        assert audit["finalized_by_user_id"] is None
        assert audit["finalized_at"] is None
        market = panel.read_market(base["market"]["id"])
        assert market["open_audit_count"] == 1
        assert market["recruitment_posture"] == "FROZEN"

    def test_qualified_finalize_stamps_the_second_auditor_and_stores_disclosures_in_order(
        self, panel: PanelHarness
    ):
        """The finalization is signed by an auditor other than the opener, in payload order.

        PRD 3.9: "In every case the audit moves to `FINALIZED` with `outcome` stored,
        `limitation_disclosures` stored in payload order, and `finalized_by_user_id`
        and `finalized_at` stamped".

        Design: Corner/state_machines/audit_finalize_qualified_appends_disclosures_and_unfreezes_the_market
        """
        base = build_open_audit_fixture(panel, 142)

        finalized = validate_success(
            panel.client.finalize_accreditation_audit(
                panel.finalizer,
                base["audit"]["id"],
                outcome="QUALIFIED",
                limitation_disclosures=["SMALL_CELL_SAMPLE", "OOH_COVERAGE_PARTIAL"],
            ),
            200,
        )
        assert finalized["state"] == "FINALIZED"
        assert finalized["outcome"] == "QUALIFIED"
        assert finalized["finalized_by_user_id"] == AUDITOR_FINALIZER_USER_ID
        assert finalized["finalized_by_user_id"] != base["audit"]["opened_by_user_id"]
        assert_instant(finalized["finalized_at"], CLOCK_T0)
        assert finalized["limitation_disclosures"] == [
            "SMALL_CELL_SAMPLE",
            "OOH_COVERAGE_PARTIAL",
        ]

    def test_qualified_finalize_unfreezes_the_market_and_appends_its_disclosures(
        self, panel: PanelHarness
    ):
        """QUALIFIED is the middle case: publication is allowed and the caveats stick.

        PRD 3.9: "the market's `accreditation_status` is set to the outcome; and the
        market's `open_audit_count` falls by one before the posture is re-evaluated,
        which releases `FROZEN` when no other audit of that market is open."

        PRD 3.9: "`QUALIFIED` sets `publication_blocked` to false and appends every
        element of the payload's `limitation_disclosures` onto the market's
        `limitation_disclosures` in payload order."

        Design: Corner/state_machines/audit_finalize_qualified_appends_disclosures_and_unfreezes_the_market
        """
        base = build_open_audit_fixture(panel, 142)
        panel.finalize_audit(
            base["audit"]["id"],
            outcome="QUALIFIED",
            limitation_disclosures=["SMALL_CELL_SAMPLE", "OOH_COVERAGE_PARTIAL"],
        )

        market = panel.read_market(base["market"]["id"])
        assert market["accreditation_status"] == "QUALIFIED"
        assert market["publication_blocked"] is False
        assert market["open_audit_count"] == 0
        assert market["limitation_disclosures"] == [
            "SMALL_CELL_SAMPLE",
            "OOH_COVERAGE_PARTIAL",
        ]
        assert market["recruitment_posture"] == "OPEN"
        assert_instant(market["posture_changed_at"], CLOCK_T0)

    def test_a_second_audit_is_allowed_once_the_first_is_finalized_and_refreezes_the_market(
        self, panel: PanelHarness
    ):
        """The "one OPEN audit" rule bars concurrency, not succession.

        PRD 3.9: "and the market must not already hold an audit in `state` `OPEN`,
        otherwise `ERR_AUDIT_ALREADY_OPEN`."

        PRD 3.9: "Opening it raises the market's `open_audit_count` by one, which
        fires the first clause of the posture calculation and drives
        `recruitment_posture` to `FROZEN` with `posture_changed_at` updated —
        overriding every cell-level consideration."

        Design: Corner/state_machines/second_open_audit_and_second_finalize_are_rejected
        """
        base = build_second_audit_fixture(panel, 143)

        assert base["market_after_first"]["open_audit_count"] == 0
        assert base["market_after_first"]["recruitment_posture"] == "OPEN"
        assert base["second_audit"]["state"] == "OPEN"
        market = panel.read_market(base["market"]["id"])
        assert market["open_audit_count"] == 1
        assert market["recruitment_posture"] == "FROZEN"

    def test_a_third_audit_while_one_is_open_is_refused(self, panel: PanelHarness):
        """A market already holding an OPEN audit refuses another one and stays at one.

        PRD 3.9: "and the market must not already hold an audit in `state` `OPEN`,
        otherwise `ERR_AUDIT_ALREADY_OPEN`."

        Design: Corner/state_machines/second_open_audit_and_second_finalize_are_rejected
        """
        base = build_second_audit_fixture(panel, 143)

        validate_error(
            panel.client.create_accreditation_audit(
                panel.auditor,
                market_id=base["market"]["id"],
                scope_edit_rule_set_id=base["rule_set"]["id"],
                auditor_note="Third review while the second is open",
            ),
            "ERR_AUDIT_ALREADY_OPEN",
        )
        assert panel.read_market(base["market"]["id"])["open_audit_count"] == 1

    def test_a_finalized_audit_cannot_be_re_decided(self, panel: PanelHarness):
        """FINALIZED is terminal, so a signed-off audit cannot be turned into a denial.

        PRD 3.9: "The audit's `state` must be `OPEN`, otherwise `ERR_AUDIT_NOT_OPEN`.
        `FINALIZED` is terminal."

        Design: Corner/state_machines/second_open_audit_and_second_finalize_are_rejected
        """
        base = build_second_audit_fixture(panel, 143)
        finalized = validate_success(
            panel.client.finalize_accreditation_audit(
                panel.finalizer,
                base["second_audit"]["id"],
                outcome="ACCREDITED",
                limitation_disclosures=[],
            ),
            200,
        )
        assert finalized["state"] == "FINALIZED"
        assert finalized["outcome"] == "ACCREDITED"
        assert finalized["limitation_disclosures"] == []

        validate_error(
            panel.client.finalize_accreditation_audit(
                panel.finalizer,
                base["second_audit"]["id"],
                outcome="DENIED",
                limitation_disclosures=["ATTEMPTED_REOPEN"],
            ),
            "ERR_AUDIT_NOT_OPEN",
        )
        audit = panel.read_audit(base["second_audit"]["id"])
        assert audit["outcome"] == "ACCREDITED"
        assert audit["limitation_disclosures"] == []

    def test_accredited_outcome_never_erases_an_earlier_qualified_disclosure(
        self, panel: PanelHarness
    ):
        """A clean audit lowers nothing but the freeze: the recorded limitation survives it.

        PRD 3.9: "`ACCREDITED` sets `publication_blocked` to false and leaves the
        market's `limitation_disclosures` exactly as it was. A clean audit never
        erases a disclosure an earlier audit recorded."

        Design: Corner/state_machines/second_open_audit_and_second_finalize_are_rejected
        """
        base = build_second_audit_fixture(panel, 143)
        assert base["market_after_first"]["limitation_disclosures"] == ["STREAMING_SDK_BETA"]

        panel.finalize_audit(
            base["second_audit"]["id"], outcome="ACCREDITED", limitation_disclosures=[]
        )

        market = panel.read_market(base["market"]["id"])
        assert market["accreditation_status"] == "ACCREDITED"
        assert market["publication_blocked"] is False
        assert market["open_audit_count"] == 0
        assert market["recruitment_posture"] == "OPEN"
        assert market["limitation_disclosures"] == ["STREAMING_SDK_BETA"]


def build_two_vintage_fixture(panel: PanelHarness, dma_rank: int = 144):
    """A market with a PUBLISHED 2026Q1 vintage and a DRAFT 2026Q2 successor."""
    market = panel.create_market(dma_rank=dma_rank, incentive_budget_cents=500000)
    cell = panel.create_quota_cell(market["id"], target_households=1, base_incentive_cents=1000)
    live = panel.published_universe(
        market["id"],
        [cell["id"]],
        vintage_label="2026Q1",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
        cell_populations=[
            cell_population(cell["id"], population_households=90000, population_persons=220000)
        ],
    )
    successor = panel.draft_universe(
        market["id"],
        [cell["id"]],
        vintage_label="2026Q2",
        effective_from="2026-04-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
        cell_populations=[
            cell_population(cell["id"], population_households=95000, population_persons=230000)
        ],
    )
    return {"market": market, "cell": cell, "live": live, "successor": successor}


class TestUniverseAndRuleSetPublication:
    """DRAFT to PUBLISHED is one-shot for both methodology artefacts."""

    def test_an_already_published_vintage_cannot_be_published_again(self, panel: PanelHarness):
        """A republish of the live vintage is refused outright and changes nothing.

        PRD 3.5: "The estimate's `status` must be `DRAFT`, otherwise
        `ERR_UNIVERSE_NOT_DRAFT`."

        Design: Corner/state_machines/universe_republish_and_too_soon_publish_are_rejected
        """
        base = build_two_vintage_fixture(panel, 144)
        assert_instant(base["live"]["published_at"], CLOCK_T0)

        validate_error(
            panel.client.publish_universe_estimate(panel.statistician, base["live"]["id"]),
            "ERR_UNIVERSE_NOT_DRAFT",
        )

        live = panel.read_universe(base["live"]["id"])
        assert live["status"] == "PUBLISHED"
        assert_instant(live["published_at"], CLOCK_T0)
        assert live["superseded_at"] is None

    def test_twenty_seven_whole_days_after_the_live_vintage_is_too_soon(
        self, panel: PanelHarness
    ):
        """The 28-day floor is measured from the live vintage's published_at, and 27 fails.

        PRD 3.5: "At least 28 whole days must have elapsed between the currently
        published vintage's `published_at` and the logical clock at this call,
        otherwise `ERR_UNIVERSE_VINTAGE_TOO_SOON` — universe estimates are not
        allowed to churn."

        Design: Corner/state_machines/universe_republish_and_too_soon_publish_are_rejected
        """
        base = build_two_vintage_fixture(panel, 144)
        panel.set_clock("2026-08-28T00:00:00Z")

        validate_error(
            panel.client.publish_universe_estimate(panel.statistician, base["successor"]["id"]),
            "ERR_UNIVERSE_VINTAGE_TOO_SOON",
        )

        successor = panel.read_universe(base["successor"]["id"])
        assert successor["status"] == "DRAFT"
        assert successor["published_at"] is None
        assert panel.read_universe(base["live"]["id"])["status"] == "PUBLISHED"

    def test_exactly_twenty_eight_whole_days_clears_the_floor_and_supersedes_the_past(
        self, panel: PanelHarness
    ):
        """One more day carries the successor through, and the older vintage goes terminal.

        PRD 3.5: "Publication sets `status` to `PUBLISHED` with `published_at`
        stamped from the clock, and then supersedes the past: every other universe
        estimate of the same market whose `status` is `PUBLISHED` and whose
        `effective_from` is earlier than this estimate's `effective_from` moves to
        `SUPERSEDED` with `superseded_at` stamped. `SUPERSEDED` is terminal."

        Design: Corner/state_machines/universe_republish_and_too_soon_publish_are_rejected
        """
        base = build_two_vintage_fixture(panel, 144)
        panel.set_clock("2026-08-28T00:00:00Z")
        validate_error(
            panel.client.publish_universe_estimate(panel.statistician, base["successor"]["id"]),
            "ERR_UNIVERSE_VINTAGE_TOO_SOON",
        )
        panel.set_clock("2026-08-29T00:00:00Z")

        published = validate_success(
            panel.client.publish_universe_estimate(panel.statistician, base["successor"]["id"]),
            200,
        )
        assert published["status"] == "PUBLISHED"
        assert_instant(published["published_at"], "2026-08-29T00:00:00Z")

        live = panel.read_universe(base["live"]["id"])
        assert live["status"] == "SUPERSEDED"
        assert_instant(live["superseded_at"], "2026-08-29T00:00:00Z")
        _runs, runs_meta = validate_paginated(
            panel.client.list_processing_runs(panel.statistician, market_id=base["market"]["id"])
        )
        assert runs_meta["total_count"] == 0

    def test_minimum_legal_thresholds_are_accepted_and_publication_stamps_the_clock(
        self, panel: PanelHarness
    ):
        """Every threshold at its floor is a legal rule set, and publishing it stamps the clock.

        PRD 3.5: "`missing_interval_ascription_minutes`, the maximum gap in minutes
        between two consecutive same-meter intervals that the edit pass will fill
        with a synthetic record, at least 0 and at most 240; `invalid_tuning_max_minutes`,
        at least 1, above which a raw record is invalidated; `outlier_household_minutes_cap`,
        at least 1, above which a household's whole contribution is treated as an
        outlier; `outlier_weight_ratio_cap`, a number of at least 1.0000 held to 4
        decimal places".

        PRD 3.5: "A new rule set is `DRAFT` with `published_at` null."

        Design: Corner/state_machines/rule_set_republish_is_rejected
        """
        draft = validate_success(
            panel.client.create_edit_rule_set(
                panel.statistician,
                **edit_rule_set_payload(
                    label="RS-C45",
                    missing_interval_ascription_minutes=0,
                    invalid_tuning_max_minutes=1,
                    outlier_household_minutes_cap=1,
                    outlier_weight_ratio_cap=1.0000,
                    fault_missing_minutes_threshold=1,
                ),
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        assert draft["published_at"] is None

        published = validate_success(
            panel.client.publish_edit_rule_set(panel.statistician, draft["id"]), 200
        )
        assert published["status"] == "PUBLISHED"
        assert_instant(published["published_at"], CLOCK_T0)

    def test_republishing_a_published_rule_set_is_refused_and_keeps_the_first_stamp(
        self, panel: PanelHarness
    ):
        """A second publish is refused and the advanced clock never rewrites published_at.

        PRD 3.5: "The rule set's `status` must be `DRAFT`, otherwise
        `ERR_RULE_SET_NOT_DRAFT`."

        PRD 3.5: "Publication sets `status` to `PUBLISHED` with `published_at`
        stamped, moves the previously published rule set to `SUPERSEDED`".

        Design: Corner/state_machines/rule_set_republish_is_rejected
        """
        rule_set = panel.published_rule_set(
            label="RS-C45",
            missing_interval_ascription_minutes=0,
            invalid_tuning_max_minutes=1,
            outlier_household_minutes_cap=1,
            outlier_weight_ratio_cap=1.0000,
            fault_missing_minutes_threshold=1,
        )
        assert_instant(rule_set["published_at"], CLOCK_T0)
        panel.set_clock("2026-09-01T00:00:00Z")

        validate_error(
            panel.client.publish_edit_rule_set(panel.statistician, rule_set["id"]),
            "ERR_RULE_SET_NOT_DRAFT",
        )

        reread = panel.read_rule_set(rule_set["id"])
        assert reread["status"] == "PUBLISHED"
        assert_instant(reread["published_at"], CLOCK_T0)
