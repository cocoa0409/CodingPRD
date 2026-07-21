"""Tables, reservation creation/validation, turnover discipline, and reschedule OCC."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_reservation_payload, create_table_payload,
)
from test_helpers import fixtures as fx


class TestTableSystemFields:
    def test_created_table_defaults_active_version_one(self, api):
        """PRD 3.2: "A table's status begins ACTIVE and cycles between ACTIVE and
        MAINTENANCE, or ends at the terminal RETIRED."
        PRD 2.4: "The version begins at 1 when the resource is created"

        Design: Corner/entities/table_system_fields_generated_version_one
        """
        resp = api.create_table(
            create_table_payload(table_number=20, table_type="BILLIARDS",
                                 seat_capacity=4, hourly_rate_cents=1400),
            TEST_USERS["manager"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1


class TestTableMaintenanceCycle:
    def test_maintenance_moves_table_to_maintenance(self, api):
        """PRD 3.2: "Putting a table into MAINTENANCE (ACTIVE -> MAINTENANCE) or
        retiring it (ACTIVE -> RETIRED, or MAINTENANCE -> RETIRED) is a Manager action"

        Design: Difficulty/non_linear_state_machine/pooltable_maintenance_activate_cycle
        """
        table = fx.make_table(table_type="SNOOKER", seat_capacity=2, hourly_rate_cents=1500)
        data = validate_success(api.table_maintenance(table["id"], TEST_USERS["manager"]))
        assert data["status"] == "MAINTENANCE"

    def test_activate_returns_maintenance_table_to_active(self, api):
        """PRD 3.2: "Returning a table from MAINTENANCE to ACTIVE (activation) has no
        side effects."

        Design: Difficulty/non_linear_state_machine/pooltable_maintenance_activate_cycle
        """
        table = fx.make_table(table_type="SNOOKER", seat_capacity=2, hourly_rate_cents=1500)
        validate_success(api.table_maintenance(table["id"], TEST_USERS["manager"]))
        data = validate_success(api.table_activate(table["id"], TEST_USERS["manager"]))
        assert data["status"] == "ACTIVE"


class TestReservationCreation:
    def test_create_reservation_returns_pending_immediately(self, api):
        """PRD 3.2: "The reservation is created in PENDING."
        PRD 4: "Newly created resources are returned with HTTP 201"

        Design: Corner/consistency_model/immediate_reservation_status_in_create_response
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(seat_capacity=4)
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-13T10:00:00Z",
                                       end_at="2026-07-13T11:00:00Z", party_size=2),
            TEST_USERS["frontdesk"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"

    def test_reservation_start_after_end_returns_invalid_window(self, api):
        """PRD 3.2: "the window must be well-formed — start_at strictly before end_at,
        both aligned to whole minutes, and the whole window falling within the member's
        plan reservation_horizon_days ahead of the current logical time (ERR_INVALID_WINDOW)".

        Design: Corner/validations/reservation_start_after_end_returns_invalid_window
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(seat_capacity=4)
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-09T12:00:00Z",
                                       end_at="2026-07-09T11:00:00Z", party_size=2),
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)

    def test_reservation_party_over_capacity_rejected(self, api):
        """PRD 3.2: "the party_size must not exceed the table's seat_capacity
        (ERR_CAPACITY_EXCEEDED)".

        Design: Corner/validations/reservation_party_over_capacity_returns_capacity_exceeded
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(seat_capacity=4)
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-09T10:00:00Z",
                                       end_at="2026-07-09T11:00:00Z", party_size=6),
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)

    def test_reservation_nonexistent_table_returns_not_found(self, api):
        """PRD 2.8: "Existence — every id named in the path or body resolves to a live
        entity, validated left to right along the path, else ERR_NOT_FOUND (404)."

        Design: Corner/endpoints/reservation_nonexistent_table_returns_not_found
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=NON_EXISTENT_UUID,
                                       start_at="2026-07-09T10:00:00Z",
                                       end_at="2026-07-09T11:00:00Z", party_size=2),
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_confirm_cancelled_reservation_invalid_state(self, api):
        """PRD 2.8: "State — the target resource is in a state from which the requested
        transition is defined, else ERR_INVALID_STATE (409)."
        PRD 3.2: "A member or front-desk operator may cancel a reservation while it is
        PENDING or CONFIRMED, moving it to CANCELLED."

        Design: Corner/state_machines/confirm_from_cancelled_reservation_invalid_state
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(seat_capacity=4)
        res = fx.make_reservation(member["id"], table["id"],
                                  "2026-07-09T10:00:00Z", "2026-07-09T11:00:00Z")
        validate_success(api.cancel_reservation(res["id"], TEST_USERS["frontdesk"]))
        resp = api.confirm_reservation(res["id"], TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_reservation(res["id"], TEST_USERS["frontdesk"]))
        assert after["status"] == "CANCELLED"


