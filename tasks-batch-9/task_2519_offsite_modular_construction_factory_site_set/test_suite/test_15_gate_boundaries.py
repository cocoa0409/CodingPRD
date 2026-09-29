"""Two gates examined one unit either side of their exact threshold.

The crane gate is an integer cross-product, so the interesting weights are the
one that makes the two sides equal and the one that is a single pound heavier.
The freeze floor is an integer score, so the interesting revisions are the one
scoring exactly the floor and the one scoring a single point below it.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CRANE_CAPACITY_EXCEEDED,
    ERR_FACTORY_COMPATIBILITY_TOO_LOW,
)
from test_helpers.assertions import assert_instant, assert_two_decimal_value
from test_helpers.test_users import (
    DESIGN_ENGINEER_REVIEWER,
    DESIGN_ENGINEER_SUBMITTER,
)


@pytest.fixture
def three_modules_astride_the_crane_gate(api):
    """Modules at 76,599, 76,600 and 76,601 pounds against a 96,000 pound row.

    With 5,000 pounds of rigging the three rigged weights are 81,599, 81,600 and
    81,601, and 85 percent of the chart row is exactly 81,600.
    """
    world = fx.world_plant_and_project(api, project_overrides={"forecast_wind_gust_mph": 0})
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    for code, index, weight in (
        ("M-01", 1, 76600),
        ("M-02", 2, 76601),
        ("M-03", 3, 76599),
    ):
        fx.add_module(world, code, index, gross_weight_lb=weight)
    return world


def test_a_rigged_weight_exactly_at_the_crane_gate_is_admitted(
    three_modules_astride_the_crane_gate,
):
    """PRD §3.7: "The feasibility gate is an exact integer comparison that never sees the rounded value: the pick is infeasible when the rigged weight multiplied by 100 is strictly greater than 85 multiplied by the derated capacity."
    PRD §3.7: "On success the module's `pick_window_start`, `pick_window_end`, `pick_radius_ft` and `rigging_weight_lb` are persisted along with the computed `crane_utilization_pct`, and the module's `version` increments."

    Design: Difficulty/boundary_precision_check/crane_utilization_exactly_85_percent_integer_cross_product_on_schedule_pick
    """
    world = three_modules_astride_the_crane_gate

    module = validate_success(
        world.api.schedule_pick(
            world.module_id("M-01"),
            f.pick_payload("2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z", 90, 5000),
            world.superintendent,
        )
    )

    # 8,160,000 on both sides of the comparison, and the gate is strictly greater.
    assert_two_decimal_value(
        module["crane_utilization_pct"], 85.00, "crane_utilization_pct"
    )
    assert_instant(module["pick_window_start"], "2026-09-10T09:00:00Z")


def test_one_pound_over_the_crane_gate_is_refused(three_modules_astride_the_crane_gate):
    """PRD §3.7: "A lift that displays exactly 85.00 percent after rounding can therefore still be infeasible, and an infeasible lift is rejected with `ERR_CRANE_CAPACITY_EXCEEDED`."
    PRD §2.2: "A newly created module begins with `production_status` `PLANNED`, `qc_status` `PENDING`, `site_status` `AT_FACTORY`, `station_index` at 0, `wip_earned_cents` at 0, `exposure_open_hours` at 0, `shipment_id` null, `line_slot_start`, `line_slot_end`, `pick_window_start`, `pick_window_end`, `pick_radius_ft`, `rigging_weight_lb`, `crane_utilization_pct`, `set_at` and `connected_at` all null, `line_slot_minutes` at 0, `defect_count_factory` and `defect_count_field` at 0, and `version` at 1."

    Design: Difficulty/boundary_precision_check/crane_utilization_exactly_85_percent_integer_cross_product_on_schedule_pick
    """
    world = three_modules_astride_the_crane_gate

    # 8,160,100 is strictly greater than 8,160,000, though it still displays as
    # 85.00 percent once rounded to two decimals.
    validate_error(
        world.api.schedule_pick(
            world.module_id("M-02"),
            f.pick_payload("2026-09-10T11:30:00Z", "2026-09-10T12:15:00Z", 90, 5000),
            world.superintendent,
        ),
        ERR_CRANE_CAPACITY_EXCEEDED,
    )

    module = world.refresh_module("M-02")
    assert module["pick_window_start"] is None
    assert module["crane_utilization_pct"] is None


def test_one_pound_under_the_crane_gate_is_admitted(
    three_modules_astride_the_crane_gate,
):
    """PRD §3.7: "Third, the rigged weight is the module's `gross_weight_lb` plus its `rigging_weight_lb`."
    PRD §3.7: "The module's `crane_utilization_pct` is stored as the rigged weight multiplied by 100, divided by the derated capacity, rounded half up to two decimal places — but that stored figure is display only."

    Design: Difficulty/boundary_precision_check/crane_utilization_exactly_85_percent_integer_cross_product_on_schedule_pick
    """
    world = three_modules_astride_the_crane_gate

    module = validate_success(
        world.api.schedule_pick(
            world.module_id("M-03"),
            f.pick_payload("2026-09-10T14:00:00Z", "2026-09-10T14:45:00Z", 90, 5000),
            world.superintendent,
        )
    )

    # 8,159,900 is below the gate; 81,599 of 96,000 pounds is 84.9990 percent,
    # which still displays as 85.00 once rounded to two decimals.
    assert_two_decimal_value(
        module["crane_utilization_pct"], 85.00, "crane_utilization_pct"
    )
    assert module["pick_radius_ft"] == 90


def _submit_for_review(world, package_id):
    return validate_success(
        world.api.submit_design_package(
            package_id, f.submit_payload(), DESIGN_ENGINEER_SUBMITTER
        )
    )


def test_a_compatibility_score_of_exactly_seventy_clears_the_freeze_floor(api):
    """PRD §3.2: "The `factory_compatibility_score` must be at least 70 — a score of exactly 70 is freezable."
    PRD §3.2: "Each uncoordinated site-built scope item counted in `field_scope_items_open` contributes 5 penalty points."
    PRD §3.2: "The maturity of connection detailing contributes a fixed penalty by state: 40 points while `connection_detail_state` is `NOT_STARTED`, 15 points at `FACTORY_DETAILED`, 5 points at `FIELD_COORDINATED`, and nothing at `COMPLETE`."

    Design: Difficulty/boundary_precision_check/compatibility_score_exactly_70_freeze_floor_on_review_decision
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api,
        world.project_id,
        world.project["version"],
        connection_detail_state="FIELD_COORDINATED",
        open_connection_conflicts=0,
        field_scope_items_open=5,
    )
    # Five points of detailing maturity plus twenty-five for five open field
    # items is a thirty point penalty, landing exactly on the floor.
    assert world.package["factory_compatibility_score"] == 70
    _submit_for_review(world, world.package_id)

    frozen = validate_success(
        api.decide_design_review(
            world.package_id,
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        )
    )

    assert frozen["freeze_state"] == "FROZEN"
    assert frozen["factory_compatibility_score"] == 70
    assert world.refresh_project()["phase"] == "DESIGN_FROZEN"


