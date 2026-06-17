"""Temporal-overlap rules, cross-account integrity, capacity guards, and the
state-over-temporal validation-priority pair.

Translates queue A (Difficulty) `resource_temporal_overlap` and
`priority_pair_validation_conflict` (route-locked) instances, plus queue B
(Corner) `validations` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_account_payload, create_site_payload, create_contract_payload,
    create_plan_payload, create_crew_payload, create_route_payload,
    create_equipment_payload, create_visit_payload, create_reservation_payload,
    create_invoice_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_visit_slot_halfopen_adjacency_allowed(api):
    """PRD §3.4: "the requested slot must lie entirely within the route shift
    window and must not overlap, under half-open interval semantics, any
    non-`CANCELLED` visit already on the same route; a slot ending exactly where
    another begins is adjacency and is allowed".

    Design: Difficulty/resource_temporal_overlap/visit_slot_halfopen_adjacency_allowed
    """
    scenario = fixtures.setup_active_contract_scenario()
    # first visit occupies [480,570)
    fixtures.schedule_visit(scenario, slot_start_minute=480, slot_duration_minute=90,
                            contract_version=scenario["contract_version"])
    cver2 = fixtures.get_contract_version(scenario["contract"]["id"])
    # adjacent [570,660) — end==start of the gap, allowed
    resp = api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver2,
                             slot_start_minute=570, slot_duration_minute=90), CL)
    validate_success(resp, expected_status=201)
    assert get_success_data(api.get_route(scenario["route"]["id"], AM))["booked_minutes"] == 180


def test_visit_slot_true_overlap_rejected(api):
    """PRD §3.4: "any true overlap or a slot extending outside the shift window is
    rejected with `ERR_VISIT_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/visit_slot_halfopen_adjacency_allowed
    """
    scenario = fixtures.setup_active_contract_scenario()
    fixtures.schedule_visit(scenario, slot_start_minute=480, slot_duration_minute=90,
                            contract_version=scenario["contract_version"])
    cver2 = fixtures.get_contract_version(scenario["contract"]["id"])
    # [500,590) truly overlaps [480,570)
    resp = api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver2,
                             slot_start_minute=500, slot_duration_minute=90), CL)
    validate_error(resp, ApiErrorId.ERR_VISIT_SLOT_CONFLICT.value, expected_status=409)


def _scenario_with_reserved_asset(api, *, window_start_minute=480, window_end_minute=600):
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    plan = get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    cver = get_success_data(api.activate_contract(contract["id"], AM))["version"]
    crew = get_success_data(api.create_crew(create_crew_payload(acct["id"]), AM))
    route = get_success_data(api.create_route(create_route_payload(crew["id"]), CL))
    visit = get_success_data(api.create_visit(create_visit_payload(plan["id"], route["id"], cver), CL))
    asset = get_success_data(api.create_equipment(create_equipment_payload(acct["id"]), AM))
    get_success_data(api.create_reservation(
        create_reservation_payload(asset["id"], visit["id"],
                                   window_start_minute=window_start_minute,
                                   window_end_minute=window_end_minute), CL))
    return asset, visit


def test_equipment_reservation_closed_adjacency_rejected(api):
    """PRD §3.7: "The reservation window, treated as a **closed** interval from
    `window_start_minute` through `window_end_minute` inclusive, must not overlap
    any non-`RELEASED` reservation on the same asset; because the interval is
    closed, two reservations that merely touch at an endpoint do collide, and the
    conflict is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED`".

    Design: Difficulty/resource_temporal_overlap/equipment_reservation_closed_adjacency_rejected
    """
    asset, visit = _scenario_with_reserved_asset(api, window_start_minute=480, window_end_minute=600)
    # [600,720] touches [480,600] at 600 -> collides under closed semantics
    resp = api.create_reservation(
        create_reservation_payload(asset["id"], visit["id"],
                                   window_start_minute=600, window_end_minute=720), CL)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_DOUBLE_BOOKED.value, expected_status=409)


def test_equipment_reservation_non_touching_window_allowed(api):
    """PRD §3.7: "two reservations that merely touch at an endpoint do collide ...
    — the opposite adjacency rule from the half-open visit-slot check."

    Design: Difficulty/resource_temporal_overlap/equipment_reservation_closed_adjacency_rejected
    """
    asset, visit = _scenario_with_reserved_asset(api, window_start_minute=480, window_end_minute=600)
    # [601,720] does not touch [480,600] -> allowed
    resp = api.create_reservation(
        create_reservation_payload(asset["id"], visit["id"],
                                   window_start_minute=601, window_end_minute=720), CL)
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict (route-locked state beats temporal)
# ---------------------------------------------------------------------------
def test_visit_create_on_locked_route_returns_route_not_open(api):
    """PRD §3.4: "the target route's `status` must be `OPEN` (otherwise
    `ERR_ROUTE_NOT_OPEN`)".
    PRD §3.4: "the requested slot must lie entirely within the route shift window
    and must not overlap, under half-open interval semantics, any non-`CANCELLED`
    visit already on the same route".

    Design: Difficulty/priority_pair_validation_conflict/route_locked_state_beats_temporal_overlap_on_visit
    """
    scenario = fixtures.setup_active_contract_scenario()
    # one SCHEDULED visit at [480,570)
    fixtures.schedule_visit(scenario, slot_start_minute=480, slot_duration_minute=90,
                            contract_version=scenario["contract_version"])
    cver2 = fixtures.get_contract_version(scenario["contract"]["id"])
    get_success_data(api.lock_route(scenario["route"]["id"], CL))  # does NOT cancel the visit
    # new visit overlaps the existing one AND the route is now LOCKED;
    # the route-state error takes precedence over the temporal conflict.
    resp = api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver2,
                             slot_start_minute=480, slot_duration_minute=90), CL)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_OPEN.value, expected_status=409)


def test_overlapping_slot_on_open_route_returns_slot_conflict(api):
    """PRD §3.4: "the requested slot ... must not overlap, under half-open
    interval semantics, any non-`CANCELLED` visit already on the same route; ...
    any true overlap or a slot extending outside the shift window is rejected with
    `ERR_VISIT_SLOT_CONFLICT`."
    PRD §3.4: "the target route's `status` must be `OPEN` (otherwise
    `ERR_ROUTE_NOT_OPEN`)".

    Design: Difficulty/priority_pair_validation_conflict/route_locked_state_beats_temporal_overlap_on_visit
    """
    scenario = fixtures.setup_active_contract_scenario()
    fixtures.schedule_visit(scenario, slot_start_minute=480, slot_duration_minute=90,
                            contract_version=scenario["contract_version"])
    cver2 = fixtures.get_contract_version(scenario["contract"]["id"])
    # route still OPEN: the temporal overlap is now the binding failure
    resp = api.create_visit(
        create_visit_payload(scenario["plan"]["id"], scenario["route"]["id"], cver2,
                             slot_start_minute=480, slot_duration_minute=90), CL)
    validate_error(resp, ApiErrorId.ERR_VISIT_SLOT_CONFLICT.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue B — validations
# ---------------------------------------------------------------------------
def test_reservation_service_interval_exact_equal_allowed(api):
    """PRD §3.7: "the reservation is rejected with `ERR_SERVICE_INTERVAL_EXCEEDED`
    when the asset's `accumulated_usage_minutes` plus the new `reserved_minutes`
    would *strictly* exceed the asset's `service_interval_hours` multiplied by 60;
    reaching exactly the interval is allowed, and only a strict excess is
    rejected."

    Design: Corner/validations/reservation_service_interval_exact_equal_allowed
    """
    scenario = fixtures.setup_scheduled_visit()
    asset = get_success_data(api.create_equipment(
        create_equipment_payload(scenario["account"]["id"], service_interval_hours=2), AM))
    # 120-minute window brings accumulated usage to exactly 120 (== 2*60 cap)
    resp = api.create_reservation(
        create_reservation_payload(asset["id"], scenario["visit"]["id"],
                                   window_start_minute=480, window_end_minute=600), CL)
    validate_success(resp, expected_status=201)
    assert get_success_data(api.get_equipment(asset["id"], AM))["accumulated_usage_minutes"] == 120


def test_reservation_service_interval_exceeded_rejected(api):
    """PRD §3.7: "the reservation is rejected with `ERR_SERVICE_INTERVAL_EXCEEDED`
    when the asset's `accumulated_usage_minutes` plus the new `reserved_minutes`
    would *strictly* exceed the asset's `service_interval_hours` multiplied by 60".

    Design: Corner/validations/reservation_service_interval_exceeded_rejected
    """
    scenario = fixtures.setup_scheduled_visit()
    asset = get_success_data(api.create_equipment(
        create_equipment_payload(scenario["account"]["id"], service_interval_hours=2), AM))
    # 121-minute window would push usage to 121 (> 120 cap)
    resp = api.create_reservation(
        create_reservation_payload(asset["id"], scenario["visit"]["id"],
                                   window_start_minute=480, window_end_minute=601), CL)
    validate_error(resp, ApiErrorId.ERR_SERVICE_INTERVAL_EXCEEDED.value, expected_status=409)


def test_schedule_visit_on_paused_plan_rejected(api):
    """PRD §3.4: "the parent plan's `status` must be `ACTIVE` (otherwise
    `ERR_PLAN_PAUSED`)".

    Design: Corner/validations/schedule_visit_on_paused_plan_rejected
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    plan = get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    cver = get_success_data(api.activate_contract(contract["id"], AM))["version"]
    get_success_data(api.pause_plan(plan["id"], AM))
    crew = get_success_data(api.create_crew(create_crew_payload(acct["id"]), AM))
    route = get_success_data(api.create_route(create_route_payload(crew["id"]), CL))
    resp = api.create_visit(create_visit_payload(plan["id"], route["id"], cver), CL)
    validate_error(resp, ApiErrorId.ERR_PLAN_PAUSED.value, expected_status=409)


