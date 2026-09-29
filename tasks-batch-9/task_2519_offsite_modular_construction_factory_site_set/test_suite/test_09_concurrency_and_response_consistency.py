"""Two writers looking at the same aggregate, and derived numbers that never lag.

Opening a design revision and loading a module onto a truck are the two writes
that fan out far enough to demand the writer prove its picture of the parent is
current: a design engineer quotes the project version it last read, a transport
coordinator quotes the load version it last read, and a value that has moved on
underneath them is answered with a refusal that leaves the target row exactly as
it was. Alongside that, the plant's and the project's version counters are the
things those refusals are compared against, so they must move once per write and
stand still on every read, including the heavy computed set-readiness view.

The second half of this file exercises the other side of the same coin. Nothing
in this domain settles after the fact: the work-in-progress value recomputed by a
station advance is already in the advance response, the project's phase is right
on the very next read with no nudging write in between, and a load that has just
acquired an overwidth module reports its re-priced permit fee, its escort
obligation and its survey posture inside the load response itself.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_PROJECT_VERSION,
    ERR_STALE_SHIPMENT_VERSION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_ledger,
    assert_module_dimensions,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_SUBMITTER,
    PROGRAM_ADMIN,
    TRANSPORT_COORDINATOR,
)


# The fields a caller reads off a load and off a project that are not stored as
# written but re-derived from the rows underneath them.
_SHIPMENT_DERIVED_FIELDS = (
    "status",
    "route_survey_state",
    "max_envelope_class",
    "loaded_module_count",
    "permit_fee_cents",
    "escort_required",
    "escort_confirmed",
    "version",
)

_PROJECT_DERIVED_FIELDS = (
    "phase",
    "permit_posture",
    "modules_set_count",
    "modules_connected_count",
    "wip_certified_cents",
    "funded_to_date_cents",
    "version",
)


def _derived(resource, fields):
    """The subset of a row a second identical read has to reproduce exactly."""
    return {name: resource[name] for name in fields}


@pytest.fixture
def project_whose_version_moved_under_the_engineer(api):
    """A bare project, plus one site weather observation that advanced it.

    The observation is the cheapest legitimate way to move a project version, so
    the engineer holding the version it read at project creation is now one
    behind through no fault of its own.
    """
    world = fx.world_plant_and_project(api)
    assert world.project["version"] == 1
    validate_success(
        api.record_weather_observation(
            world.project_id,
            f.weather_payload(
                forecast_precip_probability_pct=20, forecast_wind_gust_mph=5
            ),
            world.superintendent,
        )
    )
    return world


def test_a_design_revision_opened_against_a_pre_observation_project_version_is_refused(
    project_whose_version_moved_under_the_engineer,
):
    """PRD §2.7: "Creating a design package requires `expected_project_version` in the request body, carrying the client's last observed `version` of the `Project` named by `project_id`."
    PRD §2.7: "If the project's stored `version` has advanced since the client read it — because a permit was decided, a module was set, a draw was certified, or a phase was re-derived — the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §3.1: "Recording an observation increments the project's `version`."

    Design: Corner/cross-cutting complexity layers/stale_expected_project_version_is_rejected_on_design_package_create
    """
    world = project_whose_version_moved_under_the_engineer
    assert world.project_version == 2, "the observation must advance the parent"

    validate_error(
        world.api.create_design_package(
            f.design_package_payload(world.project_id, 1),
            DESIGN_ENGINEER_SUBMITTER,
        ),
        ERR_STALE_PROJECT_VERSION,
    )

    # The refused create leaves the project exactly where the observation put it.
    project = world.refresh_project()
    assert project["version"] == 2, "a rejected create must not touch the project"
    assert project["phase"] == "PRECONSTRUCTION"
    _, meta = validate_paginated(
        world.api.list_design_packages({"project_id": world.project_id}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0, "the rejected attempt created nothing"


def test_the_revision_opens_once_the_engineer_re_reads_the_advanced_project_version(
    project_whose_version_moved_under_the_engineer,
):
    """PRD §2.7: "Both use the same mechanism: a non-optional input field carrying the client's last observed `version` of the parent, compared for equality against that parent's stored `version`, with a mismatch rejected before any state precondition is evaluated."
    PRD §3.2: "A new package is persisted in `freeze_state` `DRAFT` with `revision_round` at 0, `submitted_by_user_id`, `reviewed_by_user_id` and `review_note` all null, and `version` at 1; creating it also increments the project's `version`."

    Design: Corner/cross-cutting complexity layers/stale_expected_project_version_is_rejected_on_design_package_create
    """
    world = project_whose_version_moved_under_the_engineer

    package = validate_success(
        world.api.create_design_package(
            f.design_package_payload(world.project_id, 2),
            DESIGN_ENGINEER_SUBMITTER,
        ),
        expected_status=201,
    )

    assert package["freeze_state"] == "DRAFT"
    assert package["revision_round"] == 0
    assert package["version"] == 1
    assert world.project_version == 3, "creating the revision moves the parent again"
    rows, meta = validate_paginated(
        world.api.list_design_packages({"project_id": world.project_id}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == package["id"]


@pytest.fixture
def two_released_modules_and_an_empty_load(api):
    """Two modules off the end of the line and QC released, and a DRAFT load.

    Both modules are standard envelope on a single-state route, so the only thing
    separating the two loads is the load version each one quotes.
    """
    world = fx.world_qc_released_module(api)
    fx.add_module(world, "M-02", 2)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", world.factory["station_count"])
    fx.release_quality(world, "M-02")
    world.shipment = fx.create_shipment(api, world.project_id)
    assert world.shipment["version"] == 1
    assert world.shipment["loaded_module_count"] == 0
    return world


def test_a_second_module_loaded_against_the_pre_load_shipment_version_is_refused(
    two_released_modules_and_an_empty_load,
):
    """PRD §2.7: "Loading a module onto a shipment requires `expected_shipment_version` in the request body, carrying the client's last observed `version` of the `Shipment` named in the path."
    PRD §2.7: "A mismatch against the shipment's stored `version` is rejected with `ERR_STALE_SHIPMENT_VERSION` (HTTP 412)."
    PRD §3.6: "On success the module's `site_status` moves from `AT_FACTORY` to `LOADED`, its `shipment_id` is set to the shipment, the shipment's `loaded_module_count` increases by 1, and both rows take `version` increments."

    Design: Corner/cross-cutting complexity layers/stale_expected_shipment_version_is_rejected_on_load_module
    """
    world = two_released_modules_and_an_empty_load

    first = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-01"), 1),
            TRANSPORT_COORDINATOR,
        )
    )
    assert first["version"] == 2, "the first load is what invalidates the client's view"

    # The coordinator replays the version it read when the load was opened.
    validate_error(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-02"), 1),
            TRANSPORT_COORDINATOR,
        ),
        ERR_STALE_SHIPMENT_VERSION,
    )

    module = world.refresh_module("M-02")
    assert module["shipment_id"] is None, "a refused load must not book the module"
    assert_module_dimensions(
        module, production_status="LINE_COMPLETE", qc_status="RELEASED",
        site_status="AT_FACTORY",
    )
    shipment = world.refresh_shipment()
    assert_ledger(shipment, "loaded_module_count", 1)
    assert shipment["version"] == 2, "a rejected load must not touch the load"


def test_the_second_module_goes_aboard_once_the_refreshed_load_version_is_supplied(
    two_released_modules_and_an_empty_load,
):
    """PRD §2.8: "A shipment's `loaded_module_count` together with the set of modules whose `shipment_id` points at that shipment is a single referential quantity: unloading always decrements the count by exactly one per module removed."
    PRD §3.6: "On success the module's `site_status` moves from `AT_FACTORY` to `LOADED`, its `shipment_id` is set to the shipment, the shipment's `loaded_module_count` increases by 1, and both rows take `version` increments."

    Design: Corner/cross-cutting complexity layers/stale_expected_shipment_version_is_rejected_on_load_module
    """
    world = two_released_modules_and_an_empty_load

    after_first = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-01"), 1),
            TRANSPORT_COORDINATOR,
        )
    )
    after_second = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-02"), after_first["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    assert_ledger(after_second, "loaded_module_count", 2)
    assert after_second["version"] == 3, "one increment per accepted load"
    module = world.refresh_module("M-02")
    assert module["shipment_id"] == world.shipment_id
    assert_module_dimensions(module, site_status="LOADED")


@pytest.fixture
def freshly_registered_plant_and_project(api):
    """A plant and a project, both untouched since they were persisted."""
    world = fx.world_plant_and_project(api)
    assert world.factory["version"] == 1
    assert world.project["version"] == 1
    return world


def test_reading_the_plant_never_moves_its_version_counter(
    freshly_registered_plant_and_project,
):
    """PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."
    PRD §3.1: "A newly registered plant begins with `committed_line_minutes` at 0 and `version` at 1."

    Design: Corner/cross-cutting complexity layers/version_increments_exactly_once_per_write_and_never_on_reads
    """
    world = freshly_registered_plant_and_project

    first_read = validate_success(world.api.get_factory(world.factory_id, PROGRAM_ADMIN))
    second_read = validate_success(world.api.get_factory(world.factory_id, PROGRAM_ADMIN))
    rows, _ = validate_paginated(
        world.api.list_factories({"code": world.factory["code"]}, PROGRAM_ADMIN)
    )

    assert first_read["version"] == 1, "a read must not bump the row"
    assert second_read["version"] == 1, "nor must a second read"
    assert [row["version"] for row in rows] == [1], "nor must a list read"
    assert second_read["created_at"] == first_read["created_at"]
    assert_ledger(second_read, "committed_line_minutes", 0)


def test_each_line_state_change_moves_the_plant_version_by_exactly_one(
    freshly_registered_plant_and_project,
):
    """PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."
    PRD §3.1: "The change increments the plant's `version`."

    Design: Corner/cross-cutting complexity layers/version_increments_exactly_once_per_write_and_never_on_reads
    """
    world = freshly_registered_plant_and_project
    created_at = world.factory["created_at"]

    paused = validate_success(
        world.api.update_factory_line_state(
            world.factory_id, f.line_state_payload("PAUSED"), PROGRAM_ADMIN
        )
    )
    restarted = validate_success(
        world.api.update_factory_line_state(
            world.factory_id, f.line_state_payload("RUNNING"), PROGRAM_ADMIN
        )
    )

    # Two writes land on 2 then 3 — never on 3 in one hop.
    assert paused["line_state"] == "PAUSED"
    assert paused["version"] == 2
    assert restarted["line_state"] == "RUNNING"
    assert restarted["version"] == 3
    final_read = validate_success(world.api.get_factory(world.factory_id, PROGRAM_ADMIN))
    assert final_read["version"] == 3, "a final read is still stable"
    assert final_read["created_at"] == created_at, "created_at is the first persist"


def test_the_set_readiness_view_refreshes_derivations_without_writing_a_version(
    freshly_registered_plant_and_project,
):
    """PRD §3.1: "A heavier computed read — the set-readiness view, available to `ProgramAdmin`, `SiteSuperintendent` and `AuthorityHavingJurisdiction` — re-derives `permit_posture` and `phase`, refreshes the exposure clock on every module of the project, and refreshes the set counters before returning the project row; it is the view the field uses before deciding whether a lift may proceed."
    PRD §2.9: "Alongside those, several fields are **pure derivations**: they are recomputed by a full re-scan of the underlying children on every trigger, never incremented in place."
    PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."

    Design: Corner/cross-cutting complexity layers/version_increments_exactly_once_per_write_and_never_on_reads
    """
    world = freshly_registered_plant_and_project

    before = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))
    readiness = validate_success(
        world.api.get_set_readiness(world.project_id, PROGRAM_ADMIN)
    )
    after = validate_success(world.api.get_project(world.project_id, PROGRAM_ADMIN))

    assert before["version"] == 1
    assert readiness["version"] == 1, "the computed read writes no version"
    assert after["version"] == 1, "and the row is unchanged afterwards"
    assert readiness["id"] == world.project_id
    assert readiness["phase"] == "PRECONSTRUCTION"
    assert readiness["permit_posture"] == "DUAL_BLOCKED"
    assert readiness["created_at"] == before["created_at"]


def test_the_advance_station_response_already_carries_the_recomputed_work_in_progress_value(
    api,
):
    """PRD §3.4: "The first advance from `SLOTTED` moves `production_status` to `IN_LINE`, increases `station_index` by `stations_advanced` capped at the plant's `station_count`, recomputes `wip_earned_cents`, re-derives the project's `phase` from `DESIGN_FROZEN` up to `IN_PRODUCTION`, and increments both the module's and the project's `version`."
    PRD §3.4: "When the module's `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` *and* its `qc_status` is not `HOLD`, the earned value is the plant's `wip_unit_value_cents` multiplied by the module's `station_index`, divided by the plant's `station_count`, and rounded half up to a whole cent."

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response
    """
    world = fx.world_slotted_module(api)

    module = validate_success(
        api.advance_station(
            world.module_id(), f.advance_payload(3), world.factory_manager
        )
    )

    # 8,750,000 cents of unit value, three of six stations complete.
    assert_module_dimensions(module, production_status="IN_LINE")
    assert module["station_index"] == 3
    assert_cents(module["wip_earned_cents"], 4375000, "wip_earned_cents")


def test_the_project_phase_reads_in_production_on_the_very_next_read(api):
    """PRD §3.7: "Otherwise, if any module of the project has `production_status` `IN_LINE` or `LINE_COMPLETE`, `phase` is `IN_PRODUCTION`."
    PRD §3.1: "Reading a single project re-derives `permit_posture` and `phase` before responding, so a read is never stale even if the last mutation that should have moved them was applied elsewhere."

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response
    """
    world = fx.world_slotted_module(api)
    before = validate_success(api.get_project(world.project_id, PROGRAM_ADMIN))
    assert before["phase"] == "DESIGN_FROZEN", "a slotted module has not reached the line"

    validate_success(
        api.advance_station(
            world.module_id(), f.advance_payload(3), world.factory_manager
        )
    )

    # No intervening write: the next read of the project is the immediate one.
    after = validate_success(api.get_project(world.project_id, PROGRAM_ADMIN))
    assert after["phase"] == "IN_PRODUCTION"


@pytest.fixture
def overwidth_module_and_a_two_state_load(api):
    """A two-hundred-inch module, released for transport, and a WA to OR load.

    Two hundred inches clears the sixteen-foot ceiling, so the first module
    aboard re-prices the load, obliges escorts and demands a route survey.
    """
    world = fx.world_qc_released_module(
        api,
        module_code="M-02",
        set_sequence_index=2,
        module_overrides={"width_in": 200},
    )
    assert world.module("M-02")["envelope_class"] == "OVERWIDTH"
    world.shipment = fx.create_shipment(api, world.project_id, ["WA", "OR"])
    assert world.shipment["max_envelope_class"] == "STANDARD"
    assert world.shipment["status"] == "DRAFT"
    assert world.shipment["route_survey_state"] == "NOT_REQUIRED"
    return world


def test_the_load_module_response_carries_the_repriced_envelope_fee_and_escort_obligation(
    overwidth_module_and_a_two_state_load,
):
    """PRD §3.6: "Otherwise, if `width_in` is greater than 192 inches — sixteen feet — or `height_in` is greater than 162 inches, or `gross_weight_lb` is greater than 80,000 pounds, then `envelope_class` is `OVERWIDTH`."
    PRD §3.6: "`permit_fee_cents` is then a base state permit fee of $250.00 — that is 25,000 cents — multiplied by the number of entries in `route_state_codes`, multiplied again by that class multiplier."
    PRD §3.6: "When a load in `route_survey_state` `NOT_REQUIRED` acquires a module that raises `max_envelope_class` to `OVERWIDTH` or `SUPERLOAD`, the survey axis moves from `NOT_REQUIRED` to `REQUIRED` and the fee and escort obligation are recomputed; if the transport axis was still at `DRAFT`, it moves in the same operation from `DRAFT` to `SURVEY_REQUIRED`."

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response
    """
    world = overwidth_module_and_a_two_state_load

    shipment = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-02"), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    # 25,000 cents of base fee, two route states, an overwidth multiplier of 2.
    assert shipment["max_envelope_class"] == "OVERWIDTH"
    assert_cents(shipment["permit_fee_cents"], 100000, "permit_fee_cents")
    assert shipment["escort_required"] is True
    assert shipment["route_survey_state"] == "REQUIRED"
    assert shipment["status"] == "SURVEY_REQUIRED"
    assert_ledger(shipment, "loaded_module_count", 1)


def test_repeating_the_read_returns_the_same_derived_values_with_nothing_settling_afterwards(
    overwidth_module_and_a_two_state_load,
):
    """PRD §3.6: "`escort_required` becomes true when `max_envelope_class` is `SUPERLOAD`, and also when `max_envelope_class` is `OVERWIDTH` and the route crosses two or more states; otherwise it is false, and whenever it is false the shipment's `escort_confirmed` is forced back to false as well."
    PRD §2.9: "Alongside those, several fields are **pure derivations**: they are recomputed by a full re-scan of the underlying children on every trigger, never incremented in place."
    PRD §3.1: "Reading a single project re-derives `permit_posture` and `phase` before responding, so a read is never stale even if the last mutation that should have moved them was applied elsewhere."

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response
    """
    world = overwidth_module_and_a_two_state_load
    written = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-02"), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    first_load_read = validate_success(
        world.api.get_shipment(world.shipment_id, TRANSPORT_COORDINATOR)
    )
    second_load_read = validate_success(
        world.api.get_shipment(world.shipment_id, TRANSPORT_COORDINATOR)
    )
    first_project_read = validate_success(
        world.api.get_project(world.project_id, PROGRAM_ADMIN)
    )
    second_project_read = validate_success(
        world.api.get_project(world.project_id, PROGRAM_ADMIN)
    )

    # The write's own view of the load is already the settled one.
    assert _derived(first_load_read, _SHIPMENT_DERIVED_FIELDS) == _derived(
        written, _SHIPMENT_DERIVED_FIELDS
    )
    assert _derived(second_load_read, _SHIPMENT_DERIVED_FIELDS) == _derived(
        first_load_read, _SHIPMENT_DERIVED_FIELDS
    )
    assert first_project_read["phase"] == "IN_PRODUCTION"
    assert _derived(second_project_read, _PROJECT_DERIVED_FIELDS) == _derived(
        first_project_read, _PROJECT_DERIVED_FIELDS
    )
