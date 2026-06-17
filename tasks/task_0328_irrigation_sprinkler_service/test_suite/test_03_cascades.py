"""Cascading side effects and conserved-quantity invariants: the system-decommission
depth-3 chain, the backflow PASS bubble-up to compliance, and the money / slot-count
conservation when a work order is cancelled.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_customer_property_system,
    setup_backflow_ready,
    record_backflow_test,
    create_customer,
    create_property,
    create_system,
    create_zone,
    create_technician,
    create_work_order,
    create_route,
    create_route_stop,
    create_program,
    winterize_then_startup_system,
    make_technician_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_system_decommission_cascades_zone_program_workorder(api):
    """PRD §3.5: "First, every zone of the system whose `zone_state` is not already
    `ARCHIVED` is moved to `ARCHIVED`. Second, each zone just archived that is referenced
    by the slots of an `ACTIVE` controller program forces that program from `ACTIVE` to
    `STALE`. Third, every work order on the system whose `completion_status` is not already
    one of `COMPLETED`, `FAILED`, or `CANCELLED` is cancelled".

    Design: Difficulty/transitive_cascade/system_decommission_depth3_zone_program_workorder_chain
    """
    cust = create_customer(company_name="Casc Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=60)
    zone = create_zone(sys["id"], 1, plant_type="TURF", head_count=8, gpm_per_head=18)
    tech = create_technician(full_name="Cas Tech")

    # Take the system to season_state=ACTIVE so a program may be activated.
    winterize_then_startup_system(sys["id"], tech["id"], route_date="2026-10-01")

    # Activate a controller program over the zone (DRAFT -> ACTIVE, zone -> ACTIVE).
    prog = create_program(sys["id"], [{"zone_id": zone["id"], "start_sec": 21600, "run_minutes": 20}])
    tech_headers = make_technician_headers(tech["id"])
    validate_success(api.activate_program(prog["id"], tech_headers))

    # An open work order that the cascade must cancel.
    open_wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                                estimated_minutes=20, estimated_cost_cents=3000)

    validate_success(api.decommission_system(sys["id"], DISPATCHER))

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["lifecycle_state"] == "DECOMMISSIONED"
    z = validate_success(api.get_zone(zone["id"], DISPATCHER))
    assert z["zone_state"] == "ARCHIVED", f"zone should be ARCHIVED, got {z['zone_state']}"
    program = validate_success(api.get_program(prog["id"], DISPATCHER))
    assert program["program_state"] == "STALE", (
        f"program should be STALE, got {program['program_state']}")
    wo = validate_success(api.get_work_order(open_wo["id"], DISPATCHER))
    assert wo["completion_status"] == "CANCELLED", (
        f"open work order should be CANCELLED, got {wo['completion_status']}")


def test_backflow_pass_certifies_system_and_makes_property_compliant(api):
    """PRD §3.5: "A `PASS` sets the system's `backflow_status` to `CERTIFIED`, then
    recomputes the property's `compliance_status` — which becomes `COMPLIANT` only if every
    non-decommissioned system on that property is now `CERTIFIED`."

    Design: Difficulty/transitive_cascade/backflow_pass_bubbles_up_system_then_property_compliance
    """
    prop, sys, tester = setup_backflow_ready(has_backflow_device=True, certified=True)
    test = record_backflow_test(sys["id"], tester["id"], relief_open_psi=5, checkvalve_hold_psi=3)
    assert test["result"] == "PASS"

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["backflow_status"] == "CERTIFIED", (
        f"backflow_status should be CERTIFIED, got {system['backflow_status']}")
    property_ = validate_success(api.get_property(prop["id"], DISPATCHER))
    assert property_["compliance_status"] == "COMPLIANT", (
        f"compliance_status should be COMPLIANT, got {property_['compliance_status']}")


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_committed_cost_credited_back_on_cancel(api):
    """PRD §3.4: "Creating any work order immediately debits the serviced system's
    `committed_cost_cents` by the work order's `estimated_cost_cents`." PRD §3.4:
    "Cancellation credits the system's `committed_cost_cents` back by the
    `estimated_cost_cents`".

    Design: Difficulty/compensating_invariant/committed_cost_conserved_on_cancel
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Inv1 Co")
    wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=3000)
    before = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert before["committed_cost_cents"] == 3000

    validate_success(api.cancel_work_order(wo["id"], DISPATCHER))

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["committed_cost_cents"] == 0, (
        f"committed_cost_cents should return to 0, got {system['committed_cost_cents']}")
    work_order = validate_success(api.get_work_order(wo["id"], DISPATCHER))
    assert work_order["completion_status"] == "CANCELLED"


def test_route_slot_freed_when_work_order_cancelled(api):
    """PRD §3.4: "Cancellation... additionally drives any `SCHEDULED` route stop that
    references this work order to `REMOVED`, recomputing that stop's route `stops_used` and
    `minutes_committed`." PRD §3.6: "A route's `stops_used` is the count of its route stops
    whose `stop_state` is `SCHEDULED`".

    Design: Difficulty/compensating_invariant/route_slot_count_conserved_on_stop_removal
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Inv2 Co")
    tech = create_technician(full_name="Inv2 Tech")
    wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=3000)
    route = create_route(tech["id"], route_date="2026-05-05")
    route_after = create_route_stop(route["id"], wo["id"], route["version"],
                                    arrival_start_sec=28800, window_minutes=60)
    assert route_after["stops_used"] == 1

    validate_success(api.cancel_work_order(wo["id"], DISPATCHER))

    route_now = validate_success(api.get_route(route["id"], DISPATCHER))
    assert route_now["stops_used"] == 0, (
        f"stops_used should return to 0, got {route_now['stops_used']}")
    work_order = validate_success(api.get_work_order(wo["id"], DISPATCHER))
    assert work_order["completion_status"] == "CANCELLED"