def test_duplicate_invoice_period_label_rejected(api):
    """PRD §3.10: "The `period_label` must be unique among the non-`VOID` invoices
    of the same contract; a collision is rejected with
    `ERR_DUPLICATE_PERIOD_LABEL`."

    Design: Corner/validations/duplicate_invoice_period_label_rejected
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    get_success_data(api.activate_contract(contract["id"], AM))
    get_success_data(api.create_invoice(create_invoice_payload(contract["id"], "2026-06"), AM))
    resp = api.create_invoice(create_invoice_payload(contract["id"], "2026-06"), AM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD_LABEL.value, expected_status=409)


def test_cross_account_reservation_rejected(api):
    """PRD §3.7: "The asset and the visit must share a single
    `service_account_id`, or the request is rejected with
    `ERR_CROSS_ACCOUNT_REFERENCE`."

    Design: Corner/validations/cross_account_reservation_rejected
    """
    # Account A with a SCHEDULED visit
    acctA = get_success_data(api.create_account(create_account_payload(name="Account A"), AM))
    siteA = get_success_data(api.create_site(create_site_payload(acctA["id"]), AM))
    contractA = get_success_data(api.create_contract(create_contract_payload(acctA["id"], siteA["id"]), AM))
    planA = get_success_data(api.create_plan(create_plan_payload(contractA["id"]), AM))
    cverA = get_success_data(api.activate_contract(contractA["id"], AM))["version"]
    crewA = get_success_data(api.create_crew(create_crew_payload(acctA["id"]), AM))
    routeA = get_success_data(api.create_route(create_route_payload(crewA["id"]), CL))
    visitA = get_success_data(api.create_visit(create_visit_payload(planA["id"], routeA["id"], cverA), CL))
    # Account B with its own equipment asset
    acctB = get_success_data(api.create_account(create_account_payload(name="Account B", region_code="SE"), AM))
    assetB = get_success_data(api.create_equipment(create_equipment_payload(acctB["id"], name="Mower B"), AM))
    resp = api.create_reservation(
        create_reservation_payload(assetB["id"], visitA["id"],
                                   window_start_minute=480, window_end_minute=600), CL)
    validate_error(resp, ApiErrorId.ERR_CROSS_ACCOUNT_REFERENCE.value, expected_status=409)
