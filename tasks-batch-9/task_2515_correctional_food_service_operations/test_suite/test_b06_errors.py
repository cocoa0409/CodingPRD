"""Every declared error identifier, reached by the request that provokes it.

These cases pin the authentication ladder, the range and existence checks, the HACCP
sequencing bars, the tool-issue eligibility ladder and the grievance remedy gates.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


def test_a_role_nobody_declared_is_an_authentication_fault_not_a_permission_one(
    api: ApiClient,
) -> None:
    """An unrecognised role name is refused at 401 before authorisation runs; a declared
    role that merely lacks the operation is the 403 instead.

    The PRD states the ladder: "3. `X-User-Role` names one of the eight declared roles,
    else `ERR_UNKNOWN_ROLE`. 4. The named role appears in the called endpoint's
    authorized-role list, else `ERR_UNAUTHORIZED`."

    Design: Corner/errors/corner_unknown_role_header_rejected
    """
    fixtures.set_clock(api)
    payload = factories.service_contract_payload(contract_code="CFS-2515-E01")

    validate_error(
        api.create_service_contract(payload, users.UNKNOWN_ROLE),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
        401,
    )
    validate_error(
        api.create_service_contract(payload, users.OFFICER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    _, meta = validate_paginated(api.list_service_contracts(users.AUDITOR))
    assert meta["total_count"] == 0


def test_the_identity_header_is_missed_before_the_role_header_is(
    api: ApiClient,
) -> None:
    """Each header omission has its own code, and a request that omits both reports the
    earlier of the two.

    The PRD states: "1. `X-User-ID` present and non-empty, else `ERR_MISSING_USER_HEADER`.
    2. `X-User-Role` present and non-empty, else `ERR_MISSING_ROLE_HEADER`", and that "a
    request that fails two checks always reports the earlier one".

    Design: Corner/errors/corner_missing_user_header_rejected
    """
    fixtures.set_clock(api)
    payload = factories.service_contract_payload(contract_code="CFS-2515-E02")
    neither = {"Content-Type": "application/json"}

    validate_error(
        api.create_service_contract(payload, users.MISSING_USER_ID),
        ApiErrorId.ERR_MISSING_USER_HEADER.value,
        401,
    )
    validate_error(
        api.create_service_contract(payload, users.MISSING_ROLE),
        ApiErrorId.ERR_MISSING_ROLE_HEADER.value,
        401,
    )
    validate_error(
        api.create_service_contract(payload, neither),
        ApiErrorId.ERR_MISSING_USER_HEADER.value,
        401,
    )
    validate_error(
        api.create_service_contract(payload, users.EMPTY_USER_ID),
        ApiErrorId.ERR_MISSING_USER_HEADER.value,
        401,
    )
    validate_error(
        api.create_service_contract(payload, users.EMPTY_ROLE),
        ApiErrorId.ERR_MISSING_ROLE_HEADER.value,
        401,
    )


def test_the_audit_ceiling_is_on_the_whole_identity_not_the_counted_figure(
    api: ApiClient,
) -> None:
    """With one knife signed out, a shadow-board count of twelve against twelve authorised
    already overshoots, while eleven sits exactly at the ceiling and is accepted.

    The PRD states: "`counted_on_board` plus `sharps_issued_count` plus
    `sharps_unaccounted_count` must not exceed `sharps_authorized_count`, because a kitchen
    cannot hold more sharps than it is authorized to hold; a count that exceeds the
    authorization is rejected with `ERR_SHARPS_COUNT_OVER_AUTHORIZED`."

    Design: Corner/errors/corner_sharps_audit_over_authorized_rejected
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E03")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-E03", sharps_authorized_count=12
    )
    worker = fixtures.enrolled_worker(
        api, facility["id"], booking_number="BK-E03", sharps_eligible=True
    )["worker"]
    fixtures.issued_tool(api, facility["id"], worker["id"], tool_serial="KNF-E03")

    before = fixtures.read_facility(api, facility["id"])
    assert before["sharps_on_board_count"] == 11
    assert before["sharps_issued_count"] == 1
    assert before["last_sharps_audit_at"] is None

    validate_error(
        api.sharps_audit(
            facility["id"], factories.sharps_audit_payload(12), users.OFFICER
        ),
        ApiErrorId.ERR_SHARPS_COUNT_OVER_AUTHORIZED.value,
        422,
    )
    untouched = fixtures.read_facility(api, facility["id"])
    assert untouched["sharps_on_board_count"] == 11
    assert untouched["last_sharps_audit_at"] is None
    assertions.assert_no_version_change(before, untouched)

    accepted = validate_success(
        api.sharps_audit(
            facility["id"], factories.sharps_audit_payload(11), users.OFFICER
        )
    )
    assert accepted["sharps_on_board_count"] == 11
    assert accepted["sharps_audit_shortfall"] == 0
    assert accepted["kitchen_posture"] == "OPEN"
    assertions.assert_instant(accepted["last_sharps_audit_at"], "2026-08-01T00:00:00Z")


