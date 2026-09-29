"""Who may act, and on whose behalf, across the ten disciplines of the programme.

Ten disciplines write to this system and none of them trusts the others by
default. Some operations belong to exactly one of them — only the plant creates
modules, only the field lands them, only the lender certifies a draw, only the
officer of the matching track decides a permit application, and only the two
sides of a warranty argument may dispute its allocation. Other operations are
deliberately shared, and every declared holder of a shared operation has to be
able to run it. Three of the ten disciplines also carry the identifier of a
stored row rather than an operator string, so holding the right discipline is
not enough: an inspection agency cannot record under a sister agency, a field
crew cannot reach into another project's modules, and a plant cannot touch the
work of another plant.

The tests below attack each exclusive operation with its most plausible
neighbour, reach across aggregate boundaries with genuinely permitted roles, and
then exercise the shared operations from their second declared holder.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_OWNER,
    ERR_DRAW_NOT_FOUND,
    ERR_PERMIT_TRACK_ROLE_MISMATCH,
    ERR_ROLE_NOT_PERMITTED,
)
from test_helpers.assertions import assert_module_dimensions
from test_helpers.test_users import (
    AUTHORITY_HAVING_JURISDICTION,
    DESIGN_ENGINEER_SUBMITTER,
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    STATE_PROGRAM_OFFICER,
    TRANSPORT_COORDINATOR,
    WARRANTY_ADJUDICATOR,
    make_factory_manager_headers,
    make_inspector_headers,
    make_site_superintendent_headers,
)


@pytest.fixture
def five_exclusive_operations(api):
    """One target apiece for the five exclusive operations under attack.

    A module on the books, a filed local set application still awaiting its
    decision, a draft deposit draw and an open factory defect claim.
    """
    world = fx.world_with_module(api)
    world.set_permit = validate_success(
        api.create_permit(
            f.permit_payload(world.project_id, "LOCAL_AHJ", "SET"), PROGRAM_ADMIN
        ),
        201,
    )
    world.draw = fx.create_draw(api, world.project_id, world.agency_id)
    world.claim = validate_success(
        api.create_defect_claim(
            f.defect_claim_payload(world.module_id(), "FACTORY", 250000),
            world.factory_manager,
        ),
        201,
    )
    return world


def _the_field_creating_a_module(world):
    """The site superintendent trying to book a module into the plant."""
    return world.api.create_module(
        f.module_payload(world.project_id, world.package_id, "M-99", 9),
        world.superintendent,
    )


def _the_plant_setting_a_module(world):
    """The plant manager trying to land a module on the foundation."""
    return world.api.execute_set(
        world.module_id(), {"set_note": "not the plant's call"}, world.factory_manager
    )


def _the_carrier_certifying_a_draw(world):
    """The transport coordinator trying to certify the lender's draw."""
    return world.api.certify_draw(
        world.draw["id"], f.certify_payload(), TRANSPORT_COORDINATOR
    )


def _the_detailer_deciding_a_permit(world):
    """The design engineer trying to decide a building department application."""
    return world.api.decide_permit(
        world.set_permit["id"],
        f.permit_decision_payload("APPROVE"),
        DESIGN_ENGINEER_SUBMITTER,
    )


def _the_adjudicator_disputing_its_own_ruling(world):
    """The warranty adjudicator trying to dispute an allocation it owns."""
    return world.api.dispute_defect_claim(
        world.claim["id"],
        f.dispute_payload("the adjudicator cannot dispute"),
        WARRANTY_ADJUDICATOR,
    )


