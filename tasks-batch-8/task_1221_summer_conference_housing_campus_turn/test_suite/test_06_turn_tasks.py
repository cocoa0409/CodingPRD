"""Turn tasks: rework cycle, invalid starts, escalation, admin cancel override."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_building_turn_active,
    get_room,
    get_success_data,
    setup_room_needs_turn,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HOUSEKEEPING = TEST_USERS["housekeeping_headers"]


class TestTurnTaskReworkCycle:
    def test_turn_task_rework_cycle_fail_then_pass(self, api):
        """PRD: "A FAIL outcome moves the task to FAILED and increments its
        rework_count, sending the crew back through the start step."
        PRD: "A PASS outcome moves the task to its terminal PASSED state and
        cascades the room from IN_TURN to READY, clearing the room's
        active_turn_task_id and decrementing scheduled_turn_count."

        Design: Difficulty/non_linear_state_machine/turn_task_rework_cycle
        """
        building, rooms = create_building_turn_active(name="Gibbs Hall", key_pool_size=10,
                                                      rooms=(("R1", 1),))
        group, assignment, task = setup_room_needs_turn(
            building, rooms, client_name="Alumni Weekend",
            arrival_date="2026-06-15", departure_date="2026-06-17")
        task_id = task["id"]

        get_success_data(api.start_turn_task(task_id, HOUSEKEEPING))
        get_success_data(api.submit_turn_task_for_inspection(task_id, HOUSEKEEPING))
        failed = validate_success(
            api.inspect_turn_task(task_id, "FAIL", HOUSEKEEPING,
                                  note="bathroom not cleaned"))
        assert failed["status"] == "FAILED"
        assert failed["rework_count"] == 1

        # Cyclic rework: FAILED -> IN_PROGRESS is a legal transition, not an error.
        restarted = validate_success(api.start_turn_task(task_id, HOUSEKEEPING))
        assert restarted["status"] == "IN_PROGRESS"
        get_success_data(api.submit_turn_task_for_inspection(task_id, HOUSEKEEPING))
        passed = validate_success(api.inspect_turn_task(task_id, "PASS", HOUSEKEEPING))
        assert passed["status"] == "PASSED"
        assert passed["rework_count"] == 1, "a PASS does not increment rework_count"

        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "READY"
        assert room["active_turn_task_id"] is None
        building_after = get_success_data(api.get_building(building["id"], ADMIN))
        assert building_after["scheduled_turn_count"] == 0, \
            "one task created at checkout, one closed at PASS"

    def test_turn_task_fail_keeps_room_in_turn(self, api):
        """PRD: "A `HousekeepingSupervisor` starts the work, moving the task from
        `SCHEDULED` — or from `FAILED` on the rework loop — to `IN_PROGRESS`,
        permitted only while the room is `NEEDS_TURN` or `IN_TURN`; a start from
        `NEEDS_TURN` flips the room to `IN_TURN`."

        Design: Difficulty/non_linear_state_machine/turn_task_rework_cycle
        """
        building, rooms = create_building_turn_active(name="Gibbs Hall", key_pool_size=10,
                                                      rooms=(("R1", 1),))
        group, assignment, task = setup_room_needs_turn(
            building, rooms, client_name="Alumni Weekend",
            arrival_date="2026-06-15", departure_date="2026-06-17")
        task_id = task["id"]
        get_success_data(api.start_turn_task(task_id, HOUSEKEEPING))
        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "IN_TURN", "starting the task from NEEDS_TURN flips the room"
        get_success_data(api.submit_turn_task_for_inspection(task_id, HOUSEKEEPING))
        get_success_data(api.inspect_turn_task(task_id, "FAIL", HOUSEKEEPING))
        room = get_room(rooms["R1"]["id"])
        assert room["status"] == "IN_TURN", "a FAIL sends the crew back; the room stays IN_TURN"
        assert room["active_turn_task_id"] == task_id


class TestTurnTaskInvalidStarts:
    def test_turn_task_start_from_in_progress_rejected(self, api):
        """PRD: "moving the task from `SCHEDULED` — or from `FAILED` on the rework
        loop — to `IN_PROGRESS`, permitted only while the room is `NEEDS_TURN` or
        `IN_TURN`" (no other from-state is permitted, so a start on an
        IN_PROGRESS task fails the state check of §2.6 with ERR_INVALID_STATE).

        Design: Corner/state_machines/turn_task_start_from_in_progress_rejected
        """
        building, rooms = create_building_turn_active(name="Kellogg Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, assignment, task = setup_room_needs_turn(building, rooms,
                                                        client_name="Start Twice")
        get_success_data(api.start_turn_task(task["id"], HOUSEKEEPING))
        resp = api.start_turn_task(task["id"], HOUSEKEEPING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTurnReworkEscalation:
    def test_error_turn_rework_escalation(self, api):
        """PRD: "once a task's `rework_count` has reached two, only a
        `ConferenceServicesAdmin` may inspect it, and a
        `HousekeepingSupervisor`'s inspection attempt is rejected with
        `ERR_TURN_REWORK_ESCALATION` (HTTP 403)."

        Design: Corner/errors/error_turn_rework_escalation
        """
        building, rooms = create_building_turn_active(name="Oscar Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, assignment, task = setup_room_needs_turn(building, rooms,
                                                        client_name="Escalation")
        task_id = task["id"]
        for _round in range(2):
            get_success_data(api.start_turn_task(task_id, HOUSEKEEPING))
            get_success_data(api.submit_turn_task_for_inspection(task_id, HOUSEKEEPING))
            failed = get_success_data(api.inspect_turn_task(task_id, "FAIL", HOUSEKEEPING))
        assert failed["rework_count"] == 2
        get_success_data(api.start_turn_task(task_id, HOUSEKEEPING))
        get_success_data(api.submit_turn_task_for_inspection(task_id, HOUSEKEEPING))

        resp = api.inspect_turn_task(task_id, "PASS", HOUSEKEEPING)
        validate_error(resp, ApiErrorId.ERR_TURN_REWORK_ESCALATION)
        still_open = get_success_data(api.get_turn_task(task_id, HOUSEKEEPING))
        assert still_open["status"] == "READY_FOR_INSPECTION"

        passed = validate_success(api.inspect_turn_task(task_id, "PASS", ADMIN))
        assert passed["status"] == "PASSED"
        assert get_room(rooms["R1"]["id"])["status"] == "READY"
