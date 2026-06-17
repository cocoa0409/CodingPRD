"""Validation check-ordering: state pre-empts business rules; existence pre-empts state.
Also the two cross-entity state-dependency gates (PRD §3.3, §3.6, §3.10).

Difficulty queue (A) instances:
  - priority_pair_validation_conflict / state_beats_business_referential_on_dispatch
  - priority_pair_validation_conflict / existence_beats_state_on_occupy
  - cross_entity_state_dependency / fuel_dispatch_requires_visit_on_ground
  - cross_entity_state_dependency / visit_mark_ready_requires_children_settled
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_servicing_visit,
    create_fueled_fuel_order,
    create_requested_fuel_order,
    create_ramp_service_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
LINE = TEST_USERS["line_manager_headers"]


def test_dispatch_on_fueled_order_with_expired_contract_returns_invalid_state():
    """PRD §3.10: "State eligibility for the requested transition comes next with
    `ERR_INVALID_STATE`."
    PRD §3.6: "Dispatch is permitted only while `logistics_status` is `REQUESTED`, only
    while the parent visit is `ON_GROUND` or `SERVICING`, and only while the chosen
    contract is `ACTIVE` — a dispatch against an `EXPIRED` contract is rejected with
    `ERR_CONTRACT_EXPIRED` (HTTP 422)."

    Dispatching an already-FUELED order (whose contract is now expired) surfaces the
    state error ERR_INVALID_STATE, because state eligibility is checked before the
    contract/product business rules.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_dispatch
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    get_success_data(api.expire_fuel_contract(contract["id"], BILLING))
    res = api.dispatch_fuel_order(order["id"], FUEL)
    validate_error(res, "ERR_INVALID_STATE")


def test_occupy_nonexistent_assignment_returns_not_found_over_state():
    """PRD §3.10: "Existence of every path identifier and body foreign key, resolved
    left to right, comes next with `ERR_NOT_FOUND`. State eligibility for the requested
    transition comes next with `ERR_INVALID_STATE`."
    PRD §2.5: "the first reference that does not resolve to an existing resource causes
    the whole request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business
    rule is evaluated."

    An occupy naming a non-existent assignment id returns ERR_NOT_FOUND, because
    existence is resolved before the state check.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_occupy
    """
    operator, _aircraft, _contract = setup_operator_aircraft_contract()
    res = api.occupy_parking_assignment(
        NON_EXISTENT_UUID, {"expected_assignment_version": 1}, OPS)
    validate_error(res, "ERR_NOT_FOUND")


def test_dispatch_requires_parent_visit_on_ground():
    """PRD §3.6: "Dispatch is permitted only while `logistics_status` is `REQUESTED`,
    only while the parent visit is `ON_GROUND` or `SERVICING`, and only while the chosen
    contract is `ACTIVE`"
    PRD §3.3: "where a downstream operation needs the parent visit to be in a
    servicing-capable state and finds it is not, that operation is rejected with
    `ERR_VISIT_NOT_SERVICEABLE` (HTTP 409)."

    Dispatching a REQUESTED order whose parent visit is still SCHEDULED (never arrived)
    is a downstream fuel-order operation needing a servicing-capable parent visit, so it
    is rejected with ERR_VISIT_NOT_SERVICEABLE; the order stays REQUESTED.

    Design: Difficulty/cross_entity_state_dependency/fuel_dispatch_requires_visit_on_ground
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    # SCHEDULED visit — never arrived.
    visit = get_success_data(api.create_service_visit(
        {"operator_id": operator["id"], "aircraft_id": aircraft["id"],
         "arrival_utc": "2026-06-14T08:00:00.000Z", "departure_utc": "2026-06-15T08:00:00.000Z"}, OPS))
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=False)
    res = api.dispatch_fuel_order(order["id"], FUEL)
    validate_error(res, "ERR_VISIT_NOT_SERVICEABLE")
    order_after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert order_after["logistics_status"] == "REQUESTED"


def test_mark_ready_blocked_while_child_service_outstanding():
    """PRD §3.3: "Marking the stay ready moves it `SERVICING → READY_FOR_DEPARTURE` only
    when the visit is settled: `services_outstanding` must be 0 (every ramp service
    `COMPLETED` or `CANCELLED`) and no fuel order on the visit may still be in `REQUESTED`
    or `DISPATCHED` logistics status."
    PRD §3.3: "Any of these step requests against a visit that is not in the required
    starting state is rejected with `ERR_INVALID_STATE` (HTTP 409)"

    A SERVICING visit with one IN_PROGRESS GPU service (services_outstanding == 1) cannot
    be marked ready; the request is rejected and the visit stays SERVICING.

    Design: Difficulty/cross_entity_state_dependency/visit_mark_ready_requires_children_settled
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-3"})
    service = get_success_data(api.create_ramp_service(
        create_ramp_service_payload(visit["id"], service_type="GPU"), OPS))
    get_success_data(api.start_ramp_service(service["id"], LINE))

    res = api.mark_ready_service_visit(visit["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")
    visit_after = get_success_data(api.get_service_visit(visit["id"], OPS))
    assert visit_after["status"] == "SERVICING"
    assert visit_after["services_outstanding"] == 1
