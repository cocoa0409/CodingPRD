"""
Thresholds probed at exact equality and one step either side.

The grade tiers are stepped, so the tonnage a panel reports is discontinuous at
95.0 and at 90.0 and flat in between. The depot's storm threshold is a ratio the
system deliberately compares cross-multiplied, so the displayed percentage can read
90.00 while the depot is still open.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_amount,
    assert_posture_view_threshold,
    assert_rate_per_hour,
    assert_tons,
)
from test_helpers.constants import (
    COVERED,
    DEPOT_OPEN,
    DEPOT_SURGE,
    HIGHWAY_DEICING,
    MEDIUM,
)
from test_helpers.test_users import MINE_PLANNER

CLOCK = "2026-08-10T00:00:00Z"

# One geology, one grade knob: 600,000 t of base tonnage and a 0.024 insolubles
# penalty, so only the grade tier can move the answer.
GEOMETRY = dict(
    gross_tons_in_place=1000000,
    extraction_ratio_pct=60,
    insolubles_pct=5.0,
    pillar_recovery_allowed=True,
)


def _panel_at_grade(api, mine_id, panel_code, grade_pct_nacl):
    return get_success_data(
        api.create_panel(
            f.panel_payload(
                mine_id,
                panel_code=panel_code,
                grade_pct_nacl=grade_pct_nacl,
                **GEOMETRY,
            ),
            MINE_PLANNER,
        ),
        201,
    )


def test_top_grade_tier_holds_at_exactly_95_and_drops_one_hundredth_below(api):
    """
    A grade of exactly 95.0 is inside the top tier, and 94.99 — one hundredth below —
    steps down to 0.96, moving the reported reserve by the whole tier step of
    23424.00 t.

    PRD §3.2: "**Grade tier.** Choose a single grade factor from the assayed
    `grade_pct_nacl`: 1.00 when the grade is at least 95.0; 0.96 when the grade is at
    least 90.0 but below 95.0; 0.88 when the grade is below 90.0."

    PRD §3.2: "**Base tonnage.** Multiply `gross_tons_in_place` by
    `extraction_ratio_pct` divided by 100."

    PRD §3.2: "Take the smaller of that combined figure and 72 percent of
    `gross_tons_in_place`, and round the winner half up to two decimal places."

    Design: Difficulty/boundary_precision_check/grade_tier_boundary_at_exactly_95_and_90_pct_nacl
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)

    at_threshold = _panel_at_grade(api, mine["id"], "P-A", 95.0)
    below_threshold = _panel_at_grade(api, mine["id"], "P-B", 94.99)

    assert_tons(at_threshold["recoverable_tons"], 617600.00, "recoverable_tons")
    assert_tons(below_threshold["recoverable_tons"], 594176.00, "recoverable_tons")
    # 600000 x 0.04 x 0.976 — neither figure is clipped by the 720000.00 ceiling.
    assert_tons(
        round(
            float(at_threshold["recoverable_tons"])
            - float(below_threshold["recoverable_tons"]),
            2,
        ),
        23424.00,
        "grade tier step",
    )


