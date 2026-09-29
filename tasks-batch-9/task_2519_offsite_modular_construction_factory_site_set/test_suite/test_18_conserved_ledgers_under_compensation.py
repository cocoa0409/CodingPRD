"""Two ledgers taken out and put back, and asked to land on their old value.

The plant's committed minutes are added by a takt claim and removed by a release
and again by line completion; the project's certified work-in-progress is added
by a certification and removed by a rejection. Neither may drift: after a full
out-and-back cycle each ledger has to read exactly what it read before.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_module_dimensions
from test_helpers.test_users import LENDER_DRAW_ADMINISTRATOR, PROGRAM_ADMIN


@pytest.fixture
def one_module_waiting_on_an_empty_line(api):
    """A released project with a single PLANNED module and an idle ledger."""
    world = fx.world_with_module(api)
    return world


def test_releasing_the_takt_claim_returns_the_plant_ledger_to_zero(
    one_module_waiting_on_an_empty_line,
):
    """PRD §2.5: "The plant's `committed_line_minutes` is the sum of the occupancy length of every module of that plant currently holding a line slot; releasing a slot subtracts back exactly what scheduling it added, and a module completing the line releases its minutes as well."
    PRD §3.4: "It moves `production_status` from `SLOTTED` back to `PLANNED`, subtracts exactly the module's `line_slot_minutes` from the plant's `committed_line_minutes` so the ledger returns to its pre-schedule value, increments the plant's `version`, clears `line_slot_start` and `line_slot_end` and sets `line_slot_minutes` to 0, re-derives the project's `phase`, and increments the module's and the project's `version`."

    Design: Difficulty/compensating_invariant/factory_committed_line_minutes_returns_to_zero_after_release_reslot_and_line_completion
    """
    world = one_module_waiting_on_an_empty_line
    assert world.refresh_factory()["committed_line_minutes"] == 0

    claimed = fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    assert claimed["line_slot_minutes"] == 540
    assert world.refresh_factory()["committed_line_minutes"] == 540

    released = validate_success(
        world.api.release_line_slot(
            world.module_id(),
            {"reason": "sheathing shortage"},
            world.factory_manager,
        )
    )

    assert released["line_slot_minutes"] == 0
    assert world.refresh_factory()["committed_line_minutes"] == 0


def test_reslotting_recommits_exactly_the_same_minutes(
    one_module_waiting_on_an_empty_line,
):
    """PRD §3.4: "The module's `line_slot_minutes` is then the plant's `station_count` multiplied by that effective takt, in whole minutes."
    PRD §3.4: "On success the plant's `committed_line_minutes` increases by the module's `line_slot_minutes` and the plant's `version` increments; the module's `wip_earned_cents` is recomputed under the station-progress rule, which at `station_index` 0 yields 0; and the module's `version` increments."

    Design: Difficulty/compensating_invariant/factory_committed_line_minutes_returns_to_zero_after_release_reslot_and_line_completion
    """
    world = one_module_waiting_on_an_empty_line
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    validate_success(
        world.api.release_line_slot(
            world.module_id(), {"reason": "sheathing shortage"}, world.factory_manager
        )
    )

    reclaimed = fx.schedule_slot(world, "M-01", "2026-09-04T14:00:00Z")

    # The line is empty again, so the second claim costs what the first did.
    assert reclaimed["line_slot_minutes"] == 540
    assert world.refresh_factory()["committed_line_minutes"] == 540


def test_completing_the_line_clears_the_ledger_and_leaves_the_interval_as_history(
    one_module_waiting_on_an_empty_line,
):
    """PRD §3.4: "A terminating advance, where `station_index` plus `stations_advanced` reaches or exceeds the plant's `station_count`, moves `production_status` to `LINE_COMPLETE`, sets `station_index` exactly to the plant's `station_count`, subtracts the module's `line_slot_minutes` from the plant's `committed_line_minutes` and increments the plant's `version` — the line is released, and the interval stays on the module as history while no longer occupying capacity — recomputes `wip_earned_cents`, which under the station-progress rule now yields the plant's full `wip_unit_value_cents`, recomputes the `basis_earned_cents` and `requested_cents` of the project's `DRAFT` draw requests, and increments the module's `version`."

    Design: Difficulty/compensating_invariant/factory_committed_line_minutes_returns_to_zero_after_release_reslot_and_line_completion
    """
    world = one_module_waiting_on_an_empty_line
    fx.schedule_slot(world, "M-01", "2026-09-02T14:00:00Z")
    validate_success(
        world.api.release_line_slot(
            world.module_id(), {"reason": "sheathing shortage"}, world.factory_manager
        )
    )
    fx.schedule_slot(world, "M-01", "2026-09-04T14:00:00Z")

    finished = fx.advance_stations(world, "M-01", 6)

    assert_module_dimensions(finished, production_status="LINE_COMPLETE")
    assert finished["station_index"] == 6
    assert finished["line_slot_start"] is not None
    assert world.refresh_factory()["committed_line_minutes"] == 0

    still_slotted = validate_success(
        world.api.list_modules({"production_status": "SLOTTED"}, PROGRAM_ADMIN)
    )
    assert still_slotted == []


@pytest.fixture
def a_certified_draw_on_a_finished_module(api):
    """A module off the end of the line and a certified deposit draw against it."""
    world = fx.world_line_complete_module(api)
    draw = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1)
    draw = validate_success(
        api.certify_draw(draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR)
    )
    return world, draw


def test_rejecting_a_certified_draw_reverses_the_project_ledger_exactly(
    a_certified_draw_on_a_finished_module,
):
    """PRD §3.9: "When the draw being rejected was in `CERTIFIED`, the project's `wip_certified_cents` is reduced by exactly the amount that certifying it added, so the ledger returns to its prior value with no drift; rejecting a `DRAFT` draw touches no ledger because nothing was ever added."

    Design: Difficulty/compensating_invariant/project_wip_certified_cents_reverses_exactly_on_draw_rejection
    """
    world, draw = a_certified_draw_on_a_finished_module
    assert_cents(draw["certified_cents"], 1750000, "certified_cents")
    assert_cents(
        world.refresh_project()["wip_certified_cents"], 1750000, "wip_certified_cents"
    )

    validate_success(
        world.api.reject_draw(
            draw["id"],
            f.reject_payload("lender inspection report unsigned"),
            LENDER_DRAW_ADMINISTRATOR,
        )
    )

    assert_cents(
        world.refresh_project()["wip_certified_cents"], 0, "wip_certified_cents"
    )


def test_the_rejected_draw_zeroes_its_own_money_fields(
    a_certified_draw_on_a_finished_module,
):
    """PRD §3.9: "Rejection moves `status` to `REJECTED`, stores the supplied reason, and resets `certified_cents`, `retainage_held_cents` and `net_funded_cents` to 0."
    PRD §3.9: "`retainage_held_cents` is `certified_cents` multiplied by the project's `retainage_pct` — 5 percent by default — rounded half up to a whole cent."

    Design: Difficulty/compensating_invariant/project_wip_certified_cents_reverses_exactly_on_draw_rejection
    """
    world, draw = a_certified_draw_on_a_finished_module
    assert_cents(draw["retainage_held_cents"], 87500, "retainage_held_cents")
    assert_cents(draw["net_funded_cents"], 1662500, "net_funded_cents")

    rejected = validate_success(
        world.api.reject_draw(
            draw["id"],
            f.reject_payload("lender inspection report unsigned"),
            LENDER_DRAW_ADMINISTRATOR,
        )
    )

    assert rejected["status"] == "REJECTED"
    assert_cents(rejected["certified_cents"], 0, "certified_cents")
    assert_cents(rejected["retainage_held_cents"], 0, "retainage_held_cents")
    assert_cents(rejected["net_funded_cents"], 0, "net_funded_cents")


def test_a_replacement_draw_certifies_to_the_same_amount_with_no_drift(
    a_certified_draw_on_a_finished_module,
):
    """PRD §3.9: "The whole basis computation is then **re-run from live module state and never copied** from the provisional figures."
    PRD §3.9: "A successful certification moves `status` from `DRAFT` to `CERTIFIED`, stamps `certified_at` with the current clock instant, adds `certified_cents` to the project's `wip_certified_cents`, and increments both the draw's and the project's `version`."
    PRD §2.5: "Alongside it, `funded_to_date_cents` accumulates `net_funded_cents` over the project's draws in status `FUNDED`."

    Design: Difficulty/compensating_invariant/project_wip_certified_cents_reverses_exactly_on_draw_rejection
    """
    world, draw = a_certified_draw_on_a_finished_module
    validate_success(
        world.api.reject_draw(
            draw["id"],
            f.reject_payload("lender inspection report unsigned"),
            LENDER_DRAW_ADMINISTRATOR,
        )
    )

    replacement = fx.create_draw(
        world.api, world.project_id, world.agency_id, "WIP_DEPOSIT", 2
    )
    replacement = validate_success(
        world.api.certify_draw(
            replacement["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        )
    )

    assert_cents(replacement["certified_cents"], 1750000, "certified_cents")
    assert_cents(replacement["retainage_held_cents"], 87500, "retainage_held_cents")
    assert_cents(replacement["net_funded_cents"], 1662500, "net_funded_cents")

    project = world.refresh_project()
    assert_cents(project["wip_certified_cents"], 1750000, "wip_certified_cents")
    # Nothing has been funded yet, so no cash has moved on either draw.
    assert_cents(project["funded_to_date_cents"], 0, "funded_to_date_cents")

    certified = validate_success(
        world.api.list_draw_requests(
            {"project_id": world.project_id, "status": "CERTIFIED"},
            LENDER_DRAW_ADMINISTRATOR,
        )
    )
    assert [row["id"] for row in certified] == [replacement["id"]]
