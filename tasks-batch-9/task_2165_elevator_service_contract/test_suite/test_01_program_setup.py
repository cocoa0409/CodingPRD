"""Standing up a building program: contracts, cars, listings and the logical clock."""
from test_helpers import (
    ApiErrorId,
    add_car,
    UNUSED_UUID,
    assert_elevator_car,
    assert_instant_equals,
    assert_service_contract,
    create_car_payload,
    create_contract_payload,
    plan_project,
    read_car,
    read_contract,
    read_project,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_contract_lands_in_draft_with_zeroed_ledger(api, admin_headers):
    """PRD §3.1: "A newly drafted contract lands in `status` `DRAFT` with `version` 1
    and its entire penalty ledger zeroed — `penalty_lifetime_assessed_cents`,
    `penalty_lifetime_waived_cents`, `penalty_lifetime_credited_cents` and
    `penalty_balance_cents` all 0 — along with `cars_out_of_service_count` 0,
    `renegotiation_round_count` 0, and `performance_score` null, because no score
    has yet been evaluated."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix of any kind."

    Design: Corner/entities/create_contract_returns_defaults_and_common_fields
    """
    payload = create_contract_payload(
        building_name="Corner One",
        building_address="1 Corner St",
        building_manager_user_id="bm-c1",
        contractor_user_id="sc-c1",
    )
    response = api.create_contract(payload, admin_headers)
    data = validate_success(response, 201)

    assert_service_contract(data)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["penalty_lifetime_assessed_cents"] == 0
    assert data["penalty_lifetime_waived_cents"] == 0
    assert data["penalty_lifetime_credited_cents"] == 0
    assert data["penalty_balance_cents"] == 0
    assert data["performance_score"] is None, "performance_score must start null"
    assert data["renegotiation_round_count"] == 0
    assert data["cars_out_of_service_count"] == 0

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_create_contract_missing_monthly_fee_is_rejected(api, admin_headers):
    """PRD §2.7: "Every required input field present; every enum field carrying a
    declared member; every datetime parsing as ISO 8601 UTC and every date as
    `YYYY-MM-DD`; every `period_month` matching a four-digit year, a hyphen, and a
    two-digit month in the range 01 through 12; `window_end` strictly after
    `window_start`; `term_end_date` strictly after `term_start_date`;
    `scheduled_date` falling inside the visit's `period_month`; and
    `passengers_trapped` at least 1 whenever `callback_type` is `ENTRAPMENT`. Any
    failure yields `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_contract_missing_required_field_returns_validation
    """
    payload = create_contract_payload(
        building_name="Corner Two",
        building_address="2 Corner St",
        building_manager_user_id="bm-c2",
        contractor_user_id="sc-c2",
    )
    payload.pop("monthly_base_fee_cents")

    validate_error(
        api.create_contract(payload, admin_headers), ApiErrorId.ERR_VALIDATION.value
    )

    rows, meta = validate_paginated(api.list_contracts(admin_headers))
    assert meta["total_count"] == 0, "no contract may be written by a rejected request"
    assert rows == []


def test_create_contract_with_undeclared_scope_type_is_rejected(api, admin_headers):
    """PRD §3.1: "`scope_type` is either `FULL_MAINTENANCE` or `OIL_AND_GREASE`, and
    it simultaneously selects which maintenance task codes are mandatory, which
    classes of spare part may be ordered, and which of the two uptime variants is
    used when money is at stake."
    PRD §2.7: "Every required input field present; every enum field carrying a
    declared member; every datetime parsing as ISO 8601 UTC and every date as
    `YYYY-MM-DD`; every `period_month` matching a four-digit year, a hyphen, and a
    two-digit month in the range 01 through 12; `window_end` strictly after
    `window_start`; `term_end_date` strictly after `term_start_date`;
    `scheduled_date` falling inside the visit's `period_month`; and
    `passengers_trapped` at least 1 whenever `callback_type` is `ENTRAPMENT`. Any
    failure yields `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_contract_invalid_enum_scope_type_returns_validation
    """
    payload = create_contract_payload(
        building_name="Corner Three",
        building_address="3 Corner St",
        building_manager_user_id="bm-c3",
        contractor_user_id="sc-c3",
        scope_type="PARTS_ONLY",
    )
    validate_error(
        api.create_contract(payload, admin_headers), ApiErrorId.ERR_VALIDATION.value
    )


def test_new_car_starts_in_service_regardless_of_supplied_state(api, admin_headers):
    """PRD §3.1: "A new car begins at `IN_SERVICE` and `INSPECTION_DUE`, with
    `version` 1, `scheduled_downtime_minutes` 0, `open_part_order_count` 0, and
    `unplanned_outage_open_since`, `red_tag_issued_at`, `red_tag_lifted_at`,
    `current_certificate_number` and `certificate_expiry_date` all null."
    PRD §2.10: "A newly registered car starts at `IN_SERVICE` on the first dimension
    and `INSPECTION_DUE` on the second."

    Design: Corner/entities/create_car_client_supplied_state_input_ignored
    """
    program = setup_program(activate=False, building_name="Corner Four")
    payload = create_car_payload(
        program.contract_id,
        car_code="CAR-C4",
        availability_state="DECOMMISSIONED",
        compliance_state="CERTIFIED",
    )
    data = validate_success(api.create_car(payload, admin_headers), 201)

    assert_elevator_car(data)
    assert data["availability_state"] == "IN_SERVICE"
    assert data["compliance_state"] == "INSPECTION_DUE"
    assert data["scheduled_downtime_minutes"] == 0
    assert data["open_part_order_count"] == 0
    assert data["version"] == 1
    assert data["unplanned_outage_open_since"] is None
    assert data["red_tag_issued_at"] is None
    assert data["red_tag_lifted_at"] is None
    assert data["current_certificate_number"] is None
    assert data["certificate_expiry_date"] is None


def test_get_contract_with_unused_id_returns_contract_not_found(api, admin_headers):
    """PRD §2.7: "Every resource the request names must exist, checked left to right:
    the identifier in the URL path first, and then the foreign-key fields in the
    request body in the fixed order `contract_id`, `car_id`, `part_id`, `window_id`,
    `project_id`. A missing contract yields `ERR_CONTRACT_NOT_FOUND`, a missing car
    `ERR_CAR_NOT_FOUND`, a missing spare part (whether named in the path, in
    `part_id`, or in `replacement_part_id`) `ERR_PART_NOT_FOUND`, and a missing
    visit, callback, inspection, project, downtime window, part order, penalty
    assessment or renegotiation round `ERR_RESOURCE_NOT_FOUND` — all with HTTP 404."

    Design: Corner/entities/get_contract_with_unknown_id_returns_not_found
    """
    response = api.get_contract(UNUSED_UUID, admin_headers)
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_create_car_under_unknown_contract_returns_contract_not_found(api, admin_headers):
    """PRD §2.7: "Every resource the request names must exist, checked left to right:
    the identifier in the URL path first, and then the foreign-key fields in the
    request body in the fixed order `contract_id`, `car_id`, `part_id`, `window_id`,
    `project_id`. A missing contract yields `ERR_CONTRACT_NOT_FOUND`, a missing car
    `ERR_CAR_NOT_FOUND`, a missing spare part (whether named in the path, in
    `part_id`, or in `replacement_part_id`) `ERR_PART_NOT_FOUND`, and a missing
    visit, callback, inspection, project, downtime window, part order, penalty
    assessment or renegotiation round `ERR_RESOURCE_NOT_FOUND` — all with HTTP 404."

    Design: Corner/entities/create_car_under_unknown_contract_returns_not_found
    """
    payload = create_car_payload(UNUSED_UUID, car_code="CAR-GHOST")
    validate_error(
        api.create_car(payload, admin_headers), ApiErrorId.ERR_CONTRACT_NOT_FOUND.value
    )

    rows, meta = validate_paginated(api.list_cars(admin_headers))
    assert meta["total_count"] == 0, "a rejected creation must write no car row"
    assert rows == []


def test_list_cars_paginates_and_filters_by_contract(api, admin_headers):
    """PRD §2.3: "`limit` controls page size: its default is 10, its minimum accepted
    value is 1, and its maximum accepted value is 100."
    PRD §2.3: "`total_count` reports the number of records matching the filters
    before pagination was applied, and `has_more` is true when records remain beyond
    the current page."
    PRD §2.11: "cars can be filtered by `contract_id`, `availability_state` and
    `compliance_state`"

    Design: Corner/entities/list_cars_supports_limit_offset_and_contract_filter
    """
    program = setup_program(
        ["CAR-01", "CAR-02"], building_name="Corner Six", building_address="6 Corner St"
    )
    add_car(program, "CAR-03", car_type="HYDRAULIC", capacity_lbs=2000)

    first = api.list_cars(
        admin_headers, {"contract_id": program.contract_id, "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first)
    assert len(rows) == 2, f"expected 2 rows on page one, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert first.json()["response_type"] == "array"

    second = api.list_cars(
        admin_headers, {"contract_id": program.contract_id, "limit": 2, "offset": 2}
    )
    rows2, meta2 = validate_paginated(second)
    assert len(rows2) == 1, f"expected 1 row on page two, got {len(rows2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2
    assert second.json()["response_type"] == "array"


def test_activating_an_already_active_contract_is_rejected(api, admin_headers):
    """PRD §3.1: "Activation by a `ProgramAdministrator` moves it `DRAFT → ACTIVE`;
    it requires that the contract is still in `DRAFT` and that `term_end_date` is
    strictly later than `term_start_date`, and it increments the contract's
    `version` by 1."
    PRD §2.7: "The target resource must currently sit in a state from which the
    requested transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION`
    (409)."

    Design: Corner/state_machines/activate_an_already_active_contract_is_rejected
    """
    program = setup_program(building_name="SM One", building_address="1 SM St")
    assert program.contract["version"] == 2, (
        "the first activation increments version from 1 to 2"
    )

    validate_error(
        api.activate_contract(program.contract_id, admin_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    after = read_contract(program.contract_id, admin_headers)
    assert after["status"] == "ACTIVE"
    assert after["version"] == 2, "a rejected activation must not bump version again"


def test_terminated_contract_refuses_further_transitions(api, admin_headers):
    """PRD §3.1: "every modernization project on the contract in `PLANNED`,
    `APPROVED`, `IN_PROGRESS` or `AT_RISK` becomes `CANCELLED`, which in turn sets
    each of that project's `SCHEDULED` downtime windows to `CANCELLED` and
    recomputes the affected cars' `scheduled_downtime_minutes`; and the contract
    itself moves to `TERMINATED` with its `version` incremented by 1. `TERMINATED`
    is terminal — nothing leaves it."
    PRD §2.7: "The target resource must currently sit in a state from which the
    requested transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION`
    (409)."

    Design: Corner/state_machines/terminated_contract_is_locked_down_for_further_transitions
    """
    program = setup_program(building_name="SM Two", building_address="2 SM St")
    project = plan_project(
        program,
        title="Doomed project",
        budget_cents=1_000_000,
        target_completion_date="2026-12-01",
    )
    validate_success(api.terminate_contract(program.contract_id, admin_headers))

    validate_error(
        api.terminate_contract(program.contract_id, admin_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    assert read_contract(program.contract_id, admin_headers)["status"] == "TERMINATED"
    assert read_project(project["id"], admin_headers)["status"] == "CANCELLED"


def test_unknown_renegotiation_round_returns_resource_not_found(
    api, building_manager_headers
):
    """PRD §2.7: "Every resource the request names must exist, checked left to right:
    the identifier in the URL path first, and then the foreign-key fields in the
    request body in the fixed order `contract_id`, `car_id`, `part_id`, `window_id`,
    `project_id`. A missing contract yields `ERR_CONTRACT_NOT_FOUND`, a missing car
    `ERR_CAR_NOT_FOUND`, a missing spare part (whether named in the path, in
    `part_id`, or in `replacement_part_id`) `ERR_PART_NOT_FOUND`, and a missing
    visit, callback, inspection, project, downtime window, part order, penalty
    assessment or renegotiation round `ERR_RESOURCE_NOT_FOUND` — all with HTTP 404."

    Design: Corner/errors/unknown_renegotiation_round_returns_resource_not_found
    """
    validate_error(
        api.get_renegotiation(UNUSED_UUID, building_manager_headers),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
    )


def test_uptime_report_for_unknown_car_returns_car_not_found(api, admin_headers):
    """PRD §2.7: "Every resource the request names must exist, checked left to right:
    the identifier in the URL path first, and then the foreign-key fields in the
    request body in the fixed order `contract_id`, `car_id`, `part_id`, `window_id`,
    `project_id`. A missing contract yields `ERR_CONTRACT_NOT_FOUND`, a missing car
    `ERR_CAR_NOT_FOUND`, a missing spare part (whether named in the path, in
    `part_id`, or in `replacement_part_id`) `ERR_PART_NOT_FOUND`, and a missing
    visit, callback, inspection, project, downtime window, part order, penalty
    assessment or renegotiation round `ERR_RESOURCE_NOT_FOUND` — all with HTTP 404."

    Design: Corner/errors/uptime_report_for_an_unknown_car_returns_car_not_found
    """
    response = api.get_uptime_report(UNUSED_UUID, "2026-08", admin_headers)
    validate_error(response, ApiErrorId.ERR_CAR_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_logical_clock_starts_at_the_fixed_startup_instant(api, admin_headers):
    """PRD §2.5: "On startup the clock reads exactly `2026-08-01T00:00:00Z`; before
    any administrator has set it, that is the value it reports, and it never
    silently falls back to the host's real time."
    PRD §3.3: "The callback is created in `status` `REPORTED` with `reported_at`
    stamped from the logical clock; that instant is both the start of the
    response-time measurement and the start of any unplanned outage interval the
    call contributes."
    PRD §2.5: "The response reports the resulting `current_utc` together with five
    counters describing what the move triggered: `missed_visits_marked`,
    `rejected_visits_marked`, `certificates_expired`, `windows_completed` and
    `cars_under_modernization`."

    Design: Corner/endpoints/default_logical_clock_reads_the_fixed_startup_instant
    """
    program = setup_program(
        ["CAR-E1"],
        building_name="Ep One",
        building_address="1 Ep St",
        building_manager_user_id="bm-e1",
        contractor_user_id="sc-e1",
    )
    callback = validate_success(
        api.create_callback(
            {
                "car_id": program.car_id(),
                "callback_type": "NUISANCE",
                "out_of_service": False,
            },
            program.manager_headers,
        ),
        201,
    )
    assert_instant_equals(
        callback["reported_at"], "2026-08-01T00:00:00Z", "reported_at"
    )
    assert callback["status"] == "REPORTED"

    clock = validate_success(api.set_clock("2026-09-01T00:00:00Z", admin_headers))
    assert_instant_equals(clock["current_utc"], "2026-09-01T00:00:00Z", "current_utc")


def test_car_read_is_reachable_after_registration(api, admin_headers):
    """PRD §3.1: "A new car begins at `IN_SERVICE` and `INSPECTION_DUE`, with
    `version` 1, `scheduled_downtime_minutes` 0, `open_part_order_count` 0, and
    `unplanned_outage_open_since`, `red_tag_issued_at`, `red_tag_lifted_at`,
    `current_certificate_number` and `certificate_expiry_date` all null.
    Registering a car does **not** mutate the contract row — the contract's
    `version` is untouched by car creation."

    Design: Corner/entities/create_car_client_supplied_state_input_ignored
    """
    program = setup_program(building_name="Corner Four B", building_address="4b Corner St")
    version_before = read_contract(program.contract_id, admin_headers)["version"]

    car = add_car(program, "CAR-C4B")
    stored = read_car(car["id"], admin_headers)
    assert_elevator_car(stored)
    assert stored["availability_state"] == "IN_SERVICE"
    assert stored["compliance_state"] == "INSPECTION_DUE"
    assert stored["contract_id"] == program.contract_id

    version_after = read_contract(program.contract_id, admin_headers)["version"]
    assert version_after == version_before, (
        "registering a car must not mutate the contract row"
    )
