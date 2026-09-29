"""Where a module stands, where its load stands, and what may still be done to either.

A volumetric module carries three lifecycles at once — the factory line, the
third-party quality file and the journey from the plant floor to the foundation —
and a fresh module has to sit at the head of all three simultaneously. Its load
carries two more: the transport lifecycle that runs from an open trailer to a
delivered one, and the route-survey axis that moves independently of it. This
file walks a standard single-state load from an empty trailer through permit,
dispatch and delivery, checking that each step drags the module aboard along with
it, and then pushes on the doors that are supposed to be shut: dispatching an
empty trailer, closing connections on a module that never left the plant,
cancelling a load already standing on site, and recording the same delivery
twice.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_MODULE_NOT_SET,
    ERR_SHIPMENT_NOT_DISPATCHED,
    ERR_SHIPMENT_NOT_PERMITTED,
    ERR_SHIPMENT_TERMINAL,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_fields,
    assert_instant,
    assert_module_dimensions,
    assert_two_decimal_value,
)
from test_helpers.test_users import TRANSPORT_COORDINATOR


@pytest.fixture
def project_with_a_draft_revision(api):
    """A plant, an agency panel, a project and one unfrozen design revision.

    Creating a module reads the revision and the project only, so the revision
    is deliberately left in DRAFT: nothing here depends on the review chain.
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    return world


