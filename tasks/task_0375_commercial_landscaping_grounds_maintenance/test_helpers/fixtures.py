"""Composite setup helpers.

These encapsulate the multi-step preambles that most test claims require: an
account, a site, an activated contract with a plan, a crew, a route, and a
scheduled / completed visit. Each helper uses get_success_data() (lenient) so a
setup failure surfaces as a clear "Setup failed" rather than a confusing
assertion failure.

Because the test harness restarts the server (empty database) before every test,
every helper builds its preconditions from scratch using only PRD-declared
endpoints.

All four roles carry opaque identity (PRD §2.1), so the shared role headers in
TEST_USERS are the canonical form for every call.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories


AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]
QI = TEST_USERS["quality_inspector_headers"]
DO = TEST_USERS["dispatch_operator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive creators
# ---------------------------------------------------------------------------
def create_account(**overrides) -> dict:
    resp = api_client.create_account(factories.create_account_payload(**overrides), AM)
    return get_success_data(resp)


def create_site(account_id, **overrides) -> dict:
    resp = api_client.create_site(factories.create_site_payload(account_id, **overrides), AM)
    return get_success_data(resp)


def create_contract(account_id, site_id, **overrides) -> dict:
    resp = api_client.create_contract(
        factories.create_contract_payload(account_id, site_id, **overrides), AM
    )
    return get_success_data(resp)


def create_plan(contract_id, **overrides) -> dict:
    resp = api_client.create_plan(factories.create_plan_payload(contract_id, **overrides), AM)
    return get_success_data(resp)


def create_crew(account_id, **overrides) -> dict:
    resp = api_client.create_crew(factories.create_crew_payload(account_id, **overrides), AM)
    return get_success_data(resp)


def create_route(crew_id, **overrides) -> dict:
    resp = api_client.create_route(factories.create_route_payload(crew_id, **overrides), CL)
    return get_success_data(resp)


def create_equipment(account_id, **overrides) -> dict:
    resp = api_client.create_equipment(factories.create_equipment_payload(account_id, **overrides), AM)
    return get_success_data(resp)


def activate_contract(contract_id) -> dict:
    return get_success_data(api_client.activate_contract(contract_id, AM))


def get_contract_version(contract_id) -> int:
    data = get_success_data(api_client.get_contract(contract_id, AM))
    return data["version"]


# ---------------------------------------------------------------------------
# Tier 2: an active contract scenario (account/site/active contract/plan/crew/route)
# ---------------------------------------------------------------------------
def setup_active_contract_scenario(
    *,
    turf_area_sqft=5000,
    base_rate_cents=10000,
    hourly_rate_cents=6000,
    annual_budget_cents=100000000,
    service_type="MOWING",
    frequency="WEEKLY",
    snow_zone=None,
    shift_start_minute=400,
    shift_end_minute=800,
    route_date="2026-06-01",
) -> dict:
    """Account + site + ACTIVE contract + plan + crew + OPEN route.

    Returns a dict with keys: account, site, contract, plan, crew, route,
    contract_version (the contract version AFTER activation).
    """
    account = create_account()
    site_overrides = {"turf_area_sqft": turf_area_sqft}
    if snow_zone is not None:
        site_overrides["snow_zone"] = snow_zone
    site = create_site(account["id"], **site_overrides)
    contract = create_contract(
        account["id"], site["id"], annual_budget_cents=annual_budget_cents
    )
    plan = create_plan(
        contract["id"], service_type=service_type, frequency=frequency, base_rate_cents=base_rate_cents
    )
    activate_contract(contract["id"])
    contract_version = get_contract_version(contract["id"])
    crew = create_crew(account["id"], hourly_rate_cents=hourly_rate_cents)
    route = create_route(
        crew["id"],
        route_date=route_date,
        shift_start_minute=shift_start_minute,
        shift_end_minute=shift_end_minute,
    )
    return {
        "account": account,
        "site": site,
        "contract": contract,
        "plan": plan,
        "crew": crew,
        "route": route,
        "contract_version": contract_version,
    }


def schedule_visit(scenario, *, slot_start_minute=480, slot_duration_minute=90, contract_version=None) -> dict:
    """Place a visit on the scenario's route; refreshes the contract version
    automatically when not supplied. Returns the created visit dict."""
    if contract_version is None:
        contract_version = get_contract_version(scenario["contract"]["id"])
    resp = api_client.create_visit(
        factories.create_visit_payload(
            scenario["plan"]["id"],
            scenario["route"]["id"],
            contract_version,
            slot_start_minute=slot_start_minute,
            slot_duration_minute=slot_duration_minute,
        ),
        CL,
    )
    return get_success_data(resp)


def lock_route(route_id) -> dict:
    return get_success_data(api_client.lock_route(route_id, CL))


def start_visit(visit_id) -> dict:
    return get_success_data(api_client.start_visit(visit_id, CL))


def complete_visit(visit_id, actual_labor_minutes) -> dict:
    return get_success_data(
        api_client.complete_visit(visit_id, {"actual_labor_minutes": actual_labor_minutes}, CL)
    )


# ---------------------------------------------------------------------------
# Tier 3: visit-lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_scheduled_visit(*, slot_start_minute=480, slot_duration_minute=90, **scenario_kwargs) -> dict:
    """Active scenario + one SCHEDULED visit on an OPEN route.
    Returns the scenario dict augmented with key 'visit'."""
    scenario = setup_active_contract_scenario(**scenario_kwargs)
    visit = schedule_visit(
        scenario,
        slot_start_minute=slot_start_minute,
        slot_duration_minute=slot_duration_minute,
        contract_version=scenario["contract_version"],
    )
    scenario["visit"] = visit
    return scenario


def setup_started_visit(*, slot_start_minute=480, slot_duration_minute=90, **scenario_kwargs) -> dict:
    """Active scenario + a visit moved to IN_PROGRESS (route locked, visit started).
    Returns the scenario dict augmented with key 'visit'."""
    scenario = setup_scheduled_visit(
        slot_start_minute=slot_start_minute, slot_duration_minute=slot_duration_minute, **scenario_kwargs
    )
    lock_route(scenario["route"]["id"])
    scenario["visit"] = start_visit(scenario["visit"]["id"])
    return scenario


def setup_completed_visit(
    *, actual_labor_minutes=90, slot_start_minute=480, slot_duration_minute=90, **scenario_kwargs
) -> dict:
    """Active scenario + a visit completed with the given actual_labor_minutes.
    Returns the scenario dict augmented with key 'visit'."""
    scenario = setup_started_visit(
        slot_start_minute=slot_start_minute, slot_duration_minute=slot_duration_minute, **scenario_kwargs
    )
    scenario["visit"] = complete_visit(scenario["visit"]["id"], actual_labor_minutes)
    return scenario


def reserve_equipment(asset_id, visit_id, *, window_start_minute=480, window_end_minute=600) -> dict:
    resp = api_client.create_reservation(
        factories.create_reservation_payload(
            asset_id, visit_id, window_start_minute=window_start_minute, window_end_minute=window_end_minute
        ),
        CL,
    )
    return get_success_data(resp)


def setup_visit_with_reservation(
    *,
    asset_hourly_usage_cost_cents=3000,
    asset_service_interval_hours=100,
    window_start_minute=480,
    window_end_minute=600,
    **scenario_kwargs,
) -> dict:
    """Active scenario + SCHEDULED visit + an equipment asset + one RESERVED
    reservation on it. Returns the scenario dict augmented with keys 'visit',
    'asset', 'reservation'."""
    scenario = setup_scheduled_visit(**scenario_kwargs)
    asset = create_equipment(
        scenario["account"]["id"],
        hourly_usage_cost_cents=asset_hourly_usage_cost_cents,
        service_interval_hours=asset_service_interval_hours,
    )
    reservation = reserve_equipment(
        asset["id"],
        scenario["visit"]["id"],
        window_start_minute=window_start_minute,
        window_end_minute=window_end_minute,
    )
    scenario["asset"] = asset
    scenario["reservation"] = reservation
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: inspection setup
# ---------------------------------------------------------------------------
def open_inspection(visit_id) -> dict:
    return get_success_data(api_client.create_inspection({"service_visit_id": visit_id}, QI))


def grade_inspection(inspection_id, score) -> dict:
    return get_success_data(api_client.grade_inspection(inspection_id, {"score": score}, QI))


def setup_pending_inspection(*, actual_labor_minutes=90, **scenario_kwargs) -> dict:
    """Active scenario + completed visit + a PENDING inspection on it.
    Returns the scenario dict augmented with keys 'visit', 'inspection'."""
    scenario = setup_completed_visit(actual_labor_minutes=actual_labor_minutes, **scenario_kwargs)
    scenario["inspection"] = open_inspection(scenario["visit"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: storm-event setup
# ---------------------------------------------------------------------------
def create_storm_event(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_storm_event(factories.create_storm_event_payload(site_id, **overrides), DO)
    )


def setup_reported_storm_event(*, snow_zone="STANDARD", snowfall_inches=5, certified_crews=None) -> dict:
    """Account + site (given snow_zone) + crews + a REPORTED storm event.

    certified_crews is a list of dicts of crew overrides (e.g.
    [{"hourly_rate_cents": 4000, "certified_for_snow": True}, ...]); each becomes
    a crew on the account in order. Returns a dict with keys account, site,
    crews (list, in creation order), event.
    """
    account = create_account()
    site = create_site(account["id"], snow_zone=snow_zone, turf_area_sqft=4000, name="HQ", address="9 Oak")
    crews = []
    if certified_crews:
        for i, overrides in enumerate(certified_crews):
            crews.append(create_crew(account["id"], name=f"Crew {i}", **overrides))
    event = create_storm_event(site["id"], snowfall_inches=snowfall_inches)
    return {"account": account, "site": site, "crews": crews, "event": event}


# ---------------------------------------------------------------------------
# Tier 6: invoice setup
# ---------------------------------------------------------------------------
def create_invoice(contract_id, period_label) -> dict:
    return get_success_data(
        api_client.create_invoice(factories.create_invoice_payload(contract_id, period_label), AM)
    )


def setup_draft_invoice_from_completed_visit(
    *,
    annual_budget_cents=100000000,
    actual_labor_minutes=90,
    reservation=False,
    window_start_minute=480,
    window_end_minute=600,
    period_label="2026-06",
) -> dict:
    """Active scenario + one COMPLETED visit (optionally with a consumed
    reservation) + a DRAFT invoice that swept it.

    Returns a dict with keys account, site, contract, plan, crew, route, visit,
    invoice, and (if reservation) asset, reservation.
    """
    scenario = setup_started_visit(annual_budget_cents=annual_budget_cents)
    if reservation:
        asset = create_equipment(scenario["account"]["id"])
        # The visit is already IN_PROGRESS; reserve before completion so the
        # reservation is CONSUMED and its usage cost enters the final charge.
        # Re-create the reservation against the in-progress visit.
        resv = reserve_equipment(
            asset["id"],
            scenario["visit"]["id"],
            window_start_minute=window_start_minute,
            window_end_minute=window_end_minute,
        )
        scenario["asset"] = asset
        scenario["reservation"] = resv
    scenario["visit"] = complete_visit(scenario["visit"]["id"], actual_labor_minutes)
    scenario["invoice"] = create_invoice(scenario["contract"]["id"], period_label)
    return scenario
