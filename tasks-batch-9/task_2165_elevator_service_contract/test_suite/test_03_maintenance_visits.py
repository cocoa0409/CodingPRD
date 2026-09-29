"""The monthly maintenance visit: task lists, the rework loop and month-close sweeps."""
from test_helpers import (
    ApiErrorId,
    assert_maintenance_visit,
    perform_visit,
    read_contract,
    read_visit,
    run_rework_loop,
    schedule_and_perform_visit,
    schedule_visit,
    setup_performed_visit_then_open_renegotiation,
    setup_program,
    task_items,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_task_codes_follow_the_oil_and_grease_required_set(api):
    """PRD §3.2: "A `FULL_MAINTENANCE` contract requires all seven of `BRAKE`,
    `CONTROLLER`, `DOOR_OPERATOR`, `FIRE_SERVICE_TEST`, `GOVERNOR`, `PIT_CLEAN` and
    `ROPES`. An `OIL_AND_GREASE` contract requires only the three of `LUBRICATION`,
    `PIT_CLEAN` and `VISUAL_INSPECTION`."
    PRD §3.2: "`completed_task_codes` is the set of `task_code` values whose
    `completed` flag is true, sorted in ascending order. `missing_task_codes` is the
    list of task codes required by the contract's `scope_type` that do not appear in
    `completed_task_codes`, also sorted ascending. Performing also stamps
    `performed_at` from the logical clock and `performed_by_user_id` from the acting
    `X-User-ID`."

    Design: Corner/entities/visit_computed_missing_task_codes_reflects_oil_and_grease_scope
    """
    program = setup_program(
        ["CAR-C8"],
        building_name="Corner Eight",
        building_address="8 Corner St",
        building_manager_user_id="bm-c8",
        contractor_user_id="sc-c8",
        scope_type="OIL_AND_GREASE",
        monthly_base_fee_cents=200_000,
        callback_response_minutes=90,
        entrapment_response_minutes=45,
    )
    visit = schedule_visit(program, program.car_id(), "2026-08", "2026-08-15")

    performed = validate_success(
        api.perform_visit(
            visit["id"],
            {
                "task_items": [
                    {"task_code": "LUBRICATION", "completed": True, "note": "greased"},
                    {"task_code": "PIT_CLEAN", "completed": False, "note": "flooded pit"},
                ]
            },
            program.contractor_headers,
        )
    )
    assert_maintenance_visit(performed)
    assert performed["status"] == "PERFORMED"
    assert performed["completed_task_codes"] == ["LUBRICATION"]
    assert performed["missing_task_codes"] == ["PIT_CLEAN", "VISUAL_INSPECTION"]
    assert performed["performed_by_user_id"] == "sc-c8"
    assert performed["rework_count"] == 0


def test_verifying_a_scheduled_visit_is_an_invalid_transition(api):
    """PRD §3.2: "Verification is the `BuildingManager`'s move and drives
    `PERFORMED → VERIFIED`, stamping `verified_at` and `verified_by_user_id`. It is
    gated four ways. The visit must currently be `PERFORMED`; the governing contract
    must be in `ACTIVE` or `SERVICE_ALERT`; `missing_task_codes` must be empty, and
    if it is not the request is refused with `ERR_TASK_LIST_INCOMPLETE`; and the
    verifying `X-User-ID` must differ from the recorded `performed_by_user_id`, or
    the request is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.7: "The target resource must currently sit in a state from which the
    requested transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION`
    (409)."

    Design: Corner/state_machines/verify_a_scheduled_visit_returns_invalid_state_transition
    """
    program = setup_program(
        ["CAR-S3"],
        building_name="SM Three",
        building_address="3 SM St",
        building_manager_user_id="bm-s3",
        contractor_user_id="sc-s3",
    )
    visit = schedule_visit(program, program.car_id(), "2026-08", "2026-08-15")

    validate_error(
        api.verify_visit(visit["id"], program.manager_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    stored = read_visit(visit["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["verified_at"] is None


def test_third_dispute_after_two_reworks_hits_the_rework_limit(api):
    """PRD §3.2: "That loop — performed, disputed, performed again — is bounded: a
    visit whose `rework_count` has already reached **two** may not be disputed a
    third time, and the attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED`."
    PRD §3.2: "When the work does not measure up, the same `BuildingManager` disputes
    it instead, driving `PERFORMED → DISPUTED` with a `dispute_reason` recorded on
    the visit and `rework_count` incremented by 1."

    Design: Corner/state_machines/visit_rework_loop_runs_twice_then_third_dispute_hits_rework_limit
    """
    program = setup_program(
        ["CAR-S6"],
        building_name="SM Six",
        building_address="6 SM St",
        building_manager_user_id="bm-s6",
        contractor_user_id="sc-s6",
    )
    visit = schedule_and_perform_visit(program, program.car_id(), "2026-08", "2026-08-15")
    run_rework_loop(program, visit["id"], rounds=2)

    validate_error(
        api.dispute_visit(
            visit["id"], {"dispute_reason": "third complaint"}, program.manager_headers
        ),
        ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED.value,
    )

    stored = read_visit(visit["id"])
    assert stored["rework_count"] == 2, f"expected rework_count 2, got {stored['rework_count']}"
    assert stored["status"] == "PERFORMED"
    assert stored["dispute_reason"] == "rework 2"


def test_month_close_sweeps_a_disputed_visit_to_rejected(api):
    """PRD §3.2: "When the logical clock reaches or passes the first instant of the
    month *after* a visit's `period_month`, the epoch sweep turns any visit still
    `SCHEDULED` into `MISSED` and any visit still `DISPUTED` into `REJECTED`."
    PRD §2.5: "The response reports the resulting `current_utc` together with five
    counters describing what the move triggered: `missed_visits_marked`,
    `rejected_visits_marked`, `certificates_expired`, `windows_completed` and
    `cars_under_modernization`."

    Design: Corner/state_machines/clock_sweep_marks_disputed_visit_rejected_when_month_closes
    """
    program = setup_program(
        ["CAR-S7"],
        building_name="SM Seven",
        building_address="7 SM St",
        building_manager_user_id="bm-s7",
        contractor_user_id="sc-s7",
    )
    visit = schedule_and_perform_visit(program, program.car_id(), "2026-08", "2026-08-15")
    validate_success(
        api.dispute_visit(
            visit["id"], {"dispute_reason": "ropes not measured"}, program.manager_headers
        )
    )

    sweep = validate_success(api.set_clock("2026-09-01T00:00:00Z", program.admin_headers))
    assert sweep["rejected_visits_marked"] == 1, (
        f"expected 1 rejected visit, got {sweep['rejected_visits_marked']}"
    )
    assert sweep["missed_visits_marked"] == 0, (
        "a disputed visit is rejected, never missed"
    )

    stored = read_visit(visit["id"])
    assert stored["status"] == "REJECTED"
    assert stored["rework_count"] == 1


def test_second_visit_for_the_same_car_month_is_a_duplicate(api):
    """PRD §3.2: "Only one live visit may exist per car and month: if another visit
    already covers the same `car_id` and `period_month` in any status other than
    `REJECTED`, the request is refused with `ERR_VISIT_MONTH_DUPLICATE`."

    Design: Corner/validations/second_visit_for_the_same_car_and_month_is_rejected_as_duplicate
    """
    program = setup_program(
        ["CAR-V5"],
        building_name="Val Five",
        building_address="5 Val St",
        building_manager_user_id="bm-v5",
        contractor_user_id="sc-v5",
    )
    first = schedule_visit(program, program.car_id(), "2026-08", "2026-08-10")

    validate_error(
        api.create_visit(
            {
                "car_id": program.car_id(),
                "period_month": "2026-08",
                "scheduled_date": "2026-08-25",
            },
            program.contractor_headers,
        ),
        ApiErrorId.ERR_VISIT_MONTH_DUPLICATE.value,
    )

    rows, meta = validate_paginated(
        api.list_visits(program.admin_headers, {"car_id": program.car_id()})
    )
    assert meta["total_count"] == 1, f"expected exactly 1 visit, got {meta['total_count']}"
    assert len(rows) == 1
    assert read_visit(first["id"])["scheduled_date"] == "2026-08-10"


def test_verify_with_an_incomplete_task_list_is_refused(api):
    """PRD §3.2: "Verification is the `BuildingManager`'s move and drives
    `PERFORMED → VERIFIED`, stamping `verified_at` and `verified_by_user_id`. It is
    gated four ways. The visit must currently be `PERFORMED`; the governing contract
    must be in `ACTIVE` or `SERVICE_ALERT`; `missing_task_codes` must be empty, and
    if it is not the request is refused with `ERR_TASK_LIST_INCOMPLETE`; and the
    verifying `X-User-ID` must differ from the recorded `performed_by_user_id`, or
    the request is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "A `FULL_MAINTENANCE` contract requires all seven of `BRAKE`,
    `CONTROLLER`, `DOOR_OPERATOR`, `FIRE_SERVICE_TEST`, `GOVERNOR`, `PIT_CLEAN` and
    `ROPES`."

    Design: Corner/validations/verifying_a_visit_with_missing_task_codes_returns_task_list_incomplete
    """
    program = setup_program(
        ["CAR-V7"],
        building_name="Val Seven",
        building_address="7 Val St",
        building_manager_user_id="bm-v7",
        contractor_user_id="sc-v7",
    )
    visit = schedule_visit(program, program.car_id(), "2026-08", "2026-08-10")
    performed = perform_visit(
        program,
        visit["id"],
        task_items(
            [
                "BRAKE",
                "CONTROLLER",
                "DOOR_OPERATOR",
                "GOVERNOR",
                "PIT_CLEAN",
                "ROPES",
            ]
        ),
    )
    assert performed["missing_task_codes"] == ["FIRE_SERVICE_TEST"]

    validate_error(
        api.verify_visit(visit["id"], program.manager_headers),
        ApiErrorId.ERR_TASK_LIST_INCOMPLETE.value,
    )

    stored = read_visit(visit["id"])
    assert stored["status"] == "PERFORMED"
    assert stored["verified_by_user_id"] is None


def test_scheduling_a_visit_on_a_decommissioned_car_is_refused(api):
    """PRD §3.2: "A car that is `DECOMMISSIONED` cannot take a new visit
    (`ERR_CAR_DECOMMISSIONED`), and neither can one that is `RED_TAGGED`
    (`ERR_CAR_RED_TAGGED`)."
    PRD §2.7: "The target car's `availability_state` must not be `DECOMMISSIONED`,
    otherwise `ERR_CAR_DECOMMISSIONED` (409)."

    Design: Corner/validations/scheduling_a_visit_on_a_decommissioned_car_is_rejected
    """
    program = setup_program(
        ["CAR-VC"],
        building_name="Val Twelve",
        building_address="12 Val St",
        building_manager_user_id="bm-vc",
        contractor_user_id="sc-vc",
    )
    car_id = program.car_id()
    decommissioned = validate_success(
        api.decommission_car(car_id, program.admin_headers)
    )
    assert decommissioned["availability_state"] == "DECOMMISSIONED"

    validate_error(
        api.create_visit(
            {
                "car_id": car_id,
                "period_month": "2026-08",
                "scheduled_date": "2026-08-10",
            },
            program.admin_headers,
        ),
        ApiErrorId.ERR_CAR_DECOMMISSIONED.value,
    )

    rows, meta = validate_paginated(
        api.list_visits(program.admin_headers, {"car_id": car_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_verify_is_blocked_while_the_contract_is_under_renegotiation(api):
    """PRD §2.7: "Operational writes require the governing contract to be in either
    `ACTIVE` or `SERVICE_ALERT`; opening a renegotiation requires the contract to be
    exactly `ACTIVE`; countering, accepting or closing a round requires it to be
    exactly `UNDER_RENEGOTIATION`. A violation is `ERR_CONTRACT_NOT_ACTIVE` (409).
    This rule guards fourteen operations: scheduling a visit, performing a visit,
    verifying a visit, reporting a callback, scheduling an inspection, planning a
    project, approving a project, reserving a downtime window, creating a part
    order, assessing a penalty, opening a renegotiation, countering a round,
    accepting a round, and closing a round."
    PRD §3.9: "When it succeeds, a round is created in `status` `OPEN` with
    `opened_by_user_id` stamped from the acting `X-User-ID` and
    `trigger_performance_score` set to the score just evaluated; the contract's
    `renegotiation_round_count` is incremented by 1 and the round's `round_number`
    is that resulting count, so the first round of a contract's life is round 1; the
    contract moves `ACTIVE → UNDER_RENEGOTIATION`; and the contract's `version` is
    incremented by 1."

    Design: Difficulty/cross_entity_state_dependency/visit_verify_blocked_while_parent_contract_is_under_renegotiation
    """
    world = setup_performed_visit_then_open_renegotiation(
        building_name="Omicron House", building_address="15 Omi St"
    )
    program = world["program"]
    visit = world["visit"]

    assert read_contract(program.contract_id)["status"] == "UNDER_RENEGOTIATION"

    validate_error(
        api.verify_visit(visit["id"], program.manager_headers),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
    )

    stored = read_visit(visit["id"])
    assert stored["status"] == "PERFORMED"
    assert stored["missing_task_codes"] == []
    assert stored["verified_at"] is None


def test_renegotiation_trigger_score_is_stored_on_the_opened_round(api):
    """PRD §3.9: "The raw score is then the uptime component weighted at 0.50, plus
    the response component weighted at 0.25, plus the visit component weighted at
    0.25, less the penalty drag."
    PRD §3.9: "The **response component** is 100.00 when no callback on those cars
    reached `CLEARED` with a `reported_at` inside the scoring month; otherwise it is
    100 multiplied by the number of those cleared callbacks whose `sla_breached` is
    false, divided by the total number of them, rounded half up to 2 decimal places."
    PRD §3.9: "The **visit component** is 100.00 when no maintenance visit on those
    cars carries that scoring month as its `period_month` in one of the statuses
    `VERIFIED`, `DISPUTED`, `REJECTED`, `MISSED` or `PERFORMED`; otherwise it is 100
    multiplied by the number of those visits whose `status` is `VERIFIED`, divided
    by the total number of them, rounded half up to 2 decimal places."

    Design: Difficulty/cross_entity_state_dependency/visit_verify_blocked_while_parent_contract_is_under_renegotiation
    """
    world = setup_performed_visit_then_open_renegotiation(
        building_name="Omicron House B", building_address="15b Omi St"
    )
    program = world["program"]
    opened = world["round"]

    assert opened["trigger_performance_score"] == 50.00, (
        "0.50*100.00 uptime + 0.25*0.00 response + 0.25*0.00 visit - 0.00 drag"
    )
    contract = read_contract(program.contract_id)
    assert contract["performance_score"] == 50.00
    assert contract["status"] == "UNDER_RENEGOTIATION"
    assert read_visit(world["visit"]["id"])["status"] == "PERFORMED"
