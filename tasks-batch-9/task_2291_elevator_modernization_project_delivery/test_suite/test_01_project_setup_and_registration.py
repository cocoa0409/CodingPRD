"""Standing up a delivery: the jurisdiction, the project, the groups and the cars."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    anchor_clock,
    api_client,
    assert_common_fields,
    assert_jurisdiction,
    assert_project,
    countersign_survey,
    create_jurisdiction,
    get_success_data,
    is_valid_uuid,
    read_group,
    read_jurisdiction,
    read_posture,
    read_project,
    setup_project,
    setup_project_with_cars,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INITIAL_CLOCK_TIMESTAMP
from test_helpers.fixtures import OPS, PM, TECH, create_car, create_group


def test_jurisdiction_creation_echoes_every_declared_input():
    """A `SystemOperator` registers one by supplying its display `name` and the
    `code_edition_year` of the elevator safety code it enforces, which must fall between
    2000 and 2030 inclusive, together with three code posture flags:
    `fire_service_required`, the `seismic_zone` — a seismic design category between 0 and
    4 inclusive — and `door_protection_required`.

    `id` is a server-minted UUID with no type prefix, assigned at creation and never
    reused or reassigned; clients never supply it.

    Design: Corner/entities/jurisdiction_creation_echoes_every_declared_input_field
    """
    anchor_clock()

    response = api_client.create_jurisdiction(
        {
            "name": "County of Marlow",
            "code_edition_year": 2022,
            "fire_service_required": True,
            "seismic_zone": 3,
            "door_protection_required": True,
            "inspection_lead_days": 14,
            "witness_test_required": True,
            "reinspection_extension_hours": 48,
            "permit_surcharge_pct": 0.0250,
        },
        OPS,
    )
    jurisdiction = validate_success(response, expected_status=201)

    assert jurisdiction["name"] == "County of Marlow"
    assert jurisdiction["code_edition_year"] == 2022
    assert jurisdiction["fire_service_required"] is True
    assert jurisdiction["seismic_zone"] == 3
    assert jurisdiction["door_protection_required"] is True
    assert jurisdiction["inspection_lead_days"] == 14
    assert jurisdiction["witness_test_required"] is True
    assert jurisdiction["reinspection_extension_hours"] == 48
    assert jurisdiction["permit_surcharge_pct"] == 0.0250

    assert_jurisdiction(jurisdiction)
    assert is_valid_uuid(jurisdiction["id"])
    assert jurisdiction["version"] == 1
    assert jurisdiction["created_at"] == INITIAL_CLOCK_TIMESTAMP
    assert jurisdiction["updated_at"] == jurisdiction["created_at"]

    envelope = response.json()
    assert envelope["meta"]["api_request_id"]
    assert envelope["meta"]["api_request_timestamp"]


def test_jurisdiction_omitted_optional_inputs_take_their_declared_defaults():
    """`inspection_lead_days` is the minimum number of whole days that must separate the
    logical clock from any requested or rescheduled inspection date, and defaults to 10.
    `witness_test_required` defaults to false; when a jurisdiction sets it true, an
    inspection request that does not state otherwise is opened with a witnessed
    acceptance test requested. `reinspection_extension_hours` is the number of hours a
    reopened outage window gains when an inspection is recorded as a failure, and
    defaults to 24 — one full day of extra outage as the standing price of a failed
    acceptance test. `permit_surcharge_pct` is the permit surcharge applied to each
    priced code trigger and defaults to 0.0000.

    Design: Corner/entities/jurisdiction_omitted_optional_inputs_apply_declared_defaults
    """
    anchor_clock()

    response = api_client.create_jurisdiction(
        {
            "name": "City of Brentwood",
            "code_edition_year": 2019,
            "fire_service_required": False,
            "seismic_zone": 0,
            "door_protection_required": False,
        },
        OPS,
    )
    jurisdiction = validate_success(response, expected_status=201)

    assert jurisdiction["inspection_lead_days"] == 10
    assert jurisdiction["witness_test_required"] is False
    assert jurisdiction["reinspection_extension_hours"] == 24
    assert jurisdiction["permit_surcharge_pct"] == 0.0000

    stored = read_jurisdiction(jurisdiction["id"])
    assert stored["inspection_lead_days"] == 10
    assert stored["witness_test_required"] is False
    assert stored["reinspection_extension_hours"] == 24
    assert stored["permit_surcharge_pct"] == 0.0000


def test_new_project_initializes_its_phase_posture_and_four_counters():
    """A new project opens in phase `SURVEY` with a `downtime_posture` of `OPEN` and all
    four of its counters — `car_count`, `approved_scope_value_cents`,
    `staging_committed_sqft` and `active_outage_count` — at zero.

    Two governance parameters are optional: `outage_buffer_hours`, the separation
    required between two outage windows on cars of the same hoistway group, defaulting to
    4; and `tenant_notice_lead_hours`, the minimum advance notice an outage window must
    carry before it may be activated, defaulting to 72 — three full days, which is what
    most residential leases assume.

    Design: Corner/entities/project_system_and_computed_fields_are_server_initialized
    """
    anchor_clock()
    jurisdiction = create_jurisdiction()

    response = api_client.create_project(
        {
            "jurisdiction_id": jurisdiction["id"],
            "building_name": "Brentwood Tower",
            "occupancy_type": "OCCUPIED",
            "contract_value_cents": 60_000_000,
            "staging_area_sqft": 1200,
            "max_concurrent_outages": 2,
        },
        PM,
    )
    project = validate_success(response, expected_status=201)

    assert project["status"] == "SURVEY"
    assert project["car_count"] == 0
    assert project["approved_scope_value_cents"] == 0
    assert project["staging_committed_sqft"] == 0
    assert project["active_outage_count"] == 0
    assert project["downtime_posture"] == "OPEN"
    assert project["outage_buffer_hours"] == 4
    assert project["tenant_notice_lead_hours"] == 72
    assert project["version"] == 1
    assert project["created_at"] == INITIAL_CLOCK_TIMESTAMP
    assert_project(project)


def test_car_count_reconciles_on_the_project_and_on_each_group():
    """A newly registered car stands at `work_status` `SURVEY_PENDING` and
    `compliance_status` `NOT_EVALUATED`, with `condition_score`,
    `recommended_scope_tier` and `approved_scope_option_id` all null.

    Registering the car increments its group's `car_count` and `cars_in_service` by 1
    each, increments the project's `car_count` by 1 and the project's `version` by 1, and
    recomputes the project's downtime posture.

    Design: Corner/entities/car_count_reconciles_on_both_project_and_group_as_cars_are_added
    """
    ctx = setup_project()
    project_id = ctx["project"]["id"]
    bank_a = create_group(project_id, group_label="BANK-A", min_cars_in_service=0)
    bank_b = create_group(project_id, group_label="BANK-B", min_cars_in_service=0)

    specs = [
        (bank_a["id"], {"car_designation": "CAR-1", "duty_rank": 1}),
        (bank_a["id"], {"car_designation": "CAR-2", "duty_rank": 2}),
        (
            bank_b["id"],
            {
                "car_designation": "CAR-3",
                "duty_rank": 1,
                "rated_load_lbs": 4000,
                "controller_type_legacy": "MICROPROCESSOR",
                "machine_type": "MRL_GEARLESS",
            },
        ),
    ]
    for group_id, overrides in specs:
        response = api_client.create_elevator_car(
            {
                "project_id": project_id,
                "group_id": group_id,
                "rated_load_lbs": 3500,
                "controller_type_legacy": "RELAY",
                "machine_type": "GEARLESS",
                **overrides,
            },
            PM,
        )
        car = validate_success(response, expected_status=201)
        assert car["work_status"] == "SURVEY_PENDING"
        assert car["compliance_status"] == "NOT_EVALUATED"
        assert car["condition_score"] is None
        assert car["recommended_scope_tier"] is None
        assert car["approved_scope_option_id"] is None

    assert read_project(project_id)["car_count"] == 3

    group_a = read_group(bank_a["id"])
    assert group_a["car_count"] == 2
    assert group_a["cars_in_service"] == 2

    group_b = read_group(bank_b["id"])
    assert group_b["car_count"] == 1
    assert group_b["cars_in_service"] == 1

    assert read_posture(project_id)["groups_below_floor"] == 0


def test_car_read_returns_the_stored_row_with_both_status_dimensions():
    """Cars can be listed and narrowed by `project_id`, `group_id`, `work_status` or
    `compliance_status`, and a single car read returns both status dimensions along with
    its condition score.

    Design: Corner/entities/elevator_car_retrieval_returns_the_stored_row
    """
    ctx = setup_project()
    group = create_group(ctx["project"]["id"])
    car = create_car(
        ctx["project"]["id"],
        group["id"],
        car_designation="CAR-1",
        rated_load_lbs=3500,
        controller_type_legacy="SOLID_STATE_ANALOG",
        machine_type="GEARED",
        duty_rank=1,
    )

    stored = get_success_data(api_client.get_elevator_car(car["id"], TECH))

    assert stored["id"] == car["id"]
    assert stored["project_id"] == ctx["project"]["id"]
    assert stored["group_id"] == group["id"]
    assert stored["car_designation"] == "CAR-1"
    assert stored["rated_load_lbs"] == 3500
    assert stored["controller_type_legacy"] == "SOLID_STATE_ANALOG"
    assert stored["machine_type"] == "GEARED"
    assert stored["duty_rank"] == 1
    assert stored["work_status"] == "SURVEY_PENDING"
    assert stored["compliance_status"] == "NOT_EVALUATED"
    assert stored["version"] == 1
    assert_common_fields(stored)


def test_car_listing_partitions_by_work_status_and_carries_the_page_meta():
    """Alongside the request identifier and timestamp, the `meta` object of a list
    response carries `limit` and `offset` as they were applied, `total_count` giving the
    number of rows matching the request's filters before pagination, and `has_more`,
    which is true exactly when rows matching the filters remain beyond the current page.

    `limit` controls page size: it defaults to 10, may not be smaller than 1, and may not
    be larger than 100. `offset` controls the starting position in the result set: it
    defaults to 0 and may not be negative.

    Design: Corner/entities/elevator_car_listing_filters_by_work_status_with_pagination_fields
    """
    ctx = setup_project_with_cars(num_cars=2)
    surveyed_car, untouched_car = ctx["cars"]
    survey = submit_survey(
        surveyed_car["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
    )
    countersign_survey(survey["id"])

    rows, meta = validate_paginated(
        api_client.list_elevator_cars(
            PM, params={"project_id": ctx["project"]["id"], "work_status": "SURVEYED"}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert rows[0]["id"] == surveyed_car["id"]
    assert rows[0]["work_status"] == "SURVEYED"
    assert rows[0]["condition_score"] == 85.00

    pending_rows, pending_meta = validate_paginated(
        api_client.list_elevator_cars(
            PM,
            params={"project_id": ctx["project"]["id"], "work_status": "SURVEY_PENDING"},
        )
    )
    assert pending_meta["total_count"] == 1
    assert pending_rows[0]["id"] == untouched_car["id"]

    _, all_meta = validate_paginated(
        api_client.list_elevator_cars(PM, params={"project_id": ctx["project"]["id"]})
    )
    assert all_meta["total_count"] == 2


def test_reading_a_scope_option_that_does_not_exist_is_a_not_found():
    """**Path identifier resolution** — every identifier embedded in the request path must
    resolve to an existing row, and the identifiers are resolved strictly left to right,
    so the leftmost unresolvable identifier is the one reported. Any unresolvable path
    identifier yields the generic `ERR_NOT_FOUND` with HTTP 404.

    Design: Corner/entities/get_scope_option_with_unknown_id_returns_not_found
    """
    anchor_clock()

    response = api_client.get_scope_option(NON_EXISTENT_UUID, PM)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    assert response.json()["data"]["message"]

    _, meta = validate_paginated(api_client.list_scope_options(PM))
    assert meta["total_count"] == 0


def test_opening_a_project_without_the_staging_area_is_a_shape_failure():
    """**Request shape** — `ERR_INVALID_REQUEST`, HTTP 400, on every endpoint. All required
    input fields must be present, no unknown fields may appear, enum-valued fields must
    carry a value from their declared set, integers must be non-negative, monetary
    amounts must be non-negative whole numbers of cents, timestamps must be valid ISO
    8601 UTC, `hold_end` must be strictly after `hold_start`, `end_at` must be strictly
    after `start_at`, `seismic_zone` must lie between 0 and 4 inclusive,
    `warranty_months` must lie between 12 and 60 inclusive, and where a `basis` query
    parameter is required its value must be one of the declared basis names for that
    endpoint.

    Design: Corner/entities/post_projects_missing_staging_area_sqft_is_rejected_as_invalid_request
    """
    anchor_clock()
    jurisdiction = create_jurisdiction()

    response = api_client.create_project(
        {
            "jurisdiction_id": jurisdiction["id"],
            "building_name": "Brentwood Tower",
            "occupancy_type": "OCCUPIED",
            "contract_value_cents": 60_000_000,
            "max_concurrent_outages": 2,
        },
        PM,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    _, meta = validate_paginated(
        api_client.list_projects(PM, params={"jurisdiction_id": jurisdiction["id"]})
    )
    assert meta["total_count"] == 0


def test_a_condition_grade_outside_the_declared_scale_is_a_shape_failure():
    """Each grade is drawn from the same ordinal scale — `EXCELLENT`, `GOOD`, `FAIR`,
    `POOR`, `FAILED` or `NOT_OBSERVED` — where `NOT_OBSERVED` is the honest answer when a
    machine room was locked or a door operator could not be exercised.

    **Request shape** — `ERR_INVALID_REQUEST`, HTTP 400, on every endpoint.

    Design: Corner/entities/equipment_survey_with_undeclared_condition_enum_is_rejected
    """
    ctx = setup_project_with_cars(num_cars=1)

    response = api_client.create_equipment_survey(
        {
            "car_id": ctx["car"]["id"],
            "controller_condition": "MEDIOCRE",
            "machine_condition": "GOOD",
            "door_equipment_condition": "GOOD",
        },
        TECH,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_registering_a_car_into_an_unknown_group_is_a_not_found():
    """**Body foreign-key resolution** — every foreign key supplied in a request body must
    resolve to an existing row, validated in the order the fields are listed in the
    endpoint's input, again reporting `ERR_NOT_FOUND` with HTTP 404.

    Design: Corner/entities/elevator_car_creation_with_unknown_group_id_returns_not_found
    """
    ctx = setup_project()
    project_id = ctx["project"]["id"]

    response = api_client.create_elevator_car(
        {
            "project_id": project_id,
            "group_id": NON_EXISTENT_UUID,
            "car_designation": "CAR-1",
            "rated_load_lbs": 3500,
            "controller_type_legacy": "RELAY",
            "machine_type": "GEARLESS",
            "duty_rank": 1,
        },
        PM,
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    assert read_project(project_id)["car_count"] == 0
    _, meta = validate_paginated(
        api_client.list_elevator_cars(PM, params={"project_id": project_id})
    )
    assert meta["total_count"] == 0