def test_a_compatibility_score_one_point_below_the_floor_is_refused(api):
    """PRD §3.2: "Any of those three failing yields `ERR_FACTORY_COMPATIBILITY_TOO_LOW`."
    PRD §3.2: "Each unresolved module-to-module connection clash counted in `open_connection_conflicts` contributes 8 penalty points."
    PRD §3.2: "The `factory_compatibility_score` is then 100 minus the accumulated penalty, floored at 0 so it never goes negative, and it is stored as an integer in the range 0 through 100."

    Design: Difficulty/boundary_precision_check/compatibility_score_exactly_70_freeze_floor_on_review_decision
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api,
        world.project_id,
        world.project["version"],
        connection_detail_state="COMPLETE",
        open_connection_conflicts=2,
        field_scope_items_open=3,
    )
    # Sixteen points for two clashes plus fifteen for three open field items is
    # a thirty-one point penalty — one point short of freezable.
    assert world.package["factory_compatibility_score"] == 69
    _submit_for_review(world, world.package_id)

    validate_error(
        api.decide_design_review(
            world.package_id,
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        ),
        ERR_FACTORY_COMPATIBILITY_TOO_LOW,
    )

    assert world.refresh_package()["freeze_state"] == "IN_REVIEW"
    assert world.refresh_project()["phase"] == "PRECONSTRUCTION"


def test_a_successor_revision_that_regresses_the_detailing_cannot_freeze(api):
    """PRD §3.2: "**Factory compatibility** is the number that decides whether a revision may be frozen, and it is recomputed from the package's current detailing fields whenever the package is created, submitted, or reviewed."
    PRD §3.2: "The `factory_compatibility_score` must be at least 70 — a score of exactly 70 is freezable."

    Design: Difficulty/boundary_precision_check/compatibility_score_exactly_70_freeze_floor_on_review_decision
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api,
        world.project_id,
        world.project["version"],
        connection_detail_state="FIELD_COORDINATED",
        field_scope_items_open=5,
    )
    _submit_for_review(world, world.package_id)
    validate_success(
        api.decide_design_review(
            world.package_id,
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        )
    )

    successor = fx.create_design_package(
        api,
        world.project_id,
        world.project_version,
        revision_index=2,
        connection_detail_state="FIELD_COORDINATED",
        open_connection_conflicts=1,
        field_scope_items_open=5,
    )
    # One extra connection clash costs eight points, taking 70 down to 62.
    assert successor["factory_compatibility_score"] == 62
    _submit_for_review(world, successor["id"])

    validate_error(
        api.decide_design_review(
            successor["id"],
            f.review_decision_payload("FREEZE"),
            DESIGN_ENGINEER_REVIEWER,
        ),
        ERR_FACTORY_COMPATIBILITY_TOO_LOW,
    )

    still_in_review = validate_success(
        api.get_design_package(successor["id"], DESIGN_ENGINEER_SUBMITTER)
    )
    assert still_in_review["freeze_state"] == "IN_REVIEW"
    assert world.refresh_project()["phase"] == "DESIGN_FROZEN"