def _permit_the_load(world) -> dict:
    """Record the route survey and the transport permit it produced."""
    world.shipment = validate_success(
        world.api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    return world.shipment


def _put_the_load_on_the_road(world) -> dict:
    """Permit the load and dispatch it."""
    _permit_the_load(world)
    world.shipment = validate_success(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )
    return world.shipment


def test_a_new_module_sits_at_the_head_of_all_three_state_dimensions(
    project_with_a_draft_revision,
):
    """PRD §3.4: "A newly created module begins with `production_status` `PLANNED`, `qc_status` `PENDING`, `site_status` `AT_FACTORY`, `station_index` at 0, `wip_earned_cents` at 0, `exposure_open_hours` at 0, `shipment_id` null, `line_slot_start`, `line_slot_end`, `pick_window_start`, `pick_window_end`, `pick_radius_ft`, `rigging_weight_lb`, `crane_utilization_pct`, `set_at` and `connected_at` all null, `line_slot_minutes` at 0, `defect_count_factory` and `defect_count_field` at 0, and `version` at 1."
    PRD §2.9: "A `ModuleUnit` carries three, on one row, advancing independently: `production_status` tracks the factory line, `qc_status` tracks third-party quality, and `site_status` tracks logistics and the site."

    Design: Corner/state_machines/module_create_starts_all_three_dimensions_in_their_initial_states
    """
    world = project_with_a_draft_revision

    module = validate_success(
        world.api.create_module(
            f.module_payload(world.project_id, world.package_id, "M-01", 1),
            world.factory_manager,
        ),
        201,
    )

    assert_module_dimensions(
        module,
        production_status="PLANNED",
        qc_status="PENDING",
        site_status="AT_FACTORY",
    )
    assert module["station_index"] == 0
    assert_cents(module["wip_earned_cents"], 0, "wip_earned_cents")
    assert_two_decimal_value(module["exposure_open_hours"], 0.00, "exposure_open_hours")


def test_a_new_module_has_no_line_slot_no_pick_window_and_no_load(
    project_with_a_draft_revision,
):
    """PRD §3.4: "A newly created module begins with `production_status` `PLANNED`, `qc_status` `PENDING`, `site_status` `AT_FACTORY`, `station_index` at 0, `wip_earned_cents` at 0, `exposure_open_hours` at 0, `shipment_id` null, `line_slot_start`, `line_slot_end`, `pick_window_start`, `pick_window_end`, `pick_radius_ft`, `rigging_weight_lb`, `crane_utilization_pct`, `set_at` and `connected_at` all null, `line_slot_minutes` at 0, `defect_count_factory` and `defect_count_field` at 0, and `version` at 1."
    PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."

    Design: Corner/state_machines/module_create_starts_all_three_dimensions_in_their_initial_states
    """
    world = project_with_a_draft_revision

    module = validate_success(
        world.api.create_module(
            f.module_payload(world.project_id, world.package_id, "M-01", 1),
            world.factory_manager,
        ),
        201,
    )

    for field in (
        "line_slot_start",
        "line_slot_end",
        "pick_window_start",
        "pick_window_end",
        "pick_radius_ft",
        "rigging_weight_lb",
        "crane_utilization_pct",
        "set_at",
        "connected_at",
        "shipment_id",
    ):
        assert module[field] is None, f"{field} must be null on a fresh module"
    assert module["line_slot_minutes"] == 0
    assert module["defect_count_factory"] == 0
    assert module["defect_count_field"] == 0
    assert_common_fields(module, expected_version=1)


def test_a_new_module_takes_the_declared_pair_and_connection_scope_defaults(
    project_with_a_draft_revision,
):
    """PRD §3.4: "`pair_role` describes the module's role in a mated pair sharing a corridor wall and takes `SINGLE`, `PAIR_A` or `PAIR_B`, defaulting to `SINGLE`."
    PRD §3.4: "`connection_scope_owner` names who owns the module-to-module connection scope at this module's interface and takes `FACTORY`, `FIELD` or `SHARED`, defaulting to `FIELD`."
    PRD §3.4: "Every comparison is strictly greater-than against the ceiling, so a module measuring exactly 192 inches wide, exactly 162 inches high and weighing exactly 80,000 pounds is still `STANDARD`."

    Design: Corner/state_machines/module_create_starts_all_three_dimensions_in_their_initial_states
    """
    world = project_with_a_draft_revision

    # 180 inches wide, 156 high and 76,600 pounds — under every ceiling.
    module = validate_success(
        world.api.create_module(
            f.module_payload(world.project_id, world.package_id, "M-01", 1),
            world.factory_manager,
        ),
        201,
    )

    assert module["pair_role"] == "SINGLE"
    assert module["pair_group_code"] is None
    assert module["connection_scope_owner"] == "FIELD"
    assert module["envelope_class"] == "STANDARD"


@pytest.fixture
def standard_load_with_one_module(api):
    """One QC released module aboard an open load routed inside its own state.

    The clock stands at 2026-09-01T08:00:00Z throughout, so every stamp the
    transport chain writes is that instant.
    """
    return fx.world_loaded_module(api)


def test_a_standard_load_reaches_permitted_without_ever_requiring_a_survey(
    standard_load_with_one_module,
):
    """PRD §3.6: "On success `route_survey_state` becomes `COMPLETED` — from `REQUIRED` on a load that acquired the obligation, or directly from `NOT_REQUIRED` on a standard load that never needed one — the transport axis moves to `PERMITTED` from either `DRAFT` or `SURVEY_REQUIRED`, `survey_completed_at`, `permit_expires_at` and `escort_confirmed` are persisted from the payload, and the shipment's `version` increments."
    PRD §3.6: "The axes are independent by design: a load can gain and then lose its survey obligation without the transport axis moving forward at all."

    Design: Corner/state_machines/shipment_survey_dispatch_deliver_walk_the_declared_transitions
    """
    world = standard_load_with_one_module
    version_before = world.shipment["version"]

    shipment = validate_success(
        world.api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )

    assert shipment["status"] == "PERMITTED"
    assert shipment["route_survey_state"] == "COMPLETED"
    assert_instant(shipment["survey_completed_at"], "2026-09-01T09:00:00Z")
    assert_instant(shipment["permit_expires_at"], "2026-09-20T00:00:00Z")
    assert shipment["version"] == version_before + 1


def test_dispatch_puts_the_permitted_load_and_its_module_on_the_road(
    standard_load_with_one_module,
):
    """PRD §3.6: "On success `status` moves from `PERMITTED` to `DISPATCHED`, `dispatched_at` is stamped with the current clock instant, every module aboard moves its `site_status` from `LOADED` to `IN_TRANSIT`, the project's `phase` is re-derived up to `SHIPPING`, and the shipment, every module aboard and the project all take `version` increments."
    PRD §3.7: "Otherwise, if any shipment of the project has `status` `DISPATCHED` or `DELIVERED`, `phase` is `SHIPPING`."

    Design: Corner/state_machines/shipment_survey_dispatch_deliver_walk_the_declared_transitions
    """
    world = standard_load_with_one_module
    _permit_the_load(world)

    shipment = validate_success(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )

    assert shipment["status"] == "DISPATCHED"
    assert_instant(shipment["dispatched_at"], f.DEFAULT_CLOCK, "dispatched_at")
    assert_module_dimensions(world.refresh_module(), site_status="IN_TRANSIT")
    assert world.refresh_project()["phase"] == "SHIPPING"


def test_delivery_lands_the_load_and_its_module_at_the_site(
    standard_load_with_one_module,
):
    """PRD §3.6: "On success `status` moves to `DELIVERED`, which is terminal, `delivered_at` is stamped with the current clock instant, every module carried moves its `site_status` from `IN_TRANSIT` to `DELIVERED`, the `basis_earned_cents` and `requested_cents` of every `DRAFT` draw request of the project are recomputed because delivered modules enter the milestone basis, and the shipment and every module take `version` increments."
    PRD §3.6: "`status` is the transport lifecycle, running `DRAFT`, `SURVEY_REQUIRED`, `PERMITTED`, `DISPATCHED` and `DELIVERED`, with `CANCELLED` as the other terminal outcome alongside `DELIVERED`."

    Design: Corner/state_machines/shipment_survey_dispatch_deliver_walk_the_declared_transitions
    """
    world = standard_load_with_one_module
    _put_the_load_on_the_road(world)

    shipment = validate_success(
        world.api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )

    assert shipment["status"] == "DELIVERED"
    assert_instant(shipment["delivered_at"], f.DEFAULT_CLOCK, "delivered_at")
    module = world.refresh_module()
    assert_module_dimensions(module, site_status="DELIVERED")
    assert module["shipment_id"] == world.shipment_id


def test_an_empty_draft_load_may_not_be_dispatched(api):
    """PRD §3.6: "The shipment's `status` must be `PERMITTED` and its `loaded_module_count` at least 1, or the attempt is `ERR_SHIPMENT_NOT_PERMITTED`, and the current clock instant must be strictly before `permit_expires_at`, or the attempt is `ERR_TRANSPORT_PERMIT_EXPIRED`."
    PRD §3.6: "A new load begins with `status` `DRAFT`, `route_survey_state` `NOT_REQUIRED`, `max_envelope_class` `STANDARD`, `loaded_module_count` 0, `permit_fee_cents` 0, `escort_required` false, `escort_confirmed` false, `survey_completed_at`, `permit_expires_at`, `dispatched_at`, `delivered_at` and `cancel_reason` all null, and `version` 1."

    Design: Corner/state_machines/shipment_dispatch_from_draft_is_rejected
    """
    world = fx.world_plant_and_project(api)
    world.shipment = fx.create_shipment(api, world.project_id)

    validate_error(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR),
        ERR_SHIPMENT_NOT_PERMITTED,
    )

    # An empty trailer is still sitting on the plant apron, undispatched.
    shipment = world.refresh_shipment()
    assert shipment["status"] == "DRAFT"
    assert shipment["dispatched_at"] is None
    assert shipment["loaded_module_count"] == 0
    assert shipment["version"] == 1


