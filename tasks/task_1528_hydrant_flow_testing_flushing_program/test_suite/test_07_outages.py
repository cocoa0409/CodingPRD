"""Out-of-service tagging: the three-hop cascade, the service cycle,
counter conservation, close gates, acknowledgement handshake, escalation."""
from datetime import datetime, timedelta

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_outage,
    assert_program_counters,
    api_client,
    TEST_USERS,
    create_program,
    create_zone,
    create_hydrant,
    create_scheduled_flow_test,
    create_draft_work_order,
    tag_hydrant_out,
    acknowledge_outage,
    close_outage,
    setup_hydrant_out_of_service_acknowledged,
    get_hydrant,
    get_program,
    set_clock,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
LIAISON = TEST_USERS["liaison_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestServiceCycle:
    def test_hydrant_service_cycle_in_out_returns_in_service(self, api):
        """PRD §3.6: "A successful close sets the outage's `status` to
        `CLOSED`, records `closed_at`, moves the hydrant back to `IN_SERVICE`
        with `active_outage_id` cleared and its version incremented, and
        decrements the program's `hydrants_out_of_service_count` by one."

        Design: Difficulty/non_linear_state_machine/hydrant_service_cycle_in_out
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = setup_hydrant_out_of_service_acknowledged(program, zone, hydrant)

        close_outage(outage["id"])
        after = get_hydrant(hydrant["id"])
        assert after["status"] == "IN_SERVICE", (
            f"hydrant must return to IN_SERVICE after the cycle, got {after['status']}"
        )
        assert after.get("active_outage_id") is None, (
            "active_outage_id must be cleared by the close"
        )

    def test_hydrant_service_cycle_closes_outage_and_reenters(self, api):
        """PRD §3.6: "A successful close sets the outage's `status` to
        `CLOSED`, records `closed_at`, moves the hydrant back to `IN_SERVICE`
        with `active_outage_id` cleared and its version incremented, and
        decrements the program's `hydrants_out_of_service_count` by one."
        PRD §3.6: "When a hydrant cannot serve — a valve failure, a leak,
        physical damage, or any other cause — a `FieldOperator` tags it out of
        service by creating a `HydrantOutage` with the `hydrant_id`, a `reason`
        of `VALVE_FAILURE`, `LEAK`, `DAMAGE`, or `OTHER`, and an optional
        `expected_return_date`."

        Design: Difficulty/non_linear_state_machine/hydrant_service_cycle_in_out
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = setup_hydrant_out_of_service_acknowledged(program, zone, hydrant)
        close_outage(outage["id"])

        closed = validate_success(api.get_outage(outage["id"], OP1))
        assert closed["status"] == "CLOSED"
        assert closed.get("closed_at"), "closed_at must be recorded on close"

        # The cycle is re-enterable: a fresh outage rewires active_outage_id.
        second = tag_hydrant_out(hydrant["id"], reason="DAMAGE")
        assert second["status"] == "ACTIVE"
        assert second["id"] != outage["id"]
        after = get_hydrant(hydrant["id"])
        assert after["status"] == "OUT_OF_SERVICE"
        assert after["active_outage_id"] == second["id"], (
            "each pass of the cycle rewires active_outage_id to the new outage"
        )


class TestOutageTagCascade:
    def test_outage_tag_cascade_depth3_outage_and_hydrant(self, api):
        """PRD §3.6: "The new outage starts in `ACTIVE` status with
        `notification_status` `PENDING`, `notified_at` set to the current
        logical clock, `ack_deadline` computed as `notified_at` plus 2 hours,
        and `escalated` false. The hydrant's `status` moves to
        `OUT_OF_SERVICE`, its `active_outage_id` is set to the new outage's id,
        and its `version` increments."

        Design: Difficulty/transitive_cascade/outage_tag_cascade_depth3
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        create_scheduled_flow_test(hydrant["id"], "2026-08-04T10:00:00Z",
                                   "2026-08-04T11:00:00Z")

        outage = tag_hydrant_out(hydrant["id"], reason="VALVE_FAILURE")
        assert_outage(outage)
        assert outage["status"] == "ACTIVE"
        assert outage["notification_status"] == "PENDING"
        # Clock never set: default 2026-08-01T00:00:00Z (PRD §2.8).
        assert _parse(outage["notified_at"]) == _parse("2026-08-01T00:00:00Z")
        assert _parse(outage["ack_deadline"]) == _parse(outage["notified_at"]) + timedelta(hours=2)
        assert outage["escalated"] is False

        after = get_hydrant(hydrant["id"])
        assert after["status"] == "OUT_OF_SERVICE"
        assert after["active_outage_id"] == outage["id"]

    def test_outage_tag_cascade_depth3_program_and_flow_tests(self, api):
        """PRD §3.6: "The owning program's `hydrants_out_of_service_count`
        increments by one and its `unacknowledged_notification_count`
        increments by one. And every `SCHEDULED` flow test on this hydrant is
        cancelled to `CANCELLED` with `cancel_reason` of `OUTAGE_AUTO_CANCEL`
        — tests already in `RESULTS_SUBMITTED` or beyond are untouched."

        Design: Difficulty/transitive_cascade/outage_tag_cascade_depth3
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"], "2026-08-04T10:00:00Z",
                                        "2026-08-04T11:00:00Z")

        tag_hydrant_out(hydrant["id"], reason="VALVE_FAILURE")

        program_after = get_program(program["id"])
        assert_program_counters(program_after, out_of_service=1, unacknowledged=1)

        ft_after = validate_success(api.get_flow_test(ft["id"], OP1))
        assert ft_after["status"] == "CANCELLED", (
            f"SCHEDULED test must be auto-cancelled, got {ft_after['status']}"
        )
        assert ft_after["cancel_reason"] == "OUTAGE_AUTO_CANCEL"