def test_both_window_faults_report_the_one_window_code(
    api: ApiClient,
) -> None:
    """An empty window and a window that has already closed share a single error id, and
    neither rejected order consumes the inmate's concurrency token.

    The PRD states: "`effective_from` must fall strictly before `effective_to`, and
    `effective_to` must fall strictly after the logical clock's current instant — an order
    that has already expired cannot be raised. Either failure reports `ERR_INVALID_WINDOW`."

    Design: Corner/errors/corner_diet_order_invalid_window_rejected
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E04")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-E04", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(api, facility["id"], booking_number="BK-E04")
    assert inmate["version"] == 1

    validate_error(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                inmate["id"],
                inmate["version"],
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        ApiErrorId.ERR_INVALID_WINDOW.value,
        422,
    )
    validate_error(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                inmate["id"],
                inmate["version"],
                effective_from="2026-07-01T00:00:00Z",
                effective_to="2026-08-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        ApiErrorId.ERR_INVALID_WINDOW.value,
        422,
    )

    assert validate_success(api.get_inmate(inmate["id"], users.DIETITIAN))["version"] == 1
    _, meta = validate_paginated(
        api.list_diet_orders(users.DIETITIAN, params={"inmate_id": inmate["id"]})
    )
    assert meta["total_count"] == 0


def test_the_day_index_is_bounded_by_its_own_cycle_at_both_ends(
    api: ApiClient,
) -> None:
    """On a one-day cycle, day 2 overshoots and day 0 undershoots the same rule, and
    neither rejected item is counted against the cycle.

    The PRD states: "`cycle_day` must be at least 1 and at most the parent cycle's
    `cycle_length_days`; a day index outside that span is `ERR_CYCLE_DAY_OUT_OF_RANGE`."

    Design: Corner/errors/corner_cycle_day_out_of_range_rejected
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E05")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-E05", sharps_authorized_count=12
    )
    cycle = validate_success(
        api.create_menu_cycle(
            factories.menu_cycle_payload(
                facility["id"], cycle_code="CYC-E05", cycle_length_days=1
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert cycle["cycle_length_days"] == 1
    assert cycle["item_count"] == 0

    validate_error(
        api.add_menu_cycle_item(
            cycle["id"],
            factories.breakfast_item_payload(cycle_day=2),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_CYCLE_DAY_OUT_OF_RANGE.value,
        422,
    )
    validate_error(
        api.add_menu_cycle_item(
            cycle["id"],
            factories.breakfast_item_payload(cycle_day=0),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_CYCLE_DAY_OUT_OF_RANGE.value,
        422,
    )

    accepted = validate_success(
        api.add_menu_cycle_item(
            cycle["id"],
            factories.breakfast_item_payload(cycle_day=1),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert accepted["cycle_day"] == 1
    reread = validate_success(api.get_menu_cycle(cycle["id"], users.FOOD_SUPERVISOR))
    assert reread["item_count"] == 1


def test_the_forecast_key_ignores_the_variant_but_honours_the_slot(
    api: ApiClient,
) -> None:
    """A second LUNCH forecast for the same day collides even under a different variant,
    while the same day's DINNER forecast is a different key entirely.

    The PRD states: "At most one forecast may exist per `(facility_id, service_date,
    meal_slot)` in `DRAFT` or `LOCKED`; a second attempt reports
    `ERR_DUPLICATE_FORECAST`."

    Design: Corner/errors/corner_duplicate_forecast_rejected
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E06")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-E06", sharps_authorized_count=12
    )
    count = fixtures.create_population_count(api, facility["id"])
    first = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility["id"],
                count["id"],
                service_date="2026-08-01",
                meal_slot="LUNCH",
                forecast_variant="COUNT_DRIVEN",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    validate_error(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility["id"],
                count["id"],
                service_date="2026-08-01",
                meal_slot="LUNCH",
                forecast_variant="ROSTER_DRIVEN",
            ),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_DUPLICATE_FORECAST.value,
        409,
    )

    dinner = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility["id"],
                count["id"],
                service_date="2026-08-01",
                meal_slot="DINNER",
                forecast_variant="COUNT_DRIVEN",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert dinner["meal_slot"] == "DINNER"
    assert dinner["status"] == "DRAFT"

    _, meta = validate_paginated(
        api.list_meal_forecasts(
            users.FOOD_SUPERVISOR, params={"facility_id": facility["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_the_cold_chain_is_checked_pairwise_and_not_merely_from_the_cook(
    api: ApiClient,
) -> None:
    """A chill reading with no cook on file is out of sequence; once the cook is on file a
    transport arrival is still out of sequence because its own predecessor is missing.

    The PRD states: "`CHILL_INTERMEDIATE` requires an existing `COOK_END`, `CHILL_FINAL`
    requires an existing `CHILL_INTERMEDIATE`, `TRANSPORT_DEPART` requires an existing
    `CHILL_FINAL`, `TRANSPORT_ARRIVE` requires an existing `TRANSPORT_DEPART` and
    `REHEAT_SERVE` requires an existing `TRANSPORT_ARRIVE`. A reading whose predecessor is
    absent is rejected with `ERR_LOG_POINT_OUT_OF_SEQUENCE`."

    Design: Corner/errors/corner_temperature_log_out_of_sequence_rejected
    """
    ctx = fixtures.planned_batch(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-E07"},
            facility_overrides={
                "facility_code": "FAC-E07",
                "sharps_authorized_count": 12,
            },
        ),
        scheduled_cook_start_at="2026-08-01T04:00:00Z",
    )
    batch = ctx["batch"]
    assert batch["production_stage"] == "PLANNED"
    assert batch["qa_status"] == "QA_PENDING"

    validate_error(
        api.post_temperature_log(
            batch["id"],
            factories.temperature_log_payload("CHILL_INTERMEDIATE", 70.0),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_LOG_POINT_OUT_OF_SEQUENCE.value,
        409,
    )
    _, empty_meta = validate_paginated(
        api.list_temperature_logs(batch["id"], users.FOOD_SUPERVISOR)
    )
    assert empty_meta["total_count"] == 0

    cook = validate_success(
        api.post_temperature_log(
            batch["id"],
            factories.temperature_log_payload("COOK_END", 170.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert cook["in_range"] is True
    assert cook["minutes_since_cook_end"] is None

    validate_error(
        api.post_temperature_log(
            batch["id"],
            factories.temperature_log_payload("TRANSPORT_ARRIVE", 39.0),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_LOG_POINT_OUT_OF_SEQUENCE.value,
        409,
    )

    data, meta = validate_paginated(
        api.list_temperature_logs(batch["id"], users.FOOD_SUPERVISOR)
    )
    assert meta["total_count"] == 1
    assert [row["log_point"] for row in data] == ["COOK_END"]
    assert fixtures.read_batch(api, batch["id"])["qa_status"] == "QA_PENDING"


def test_the_condemning_reading_is_kept_and_the_one_after_it_is_refused(
    api: ApiClient,
) -> None:
    """A warm arrival is recorded, condemns the batch and discards it; the next reading
    against that same batch is then refused outright.

    The PRD states: "A `TRANSPORT_ARRIVE` or `REHEAT_SERVE` reading outside its band drives
    `qa_status` to `QA_CONDEMNED` with `qa_reason` `TRANSPORT_REHEAT_GATE_FAILED` ... A
    batch whose `qa_status` is `QA_CONDEMNED` cascades to `production_stage` `DISCARDED`",
    and: "A reading against a batch already in `DISCARDED` is rejected with
    `ERR_BATCH_DISCARDED`."

    Design: Corner/errors/corner_reading_against_discarded_batch_rejected
    """
    ctx = fixtures.planned_batch(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-E08"},
            facility_overrides={
                "facility_code": "FAC-E08",
                "sharps_authorized_count": 12,
            },
        ),
        service_site="SATELLITE_A",
        scheduled_cook_start_at="2026-08-01T04:00:00Z",
    )
    batch_id = ctx["batch"]["id"]

    for point, reading in (
        ("COOK_END", 170.0),
        ("CHILL_INTERMEDIATE", 70.0),
        ("CHILL_FINAL", 38.0),
    ):
        logged = validate_success(
            api.post_temperature_log(
                batch_id,
                factories.temperature_log_payload(point, reading),
                users.FOOD_SUPERVISOR,
            ),
            201,
        )
        assert logged["in_range"] is True

    passed = validate_success(
        api.qa_decision(
            batch_id,
            factories.qa_decision_payload("QA_PASSED", "HACCP record complete."),
            users.FOOD_SUPERVISOR,
        )
    )
    assert passed["qa_status"] == "QA_PASSED"
    # The QA axis and the stage axis are independent.
    assert passed["production_stage"] == "PLANNED"

    depart = validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("TRANSPORT_DEPART", 39.0),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert depart["in_range"] is True

    # 45.0 F is above the 41.0 F cold-chain ceiling.
    arrive = validate_success(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload(
                "TRANSPORT_ARRIVE", 45.0, site="SATELLITE_A"
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert arrive["in_range"] is False

    condemned = fixtures.read_batch(api, batch_id)
    assert condemned["qa_status"] == "QA_CONDEMNED"
    assert condemned["qa_reason"] == "TRANSPORT_REHEAT_GATE_FAILED"
    assert condemned["production_stage"] == "DISCARDED"

    validate_error(
        api.post_temperature_log(
            batch_id,
            factories.temperature_log_payload("REHEAT_SERVE", 170.0, site="SATELLITE_A"),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_BATCH_DISCARDED.value,
        409,
    )

    data, meta = validate_paginated(
        api.list_temperature_logs(batch_id, users.FOOD_SUPERVISOR)
    )
    assert meta["total_count"] == 5
    assert "REHEAT_SERVE" not in [row["log_point"] for row in data]


def test_an_undeclared_edge_answers_before_the_missing_cook_log_does(
    api: ApiClient,
) -> None:
    """Two stage skips are refused as illegal edges, while the legal one-step advance gets
    far enough to fail on its temperature prerequisite instead.

    The PRD states the ladder: "18. The requested transition is a declared edge of that
    machine, else `ERR_ILLEGAL_TRANSITION` (HTTP 409)", and separately: "`PLANNED` to
    `COOKED` requires an in-range `COOK_END` reading on file, else `ERR_COOK_LOG_MISSING`."

    Design: Corner/errors/corner_stage_skip_is_illegal_transition
    """
    ctx = fixtures.planned_batch(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-E09"},
            facility_overrides={
                "facility_code": "FAC-E09",
                "sharps_authorized_count": 12,
            },
        ),
        scheduled_cook_start_at="2026-08-01T04:00:00Z",
    )
    batch = ctx["batch"]
    assert batch["version"] == 1

    validate_error(
        api.advance_stage(
            batch["id"],
            factories.advance_stage_payload("CHILLED"),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_ILLEGAL_TRANSITION.value,
        409,
    )
    validate_error(
        api.advance_stage(
            batch["id"],
            factories.advance_stage_payload("SERVED"),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_ILLEGAL_TRANSITION.value,
        409,
    )
    validate_error(
        api.advance_stage(
            batch["id"],
            factories.advance_stage_payload("COOKED", produced_trays=10),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_COOK_LOG_MISSING.value,
        409,
    )

    untouched = fixtures.read_batch(api, batch["id"])
    assert untouched["production_stage"] == "PLANNED"
    assertions.assert_no_version_change(batch, untouched)
    assert untouched["version"] == 1


def test_every_collection_owns_its_own_not_found_identifier(
    api: ApiClient,
) -> None:
    """One well-formed but unknown id probed against twelve single-resource reads yields
    twelve distinct not-found identifiers rather than a shared generic one.

    The PRD states: "Referenced entities exist, else the entity-specific not-found error
    (HTTP 404)", and enumerates them: "`ERR_MENU_CYCLE_NOT_FOUND`,
    `ERR_MENU_CYCLE_ITEM_NOT_FOUND`, `ERR_DIET_ORDER_NOT_FOUND`,
    `ERR_POPULATION_COUNT_NOT_FOUND`, `ERR_MEAL_FORECAST_NOT_FOUND`,
    `ERR_PRODUCTION_BATCH_NOT_FOUND`, `ERR_INMATE_WORKER_NOT_FOUND`,
    `ERR_TOOL_ISSUANCE_NOT_FOUND`, `ERR_CONTRABAND_INCIDENT_NOT_FOUND`,
    `ERR_MEAL_SERVICE_RECORD_NOT_FOUND`, `ERR_MENU_SUBSTITUTION_NOT_FOUND` and
    `ERR_GRIEVANCE_NOT_FOUND`."

    Design: Corner/errors/corner_unknown_ids_return_entity_specific_not_found
    """
    fixtures.set_clock(api)

    probes = (
        (api.get_menu_cycle, ApiErrorId.ERR_MENU_CYCLE_NOT_FOUND),
        (api.get_menu_cycle_item, ApiErrorId.ERR_MENU_CYCLE_ITEM_NOT_FOUND),
        (api.get_diet_order, ApiErrorId.ERR_DIET_ORDER_NOT_FOUND),
        (api.get_population_count, ApiErrorId.ERR_POPULATION_COUNT_NOT_FOUND),
        (api.get_meal_forecast, ApiErrorId.ERR_MEAL_FORECAST_NOT_FOUND),
        (api.get_production_batch, ApiErrorId.ERR_PRODUCTION_BATCH_NOT_FOUND),
        (api.get_inmate_worker, ApiErrorId.ERR_INMATE_WORKER_NOT_FOUND),
        (api.get_tool_issuance, ApiErrorId.ERR_TOOL_ISSUANCE_NOT_FOUND),
        (api.get_contraband_incident, ApiErrorId.ERR_CONTRABAND_INCIDENT_NOT_FOUND),
        (api.get_meal_service_record, ApiErrorId.ERR_MEAL_SERVICE_RECORD_NOT_FOUND),
        (api.get_menu_substitution, ApiErrorId.ERR_MENU_SUBSTITUTION_NOT_FOUND),
        (api.get_grievance, ApiErrorId.ERR_GRIEVANCE_NOT_FOUND),
    )
    seen = []
    for read, error_id in probes:
        validate_error(
            read(NON_EXISTENT_UUID, users.AUDITOR), error_id.value, 404
        )
        seen.append(error_id.value)

    # Twelve collections, twelve distinct identifiers.
    assert len(set(seen)) == 12


def test_the_pagination_window_is_inclusive_at_a_hundred_and_closed_below_one(
    api: ApiClient,
) -> None:
    """Both ends of the limit window and a negative offset share one range error, while a
    limit of exactly 100 is inside the window.

    The PRD states: "`limit` defaults to 50 and must fall between 1 and 100 inclusive;
    `offset` defaults to 0 and must be at least 0. A value outside those bounds is
    `ERR_VALUE_OUT_OF_RANGE`."

    Design: Corner/errors/corner_pagination_bounds_return_value_out_of_range
    """
    fixtures.set_clock(api)

    validate_error(
        api.list_service_contracts(users.AUDITOR, params={"limit": 101}),
        ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value,
        422,
    )
    validate_error(
        api.list_service_contracts(users.AUDITOR, params={"limit": 0}),
        ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value,
        422,
    )
    validate_error(
        api.list_service_contracts(users.AUDITOR, params={"offset": -1}),
        ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value,
        422,
    )

    data, meta = validate_paginated(
        api.list_service_contracts(users.AUDITOR, params={"limit": 100, "offset": 0})
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 100
    assert meta["offset"] == 0


def test_each_way_a_worker_can_fail_the_sharps_gate_has_its_own_code(
    api: ApiClient,
) -> None:
    """Four workers each fail exactly one rung of the tool-issue ladder, and once a
    non-sharp tool goes missing the fifth request reports the discrepancy rather than the
    posture block.

    The PRD states: "22. The worker's `clearance_status` is `CLEARED`, else
    `ERR_WORKER_NOT_CLEARED`. 23. `medical_clearance_expires_at` is strictly after the
    logical clock, else `ERR_MEDICAL_CLEARANCE_EXPIRED`. 24. For a sharp tool class the
    worker's `sharps_eligible` is true, else `ERR_WORKER_NOT_SHARPS_ELIGIBLE`. 25. The
    worker has no `OPEN` contraband incident against them, else `ERR_OPEN_CONTRABAND_HOLD`."
    It also carves out the posture check: "on the tool-issuance endpoint the posture gate
    considers only the audit and contraband clauses, and an unaccounted tool is instead
    reported one priority later as `ERR_SHARPS_DISCREPANCY_OPEN`."

    Design: Corner/errors/corner_tool_issue_eligibility_ladder_rejects_each_way
    """
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-E12")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-E12", sharps_authorized_count=12
    )
    facility_id = facility["id"]

    worker_a = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-E12-A", sharps_eligible=factories.OMIT
    )["worker"]
    assert worker_a["sharps_eligible"] is False
    assert worker_a["clearance_status"] == "CLEARED"

    worker_b = fixtures.enrolled_worker(
        api,
        facility_id,
        booking_number="BK-E12-B",
        sharps_eligible=True,
        medical_clearance_expires_at="2026-07-01T00:00:00Z",
    )["worker"]
    assert worker_b["clearance_status"] == "CLEARED"

    worker_c = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-E12-C", sharps_eligible=True
    )["worker"]
    incident = validate_success(
        api.create_contraband_incident(
            factories.contraband_incident_payload(
                facility_id,
                item_class="FOOD_DIVERSION",
                severity="MINOR",
                narrative="Extra trays diverted to a housing unit.",
                inmate_worker_id=worker_c["id"],
            ),
            users.OFFICER,
        ),
        201,
    )
    assert incident["status"] == "OPEN"

    pair_d = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-E12-D", sharps_eligible=True
    )
    worker_d = pair_d["worker"]
    validate_success(
        api.assign_inmate_worker(
            worker_d["id"], factories.assign_payload("SANITATION"), users.FOOD_SUPERVISOR
        )
    )
    validate_success(
        api.record_inmate_movement(
            pair_d["inmate"]["id"],
            factories.movement_payload("HOUSING_CHANGE", housing_unit="SEGREGATION"),
            users.OFFICER,
        )
    )
    suspended = fixtures.read_worker(api, worker_d["id"])
    assert suspended["clearance_status"] == "SUSPENDED"
    assert suspended["assignment_status"] == "UNASSIGNED"

    worker_e = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-E12-E", sharps_eligible=True
    )["worker"]

    ladder = (
        (worker_a, "MS-E12-A", 1, ApiErrorId.ERR_WORKER_NOT_SHARPS_ELIGIBLE),
        (worker_b, "MS-E12-B", 2, ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED),
        (worker_c, "MS-E12-C", 3, ApiErrorId.ERR_OPEN_CONTRABAND_HOLD),
        (worker_d, "MS-E12-D", 4, ApiErrorId.ERR_WORKER_NOT_CLEARED),
    )
    for worker, serial, slot, error_id in ladder:
        validate_error(
            api.create_tool_issuance(
                factories.tool_issuance_payload(
                    facility_id,
                    worker["id"],
                    tool_class="MEAT_SAW",
                    tool_serial=serial,
                    shadow_board_slot=slot,
                ),
                users.FOOD_SUPERVISOR,
            ),
            error_id.value,
            409,
        )

    # Clear worker C's hold first. The declaration below auto-raises its own OPEN
    # incident, and two open incidents would take the fourth waterfall clause, so the
    # carve-out under test would legitimately report the posture block instead.
    validate_success(
        api.disposition_contraband_incident(
            incident["id"], factories.disposition_payload("CLEARED"), users.OFFICER_2
        )
    )
    assert fixtures.read_facility(api, facility_id)["kitchen_posture"] == "OPEN"

    issued = validate_success(
        api.create_tool_issuance(
            factories.tool_issuance_payload(
                facility_id,
                worker_e["id"],
                tool_class="NON_SHARP",
                tool_serial="NS-E12-E",
                shadow_board_slot=5,
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert issued["status"] == "ISSUED"

    declared = validate_success(
        api.declare_tool_unaccounted(
            issued["id"],
            factories.declare_unaccounted_payload(
                "Plastic scoop missing at shift-end count."
            ),
            users.OFFICER_2,
        )
    )
    assert declared["status"] == "UNACCOUNTED"

    summary = validate_success(api.get_sharps_summary(facility_id, users.OFFICER))
    # A NON_SHARP loss takes the fifth waterfall clause and moves no sharps counter.
    assert summary["kitchen_posture"] == "RESTRICTED"
    assert summary["sharps_unaccounted_count"] == 0

    validate_error(
        api.create_tool_issuance(
            factories.tool_issuance_payload(
                facility_id,
                worker_e["id"],
                tool_class="SCISSORS",
                tool_serial="SC-E12-E",
                shadow_board_slot=6,
            ),
            users.FOOD_SUPERVISOR,
        ),
        ApiErrorId.ERR_SHARPS_DISCREPANCY_OPEN.value,
        409,
    )


def test_three_inadmissible_remedies_are_refused_before_the_fourth_is_taken(
    api: ApiClient,
) -> None:
    """A grievance that is ready to answer refuses a null remedy, a refeed against an open
    record and a reinstatement of an active order, then accepts the menu correction.

    The PRD states: "If `diet_remedy_required` is true the remedy may not be `NO_ACTION`,
    else `ERR_REMEDY_NOT_PERMITTED`. A `MEAL_REFEED` remedy requires that
    `meal_service_record_id` is present and names a record in `CLOSED`, else
    `ERR_REFEED_TARGET_INVALID`. A `DIET_REINSTATEMENT` remedy requires that
    `diet_order_id` is present and names an order in `SUSPENDED`, else
    `ERR_REINSTATEMENT_TARGET_INVALID`."

    Design: Corner/errors/corner_grievance_remedy_admissibility_rejects_each_variant
    """
    ctx = fixtures.open_service_record(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-E13"},
            facility_overrides={
                "facility_code": "FAC-E13",
                "sharps_authorized_count": 12,
            },
        ),
    )
    facility_id = ctx["facility"]["id"]
    record = ctx["record"]
    assert record["status"] == "OPEN"

    inmate = fixtures.create_inmate(api, facility_id, booking_number="BK-E13")
    order = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(inmate["id"], inmate["version"]),
            users.DIETITIAN,
        ),
        201,
    )
    verified = validate_success(api.verify_diet_order(order["id"], users.CHAPLAIN))
    assert verified["status"] == "ACTIVE"

    grievance = validate_success(
        api.create_grievance(
            factories.grievance_payload(
                inmate["id"],
                facility_id,
                category="DIET_NOT_HONORED",
                narrative="Kosher tray not delivered at lunch.",
                diet_order_id=order["id"],
                meal_service_record_id=record["id"],
            ),
            users.GRIEVANCE_COORD,
        ),
        201,
    )
    # DIET_NOT_HONORED carries the five-day SLA.
    assertions.assert_instant(grievance["response_due_at"], "2026-08-06T00:00:00Z")

    validate_success(
        api.route_grievance(
            grievance["id"], factories.route_payload("DIET_REVIEW"), users.GRIEVANCE_COORD
        )
    )
    ready = validate_success(
        api.complete_grievance_branch(
            grievance["id"],
            factories.complete_branch_payload("DIET_REVIEW", "KITCHEN_AT_FAULT"),
            users.DIETITIAN,
        )
    )
    assert ready["status"] == "READY_FOR_RESPONSE"
    assert ready["diet_remedy_required"] is True

    validate_error(
        api.respond_grievance(
            grievance["id"],
            factories.respond_payload("NO_ACTION", response_note="No fault found."),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_REMEDY_NOT_PERMITTED.value,
        409,
    )
    validate_error(
        api.respond_grievance(
            grievance["id"],
            factories.respond_payload("MEAL_REFEED", refeed_tray_count=2),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_REFEED_TARGET_INVALID.value,
        409,
    )
    validate_error(
        api.respond_grievance(
            grievance["id"],
            factories.respond_payload("DIET_REINSTATEMENT"),
            users.GRIEVANCE_COORD,
        ),
        ApiErrorId.ERR_REINSTATEMENT_TARGET_INVALID.value,
        409,
    )

    still_ready = fixtures.read_grievance(api, grievance["id"])
    assert still_ready["status"] == "READY_FOR_RESPONSE"
    assert still_ready["remedy"] is None
    assert fixtures.read_service_record(api, record["id"])["missed_meal_count"] == 0

    responded = validate_success(
        api.respond_grievance(
            grievance["id"],
            factories.respond_payload(
                "MENU_CORRECTION",
                response_note="Tray line re-briefed on religious tickets.",
            ),
            users.GRIEVANCE_COORD,
        )
    )
    assert responded["status"] == "RESPONDED"
    assert responded["remedy"] == "MENU_CORRECTION"
    assert responded["sla_breached"] is False
