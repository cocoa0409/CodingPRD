"""The four-hop red-tag cascade, the decommissioning cascade and their rejection order."""
from test_helpers import (
    ApiErrorId,
    add_window,
    assert_state_inspection,
    read_callback,
    read_car,
    read_contract,
    read_inspection,
    read_window,
    red_tag_car,
    report_callback,
    schedule_inspection,
    setup_program,
    validate_error,
    validate_success,
)


def test_failed_inspection_red_tags_the_car_and_pulls_it_from_service(api):
    """PRD §3.4: "On a `result` of `FAIL` no certificate is minted,
    `certificate_state` stays at `NONE`, and the four-hop red-tag cascade begins.
    Hop one is the inspection itself reaching `COMPLETED` with the failing result
    recorded. Hop two drives the car's compliance dimension to `RED_TAGGED` from
    whichever of `INSPECTION_DUE`, `CERTIFIED` or `CERTIFICATE_EXPIRED` it occupied,
    recording `red_tag_issued_at` at the current logical clock; a car already
    `RED_TAGGED` is not re-tagged."
    PRD §3.4: "Hop three forces the availability dimension
    `IN_SERVICE → OUT_OF_SERVICE`, recording `unplanned_outage_open_since`. Hop four
    increments the contract's `cars_out_of_service_count`, and if that count reaches
    two the contract escalates `ACTIVE → SERVICE_ALERT`."

    Design: Difficulty/transitive_cascade/inspection_fail_red_tags_car_then_pulls_it_from_service_then_alerts_contract
    """
    program = setup_program(
        ["CAR-I1", "CAR-I2"],
        building_name="Iota Center",
        building_address="9 Iota Sq",
        building_manager_user_id="bm-i",
        contractor_user_id="sc-i",
    )
    car_one, car_two = program.car_id(0), program.car_id(1)
    report_callback(program, car_two, callback_type="MALFUNCTION", out_of_service=True)
    assert read_contract(program.contract_id)["cars_out_of_service_count"] == 1

    inspection = schedule_inspection(program, car_one, "PERIODIC", "2026-08-01")
    completed = validate_success(
        api.record_inspection_result(
            inspection["id"],
            {"result": "FAIL", "deficiency_codes": ["GOV-01", "ROPE-04"]},
            program.inspector_headers,
        )
    )
    assert_state_inspection(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["result"] == "FAIL"

    car = read_car(car_one)
    assert car["compliance_state"] == "RED_TAGGED"
    assert car["availability_state"] == "OUT_OF_SERVICE"
    assert car["red_tag_issued_at"] is not None

    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 2
    assert contract["status"] == "SERVICE_ALERT"
    assert read_car(car_two)["availability_state"] == "OUT_OF_SERVICE"


def test_failed_inspection_mints_no_certificate(api):
    """PRD §3.4: "On a `result` of `FAIL` no certificate is minted,
    `certificate_state` stays at `NONE`, and the four-hop red-tag cascade begins."
    PRD §3.4: "Hop one is the inspection itself reaching `COMPLETED` with the failing
    result recorded."

    Design: Difficulty/transitive_cascade/inspection_fail_red_tags_car_then_pulls_it_from_service_then_alerts_contract
    """
    program = setup_program(
        ["CAR-I1", "CAR-I2"],
        building_name="Iota Center",
        building_address="9 Iota Sq",
        building_manager_user_id="bm-i",
        contractor_user_id="sc-i",
    )
    inspection = red_tag_car(program, program.car_id(0), scheduled_date="2026-08-01")

    stored = read_inspection(inspection["id"])
    assert stored["certificate_state"] == "NONE"
    assert stored["certificate_number"] is None
    assert stored["certificate_issued_date"] is None
    assert stored["certificate_expiry_date"] is None

    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 1
    assert contract["status"] == "ACTIVE", (
        "one red-tagged car is not enough to escalate the contract"
    )


def test_the_cascade_is_visible_in_the_triggering_response_and_the_next_read(api):
    """PRD §2.10: "Cascades in this system are transitive and each hop is observable.
    When an operation changes a second or third resource, that resource's `version`
    advances and its `updated_at` refreshes, in exactly the same way as if it had
    been written directly."
    PRD §3.4: "Hop two drives the car's compliance dimension to `RED_TAGGED` from
    whichever of `INSPECTION_DUE`, `CERTIFIED` or `CERTIFICATE_EXPIRED` it occupied,
    recording `red_tag_issued_at` at the current logical clock; a car already
    `RED_TAGGED` is not re-tagged."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_triggering_response_immediately
    """
    program = setup_program(
        ["CAR-CM1"],
        building_name="Cm One",
        building_address="1 Cm St",
        building_manager_user_id="bm-m1",
        contractor_user_id="sc-m1",
    )
    car_id = program.car_id()
    version_before = program.car()["version"]
    inspection = schedule_inspection(program, car_id, "PERIODIC", "2026-08-01")

    recorded = validate_success(
        api.record_inspection_result(
            inspection["id"],
            {"result": "FAIL", "deficiency_codes": ["SAFETY-01"]},
            program.inspector_headers,
        )
    )
    assert recorded["result"] == "FAIL"
    assert recorded["status"] == "COMPLETED"

    car = read_car(car_id)
    assert car["compliance_state"] == "RED_TAGGED"
    assert car["availability_state"] == "OUT_OF_SERVICE"
    assert car["version"] > version_before, (
        f"the cascade must advance the car's version past {version_before}"
    )

    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 1
    assert contract["status"] == "ACTIVE"


def test_decommissioning_a_car_cancels_all_of_its_open_children(api):
    """PRD §3.1: "A car may be decommissioned from `IN_SERVICE` or from
    `OUT_OF_SERVICE`, and the same cascade runs either way: every part order on the
    car still in `ORDERED` or `SUBSTITUTED` becomes `CANCELLED`; every downtime
    window on the car still `SCHEDULED` becomes `CANCELLED`, after which the car's
    `scheduled_downtime_minutes` is recomputed; every state inspection on the car
    still `SCHEDULED` becomes `CANCELLED` and mints no certificate; every callback
    on the car still in `REPORTED`, `ESCALATED` or `ON_SITE` becomes `CANCELLED` and
    thereafter contributes no outage interval to any uptime calculation; the car's
    `availability_state` becomes `DECOMMISSIONED`; and the car's `version` is
    incremented by 1."
    PRD §3.1: "When the decommissioned car was in `OUT_OF_SERVICE`, the contract's
    `cars_out_of_service_count` is decremented by 1 as part of the same cascade,
    which may in turn de-escalate the contract from `SERVICE_ALERT` back to
    `ACTIVE`."

    Design: Corner/state_machines/decommissioning_a_car_cascades_cancellations_to_all_children
    """
    program = setup_program(
        ["CAR-S9"],
        building_name="SM Nine",
        building_address="9 SM St",
        building_manager_user_id="bm-s9",
        contractor_user_id="sc-s9",
    )
    car_id = program.car_id()
    window = add_window(
        program, car_id, "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", "REPAIR"
    )
    inspection = schedule_inspection(program, car_id, "PERIODIC", "2026-09-05")
    callback = report_callback(
        program, car_id, callback_type="MALFUNCTION", out_of_service=True
    )

    decommissioned = validate_success(
        api.decommission_car(car_id, program.admin_headers)
    )
    assert decommissioned["availability_state"] == "DECOMMISSIONED"

    assert read_window(window["id"])["status"] == "CANCELLED"
    stored_inspection = read_inspection(inspection["id"])
    assert stored_inspection["status"] == "CANCELLED"
    assert stored_inspection["certificate_state"] == "NONE"
    assert read_callback(callback["id"])["status"] == "CANCELLED"
    assert read_car(car_id)["scheduled_downtime_minutes"] == 0

    contract = read_contract(program.contract_id)
    assert contract["cars_out_of_service_count"] == 0
    assert contract["status"] == "ACTIVE"


def test_red_tag_check_precedes_the_downtime_interval_conflict_check(api):
    """PRD §2.7: "**Car red-tagged.** The target car's `compliance_state` must not be
    `RED_TAGGED`, otherwise `ERR_CAR_RED_TAGGED` (409). This rule guards exactly two
    operations — reserving a downtime window and scheduling a maintenance visit —
    because a red-tagged car may take on no new scheduled work until a reinspection
    lifts the tag."
    PRD §2.7: "**Downtime interval conflict.** The first of the two downtime overlap
    rules, described in §3.5, rejecting with `ERR_DOWNTIME_WINDOW_CONFLICT` (409)."
    PRD §2.7: "Checks are applied strictly in the sequence below and **the first
    check that fails determines the response**; no later check is consulted. A
    request that would trip several rules always reports the earliest one."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_downtime_window_on_red_tagged_car
    """
    program = setup_program(
        ["CAR-M1"],
        building_name="Mu Building",
        building_address="12 Mu Pl",
        building_manager_user_id="bm-m",
        contractor_user_id="sc-m",
    )
    car_id = program.car_id()
    add_window(program, car_id, "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", "REPAIR")
    red_tag_car(program, car_id, scheduled_date="2026-08-01")

    error = validate_error(
        api.create_downtime_window(
            {
                "car_id": car_id,
                "window_type": "REPAIR",
                "window_start": "2026-09-10T10:00:00Z",
                "window_end": "2026-09-10T14:00:00Z",
            },
            program.admin_headers,
        ),
        ApiErrorId.ERR_CAR_RED_TAGGED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_DOWNTIME_WINDOW_CONFLICT.value, (
        "the red-tag check is earlier in the rejection order than the interval conflict"
    )


def test_the_rejected_overlapping_window_leaves_the_car_and_contract_untouched(api):
    """PRD §2.7: "**Car red-tagged.** The target car's `compliance_state` must not be
    `RED_TAGGED`, otherwise `ERR_CAR_RED_TAGGED` (409). This rule guards exactly two
    operations — reserving a downtime window and scheduling a maintenance visit —
    because a red-tagged car may take on no new scheduled work until a reinspection
    lifts the tag."
    PRD §3.5: "The car's `scheduled_downtime_minutes` is, at all times, the sum of
    `duration_minutes` over that car's windows whose `status` is `SCHEDULED` or
    `COMPLETED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_downtime_window_on_red_tagged_car
    """
    program = setup_program(
        ["CAR-M1"],
        building_name="Mu Building",
        building_address="12 Mu Pl",
        building_manager_user_id="bm-m",
        contractor_user_id="sc-m",
    )
    car_id = program.car_id()
    add_window(program, car_id, "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", "REPAIR")
    red_tag_car(program, car_id, scheduled_date="2026-08-01")

    validate_error(
        api.create_downtime_window(
            {
                "car_id": car_id,
                "window_type": "REPAIR",
                "window_start": "2026-09-10T10:00:00Z",
                "window_end": "2026-09-10T14:00:00Z",
            },
            program.admin_headers,
        ),
        ApiErrorId.ERR_CAR_RED_TAGGED.value,
    )

    car = read_car(car_id)
    assert car["compliance_state"] == "RED_TAGGED"
    assert car["scheduled_downtime_minutes"] == 240, (
        "the rejected reservation must not add any minutes"
    )
    assert read_contract(program.contract_id)["status"] == "ACTIVE"