def test_the_middle_grade_band_is_closed_below_at_90_and_open_above(api):
    """
    Two different grades produce the same tonnage: 94.99 and exactly 90.0 both sit in
    the middle band, while 89.99 falls out of it. That identity is what proves the band
    includes its lower bound and excludes its upper one.

    PRD §3.2: "**Grade tier.** Choose a single grade factor from the assayed
    `grade_pct_nacl`: 1.00 when the grade is at least 95.0; 0.96 when the grade is at
    least 90.0 but below 95.0; 0.88 when the grade is below 90.0."

    PRD §3.2: "**Insolubles penalty.** Take `insolubles_pct` minus 3.0, floor that
    difference at zero, multiply it by 0.012, and cap the result at 0.20."

    Design: Difficulty/boundary_precision_check/grade_tier_boundary_at_exactly_95_and_90_pct_nacl
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)

    just_inside_top = _panel_at_grade(api, mine["id"], "P-B", 94.99)
    at_lower_bound = _panel_at_grade(api, mine["id"], "P-C", 90.0)
    below_lower_bound = _panel_at_grade(api, mine["id"], "P-D", 89.99)

    assert_tons(just_inside_top["recoverable_tons"], 594176.00, "recoverable_tons")
    assert_tons(at_lower_bound["recoverable_tons"], 594176.00, "recoverable_tons")
    assert float(at_lower_bound["recoverable_tons"]) == float(
        just_inside_top["recoverable_tons"]
    ), "94.99 and 90.0 must share the middle tier factor"
    assert_tons(below_lower_bound["recoverable_tons"], 547328.00, "recoverable_tons")


def _shed_at_35999_point_1_tons(api):
    """
    Fill a 40000 t covered shed to 35999.10 t through two passed batches: 39000 t of
    dry medium-screen feed yields 35100.00 t and 999 t yields a further 899.10 t.
    """
    fx.set_clock(api, CLOCK)
    world = fx.hoisted_run(
        api,
        mine_kwargs=dict(name="Retsof", rated_hoist_tons_per_day=24000),
        panel_kwargs=dict(panel_code="P-1", pillar_recovery_allowed=True),
        hoisted_tons=40000,
        planned_tons=40000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-13T00:00:00Z",
    )
    # 40000 t spread over 48 hours, stored to four decimal places.
    assert_rate_per_hour(world["run"]["planned_tons_per_hour"], 833.3333)

    world["depot"] = fx.create_depot(
        api, name="Depot A", covered_capacity_tons=40000, open_pad_capacity_tons=20000
    )
    for input_tons in (39000, 999):
        fx.mint_lot(
            api,
            world["run"]["id"],
            world["depot"]["id"],
            product_line=HIGHWAY_DEICING,
            screen_spec=MEDIUM,
            anticaking_ppm=30,
            input_tons=input_tons,
            moisture_pct=0.0,
            storage_kind=COVERED,
        )
    return world


def test_the_shed_stays_open_while_the_displayed_utilisation_already_reads_ninety(api):
    """
    At 35999.10 t of a 40000 t shed the stored percentage rounds up to 90.00, yet the
    cross-multiplied test is 3599910.00 against 3600000 and fails, so the depot is still
    `OPEN`. Reading the rounded field instead would surge a whole batch too early.

    PRD §3.6: "Whenever tonnage lands at a depot — a quality-control pass minting a lot,
    or a shipment being received — the server tests the depot's `covered_stored_tons`
    multiplied by 100 against its `covered_capacity_tons` multiplied by 90, and a depot
    that is `OPEN` moves `OPEN → SURGE` when that product reaches or exceeds the
    threshold."

    PRD §3.6: "The comparison is on the unrounded cross-multiplied ratio, not on the
    two-decimal `covered_utilization_pct` (see §2.7)."

    PRD §3.6: "`covered_utilization_pct` is `covered_stored_tons` multiplied by 100,
    divided by `covered_capacity_tons`, rounded half up to two decimal places — and it
    reads exactly 0 when `covered_capacity_tons` is 0, rather than erroring."

    PRD §2.7: "The depot storm threshold compares stored covered tonnage multiplied by
    100 against covered capacity multiplied by 90, so it is insensitive to the 2-decimal
    rounding of `covered_utilization_pct`; a shed holding 35,999 tons of a 40,000-ton
    capacity stays open, while 36,000 tons flips it."

    Design: Difficulty/boundary_precision_check/covered_storage_auto_surge_at_exactly_ninety_percent_of_capacity
    """
    world = _shed_at_35999_point_1_tons(api)

    view = fx.storage_posture(api, world["depot"]["id"])
    assert_tons(view["covered_stored_tons"], 35999.10, "covered_stored_tons")
    # 89.99775 rounds half up to a displayed 90.00 while the real ratio is below 90.
    assert_amount(view["covered_utilization_pct"], 90.00, 2, "covered_utilization_pct")
    assert view["depot_state"] == DEPOT_OPEN
    assert_posture_view_threshold(view)

    assert fx.refresh_depot(api, world["depot"]["id"])["depot_state"] == DEPOT_OPEN


def test_nine_tenths_of_a_ton_more_lands_on_the_threshold_and_auto_surges(api):
    """
    One more batch of a single ton yields 0.90 t and lands the shed on exactly
    36000.00 t: 3600000 against 3600000 crosses on equality, so the posture flips
    without any operator naming it.

    PRD §3.6: "a depot that is `OPEN` moves `OPEN → SURGE` when that product reaches or
    exceeds the threshold"

    PRD §3.6: "An automatic move leaves `storm_state_set_by_user_id` untouched — it
    stays null when no manual call ever happened — and increments the depot's `version`
    by 1."

    PRD §3.5: "The batch's `yield_tons` is `input_tons` multiplied by the screen's yield
    factor, multiplied by one minus `moisture_pct` divided by 100, multiplied by the
    rework loss factor, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/covered_storage_auto_surge_at_exactly_ninety_percent_of_capacity
    """
    world = _shed_at_35999_point_1_tons(api)
    before = fx.refresh_depot(api, world["depot"]["id"])

    minted = fx.mint_lot(
        api,
        world["run"]["id"],
        world["depot"]["id"],
        product_line=HIGHWAY_DEICING,
        screen_spec=MEDIUM,
        anticaking_ppm=30,
        input_tons=1,
        moisture_pct=0.0,
        storage_kind=COVERED,
    )
    assert_tons(minted["batch"]["yield_tons"], 0.90, "yield_tons")

    depot = fx.refresh_depot(api, world["depot"]["id"])
    assert_tons(depot["covered_stored_tons"], 36000.00, "covered_stored_tons")
    assert depot["depot_state"] == DEPOT_SURGE
    # 36000.00 is still inside the 40000 t shed, so nothing was refused.
    assert_tons(depot["covered_capacity_tons"], 40000.00, "covered_capacity_tons")
    assert depot["storm_state_set_by_user_id"] is None
    assert depot["version"] > before["version"]

    view = fx.storage_posture(api, world["depot"]["id"])
    assert_amount(view["covered_utilization_pct"], 90.00, 2, "covered_utilization_pct")
    assert view["depot_state"] == DEPOT_SURGE
