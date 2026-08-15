"""Corner tests — state_machines section.

Covers invalid transitions, precondition enforcement, terminal lockdown, and
clock-driven sweeps.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    create_accepted_assessment,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_fema_claim,
    create_fema_claim_payload,
    create_feeder_record,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    create_priority_customer_payload,
    create_ready_work_order,
    create_requisition,
    create_stock,
    create_switching_order_payload,
    create_work_order_payload,
    get_success_data,
    make_field_crew_lead_headers,
    make_system_operator_headers,
    run_work_order_to_completed,
    set_clock,
    setup_demobilized_event_with_claim,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]
MM = TEST_USERS["materials_manager_headers"]
CO1 = TEST_USERS["claims_officer_headers"]


def test_event_close_from_active_returns_invalid_state(api):
    """PRD §3.9: "Closing then moves `DEMOBILIZING` to `CLOSED`" — closing
    directly from `ACTIVE` skips `DEMOBILIZING` and is rejected.

    Design: Corner/state_machines/event_close_from_active_returns_invalid_state
    """
    ev, _fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    resp = api.close_storm_event(ev["id"], ED)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION"
    read = get_success_data(api.get_storm_event(ev["id"], ED))
    assert read["event_status"] == "ACTIVE"


def test_event_demobilize_blocked_by_open_outage(api):
    """PRD §3.9: "Beginning demobilization moves `ACTIVE` to `DEMOBILIZING`
    and is refused with `ERR_EVENT_HAS_OPEN_WORK` while any of four kinds of
    open work remains: any outage of the event not yet in `VERIFIED` or
    `CANCELLED`".

    Design: Corner/state_machines/event_demobilize_blocked_by_open_outage
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    resp = api.begin_demobilization(ev["id"], ED)
    err = validate_error(resp, ApiErrorId.ERR_EVENT_HAS_OPEN_WORK)
    assert err["error_id"] == "ERR_EVENT_HAS_OPEN_WORK"
    read = get_success_data(api.get_storm_event(ev["id"], ED))
    assert read["event_status"] == "ACTIVE"


def test_outage_terminal_lockdown_cancelled_rejects_confirm(api):
    """PRD §3.3: "A false-alarm cancellation — available only from
    `SUSPECTED` or `CONFIRMED`" — once `CANCELLED` the outage accepts no
    further transitions.

    Design: Corner/state_machines/outage_terminal_lockdown_cancelled_rejects_confirm
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(api.cancel_outage(ot["id"], DISP))
    resp = api.confirm_outage(
        ot["id"],
        create_confirm_outage_payload(customers_affected=5, cause_code="TREE"),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION"
    read = get_success_data(api.get_outage(ot["id"], DISP))
    assert read["outage_status"] == "CANCELLED"
    assert read["customers_affected"] is None


def test_crew_end_shift_while_en_route_rejected(api):
    """PRD §3.5: "ending a shift returns the crew to `OFF_DUTY` and is
    accepted only from `AVAILABLE` — a crew that is `EN_ROUTE` or `ON_SITE`
    on any non-terminal work order cannot go off duty, and the attempt is
    rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/crew_end_shift_while_en_route_rejected
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l = create_crew(crew_type="LINE")
    wo = create_ready_work_order(ot["id"])
    get_success_data(api.assign_work_order(wo["id"], {"crew_id": cr_l["id"]}, DISP))
    # Crew is EN_ROUTE after the assign.
    resp = api.end_shift(cr_l["id"], DISP)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION"
    read = get_success_data(api.get_crew(cr_l["id"], DISP))
    assert read["crew_status"] == "EN_ROUTE"


def test_switching_issue_by_non_issuer_returns_ownership_error(api):
    """PRD §3.6: "Issuance moves the order from `DRAFT` to `ISSUED` and is
    restricted to the issuer — any other operator is rejected with
    `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/state_machines/switching_issue_by_non_issuer_returns_ownership_error
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    wo = get_success_data(
        api.create_work_order(
            create_work_order_payload(
                ot["id"],
                work_type="SWITCHING",
                required_crew_type="LINE",
                requires_switching_order=True,
            ),
            DISP,
        )
    )
    so = get_success_data(
        api.create_switching_order(
            create_switching_order_payload(wo["id"]),
            make_system_operator_headers("op-1"),
        )
    )
    resp = api.issue_switching_order(so["id"], make_system_operator_headers("op-2"))
    err = validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert err["error_id"] == "ERR_OWNERSHIP_MISMATCH"
    read = get_success_data(api.get_switching_order(so["id"], DISP))
    assert read["so_status"] == "DRAFT"


def test_switching_abort_clears_work_order_link(api):
    """PRD §3.6: "Aborting from `DRAFT`, `ISSUED`, or `APPROVED` moves the
    order to `ABORTED` and clears the work order's `switching_order_id`, so a
    switching-gated order needs a fresh executed order before it can start."

    Design: Corner/state_machines/switching_abort_clears_work_order_link
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="EQUIPMENT"),
            DISP,
        )
    )
    wo = get_success_data(
        api.create_work_order(
            create_work_order_payload(
                ot["id"],
                work_type="SWITCHING",
                required_crew_type="LINE",
                requires_switching_order=True,
            ),
            DISP,
        )
    )
    so = get_success_data(
        api.create_switching_order(
            create_switching_order_payload(wo["id"]),
            make_system_operator_headers("op-1"),
        )
    )
    get_success_data(
        api.issue_switching_order(so["id"], make_system_operator_headers("op-1"))
    )
    aborted = get_success_data(
        api.abort_switching_order(so["id"], make_system_operator_headers("op-1"))
    )
    assert aborted["so_status"] == "ABORTED"
    wo_read = get_success_data(api.get_work_order(wo["id"], DISP))
    assert wo_read["switching_order_id"] is None


