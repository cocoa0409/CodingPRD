"""Composite setup helpers.

Each helper builds all preconditions from scratch (the server restarts before every
test, so every test begins against an empty database) using only PRD-declared endpoints.
All setup calls use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing downstream assertion.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_program_admin_headers,
    make_route_manager_headers,
    make_intake_coordinator_headers,
    make_nutritionist_headers,
    make_contribution_clerk_headers,
    make_volunteer_driver_headers,
)
from . import factories as f

# Shared header constants (opaque roles).
ADMIN = TEST_USERS["program_admin_headers"]
ROUTE_MGR = TEST_USERS["route_manager_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
NUTRITION = TEST_USERS["nutritionist_headers"]
CLERK = TEST_USERS["contribution_clerk_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def get_client_version(api, client_id) -> int:
    """Read the client's current version (needed for OCC-guarded writes)."""
    return get_success_data(api.get_client(client_id, ROUTE_MGR))["version"]


def create_active_driver(api, full_name="Dana Driver", phone="555-0100") -> dict:
    """Register a driver and activate it (PENDING -> ACTIVE). Returns the ACTIVE driver."""
    drv = get_success_data(api.create_driver(f.create_driver_payload(full_name=full_name, phone=phone), ADMIN))
    return get_success_data(api.activate_driver(drv["id"], ADMIN))


def create_route(api, zone="Z1", service_days=None, max_meals_per_run=50, name="R1") -> dict:
    """Create a DRAFT route (no driver)."""
    payload = f.create_route_payload(
        name=name, zone=zone,
        service_days=service_days or ["MON", "WED", "FRI"],
        max_meals_per_run=max_meals_per_run,
    )
    return get_success_data(api.create_route(payload, ROUTE_MGR))


def create_active_route(api, driver_id=None, zone="Z1", service_days=None,
                        max_meals_per_run=50, name="R1") -> dict:
    """Create a route, assign an ACTIVE driver, and activate the route.

    Returns {"route": <ACTIVE route>, "driver": <ACTIVE driver>}. If driver_id is
    None a fresh ACTIVE driver is created and returned.
    """
    if driver_id is None:
        driver = create_active_driver(api)
        driver_id = driver["id"]
    else:
        driver = None
    route = create_route(api, zone=zone, service_days=service_days,
                         max_meals_per_run=max_meals_per_run, name=name)
    get_success_data(api.assign_driver(route["id"], f.assign_driver_payload(driver_id), ROUTE_MGR))
    route = get_success_data(api.activate_route(route["id"], ROUTE_MGR))
    return {"route": route, "driver": driver}


def intake_client(api, **overrides) -> dict:
    """Create an INTAKE client."""
    return get_success_data(api.create_client(f.create_client_payload(**overrides), INTAKE))


def create_finalized_assessment(api, client_id, **assessment_overrides) -> dict:
    """Create a DRAFT assessment for the client and finalize it (-> FINALIZED)."""
    a = get_success_data(api.create_assessment(client_id, f.create_assessment_payload(**assessment_overrides), NUTRITION))
    return get_success_data(api.finalize_assessment(a["id"], NUTRITION))


def create_assessed_client(api, client_overrides=None, assessment_overrides=None) -> dict:
    """Client with one FINALIZED assessment => client advances INTAKE -> ASSESSED.

    Returns {"client": <ASSESSED client, refreshed>, "assessment": <FINALIZED assessment>}.
    """
    client = intake_client(api, **(client_overrides or {}))
    assessment = create_finalized_assessment(api, client["id"], **(assessment_overrides or {}))
    client = get_success_data(api.get_client(client["id"], INTAKE))
    return {"client": client, "assessment": assessment}


def create_meal_plan_for(api, client_id, assessment_id, route_id, **plan_overrides) -> dict:
    """Create an ACTIVE meal plan against the client (OCC version read fresh)."""
    version = get_client_version(api, client_id)
    payload = f.create_meal_plan_payload(assessment_id, route_id, version, **plan_overrides)
    return get_success_data(api.create_meal_plan(client_id, payload, ROUTE_MGR))