class TestCounterConservation:
    def test_outage_create_close_conserves_counts_after_create(self, api):
        """PRD §2.7: "`hydrants_out_of_service_count` tracks how many of the
        program's hydrants are currently `OUT_OF_SERVICE`; it is incremented
        when an outage is created and decremented when the outage closes.
        `unacknowledged_notification_count` tracks how many `ACTIVE` outages on
        the program's hydrants still have a fire-department notification in
        `PENDING` status; it is incremented when an outage is created and
        decremented when the fire department acknowledges."

        Design: Difficulty/compensating_invariant/outage_create_close_conserves_counts
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        tag_hydrant_out(hydrant["id"], reason="LEAK")

        program_after = get_program(program["id"])
        assert_program_counters(program_after, out_of_service=1, unacknowledged=1)

    def test_outage_create_close_conserves_counts_after_pair(self, api):
        """PRD §2.7: "Both counters start at zero when the program is created,
        and the second counter is a hard gate on ISO publication (§3.7)."
        PRD §3.6: "A successful close sets the outage's `status` to `CLOSED`,
        records `closed_at`, moves the hydrant back to `IN_SERVICE` with
        `active_outage_id` cleared and its version incremented, and decrements
        the program's `hydrants_out_of_service_count` by one."

        Design: Difficulty/compensating_invariant/outage_create_close_conserves_counts
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = tag_hydrant_out(hydrant["id"], reason="LEAK")
        acknowledge_outage(outage["id"])
        close_outage(outage["id"])

        program_after = get_program(program["id"])
        assert_program_counters(program_after, out_of_service=0, unacknowledged=0)

        after = get_hydrant(hydrant["id"])
        assert after["status"] == "IN_SERVICE"
        assert after.get("active_outage_id") is None


class TestCloseGateOpenWorkOrders:
    def test_outage_close_blocked_by_open_work_order(self, api):
        """PRD §3.6: "no `RepairWorkOrder` may exist for the hydrant in
        `DRAFT`, `SUBMITTED`, or `APPROVED` status (else
        `ERR_OPEN_WORK_ORDERS_EXIST`). This last gate is the operational rule
        that a hydrant cannot come back online while repair work is still in
        flight."

        Design: Difficulty/cross_entity_state_dependency/outage_close_blocked_by_open_work_order
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = setup_hydrant_out_of_service_acknowledged(program, zone, hydrant)
        create_draft_work_order(hydrant["id"], description="Fix leak")

        resp = api.close_outage(outage["id"], OP1)
        validate_error(resp, ApiErrorId.ERR_OPEN_WORK_ORDERS_EXIST, 409)

        after = validate_success(api.get_outage(outage["id"], OP1))
        assert after["status"] == "ACTIVE", "blocked close must leave the outage ACTIVE"

    def test_outage_close_unblocked_after_work_order_cancel(self, api):
        """PRD §3.6: "no `RepairWorkOrder` may exist for the hydrant in
        `DRAFT`, `SUBMITTED`, or `APPROVED` status (else
        `ERR_OPEN_WORK_ORDERS_EXIST`)."
        PRD §3.7: "Cancellation is available from `DRAFT`, `SUBMITTED`, or
        `APPROVED` (else `ERR_WORK_ORDER_NOT_CANCELLABLE`)."

        Design: Difficulty/cross_entity_state_dependency/outage_close_blocked_by_open_work_order
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = setup_hydrant_out_of_service_acknowledged(program, zone, hydrant)
        wo = create_draft_work_order(hydrant["id"], description="Fix leak")

        validate_error(api.close_outage(outage["id"], OP1),
                       ApiErrorId.ERR_OPEN_WORK_ORDERS_EXIST, 409)

        cancelled = validate_success(api.cancel_work_order(wo["id"], OP1))
        assert cancelled["status"] == "CANCELLED"

        closed = close_outage(outage["id"])
        assert closed["status"] == "CLOSED"
        assert get_hydrant(hydrant["id"])["status"] == "IN_SERVICE"


