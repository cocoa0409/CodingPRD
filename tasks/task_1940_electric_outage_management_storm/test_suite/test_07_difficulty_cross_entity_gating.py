"""Difficulty tests — cross_entity_state_dependency rule.

Covers the WorkOrder -> SwitchingOrder gate and the Outage -> Outage nested
child gate.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_accepted_assessment,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_outage_payload,
    create_switching_order_payload,
    create_trouble_signal_payload,
    create_work_order_payload,
    get_success_data,
    make_field_crew_lead_headers,
    make_system_operator_headers,
    run_work_order_to_completed,
    set_clock,
    setup_event_with_feeder,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]


class TestWorkOrderStartGatedBySwitchingOrderExecution:
    """Start requires the linked SwitchingOrder to be EXECUTED."""

    def test_start_rejected_while_switching_order_only_approved(self, api):
        """PRD §3.5: "When `requires_switching_order` is true, the switching
        order recorded on the work order must have reached `EXECUTED`,
        otherwise the start is rejected with `ERR_SWITCHING_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_switching_order_execution
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Nu", event_type="THUNDERSTORM")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=20, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=30,
            requires_switching=True,
        )
        cr_l = create_crew(crew_type="LINE")
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    ot["id"],
                    work_type="REPAIR",
                    required_crew_type="LINE",
                    requires_switching_order=True,
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(wo["id"], DISP))
        get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP))
        fcl = make_field_crew_lead_headers(cr_l["id"])
        get_success_data(api.arrive_work_order(wo["id"], fcl))
        so = get_success_data(
            api.create_switching_order(
                create_switching_order_payload(
                    wo["id"], switching_steps=["Open breaker 12", "Ground feeder"]
                ),
                make_system_operator_headers("op-1"),
            )
        )
        get_success_data(
            api.issue_switching_order(so["id"], make_system_operator_headers("op-1"))
        )
        get_success_data(
            api.approve_switching_order(so["id"], make_system_operator_headers("op-2"))
        )
        # APPROVED is not EXECUTED — the gate stays closed.
        resp = api.start_work_order(wo["id"], fcl)
        err = validate_error(resp, ApiErrorId.ERR_SWITCHING_NOT_EXECUTED)
        assert err["error_id"] == "ERR_SWITCHING_NOT_EXECUTED"
        wo_read = get_success_data(api.get_work_order(wo["id"], DISP))
        assert wo_read["execution_status"] == "DISPATCHED"

    def test_start_succeeds_once_switching_order_executed_and_bubbles_outage(self, api):
        """PRD §3.5: "When `requires_switching_order` is true, the switching
        order recorded on the work order must have reached `EXECUTED`" and
        "Starting moves the order to `IN_PROGRESS`, and when it is the first
        non-cancelled order on its outage to do so while the outage is
        `CONFIRMED` or `ASSESSED`, the outage bubbles to `WORKING` — a single
        version increment covers the whole start request."

        Design: Difficulty/cross_entity_state_dependency/work_order_start_gated_by_switching_order_execution
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Nu", event_type="THUNDERSTORM")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=20, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=30,
            requires_switching=True,
        )
        cr_l = create_crew(crew_type="LINE")
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    ot["id"],
                    work_type="REPAIR",
                    required_crew_type="LINE",
                    requires_switching_order=True,
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(wo["id"], DISP))
        get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP))
        fcl = make_field_crew_lead_headers(cr_l["id"])
        get_success_data(api.arrive_work_order(wo["id"], fcl))
        so = get_success_data(
            api.create_switching_order(
                create_switching_order_payload(
                    wo["id"], switching_steps=["Open breaker 12", "Ground feeder"]
                ),
                make_system_operator_headers("op-1"),
            )
        )
        get_success_data(
            api.issue_switching_order(so["id"], make_system_operator_headers("op-1"))
        )
        get_success_data(
            api.approve_switching_order(so["id"], make_system_operator_headers("op-2"))
        )
        get_success_data(
            api.execute_switching_order(so["id"], make_system_operator_headers("op-2"))
        )
        started = get_success_data(api.start_work_order(wo["id"], fcl))
        assert started["execution_status"] == "IN_PROGRESS"
        # Bubble-up: the outage moved ASSESSED -> WORKING on the first start.
        outage = get_success_data(api.get_outage(ot["id"], DISP))
        assert outage["outage_status"] == "WORKING"


class TestOutageVerifyGatedByNestedChildOutages:
    """A RESTORED parent cannot verify while any child outage is non-terminal."""

    def test_parent_verify_rejected_while_child_confirmed(self, api):
        """PRD §3.6: "Verifying a `RESTORED` outage checks three things: every
        child outage nested beneath it must be in `VERIFIED` or `CANCELLED`
        (`ERR_OUTAGE_CHILDREN_OPEN`); every non-cancelled work order on it must
        carry `VERIFY_PASSED` (`ERR_UNVERIFIED_WORK_REMAINS`); and at least one
        `CLUSTERED` trouble signal of type `METER_RESTORE_PING` pointing at
        this outage must have an `occurred_at` at or after
        `restoration_reported_at` (`ERR_RESTORE_PING_MISSING`)."

        Design: Difficulty/cross_entity_state_dependency/outage_verify_gated_by_nested_child_outages
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Xi", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        parent = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                parent["id"],
                create_confirm_outage_payload(
                    customers_affected=40, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        cr_l = create_crew(crew_type="LINE")
        create_accepted_assessment(
            parent["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=30,
            requires_switching=False,
        )
        # Run the parent's work order through to started (bubbles WORKING).
        wo_p = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    parent["id"], work_type="REPAIR", required_crew_type="LINE"
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(wo_p["id"], DISP))
        get_success_data(api.assign_work_order(wo_p["id"], {"crew_id": cr_l["id"]}, DISP))
        fcl = make_field_crew_lead_headers(cr_l["id"])
        get_success_data(api.arrive_work_order(wo_p["id"], fcl))
        get_success_data(api.start_work_order(wo_p["id"], fcl))
        # Nest a child while the parent is WORKING.
        child = get_success_data(
            api.create_outage(
                create_outage_payload(
                    ev["id"], fd["id"], parent_outage_id=parent["id"]
                ),
                DISP,
            )
        )
        get_success_data(
            api.confirm_outage(
                child["id"],
                create_confirm_outage_payload(
                    customers_affected=15, cause_code="TREE"
                ),
                DISP,
            )
        )
        # Complete and verify the parent's work order; restore the parent.
        get_success_data(api.complete_work_order(wo_p["id"], fcl))
        get_success_data(
            api.verify_work_order(wo_p["id"], {"outcome": "PASSED"}, DISP)
        )
        get_success_data(api.report_restored(parent["id"], DISP))
        get_success_data(
            api.create_trouble_signal(
                create_trouble_signal_payload(
                    fd["id"],
                    signal_type="METER_RESTORE_PING",
                    occurred_at="2026-08-10T00:00:00Z",
                    outage_id=parent["id"],
                ),
                TG,
            )
        )
        # Child is still CONFIRMED — parent verify is blocked.
        resp = api.verify_outage(parent["id"], DISP)
        err = validate_error(resp, ApiErrorId.ERR_OUTAGE_CHILDREN_OPEN)
        assert err["error_id"] == "ERR_OUTAGE_CHILDREN_OPEN"

    def test_parent_verify_succeeds_after_child_verified(self, api):
        """PRD §3.6: "Verifying a `RESTORED` outage checks three things: every
        child outage nested beneath it must be in `VERIFIED` or `CANCELLED`"
        and PRD §3.5: "Restoration of a parent says nothing about its nested
        outages: children in `CONFIRMED`, `ASSESSED`, or `WORKING` remain open
        and must be worked to their own conclusions."

        Design: Difficulty/cross_entity_state_dependency/outage_verify_gated_by_nested_child_outages
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Xi", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        parent = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                parent["id"],
                create_confirm_outage_payload(
                    customers_affected=40, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        cr_l = create_crew(crew_type="LINE")
        create_accepted_assessment(
            parent["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=30,
            requires_switching=False,
        )
        wo_p = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    parent["id"], work_type="REPAIR", required_crew_type="LINE"
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(wo_p["id"], DISP))
        get_success_data(api.assign_work_order(wo_p["id"], {"crew_id": cr_l["id"]}, DISP))
        fcl = make_field_crew_lead_headers(cr_l["id"])
        get_success_data(api.arrive_work_order(wo_p["id"], fcl))
        get_success_data(api.start_work_order(wo_p["id"], fcl))
        child = get_success_data(
            api.create_outage(
                create_outage_payload(
                    ev["id"], fd["id"], parent_outage_id=parent["id"]
                ),
                DISP,
            )
        )
        get_success_data(
            api.confirm_outage(
                child["id"],
                create_confirm_outage_payload(
                    customers_affected=15, cause_code="TREE"
                ),
                DISP,
            )
        )
        get_success_data(api.complete_work_order(wo_p["id"], fcl))
        get_success_data(
            api.verify_work_order(wo_p["id"], {"outcome": "PASSED"}, DISP)
        )
        get_success_data(api.report_restored(parent["id"], DISP))
        get_success_data(
            api.create_trouble_signal(
                create_trouble_signal_payload(
                    fd["id"],
                    signal_type="METER_RESTORE_PING",
                    occurred_at="2026-08-10T00:00:00Z",
                    outage_id=parent["id"],
                ),
                TG,
            )
        )
        # Work the child to VERIFIED independently.
        wo_c = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    child["id"], work_type="ASSESSMENT", required_crew_type="LINE"
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(wo_c["id"], DISP))
        get_success_data(api.assign_work_order(wo_c["id"], {"crew_id": cr_l["id"]}, DISP))
        get_success_data(api.arrive_work_order(wo_c["id"], fcl))
        get_success_data(api.start_work_order(wo_c["id"], fcl))
        get_success_data(api.complete_work_order(wo_c["id"], fcl))
        get_success_data(
            api.verify_work_order(wo_c["id"], {"outcome": "PASSED"}, DISP)
        )
        get_success_data(api.report_restored(child["id"], DISP))
        get_success_data(
            api.create_trouble_signal(
                create_trouble_signal_payload(
                    fd["id"],
                    signal_type="METER_RESTORE_PING",
                    occurred_at="2026-08-10T00:00:00Z",
                    outage_id=child["id"],
                ),
                TG,
            )
        )
        get_success_data(api.verify_outage(child["id"], DISP))
        # Now the parent's verify succeeds.
        parent_read = get_success_data(api.verify_outage(parent["id"], DISP))
        assert parent_read["outage_status"] == "VERIFIED"
