"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so nothing is
carried over). Setup calls use the lenient get_success_data validator so a
failed precondition reports as a clear setup error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_car_order_payload,
    create_crew_call_payload,
    create_crew_member_payload,
    create_customer_payload,
    create_grant_milestone_payload,
    create_grant_project_payload,
    create_incident_payload,
    create_interchange_event_payload,
    create_railcar_payload,
    create_siding_payload,
    create_track_inspection_payload,
    create_track_segment_payload,
    create_train_movement_payload,
    create_waybill_payload,
)
from .test_users import TEST_USERS, make_conductor_headers, make_customer_rep_headers

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]
INSPECTOR = TEST_USERS["track_inspector_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
REGULATOR = TEST_USERS["regulator_officer_headers"]
GRANT_MGR = TEST_USERS["grant_manager_headers"]


# --- Clock (PRD §2.4) ---

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; returns the sweep-counters payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --- Master data (PRD §3.1, §3.3, §3.6, §3.7) ---

def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def create_segment(**overrides) -> dict:
    return get_success_data(api_client.create_track_segment(create_track_segment_payload(**overrides), ADMIN))


def create_siding(customer_id: str, segment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_siding(create_siding_payload(customer_id, segment_id, **overrides), ADMIN)
    )


def create_railcar(**overrides) -> dict:
    return get_success_data(api_client.create_railcar(create_railcar_payload(**overrides), ADMIN))


def create_crew_member(**overrides) -> dict:
    return get_success_data(api_client.create_crew_member(create_crew_member_payload(**overrides), ADMIN))


def create_movement(route_segment_ids, **overrides) -> dict:
    return get_success_data(
        api_client.create_train_movement(create_train_movement_payload(route_segment_ids, **overrides), DISPATCH)
    )


def create_inspection(segment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_track_inspection(create_track_inspection_payload(segment_id, **overrides), INSPECTOR)
    )


# --- Car orders (PRD §3.1, §3.2) ---

def place_car_order(customer_id: str, siding_id: str, **overrides) -> dict:
    """CustomerRep places an order; identity is entity-backed (PRD §2.1)."""
    return get_success_data(
        api_client.create_car_order(
            create_car_order_payload(customer_id, siding_id, **overrides),
            make_customer_rep_headers(customer_id),
        )
    )


def setup_customer_with_siding(capacity_cars=10, fra_class="CLASS_1", **customer_over):
    """Customer + serving segment + siding. Returns (customer, segment, siding)."""
    customer = create_customer(**customer_over)
    segment = create_segment(fra_class=fra_class)
    siding = create_siding(customer["id"], segment["id"], capacity_cars=capacity_cars)
    return customer, segment, siding


def setup_placed_order(quantity=1, car_type="BOX", capacity_cars=10, **order_over) -> dict:
    """Customer + segment + siding + PLACED order. Returns a context dict."""
    customer, segment, siding = setup_customer_with_siding(capacity_cars=capacity_cars)
    order = place_car_order(customer["id"], siding["id"], car_type=car_type, quantity=quantity, **order_over)
    return {"customer": customer, "segment": segment, "siding": siding, "order": order}


def accept_order(order_id: str) -> dict:
    return get_success_data(api_client.accept_car_order(order_id, DISPATCH))


def furnish_order(order_id: str, count: int) -> dict:
    return get_success_data(api_client.furnish_car_order(order_id, {"count": count}, DISPATCH))


def setup_accepted_order(quantity=1, car_type="BOX", capacity_cars=10, num_cars=0,
                         car_ownership="HOME", **order_over) -> dict:
    """PLACED -> ACCEPTED order, optionally with `num_cars` eligible railcars."""
    ctx = setup_placed_order(quantity=quantity, car_type=car_type, capacity_cars=capacity_cars, **order_over)
    ctx["order"] = accept_order(ctx["order"]["id"])
    ctx["railcars"] = [
        create_railcar(car_type=car_type, ownership=car_ownership) for _ in range(num_cars)
    ]
    return ctx


def setup_furnished_order(quantity=1, furnish_count=None, **kwargs) -> dict:
    """ACCEPTED order furnished with `furnish_count` cars (defaults to quantity)."""
    qty = quantity
    count = furnish_count if furnish_count is not None else qty
    ctx = setup_accepted_order(quantity=qty, num_cars=count, **kwargs)
    ctx["order"] = furnish_order(ctx["order"]["id"], count)
    return ctx


def setup_released_order(quantity=1, **kwargs) -> dict:
    """FURNISHED order released by its owning CustomerRep."""
    ctx = setup_furnished_order(quantity=quantity, **kwargs)
    ctx["order"] = get_success_data(
        api_client.release_car_order(ctx["order"]["id"], make_customer_rep_headers(ctx["customer"]["id"]))
    )
    return ctx


# --- Crew calling (PRD §3.7) ---

def create_crew_call_for_movement(member_id: str, movement_id: str,
                                  start="2026-05-02T06:00:00Z", end="2026-05-02T18:00:00Z") -> dict:
    payload = create_crew_call_payload(
        member_id, movement_id=movement_id, scheduled_start_at=start, scheduled_end_at=end
    )
    return get_success_data(api_client.create_crew_call(payload, CALLER))


def accept_call(call_id: str, member_id: str) -> dict:
    """Called member accepts; Conductor identity is entity-backed (PRD §2.1)."""
    return get_success_data(
        api_client.respond_crew_call(call_id, {"response": "ACCEPTED"}, make_conductor_headers(member_id))
    )


def setup_movement_with_crew(symbol="GW-100", fra_class="CLASS_3",
                             start="2026-05-02T06:00:00Z", end="2026-05-02T18:00:00Z",
                             respond=True) -> dict:
    """Segment + movement + crew member + call (ACCEPTED when respond=True)."""
    segment = create_segment(fra_class=fra_class)
    movement = create_movement([segment["id"]], symbol=symbol)
    member = create_crew_member()
    call = create_crew_call_for_movement(member["id"], movement["id"], start, end)
    if respond:
        call = accept_call(call["id"], member["id"])
    return {"segment": segment, "movement": movement, "member": member, "call": call}


def setup_departed_movement(**kwargs) -> dict:
    """Movement walked PLANNED -> READY -> DEPARTED."""
    ctx = setup_movement_with_crew(**kwargs)
    get_success_data(api_client.ready_train_movement(ctx["movement"]["id"], DISPATCH))
    ctx["movement"] = get_success_data(api_client.depart_train_movement(ctx["movement"]["id"], DISPATCH))
    return ctx


def setup_arrived_movement(**kwargs) -> dict:
    """Movement walked PLANNED -> READY -> DEPARTED -> ARRIVED."""
    ctx = setup_departed_movement(**kwargs)
    ctx["movement"] = get_success_data(api_client.arrive_train_movement(ctx["movement"]["id"], DISPATCH))
    return ctx


def adjust_hos(member_id: str, version: int, **fields) -> dict:
    """OCC-guarded HOS correction (PRD §2.8); caller supplies the live version."""
    payload = {"expected_crew_member_version": version}
    payload.update(fields)
    return get_success_data(api_client.adjust_crew_member_hos(member_id, payload, CALLER))


def setup_member_with_accumulators(**fields) -> dict:
    """Fresh crew member whose HOS accumulators are corrected via adjust-hos."""
    member = create_crew_member()
    member = adjust_hos(member["id"], member["version"], **fields)
    return member


# --- Waybills and revenue divisions (PRD §3.5) ---

def create_waybill(railcar_id: str, customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_waybill(create_waybill_payload(railcar_id, customer_id, **overrides), DISPATCH)
    )


def setup_rated_waybill(commodity="GRAIN", weight_tons=10, through_route=False,
                        our_miles=None, total_miles=None, **waybill_over) -> dict:
    """Customer + HOME railcar + waybill, rated by the clerk. Returns context."""
    customer = create_customer()
    railcar = create_railcar()
    extra = dict(waybill_over)
    if through_route:
        extra["our_miles"] = our_miles if our_miles is not None else 10
        extra["total_miles"] = total_miles if total_miles is not None else 100
    waybill = create_waybill(
        railcar["id"], customer["id"], commodity=commodity, weight_tons=weight_tons,
        through_route=through_route, **extra,
    )
    waybill = get_success_data(api_client.rate_waybill(waybill["id"], CLERK))
    return {"customer": customer, "railcar": railcar, "waybill": waybill}


# --- Interchange and car hire (PRD §3.3) ---

def report_and_confirm_interchange(railcar_id: str, direction="RECEIVED", **overrides) -> dict:
    event = get_success_data(
        api_client.create_interchange_event(
            create_interchange_event_payload(railcar_id, direction=direction, **overrides), DISPATCH
        )
    )
    return get_success_data(api_client.confirm_interchange_event(event["id"], CLERK))


def receive_foreign_car(mark="CSXT 100", hire_rate_per_hour_cents=100,
                        hire_rate_per_mile_cents=50, partner="CSX", **car_over) -> dict:
    """FOREIGN car with a confirmed RECEIVED event; statement OPEN. Returns context."""
    railcar = create_railcar(
        reporting_mark=mark, ownership="FOREIGN", home_road_mark=partner,
        hire_rate_per_hour_cents=hire_rate_per_hour_cents,
        hire_rate_per_mile_cents=hire_rate_per_mile_cents,
        **car_over,
    )
    event = report_and_confirm_interchange(railcar["id"], "RECEIVED", class_i_partner=partner)
    statements, _meta = _list_statements(railcar["id"])
    return {"railcar": railcar, "event": event, "statement": statements[0]}


def _list_statements(railcar_id: str):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_car_hire_statements(CLERK, params={"railcar_id": railcar_id})
    return validate_paginated(resp)


# --- Incidents (PRD §3.8) ---

def create_incident(segment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_incident(create_incident_payload(segment_id, **overrides), DISPATCH)
    )


def setup_investigating_incident(incident_type="DERAILMENT", estimated_damage_cents=2000000, **over) -> dict:
    """Segment + incident walked REPORTED -> INVESTIGATING."""
    segment = create_segment()
    incident = create_incident(
        segment["id"], incident_type=incident_type, estimated_damage_cents=estimated_damage_cents, **over
    )
    incident = get_success_data(api_client.investigate_incident(incident["id"], DISPATCH))
    return {"segment": segment, "incident": incident}


# --- Grant projects (PRD §3.9) ---

def create_grant_project(**overrides) -> dict:
    return get_success_data(api_client.create_grant_project(create_grant_project_payload(**overrides), GRANT_MGR))


def setup_active_project(award_amount_cents=1000000, required_match_pct=20, **over) -> dict:
    project = create_grant_project(
        award_amount_cents=award_amount_cents, required_match_pct=required_match_pct, **over
    )
    return get_success_data(api_client.activate_grant_project(project["id"], GRANT_MGR))


def create_milestone(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_grant_milestone(project_id, create_grant_milestone_payload(**overrides), GRANT_MGR)
    )


def submit_milestone(milestone_id: str, actual_cost_cents: int) -> dict:
    return get_success_data(
        api_client.submit_grant_milestone(milestone_id, {"actual_cost_cents": actual_cost_cents}, GRANT_MGR)
    )


def approve_milestone(milestone_id: str) -> dict:
    return get_success_data(api_client.approve_grant_milestone(milestone_id, REGULATOR))


def reject_milestone(milestone_id: str) -> dict:
    return get_success_data(api_client.reject_grant_milestone(milestone_id, REGULATOR))


def pay_milestone(milestone_id: str) -> dict:
    return get_success_data(api_client.pay_grant_milestone(milestone_id, CLERK))
