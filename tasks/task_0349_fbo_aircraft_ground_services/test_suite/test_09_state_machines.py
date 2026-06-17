"""State-machine corner cases: invalid transitions, terminal lockdown, cross-entity
side effects, bubble-up counters, and the multi-line invoice aggregation
(PRD §3.3, §3.6, §3.7, §3.8, §3.9).

Corner queue (B) instances:
  - state_machines / dispatch_already_dispatched_returns_invalid_state
  - state_machines / depart_from_scheduled_returns_invalid_state
  - state_machines / cancel_departed_visit_terminal_lockdown
  - state_machines / mark_past_due_suspends_operator_cross_entity
  - state_machines / complete_ramp_service_bubbles_up_counter
  - state_machines / re_request_from_approved_returns_invalid_state
  - calculations / invoice_total_multi_line_aggregation
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_servicing_visit,
    setup_departed_visit_with_invoice,
    setup_approved_slot,
    get_invoice_for_visit,
    create_dispatched_fuel_order,
    create_fueled_fuel_order,
    create_ramp_service_payload,
    create_deice_service_payload,
    create_parking_assignment_payload,
    create_service_visit_payload,
    occupy_payload,
    make_operator_headers,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
LINE = TEST_USERS["line_manager_headers"]


def test_dispatch_already_dispatched_returns_invalid_state():
    """PRD §3.6: "A logistics step requested from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`."

    Re-dispatching an already-DISPATCHED order → ERR_INVALID_STATE; priced amount
    (3,115,000) unchanged.

    Design: Corner/state_machines/dispatch_already_dispatched_returns_invalid_state
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_dispatched_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                         ordered_gallons=6000, tankering=False)
    assert order["priced_amount_cents"] == 3_115_000
    res = api.dispatch_fuel_order(order["id"], FUEL)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert after["priced_amount_cents"] == 3_115_000


