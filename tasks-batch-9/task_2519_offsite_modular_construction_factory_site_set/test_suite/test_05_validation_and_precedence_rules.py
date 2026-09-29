"""Which rule answers when a request breaks several of them at once.

Ten disciplines share this system and none of them trusts the others, so two
parties arguing about why a takt claim, a route survey or a crane lift was
refused have to be handed the same answer every time. These tests drive requests
that violate an early guard and a late guard together — no identity at all
alongside a half-written body, a plant manager from the wrong plant reaching for
another plant's line, a load whose transport permit died on the logical clock —
and pin the identifier the server is obliged to return. The admitting side of
each guard is exercised too: a shift window that opens on the minute, an escort
obligation that never arose, a hold that has been cleared, and a superload short
enough of a route to stay legal.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_OWNER,
    ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT,
    ERR_ESCORT_NOT_CONFIRMED,
    ERR_HOLD_NOT_ACTIVE,
    ERR_LINE_SLOT_OUTSIDE_SHIFT,
    ERR_PINNED_PACKAGE_MISMATCH,
    ERR_QC_HOLD_BLOCKS_OPERATION,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_TRANSPORT_PERMIT_EXPIRED,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_module_dimensions,
)
from test_helpers.test_users import (
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    TRANSPORT_COORDINATOR,
    make_factory_manager_headers,
    make_headers,
)

NO_IDENTITY_HEADERS = {}


def _walk_module_to_the_site(world, module_code="M-01"):
    """Slot, build, release, load, permit, dispatch and deliver one module."""
    fx.schedule_slot(world, module_code)
    fx.advance_stations(world, module_code, world.factory["station_count"])
    fx.release_quality(world, module_code)
    world.shipment = fx.create_shipment(world.api, world.project_id)
    world.shipment = fx.load_module(
        world.api,
        world.shipment_id,
        world.module_id(module_code),
        world.shipment["version"],
    )
    get_success_data(
        world.api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    get_success_data(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )
    world.shipment = get_success_data(
        world.api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )
    return world.refresh_module(module_code)


def test_a_plant_registration_with_no_identity_headers_is_refused_unread(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the discipline it acts as."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the ten declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "The ladder runs authentication, then role authorisation, then payload well-formedness, then existence, then ownership and segregation of duties, then optimistic concurrency, then link uniqueness, then state preconditions, then safety and regulatory gates, then constraint satisfaction, then temporal windows, then referential and compliance rules, and finally fiscal ceilings."

    Design: Corner/validations/unauthenticated_request_outranks_every_later_check
    """
    fx.set_clock(api)

    # The body is missing the code, the takt, the station count, the parallel
    # capacity and the unit value, and the endpoint admits ProgramAdmin alone.
    validate_error(
        api.create_factory({"name": "Ghost Plant"}, NO_IDENTITY_HEADERS),
        ERR_UNAUTHENTICATED,
    )

    _, meta = validate_paginated(api.list_factories({}, PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "the rejected registration created no plant"


def test_a_role_name_outside_the_ten_disciplines_never_reaches_the_role_table(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the ten declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "These two checks precede every other consideration in the system, including whether the resources named in the URL exist."

    Design: Corner/validations/unauthenticated_request_outranks_every_later_check
    """
    fx.set_clock(api)

    # "SiteInspector" is not one of the ten declared roles, and the payload is
    # missing every field but the display name.
    validate_error(
        api.create_factory(
            {"name": "Ghost Plant"}, make_headers("ghost-001", "SiteInspector")
        ),
        ERR_UNAUTHENTICATED,
    )

    _, meta = validate_paginated(api.list_factories({}, PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "the rejected registration created no plant"


def test_a_lender_posting_a_half_written_module_is_refused_on_its_role(api):
    """PRD §2.1: "When both headers are well formed but the named role is not among the roles authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.6: "`ERR_ROLE_NOT_PERMITTED` — the caller's `X-User-Role` appears in the endpoint's authorised role list. Applies to every endpoint."
    PRD §3.4: "The shipping envelope is declared with four required integers, each at least 1: `width_in`, `length_in`, `height_in` — the height measured as the module will sit on the carrier — and `gross_weight_lb`."

    Design: Corner/validations/role_check_outranks_payload_shape_validation
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )

    # Module creation belongs to the plant manager alone, and this body drops the
    # set sequence position, all three dimensions and the gross weight.
    validate_error(
        api.create_module(
            f.module_payload(
                world.project_id,
                world.package_id,
                "M-01",
                set_sequence_index=...,
                width_in=...,
                length_in=...,
                height_in=...,
                gross_weight_lb=...,
            ),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    _, meta = validate_paginated(
        api.list_modules({"project_id": world.project_id}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0, "the refused call created no module"


def test_dispatching_a_load_that_was_never_opened_reports_the_missing_load(api):
    """PRD §2.5: "Path identifiers are nevertheless resolved strictly left to right, and each is resolved before any body field is examined."
    PRD §2.5: "An unresolvable identifier produces the 404 that names the missing type: `ERR_FACTORY_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_PACKAGE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_DEFECT_CLAIM_NOT_FOUND` or `ERR_DRAW_NOT_FOUND`."
    PRD §3.6: "The shipment's `status` must be `PERMITTED` and its `loaded_module_count` at least 1, or the attempt is `ERR_SHIPMENT_NOT_PERMITTED`, and the current clock instant must be strictly before `permit_expires_at`, or the attempt is `ERR_TRANSPORT_PERMIT_EXPIRED`."

    Design: Corner/validations/path_id_existence_outranks_the_state_precondition
    """
    world = fx.world_plant_and_project(api)
    world.shipment = fx.create_shipment(api, world.project_id)

    # A real DRAFT load exists, so the state precondition has something to be
    # tempted by; the id in the path still resolves to nothing.
    validate_error(
        api.dispatch_shipment(NON_EXISTENT_UUID, {}, TRANSPORT_COORDINATOR),
        ERR_SHIPMENT_NOT_FOUND,
    )

    assert world.refresh_shipment()["status"] == "DRAFT"
    assert world.shipment["dispatched_at"] is None


def test_a_manager_of_another_plant_cannot_claim_a_takt_window(api):
    """PRD §2.1: "When `X-User-Role` is `FactoryProductionManager`, `X-User-ID` is the `id` of the acting `Factory`; ownership checks on any resource that references a `Factory` compare the resource's foreign-key field to `X-User-ID` — concretely, a module operation is permitted only when the module's project carries a `factory_id` equal to `X-User-ID`."
    PRD §2.1: "A violation of any of these three ownership comparisons is `ERR_ACTOR_NOT_OWNER` (HTTP 403)."
    PRD §3.4: "Claiming a takt window moves `production_status` from `PLANNED` to `SLOTTED`, and the only payload field is `line_slot_start`, the instant at which the module wants the line."

    Design: Corner/validations/foreign_factory_manager_cannot_schedule_a_slot
    """
    world = fx.world_with_module(api)
    other_plant = fx.create_factory(
        api, name="Columbia Modular Plant 2", code="PMP2"
    )

    # A real plant manager, a permitted role — but of the wrong plant entirely.
    validate_error(
        api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload(fx.DEFAULT_LINE_SLOT_START),
            make_factory_manager_headers(other_plant["id"]),
        ),
        ERR_ACTOR_NOT_OWNER,
    )

    module = world.refresh_module()
    assert_module_dimensions(module, production_status="PLANNED")
    assert module["line_slot_start"] is None
    assert module["line_slot_minutes"] == 0
    assert world.refresh_factory()["committed_line_minutes"] == 0
    assert (
        get_success_data(api.get_factory(other_plant["id"], PROGRAM_ADMIN))[
            "committed_line_minutes"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "line_slot_start",
    ["2026-09-02T05:00:00Z", "2026-09-02T05:59:00Z"],
)
def test_a_takt_window_starting_before_the_shift_opens_is_refused(
    api, line_slot_start
):
    """PRD §3.4: "A seventh, temporal constraint applies as well: the minute-of-day of the requested `line_slot_start` must fall inside the plant's shift window, meaning it is at or after `shift_start_minute_of_day` and strictly before `shift_start_minute_of_day` plus `shift_minutes_per_day`; a start outside that window is rejected with `ERR_LINE_SLOT_OUTSIDE_SHIFT`."
    PRD §3.1: "`shift_start_minute_of_day` is the first minute of the production shift counted in UTC minutes past midnight, accepts any value from 0 through 1439, and defaults to 360 — six o'clock in the morning."

    Design: Corner/validations/line_slot_shift_window_rejects_before_open_and_admits_at_open
    """
    world = fx.world_with_module(api)

    # Minute-of-day 300 and 359 both sit below the 360 lower bound.
    validate_error(
        api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload(line_slot_start),
            world.factory_manager,
        ),
        ERR_LINE_SLOT_OUTSIDE_SHIFT,
    )

    assert_module_dimensions(world.refresh_module(), production_status="PLANNED")
    assert world.module()["line_slot_start"] is None
    assert world.refresh_factory()["committed_line_minutes"] == 0


def test_a_takt_window_starting_exactly_at_the_shift_open_minute_is_admitted(api):
    """PRD §3.4: "A seventh, temporal constraint applies as well: the minute-of-day of the requested `line_slot_start` must fall inside the plant's shift window, meaning it is at or after `shift_start_minute_of_day` and strictly before `shift_start_minute_of_day` plus `shift_minutes_per_day`; a start outside that window is rejected with `ERR_LINE_SLOT_OUTSIDE_SHIFT`."
    PRD §3.4: "The module's `line_slot_minutes` is then the plant's `station_count` multiplied by that effective takt, in whole minutes."
    PRD §3.4: "Its `line_slot_start` is the requested instant and its `line_slot_end` is that instant plus `line_slot_minutes` minutes."

    Design: Corner/validations/line_slot_shift_window_rejects_before_open_and_admits_at_open
    """
    world = fx.world_with_module(api)

    # Minute-of-day 360 is the inclusive lower bound of the shift window.
    module = validate_success(
        api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-09-02T06:00:00Z"),
            world.factory_manager,
        )
    )

    assert_module_dimensions(module, production_status="SLOTTED")
    assert_instant(module["line_slot_start"], "2026-09-02T06:00:00Z")
    assert module["line_slot_minutes"] == 540
    # The slot may run past the shift end; only the start minute is constrained.
    assert_instant(module["line_slot_end"], "2026-09-02T15:00:00Z")
    assert world.refresh_factory()["committed_line_minutes"] == 540


def test_a_takt_window_starting_in_the_last_minute_of_the_shift_is_admitted(api):
    """PRD §3.4: "A seventh, temporal constraint applies as well: the minute-of-day of the requested `line_slot_start` must fall inside the plant's shift window, meaning it is at or after `shift_start_minute_of_day` and strictly before `shift_start_minute_of_day` plus `shift_minutes_per_day`; a start outside that window is rejected with `ERR_LINE_SLOT_OUTSIDE_SHIFT`."
    PRD §3.1: "`shift_minutes_per_day` is how many productive minutes the shift makes available, accepts 1 through 1440, and defaults to 1080, which is an eighteen-hour working day."

    Design: Corner/validations/line_slot_shift_window_rejects_before_open_and_admits_at_open
    """
    world = fx.world_with_module(api)

    # 360 plus 1080 is 1440, and minute-of-day 1439 is strictly below it.
    module = validate_success(
        api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-09-02T23:59:00Z"),
            world.factory_manager,
        )
    )

    assert_module_dimensions(module, production_status="SLOTTED")
    assert_instant(module["line_slot_start"], "2026-09-02T23:59:00Z")
    assert module["line_slot_minutes"] == 540


def test_a_standard_single_state_load_needs_no_escort_confirmation(api):
    """PRD §3.6: "`escort_required` becomes true when `max_envelope_class` is `SUPERLOAD`, and also when `max_envelope_class` is `OVERWIDTH` and the route crosses two or more states; otherwise it is false, and whenever it is false the shipment's `escort_confirmed` is forced back to false as well."
    PRD §3.6: "On success `route_survey_state` becomes `COMPLETED` — from `REQUIRED` on a load that acquired the obligation, or directly from `NOT_REQUIRED` on a standard load that never needed one — the transport axis moves to `PERMITTED` from either `DRAFT` or `SURVEY_REQUIRED`, `survey_completed_at`, `permit_expires_at` and `escort_confirmed` are persisted from the payload, and the shipment's `version` increments."

    Design: Corner/validations/escort_confirmation_is_required_only_when_the_load_escalates
    """
    world = fx.world_loaded_module(api)

    assert world.shipment["max_envelope_class"] == "STANDARD"
    assert world.shipment["escort_required"] is False
    assert_cents(world.shipment["permit_fee_cents"], 0, "permit_fee_cents")

    shipment = validate_success(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )

    # The escort rule never applied, so the omitted flag is not an error.
    assert shipment["status"] == "PERMITTED"
    assert shipment["route_survey_state"] == "COMPLETED"
    assert shipment["escort_confirmed"] is False


def test_an_overwidth_two_state_load_refuses_a_survey_with_no_escorts_confirmed(api):
    """PRD §3.6: "When the shipment's `escort_required` is true, the payload's `escort_confirmed` must be true, or the attempt is `ERR_ESCORT_NOT_CONFIRMED`."
    PRD §3.6: "`permit_fee_cents` is then a base state permit fee of $250.00 — that is 25,000 cents — multiplied by the number of entries in `route_state_codes`, multiplied again by that class multiplier."
    PRD §3.4: "Otherwise, if `width_in` is greater than 192 inches — sixteen feet — or `height_in` is greater than 162 inches, or `gross_weight_lb` is greater than 80,000 pounds, then `envelope_class` is `OVERWIDTH`."

    Design: Corner/validations/escort_confirmation_is_required_only_when_the_load_escalates
    """
    world = fx.world_loaded_module(
        api, route_state_codes=["WA", "OR"], module_overrides={"width_in": 200}
    )

    assert world.shipment["max_envelope_class"] == "OVERWIDTH"
    assert world.shipment["escort_required"] is True
    # 25,000 cents by two states by the OVERWIDTH multiplier of 2.
    assert_cents(world.shipment["permit_fee_cents"], 100000, "permit_fee_cents")

    validate_error(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        ),
        ERR_ESCORT_NOT_CONFIRMED,
    )

    shipment = world.refresh_shipment()
    assert shipment["route_survey_state"] == "REQUIRED"
    assert shipment["status"] == "SURVEY_REQUIRED"
    assert shipment["permit_expires_at"] is None
    assert shipment["survey_completed_at"] is None


def test_confirming_the_escorts_lets_the_overwidth_survey_through(api):
    """PRD §3.6: "When the shipment's `escort_required` is true, the payload's `escort_confirmed` must be true, or the attempt is `ERR_ESCORT_NOT_CONFIRMED`."
    PRD §3.6: "On success `route_survey_state` becomes `COMPLETED` — from `REQUIRED` on a load that acquired the obligation, or directly from `NOT_REQUIRED` on a standard load that never needed one — the transport axis moves to `PERMITTED` from either `DRAFT` or `SURVEY_REQUIRED`, `survey_completed_at`, `permit_expires_at` and `escort_confirmed` are persisted from the payload, and the shipment's `version` increments."

    Design: Corner/validations/escort_confirmation_is_required_only_when_the_load_escalates
    """
    world = fx.world_loaded_module(
        api, route_state_codes=["WA", "OR"], module_overrides={"width_in": 200}
    )

    shipment = validate_success(
        api.record_route_survey(
            world.shipment_id,
            f.route_survey_payload(escort_confirmed=True),
            TRANSPORT_COORDINATOR,
        )
    )

    assert shipment["escort_confirmed"] is True
    assert shipment["status"] == "PERMITTED"
    assert shipment["route_survey_state"] == "COMPLETED"
    assert_instant(shipment["permit_expires_at"], "2026-09-20T00:00:00Z")


@pytest.fixture
def module_two_stations_in_under_inspection(api):
    """A module standing at station 2 of 6 with an open IN_PLANT record."""
    world = fx.world_slotted_module(api)
    fx.advance_stations(world, "M-01", 2)
    world.inspections["M-01:IN_PLANT"] = fx.open_inspection(
        api, world.module_id(), world.agency_id, "IN_PLANT"
    )
    return world


def test_a_failed_in_plant_inspection_stops_the_line_without_moving_production(
    module_two_stations_in_under_inspection,
):
    """PRD §3.5: "A `FAIL` moves `qc_status` to `HOLD` — from `IN_PROGRESS` on a first pass, or from `CONDITIONAL_RELEASE` on a re-opened `FINAL_FACTORY` record — and requires the recording agency's `hold_authority` to be true."
    PRD §3.5: "Both hold arms set the record's `hold_state` to `AGENCY_HOLD` and increment the module's `version`."
    PRD §3.5: "Four operations across the factory, transport and site refuse to proceed against a module whose `qc_status` is `HOLD`, and in all four the rejection is `ERR_QC_HOLD_BLOCKS_OPERATION`: claiming a takt window, advancing a station, loading the module onto a shipment, and setting the module on the foundation."

    Design: Corner/validations/qc_hold_blocks_the_advance_and_clearing_the_hold_admits_it
    """
    world = module_two_stations_in_under_inspection
    record = validate_success(
        world.api.record_inspection_result(
            world.inspections["M-01:IN_PLANT"]["id"],
            f.inspection_result_payload(
                "FAIL", 4, 4, corrective_note="shear wall nailing pattern"
            ),
            world.inspector,
        )
    )

    assert record["hold_state"] == "AGENCY_HOLD"
    assert_module_dimensions(
        world.refresh_module(), production_status="IN_LINE", qc_status="HOLD"
    )

    validate_error(
        world.api.advance_station(
            world.module_id(), f.advance_payload(1), world.factory_manager
        ),
        ERR_QC_HOLD_BLOCKS_OPERATION,
    )

    module = world.refresh_module()
    assert module["station_index"] == 2, "the refused advance moved no station"
    assert_module_dimensions(module, production_status="IN_LINE", qc_status="HOLD")


def test_clearing_the_agency_hold_lets_the_identical_advance_through(
    module_two_stations_in_under_inspection,
):
    """PRD §3.5: "On success the record's `hold_state` becomes `CLEARED`, its `result` is reset to `PENDING`, its `defect_count` and `severity_max` are both reset to 0, and the supplied `corrective_note` is stored."
    PRD §3.5: "The module's `qc_status` returns from `HOLD` to `IN_PROGRESS`, closing the cycle from `IN_PROGRESS` through `HOLD` and back to `IN_PROGRESS`."
    PRD §3.4: "An intermediate advance, where `station_index` plus `stations_advanced` remains strictly less than the plant's `station_count`, keeps `production_status` at `IN_LINE`, increases `station_index` by `stations_advanced`, recomputes `wip_earned_cents`, recomputes the `basis_earned_cents` and `requested_cents` of every draw request of the project still in status `DRAFT`, and increments the module's `version`."

    Design: Corner/validations/qc_hold_blocks_the_advance_and_clearing_the_hold_admits_it
    """
    world = module_two_stations_in_under_inspection
    inspection_id = world.inspections["M-01:IN_PLANT"]["id"]
    fx.record_result(world.api, inspection_id, world.agency_id, "FAIL", 4, 4)

    record = validate_success(
        world.api.clear_hold(
            inspection_id,
            f.clear_hold_payload("re-nailed and re-inspected"),
            world.inspector,
        )
    )

    assert record["hold_state"] == "CLEARED"
    assert record["result"] == "PENDING"
    assert record["defect_count"] == 0
    assert record["severity_max"] == 0
    assert_module_dimensions(world.refresh_module(), qc_status="IN_PROGRESS")

    module = validate_success(
        world.api.advance_station(
            world.module_id(), f.advance_payload(1), world.factory_manager
        )
    )

    assert module["station_index"] == 3
    assert_module_dimensions(
        module, production_status="IN_LINE", qc_status="IN_PROGRESS"
    )


def test_a_hold_cannot_be_cleared_while_the_record_is_still_pending(
    module_two_stations_in_under_inspection,
):
    """PRD §3.5: "The inspector supplies a required `corrective_note`, and three preconditions apply: the module's `qc_status` must be `HOLD` and the record's `hold_state` must be `AGENCY_HOLD` — otherwise the attempt is `ERR_HOLD_NOT_ACTIVE` — and the clearing agency's `accreditation_state` must be `ACCREDITED` or `PROBATION`."

    Design: Corner/validations/qc_hold_blocks_the_advance_and_clearing_the_hold_admits_it
    """
    world = module_two_stations_in_under_inspection

    # No result has been recorded, so the record sits at hold_state NONE.
    validate_error(
        world.api.clear_hold(
            world.inspections["M-01:IN_PLANT"]["id"],
            f.clear_hold_payload(),
            world.inspector,
        ),
        ERR_HOLD_NOT_ACTIVE,
    )

    assert_module_dimensions(
        world.refresh_module(), production_status="IN_LINE", qc_status="IN_PROGRESS"
    )


@pytest.fixture
def module_built_to_the_unapproved_revision(api):
    """A delivered, lift-planned module detailed against a revision R2 in DRAFT.

    The state approved R1 and pinned it, the site is cleared for setting and the
    module is first in the set order, so nothing but the revision is out of place.
    """
    world = fx.world_plan_review_approved(api)
    fx.clear_the_site_for_setting(world)
    world.package = fx.create_design_package(
        api, world.project_id, world.refresh_project()["version"], revision_index=2
    )
    fx.add_module(world, "M-01", 1)
    _walk_module_to_the_site(world)
    fx.plan_pick(world, "M-01")
    return world


def test_a_module_detailed_against_an_unapproved_revision_is_not_set(
    module_built_to_the_unapproved_revision,
):
    """PRD §3.7: "The module's `design_package_id` must equal the `pinned_package_id` carried by the project's live state plan-review approval, or the attempt is `ERR_PINNED_PACKAGE_MISMATCH` — a module built to a revision the state never approved does not go on the building."
    PRD §3.7: "The project's `permit_posture` must be `SET_CLEARED` or `OCCUPANCY_CLEARED`, or the attempt is `ERR_SET_NOT_PERMITTED`."
    PRD §3.7: "Under `STRICT_ASCENDING`, the module's `set_sequence_index` must equal the project's current `modules_set_count` plus 1 — modules go on in exactly the numbered order, with no gaps and no reordering."

    Design: Corner/validations/pinned_package_mismatch_is_checked_after_posture_and_sequence
    """
    world = module_built_to_the_unapproved_revision
    project = world.refresh_project()
    module = world.refresh_module()

    # Neither the permit posture gate nor the set sequence rule can fire here.
    assert project["permit_posture"] == "SET_CLEARED"
    assert project["modules_set_count"] == 0
    assert module["set_sequence_index"] == 1
    assert module["pick_window_start"] is not None

    validate_error(
        world.api.execute_set(
            world.module_id(),
            {"set_note": "detailed against the unapproved revision"},
            world.superintendent,
        ),
        ERR_PINNED_PACKAGE_MISMATCH,
    )

    permit = get_success_data(
        world.api.get_permit(world.plan_review_permit["id"], PROGRAM_ADMIN)
    )
    assert permit["pinned_package_id"] != module["design_package_id"]
    module = world.refresh_module()
    assert_module_dimensions(module, site_status="DELIVERED")
    assert module["set_at"] is None
    assert world.refresh_project()["modules_set_count"] == 0


def test_a_module_detailed_against_the_pinned_revision_lands_on_the_foundation(api):
    """PRD §3.7: "The module's `design_package_id` must equal the `pinned_package_id` carried by the project's live state plan-review approval, or the attempt is `ERR_PINNED_PACKAGE_MISMATCH` — a module built to a revision the state never approved does not go on the building."
    PRD §3.7: "A successful set stamps `set_at` with the current clock instant, resets the module's `exposure_open_hours` to 0 because the exposure clock starts now, increases the project's `modules_set_count` by 1, re-derives the project's `phase` up to `SETTING`, and increments both the module's and the project's `version`."

    Design: Corner/validations/pinned_package_mismatch_is_checked_after_posture_and_sequence
    """
    world = fx.world_delivered_module(api)
    fx.clear_the_site_for_setting(world)
    fx.plan_pick(world, "M-01")

    module = validate_success(
        world.api.execute_set(world.module_id(), {}, world.superintendent)
    )

    assert_module_dimensions(module, site_status="SET")
    assert module["design_package_id"] == world.package_id
    assert_instant(module["set_at"], f.DEFAULT_CLOCK)
    project = world.refresh_project()
    assert project["modules_set_count"] == 1
    assert project["phase"] == "SETTING"


@pytest.fixture
def permitted_load_whose_permit_dies_on_september_third(api):
    """A single-module standard load carrying a permit that expires 09-03T00:00."""
    world = fx.world_loaded_module(api)
    world.shipment = validate_success(
        world.api.record_route_survey(
            world.shipment_id,
            f.route_survey_payload(permit_expires_at="2026-09-03T00:00:00Z"),
            TRANSPORT_COORDINATOR,
        )
    )
    return world


def test_a_load_cannot_be_dispatched_at_the_instant_its_permit_expires(
    permitted_load_whose_permit_dies_on_september_third,
):
    """PRD §3.6: "And the supplied `permit_expires_at` must be strictly later than the current logical clock instant, or the attempt is `ERR_TRANSPORT_PERMIT_EXPIRED`."
    PRD §3.6: "The shipment's `status` must be `PERMITTED` and its `loaded_module_count` at least 1, or the attempt is `ERR_SHIPMENT_NOT_PERMITTED`, and the current clock instant must be strictly before `permit_expires_at`, or the attempt is `ERR_TRANSPORT_PERMIT_EXPIRED`."
    PRD §2.10: "The server owns a single logical clock and never consults wall-clock time."

    Design: Corner/validations/transport_permit_expiry_is_detected_at_dispatch_by_the_clock
    """
    world = permitted_load_whose_permit_dies_on_september_third

    # Filing the survey was legal at 09-01T08:00; only the clock has moved since.
    assert world.shipment["status"] == "PERMITTED"
    assert_instant(world.shipment["permit_expires_at"], "2026-09-03T00:00:00Z")

    fx.set_clock(world.api, "2026-09-03T00:00:00Z")

    validate_error(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR),
        ERR_TRANSPORT_PERMIT_EXPIRED,
    )

    shipment = world.refresh_shipment()
    assert shipment["status"] == "PERMITTED"
    assert shipment["dispatched_at"] is None
    assert_module_dimensions(world.refresh_module(), site_status="LOADED")


def test_a_load_dispatches_in_the_last_minute_before_its_permit_expires(
    permitted_load_whose_permit_dies_on_september_third,
):
    """PRD §3.6: "The shipment's `status` must be `PERMITTED` and its `loaded_module_count` at least 1, or the attempt is `ERR_SHIPMENT_NOT_PERMITTED`, and the current clock instant must be strictly before `permit_expires_at`, or the attempt is `ERR_TRANSPORT_PERMIT_EXPIRED`."
    PRD §3.6: "On success `status` moves from `PERMITTED` to `DISPATCHED`, `dispatched_at` is stamped with the current clock instant, every module aboard moves its `site_status` from `LOADED` to `IN_TRANSIT`, the project's `phase` is re-derived up to `SHIPPING`, and the shipment, every module aboard and the project all take `version` increments."

    Design: Corner/validations/transport_permit_expiry_is_detected_at_dispatch_by_the_clock
    """
    world = permitted_load_whose_permit_dies_on_september_third
    fx.set_clock(world.api, "2026-09-02T23:59:00Z")

    shipment = validate_success(
        world.api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )

    assert shipment["status"] == "DISPATCHED"
    assert_instant(shipment["dispatched_at"], "2026-09-02T23:59:00Z")
    assert_module_dimensions(world.refresh_module(), site_status="IN_TRANSIT")
    assert world.refresh_project()["phase"] == "SHIPPING"


def test_a_superload_cannot_join_a_load_routed_over_three_states(api):
    """PRD §3.6: "And a load whose recomputed `max_envelope_class` would be `SUPERLOAD` may not traverse more than two states: if the shipment's `route_state_codes` array holds three or more entries, the load is rejected with `ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT`."
    PRD §3.4: "If `width_in` is greater than 216 inches — eighteen feet — or `height_in` is greater than 174 inches, or `gross_weight_lb` is greater than 120,000 pounds, then `envelope_class` is `SUPERLOAD`."
    PRD §3.6: "The shipment's `max_envelope_class` is the widest `envelope_class` among the modules currently aboard, ordering the classes `STANDARD` below `OVERWIDTH` below `SUPERLOAD`, and it is `STANDARD` whenever the load is empty."

    Design: Corner/validations/superload_over_three_states_is_rejected_by_the_route_limit
    """
    world = fx.world_loaded_module(api, route_state_codes=["WA", "OR", "CA"])
    fx.add_module(world, "M-02", 2, width_in=220)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", world.factory["station_count"])
    fx.release_quality(world, "M-02")

    assert world.module("M-02")["envelope_class"] == "SUPERLOAD"

    # M-02 is individually loadable; only the recomputed aggregate breaches.
    validate_error(
        api.load_module(
            world.shipment_id,
            f.load_module_payload(
                world.module_id("M-02"), world.refresh_shipment()["version"]
            ),
            TRANSPORT_COORDINATOR,
        ),
        ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT,
    )

    shipment = world.refresh_shipment()
    assert shipment["loaded_module_count"] == 1
    assert shipment["max_envelope_class"] == "STANDARD"
    assert_cents(shipment["permit_fee_cents"], 0, "permit_fee_cents")
    assert shipment["status"] == "DRAFT"
    module = world.refresh_module("M-02")
    assert module["shipment_id"] is None
    assert_module_dimensions(module, site_status="AT_FACTORY")


def test_a_superload_over_exactly_two_states_is_admitted_and_priced(api):
    """PRD §3.6: "And a load whose recomputed `max_envelope_class` would be `SUPERLOAD` may not traverse more than two states: if the shipment's `route_state_codes` array holds three or more entries, the load is rejected with `ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT`."
    PRD §3.6: "`permit_fee_cents` is then a base state permit fee of $250.00 — that is 25,000 cents — multiplied by the number of entries in `route_state_codes`, multiplied again by that class multiplier."
    PRD §3.6: "On success the module's `site_status` moves from `AT_FACTORY` to `LOADED`, its `shipment_id` is set to the shipment, the shipment's `loaded_module_count` increases by 1, and both rows take `version` increments."

    Design: Corner/validations/superload_over_three_states_is_rejected_by_the_route_limit
    """
    world = fx.world_loaded_module(
        api, route_state_codes=["WA", "OR"], module_overrides={"width_in": 220}
    )

    shipment = world.refresh_shipment()
    assert shipment["max_envelope_class"] == "SUPERLOAD"
    assert shipment["loaded_module_count"] == 1
    assert shipment["escort_required"] is True
    # 25,000 cents by two states by the SUPERLOAD multiplier of 5.
    assert_cents(shipment["permit_fee_cents"], 250000, "permit_fee_cents")
    assert shipment["route_survey_state"] == "REQUIRED"
    assert shipment["status"] == "SURVEY_REQUIRED"
    assert_module_dimensions(world.refresh_module(), site_status="LOADED")
