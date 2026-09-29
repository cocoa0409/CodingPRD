"""The registry layer: plants, agency panels, projects and the rows that point at them.

Before a single module moves down a line, the program office has to describe the
physical plant, accredit an inspection panel, open a project with its contract,
its crane chart and its financing rates, and file permit applications against it.
This file exercises that registry surface — what a create call answers, which
fields the server owns and which the caller may state, what a read gives back,
how a collection is filtered and paged, and how a reference to a row of the wrong
aggregate is refused without being mistaken for a missing row.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CROSS_AGGREGATE_MISMATCH,
    ERR_DESIGN_PACKAGE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PROJECT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_fields,
    assert_created_at_ascending,
    assert_envelope_meta,
    assert_list_meta,
    assert_single_resource_meta_omits_paging,
    assert_two_decimal_value,
    parse_instant,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_SUBMITTER,
    PROGRAM_ADMIN,
    TRANSPORT_COORDINATOR,
    WARRANTY_ADJUDICATOR,
)


def _codes(rows):
    """The shop codes of a page of modules, in the order they came back."""
    return [row["module_code"] for row in rows]


# ─── Registering the plant ────────────────────────────────────────────────────
def test_registering_a_plant_answers_created_with_the_whole_plant_row(api):
    """PRD §4: "Every endpoint below is mounted under the `/modular` namespace and follows one status-code convention: an operation that brings a new resource into existence answers **201 Created**, and every other successful operation — reads, state transitions, posture changes, the logical clock — answers **200 OK**."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §3.1: "A newly registered plant begins with `committed_line_minutes` at 0 and `version` at 1."

    Design: Corner/entities/factory_creation_returns_declared_fields_and_envelope
    """
    fx.set_clock(api)

    response = api.create_factory(f.factory_payload(), PROGRAM_ADMIN)
    factory = validate_success(response, 201)

    body = response.json()
    assert_envelope_meta(body)
    assert body["response_type"] == "object"
    assert_single_resource_meta_omits_paging(body)

    assert_common_fields(factory, expected_version=1)
    assert factory["name"] == f.FACTORY_NAME
    assert factory["code"] == f.FACTORY_CODE
    assert factory["takt_minutes"] == 90
    assert factory["station_count"] == 6
    assert factory["parallel_station_capacity"] == 2
    assert_cents(factory["wip_unit_value_cents"], 8750000, "wip_unit_value_cents")
    assert factory["committed_line_minutes"] == 0


def test_a_plant_registered_without_a_shift_or_a_line_posture_takes_the_declared_defaults(
    api,
):
    """PRD §3.1: "`shift_start_minute_of_day` is the first minute of the production shift counted in UTC minutes past midnight, accepts any value from 0 through 1439, and defaults to 360 — six o'clock in the morning."
    PRD §3.1: "`shift_minutes_per_day` is how many productive minutes the shift makes available, accepts 1 through 1440, and defaults to 1080, which is an eighteen-hour working day."
    PRD §3.1: "`line_state` describes the line's posture, is one of `RUNNING`, `PAUSED` or `SHUTDOWN`, and defaults to `RUNNING`."

    Design: Corner/entities/factory_creation_returns_declared_fields_and_envelope
    """
    fx.set_clock(api)

    factory = validate_success(
        api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201
    )

    assert factory["shift_start_minute_of_day"] == 360
    assert factory["shift_minutes_per_day"] == 1080
    assert factory["line_state"] == "RUNNING"


# ─── Reading the project back ─────────────────────────────────────────────────
def test_reading_a_project_returns_the_row_the_program_office_opened(api):
    """PRD §3.1: "A freshly opened project begins with `permit_posture` at `DUAL_BLOCKED`, `phase` at `PRECONSTRUCTION`, all four of `wip_certified_cents`, `funded_to_date_cents`, `modules_set_count` and `modules_connected_count` at 0, and `version` at 1."
    PRD §3.1: "Reading a single project re-derives `permit_posture` and `phase` before responding, so a read is never stale even if the last mutation that should have moved them was applied elsewhere."
    PRD §2.3: "Single-resource responses omit all four."

    Design: Corner/entities/project_retrieval_returns_stored_row
    """
    world = fx.world_plant_and_project(api)

    response = api.get_project(world.project_id, world.superintendent)
    project = validate_success(response)

    assert_single_resource_meta_omits_paging(response.json())
    assert project["id"] == world.project_id
    assert project["name"] == f.PROJECT_NAME
    assert project["state_code"] == "WA"
    assert project["ahj_code"] == "SEA"
    assert project["factory_id"] == world.factory_id
    assert project["planned_module_count"] == 4
    assert_cents(project["contract_price_cents"], 3200000000, "contract_price_cents")
    assert project["permit_posture"] == "DUAL_BLOCKED"
    assert project["phase"] == "PRECONSTRUCTION"
    assert_cents(project["wip_certified_cents"], 0, "wip_certified_cents")
    assert_cents(project["funded_to_date_cents"], 0, "funded_to_date_cents")
    assert project["modules_set_count"] == 0
    assert project["modules_connected_count"] == 0
    # A read is a read: it re-derives, it does not mutate.
    assert project["version"] == 1


def test_the_crane_chart_comes_back_in_the_order_the_site_declared_it(api):
    """PRD §3.1: "`crane_capacity_chart` is a required, non-empty ordered array of objects, each carrying an integer `radius_ft` and an integer `capacity_lb`; the `radius_ft` values are strictly ascending across the array and the `capacity_lb` values strictly descending, which is simply the physical fact that a crane lifts less the further out it reaches."

    Design: Corner/entities/project_retrieval_returns_stored_row
    """
    world = fx.world_plant_and_project(
        api,
        project_overrides={
            "crane_capacity_chart": [
                {"radius_ft": 60, "capacity_lb": 150000},
                {"radius_ft": 90, "capacity_lb": 96000},
            ]
        },
    )

    project = validate_success(api.get_project(world.project_id, PROGRAM_ADMIN))

    assert project["crane_capacity_chart"] == [
        {"radius_ft": 60, "capacity_lb": 150000},
        {"radius_ft": 90, "capacity_lb": 96000},
    ]


def test_a_project_opened_without_financing_or_site_parameters_takes_the_declared_defaults(
    api,
):
    """PRD §3.1: "Financing rates are optional with defaults: `deposit_pct` is the fraction of factory work-in-progress value financeable as a deposit draw, must be greater than 0 and no more than 1, and defaults to 0.20; `retainage_pct` is the fraction of each certified draw withheld, must be at least 0 and strictly less than 1, and defaults to 0.05."
    PRD §3.1: "`crane_rigging_buffer_minutes` is the rig-up and rig-down buffer applied to *both* ends of every crane pick window and defaults to 45 minutes — three quarters of an hour of exclusivity purchased on each side of every lift."
    PRD §3.1: "`weather_exposure_limit_hours` is the maximum number of hours a set module may remain open before protection is deemed breached, must be greater than 0, and defaults to 8.0."

    Design: Corner/entities/project_retrieval_returns_stored_row
    """
    world = fx.world_plant_and_project(api)

    project = validate_success(api.get_project(world.project_id, PROGRAM_ADMIN))

    assert_two_decimal_value(project["deposit_pct"], 0.20, "deposit_pct")
    assert_two_decimal_value(project["retainage_pct"], 0.05, "retainage_pct")
    assert project["crane_rigging_buffer_minutes"] == 45
    assert_two_decimal_value(
        project["weather_exposure_limit_hours"], 8.0, "weather_exposure_limit_hours"
    )
    assert project["set_sequence_policy"] == "STRICT_ASCENDING"


# ─── Walking the module register ──────────────────────────────────────────────
@pytest.fixture
def three_modules_in_shop_code_order(api):
    """Three modules of one project, each persisted at its own clock instant.

    The clock is moved between the three creates so that the register has a
    strict oldest-first order to page through rather than a tie to break.
    """
    world = fx.world_with_module(api)
    fx.set_clock(api, "2026-09-01T09:00:00Z")
    fx.add_module(world, "M-02", 2)
    fx.set_clock(api, "2026-09-01T10:00:00Z")
    fx.add_module(world, "M-03", 3)
    return world


def test_a_module_page_of_two_at_offset_one_leaves_out_exactly_the_oldest_row(
    three_modules_in_shop_code_order,
):
    """PRD §2.3: "Unless a list endpoint states otherwise, results are ordered by `created_at` ascending — oldest row first."
    PRD §2.3: "For every list response the `meta` object carries `limit` (the effective page size actually applied), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before paging), and `has_more` (true when rows remain beyond the current page)."
    PRD §3.4: "Modules may be listed filtered by `project_id`, `design_package_id`, `shipment_id`, `production_status`, `qc_status`, `site_status` or `envelope_class`."

    Design: Corner/entities/modules_listing_filters_and_paginates
    """
    world = three_modules_in_shop_code_order

    rows, meta = validate_paginated(
        world.api.list_modules(
            {"project_id": world.project_id, "limit": 2, "offset": 1},
            world.factory_manager,
        )
    )

    assert _codes(rows) == ["M-02", "M-03"]
    assert_created_at_ascending(rows)
    # total_count counts the filter matches before paging, so it stays at three.
    assert_list_meta(meta, 2, 1, 3, False)


def test_filtering_the_register_by_a_status_no_module_holds_returns_an_empty_page(
    three_modules_in_shop_code_order,
):
    """PRD §3.4: "Modules may be listed filtered by `project_id`, `design_package_id`, `shipment_id`, `production_status`, `qc_status`, `site_status` or `envelope_class`."
    PRD §2.3: "For every list response the `meta` object carries `limit` (the effective page size actually applied), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before paging), and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/modules_listing_filters_and_paginates
    """
    world = three_modules_in_shop_code_order

    rows, meta = validate_paginated(
        world.api.list_modules(
            {"project_id": world.project_id, "production_status": "SLOTTED"},
            world.factory_manager,
        )
    )

    # All three modules are still PLANNED — an unmatched filter is an empty
    # page, not a missing collection.
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# ─── Naming a revision that was never created ─────────────────────────────────
def test_an_unknown_revision_identifier_answers_the_design_package_not_found_code(api):
    """PRD §2.5: "An unresolvable identifier produces the 404 that names the missing type: `ERR_FACTORY_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_PACKAGE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_DEFECT_CLAIM_NOT_FOUND` or `ERR_DRAW_NOT_FOUND`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/design_package_get_with_unknown_id_returns_not_found
    """
    fx.set_clock(api)

    response = api.get_design_package(NON_EXISTENT_UUID, DESIGN_ENGINEER_SUBMITTER)
    error = validate_error(response, ERR_DESIGN_PACKAGE_NOT_FOUND)

    assert error["message"].strip() != ""
    body = response.json()
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert_envelope_meta(body)


# ─── Declaring a module without its weight ────────────────────────────────────
def test_a_module_declared_without_its_gross_weight_is_refused(api):
    """PRD §3.4: "The shipping envelope is declared with four required integers, each at least 1: `width_in`, `length_in`, `height_in` — the height measured as the module will sit on the carrier — and `gross_weight_lb`."
    PRD §2.6: "`ERR_INVALID_REQUEST` — the body parses, every required input field is present, every enum-valued field carries a declared member, integer fields hold integers, percentage fields lie between 0 and 100 inclusive, and every numeric constraint stated in this document holds."

    Design: Corner/entities/module_create_without_gross_weight_is_rejected
    """
    world = fx.world_plant_and_project(api)
    package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )

    validate_error(
        api.create_module(
            f.module_payload(
                world.project_id, package["id"], "M-01", 1, gross_weight_lb=...
            ),
            world.factory_manager,
        ),
        ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(
        api.list_modules({"project_id": world.project_id}, world.factory_manager)
    )
    assert rows == []
    assert meta["total_count"] == 0


# ─── Opening a load ───────────────────────────────────────────────────────────
def test_a_freshly_opened_load_takes_every_declared_transport_default(api):
    """PRD §3.6: "A new load begins with `status` `DRAFT`, `route_survey_state` `NOT_REQUIRED`, `max_envelope_class` `STANDARD`, `loaded_module_count` 0, `permit_fee_cents` 0, `escort_required` false, `escort_confirmed` false, `survey_completed_at`, `permit_expires_at`, `dispatched_at`, `delivered_at` and `cancel_reason` all null, and `version` 1."

    Design: Corner/entities/shipment_create_applies_declared_defaults
    """
    world = fx.world_plant_and_project(api)

    shipment = validate_success(
        api.create_shipment(
            f.shipment_payload(world.project_id), TRANSPORT_COORDINATOR
        ),
        201,
    )

    assert_common_fields(shipment, expected_version=1)
    assert shipment["status"] == "DRAFT"
    assert shipment["route_survey_state"] == "NOT_REQUIRED"
    assert shipment["max_envelope_class"] == "STANDARD"
    assert shipment["loaded_module_count"] == 0
    assert_cents(shipment["permit_fee_cents"], 0, "permit_fee_cents")
    assert shipment["escort_required"] is False
    assert shipment["escort_confirmed"] is False
    assert shipment["survey_completed_at"] is None
    assert shipment["permit_expires_at"] is None
    assert shipment["dispatched_at"] is None
    assert shipment["delivered_at"] is None
    assert shipment["cancel_reason"] is None


def test_an_empty_load_prices_at_nothing_however_many_states_the_route_crosses(api):
    """PRD §3.6: "The shipment's `max_envelope_class` is the widest `envelope_class` among the modules currently aboard, ordering the classes `STANDARD` below `OVERWIDTH` below `SUPERLOAD`, and it is `STANDARD` whenever the load is empty."
    PRD §3.6: "`permit_fee_cents` is then a base state permit fee of $250.00 — that is 25,000 cents — multiplied by the number of entries in `route_state_codes`, multiplied again by that class multiplier."
    PRD §3.6: "Because the standard multiplier is zero, a standard load is fee-free no matter how many states the route crosses."

    Design: Corner/entities/shipment_permit_fee_is_computed_and_client_input_ignored
    """
    world = fx.world_plant_and_project(api)

    shipment = validate_success(
        api.create_shipment(
            f.shipment_payload(
                world.project_id,
                ["WA", "OR"],
                permit_fee_cents=999999,
                max_envelope_class="SUPERLOAD",
                loaded_module_count=7,
            ),
            TRANSPORT_COORDINATOR,
        ),
        201,
    )

    # A two-state route at the standard multiplier of zero is still fee-free,
    # and the caller's claim of a superload aboard an empty load counts for
    # nothing.
    assert shipment["max_envelope_class"] == "STANDARD"
    assert_cents(shipment["permit_fee_cents"], 0, "permit_fee_cents")
    assert shipment["loaded_module_count"] == 0
    assert shipment["route_state_codes"] == ["WA", "OR"]


def test_the_escort_obligation_of_an_empty_load_is_derived_and_not_asserted(api):
    """PRD §3.6: "`escort_required` becomes true when `max_envelope_class` is `SUPERLOAD`, and also when `max_envelope_class` is `OVERWIDTH` and the route crosses two or more states; otherwise it is false, and whenever it is false the shipment's `escort_confirmed` is forced back to false as well."

    Design: Corner/entities/shipment_permit_fee_is_computed_and_client_input_ignored
    """
    world = fx.world_plant_and_project(api)

    shipment = validate_success(
        api.create_shipment(
            f.shipment_payload(
                world.project_id,
                ["WA", "OR"],
                max_envelope_class="SUPERLOAD",
                escort_required=True,
                escort_confirmed=True,
            ),
            TRANSPORT_COORDINATOR,
        ),
        201,
    )

    assert shipment["escort_required"] is False
    assert shipment["escort_confirmed"] is False


# ─── Server-minted identity on the plant row ──────────────────────────────────
def test_a_plant_identifier_is_minted_by_the_server_not_taken_from_the_payload(api):
    """PRD §2.4: "Every resource in the system — `Factory`, `InspectionAgency`, `Project`, `DesignPackage`, `ModuleUnit`, `PermitRecord`, `InspectionRecord`, `Shipment`, `DefectClaim` and `DrawRequest` — is identified by an `id` that the server mints as a UUID."
    PRD §2.4: "Identifiers carry no type prefix and no domain-flavoured encoding; a caller must never parse an `id` to learn what kind of thing it points at."

    Design: Corner/entities/factory_system_fields_are_server_minted_and_client_input_ignored
    """
    fx.set_clock(api)

    factory = validate_success(
        api.create_factory(
            f.factory_payload(id="fac_seeded_by_client"), PROGRAM_ADMIN
        ),
        201,
    )

    assert factory["id"] != "fac_seeded_by_client"
    assert_common_fields(factory, expected_version=1)
    assert validate_success(api.get_factory(factory["id"], PROGRAM_ADMIN))["code"] == (
        f.FACTORY_CODE
    )


def test_a_client_cannot_seed_the_plant_version_or_its_capacity_ledger(api):
    """PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."
    PRD §2.4: "`created_at` is the instant the row was first persisted, `updated_at` is the instant of the most recent mutation, and both are rendered as ISO 8601 UTC timestamps with exactly three fractional-second digits."
    PRD §3.1: "A newly registered plant begins with `committed_line_minutes` at 0 and `version` at 1."

    Design: Corner/entities/factory_system_fields_are_server_minted_and_client_input_ignored
    """
    fx.set_clock(api)

    factory = validate_success(
        api.create_factory(
            f.factory_payload(version=42, committed_line_minutes=5000), PROGRAM_ADMIN
        ),
        201,
    )

    assert factory["version"] == 1
    assert factory["committed_line_minutes"] == 0
    # Nothing has mutated the row yet, so the two stamps name one instant.
    assert parse_instant(factory["created_at"]) == parse_instant(factory["updated_at"])


# ─── Constrained values on the agency panel and the project ───────────────────
def test_an_agency_registered_with_an_undeclared_accreditation_posture_is_refused(api):
    """PRD §3.1: "`accreditation_state` is one of `ACCREDITED`, `PROBATION` or `SUSPENDED` and defaults to `ACCREDITED`."
    PRD §2.6: "`ERR_INVALID_REQUEST` — the body parses, every required input field is present, every enum-valued field carries a declared member, integer fields hold integers, percentage fields lie between 0 and 100 inclusive, and every numeric constraint stated in this document holds."

    Design: Corner/entities/agency_accreditation_state_rejects_undeclared_enum_value
    """
    fx.set_clock(api)

    validate_error(
        api.create_agency(
            f.agency_payload(accreditation_state="REVOKED"), PROGRAM_ADMIN
        ),
        ERR_INVALID_REQUEST,
    )

    # A refused posture is neither stored nor quietly coerced to the default.
    rows, meta = validate_paginated(
        api.list_agencies({"agency_code": f.AGENCY_CODE}, PROGRAM_ADMIN)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_project_planned_for_no_modules_at_all_is_refused_at_the_boundary(api):
    """PRD §3.1: "A `ProgramAdmin` supplies the project `name`, the `factory_id` of the plant that will manufacture its modules, the two-character uppercase `state_code` whose modular program will approve the design, the `ahj_code` identifying the local authority having jurisdiction for site permits, the `planned_module_count` the building is split into (at least 1), and the `contract_price_cents` total contract value in cents."
    PRD §2.6: "`ERR_INVALID_REQUEST` — the body parses, every required input field is present, every enum-valued field carries a declared member, integer fields hold integers, percentage fields lie between 0 and 100 inclusive, and every numeric constraint stated in this document holds."

    Design: Corner/entities/project_planned_module_count_below_one_is_rejected
    """
    fx.set_clock(api)
    factory = fx.create_factory(api)

    # One below the floor is refused, the floor itself and one above it stand.
    validate_error(
        api.create_project(
            f.project_payload(factory["id"], planned_module_count=0), PROGRAM_ADMIN
        ),
        ERR_INVALID_REQUEST,
    )

    single = validate_success(
        api.create_project(
            f.project_payload(factory["id"], planned_module_count=1), PROGRAM_ADMIN
        ),
        201,
    )
    assert single["planned_module_count"] == 1

    pair = validate_success(
        api.create_project(
            f.project_payload(
                factory["id"], name="Cedar Court", planned_module_count=2
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert pair["planned_module_count"] == 2


# ─── References that resolve but belong elsewhere ─────────────────────────────
def test_a_module_detailed_against_another_projects_revision_is_refused(api):
    """PRD §3.4: "The referenced design revision must belong to the project named by `project_id`; a cross-project reference is rejected with `ERR_CROSS_AGGREGATE_MISMATCH`."
    PRD §2.5: "Existence resolution answers only *does the row exist*; whether the row belongs to the right aggregate is a separate, much later check described in §2.6 and §3."

    Design: Corner/entities/module_create_with_design_package_of_another_project_is_rejected
    """
    world = fx.world_plant_and_project(api)
    neighbour = fx.create_project(
        api,
        world.factory_id,
        name="Cedar Court",
        ahj_code="TAC",
        contract_price_cents=2800000000,
    )
    neighbours_package = fx.create_design_package(
        api, neighbour["id"], neighbour["version"]
    )

    validate_error(
        api.create_module(
            f.module_payload(
                world.project_id, neighbours_package["id"], "M-01", 1
            ),
            world.factory_manager,
        ),
        ERR_CROSS_AGGREGATE_MISMATCH,
    )

    # The revision does exist, so this is not a missing-row answer, and no
    # module was persisted against the wrong revision.
    validate_success(
        api.get_design_package(neighbours_package["id"], DESIGN_ENGINEER_SUBMITTER)
    )
    rows, _ = validate_paginated(
        api.list_modules({"project_id": world.project_id}, world.factory_manager)
    )
    assert rows == []


def test_filing_a_permit_application_against_an_unknown_project_answers_not_found(api):
    """PRD §2.5: "Foreign keys arriving in a request body are resolved next, after every path identifier has been confirmed, using the same catalogue of 404 codes."
    PRD §2.6: "Existence of every foreign key in the request body, reporting the matching `*_NOT_FOUND` code."
    PRD §2.5: "An unresolvable identifier produces the 404 that names the missing type: `ERR_FACTORY_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_PACKAGE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_DEFECT_CLAIM_NOT_FOUND` or `ERR_DRAW_NOT_FOUND`."

    Design: Corner/entities/permit_create_with_unknown_project_returns_project_not_found
    """
    fx.set_clock(api)

    validate_error(
        api.create_permit(
            f.permit_payload(NON_EXISTENT_UUID, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"),
            PROGRAM_ADMIN,
        ),
        ERR_PROJECT_NOT_FOUND,
    )

    rows, _ = validate_paginated(api.list_permits({}, PROGRAM_ADMIN))
    assert rows == []


# ─── The claim that joins a module to an inspection record ────────────────────
@pytest.fixture
def two_modules_and_one_inspection_record(api):
    """Two modules of one project, with an in-plant record opened on M-01 only.

    M-01 has walked the whole line, which is what lets an inspection be opened
    against it; M-02 is still waiting its turn on the shop floor.
    """
    world = fx.world_line_complete_module(api)
    fx.add_module(world, "M-02", 2)
    world.inspections["M-01:IN_PLANT"] = fx.open_inspection(
        api, world.module_id("M-01"), world.agency_id, "IN_PLANT"
    )
    return world


def test_a_defect_claim_citing_another_modules_inspection_record_is_refused(
    two_modules_and_one_inspection_record,
):
    """PRD §3.8: "It may optionally reference an `inspection_id`, the inspection record that evidences the defect; that reference, when supplied, must belong to the same module named by `module_id`, or the claim is rejected with `ERR_CROSS_AGGREGATE_MISMATCH`."
    PRD §2.5: "Existence resolution answers only *does the row exist*; whether the row belongs to the right aggregate is a separate, much later check described in §2.6 and §3."

    Design: Corner/entities/graph_topology_defect_claim_joins_module_and_inspection_record
    """
    world = two_modules_and_one_inspection_record
    record = world.inspections["M-01:IN_PLANT"]

    validate_error(
        world.api.create_defect_claim(
            f.defect_claim_payload(
                world.module_id("M-02"), "FACTORY", 1234567, inspection_id=record["id"]
            ),
            world.factory_manager,
        ),
        ERR_CROSS_AGGREGATE_MISMATCH,
    )

    rows, _ = validate_paginated(
        world.api.list_defect_claims(
            {"inspection_id": record["id"]}, WARRANTY_ADJUDICATOR
        )
    )
    assert rows == []


def test_a_defect_claim_citing_its_own_modules_record_is_navigable_from_either_side(
    two_modules_and_one_inspection_record,
):
    """PRD §3.8: "It may optionally reference an `inspection_id`, the inspection record that evidences the defect; that reference, when supplied, must belong to the same module named by `module_id`, or the claim is rejected with `ERR_CROSS_AGGREGATE_MISMATCH`."
    PRD §3.8: "A new claim is persisted with `status` `OPEN`, `responsibility` `UNDETERMINED`, `adjudication_round` 0, all four of `factory_share_pct`, `field_share_pct`, `factory_charge_cents` and `field_charge_cents` at 0, `warranty_bucket` at its default of `SPLIT`, `adjudicated_by_user_id` and `dispute_note` null, and `version` 1."
    PRD §3.8: "Claims may be listed filtered by `module_id`, `inspection_id`, `status`, `responsibility`, `discovered_phase` or `warranty_bucket`."

    Design: Corner/entities/graph_topology_defect_claim_joins_module_and_inspection_record
    """
    world = two_modules_and_one_inspection_record
    record = world.inspections["M-01:IN_PLANT"]

    claim = validate_success(
        world.api.create_defect_claim(
            f.defect_claim_payload(
                world.module_id("M-01"), "FACTORY", 1234567, inspection_id=record["id"]
            ),
            world.factory_manager,
        ),
        201,
    )

    assert claim["module_id"] == world.module_id("M-01")
    assert claim["inspection_id"] == record["id"]
    assert claim["status"] == "OPEN"
    assert claim["responsibility"] == "UNDETERMINED"
    assert claim["warranty_bucket"] == "SPLIT"
    assert claim["adjudication_round"] == 0

    from_the_record, _ = validate_paginated(
        world.api.list_defect_claims(
            {"inspection_id": record["id"]}, WARRANTY_ADJUDICATOR
        )
    )
    assert [row["id"] for row in from_the_record] == [claim["id"]]

    from_the_module, _ = validate_paginated(
        world.api.list_defect_claims(
            {"module_id": world.module_id("M-01")}, WARRANTY_ADJUDICATOR
        )
    )
    assert [row["id"] for row in from_the_module] == [claim["id"]]
