"""Contract lifecycle, the suspend/terminate cascade, and compensating invariants.

Translates queue B (Corner) `state_machines` contract instances and queue A
(Difficulty) `transitive_cascade` + `compensating_invariant` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_account_payload, create_site_payload, create_contract_payload,
    create_plan_payload, create_crew_payload, create_route_payload,
    create_equipment_payload, create_visit_payload, create_reservation_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]


# ---------------------------------------------------------------------------
# Queue B — state_machines (contract transitions)
# ---------------------------------------------------------------------------
def test_new_contract_initial_state_is_draft(api):
    """PRD §3.2: "On creation, the contract's `status` is `DRAFT`, its
    `committed_cents` is 0, and its `budget_remaining_cents` equals
    `annual_budget_cents`."

    Design: Corner/state_machines/new_contract_initial_state_is_draft
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    resp = api.create_contract(create_contract_payload(acct["id"], site["id"]), AM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"


def test_activate_contract_with_no_plan_returns_no_plan_defined(api):
    """PRD §3.2: "activation requires the contract to be in `DRAFT` (otherwise
    `ERR_CONTRACT_NOT_DRAFT`) and requires at least one `ServicePlan` to exist
    under the contract (otherwise `ERR_NO_PLAN_DEFINED`)".

    Design: Corner/state_machines/activate_contract_with_no_plan_returns_no_plan_defined
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    resp = api.activate_contract(contract["id"], AM)
    validate_error(resp, ApiErrorId.ERR_NO_PLAN_DEFINED.value, expected_status=409)


def test_terminated_contract_cannot_be_reactivated(api):
    """PRD §3.2: "reactivation requires the contract to be in `SUSPENDED`
    (otherwise `ERR_CONTRACT_NOT_SUSPENDED`), moving it from `SUSPENDED` back to
    `ACTIVE`".
    PRD §3.2: "A `TERMINATED` contract is terminal and is the only contract state
    from which no further transitions are possible."

    Design: Corner/state_machines/terminate_contract_is_terminal_no_reactivation
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    get_success_data(api.activate_contract(contract["id"], AM))
    get_success_data(api.terminate_contract(contract["id"], AM))
    resp = api.activate_contract(contract["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_SUSPENDED.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade
# ---------------------------------------------------------------------------
def _scenario_with_reserved_visit(api):
    """Account/site/ACTIVE contract/plan/crew/OPEN route; a SCHEDULED visit
    (slot 90) with a RESERVED reservation [480,600] (120 min) on an asset whose
    accumulated_usage_minutes is then 120. Returns ids needed by cascade tests."""
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"], turf_area_sqft=5000), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    plan = get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    cver = get_success_data(api.activate_contract(contract["id"], AM))["version"]
    crew = get_success_data(api.create_crew(create_crew_payload(acct["id"]), AM))
    route = get_success_data(api.create_route(create_route_payload(crew["id"]), CL))
    visit = get_success_data(api.create_visit(
        create_visit_payload(plan["id"], route["id"], cver), CL))
    asset = get_success_data(api.create_equipment(create_equipment_payload(acct["id"]), AM))
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(asset["id"], visit["id"], window_start_minute=480, window_end_minute=600), CL))
    return contract, route, visit, asset, resv


def test_contract_suspend_cascades_visit_reservation_asset_depth3(api):
    """PRD §3.2: "Suspension carries a cascade: every `SCHEDULED` visit whose
    plan belongs to this contract is moved to `CANCELLED`; each such cancelled
    visit decrements its route's `booked_minutes` by that visit's
    `slot_duration_minute`, and each of that visit's `RESERVED` equipment
    reservations is moved to `RELEASED`, with each released reservation
    subtracting its `reserved_minutes` from its asset's
    `accumulated_usage_minutes`."

    Design: Difficulty/transitive_cascade/contract_suspend_cascade_visit_reservation_asset_depth3
    """
    contract, route, visit, asset, resv = _scenario_with_reserved_visit(api)
    suspend = api.suspend_contract(contract["id"], AM)
    validate_success(suspend, expected_status=200)
    assert get_success_data(api.get_contract(contract["id"], AM))["status"] == "SUSPENDED"
    assert get_success_data(api.get_visit(visit["id"], AM))["execution_status"] == "CANCELLED"
    assert get_success_data(api.get_reservation(resv["id"], AM))["status"] == "RELEASED"
    assert get_success_data(api.get_equipment(asset["id"], AM))["accumulated_usage_minutes"] == 0
    assert get_success_data(api.get_route(route["id"], AM))["booked_minutes"] == 0


def test_suspend_cascade_releases_route_minutes_to_zero(api):
    """PRD §3.2: "each such cancelled visit decrements its route's
    `booked_minutes` by that visit's `slot_duration_minute`".

    Design: Difficulty/transitive_cascade/contract_suspend_cascade_visit_reservation_asset_depth3
    """
    contract, route, visit, asset, resv = _scenario_with_reserved_visit(api)
    # before suspend the route holds the visit's 90 booked minutes
    assert get_success_data(api.get_route(route["id"], AM))["booked_minutes"] == 90
    validate_success(api.suspend_contract(contract["id"], AM), expected_status=200)
    assert get_success_data(api.get_route(route["id"], AM))["booked_minutes"] == 0


def test_addon_approve_cascades_visit_estimate_and_contract_committed(api):
    """PRD §3.6: "a two-hop cascade fires: the parent visit's
    `estimated_charge_cents` is recomputed to include this add-on, and the owning
    contract's `committed_cents` is then reconciled."

    Design: Difficulty/transitive_cascade/addon_approve_cascade_visit_estimate_contract_committed_depth2
    """
    scenario = fixtures.setup_scheduled_visit(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000
    )
    addon = get_success_data(api.create_addon(
        {"service_visit_id": scenario["visit"]["id"], "addon_type": "IRRIGATION_TUNEUP",
         "quantity": 20, "unit_price_cents": 1000}, CL))
    approve = api.approve_addon(addon["id"], AM)
    approved = validate_success(approve, expected_status=200)
    # bucket1 = 10*1000 = 10000; bucket2 = round(10*1000*0.9) = 9000 -> 19000
    assert approved["addon_charge_cents"] == 19000
    visit = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert visit["estimated_charge_cents"] == 78000  # 59000 + 19000
    contract = get_success_data(api.get_contract(scenario["contract"]["id"], AM))
    assert contract["committed_cents"] == 78000


def test_addon_approve_recomputes_visit_estimate(api):
    """PRD §3.4: "The estimate is a provisional figure computed from planned
    inputs at scheduling time, and recomputed whenever an add-on on this visit is
    approved."

    Design: Difficulty/transitive_cascade/addon_approve_cascade_visit_estimate_contract_committed_depth2
    """
    scenario = fixtures.setup_scheduled_visit(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000
    )
    before = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert before["estimated_charge_cents"] == 59000
    addon = get_success_data(api.create_addon(
        {"service_visit_id": scenario["visit"]["id"], "addon_type": "IRRIGATION_TUNEUP",
         "quantity": 20, "unit_price_cents": 1000}, CL))
    get_success_data(api.approve_addon(addon["id"], AM))
    after = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert after["estimated_charge_cents"] == 78000


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant
# ---------------------------------------------------------------------------
def test_cancel_visit_restores_route_booked_minutes_and_committed(api):
    """PRD §3.5: "Cancellation moves the visit's `execution_status` to the
    terminal `CANCELLED` state and performs a three-hop compensating release: the
    route's `booked_minutes` is decreased by the visit's `slot_duration_minute`".
    PRD §3.2: "Cancelled visits contribute nothing, which is what makes a cancel
    and an un-cancel conserve the running total exactly."

    Design: Difficulty/compensating_invariant/cancel_visit_restores_route_booked_minutes
    """
    scenario = fixtures.setup_scheduled_visit(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000
    )
    assert get_success_data(api.get_route(scenario["route"]["id"], AM))["booked_minutes"] == 90
    cancel = api.cancel_visit(scenario["visit"]["id"], CL)
    cancelled = validate_success(cancel, expected_status=200)
    assert cancelled["execution_status"] == "CANCELLED"
    assert get_success_data(api.get_route(scenario["route"]["id"], AM))["booked_minutes"] == 0
    assert get_success_data(api.get_contract(scenario["contract"]["id"], AM))["committed_cents"] == 0


def test_cancel_visit_returns_committed_cents_to_zero(api):
    """PRD §3.5: "The contract's `committed_cents` is then reconciled, dropping
    this visit's contribution."

    Design: Difficulty/compensating_invariant/cancel_visit_restores_route_booked_minutes
    """
    scenario = fixtures.setup_scheduled_visit(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000
    )
    assert get_success_data(api.get_contract(scenario["contract"]["id"], AM))["committed_cents"] == 59000
    validate_success(api.cancel_visit(scenario["visit"]["id"], CL), expected_status=200)
    assert get_success_data(api.get_contract(scenario["contract"]["id"], AM))["committed_cents"] == 0


def test_release_reservation_restores_asset_usage_minutes(api):
    """PRD §3.7: "release a reservation, which requires it to be `RESERVED`
    (otherwise `ERR_RESERVATION_NOT_RESERVED`), moves its `status` to the terminal
    `RELEASED` state, and subtracts its `reserved_minutes` from the asset's
    `accumulated_usage_minutes`, returning the conserved usage pool."

    Design: Difficulty/compensating_invariant/release_reservation_restores_asset_usage_minutes
    """
    scenario = fixtures.setup_visit_with_reservation(window_start_minute=480, window_end_minute=600)
    assert get_success_data(api.get_equipment(scenario["asset"]["id"], AM))["accumulated_usage_minutes"] == 120
    release = api.release_reservation(scenario["reservation"]["id"], CL)
    released = validate_success(release, expected_status=200)
    assert released["status"] == "RELEASED"
    assert get_success_data(api.get_equipment(scenario["asset"]["id"], AM))["accumulated_usage_minutes"] == 0


def test_release_reservation_moves_to_released_state(api):
    """PRD §3.7: "release a reservation ... moves its `status` to the terminal
    `RELEASED` state, and subtracts its `reserved_minutes` from the asset's
    `accumulated_usage_minutes`, returning the conserved usage pool."

    Design: Difficulty/compensating_invariant/release_reservation_restores_asset_usage_minutes
    """
    scenario = fixtures.setup_visit_with_reservation(window_start_minute=480, window_end_minute=600)
    released = validate_success(api.release_reservation(scenario["reservation"]["id"], CL), expected_status=200)
    assert released["status"] == "RELEASED"
    assert get_success_data(api.get_equipment(scenario["asset"]["id"], AM))["accumulated_usage_minutes"] == 0