def test_connections_cannot_be_closed_on_a_module_still_standing_at_the_plant(
    project_with_a_draft_revision,
):
    """PRD §3.7: "The module's `site_status` must be `SET`, or the attempt is `ERR_MODULE_NOT_SET`."
    PRD §3.7: "Closing the connections moves `site_status` from `SET` to `CONNECTED` and requires `field_scope_signed_off` in the payload, optionally alongside a replacement `connection_scope_owner` and a `connected_note`."
    PRD §3.7: "Closing connections stamps `connected_at` with the current clock instant and freezes `exposure_open_hours` at the elapsed span between `set_at` and `connected_at`."

    Design: Corner/state_machines/close_connections_on_an_at_factory_module_is_rejected
    """
    world = project_with_a_draft_revision
    world.modules["M-01"] = fx.create_module(
        world.api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )

    # The payload is complete and the field scope is signed off; the transition
    # simply does not exist from AT_FACTORY.
    validate_error(
        world.api.close_connections(
            world.module_id(),
            f.close_connections_payload(
                True, connected_note="attempt from the wrong state"
            ),
            world.superintendent,
        ),
        ERR_MODULE_NOT_SET,
    )

    module = world.refresh_module()
    assert_module_dimensions(module, site_status="AT_FACTORY")
    assert module["connected_at"] is None
    assert module["version"] == 1


@pytest.fixture
def load_already_standing_on_site(api):
    """A standard single-state load surveyed, dispatched and delivered.

    Its one module has reached the site, so both the transport lifecycle and the
    module's own site dimension read DELIVERED.
    """
    return fx.world_delivered_module(api)


