"""Visit field-work lifecycle, dual-variant charges, parallel billing/execution
dimensions, the inspection rework loop, and cross-entity state guards.

Translates queue A (Difficulty) instances `dual_variant_calc` (visit estimate vs
final), `non_linear_state_machine`, and `cross_entity_state_dependency`, plus
queue B (Corner) `state_machines` side-effect instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_account_payload, create_site_payload, create_contract_payload,
    create_plan_payload, create_crew_payload, create_route_payload,
    create_equipment_payload, create_visit_payload, create_reservation_payload,
    create_inspection_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]
QI = TEST_USERS["quality_inspector_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: visit estimate vs final
# ---------------------------------------------------------------------------
def _setup_visit_with_reservation_started(api, *, slot_duration_minute=90,
                                          window_start_minute=480, window_end_minute=600,
                                          hourly_usage_cost_cents=3000):
    """Active scenario + a visit with a RESERVED reservation, route locked, started.
    Returns (contract, visit_id, asset_id)."""
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"], turf_area_sqft=5000), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    plan = get_success_data(api.create_plan(create_plan_payload(contract["id"], base_rate_cents=10000), AM))
    cver = get_success_data(api.activate_contract(contract["id"], AM))["version"]
    crew = get_success_data(api.create_crew(create_crew_payload(acct["id"], hourly_rate_cents=6000), AM))
    route = get_success_data(api.create_route(create_route_payload(crew["id"]), CL))
    visit = get_success_data(api.create_visit(
        create_visit_payload(plan["id"], route["id"], cver, slot_duration_minute=slot_duration_minute), CL))
    asset = get_success_data(api.create_equipment(
        create_equipment_payload(acct["id"], hourly_usage_cost_cents=hourly_usage_cost_cents), AM))
    get_success_data(api.create_reservation(
        create_reservation_payload(asset["id"], visit["id"],
                                   window_start_minute=window_start_minute,
                                   window_end_minute=window_end_minute), CL))
    get_success_data(api.lock_route(route["id"], CL))
    get_success_data(api.start_visit(visit["id"], CL))
    return contract, visit["id"], asset["id"]


def test_visit_estimate_and_final_diverge_on_actuals_and_equipment(api):
    """PRD §3.5: "The estimate and the final charge are two algorithms over the
    same visit: the estimate uses planned minutes and omits equipment, while the
    final uses actual minutes and adds equipment, so the two diverge whenever
    actual minutes differ from planned or any equipment was reserved."

    Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_diverge_on_actuals_and_equipment
    """
    contract, visit_id, asset_id = _setup_visit_with_reservation_started(api)
    before = get_success_data(api.get_visit(visit_id, AM))
    assert before["estimated_charge_cents"] == 59000
    completed = validate_success(api.complete_visit(visit_id, {"actual_labor_minutes": 120}, CL),
                                 expected_status=200)
    assert completed["estimated_charge_cents"] == 59000
    assert completed["final_charge_cents"] == 68000
    assert completed["final_charge_cents"] != completed["estimated_charge_cents"]


def test_visit_final_charge_adds_equipment_and_actual_labor(api):
    """PRD §3.5: "The actual labor cost is the crew's `hourly_rate_cents` times
    the visit's `actual_labor_minutes` (not the planned minutes), divided by 60,
    rounded up to a whole cent. The equipment cost is the sum of
    `usage_cost_cents` over this visit's equipment reservations whose `status` is
    `RESERVED` or `CONSUMED`".

    Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_diverge_on_actuals_and_equipment
    """
    contract, visit_id, asset_id = _setup_visit_with_reservation_started(api)
    completed = validate_success(api.complete_visit(visit_id, {"actual_labor_minutes": 120}, CL),
                                 expected_status=200)
    # area 50000 + actual labor ceil(6000*120/60)=12000 + equipment ceil(120/60)*3000=6000
    assert completed["final_charge_cents"] == 68000


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: parallel execution/billing dimensions
# ---------------------------------------------------------------------------
def test_invoice_issue_flips_billing_status_while_execution_stays_completed(api):
    """PRD §3.4: "Scheduling carries a parallel pair of independent lifecycles on
    the same visit: an `execution_status` ... and a `billing_status` ... These
    two dimensions evolve on different triggers and never drive each other through
    the execution transitions."
    PRD §3.10: "every swept visit still in `UNBILLED` billing status is moved to
    `INVOICED`".

    Design: Difficulty/non_linear_state_machine/visit_parallel_execution_and_billing_dimensions
    """
    scenario = fixtures.setup_completed_visit(actual_labor_minutes=90, annual_budget_cents=100000000)
    visit_before = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert visit_before["execution_status"] == "COMPLETED"
    assert visit_before["billing_status"] == "UNBILLED"
    invoice = fixtures.create_invoice(scenario["contract"]["id"], "2026-06")
    cver = get_success_data(api.get_contract(scenario["contract"]["id"], AM))["version"]
    issued = validate_success(
        api.issue_invoice(invoice["id"], {"expected_service_contract_version": cver}, AM),
        expected_status=200)
    assert issued["status"] == "ISSUED"
    visit_after = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert visit_after["execution_status"] == "COMPLETED"
    assert visit_after["billing_status"] == "INVOICED"


def test_completed_visit_stays_unbilled_until_invoice_issue(api):
    """PRD §3.4: "On creation, `execution_status` is `SCHEDULED` and
    `billing_status` is `UNBILLED`."
    PRD §3.4: "These two dimensions evolve on different triggers and never drive
    each other through the execution transitions."

    Design: Difficulty/non_linear_state_machine/visit_parallel_execution_and_billing_dimensions
    """
    scenario = fixtures.setup_completed_visit(actual_labor_minutes=90, annual_budget_cents=100000000)
    visit = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert visit["execution_status"] == "COMPLETED"
    assert visit["billing_status"] == "UNBILLED"


def test_inspection_reopen_increments_rework_count_and_returns_pending(api):
    """PRD §3.9: "When an inspection is in `REWORK_REQUIRED`, a `QualityInspector`
    reopens it for re-grading; reopening requires the inspection to be
    `REWORK_REQUIRED` (otherwise `ERR_INSPECTION_NOT_REWORK`), increments its
    `rework_count` by one, and returns it from `REWORK_REQUIRED` to `PENDING`."

    Design: Difficulty/non_linear_state_machine/inspection_cyclic_rework_loop_increments_count
    """
    scenario = fixtures.setup_pending_inspection(actual_labor_minutes=90)
    graded = validate_success(api.grade_inspection(scenario["inspection"]["id"], {"score": 70}, QI),
                              expected_status=200)
    assert graded["status"] == "REWORK_REQUIRED"
    reopened = validate_success(api.reopen_inspection(scenario["inspection"]["id"], QI),
                                expected_status=200)
    assert reopened["status"] == "PENDING"
    assert reopened["rework_count"] == 1


def test_inspection_grade_70_routes_to_rework_required(api):
    """PRD §3.9: "When the `score` is at or above the rework floor but below the
    passing threshold and the inspection's `rework_count` is below the maximum
    rework count, the inspection moves from `PENDING` to `REWORK_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/inspection_cyclic_rework_loop_increments_count
    """
    scenario = fixtures.setup_pending_inspection(actual_labor_minutes=90)
    graded = validate_success(api.grade_inspection(scenario["inspection"]["id"], {"score": 70}, QI),
                              expected_status=200)
    assert graded["status"] == "REWORK_REQUIRED"
    assert graded["rework_count"] == 0


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_visit_start_on_open_route_rejected_route_not_locked(api):
    """PRD §3.5: "Starting requires the visit's `execution_status` to be
    `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`), the parent contract's
    `status` to be `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`), and the visit's
    route to be `LOCKED` (otherwise `ERR_ROUTE_NOT_LOCKED`) — a route must be
    finalized before work begins."

    Design: Difficulty/cross_entity_state_dependency/visit_start_requires_contract_active_and_route_locked
    """
    scenario = fixtures.setup_scheduled_visit()  # route is OPEN, not locked
    resp = api.start_visit(scenario["visit"]["id"], CL)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_LOCKED.value, expected_status=409)


def test_visit_start_succeeds_once_route_locked(api):
    """PRD §3.5: "the visit's route to be `LOCKED` (otherwise
    `ERR_ROUTE_NOT_LOCKED`) — a route must be finalized before work begins.
    Starting moves the visit from `SCHEDULED` to `IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/visit_start_requires_contract_active_and_route_locked
    """
    scenario = fixtures.setup_scheduled_visit()
    get_success_data(api.lock_route(scenario["route"]["id"], CL))
    started = validate_success(api.start_visit(scenario["visit"]["id"], CL), expected_status=200)
    assert started["execution_status"] == "IN_PROGRESS"


def test_grade_inspection_on_in_progress_visit_rejected(api):
    """PRD §3.9: "Grading requires the inspection to be `PENDING` (otherwise
    `ERR_INSPECTION_NOT_PENDING`) and requires the parent visit's
    `execution_status` to be `COMPLETED` (otherwise `ERR_VISIT_NOT_COMPLETED`)."

    Design: Difficulty/cross_entity_state_dependency/inspection_grade_requires_visit_completed
    """
    scenario = fixtures.setup_started_visit()  # visit IN_PROGRESS, not completed
    inspection = get_success_data(api.create_inspection(
        create_inspection_payload(scenario["visit"]["id"]), QI))
    resp = api.grade_inspection(inspection["id"], {"score": 90}, QI)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_COMPLETED.value, expected_status=409)


def test_grade_inspection_succeeds_when_visit_completed(api):
    """PRD §3.9: "When the `score` is at least the passing threshold, the
    inspection moves from `PENDING` to `PASSED`."
    PRD §3.9: "requires the parent visit's `execution_status` to be `COMPLETED`
    (otherwise `ERR_VISIT_NOT_COMPLETED`)."

    Design: Difficulty/cross_entity_state_dependency/inspection_grade_requires_visit_completed
    """
    scenario = fixtures.setup_pending_inspection(actual_labor_minutes=90)
    graded = validate_success(api.grade_inspection(scenario["inspection"]["id"], {"score": 90}, QI),
                              expected_status=200)
    assert graded["status"] == "PASSED"


# ---------------------------------------------------------------------------
# Queue B — state_machines side-effects
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_visit_returns_not_cancellable(api):
    """PRD §3.5: "Cancelling a visit is performed by a `CrewLead` or an
    `AccountManager` and requires the visit to be `SCHEDULED` (otherwise
    `ERR_VISIT_NOT_CANCELLABLE`)."

    Design: Corner/state_machines/cancel_already_cancelled_visit_returns_not_cancellable
    """
    scenario = fixtures.setup_scheduled_visit()
    get_success_data(api.cancel_visit(scenario["visit"]["id"], CL))
    resp = api.cancel_visit(scenario["visit"]["id"], CL)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_CANCELLABLE.value, expected_status=409)


def test_complete_visit_consumes_reserved_equipment(api):
    """PRD §3.5: "As a cross-entity effect, every `RESERVED` equipment reservation
    for this visit is moved to `CONSUMED`, which keeps that reservation's usage
    minutes on its asset."

    Design: Corner/state_machines/complete_visit_consumes_reserved_equipment
    """
    contract, visit_id, asset_id = _setup_visit_with_reservation_started(api)
    # capture the reservation id by listing
    reservations, _ = validate_paginated(
        api.list_reservations(AM, params={"service_visit_id": visit_id}))
    resv_id = reservations[0]["id"]
    validate_success(api.complete_visit(visit_id, {"actual_labor_minutes": 90}, CL), expected_status=200)
    assert get_success_data(api.get_visit(visit_id, AM))["execution_status"] == "COMPLETED"
    assert get_success_data(api.get_reservation(resv_id, AM))["status"] == "CONSUMED"
    assert get_success_data(api.get_equipment(asset_id, AM))["accumulated_usage_minutes"] == 120


def test_failed_inspection_writes_off_visit_billing(api):
    """PRD §3.9: "A failure carries a cross-entity effect: if the parent visit's
    `billing_status` is still `UNBILLED`, it is moved to `WRITTEN_OFF`, so a final
    failed inspection writes off the visit charge and prevents it from being
    invoiced."

    Design: Corner/state_machines/failed_inspection_writes_off_visit_billing
    """
    scenario = fixtures.setup_pending_inspection(actual_labor_minutes=90)
    graded = validate_success(api.grade_inspection(scenario["inspection"]["id"], {"score": 40}, QI),
                              expected_status=200)
    assert graded["status"] == "FAILED"
    visit = get_success_data(api.get_visit(scenario["visit"]["id"], AM))
    assert visit["billing_status"] == "WRITTEN_OFF"