def test_depart_from_scheduled_returns_invalid_state():
    """PRD §3.7: "When an `OpsDispatcher` or `LineManager` departs a visit, it must be
    `READY_FOR_DEPARTURE`"
    PRD §3.3: "Any of these step requests against a visit that is not in the required
    starting state is rejected with `ERR_INVALID_STATE` (HTTP 409)"

    Departing a SCHEDULED visit (never arrived) → ERR_INVALID_STATE; status stays
    SCHEDULED.

    Design: Corner/state_machines/depart_from_scheduled_returns_invalid_state
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit = get_success_data(api.create_service_visit(
        create_service_visit_payload(operator["id"], aircraft["id"]), OPS))
    res = api.depart_service_visit(visit["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_service_visit(visit["id"], OPS))
    assert after["status"] == "SCHEDULED"


def test_cancel_departed_visit_terminal_lockdown():
    """PRD §3.3: "A cancellation request against a visit in any state other than
    `SCHEDULED` or `ON_GROUND` is rejected with `ERR_INVALID_STATE`."

    Cancelling a DEPARTED (terminal) visit → ERR_INVALID_STATE; status stays DEPARTED.

    Design: Corner/state_machines/cancel_departed_visit_terminal_lockdown
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    assert visit["status"] == "DEPARTED"
    res = api.cancel_service_visit(visit["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_service_visit(visit["id"], OPS))
    assert after["status"] == "DEPARTED"


def test_mark_past_due_suspends_operator_cross_entity():
    """PRD §3.7: "Marking an invoice past due (from `ISSUED`) moves it
    `ISSUED → PAST_DUE` and, as a cross-entity effect, sets the owning operator's
    `account_status` to `SUSPENDED`."

    Marking an ISSUED invoice PAST_DUE sets the owning operator's account_status to
    SUSPENDED.

    Design: Corner/state_machines/mark_past_due_suspends_operator_cross_entity
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    marked = get_success_data(api.mark_past_due_invoice(invoice["id"], BILLING))
    assert marked["status"] == "PAST_DUE"
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["account_status"] == "SUSPENDED"


def test_complete_ramp_service_bubbles_up_counter():
    """PRD §3.8: "Completing it moves it `IN_PROGRESS → COMPLETED`, computes its
    `charge_cents`, and bubbles up by decrementing the parent visit's
    `services_outstanding` by 1."

    Completing the last outstanding service decrements ServiceVisit.services_outstanding
    to 0.

    Design: Corner/state_machines/complete_ramp_service_bubbles_up_counter
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-31"})
    service = get_success_data(api.create_ramp_service(
        create_ramp_service_payload(visit["id"], service_type="GPU"), OPS))
    get_success_data(api.start_ramp_service(service["id"], LINE))
    completed = get_success_data(api.complete_ramp_service(service["id"], LINE))
    assert completed["status"] == "COMPLETED"
    visit_after = get_success_data(api.get_service_visit(visit["id"], OPS))
    assert visit_after["services_outstanding"] == 0


def test_re_request_from_approved_returns_invalid_state():
    """PRD §3.9: "A revoked slot can be **re-requested** — moving it `REVOKED → REQUESTED`"
    PRD §3.9: "Any slot transition from a state where it is not defined is rejected with
    `ERR_INVALID_STATE`."

    Re-requesting a slot that is APPROVED (not REVOKED) → ERR_INVALID_STATE; status stays
    APPROVED.

    Design: Corner/state_machines/re_request_from_approved_returns_invalid_state
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, pad, slot = setup_approved_slot(operator["id"], aircraft["id"])
    assert slot["status"] == "APPROVED"
    res = api.re_request_ramp_slot(slot["id"], make_operator_headers(operator["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_ramp_slot(slot["id"], OPS))
    assert after["status"] == "APPROVED"


def test_invoice_total_aggregates_fuel_parking_and_deice_lines():
    """PRD §3.7: "The invoice `total_cents` is the sum of three line groups for the visit:
    every fuel order on the visit whose `logistics_status` is not `CANCELLED` contributes
    its `priced_amount_cents`; every parking assignment on the visit in `OCCUPIED` status
    contributes its `fee_cents`; and every ramp service on the visit in `COMPLETED` status
    contributes its `charge_cents`. It is a pure integer-cent sum with no rounding."

    A visit with a tankered fuel line (180,000) + MID 3-night RAMP line (45,000) + DE_ICE
    service (104,800) aggregates to 329,800 on depart.

    Design: Corner/calculations/invoice_total_multi_line_aggregation
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"],
                                  visit_overrides={"arrival_utc": "2026-06-14T08:00:00.000Z",
                                                   "departure_utc": "2026-06-17T08:00:00.000Z"})
    # RAMP spot occupied 3 nights, no waiver (tankered fuel does not count toward waiver).
    spot = get_success_data(api.create_parking_spot(
        {"label": "PAD-50", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    assignment = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(visit["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T08:00:00.000Z",
                                          occupy_end_utc="2026-06-17T08:00:00.000Z"), OPS))
    get_success_data(api.occupy_parking_assignment(assignment["id"], occupy_payload(assignment["version"]), OPS))
    # Tankered fuel line 180000.
    create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                             ordered_gallons=6000, tankering=True)
    # DE_ICE service 104800.
    get_success_data(api.start_servicing_service_visit(visit["id"], OPS))
    service = get_success_data(api.create_ramp_service(
        create_deice_service_payload(visit["id"], deice_fluid_gallons=40,
                                     deice_fluid_type="TYPE_IV", deice_holdover_minutes=25), OPS))
    get_success_data(api.start_ramp_service(service["id"], LINE))
    get_success_data(api.complete_ramp_service(service["id"], LINE))

    get_success_data(api.mark_ready_service_visit(visit["id"], OPS))
    get_success_data(api.depart_service_visit(visit["id"], OPS))
    invoice = get_invoice_for_visit(visit["id"])
    assert invoice["total_cents"] == 329_800, (
        f"invoice should aggregate 180000+45000+104800=329800, got {invoice['total_cents']}"
    )
