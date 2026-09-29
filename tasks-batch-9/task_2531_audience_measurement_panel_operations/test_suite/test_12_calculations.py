"""Arithmetic corners of the panel contract.

Every test in this file pins one named calculation of the PRD at a boundary
where a plausible-but-wrong implementation diverges: the enumeration due
window, the quota-cell fill grade and its 4-decimal rounding, the recruitment
posture ladder, the meter suspect floor, the seven-step editing pass, the
rolling compliance rate, the weight cap and the projection, the nine-step
incentive accrual, the seven-step deliverable billing, and the weighted
methodology impact score. Each asserted figure is recomputed from the PRD's
own named steps and rounding order and is also asserted as a concrete literal.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    expected_accrual_breakdown,
    expected_adjusted_weights,
    expected_billing,
    expected_boost_reservation,
    expected_cap,
    expected_compliance_rate,
    expected_contribution,
    expected_fill_rate,
    expected_impact_delta_pct,
    expected_impact_subscores,
    expected_impact_tier,
    expected_projected_average_audience,
    expected_suspect_floor,
    expected_tenure_multiplier,
    expected_usable_minutes,
    round_half_up,
    round_half_up_to_int,
)
from test_helpers.constants import (
    BOOSTED_MULTIPLIER,
    ENUMERATION_DUE_DAYS,
    INCENTIVE_PERIOD_CAP_CENTS,
    MIN_COMPLIANT_DAY_MINUTES,
    MINUTES_PER_DAY,
    NOTIFICATION_LEAD_HOURS,
    ON_TARGET_THRESHOLD,
    TIER_TABLE,
    UNBOOSTED_MULTIPLIER,
)
from test_helpers.factories import cell_population
from test_helpers.fixtures import (
    CLOCK_T1,
    WINDOW_END,
    WINDOW_MINUTES,
    WINDOW_START,
    PanelHarness,
)

# The measurement day every multi-interval recipe below uses. The clock is
# advanced to DAY_END first, because a block's `end_iso` and a run's
# `window_end_iso` must both be at or before the logical clock.
DAY_START = "2026-08-10T00:00:00Z"
DAY_END = "2026-08-11T00:00:00Z"


def _instant(value: str) -> str:
    """An ISO 8601 instant reduced to whole seconds, ignoring the fraction.

    PRD 2.5 renders business timestamps with three fractional digits, so a
    comparison against a supplied instant is made at second precision.
    """
    return value.replace("Z", "").split(".")[0]


class TestEnumerationVerdictArithmetic:
    """The three verdict predicates and the 14-day first-visit deadline."""

    def test_first_enumeration_at_exactly_fourteen_days_is_still_timely(
        self, panel: PanelHarness
    ):
        """A first visit 14 whole days after recruitment passes the timeliness test.

        PRD 3.2: "the household's age in whole days is the elapsed time from
        `recruited_at` to the current logical clock divided by 86400 seconds and
        floored to a whole number of days, and the test passes when that age is
        at most 14 days".

        Design: Corner/calculations/enumeration_due_window_at_exactly_fourteen_days_versus_fifteen
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 4, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        household = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        assert _instant(household["recruited_at"]) == "2026-08-01T00:00:00"
        panel.installed_meter(household["id"], meter_type="TV_TUNER")

        # 2026-08-15 minus 2026-08-01 is 1209600 seconds, so floor(1209600 / 86400)
        # is exactly 14 == ENUMERATION_DUE_DAYS and the <= comparison holds.
        panel.set_clock("2026-08-15T00:00:00Z")
        assert (1209600 // 86400) == ENUMERATION_DUE_DAYS

        after = panel.enumerate_household(
            household["id"], roster_persons_count=3, tv_sets_count=1
        )
        assert after["enumeration_verdict"] == "COMPLIANT"
        assert after["status"] == "ACTIVE"
        assert after["enumeration_count"] == 1
        assert _instant(after["last_enumeration_at"]) == "2026-08-15T00:00:00"

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 1
        assert graded["fill_rate"] == expected_fill_rate(1, 4) == 0.2500
        assert graded["quota_status"] == "UNDER_TARGET"
        assert graded["incentive_boost_active"] is True

    def test_first_enumeration_at_fifteen_days_fails_and_the_second_recovers(
        self, panel: PanelHarness
    ):
        """15 whole days is late, and the due-date term is dropped from visit two.

        PRD 3.2: "Every later submission passes the timeliness test
        unconditionally, because re-enumerations carry no due date."

        Design: Corner/calculations/enumeration_due_window_at_exactly_fourteen_days_versus_fifteen
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 4, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        timely = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        late = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        panel.installed_meter(timely["id"], meter_type="TV_TUNER")
        panel.installed_meter(late["id"], meter_type="TV_TUNER")

        panel.set_clock("2026-08-15T00:00:00Z")
        on_time = panel.enumerate_household(
            timely["id"], roster_persons_count=3, tv_sets_count=1
        )
        assert on_time["enumeration_verdict"] == "COMPLIANT"
        assert on_time["status"] == "ACTIVE"

        # floor(1296000 / 86400) == 15 > 14, so the first visit is late even
        # though the roster matches and a television set was found.
        panel.set_clock("2026-08-16T00:00:00Z")
        assert (1296000 // 86400) == 15
        first = panel.enumerate_household(
            late["id"], roster_persons_count=3, tv_sets_count=1
        )
        assert first["enumeration_verdict"] == "NONCOMPLIANT"
        assert first["status"] == "NONCOMPLIANT_HOLD"
        assert first["enumeration_count"] == 1
        assert _instant(first["last_enumeration_at"]) == "2026-08-16T00:00:00"
        assert panel.read_quota_cell(cell["id"])["intab_count"] == 1

        # The byte-identical payload now succeeds: this is submission 2.
        second = panel.enumerate_household(
            late["id"], roster_persons_count=3, tv_sets_count=1
        )
        assert second["enumeration_verdict"] == "COMPLIANT"
        assert second["status"] == "ACTIVE"
        assert second["enumeration_count"] == 2

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 2
        assert graded["fill_rate"] == expected_fill_rate(2, 4) == 0.5000
        assert graded["quota_status"] == "UNDER_TARGET"
        assert graded["incentive_boost_active"] is True

    def test_roster_test_is_equality_so_an_over_count_fails_like_an_under_count(
        self, panel: PanelHarness
    ):
        """Roster 2 and roster 4 both fail against a `persons_count` of 3.

        PRD 3.2: "The roster test passes when the submitted
        `roster_persons_count` equals the household's recorded `persons_count`
        exactly."

        Design: Corner/calculations/enumeration_verdict_reads_only_the_roster_and_the_tv_set_count
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 4, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        household = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        panel.installed_meter(household["id"], meter_type="TV_TUNER")

        under = panel.enumerate_household(
            household["id"], roster_persons_count=2, tv_sets_count=1
        )
        assert under["enumeration_verdict"] == "NONCOMPLIANT"
        assert under["status"] == "NONCOMPLIANT_HOLD"
        assert under["roster_persons_count"] == 2
        assert under["enumeration_count"] == 1
        assert panel.read_quota_cell(cell["id"])["intab_count"] == 0

        over = panel.enumerate_household(
            household["id"], roster_persons_count=4, tv_sets_count=2
        )
        assert over["enumeration_verdict"] == "NONCOMPLIANT"
        assert over["enumeration_count"] == 2
        assert over["tv_sets_count"] == 2

        # A roster of 13 never reaches the verdict at all: PRD 2.6 step 7 bounds
        # `roster_persons_count` to 1..12, so the shape check wins.
        rejected = panel.client.create_enumeration(
            panel.tech, household["id"], roster_persons_count=13, tv_sets_count=1
        )
        validate_error(rejected, "ERR_INVALID_REQUEST")
        assert panel.read_household(household["id"])["enumeration_count"] == 2

    def test_zero_television_sets_is_a_legal_input_that_still_fails_the_sets_test(
        self, panel: PanelHarness
    ):
        """`tv_sets_count` 0 is inside its range yet fails the sets predicate.

        PRD 3.2: "The sets test passes when the submitted `tv_sets_count` is at
        least 1."

        Design: Corner/calculations/enumeration_verdict_reads_only_the_roster_and_the_tv_set_count
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 4, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        household = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        panel.installed_meter(household["id"], meter_type="TV_TUNER")

        blind = panel.enumerate_household(
            household["id"], roster_persons_count=3, tv_sets_count=0
        )
        assert blind["enumeration_verdict"] == "NONCOMPLIANT"
        assert blind["status"] == "NONCOMPLIANT_HOLD"
        assert blind["tv_sets_count"] == 0
        assert blind["enumeration_count"] == 1
        assert panel.read_quota_cell(cell["id"])["intab_count"] == 0

        compliant = panel.enumerate_household(
            household["id"], roster_persons_count=3, tv_sets_count=1
        )
        assert compliant["enumeration_verdict"] == "COMPLIANT"
        assert compliant["status"] == "ACTIVE"
        assert compliant["enumeration_count"] == 2

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 1
        assert graded["fill_rate"] == expected_fill_rate(1, 4) == 0.2500
        assert graded["quota_status"] == "UNDER_TARGET"


class TestQuotaCellFillGrade:
    """The fill rate, its 4-decimal rounding, and the boost it arms."""

    def test_three_of_five_is_under_target_and_keeps_the_boost_armed(
        self, panel: PanelHarness
    ):
        """0.6000 is below 0.8000, so the cell stays in its aggressive stance.

        PRD 3.1: "`UNDER_TARGET` in every other case".

        Design: Corner/calculations/quota_cell_fill_at_exactly_four_fifths_is_on_target_and_disarms_the_boost
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 5, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        for _ in range(3):
            panel.active_household(market["id"], cell["id"])

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 3
        assert graded["fill_rate"] == expected_fill_rate(3, 5) == 0.6000
        assert graded["quota_status"] == "UNDER_TARGET"
        assert graded["incentive_boost_active"] is True
        assert graded["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER == 1.25

        # The reservation is base_incentive_cents * 1/4 * target_households.
        holder = panel.read_market(market["id"])
        assert holder["incentive_budget_reserved_cents"] == expected_boost_reservation(1000, 5)
        assert holder["incentive_budget_reserved_cents"] == 1250
        assert holder["under_target_cell_count"] == 1
        assert holder["filled_cell_count"] == 0
        assert holder["recruitment_posture"] == "OPEN"

    def test_four_of_five_is_exactly_on_target_and_disarms_the_boost(
        self, panel: PanelHarness
    ):
        """0.8000 meets the ON_TARGET floor, so the boost releases its reservation.

        PRD 3.1: "`ON_TARGET` when the rate is 0.8000 or more but below 1.0000".

        Design: Corner/calculations/quota_cell_fill_at_exactly_four_fifths_is_on_target_and_disarms_the_boost
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 5, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        for _ in range(3):
            panel.active_household(market["id"], cell["id"])
        assert panel.read_market(market["id"])["recruitment_posture"] == "OPEN"

        # The fourth activation happens on a later day so `posture_changed_at`
        # is distinguishable from the registration stamp of 2026-08-01.
        panel.set_clock("2026-08-05T00:00:00Z")
        panel.active_household(market["id"], cell["id"])

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 4
        assert graded["fill_rate"] == expected_fill_rate(4, 5) == 0.8000
        assert graded["fill_rate"] == ON_TARGET_THRESHOLD
        assert graded["quota_status"] == "ON_TARGET"
        assert graded["incentive_boost_active"] is False
        assert graded["effective_incentive_multiplier"] == UNBOOSTED_MULTIPLIER == 1.00

        # Disarming is the exact inverse of arming: the same 1250 comes back.
        holder = panel.read_market(market["id"])
        assert holder["incentive_budget_reserved_cents"] == 0
        assert holder["under_target_cell_count"] == 0
        assert holder["filled_cell_count"] == 0
        assert holder["recruitment_posture"] == "RESTRICTED"
        assert _instant(holder["posture_changed_at"]) == "2026-08-05T00:00:00"

        # RESTRICTED is not CLOSED: intake still passes the posture gate.
        latecomer = panel.recruit_household(market["id"], cell["id"], persons_count=3)
        assert latecomer["status"] == "RECRUITED"

    def test_one_third_rounds_half_up_to_four_decimals(self, panel: PanelHarness):
        """1/3 is 0.333333..., which rounds half up at 4 places to 0.3333.

        PRD 3.1: "`fill_rate` is then the in-tab count divided by
        `target_households`, rounded half up to 4 decimal places."

        Design: Corner/calculations/fill_rate_rounds_half_up_to_four_decimal_places
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 3, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        panel.active_household(market["id"], cell["id"])

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 1
        assert graded["fill_rate"] == expected_fill_rate(1, 3) == 0.3333
        assert graded["fill_rate"] == round_half_up(1 / 3, 4)
        assert graded["quota_status"] == "UNDER_TARGET"
        assert graded["incentive_boost_active"] is True

    def test_two_thirds_rounds_half_up_away_from_the_truncated_value(
        self, panel: PanelHarness
    ):
        """2/3 is 0.666666..., which rounds UP to 0.6667 rather than truncating.

        PRD 2.8: "One rounding convention governs the entire system: **round half
        up**, applied at exactly the precision the rule names".

        Design: Corner/calculations/fill_rate_rounds_half_up_to_four_decimal_places
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 3, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        panel.active_household(market["id"], cell["id"])
        panel.active_household(market["id"], cell["id"])

        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 2
        assert graded["fill_rate"] == expected_fill_rate(2, 3) == 0.6667
        assert graded["fill_rate"] != 0.6666
        assert graded["quota_status"] == "UNDER_TARGET"
        assert graded["incentive_boost_active"] is True
        assert panel.read_market(market["id"])[
            "incentive_budget_reserved_cents"
        ] == expected_boost_reservation(1000, 3) == 750


class TestRecruitmentPostureLadder:
    """The four posture clauses, walked in order, first match wins."""

    def test_a_cell_less_market_is_restricted_and_a_wholly_filled_one_is_closed(
        self, panel: PanelHarness
    ):
        """Clause 3 fires before clause 4 with no cells, clause 2 once all are FILLED.

        PRD 3.1: "Note the consequence for a brand-new market: it has no quota
        cells at all, so `under_target_cell_count` is 0, clause 3 fires before
        clause 4, and the initial posture is `RESTRICTED` rather than `OPEN`."

        Design: Corner/calculations/posture_frozen_outranks_closed_and_a_cell_less_market_is_restricted
        """
        market = panel.create_market()
        assert market["quota_cell_count"] == 0
        assert market["under_target_cell_count"] == 0
        assert market["filled_cell_count"] == 0
        assert market["recruitment_posture"] == "RESTRICTED"
        assert market["accreditation_status"] == "UNAUDITED"
        assert market["publication_blocked"] is False
        assert _instant(market["posture_changed_at"]) == "2026-08-01T00:00:00"

        # The first cell lands UNDER_TARGET, so clause 3 stops matching.
        cell = panel.create_quota_cell(
            market["id"], target_households=1, base_incentive_cents=1000
        )
        assert cell["quota_status"] == "UNDER_TARGET"
        opened = panel.read_market(market["id"])
        assert opened["quota_cell_count"] == 1
        assert opened["under_target_cell_count"] == 1
        assert opened["recruitment_posture"] == "OPEN"
        assert opened["incentive_budget_reserved_cents"] == expected_boost_reservation(1000, 1)
        assert opened["incentive_budget_reserved_cents"] == 250

        panel.set_clock("2026-08-05T00:00:00Z")
        panel.active_household(market["id"], cell["id"])
        graded = panel.read_quota_cell(cell["id"])
        assert graded["fill_rate"] == expected_fill_rate(1, 1) == 1.0000
        assert graded["quota_status"] == "FILLED"
        assert graded["incentive_boost_active"] is False

        closed = panel.read_market(market["id"])
        assert closed["filled_cell_count"] == closed["quota_cell_count"] == 1
        assert closed["under_target_cell_count"] == 0
        assert closed["recruitment_posture"] == "CLOSED"
        assert closed["incentive_budget_reserved_cents"] == 0
        assert _instant(closed["posture_changed_at"]) == "2026-08-05T00:00:00"

    def test_an_open_audit_freezes_a_closed_market_and_a_denial_releases_it(
        self, panel: PanelHarness
    ):
        """Clause 1 overrides the CLOSED clause below it, and the release restores it.

        PRD 3.1: "If the market has at least one accreditation audit in state
        `OPEN` — that is, `open_audit_count` is 1 or more — the posture is
        `FROZEN`."

        Design: Corner/calculations/posture_frozen_outranks_closed_and_a_cell_less_market_is_restricted
        """
        market, cells = panel.market_with_cells(
            [{"target_households": 1, "base_incentive_cents": 1000}]
        )
        cell = cells[0]
        rule_set = panel.published_rule_set()
        panel.active_household(market["id"], cell["id"])
        assert panel.read_quota_cell(cell["id"])["quota_status"] == "FILLED"
        assert panel.read_market(market["id"])["recruitment_posture"] == "CLOSED"

        panel.set_clock("2026-08-05T00:00:00Z")
        audit = panel.open_audit(market["id"], rule_set["id"])
        assert audit["state"] == "OPEN"
        frozen = panel.read_market(market["id"])
        assert frozen["open_audit_count"] == 1
        assert frozen["recruitment_posture"] == "FROZEN"
        # The cell roll-ups that made the market CLOSED are untouched underneath.
        assert frozen["filled_cell_count"] == frozen["quota_cell_count"] == 1
        assert frozen["under_target_cell_count"] == 0
        assert _instant(frozen["posture_changed_at"]) == "2026-08-05T00:00:00"

        panel.set_clock("2026-08-06T00:00:00Z")
        finalized = panel.finalize_audit(
            audit["id"],
            outcome="DENIED",
            limitation_disclosures=["PANEL_TOO_SMALL"],
        )
        assert finalized["state"] == "FINALIZED"
        assert finalized["outcome"] == "DENIED"

        released = panel.read_market(market["id"])
        assert released["open_audit_count"] == 0
        assert released["recruitment_posture"] == "CLOSED"
        assert released["accreditation_status"] == "DENIED"
        assert released["publication_blocked"] is True
        assert released["limitation_disclosures"] == ["PANEL_TOO_SMALL"]
        assert _instant(released["posture_changed_at"]) == "2026-08-06T00:00:00"


class TestMeterSuspectFloor:
    """The coverage scan's halved-and-rounded escalation threshold."""

    def test_missing_minutes_exactly_at_the_halved_floor_escalate_to_suspect(
        self, panel: PanelHarness
    ):
        """A threshold of 1441 halves to 720.5, which rounds half up to 721.

        PRD 3.3: "The suspect floor is the rule set's
        `fault_missing_minutes_threshold` divided by two and rounded half up to a
        whole number."

        Design: Corner/calculations/meter_suspect_floor_is_the_threshold_halved_and_rounded_half_up
        """
        base = panel.measurement_base(
            cell_specs=[{"target_households": 4, "base_incentive_cents": 1000}],
            fault_missing_minutes_threshold=1441,
        )
        cell = base["cells"][0]
        household = panel.recruit_household(base["market"]["id"], cell["id"], persons_count=3)
        tuner = panel.installed_meter(household["id"], meter_type="TV_TUNER")

        panel.set_clock(CLOCK_T1)
        panel.ingest_interval(
            tuner["id"], household["id"], WINDOW_START, "2026-08-01T13:00:00Z", 719
        )
        run = panel.open_run_over(base)
        assert run["window_minutes"] == WINDOW_MINUTES == 1440

        validate_success(panel.client.detect_faults(panel.statistician, run["id"]), 200)

        floor = expected_suspect_floor(1441)
        assert floor == round_half_up_to_int(720.5) == 721
        scanned = panel.read_meter(tuner["id"])
        assert scanned["missing_minutes_last_scan"] == WINDOW_MINUTES - 719 == 721
        # 721 is at the floor and below the 1441 threshold: SUSPECT, not FAULTED.
        assert scanned["health_status"] == "SUSPECT"
        assert scanned["fault_count"] == 0
        assert scanned["last_fault_code"] is None
        assert panel.read_run(run["id"])["state"] == "OPEN"

        # PRD 3.2 check 3: a home whose only tuner is SUSPECT cannot be enumerated.
        refused = panel.client.create_enumeration(
            panel.tech, household["id"], roster_persons_count=3, tv_sets_count=1
        )
        validate_error(refused, "ERR_METER_FAULTED")

    def test_one_minute_below_the_floor_leaves_health_alone_but_still_records_the_scan(
        self, panel: PanelHarness
    ):
        """720 missing minutes is below the floor of 721, so health does not move.

        PRD 3.3: "Missing minutes below the suspect floor leave `health_status`
        unchanged. Every scanned meter's `missing_minutes_last_scan` is updated
        regardless of the verdict".

        Design: Corner/calculations/meter_suspect_floor_is_the_threshold_halved_and_rounded_half_up
        """
        base = panel.measurement_base(
            cell_specs=[{"target_households": 4, "base_incentive_cents": 1000}],
            fault_missing_minutes_threshold=1441,
        )
        cell = base["cells"][0]
        household = panel.recruit_household(base["market"]["id"], cell["id"], persons_count=3)
        tuner = panel.installed_meter(household["id"], meter_type="TV_TUNER")

        panel.set_clock(CLOCK_T1)
        panel.ingest_interval(
            tuner["id"], household["id"], WINDOW_START, "2026-08-01T13:00:00Z", 720
        )
        run = panel.open_run_over(base)
        validate_success(panel.client.detect_faults(panel.statistician, run["id"]), 200)

        scanned = panel.read_meter(tuner["id"])
        assert scanned["missing_minutes_last_scan"] == WINDOW_MINUTES - 720 == 720
        assert scanned["missing_minutes_last_scan"] < expected_suspect_floor(1441)
        assert scanned["health_status"] == "HEALTHY"
        assert scanned["fault_count"] == 0
        assert panel.read_run(run["id"])["state"] == "OPEN"

        # The one reported day carried 720 raw minutes, so the refreshed rolling
        # figure is 1 compliant day out of 1 reported day.
        assert panel.read_household(household["id"])[
            "compliance_rate_rolling_30"
        ] == expected_compliance_rate(1, 1) == 1.0000

        # A HEALTHY tuner passes check 3, so the visit lands the home in tab.
        activated = panel.enumerate_household(
            household["id"], roster_persons_count=3, tv_sets_count=1
        )
        assert activated["enumeration_verdict"] == "COMPLIANT"
        assert activated["status"] == "ACTIVE"
        graded = panel.read_quota_cell(cell["id"])
        assert graded["intab_count"] == 1
        assert graded["fill_rate"] == expected_fill_rate(1, 4) == 0.2500


def _active_household_with_ooh(panel: PanelHarness, market_id: str, quota_cell_id: str):
    """An ACTIVE home holding both a TV_TUNER and a PORTABLE_OOH device.

    Both devices are shipped while the home is still `INSTALL_SCHEDULED`, because
    PRD 3.3 check 1 refuses a shipment to a household past enumeration and
    confirming the tuner is what moves the home to `ENUM_PENDING`.
    """
    household = panel.recruit_household(market_id, quota_cell_id, persons_count=3)
    tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
    portable = panel.ship_meter(household["id"], meter_type="PORTABLE_OOH")
    tuner = panel.install_meter(tuner["id"])
    portable = panel.install_meter(portable["id"])
    household = panel.enumerate_household(
        household["id"], roster_persons_count=3, tv_sets_count=1
    )
    assert household["status"] == "ACTIVE"
    return {"household": household, "tuner": tuner, "portable": portable}


def _editing_base(panel: PanelHarness):
    """The ordered-editing recipe: five tuner blocks and two out-of-home blocks.

    The rule set allows a 60-minute ascription gap and invalidates any block above
    900 tuning minutes. On the tuner the gaps are 30, 60 and 65 minutes, so the
    first two are filled and the third is left as a hole; block E is over the
    tuning ceiling, so the 30-minute gap between D and E is never ascribed.
    """
    base = panel.measurement_base(
        cell_specs=[{"target_households": 4, "base_incentive_cents": 1000}],
        missing_interval_ascription_minutes=60,
        invalid_tuning_max_minutes=900,
    )
    built = _active_household_with_ooh(
        panel, base["market"]["id"], base["cells"][0]["id"]
    )
    home = built["household"]["id"]
    tuner = built["tuner"]["id"]
    portable = built["portable"]["id"]

    panel.set_clock(DAY_END)
    blocks = {
        "A": panel.ingest_interval(
            tuner, home, "2026-08-10T00:00:00Z", "2026-08-10T00:30:00Z", 30,
            station_code="WAAA",
        ),
        "B": panel.ingest_interval(
            tuner, home, "2026-08-10T01:00:00Z", "2026-08-10T01:30:00Z", 30,
            station_code="WBBB",
        ),
        "C": panel.ingest_interval(
            tuner, home, "2026-08-10T02:30:00Z", "2026-08-10T03:00:00Z", 30,
            station_code="WCCC",
        ),
        "D": panel.ingest_interval(
            tuner, home, "2026-08-10T04:05:00Z", "2026-08-10T05:00:00Z", 55,
            station_code="WDDD",
        ),
        "E": panel.ingest_interval(
            tuner, home, "2026-08-10T05:30:00Z", "2026-08-10T20:40:00Z", 901,
            station_code="WEEE",
        ),
        "F": panel.ingest_interval(
            portable, home, "2026-08-10T06:00:00Z", "2026-08-10T07:00:00Z", 60,
            station_code="WFFF", source_methodology="PORTABLE_OOH",
        ),
        "G": panel.ingest_interval(
            portable, home, "2026-08-10T08:00:00Z", "2026-08-10T08:30:00Z", 30,
            station_code="WGGG", source_methodology="PORTABLE_OOH",
        ),
    }
    run = panel.open_run_over(base, window_start_iso=DAY_START, window_end_iso=DAY_END)
    base["run"] = panel.edit_run(run["id"])
    base["built"] = built
    base["blocks"] = blocks
    return base


class TestOrderedEditingPass:
    """The seven steps of the editing pass, in the order the PRD pins."""

    def test_invalidation_runs_before_ascription_so_the_gap_to_e_is_never_filled(
        self, panel: PanelHarness
    ):
        """Two gaps are ascribed; the gap beside the over-ceiling block is not.

        PRD 3.6: "For each meter, its surviving `EDITED` records are walked in
        `start_iso` ascending order."

        Design: Corner/calculations/interval_editing_orders_invalidation_before_ascription_and_halves_ooh_credit
        """
        base = _editing_base(panel)
        run = base["run"]
        blocks = base["blocks"]

        assert run["state"] == "EDITED"
        assert run["invalidated_interval_count"] == 1
        assert run["ascribed_interval_count"] == 2
        assert run["outlier_household_count"] == 0
        assert run["contributing_household_count"] == 1
        assert run["limitation_disclosures"] == ["ASCRIBED_INTERVALS_PRESENT"]

        # Step 2 threw E out at 901 > 900 before step 5 could ever see it.
        thrown = panel.read_interval(blocks["E"]["id"])
        assert thrown["state"] == "INVALIDATED"
        assert thrown["invalidation_reason"] == "OVER_MAX_TUNING"
        assert thrown["usable_minutes"] == 0
        assert thrown["ascribed"] is False

        synthetic = sorted(
            (row for row in panel.intervals_of_run(run["id"]) if row["ascribed"]),
            key=lambda row: row["start_iso"],
        )
        assert len(synthetic) == 2

        # Gap 1: A ends 00:30, B starts 01:00 - 30 minutes, at or under the 60
        # allowance, credited at the INHOME_TUNER factor of 1.0 and carrying the
        # EARLIER record's station code.
        first = synthetic[0]
        assert _instant(first["start_iso"]) == "2026-08-10T00:30:00"
        assert _instant(first["end_iso"]) == "2026-08-10T01:00:00"
        assert first["tuning_minutes"] == 30
        assert first["usable_minutes"] == expected_usable_minutes(30, "INHOME_TUNER") == 30
        assert first["station_code"] == "WAAA"
        assert first["source_methodology"] == "INHOME_TUNER"
        assert first["state"] == "ASCRIBED"
        assert first["meter_id"] == base["built"]["tuner"]["id"]

        # Gap 2: B ends 01:30, C starts 02:30 - exactly the 60-minute allowance,
        # which is inclusive, so it is filled rather than left as a hole.
        second = synthetic[1]
        assert _instant(second["start_iso"]) == "2026-08-10T01:30:00"
        assert _instant(second["end_iso"]) == "2026-08-10T02:30:00"
        assert second["tuning_minutes"] == 60
        assert second["usable_minutes"] == expected_usable_minutes(60, "INHOME_TUNER") == 60
        assert second["station_code"] == "WBBB"

        # Gap 3 (C to D) is 65 minutes, above the allowance, and the 30-minute gap
        # from D to E is suppressed because E is no longer an EDITED record.
        assert not [
            row
            for row in synthetic
            if _instant(row["start_iso"]) in ("2026-08-10T03:00:00", "2026-08-10T05:00:00")
        ]
        for key in ("A", "B", "C", "D"):
            assert panel.read_interval(blocks[key]["id"])["state"] == "EDITED"

    def test_out_of_home_credit_is_halved_and_out_of_home_gaps_are_never_ascribed(
        self, panel: PanelHarness
    ):
        """PORTABLE_OOH minutes are credited at 0.5 and its 60-minute gap stays a hole.

        PRD 3.6: "Meters whose `meter_type` is `PORTABLE_OOH` are never ascribed
        at all: out-of-home absence is real absence, not a collection gap."

        Design: Corner/calculations/interval_editing_orders_invalidation_before_ascription_and_halves_ooh_credit
        """
        base = _editing_base(panel)
        blocks = base["blocks"]
        portable_id = base["built"]["portable"]["id"]

        # 60 raw minutes credit as 30; 30 raw minutes credit as 15.
        portable_long = panel.read_interval(blocks["F"]["id"])
        assert portable_long["state"] == "EDITED"
        assert portable_long["usable_minutes"] == expected_usable_minutes(60, "PORTABLE_OOH")
        assert portable_long["usable_minutes"] == 30
        assert portable_long["ascribed"] is False

        portable_short = panel.read_interval(blocks["G"]["id"])
        assert portable_short["usable_minutes"] == expected_usable_minutes(30, "PORTABLE_OOH")
        assert portable_short["usable_minutes"] == 15

        # F ends 07:00 and G starts 08:00, a 60-minute gap that would have been
        # ascribed on any other meter type.
        assert not [
            row for row in panel.intervals_of_meter(portable_id) if row["ascribed"]
        ]
        assert len(panel.intervals_of_meter(portable_id)) == 2

        # In-home collection is credited in full, so D keeps all 55 minutes.
        assert panel.read_interval(blocks["D"]["id"])["usable_minutes"] == 55
        assert expected_usable_minutes(55, "INHOME_TUNER") == 55

        # 30 + 30 + 30 + 55 real tuner minutes, 30 + 60 ascribed, 30 + 15 portable.
        credited = sum(
            row["usable_minutes"]
            for row in panel.intervals_of_run(base["run"]["id"])
            if row["state"] in ("EDITED", "ASCRIBED")
        )
        assert credited == 145 + 90 + 45 == 280


def _outlier_base(panel: PanelHarness):
    """One heavy home whose ascribed minutes tip it over the cap, plus one light home.

    The heavy home reports 100 + 90 = 190 raw minutes, which is under the
    200-minute cap on its own; the 30-minute gap between its two blocks is
    ascribed, and 190 + 30 = 220 is what the outlier comparison actually reads.
    """
    base = panel.measurement_base(
        cell_specs=[{"target_households": 4, "base_incentive_cents": 1000}],
        missing_interval_ascription_minutes=60,
        outlier_household_minutes_cap=200,
    )
    cell = base["cells"][0]
    heavy = panel.active_household(base["market"]["id"], cell["id"])
    light = panel.active_household(base["market"]["id"], cell["id"])

    panel.set_clock(DAY_END)
    heavy_blocks = [
        panel.ingest_interval(
            heavy["tuner"]["id"], heavy["household"]["id"],
            "2026-08-10T00:00:00Z", "2026-08-10T01:40:00Z", 100, station_code="WHVY",
        ),
        panel.ingest_interval(
            heavy["tuner"]["id"], heavy["household"]["id"],
            "2026-08-10T02:10:00Z", "2026-08-10T03:40:00Z", 90, station_code="WHVY",
        ),
    ]
    light_block = panel.ingest_interval(
        light["tuner"]["id"], light["household"]["id"],
        "2026-08-10T00:00:00Z", "2026-08-10T01:00:00Z", 60, station_code="WLGT",
    )
    opened = panel.open_run_over(
        base, window_start_iso=DAY_START, window_end_iso=DAY_END
    )
    base["opened"] = opened
    base["run"] = panel.edit_run(opened["id"])
    base["heavy"] = heavy
    base["light"] = light
    base["heavy_blocks"] = heavy_blocks
    base["light_block"] = light_block
    return base


class TestOutlierHouseholdExclusion:
    """The outlier comparison reads credited minutes, ascriptions included."""

    def test_the_cap_comparison_includes_the_households_own_ascribed_minutes(
        self, panel: PanelHarness
    ):
        """190 raw minutes plus a 30-minute ascription is 220, which exceeds 200.

        PRD 3.6: "For each household, the summed `usable_minutes` across its
        `EDITED` and `ASCRIBED` records claimed by this run is compared with the
        rule set's `outlier_household_minutes_cap`."

        Design: Corner/calculations/outlier_household_invalidation_counts_its_own_ascribed_minutes
        """
        base = _outlier_base(panel)
        run = base["run"]

        # The raw total alone would have survived the cap.
        assert 100 + 90 == 190
        assert 190 <= 200
        assert 190 + 30 == 220 > 200

        assert run["state"] == "EDITED"
        assert run["outlier_household_count"] == 1
        assert run["invalidated_interval_count"] == 2
        # The synthetic row was created by step 5 and then deleted by step 6, so
        # it is counted neither as ascribed nor as invalidated.
        assert run["ascribed_interval_count"] == 0
        assert run["contributing_household_count"] == 1
        assert run["limitation_disclosures"] == ["OUTLIER_HOUSEHOLDS_EXCLUDED"]

        for block in base["heavy_blocks"]:
            row = panel.read_interval(block["id"])
            assert row["state"] == "INVALIDATED"
            assert row["invalidation_reason"] == "OUTLIER_HOUSEHOLD"
            assert row["usable_minutes"] == 0

        survivor = panel.read_interval(base["light_block"]["id"])
        assert survivor["state"] == "EDITED"
        assert survivor["usable_minutes"] == 60
        assert survivor["invalidation_reason"] is None

        claimed = panel.intervals_of_run(run["id"])
        assert len(claimed) == 3
        assert not [row for row in claimed if row["ascribed"]]

    def test_the_surviving_home_carries_the_whole_final_projection(
        self, panel: PanelHarness
    ):
        """One contributor, a FINAL denominator of 1, and a 2-decimal contribution.

        PRD 3.7: "First, each household's `contribution` is its `adjusted_weight`
        multiplied by its summed usable minutes and divided by the run's
        `window_minutes`, rounded half up to 2 decimal places."

        Design: Corner/calculations/outlier_household_invalidation_counts_its_own_ascribed_minutes
        """
        base = _outlier_base(panel)
        weighted = panel.weight_run(base["run"]["id"], weight_variant="FINAL")

        assert weighted["state"] == "WEIGHTED"
        assert weighted["weight_variant"] == "FINAL"
        # The snapshot was frozen at run open, when both homes were still ACTIVE.
        assert weighted["intab_snapshot_count"] == 2
        assert weighted["excluded_cell_count"] == 0

        rows = panel.weights_of_run(base["run"]["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["household_id"] == base["light"]["household"]["id"]
        assert row["usable_minutes"] == 60
        # 100000 population households over a FINAL denominator of exactly 1.
        assert row["base_weight"] == 100000.0000
        assert row["adjusted_weight"] == row["base_weight"]
        assert row["capped"] is False
        assert row["weight_variant"] == "FINAL"

        adjusted, mass, capped_flags = expected_adjusted_weights([100000.0], 3.0)
        assert adjusted == [100000.0]
        assert capped_flags == [False]
        assert weighted["total_weight_mass"] == mass == 100000.0000

        # 100000 * 60 / 1440 is 4166.6666..., which rounds half up to 4166.67.
        assert row["contribution"] == expected_contribution(100000.0, 60, WINDOW_MINUTES)
        assert row["contribution"] == 4166.67
        assert weighted["projected_average_audience"] == expected_projected_average_audience(
            [4166.67]
        )
        assert weighted["projected_average_audience"] == 4167

        # Every calendar day of the window is evaluated, and the single day
        # carried 60 credited minutes.
        assert row["run_compliance_rate"] == expected_compliance_rate(1, 1) == 1.0000
        assert weighted["limitation_disclosures"] == ["OUTLIER_HOUSEHOLDS_EXCLUDED"]


def _rolling_home(panel: PanelHarness):
    """An ACTIVE home with the clock parked at 2026-08-20 for rolling-window work.

    The 30-day window is then [2026-07-21, 2026-08-20), so every block below
    lands inside it and the run machinery is not involved at all.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 4, "base_incentive_cents": 1000}]
    )
    built = panel.active_household(market["id"], cells[0]["id"])
    panel.set_clock("2026-08-20T00:00:00Z")
    built["market"] = market
    built["cell"] = cells[0]
    return built


class TestRollingComplianceRate:
    """Reported days only, credited to the start date, and stored as a snapshot."""

    def test_the_denominator_counts_reported_days_and_minutes_sum_per_date(
        self, panel: PanelHarness
    ):
        """1/1, then 1/2, then 1/3, then 2/3 as blocks arrive on three dates.

        PRD 3.6: "The evaluated days are the count of distinct UTC calendar dates
        inside that window on which the household holds at least one interval in
        `state` `RAW`, `EDITED` or `ASCRIBED` — **reported days only**, so a
        household that reported on two days out of the thirty is scored out of 2
        and not out of 30."

        Design: Corner/calculations/rolling_compliance_counts_reported_days_and_is_a_stored_snapshot
        """
        built = _rolling_home(panel)
        home = built["household"]["id"]
        tuner = built["tuner"]["id"]

        # A block crossing midnight is credited entirely to its start date, so
        # 2026-08-09 is the only reported day and it carries all 30 minutes.
        panel.ingest_interval(
            tuner, home, "2026-08-09T23:45:00Z", "2026-08-10T00:15:00Z", 30,
            station_code="WMID",
        )
        assert 30 >= MIN_COMPLIANT_DAY_MINUTES
        assert panel.read_household(home)[
            "compliance_rate_rolling_30"
        ] == expected_compliance_rate(1, 1) == 1.0000

        # 29 minutes on 2026-08-11 is one minute short of a compliant day, and it
        # is scored out of 2 reported days rather than out of 30.
        panel.ingest_interval(
            tuner, home, "2026-08-11T10:00:00Z", "2026-08-11T10:30:00Z", 29,
            station_code="WSHY",
        )
        assert panel.read_household(home)[
            "compliance_rate_rolling_30"
        ] == expected_compliance_rate(1, 2) == 0.5000

        # 15 minutes on 2026-08-12 adds a third reported day, still 1 compliant.
        panel.ingest_interval(
            tuner, home, "2026-08-12T10:00:00Z", "2026-08-12T10:15:00Z", 15,
            station_code="WHLF",
        )
        assert panel.read_household(home)[
            "compliance_rate_rolling_30"
        ] == expected_compliance_rate(1, 3) == 0.3333

        # A second 15-minute block on the SAME date sums to 30, which reaches the
        # threshold, so 2026-08-12 becomes compliant without adding a day.
        panel.ingest_interval(
            tuner, home, "2026-08-12T11:00:00Z", "2026-08-12T11:15:00Z", 15,
            station_code="WHLF",
        )
        assert panel.read_household(home)[
            "compliance_rate_rolling_30"
        ] == expected_compliance_rate(2, 3) == 0.6667

    def test_the_stored_snapshot_does_not_age_until_the_next_ingest(
        self, panel: PanelHarness
    ):
        """Moving the clock a month forward leaves 0.6667 exactly where it stood.

        PRD 3.6: "The figure is stored, not derived at read time: it is recomputed
        on interval ingest and on a fault-detection scan, so a stored value is a
        snapshot as of the clock at the last ingest or scan and does not silently
        age."

        Design: Corner/calculations/rolling_compliance_counts_reported_days_and_is_a_stored_snapshot
        """
        built = _rolling_home(panel)
        home = built["household"]["id"]
        tuner = built["tuner"]["id"]
        for start, end, minutes in (
            ("2026-08-09T23:45:00Z", "2026-08-10T00:15:00Z", 30),
            ("2026-08-11T10:00:00Z", "2026-08-11T10:30:00Z", 29),
            ("2026-08-12T10:00:00Z", "2026-08-12T10:15:00Z", 15),
            ("2026-08-12T11:00:00Z", "2026-08-12T11:15:00Z", 15),
        ):
            panel.ingest_interval(tuner, home, start, end, minutes, station_code="WSNP")
        assert panel.read_household(home)["compliance_rate_rolling_30"] == 0.6667

        # The window [2026-08-21, 2026-09-20) holds none of those blocks, yet the
        # stored figure is untouched because nothing recomputed it.
        panel.set_clock("2026-09-20T00:00:00Z")
        assert panel.read_household(home)["compliance_rate_rolling_30"] == 0.6667
        assert panel.read_household(home)["compliance_rate_rolling_30"] != 0.0000

        # The next ingest is what refreshes it: one reported day, one compliant.
        panel.ingest_interval(
            tuner, home, "2026-09-19T10:00:00Z", "2026-09-19T10:40:00Z", 40,
            station_code="WNEW",
        )
        assert panel.read_household(home)[
            "compliance_rate_rolling_30"
        ] == expected_compliance_rate(1, 1) == 1.0000


def _two_cell_weighting_base(panel: PanelHarness):
    """Two cells of 100000 and 30000 households, one contributor in each.

    The rule set's `outlier_weight_ratio_cap` is 2.5, so the cap sits at 2.5 times
    this run's own mean base weight and neither row reaches it.
    """
    market, cells = panel.market_with_cells(
        [
            {"age_band": "P18_34", "target_households": 4, "base_incentive_cents": 1000},
            {"age_band": "P35_54", "target_households": 4, "base_incentive_cents": 1000},
        ]
    )
    rule_set = panel.published_rule_set(outlier_weight_ratio_cap=2.5)
    universe = panel.published_universe(
        market["id"],
        [cells[0]["id"], cells[1]["id"]],
        cell_populations=[
            cell_population(
                cells[0]["id"], population_households=100000, population_persons=250000
            ),
            cell_population(
                cells[1]["id"], population_households=30000, population_persons=70000
            ),
        ],
    )
    base = {"market": market, "cells": cells, "rule_set": rule_set, "universe": universe}

    big = panel.active_household(market["id"], cells[0]["id"])
    small = panel.active_household(market["id"], cells[1]["id"])
    panel.set_clock(DAY_END)
    panel.ingest_interval(
        big["tuner"]["id"], big["household"]["id"],
        "2026-08-10T00:00:00Z", "2026-08-10T06:00:00Z", 350, station_code="WBIG",
    )
    panel.ingest_interval(
        small["tuner"]["id"], small["household"]["id"],
        "2026-08-10T00:00:00Z", "2026-08-10T04:00:00Z", 217, station_code="WSML",
    )
    opened = panel.open_run_over(
        base, window_start_iso=DAY_START, window_end_iso=DAY_END
    )
    base["run"] = panel.edit_run(opened["id"])
    base["big"] = big
    base["small"] = small
    return base


class TestWeightCapAndProjection:
    """A distribution wholly under its own cap, and the pinned projection order."""

    def test_no_row_above_the_cap_leaves_every_adjusted_weight_at_its_base(
        self, panel: PanelHarness
    ):
        """Bases of 100000 and 30000 sit under a cap of 162500, so nothing moves.

        PRD 3.7: "If there are no capped rows, every row's `adjusted_weight`
        equals its `base_weight` and the run's `total_weight_mass` is the mass."

        Design: Corner/calculations/weight_cap_with_no_row_above_the_cap_leaves_every_weight_untouched
        """
        base = _two_cell_weighting_base(panel)
        assert base["run"]["contributing_household_count"] == 2
        weighted = panel.weight_run(base["run"]["id"], weight_variant="FINAL")

        rows = panel.weights_of_run(base["run"]["id"])
        assert len(rows) == 2
        # Rows are created in household `created_at` ascending order.
        assert rows[0]["household_id"] == base["big"]["household"]["id"]
        assert rows[1]["household_id"] == base["small"]["household"]["id"]

        # Each FINAL denominator is 1: one contributor per cell.
        assert rows[0]["base_weight"] == 100000.0000
        assert rows[1]["base_weight"] == 30000.0000

        mean_base, cap = expected_cap([100000.0, 30000.0], 2.5)
        assert mean_base == 65000.0000
        assert cap == 162500.0000
        assert max(row["base_weight"] for row in rows) <= cap

        adjusted, mass, capped_flags = expected_adjusted_weights([100000.0, 30000.0], 2.5)
        assert capped_flags == [False, False]
        assert adjusted == [100000.0, 30000.0]
        for row in rows:
            assert row["adjusted_weight"] == row["base_weight"]
            assert row["capped"] is False

        assert weighted["total_weight_mass"] == mass == 130000.0000
        assert panel.weights_of_run(base["run"]["id"], capped=True) == []
        assert "WEIGHT_CAP_APPLIED" not in weighted["limitation_disclosures"]
        assert weighted["excluded_cell_count"] == 0
        assert "CELL_NO_CONTRIBUTORS" not in weighted["limitation_disclosures"]

    def test_each_contribution_is_rounded_to_two_places_before_the_sum(
        self, panel: PanelHarness
    ):
        """24305.56 plus 4520.83 is 28826.39, which rounds to 28826 households.

        PRD 3.7: "The rounding order is mandatory: rounding every household to 2
        decimal places before summing, and only then rounding the sum, produces a
        different — and correct — answer from summing unrounded products and
        rounding once at the end."

        Design: Corner/calculations/weight_cap_with_no_row_above_the_cap_leaves_every_weight_untouched
        """
        base = _two_cell_weighting_base(panel)
        weighted = panel.weight_run(base["run"]["id"], weight_variant="FINAL")
        rows = panel.weights_of_run(base["run"]["id"])

        # 100000 * 350 / 1440 is 24305.5555..., 30000 * 217 / 1440 is 4520.8333...
        assert rows[0]["usable_minutes"] == 350
        assert rows[0]["contribution"] == expected_contribution(100000.0, 350, WINDOW_MINUTES)
        assert rows[0]["contribution"] == 24305.56
        assert rows[1]["usable_minutes"] == 217
        assert rows[1]["contribution"] == expected_contribution(30000.0, 217, WINDOW_MINUTES)
        assert rows[1]["contribution"] == 4520.83

        assert round_half_up(24305.56 + 4520.83, 2) == 28826.39
        assert weighted["projected_average_audience"] == expected_projected_average_audience(
            [24305.56, 4520.83]
        )
        assert weighted["projected_average_audience"] == 28826

        # The projection basis is the pinned vintage, summed from its own entries.
        vintage = panel.read_universe(base["universe"]["id"])
        assert vintage["total_population_households"] == 100000 + 30000 == 130000
        assert vintage["total_population_persons"] == 250000 + 70000 == 320000


def _sole_contributor_base(panel: PanelHarness):
    """One cell, one contributing home, 350 credited minutes over the day window."""
    base = panel.measurement_base(
        cell_specs=[{"target_households": 4, "base_incentive_cents": 1000}]
    )
    built = panel.active_household(base["market"]["id"], base["cells"][0]["id"])
    panel.set_clock(DAY_END)
    panel.ingest_interval(
        built["tuner"]["id"], built["household"]["id"],
        "2026-08-10T00:00:00Z", "2026-08-10T06:00:00Z", 350, station_code="WONE",
    )
    opened = panel.open_run_over(
        base, window_start_iso=DAY_START, window_end_iso=DAY_END
    )
    base["run"] = panel.edit_run(opened["id"])
    base["built"] = built
    return base


class TestDesignDenominatorAfterRetirement:
    """The two variants differ only in the denominator, and only one can empty."""

    def test_design_weighting_is_refused_once_the_only_recruit_is_retired(
        self, panel: PanelHarness
    ):
        """A cell holding no non-retired household has a zero DESIGN denominator.

        PRD 3.7: "Under `weight_variant` `DESIGN` only, every contributing
        household's quota cell must hold at least one non-retired household so
        that no design denominator is zero, otherwise
        `ERR_DESIGN_DENOMINATOR_EMPTY`."

        Design: Corner/calculations/design_denominator_excludes_a_retired_contributor
        """
        base = _sole_contributor_base(panel)
        run = base["run"]
        home = base["built"]["household"]["id"]
        assert run["contributing_household_count"] == 1

        retired = validate_success(
            panel.client.retire_household(
                panel.ops, home, retired_reason="Household moved out of the market."
            ),
            200,
        )
        assert retired["status"] == "RETIRED"
        # The retirement cascade pulled the equipment and dropped the cell count.
        assert panel.read_meter(base["built"]["tuner"]["id"])["install_status"] == "REMOVED"
        cell = panel.read_quota_cell(base["cells"][0]["id"])
        assert cell["intab_count"] == 0
        assert cell["fill_rate"] == expected_fill_rate(0, 4) == 0.0000
        assert cell["quota_status"] == "UNDER_TARGET"

        # The edit pass already ran, so the run still remembers its contributor.
        still_edited = panel.read_run(run["id"])
        assert still_edited["state"] == "EDITED"
        assert still_edited["contributing_household_count"] == 1

        refused = panel.client.weight_processing_run(
            panel.statistician, run["id"], weight_variant="DESIGN"
        )
        validate_error(refused, "ERR_DESIGN_DENOMINATOR_EMPTY")

        unchanged = panel.read_run(run["id"])
        assert unchanged["state"] == "EDITED"
        assert unchanged["weight_variant"] is None
        assert unchanged["total_weight_mass"] == 0
        assert unchanged["projected_average_audience"] is None
        assert panel.weights_of_run(run["id"]) == []

    def test_final_weighting_still_counts_the_household_that_retired(
        self, panel: PanelHarness
    ):
        """The FINAL denominator is 1 because the retired home contributed data.

        PRD 3.7: "Only real data providers count, and that count is deliberately
        **not** re-filtered on the household's current `status`: a household
        retired after the edit pass still counts itself."

        Design: Corner/calculations/design_denominator_excludes_a_retired_contributor
        """
        base = _sole_contributor_base(panel)
        run = base["run"]
        home = base["built"]["household"]["id"]
        validate_success(
            panel.client.retire_household(
                panel.ops, home, retired_reason="Household moved out of the market."
            ),
            200,
        )

        weighted = panel.weight_run(run["id"], weight_variant="FINAL")
        assert weighted["state"] == "WEIGHTED"
        assert weighted["weight_variant"] == "FINAL"
        assert weighted["excluded_cell_count"] == 0

        rows = panel.weights_of_run(run["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["household_id"] == home
        assert panel.read_household(home)["status"] == "RETIRED"
        assert row["usable_minutes"] == 350
        assert row["base_weight"] == 100000.0000
        assert row["adjusted_weight"] == 100000.0000
        assert row["capped"] is False
        assert weighted["total_weight_mass"] == 100000.0000

        # 100000 * 350 / 1440 is 24305.5555..., so the projection is 24306.
        assert row["contribution"] == expected_contribution(100000.0, 350, WINDOW_MINUTES)
        assert row["contribution"] == 24305.56
        assert weighted["projected_average_audience"] == expected_projected_average_audience(
            [24305.56]
        )
        assert weighted["projected_average_audience"] == 24306
        assert row["run_compliance_rate"] == expected_compliance_rate(1, 1) == 1.0000


def _accrual_home(panel: PanelHarness, base_incentive_cents: int = 2000):
    """One ACTIVE home in an UNDER_TARGET cell, so its boost is armed at 1.25.

    The home never reports an interval, so `compliance_rate_rolling_30` stays at
    0.0000 and steps 5, 6 and 8 of the accrual all contribute nothing.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 4, "base_incentive_cents": base_incentive_cents}]
    )
    built = panel.active_household(market["id"], cells[0]["id"])
    built["market"] = market
    built["cell"] = cells[0]
    return built


class TestIncentiveTenureMultiplier:
    """Thirty-day months, floored, and the multiplier band they select."""

    def test_a_brand_new_household_accrues_the_boosted_cell_base_only(
        self, panel: PanelHarness
    ):
        """Tenure 0 months multiplies by 1.000, so 2000 * 1.25 = 2500 is the period.

        PRD 3.4: "The cell base is the quota cell's `base_incentive_cents`
        multiplied by the cell's `effective_incentive_multiplier`, rounded to a
        whole cent."

        Design: Corner/calculations/incentive_tenure_multiplier_at_exactly_six_thirty_day_months
        """
        built = _accrual_home(panel)
        home = built["household"]["id"]
        cell = panel.read_quota_cell(built["cell"]["id"])
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER == 1.25
        assert panel.read_household(home)["compliance_rate_rolling_30"] == 0.0000

        panel.accrue(home, period_label="2026-08")

        breakdown = expected_accrual_breakdown(2000, 1.25, 0, 0.0000, False, False)
        assert breakdown["tenure_multiplier"] == expected_tenure_multiplier(0) == 1.000
        assert breakdown["cell_base"] == 2500
        assert breakdown["tenure_amount"] == 2500
        assert breakdown["compliance_bonus"] == 0
        assert breakdown["ooh_supplement"] == 0
        assert breakdown["fault_penalty"] == 0
        assert breakdown["period_amount"] == 2500

        row = panel.read_household(home)
        assert row["incentive_accrued_cents"] == 2500
        assert len(row["accrual_periods"]) == 1
        assert row["accrual_periods"][0]["period_label"] == "2026-08"
        assert row["accrual_periods"][0]["accrued_cents"] == 2500
        assert row["accrual_periods"][0]["reversed"] is False

        holder = panel.read_market(built["market"]["id"])
        assert holder["incentive_budget_committed_cents"] == 2500
        assert holder["incentive_budget_reserved_cents"] == expected_boost_reservation(2000, 4)
        assert holder["incentive_budget_reserved_cents"] == 2000

        duplicate = panel.client.accrue_incentive(panel.ops, home, period_label="2026-08")
        validate_error(duplicate, "ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED")
        assert panel.read_household(home)["incentive_accrued_cents"] == 2500

    def test_exactly_one_hundred_eighty_days_crosses_into_the_six_month_band(
        self, panel: PanelHarness
    ):
        """179 days is still 5 months; 180 days is exactly 6 and pays 1.075.

        PRD 3.4: "The tenure multiplier is 1.000 for a tenure under 6 months,
        1.075 for a tenure of 6 months or more but under 24, and 1.150 for a
        tenure of 24 months or more."

        Design: Corner/calculations/incentive_tenure_multiplier_at_exactly_six_thirty_day_months
        """
        built = _accrual_home(panel)
        home = built["household"]["id"]
        panel.accrue(home, period_label="2026-08")
        assert panel.read_household(home)["incentive_accrued_cents"] == 2500

        # 2026-08-01 to 2027-01-27 is 179 days: 179 * 86400 / 2592000 floors to 5.
        panel.set_clock("2027-01-27T00:00:00Z")
        assert (179 * 86400) // 2592000 == 5
        assert expected_tenure_multiplier(5) == 1.000
        panel.accrue(home, period_label="2027-01")
        fifth = panel.read_household(home)
        assert fifth["accrual_periods"][1]["accrued_cents"] == 2500
        assert fifth["incentive_accrued_cents"] == 5000

        # One day later the elapsed time is exactly six thirty-day months.
        panel.set_clock("2027-01-28T00:00:00Z")
        assert (180 * 86400) // 2592000 == 6
        panel.accrue(home, period_label="2027-02")

        sixth = expected_accrual_breakdown(2000, 1.25, 6, 0.0000, False, False)
        assert sixth["tenure_multiplier"] == expected_tenure_multiplier(6) == 1.075
        # 2500 * 1.075 is 2687.5, which rounds HALF UP to 2688, not down to 2687.
        assert sixth["tenure_amount"] == round_half_up_to_int(2687.5) == 2688
        assert sixth["period_amount"] == 2688

        final = panel.read_household(home)
        assert final["accrual_periods"][2]["period_label"] == "2027-02"
        assert final["accrual_periods"][2]["accrued_cents"] == 2688
        assert final["incentive_accrued_cents"] == 2500 + 2500 + 2688 == 7688

        holder = panel.read_market(built["market"]["id"])
        assert holder["incentive_budget_committed_cents"] == 7688
        assert holder["incentive_budget_reserved_cents"] == 2000


def _ooh_accrual_home(panel: PanelHarness):
    """An ACTIVE home holding a PORTABLE_OOH device in a cell paying 4200 cents.

    With the boost armed the cell base is 5250 cents and the out-of-home
    supplement takes the gross above the 5000-cent per-period cap.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 4, "base_incentive_cents": 4200}]
    )
    built = _active_household_with_ooh(panel, market["id"], cells[0]["id"])
    built["market"] = market
    built["cell"] = cells[0]
    return built


class TestIncentivePeriodCap:
    """The per-period cap is applied last, after the fault penalty."""

    def test_the_cap_clamps_a_gross_that_exceeds_it(self, panel: PanelHarness):
        """A gross of 5463 with no penalty pays exactly the 5000-cent cap.

        PRD 3.4: "The period amount is the lesser of the gross minus the penalty
        and the hard per-period cap of 5000 cents."

        Design: Corner/calculations/incentive_period_cap_clamps_after_the_fault_penalty_is_subtracted
        """
        built = _ooh_accrual_home(panel)
        home = built["household"]["id"]
        portable = panel.read_meter(built["portable"]["id"])
        assert portable["meter_type"] == "PORTABLE_OOH"
        assert portable["install_status"] == "INSTALLED"
        assert portable["health_status"] == "HEALTHY"

        panel.accrue(home, period_label="2026-08")

        healthy = expected_accrual_breakdown(4200, 1.25, 0, 0.0000, True, False)
        assert healthy["cell_base"] == 5250
        assert healthy["tenure_amount"] == 5250
        assert healthy["compliance_bonus"] == 0
        # 5250 * 0.0405 is 212.625, which rounds half up to 213.
        assert healthy["ooh_supplement"] == round_half_up_to_int(212.625) == 213
        assert healthy["gross"] == 5250 + 213 == 5463
        assert healthy["fault_penalty"] == 0
        assert healthy["period_amount"] == INCENTIVE_PERIOD_CAP_CENTS == 5000

        row = panel.read_household(home)
        assert row["accrual_periods"][0]["accrued_cents"] == 5000
        assert row["incentive_accrued_cents"] == 5000
        holder = panel.read_market(built["market"]["id"])
        assert holder["incentive_budget_committed_cents"] == 5000
        assert holder["incentive_budget_reserved_cents"] == expected_boost_reservation(4200, 4)
        assert holder["incentive_budget_reserved_cents"] == 4200

    def test_the_penalty_is_subtracted_from_the_gross_before_the_cap_is_read(
        self, panel: PanelHarness
    ):
        """5463 minus 1366 is 4097, which is below the cap and is what is paid.

        PRD 3.4: "The fault penalty is 25 percent of that gross, rounded to a
        whole cent, and applies only when the household holds at least one meter
        whose `health_status` is `FAULTED`; otherwise it is 0."

        Design: Corner/calculations/incentive_period_cap_clamps_after_the_fault_penalty_is_subtracted
        """
        built = _ooh_accrual_home(panel)
        home = built["household"]["id"]
        panel.accrue(home, period_label="2026-08")
        assert panel.read_household(home)["incentive_accrued_cents"] == 5000

        faulted = validate_success(
            panel.client.report_meter_fault(
                panel.tech, built["portable"]["id"], fault_code="NO_SIGNAL"
            ),
            200,
        )
        assert faulted["health_status"] == "FAULTED"
        assert faulted["last_fault_code"] == "NO_SIGNAL"
        assert faulted["fault_count"] == 1
        # Health and installation are independent dimensions, so step 6 still sees
        # an INSTALLED out-of-home device and still pays the supplement.
        assert faulted["install_status"] == "INSTALLED"
        # A faulted PORTABLE_OOH stops the cascade at link 1: the home stays in tab.
        assert panel.read_household(home)["status"] == "ACTIVE"
        cell = panel.read_quota_cell(built["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == expected_fill_rate(1, 4) == 0.2500

        panel.accrue(home, period_label="2026-09")

        penalised = expected_accrual_breakdown(4200, 1.25, 0, 0.0000, True, True)
        assert penalised["gross"] == 5463
        # 5463 * 0.25 is 1365.75, which rounds half up to 1366.
        assert penalised["fault_penalty"] == round_half_up_to_int(1365.75) == 1366
        assert penalised["period_amount"] == 5463 - 1366 == 4097
        # Clamping first and only then subtracting would have paid 3634.
        assert penalised["period_amount"] != INCENTIVE_PERIOD_CAP_CENTS - 1366

        row = panel.read_household(home)
        assert row["accrual_periods"][1]["period_label"] == "2026-09"
        assert row["accrual_periods"][1]["accrued_cents"] == 4097
        assert row["incentive_accrued_cents"] == 5000 + 4097 == 9097
        holder = panel.read_market(built["market"]["id"])
        assert holder["incentive_budget_committed_cents"] == 9097
        assert holder["incentive_budget_reserved_cents"] == 4200


def _basic_dataset_placement(panel: PanelHarness):
    """A BASIC subscriber holding a SCHEDULED_DATASET row for 11 cells.

    The row is placed while the run is still `WEIGHTED`, so its `due_at` is null
    until publication starts the commercial clock at 2026-08-11.
    """
    base = panel.weighted_run()
    client = panel.create_client([base["market"]["id"]], tier="BASIC")
    assert client["tier_base_fee_cents"] == TIER_TABLE["BASIC"]["tier_base_fee_cents"] == 25000
    assert client["delivery_sla_hours"] == TIER_TABLE["BASIC"]["delivery_sla_hours"] == 168
    assert client["custom_analysis_quota"] == TIER_TABLE["BASIC"]["custom_analysis_quota"] == 0

    placement = panel.schedule_deliverable(
        client["id"], base["run"]["id"], requested_cell_count=11
    )
    assert placement["kind"] == "SCHEDULED_DATASET"
    assert placement["state"] == "SCHEDULED"
    assert placement["due_at"] is None
    assert placement["question"] is None
    assert placement["revision_count"] == 0
    assert placement["gross_cents"] == 0
    assert placement["total_cents"] == 0

    panel.set_clock("2026-08-11T00:00:00Z")
    base["run"] = panel.publish_run(base["run"]["id"])
    base["client"] = client
    base["placement"] = placement
    return base


class TestDeliverableBillingBracket:
    """The volume bracket at exactly 80000 gross, and the SLA clock behind it."""

    def test_publication_sets_the_due_date_from_the_tier_service_level(
        self, panel: PanelHarness
    ):
        """168 BASIC hours after publication at 2026-08-11 is 2026-08-18.

        PRD 3.8: "Its `due_at` is set immediately to the logical clock plus the
        client's `delivery_sla_hours` when the pinned run is already `PUBLISHED`,
        and is otherwise left null until that run publishes."

        Design: Corner/calculations/billing_volume_bracket_at_exactly_eighty_thousand_gross
        """
        base = _basic_dataset_placement(panel)
        assert base["run"]["state"] == "PUBLISHED"

        due = panel.read_deliverable(base["placement"]["id"])
        assert due["state"] == "SCHEDULED"
        # 168 hours is exactly 7 days.
        assert _instant(due["due_at"]) == "2026-08-18T00:00:00"
        assert due["gross_cents"] == 0
        assert due["discount_cents"] == 0
        assert due["late_penalty_cents"] == 0
        assert due["total_cents"] == 0

        # A BASIC quota of 0 means the analyst path is closed to this client, so
        # the dataset placement is the only row that can ever be priced.
        refused = panel.client.create_custom_analysis(
            panel.rep,
            client_id=base["client"]["id"],
            processing_run_id=base["run"]["id"],
            question="Which suburban cells drove the week-over-week lift?",
            requested_cell_count=3,
        )
        validate_error(refused, "ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED")
        assert panel.read_client(base["client"]["id"])["custom_analysis_used"] == 0

    def test_a_gross_of_exactly_eighty_thousand_takes_both_middle_brackets(
        self, panel: PanelHarness
    ):
        """25000 + 11 * 5000 is 80000, so the rates are 0.10 and 0.015.

        PRD 3.8: "The penalty rate is 0.000 when `gross_cents` is below 80000,
        0.015 when it is at least 80000 but below 150000, and 0.025 when it is
        150000 or more. This bracket is keyed on the **gross** figure and not on
        the discounted net".

        Design: Corner/calculations/billing_volume_bracket_at_exactly_eighty_thousand_gross
        """
        base = _basic_dataset_placement(panel)

        # Exactly 86400 seconds past the deadline: the ceiling makes that 1 day.
        panel.set_clock("2026-08-19T00:00:00Z")
        delivered = validate_success(
            panel.client.dispatch_deliverable(panel.rep, base["placement"]["id"]), 200
        )
        assert delivered["state"] == "DELIVERED"
        assert delivered["findings_summary"] is None
        assert _instant(delivered["delivered_at"]) == "2026-08-19T00:00:00"

        expected = expected_billing(25000, 11, days_late=1)
        assert expected["gross_cents"] == 25000 + 11 * 5000 == 80000
        assert expected["volume_discount_rate"] == 0.10
        assert expected["discount_cents"] == 8000
        assert expected["penalty_rate"] == 0.015
        assert expected["late_penalty_cents"] == 1200
        assert expected["total_cents"] == 80000 - 8000 - 1200 == 70800

        assert delivered["days_late"] == 1
        assert delivered["gross_cents"] == 80000
        assert delivered["discount_cents"] == 8000
        assert delivered["late_penalty_cents"] == 1200
        assert delivered["total_cents"] == 70800

        # The penalty the client paid is simultaneously credited back to it.
        assert panel.read_client(base["client"]["id"])["delivery_sla_credit_cents"] == 1200


def _governance_base(panel: PanelHarness):
    """A PUBLISHED baseline run pinned to a target rule set, plus one subscriber.

    The target thresholds are an `outlier_weight_ratio_cap` of 2.5, an
    `invalid_tuning_max_minutes` of 900 and a `missing_interval_ascription_minutes`
    of 60, so each impact dimension can be moved one at a time.
    """
    base = panel.published_run(
        outlier_weight_ratio_cap=2.5,
        invalid_tuning_max_minutes=900,
        missing_interval_ascription_minutes=60,
    )
    base["client"] = panel.create_client([base["market"]["id"]])
    panel.set_clock("2026-08-11T00:00:00Z")
    return base


class TestMethodologyImpactScore:
    """Three weighted sub-scores, each clamped at 1.0 before weighting."""

    def test_a_twelve_minute_ascription_move_lands_exactly_on_the_moderate_floor(
        self, panel: PanelHarness
    ):
        """12/60 weighted at 0.25 is exactly 0.0500; 11/60 is 0.0458 and MINOR.

        PRD 3.9: "`impact_tier` follows from that figure: `MATERIAL` at 0.1500 or
        above, `MODERATE` at 0.0500 or above but below 0.1500, and `MINOR` below
        0.0500."

        Design: Corner/calculations/impact_tier_boundary_at_five_hundredths_and_the_subscore_cap
        """
        base = _governance_base(panel)
        target = base["rule_set"]
        market_id = base["market"]["id"]
        baseline_run_id = base["run"]["id"]

        moderate_proposal = panel.draft_rule_set(
            outlier_weight_ratio_cap=2.5,
            invalid_tuning_max_minutes=900,
            missing_interval_ascription_minutes=72,
        )
        drafted = panel.draft_change(target["id"], moderate_proposal["id"], [market_id])
        assert drafted["impact_delta_pct"] == 0.0000
        assert drafted["impact_tier"] is None

        moderate = panel.assess_change(drafted["id"], baseline_run_id)
        subs = expected_impact_subscores(target, moderate_proposal)
        assert float(subs["ascription"]) == 12 / 60 == 0.2
        assert float(subs["cap"]) == 0.0
        assert float(subs["tuning"]) == 0.0
        assert expected_impact_delta_pct(target, moderate_proposal) == 0.0500

        assert moderate["state"] == "IMPACT_ASSESSED"
        assert moderate["impact_delta_pct"] == 0.0500
        assert moderate["impact_tier"] == expected_impact_tier(0.0500) == "MODERATE"
        assert moderate["notification_lead_hours"] == NOTIFICATION_LEAD_HOURS["MODERATE"] == 336
        assert moderate["revision_count"] == 0
        assert moderate["version"] > drafted["version"]
        # The analysis copies the baseline projection: 100000 * 600 / 1440 is
        # 41666.6666..., so the run projected 41667 households.
        assert moderate["baseline_projected_average_audience"] == 41667
        assert moderate["baseline_processing_run_id"] == baseline_run_id
        # The deadline belongs to notification, not to the analysis.
        assert moderate["notification_deadline_at"] is None

        panel.notify_change(drafted["id"])
        notified = panel.read_change(drafted["id"])
        assert notified["state"] == "NOTIFIED"
        assert notified["notified_client_count"] == 1
        # 336 hours after 2026-08-11 is 14 days.
        assert _instant(notified["notification_deadline_at"]) == "2026-08-25T00:00:00"

        # One minute less of movement drops the change a whole tier.
        minor_proposal = panel.draft_rule_set(
            outlier_weight_ratio_cap=2.5,
            invalid_tuning_max_minutes=900,
            missing_interval_ascription_minutes=71,
        )
        minor_draft = panel.draft_change(target["id"], minor_proposal["id"], [market_id])
        minor = panel.assess_change(minor_draft["id"], baseline_run_id)
        # 11/60 is 0.18333..., and 0.25 * 0.18333... is 0.0458333..., so 0.0458.
        assert expected_impact_delta_pct(target, minor_proposal) == 0.0458
        assert minor["impact_delta_pct"] == 0.0458
        assert minor["impact_delta_pct"] < 0.0500
        assert minor["impact_tier"] == expected_impact_tier(0.0458) == "MINOR"
        assert minor["notification_lead_hours"] == NOTIFICATION_LEAD_HOURS["MINOR"] == 72

        panel.notify_change(minor_draft["id"])
        # 72 hours after 2026-08-11 is 3 days.
        assert _instant(
            panel.read_change(minor_draft["id"])["notification_deadline_at"]
        ) == "2026-08-14T00:00:00"

    def test_a_runaway_cap_sub_score_is_clamped_to_one_before_it_is_weighted(
        self, panel: PanelHarness
    ):
        """|10.0 - 2.5| / 2.5 is 3.0, clamped to 1.0, so the total is its own weight.

        PRD 3.9: "Each dimension yields a normalised sub-score capped at 1.0
        **before** weighting, so no single dimension can carry the total past its
        own weight".

        Design: Corner/calculations/impact_tier_boundary_at_five_hundredths_and_the_subscore_cap
        """
        base = _governance_base(panel)
        target = base["rule_set"]
        assert target["outlier_weight_ratio_cap"] == 2.5

        proposal = panel.draft_rule_set(
            outlier_weight_ratio_cap=10.0,
            invalid_tuning_max_minutes=900,
            missing_interval_ascription_minutes=60,
        )
        subs = expected_impact_subscores(target, proposal)
        assert abs(10.0 - 2.5) / 2.5 == 3.0
        assert float(subs["cap"]) == 1.0
        assert float(subs["tuning"]) == 0.0
        assert float(subs["ascription"]) == 0.0
        assert expected_impact_delta_pct(target, proposal) == 0.4000

        drafted = panel.draft_change(
            target["id"], proposal["id"], [base["market"]["id"]]
        )
        assessed = panel.assess_change(drafted["id"], base["run"]["id"])
        # 0.40 * 1.0 rather than 0.40 * 3.0, which would have been 1.2000.
        assert assessed["impact_delta_pct"] == 0.4000
        assert assessed["impact_delta_pct"] < 1.2000
        assert assessed["impact_tier"] == expected_impact_tier(0.4000) == "MATERIAL"
        assert assessed["notification_lead_hours"] == NOTIFICATION_LEAD_HOURS["MATERIAL"] == 720
        assert assessed["baseline_projected_average_audience"] == 41667

        panel.notify_change(drafted["id"])
        notified = panel.read_change(drafted["id"])
        assert notified["notified_client_count"] == 1
        # 720 hours after 2026-08-11 is 30 days.
        assert _instant(notified["notification_deadline_at"]) == "2026-09-10T00:00:00"
        rows = panel.notifications_of_change(drafted["id"])
        assert len(rows) == 1
        assert rows[0]["impact_tier"] == "MATERIAL"
        assert rows[0]["disclosed_delta_pct"] == 0.4000