class TestTurnoverBuffer:
    def test_five_minute_gap_conflicts(self, api):
        """PRD 3.2: "A new or rescheduled window [start_at, end_at) conflicts with any
        other reservation on the same table in PENDING, CONFIRMED, or CHECKED_IN if the
        two windows overlap once each is padded by a ten-minute turnover buffer — that
        is, there must be a clear gap of at least ten minutes between one reservation's
        end and the next reservation's start. A violation is rejected with
        ERR_TABLE_TIME_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/reservation_turnover_buffer_five_minute_gap_conflicts
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=1200)
        fx.make_confirmed_reservation(member["id"], table["id"],
                                      "2026-07-07T10:00:00Z", "2026-07-07T11:00:00Z")
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-07T11:05:00Z",
                                       end_at="2026-07-07T12:00:00Z", party_size=2),
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_TABLE_TIME_CONFLICT.value)

    def test_exact_ten_minute_gap_accepted(self, api):
        """PRD 3.2: "there must be a clear gap of at least ten minutes between one
        reservation's end and the next reservation's start. A violation is rejected with
        ERR_TABLE_TIME_CONFLICT."

        A booking starting exactly ten minutes after the prior one's end satisfies the
        buffer and is accepted.

        Design: Difficulty/resource_temporal_overlap/reservation_turnover_buffer_five_minute_gap_conflicts
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=1200)
        fx.make_confirmed_reservation(member["id"], table["id"],
                                      "2026-07-07T10:00:00Z", "2026-07-07T11:00:00Z")
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-07T11:10:00Z",
                                       end_at="2026-07-07T12:00:00Z", party_size=2),
            TEST_USERS["frontdesk"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"


class TestValidationPrecedence:
    def test_overlap_wins_over_capacity(self, api):
        """PRD 2.8: "When several checks could fail on one request, they are evaluated
        in a fixed order so the returned error is deterministic." — table time conflict
        (check 8) is evaluated before party capacity (check 10), so a booking that both
        overlaps within the turnover buffer and exceeds seat_capacity returns
        ERR_TABLE_TIME_CONFLICT.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_reservation
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        fx.make_confirmed_reservation(member["id"], table["id"],
                                      "2026-07-06T10:00:00Z", "2026-07-06T11:00:00Z")
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-06T10:30:00Z",
                                       end_at="2026-07-06T11:30:00Z", party_size=6),
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_TABLE_TIME_CONFLICT.value)

    def test_overlap_over_capacity_returns_409(self, api):
        """PRD 2.8: "When several checks could fail on one request, they are evaluated
        in a fixed order so the returned error is deterministic." The table time conflict
        check maps to HTTP 409, distinct from the 422 that party capacity would return.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_reservation
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        fx.make_confirmed_reservation(member["id"], table["id"],
                                      "2026-07-06T10:00:00Z", "2026-07-06T11:00:00Z")
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-06T10:30:00Z",
                                       end_at="2026-07-06T11:30:00Z", party_size=6),
            TEST_USERS["frontdesk"],
        )
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_TABLE_TIME_CONFLICT.value)


class TestRescheduleOCC:
    def test_reschedule_stale_version_conflict(self, api):
        """PRD 2.7: "A reschedule moves the reservation to a new window and supersedes
        its prior one; if another writer has advanced the reservation's version since the
        client read it, the reschedule is acting on a stale view and is rejected with
        ERR_STALE_VERSION (HTTP 412)."
        PRD 2.4: "The version begins at 1 when the resource is created and increases by
        exactly 1 on every mutation that changes the resource"

        Design: Corner/cross_cutting_complexity_layers/occ_reservation_reschedule_stale_version_conflict
        """
        plan = fx.make_plan()
        member = fx.make_member(plan["id"])
        table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=1200)
        res = fx.make_reservation(member["id"], table["id"],
                                  "2026-07-12T10:00:00Z", "2026-07-12T11:00:00Z")
        stale_version = res["version"]  # 1
        # Confirm mutates the reservation -> version advances to 2.
        fx.get_success_data(api.confirm_reservation(res["id"], TEST_USERS["frontdesk"]))
        resp = api.reschedule_reservation(
            res["id"],
            {"start_at": "2026-07-12T13:00:00Z", "end_at": "2026-07-12T14:00:00Z",
             "expected_reservation_version": stale_version},
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
