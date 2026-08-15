"""Difficulty tests — priority_pair_validation_conflict rule.

Two instances each pin the relative order of two validation categories.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_accepted_assessment,
    create_and_activate_event,
    create_available_mutual_aid_crew,
    create_committed_lodging_block,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    create_switching_order_payload,
    create_work_order_payload,
    get_success_data,
    make_field_crew_lead_headers,
    make_system_operator_headers,
    set_clock,
    setup_event_with_feeder,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]


class TestStartStateErrorBeatsSwitchingSafetyError:
    """Priority 4 (state) fires before priority 5 (business_safety)."""

    def test_ready_work_order_with_unexecuted_switching_order_yields_state_error(self, api):
        """PRD §2.7: "Every request is validated against an ordered cascade of
        gates, and a failure at an earlier gate masks every later check — the
        client always receives the earliest applicable error." Gate 4 covers
        "The target resource's own state must permit the transition
        (`ERR_INVALID_STATE_TRANSITION`, 400)"; gate 5 covers
        `ERR_SWITCHING_NOT_EXECUTED` at 422.

        Design: Difficulty/priority_pair_validation_conflict/start_state_error_beats_switching_safety_error
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(
            event_name="Storm Iota", event_type="THUNDERSTORM"
        )
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

        # Work order is READY (never DISPATCHED); switching order is ISSUED.
        # The start call violates gate 4 first.
        resp = api.start_work_order(wo["id"], DISP)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION"
        # The masked safety error must NOT leak.
        assert err["error_id"] != "ERR_SWITCHING_NOT_EXECUTED"

        wo_read = get_success_data(api.get_work_order(wo["id"], DISP))
        assert wo_read["execution_status"] == "READY"
        so_read = get_success_data(api.get_switching_order(so["id"], DISP))
        assert so_read["so_status"] == "ISSUED"

    def test_dispatched_work_order_with_unexecuted_switching_order_yields_safety_error(self, api):
        """PRD §3.5: "When `requires_switching_order` is true, the switching
        order recorded on the work order must have reached `EXECUTED`,
        otherwise the start is rejected with `ERR_SWITCHING_NOT_EXECUTED`."

        Design: Difficulty/priority_pair_validation_conflict/start_state_error_beats_switching_safety_error
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(
            event_name="Storm Iota", event_type="THUNDERSTORM"
        )
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
        get_success_data(
            api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP)
        )
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
        # State check now passes (DISPATCHED + ON_SITE); the safety gate fires.
        resp = api.start_work_order(wo["id"], fcl)
        err = validate_error(resp, ApiErrorId.ERR_SWITCHING_NOT_EXECUTED)
        assert err["error_id"] == "ERR_SWITCHING_NOT_EXECUTED"


class TestLodgingTemporalErrorBeatsFiscalError:
    """Priority 7 (temporal) fires before priority 9 (fiscal)."""

    def test_window_containment_failure_masks_room_capacity_failure(self, api):
        """PRD §2.7: "Every request is validated against an ordered cascade of
        gates, and a failure at an earlier gate masks every later check — the
        client always receives the earliest applicable error." Gate 7 covers
        `ERR_WINDOW_OUTSIDE_BLOCK`; gate 9 covers `ERR_NO_ROOMS_AVAILABLE`.

        Design: Difficulty/priority_pair_validation_conflict/lodging_temporal_error_beats_fiscal_error
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Kappa", event_type="HURRICANE")
        lb = create_committed_lodging_block(
            ev["id"],
            room_count=2,
            nightly_rate_cents=10000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-13T00:00:00Z",
            county_code="C1",
            hotel_name="Hotel H",
        )
        ma = create_available_mutual_aid_crew(
            ev["id"],
            crew_type="LINE",
            roster_size=2,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-13T00:00:00Z",
        )
        get_success_data(
            api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC)
        )
        # Block now full (2/2 rooms).
        mb = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-10T00:00:00Z",
                    committed_window_end="2026-08-14T00:00:00Z",
                    company_name="PeerCo B",
                    crew_type="TREE",
                    roster_size=1,
                ),
                MAC,
            )
        )
        get_success_data(api.mark_arrived(mb["id"], MAC))

        # Crew B's window [08-10, 08-14) escapes the block's [08-10, 08-13)
        # AND the block is full — the temporal error must win.
        resp = api.assign_lodging(mb["id"], {"lodging_block_id": lb["id"]}, MAC)
        err = validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_BLOCK)
        assert err["error_id"] == "ERR_WINDOW_OUTSIDE_BLOCK"
        assert err["error_id"] != "ERR_NO_ROOMS_AVAILABLE"

        block = get_success_data(api.get_lodging_block(lb["id"], MAC))
        assert block["rooms_allocated"] == 2
        crew_b = get_success_data(api.get_mutual_aid_crew(mb["id"], MAC))
        assert crew_b["lodging_block_id"] is None

    def test_temporal_window_rule_cited_alone(self, api):
        """PRD §3.7: "the crew's committed window must be contained in the
        block's window — starting no earlier than `window_start` and ending no
        later than `window_end` — (`ERR_WINDOW_OUTSIDE_BLOCK`)".

        Design: Difficulty/priority_pair_validation_conflict/lodging_temporal_error_beats_fiscal_error
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Kappa", event_type="HURRICANE")
        lb = create_committed_lodging_block(
            ev["id"],
            room_count=10,
            nightly_rate_cents=10000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-13T00:00:00Z",
            county_code="C1",
            hotel_name="Hotel H",
        )
        # Plenty of rooms remain; only the window escapes.
        ma = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-10T00:00:00Z",
                    committed_window_end="2026-08-14T00:00:00Z",
                    company_name="PeerCo Solo",
                    crew_type="LINE",
                    roster_size=1,
                ),
                MAC,
            )
        )
        get_success_data(api.mark_arrived(ma["id"], MAC))
        resp = api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC)
        err = validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_BLOCK)
        assert err["error_id"] == "ERR_WINDOW_OUTSIDE_BLOCK"