def test_a_delivered_load_can_no_longer_be_cancelled(load_already_standing_on_site):
    """PRD §3.6: "Cancellation takes a required `reason` and requires `status` to be `DRAFT`, `SURVEY_REQUIRED` or `PERMITTED`; cancelling a load that has already been dispatched, delivered or cancelled is rejected with `ERR_SHIPMENT_TERMINAL`."
    PRD §3.6: "On success `status` moves to `DELIVERED`, which is terminal, `delivered_at` is stamped with the current clock instant, every module carried moves its `site_status` from `IN_TRANSIT` to `DELIVERED`, the `basis_earned_cents` and `requested_cents` of every `DRAFT` draw request of the project are recomputed because delivered modules enter the milestone basis, and the shipment and every module take `version` increments."

    Design: Corner/state_machines/cancel_a_delivered_shipment_is_rejected
    """
    world = load_already_standing_on_site
    version_before = world.shipment["version"]

    validate_error(
        world.api.cancel_shipment(
            world.shipment_id, f.cancel_payload(), TRANSPORT_COORDINATOR
        ),
        ERR_SHIPMENT_TERMINAL,
    )

    shipment = world.refresh_shipment()
    assert shipment["status"] == "DELIVERED"
    assert shipment["cancel_reason"] is None
    assert shipment["version"] == version_before


def test_a_refused_cancellation_leaves_the_delivered_module_aboard_its_load(
    load_already_standing_on_site,
):
    """PRD §3.6: "Every module aboard is unloaded — `shipment_id` cleared to null and `site_status` moved from `LOADED` back to `AT_FACTORY` — and the load's aggregate fields are reset wholesale: `loaded_module_count` to 0, `max_envelope_class` to `STANDARD`, `route_survey_state` to `NOT_REQUIRED`, `escort_required` to false, `permit_fee_cents` to 0 and `permit_expires_at` to null."
    PRD §3.6: "Cancellation takes a required `reason` and requires `status` to be `DRAFT`, `SURVEY_REQUIRED` or `PERMITTED`; cancelling a load that has already been dispatched, delivered or cancelled is rejected with `ERR_SHIPMENT_TERMINAL`."

    Design: Corner/state_machines/cancel_a_delivered_shipment_is_rejected
    """
    world = load_already_standing_on_site

    validate_error(
        world.api.cancel_shipment(
            world.shipment_id, f.cancel_payload(), TRANSPORT_COORDINATOR
        ),
        ERR_SHIPMENT_TERMINAL,
    )

    # None of the wholesale reset may fire: the module is on the ground at site.
    assert world.refresh_shipment()["loaded_module_count"] == 1
    module = world.refresh_module()
    assert_module_dimensions(module, site_status="DELIVERED")
    assert module["shipment_id"] == world.shipment_id


def test_delivery_recorded_twice_is_refused_the_second_time(
    load_already_standing_on_site,
):
    """PRD §3.6: "Delivery — recordable by either the `TransportCoordinator` or the receiving `SiteSuperintendent` — takes an optional `arrived_at` and requires `status` `DISPATCHED`, or the attempt is `ERR_SHIPMENT_NOT_DISPATCHED`."
    PRD §3.6: "`status` is the transport lifecycle, running `DRAFT`, `SURVEY_REQUIRED`, `PERMITTED`, `DISPATCHED` and `DELIVERED`, with `CANCELLED` as the other terminal outcome alongside `DELIVERED`."

    Design: Corner/state_machines/delivering_an_already_delivered_shipment_twice_is_rejected
    """
    world = load_already_standing_on_site

    validate_error(
        world.api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR),
        ERR_SHIPMENT_NOT_DISPATCHED,
    )

    assert world.refresh_shipment()["status"] == "DELIVERED"