class TestCloseTwice:
    def test_outage_close_twice_rejected(self, api):
        """PRD §3.6: "A `FieldOperator` closes the hydrant's `ACTIVE` outage;
        the outage must be `ACTIVE` (else `ERR_OUTAGE_NOT_ACTIVE`), its
        `notification_status` must be `ACKNOWLEDGED` (else
        `ERR_NOTIFICATION_NOT_ACKNOWLEDGED`), and no `RepairWorkOrder` may
        exist for the hydrant in `DRAFT`, `SUBMITTED`, or `APPROVED` status
        (else `ERR_OPEN_WORK_ORDERS_EXIST`)."
        PRD §2.7: "`hydrants_out_of_service_count` tracks how many of the
        program's hydrants are currently `OUT_OF_SERVICE`; it is incremented
        when an outage is created and decremented when the outage closes."

        Design: Corner/state_machines/outage_close_twice_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = setup_hydrant_out_of_service_acknowledged(program, zone, hydrant)
        close_outage(outage["id"])

        resp = api.close_outage(outage["id"], OP1)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_NOT_ACTIVE, 409)

        program_after = get_program(program["id"])
        assert program_after["hydrants_out_of_service_count"] == 0, (
            "a rejected second close must not decrement the counter twice"
        )


class TestEscalation:
    def test_outage_escalation_on_sweep(self, api):
        """PRD §3.9: "Third, the sweep escalates overdue notifications: every
        `ACTIVE` outage on a hydrant of the swept program whose
        `notification_status` is still `PENDING` and whose `ack_deadline` has
        passed (the current logical clock is after the deadline) has its
        `escalated` flag set to true. Escalation is a marker for operational
        follow-up; it does not change `notification_status`."
        PRD §3.9: "The sweep response reports `missed_flow_tests`,
        `escalated_outages`, and `tier_recomputed_hydrants` — the three counts
        an operations lead reviews after each run."

        Design: Corner/state_machines/outage_escalation_on_sweep
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = tag_hydrant_out(hydrant["id"], reason="DAMAGE")
        # Tagged at default clock 2026-08-01T00:00:00Z -> ack_deadline +2h.
        set_clock("2026-08-01T03:00:00Z")

        sweep = validate_success(api.sweep_program(program["id"], ADMIN))
        assert sweep["escalated_outages"] == 1, (
            f"sweep must report exactly 1 escalated outage, got {sweep['escalated_outages']}"
        )

        after = validate_success(api.get_outage(outage["id"], ADMIN))
        assert after["escalated"] is True
        assert after["notification_status"] == "PENDING", (
            "escalation must not change notification_status"
        )
        assert get_program(program["id"])["unacknowledged_notification_count"] == 1


class TestAcknowledgementHandshake:
    def test_notification_double_acknowledge_rejected(self, api):
        """PRD §3.6: "A `FireDeptLiaison` acknowledges the notification; the
        outage's `notification_status` must be `PENDING`, else the
        acknowledgement is rejected with
        `ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED`."
        PRD §3.6: "A successful acknowledgement moves `notification_status` to
        `ACKNOWLEDGED`, records `acknowledged_at` from the logical clock and
        `acknowledged_by_user_id` from `X-User-ID`, and decrements the
        program's `unacknowledged_notification_count` by one."

        Design: Corner/validations/notification_double_acknowledge_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = tag_hydrant_out(hydrant["id"], reason="LEAK")
        acknowledge_outage(outage["id"])

        resp = api.acknowledge_outage_notification(outage["id"], LIAISON)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED, 409)

        program_after = get_program(program["id"])
        assert program_after["unacknowledged_notification_count"] == 0, (
            "a rejected second acknowledgement must not decrement the counter twice"
        )

    def test_ack_notification_reconciles_program_counter(self, api):
        """PRD §2.7: "`unacknowledged_notification_count` tracks how many
        `ACTIVE` outages on the program's hydrants still have a fire-department
        notification in `PENDING` status; it is incremented when an outage is
        created and decremented when the fire department acknowledges."
        PRD §3.6: "Acknowledgement does not change the outage's `status`,
        which remains `ACTIVE`."

        Design: Corner/cross_cutting_layers/ack_notification_reconciles_program_counter
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        outage = tag_hydrant_out(hydrant["id"], reason="LEAK")

        acked = acknowledge_outage(outage["id"])
        assert acked["notification_status"] == "ACKNOWLEDGED"
        assert acked["status"] == "ACTIVE"

        program_after = get_program(program["id"])
        assert_program_counters(program_after, out_of_service=1, unacknowledged=0)


class TestImmediateConsistency:
    def test_immediate_consistency_on_create_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.6: "The new outage starts in `ACTIVE` status with
        `notification_status` `PENDING`, `notified_at` set to the current
        logical clock, `ack_deadline` computed as `notified_at` plus 2 hours,
        and `escalated` false."

        Design: Corner/consistency_model/immediate_consistency_on_create_response
        """
        program, zone, hydrant = setup_program_zone_hydrant()

        resp = api.create_outage({"hydrant_id": hydrant["id"], "reason": "LEAK"}, OP1)
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "ACTIVE"
        assert created["notification_status"] == "PENDING"

        fetched = validate_success(api.get_outage(created["id"], OP1))
        assert fetched["status"] == created["status"], (
            "the immediately following read must agree with the create response"
        )
        assert fetched["notification_status"] == created["notification_status"]