@pytest.mark.parametrize(
    "attempt",
    [
        _the_field_creating_a_module,
        _the_plant_setting_a_module,
        _the_carrier_certifying_a_draw,
        _the_detailer_deciding_a_permit,
        _the_adjudicator_disputing_its_own_ruling,
    ],
    ids=[
        "field_creating_a_module",
        "plant_setting_a_module",
        "carrier_certifying_a_draw",
        "detailer_deciding_a_permit",
        "adjudicator_disputing_its_own_ruling",
    ],
)
def test_a_neighbouring_discipline_is_refused_the_operation_it_does_not_own(
    five_exclusive_operations, attempt
):
    """PRD §2.1: "When both headers are well formed but the named role is not among the roles authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.6: "`ERR_ROLE_NOT_PERMITTED` — the caller's `X-User-Role` appears in the endpoint's authorised role list."
    PRD §2.1: "These two checks precede every other consideration in the system, including whether the resources named in the URL exist."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    validate_error(attempt(five_exclusive_operations), ERR_ROLE_NOT_PERMITTED)


def test_the_five_refusals_leave_the_module_roll_and_every_target_untouched(
    five_exclusive_operations,
):
    """PRD §2.1: "`FactoryProductionManager` is the plant manager: it creates modules, claims and releases takt slots, advances stations, and disputes warranty allocations charged to the factory."
    PRD §2.1: "`SiteSuperintendent` is the field superintendent: it records site weather, plans crane picks, sets modules, closes connections and raises field defect claims."
    PRD §2.1: "These two checks precede every other consideration in the system, including whether the resources named in the URL exist."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    world = five_exclusive_operations
    for attempt in (
        _the_field_creating_a_module,
        _the_plant_setting_a_module,
        _the_carrier_certifying_a_draw,
        _the_detailer_deciding_a_permit,
        _the_adjudicator_disputing_its_own_ruling,
    ):
        validate_error(attempt(world), ERR_ROLE_NOT_PERMITTED)

    # The refused module creation never reached the roll: M-01 stands alone.
    _, meta = validate_paginated(
        world.api.list_modules({"project_id": world.project_id}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1

    assert_module_dimensions(
        world.refresh_module(), production_status="PLANNED", site_status="AT_FACTORY"
    )
    draw = validate_success(
        world.api.get_draw_request(world.draw["id"], LENDER_DRAW_ADMINISTRATOR)
    )
    assert draw["status"] == "DRAFT"
    permit = validate_success(
        world.api.get_permit(world.set_permit["id"], PROGRAM_ADMIN)
    )
    assert permit["status"] == "SUBMITTED"
    claim = validate_success(
        world.api.get_defect_claim(world.claim["id"], WARRANTY_ADJUDICATOR)
    )
    assert claim["status"] == "OPEN"


def test_the_detailer_is_refused_the_permit_decision_before_any_track_reasoning(
    five_exclusive_operations,
):
    """PRD §2.1: "`DesignEngineer` creates design revisions, submits them for freeze review, and reviews a peer's submission."
    PRD §2.1: "Both roles appear on the decision endpoint's role list, so a cross-track attempt passes the role check and is then rejected with `ERR_PERMIT_TRACK_ROLE_MISMATCH` (HTTP 403)."
    PRD §2.1: "Second, permit decisions are bifurcated by track: a `StateProgramOfficer` may decide only applications whose `track` is `STATE_MODULAR_PROGRAM`, and an `AuthorityHavingJurisdiction` only applications whose `track` is `LOCAL_AHJ`."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    world = five_exclusive_operations
    approve = f.permit_decision_payload("APPROVE")

    # The design engineer is absent from the decide endpoint's role list, so it
    # never reaches the track comparison at rank 7.
    validate_error(
        world.api.decide_permit(
            world.set_permit["id"], approve, DESIGN_ENGINEER_SUBMITTER
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    # The state officer does hold the role and is stopped one rung lower, on the
    # local track it may not decide.
    validate_error(
        world.api.decide_permit(world.set_permit["id"], approve, STATE_PROGRAM_OFFICER),
        ERR_PERMIT_TRACK_ROLE_MISMATCH,
    )
    # And the authority having jurisdiction owns this track outright.
    decided = validate_success(
        world.api.decide_permit(
            world.set_permit["id"], approve, AUTHORITY_HAVING_JURISDICTION
        )
    )
    assert decided["status"] == "APPROVED"


def test_the_carrier_is_refused_a_draw_certification_before_the_draw_is_looked_up(
    five_exclusive_operations,
):
    """PRD §2.1: "`LenderDrawAdministrator` opens, certifies, funds and rejects construction draws."
    PRD §2.1: "`TransportCoordinator` builds loads, runs route surveys and transport permits, and dispatches, delivers and cancels shipments."
    PRD §2.1: "These two checks precede every other consideration in the system, including whether the resources named in the URL exist."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    world = five_exclusive_operations

    # No such draw exists, and the role check still answers first.
    validate_error(
        world.api.certify_draw(
            NON_EXISTENT_UUID, f.certify_payload(), TRANSPORT_COORDINATOR
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    # The lender, naming the same unresolvable identifier, is told the truth
    # about it — which is how we know the carrier never got that far.
    validate_error(
        world.api.certify_draw(
            NON_EXISTENT_UUID, f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        ),
        ERR_DRAW_NOT_FOUND,
    )


@pytest.fixture
def a_neighbourhood_of_foreign_aggregates(api):
    """Two plants, two projects and two accredited agencies, side by side.

    Rainier Flats is manufactured at Puget Modular Plant 1 and inspected by
    Cascade Inspection Services; its M-01 is off the end of the line, M-02 is
    still planned and M-03 holds a takt window. The second plant, the second
    project and the second agency exist only to lend their identifiers to a
    caller who has no business with the first project's work.
    """
    world = fx.world_line_complete_module(api)
    fx.add_module(world, "M-02", 2)
    fx.add_module(world, "M-03", 3)
    fx.schedule_slot(world, "M-03", "2026-09-03T14:00:00Z")
    world.other_factory = fx.create_factory(
        api, name="Puget Modular Plant 2", code="PMP2"
    )
    world.other_agency = fx.create_agency(
        api,
        name="Olympic Inspection Services",
        agency_code="OIS",
        per_inspection_fee_cents=110000,
    )
    world.other_project = fx.create_project(
        api,
        world.other_factory["id"],
        name="Cascade Commons",
        ahj_code="TAC",
        planned_module_count=2,
        contract_price_cents=1600000000,
    )
    return world


def _foreign_field_planning_a_pick(world):
    """A crane lift planned by the superintendent of a different project."""
    return world.api.schedule_pick(
        world.module_id(),
        f.pick_payload(fx.DEFAULT_PICK_WINDOW_START, fx.DEFAULT_PICK_WINDOW_END, 75, 4000),
        make_site_superintendent_headers(world.other_project["id"]),
    )


def _foreign_field_recording_the_weather(world):
    """A site observation recorded against a project the caller does not hold."""
    return world.api.record_weather_observation(
        world.project_id,
        f.weather_payload(forecast_precip_probability_pct=15, forecast_wind_gust_mph=8),
        make_site_superintendent_headers(world.other_project["id"]),
    )


@pytest.mark.parametrize(
    "attempt",
    [_foreign_field_planning_a_pick, _foreign_field_recording_the_weather],
    ids=["planning_a_pick", "recording_the_weather"],
)
def test_a_superintendent_holding_another_projects_identifier_is_turned_away(
    a_neighbourhood_of_foreign_aggregates, attempt
):
    """PRD §2.1: "When `X-User-Role` is `SiteSuperintendent`, `X-User-ID` is the `id` of the acting `Project`; ownership checks compare the `project_id` of the module or project being operated on to `X-User-ID`."
    PRD §2.1: "A violation of any of these three ownership comparisons is `ERR_ACTOR_NOT_OWNER` (HTTP 403)."
    PRD §2.6: "Applies to module creation, line-slot scheduling, line-slot release, station advance, pick scheduling, set execution, connection closeout, weather observation recording, inspection creation, result recording and hold clearance."

    Design: Corner/rbac/entity_backed_actors_cannot_reach_into_a_foreign_aggregate
    """
    validate_error(attempt(a_neighbourhood_of_foreign_aggregates), ERR_ACTOR_NOT_OWNER)


def test_an_inspector_cannot_open_a_record_under_a_sister_agency(
    a_neighbourhood_of_foreign_aggregates,
):
    """PRD §3.5: "A `ThirdPartyInspector` opens an inspection by supplying the `module_id` under inspection, the `agency_id` of the agency performing it — which must equal the caller's own `X-User-ID` — and the `stage`, which is either `IN_PLANT` or `FINAL_FACTORY`."
    PRD §2.1: "When `X-User-Role` is `ThirdPartyInspector`, `X-User-ID` is the `id` of the acting `InspectionAgency`; ownership checks compare the `agency_id` recorded on the inspection to `X-User-ID`."
    PRD §2.1: "A violation of any of these three ownership comparisons is `ERR_ACTOR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_actors_cannot_reach_into_a_foreign_aggregate
    """
    world = a_neighbourhood_of_foreign_aggregates

    # Both agencies are accredited in Washington and the module is off the line,
    # so nothing but the identity binding stands in the way.
    validate_error(
        world.api.create_inspection(
            f.inspection_payload(world.module_id(), world.agency_id, "IN_PLANT"),
            make_inspector_headers(world.other_agency["id"]),
        ),
        ERR_ACTOR_NOT_OWNER,
    )


def test_an_inspector_cannot_record_a_result_on_a_sister_agencys_record(
    a_neighbourhood_of_foreign_aggregates,
):
    """PRD §2.1: "When `X-User-Role` is `ThirdPartyInspector`, `X-User-ID` is the `id` of the acting `InspectionAgency`; ownership checks compare the `agency_id` recorded on the inspection to `X-User-ID`."
    PRD §3.5: "Recording stamps `recorded_at` with the current clock instant and `recorded_by_user_id` with the inspector's `X-User-ID`, and increments the record's `version`."
    PRD §2.1: "A violation of any of these three ownership comparisons is `ERR_ACTOR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_actors_cannot_reach_into_a_foreign_aggregate
    """
    world = a_neighbourhood_of_foreign_aggregates
    record = fx.open_inspection(
        world.api, world.module_id(), world.agency_id, "IN_PLANT"
    )

    validate_error(
        world.api.record_inspection_result(
            record["id"],
            f.inspection_result_payload("PASS"),
            make_inspector_headers(world.other_agency["id"]),
        ),
        ERR_ACTOR_NOT_OWNER,
    )

    still_pending = validate_success(
        world.api.get_inspection(record["id"], PROGRAM_ADMIN)
    )
    assert still_pending["result"] == "PENDING"
    assert still_pending["recorded_by_user_id"] is None


def _foreign_plant_creating_a_module(world):
    """A module booked into Rainier Flats by the manager of the second plant."""
    return world.api.create_module(
        f.module_payload(world.project_id, world.package_id, "M-99", 9),
        make_factory_manager_headers(world.other_factory["id"]),
    )


def _foreign_plant_claiming_a_takt_window(world):
    """A takt window claimed for a planned module of somebody else's plant."""
    return world.api.schedule_line_slot(
        world.module_id("M-02"),
        f.line_slot_payload("2026-09-04T14:00:00Z"),
        make_factory_manager_headers(world.other_factory["id"]),
    )


def _foreign_plant_releasing_a_takt_window(world):
    """A takt window given back by a plant that never claimed it."""
    return world.api.release_line_slot(
        world.module_id("M-03"),
        {"reason": "not this plant's ledger"},
        make_factory_manager_headers(world.other_factory["id"]),
    )


def _foreign_plant_advancing_a_station(world):
    """A station advance driven from the wrong plant's floor."""
    return world.api.advance_station(
        world.module_id("M-03"),
        f.advance_payload(1),
        make_factory_manager_headers(world.other_factory["id"]),
    )


@pytest.mark.parametrize(
    "attempt",
    [
        _foreign_plant_creating_a_module,
        _foreign_plant_claiming_a_takt_window,
        _foreign_plant_releasing_a_takt_window,
        _foreign_plant_advancing_a_station,
    ],
    ids=[
        "creating_a_module",
        "claiming_a_takt_window",
        "releasing_a_takt_window",
        "advancing_a_station",
    ],
)
def test_a_plant_manager_holding_another_plants_identifier_is_turned_away(
    a_neighbourhood_of_foreign_aggregates, attempt
):
    """PRD §2.1: "When `X-User-Role` is `FactoryProductionManager`, `X-User-ID` is the `id` of the acting `Factory`; ownership checks on any resource that references a `Factory` compare the resource's foreign-key field to `X-User-ID` — concretely, a module operation is permitted only when the module's project carries a `factory_id` equal to `X-User-ID`."
    PRD §2.1: "A violation of any of these three ownership comparisons is `ERR_ACTOR_NOT_OWNER` (HTTP 403)."
    PRD §2.6: "Applies to module creation, line-slot scheduling, line-slot release, station advance, pick scheduling, set execution, connection closeout, weather observation recording, inspection creation, result recording and hold clearance."

    Design: Corner/rbac/entity_backed_actors_cannot_reach_into_a_foreign_aggregate
    """
    validate_error(attempt(a_neighbourhood_of_foreign_aggregates), ERR_ACTOR_NOT_OWNER)


def test_the_turned_away_callers_leave_no_record_slot_or_pick_window_behind(
    a_neighbourhood_of_foreign_aggregates,
):
    """PRD §2.1: "A violation of any of these three ownership comparisons is `ERR_ACTOR_NOT_OWNER` (HTTP 403)."
    PRD §3.7: "On success the module's `pick_window_start`, `pick_window_end`, `pick_radius_ft` and `rigging_weight_lb` are persisted along with the computed `crane_utilization_pct`, and the module's `version` increments."
    PRD §3.5: "A new record is persisted with `result` `PENDING`, `hold_state` `NONE`, `defect_count` 0, `severity_max` 0, `corrective_note`, `recorded_at` and `recorded_by_user_id` all null, and `version` 1; the module's `version` increments when the first record flips its quality dimension."

    Design: Corner/rbac/entity_backed_actors_cannot_reach_into_a_foreign_aggregate
    """
    world = a_neighbourhood_of_foreign_aggregates
    committed_before = world.refresh_factory()["committed_line_minutes"]

    validate_error(
        world.api.create_inspection(
            f.inspection_payload(world.module_id(), world.agency_id, "IN_PLANT"),
            make_inspector_headers(world.other_agency["id"]),
        ),
        ERR_ACTOR_NOT_OWNER,
    )
    validate_error(_foreign_field_planning_a_pick(world), ERR_ACTOR_NOT_OWNER)
    validate_error(_foreign_plant_releasing_a_takt_window(world), ERR_ACTOR_NOT_OWNER)

    _, meta = validate_paginated(
        world.api.list_inspections({"module_id": world.module_id()}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0

    module = world.refresh_module()
    assert_module_dimensions(module, qc_status="PENDING")
    assert module["pick_window_start"] is None
    assert module["crane_utilization_pct"] is None

    assert_module_dimensions(world.refresh_module("M-03"), production_status="SLOTTED")
    assert world.refresh_factory()["committed_line_minutes"] == committed_before


def _the_program_office(world):
    """The manufacturer's program office, an opaque operator identity."""
    return PROGRAM_ADMIN


def _the_plant(world):
    """The plant manager of this world's own factory."""
    return world.factory_manager


def _the_field(world):
    """The field superintendent of this world's own project."""
    return world.superintendent


def _the_local_authority(world):
    """The local building department, an opaque operator identity."""
    return AUTHORITY_HAVING_JURISDICTION


@pytest.fixture
def a_dispatched_load(api):
    """A permitted standard load on the road with M-01 aboard."""
    world = fx.world_loaded_module(api)
    validate_success(
        world.api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    world.shipment = validate_success(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )
    return world


def test_the_receiving_superintendent_can_record_the_delivery(a_dispatched_load):
    """PRD §3.6: "Delivery — recordable by either the `TransportCoordinator` or the receiving `SiteSuperintendent` — takes an optional `arrived_at` and requires `status` `DISPATCHED`, or the attempt is `ERR_SHIPMENT_NOT_DISPATCHED`."
    PRD §3.6: "On success `status` moves to `DELIVERED`, which is terminal, `delivered_at` is stamped with the current clock instant, every module carried moves its `site_status` from `IN_TRANSIT` to `DELIVERED`, the `basis_earned_cents` and `requested_cents` of every `DRAFT` draw request of the project are recomputed because delivered modules enter the milestone basis, and the shipment and every module take `version` increments."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = a_dispatched_load

    # The field, not the carrier, signs for the load; its X-User-ID is the
    # project it receives on.
    delivered = validate_success(
        world.api.deliver_shipment(world.shipment_id, {}, world.superintendent)
    )

    assert delivered["status"] == "DELIVERED"
    assert_module_dimensions(world.refresh_module(), site_status="DELIVERED")


def test_the_program_office_can_record_the_site_weather_observation(api):
    """PRD §3.1: "Weather is carried on the project as three system-owned fields that a `SiteSuperintendent` — or a `ProgramAdmin` acting for the site — refreshes by recording an observation."
    PRD §3.1: "The observation supplies `forecast_precip_probability_pct`, the latest precipitation probability from 0 through 100, and `forecast_wind_gust_mph`, the latest wind gust reading; both may also be seeded at project creation and both default to 0."
    PRD §3.1: "Recording an observation increments the project's `version`."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = fx.world_plant_and_project(api)
    version_before = world.refresh_project()["version"]

    project = validate_success(
        world.api.record_weather_observation(
            world.project_id,
            f.weather_payload(
                forecast_precip_probability_pct=15, forecast_wind_gust_mph=8
            ),
            PROGRAM_ADMIN,
        )
    )

    # The program office is opaque: no ownership binding is asked of it.
    assert project["forecast_wind_gust_mph"] == 8
    assert project["forecast_precip_probability_pct"] == 15
    assert project["version"] == version_before + 1


def test_the_plant_can_raise_a_defect_claim_discovered_in_transit(api):
    """PRD §3.8: "Either the plant or the field may raise a defect claim, so both `FactoryProductionManager` and `SiteSuperintendent` can open one."
    PRD §3.8: "A new claim is persisted with `status` `OPEN`, `responsibility` `UNDETERMINED`, `adjudication_round` 0, all four of `factory_share_pct`, `field_share_pct`, `factory_charge_cents` and `field_charge_cents` at 0, `warranty_bucket` at its default of `SPLIT`, `adjudicated_by_user_id` and `dispute_note` null, and `version` 1."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = fx.world_delivered_module(api)

    claim = validate_success(
        world.api.create_defect_claim(
            f.defect_claim_payload(
                world.module_id(),
                "TRANSIT",
                180000,
                description="corner scuff noticed on arrival",
            ),
            world.factory_manager,
        ),
        201,
    )

    assert is_valid_uuid(claim["id"])
    assert claim["status"] == "OPEN"
    assert claim["responsibility"] == "UNDETERMINED"
    assert claim["adjudication_round"] == 0
    assert claim["version"] == 1


@pytest.mark.parametrize(
    "caller", [_the_program_office, _the_plant], ids=["program_office", "plant"]
)
def test_either_declared_holder_can_pause_the_production_line(api, caller):
    """PRD §3.1: "The plant's posture can be changed afterwards by either a `ProgramAdmin` or the plant's own `FactoryProductionManager`, who supply a replacement `line_state`."
    PRD §3.1: "The change increments the plant's `version`."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = fx.world_plant_and_project(api)
    version_before = world.refresh_factory()["version"]

    factory = validate_success(
        world.api.update_factory_line_state(
            world.factory_id, f.line_state_payload("PAUSED"), caller(world)
        )
    )

    assert factory["line_state"] == "PAUSED"
    assert factory["version"] == version_before + 1


def test_the_state_program_officer_can_revise_an_agencys_accreditation(api):
    """PRD §3.1: "Agencies may be listed filtered by `agency_code` or `accreditation_state`, and their posture may later be revised by either a `ProgramAdmin` or a `StateProgramOfficer` supplying a new `accreditation_state` and optionally a replacement `accredited_state_codes` list; that revision increments the agency's `version`."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = fx.world_plant_and_project(api)
    version_before = validate_success(
        world.api.get_agency(world.agency_id, PROGRAM_ADMIN)
    )["version"]

    agency = validate_success(
        world.api.update_agency_accreditation(
            world.agency_id,
            f.accreditation_payload("PROBATION"),
            STATE_PROGRAM_OFFICER,
        )
    )

    assert agency["accreditation_state"] == "PROBATION"
    assert agency["version"] == version_before + 1


@pytest.mark.parametrize(
    "caller",
    [_the_program_office, _the_field, _the_local_authority],
    ids=["program_office", "field", "local_authority"],
)
def test_the_set_readiness_view_answers_each_of_its_three_declared_readers(api, caller):
    """PRD §3.1: "A heavier computed read — the set-readiness view, available to `ProgramAdmin`, `SiteSuperintendent` and `AuthorityHavingJurisdiction` — re-derives `permit_posture` and `phase`, refreshes the exposure clock on every module of the project, and refreshes the set counters before returning the project row; it is the view the field uses before deciding whether a lift may proceed."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = fx.world_with_module(api)

    project = validate_success(
        world.api.get_set_readiness(world.project_id, caller(world))
    )

    assert project["id"] == world.project_id
    assert project["permit_posture"] == "STATE_CLEARED_ONLY"
    assert project["modules_set_count"] == 0


@pytest.mark.parametrize("caller", [_the_plant, _the_field], ids=["plant", "field"])
def test_either_side_of_the_warranty_argument_can_dispute_the_allocation(api, caller):
    """PRD §3.8: "Disputing an allocation is available to whichever side is unhappy — both `FactoryProductionManager` and `SiteSuperintendent` may raise one — and requires a `dispute_note` narrative."
    PRD §3.8: "A successful dispute moves `status` from `ADJUDICATED` to `DISPUTED`, stores the `dispute_note`, and increments the claim's `version`."

    Design: Corner/rbac/shared_operations_work_for_every_declared_role
    """
    world = fx.world_with_module(api)
    claim = validate_success(
        world.api.create_defect_claim(
            f.defect_claim_payload(world.module_id(), "FACTORY", 250000),
            world.factory_manager,
        ),
        201,
    )
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    disputed = validate_success(
        world.api.dispute_defect_claim(
            claim["id"], f.dispute_payload("the allocation is wrong"), caller(world)
        )
    )

    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_note"] == "the allocation is wrong"