def test_the_refused_second_delivery_leaves_the_first_arrival_stamp_intact(
    load_already_standing_on_site,
):
    """PRD §3.6: "On success `status` moves to `DELIVERED`, which is terminal, `delivered_at` is stamped with the current clock instant, every module carried moves its `site_status` from `IN_TRANSIT` to `DELIVERED`, the `basis_earned_cents` and `requested_cents` of every `DRAFT` draw request of the project are recomputed because delivered modules enter the milestone basis, and the shipment and every module take `version` increments."
    PRD §3.6: "Delivery — recordable by either the `TransportCoordinator` or the receiving `SiteSuperintendent` — takes an optional `arrived_at` and requires `status` `DISPATCHED`, or the attempt is `ERR_SHIPMENT_NOT_DISPATCHED`."

    Design: Corner/state_machines/delivering_an_already_delivered_shipment_twice_is_rejected
    """
    world = load_already_standing_on_site
    first_arrival = world.shipment["delivered_at"]
    version_before = world.shipment["version"]

    validate_error(
        world.api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR),
        ERR_SHIPMENT_NOT_DISPATCHED,
    )

    # No re-stamp and no second version bump, so no draw basis could be
    # recomputed a second time either.
    shipment = world.refresh_shipment()
    assert_instant(shipment["delivered_at"], first_arrival, "delivered_at")
    assert shipment["version"] == version_before


@pytest.fixture
def released_module_and_empty_load(api):
    """A line-complete, QC released module and an empty load routed WA only."""
    world = fx.world_qc_released_module(api)
    world.shipment = fx.create_shipment(api, world.project_id, ["WA"])
    return world


def test_loading_a_module_moves_it_aboard_and_bumps_both_rows(
    released_module_and_empty_load,
):
    """PRD §3.6: "On success the module's `site_status` moves from `AT_FACTORY` to `LOADED`, its `shipment_id` is set to the shipment, the shipment's `loaded_module_count` increases by 1, and both rows take `version` increments."
    PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."

    Design: Corner/state_machines/load_module_applies_every_declared_side_effect
    """
    world = released_module_and_empty_load
    module_version_before = world.refresh_module()["version"]
    shipment_version_before = world.shipment["version"]

    shipment = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id(), shipment_version_before),
            TRANSPORT_COORDINATOR,
        )
    )

    assert shipment["loaded_module_count"] == 1
    assert shipment["version"] == shipment_version_before + 1
    module = world.refresh_module()
    assert_module_dimensions(module, site_status="LOADED")
    assert module["shipment_id"] == world.shipment_id
    assert module["version"] == module_version_before + 1


def test_a_standard_module_leaves_both_shipment_axes_where_they_were(
    released_module_and_empty_load,
):
    """PRD §3.6: "The shipment's `max_envelope_class` is the widest `envelope_class` among the modules currently aboard, ordering the classes `STANDARD` below `OVERWIDTH` below `SUPERLOAD`, and it is `STANDARD` whenever the load is empty."
    PRD §3.6: "When a load in `route_survey_state` `NOT_REQUIRED` acquires a module that raises `max_envelope_class` to `OVERWIDTH` or `SUPERLOAD`, the survey axis moves from `NOT_REQUIRED` to `REQUIRED` and the fee and escort obligation are recomputed; if the transport axis was still at `DRAFT`, it moves in the same operation from `DRAFT` to `SURVEY_REQUIRED`."
    PRD §3.6: "Because the standard multiplier is zero, a standard load is fee-free no matter how many states the route crosses."

    Design: Corner/state_machines/load_module_applies_every_declared_side_effect
    """
    world = released_module_and_empty_load

    shipment = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id(), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    # The recompute is observable precisely by what it declines to change.
    assert shipment["max_envelope_class"] == "STANDARD"
    assert shipment["route_survey_state"] == "NOT_REQUIRED"
    assert shipment["status"] == "DRAFT"
    assert_cents(shipment["permit_fee_cents"], 0, "permit_fee_cents")


def test_a_standard_load_crossing_two_states_is_still_fee_free_and_escort_free(api):
    """PRD §3.6: "`permit_fee_cents` is then a base state permit fee of $250.00 — that is 25,000 cents — multiplied by the number of entries in `route_state_codes`, multiplied again by that class multiplier."
    PRD §3.6: "`escort_required` becomes true when `max_envelope_class` is `SUPERLOAD`, and also when `max_envelope_class` is `OVERWIDTH` and the route crosses two or more states; otherwise it is false, and whenever it is false the shipment's `escort_confirmed` is forced back to false as well."

    Design: Corner/state_machines/load_module_applies_every_declared_side_effect
    """
    world = fx.world_qc_released_module(api)
    world.shipment = fx.create_shipment(api, world.project_id, ["WA", "OR"])

    shipment = validate_success(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id(), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    # 25,000 cents times two states times the standard multiplier of zero.
    assert_cents(shipment["permit_fee_cents"], 0, "permit_fee_cents")
    assert shipment["escort_required"] is False
    assert shipment["escort_confirmed"] is False