def test_requisition_issue_from_requested_rejected(api):
    """PRD §3.8: "Issuing moves `STAGED` to `ISSUED`" — issuing a requisition
    still in `REQUESTED` is rejected.

    Design: Corner/state_machines/requisition_issue_from_requested_rejected
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    wo = create_ready_work_order(ot["id"])
    ms = create_stock(quantity_on_hand=100, unit_cost_cents=500)
    mr = create_requisition(wo["id"], ms["id"], quantity=10)
    resp = api.issue_material_requisition(mr["id"], MM)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION"
    stock = get_success_data(api.get_material_stock(ms["id"], MM))
    assert stock["quantity_on_hand"] == 100
    assert stock["quantity_reserved"] == 0


def test_fema_withdraw_permanent_terminal(api):
    """PRD §3.9: "withdrawal with `permanent` set true moves a claim from
    `DRAFT` or `SUBMITTED` to `WITHDRAWN`, terminal."

    Design: Corner/state_machines/fema_withdraw_permanent_terminal
    """
    set_clock("2026-08-10T00:00:00Z")
    ev = create_and_activate_event(event_name="Storm S8", event_type="HURRICANE")
    fc = create_fema_claim(ev["id"], county_code="C1", threshold_cents=1000)
    withdrawn = get_success_data(
        api.withdraw_fema_claim(fc["id"], {"permanent": True}, CO1)
    )
    assert withdrawn["claim_status"] == "WITHDRAWN"
    # Terminal: a later submit is rejected as an invalid state.
    resp = api.submit_fema_claim(fc["id"], CO1)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert err["error_id"] == "ERR_INVALID_STATE_TRANSITION"


def test_mutual_aid_arrive_outside_window_rejected(api):
    """PRD §3.7: "marking a crew arrived moves it from `REQUESTED` to
    `AVAILABLE` only when the logical now falls within the committed window —
    start inclusive, end exclusive — (`ERR_OUTSIDE_ENGAGEMENT_WINDOW`)".

    Design: Corner/state_machines/mutual_aid_arrive_outside_window_rejected
    """
    set_clock("2026-08-10T23:59:00Z")
    ev = create_and_activate_event(event_name="Storm S9", event_type="HURRICANE")
    ma = get_success_data(
        api.create_mutual_aid_crew(
            create_mutual_aid_crew_payload(
                ev["id"],
                committed_window_start="2026-08-11T00:00:00Z",
                committed_window_end="2026-08-15T00:00:00Z",
                roster_size=2,
            ),
            MAC,
        )
    )
    # One minute before window start: rejected.
    resp = api.mark_arrived(ma["id"], MAC)
    err = validate_error(resp, ApiErrorId.ERR_OUTSIDE_ENGAGEMENT_WINDOW)
    assert err["error_id"] == "ERR_OUTSIDE_ENGAGEMENT_WINDOW"
    # At exactly the window start: inclusive start — succeeds.
    set_clock("2026-08-11T00:00:00Z")
    arrived = get_success_data(api.mark_arrived(ma["id"], MAC))
    assert arrived["ma_status"] == "AVAILABLE"
    assert_instant_equals(arrived["arrived_at"], "2026-08-11T00:00:00Z")


def test_priority_customer_cert_expiry_sweep_and_recompute(api):
    """PRD §2.4: "Advancing the clock performs a certification sweep: every
    priority customer whose `certification_status` is `CERTIFIED` and whose
    `certified_through` lies strictly before the new logical now transitions
    to `SUSPENDED`, and the sweep recomputes the affected feeder's
    `certified_priority_count` as well as `has_priority_customers` and
    `priority_score` on every non-terminal outage served by that feeder."

    Design: Corner/state_machines/priority_customer_cert_expiry_sweep_and_recompute
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    pc = get_success_data(
        api.create_priority_customer(create_priority_customer_payload(fd["id"]), DISP)
    )
    get_success_data(
        api.certify_priority_customer(
            pc["id"], {"certified_through": "2026-08-12T00:00:00Z"}, DISP
        )
    )
    ot = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    get_success_data(
        api.confirm_outage(
            ot["id"],
            create_confirm_outage_payload(customers_affected=5, cause_code="TREE"),
            DISP,
        )
    )
    # Pre-sweep sanity.
    pre = get_success_data(api.get_outage(ot["id"], DISP))
    assert pre["has_priority_customers"] is True
    feeder_pre = get_success_data(api.get_feeder(fd["id"], DISP))
    assert feeder_pre["certified_priority_count"] == 1

    # Advance the clock past certified_through.
    set_clock("2026-08-12T00:00:01Z")
    pc_read = get_success_data(api.get_priority_customer(pc["id"], DISP))
    assert pc_read["certification_status"] == "SUSPENDED"
    feeder_post = get_success_data(api.get_feeder(fd["id"], DISP))
    assert feeder_post["certified_priority_count"] == 0
    outage_post = get_success_data(api.get_outage(ot["id"], DISP))
    assert outage_post["has_priority_customers"] is False