# ---------------------------------------------------------------------------
# Tier 2/3: full active-client scenarios
# ---------------------------------------------------------------------------
def setup_active_client_with_plan(api, meal_type="HOT", meals_per_day=2, delivery_days=None,
                                  client_overrides=None, assessment_overrides=None,
                                  route_overrides=None, plan_overrides=None) -> dict:
    """Active route + ASSESSED client + ACTIVE meal plan, then activate the client.

    Sequence: driver(active) -> route(active) -> client(assessed) -> meal-plan -> activate client.
    Returns {"driver","route","client","assessment","meal_plan"} where client is ACTIVE.
    """
    ar = create_active_route(api, **(route_overrides or {}))
    ac = create_assessed_client(api, client_overrides=client_overrides,
                                assessment_overrides=assessment_overrides)
    client, assessment = ac["client"], ac["assessment"]
    plan_kwargs = dict(meal_type=meal_type, meals_per_day=meals_per_day,
                       delivery_days=delivery_days or ["MON", "WED", "FRI"])
    plan_kwargs.update(plan_overrides or {})
    meal_plan = create_meal_plan_for(api, client["id"], assessment["id"], ar["route"]["id"], **plan_kwargs)
    client = get_success_data(api.activate_client(client["id"], INTAKE))
    return {
        "driver": ar["driver"],
        "route": ar["route"],
        "client": client,
        "assessment": assessment,
        "meal_plan": meal_plan,
    }


def setup_assessed_client_with_plan(api, meal_type="HOT", meals_per_day=2, delivery_days=None,
                                    client_overrides=None, assessment_overrides=None,
                                    route_overrides=None, plan_overrides=None) -> dict:
    """Same as setup_active_client_with_plan but the client is left ASSESSED (not activated).

    Returns {"driver","route","client","assessment","meal_plan"} with client ASSESSED.
    """
    ar = create_active_route(api, **(route_overrides or {}))
    ac = create_assessed_client(api, client_overrides=client_overrides,
                                assessment_overrides=assessment_overrides)
    client, assessment = ac["client"], ac["assessment"]
    plan_kwargs = dict(meal_type=meal_type, meals_per_day=meals_per_day,
                       delivery_days=delivery_days or ["MON", "WED", "FRI"])
    plan_kwargs.update(plan_overrides or {})
    meal_plan = create_meal_plan_for(api, client["id"], assessment["id"], ar["route"]["id"], **plan_kwargs)
    return {
        "driver": ar["driver"],
        "route": ar["route"],
        "client": client,
        "assessment": assessment,
        "meal_plan": meal_plan,
    }


def schedule_delivery(api, meal_plan_id, scheduled_date) -> dict:
    """Schedule one delivery for a plan on a date."""
    return get_success_data(api.create_delivery(f.create_delivery_payload(meal_plan_id, scheduled_date), ROUTE_MGR))


def complete_delivery(api, delivery_id, driver_id, outcome, wellness_notes=None) -> dict:
    """Complete a delivery as the owning driver."""
    payload = f.complete_delivery_payload(outcome)
    if wellness_notes is not None:
        payload["wellness_notes"] = wellness_notes
    headers = make_volunteer_driver_headers(driver_id)
    return get_success_data(api.complete_delivery(delivery_id, payload, headers))


def setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02",
                                                meal_type="HOT", meals_per_day=2,
                                                delivery_days=None, route_overrides=None) -> dict:
    """Active client with an ACTIVE plan and one SCHEDULED delivery.

    Returns the setup_active_client_with_plan dict plus {"delivery": <SCHEDULED delivery>}.
    """
    scenario = setup_active_client_with_plan(
        api, meal_type=meal_type, meals_per_day=meals_per_day,
        delivery_days=delivery_days, route_overrides=route_overrides,
    )
    scenario["delivery"] = schedule_delivery(api, scenario["meal_plan"]["id"], scheduled_date)
    return scenario


def setup_open_welfare_alert(api, scheduled_date="2026-03-02") -> dict:
    """Active client whose one delivery was completed NO_ANSWER, opening a WelfareAlert.

    Returns the scenario dict plus {"delivery","wellness_check","alert"} where the alert
    is OPEN with severity LOW (first consecutive NO_ANSWER).
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date=scheduled_date)
    driver_id = scenario["driver"]["id"]
    complete_delivery(api, scenario["delivery"]["id"], driver_id, "NO_ANSWER")
    checks, _ = _list(api.list_wellness_checks(ROUTE_MGR, params={"delivery_id": scenario["delivery"]["id"]}))
    alerts, _ = _list(api.list_welfare_alerts(ROUTE_MGR, params={"client_id": scenario["client"]["id"]}))
    scenario["wellness_check"] = checks[0] if checks else None
    scenario["alert"] = alerts[0] if alerts else None
    return scenario


def _list(response):
    """Return (data_list, meta) from a list response, tolerating 2xx."""
    data = get_success_data(response)
    body = response.json()
    return data, body.get("meta", {})
