"""Composite setup helpers.

These encapsulate the multi-step preambles that the design indices require, so
that test bodies focus on assertions. All setup calls use get_success_data()
(lenient) so a setup failure surfaces as a clear "Setup failed".

Identity threading: the Technician role is entity_backed:CrewMember. Every
technician call below uses make_technician_headers(crew_id) so the acting
X-User-ID equals the real CrewMember.id. PlanAdmin / Dispatcher are opaque and
use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import TEST_USERS, make_technician_headers
from .factories import (
    create_pricing_config_payload, create_homeowner_payload, create_home_payload,
    create_system_payload, create_crew_member_payload, create_route_plan_payload,
    create_work_order_payload, inspect_payload, complete_payload, commit_payload,
    recurring_plan_payload, duct_line, sanitize_line, dryer_line,
)

PA = TEST_USERS["plan_admin_headers"]
DI = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def create_active_pricing_config(**overrides) -> dict:
    """Create a config and activate it. Returns the activated config."""
    cfg = get_success_data(api.create_pricing_config(create_pricing_config_payload(**overrides), PA))
    return get_success_data(api.activate_pricing_config(cfg["id"], PA))


def create_draft_pricing_config(**overrides) -> dict:
    """Create a DRAFT config without activating. Returns the config."""
    return get_success_data(api.create_pricing_config(create_pricing_config_payload(**overrides), PA))


def create_homeowner(**overrides) -> dict:
    return get_success_data(api.create_homeowner(create_homeowner_payload(**overrides), PA))


def create_home(homeowner_id=None, **overrides) -> dict:
    if homeowner_id is None:
        homeowner_id = create_homeowner()["id"]
    return get_success_data(api.create_home(create_home_payload(homeowner_id, **overrides), PA))


def add_system(home_id, **overrides) -> dict:
    return get_success_data(api.add_system(home_id, create_system_payload(**overrides), PA))


def create_crew(**overrides) -> dict:
    return get_success_data(api.create_crew_member(create_crew_member_payload(**overrides), DI))


def create_route(crew_member_id, **overrides) -> dict:
    return get_success_data(api.create_route_plan(create_route_plan_payload(crew_member_id, **overrides), DI))


# ---------------------------------------------------------------------------
# Home + systems builders
# ---------------------------------------------------------------------------
def create_home_with_systems(num_systems, register_count=5, zone_code="Z1",
                             square_footage=1500, homeowner_id=None):
    """Create a Home with N ACTIVE systems. Returns (home, [system, ...]).

    The returned home dict is re-fetched so active_system_count reflects all adds.
    """
    home = create_home(homeowner_id=homeowner_id, zone_code=zone_code,
                       square_footage=square_footage)
    systems = []
    for i in range(num_systems):
        systems.append(add_system(home["id"], label=f"Sys {i}", register_count=register_count))
    home = get_success_data(api.get_home(home["id"], PA))
    return home, systems


# ---------------------------------------------------------------------------
# WorkOrder lifecycle builders
# ---------------------------------------------------------------------------
def create_work_order(home_id, service_lines, **overrides) -> dict:
    return get_success_data(api.create_work_order(
        create_work_order_payload(home_id, service_lines, **overrides), DI))


def inspect(work_order_id, crew_id, **overrides) -> dict:
    return get_success_data(api.inspect_work_order(
        work_order_id, inspect_payload(**overrides), make_technician_headers(crew_id)))


def quote(work_order_id, crew_id) -> dict:
    return get_success_data(api.quote_work_order(work_order_id, make_technician_headers(crew_id)))


def create_inspected_work_order(home_id, service_lines, crew_id, inspect_overrides=None,
                                **wo_overrides) -> dict:
    """Create a WorkOrder and advance DRAFT -> INSPECTED. Returns the work order."""
    wo = create_work_order(home_id, service_lines, **wo_overrides)
    inspect(wo["id"], crew_id, **(inspect_overrides or {}))
    return get_success_data(api.get_work_order(wo["id"], DI))


def create_quoted_work_order(home_id, service_lines, crew_id, inspect_overrides=None,
                             **wo_overrides) -> dict:
    """Create a WorkOrder and advance to QUOTED (inspect then quote)."""
    wo = create_work_order(home_id, service_lines, **wo_overrides)
    inspect(wo["id"], crew_id, **(inspect_overrides or {}))
    quote(wo["id"], crew_id)
    return get_success_data(api.get_work_order(wo["id"], DI))


def commit(route_id, work_order_id, scheduled_start_minute, expected_version) -> dict:
    return get_success_data(api.commit_slot(
        route_id, commit_payload(work_order_id, scheduled_start_minute, expected_version), DI))


def create_scheduled_work_order(home_id, service_lines, crew_id, route=None,
                                scheduled_start_minute=540, zone_code="Z1",
                                service_date="2026-04-10", inspect_overrides=None,
                                **wo_overrides):
    """Create a QUOTED work order and commit it onto a route (-> SCHEDULED).

    Returns (work_order, route). If route is None a fresh OPEN route is created.
    """
    wo = create_quoted_work_order(home_id, service_lines, crew_id,
                                  inspect_overrides=inspect_overrides, **wo_overrides)
    if route is None:
        route = create_route(crew_id, zone_code=zone_code, service_date=service_date)
    commit(route["id"], wo["id"], scheduled_start_minute, route["version"])
    wo = get_success_data(api.get_work_order(wo["id"], DI))
    route = get_success_data(api.get_route_plan(route["id"], DI))
    return wo, route


def lock_route(route_id) -> dict:
    return get_success_data(api.lock_route_plan(route_id, DI))


def create_in_progress_work_order(home_id, service_lines, crew_id, route=None,
                                  scheduled_start_minute=540, zone_code="Z1",
                                  service_date="2026-04-10", inspect_overrides=None,
                                  **wo_overrides):
    """Drive a work order to IN_PROGRESS on a LOCKED route.

    Returns (work_order, route).
    """
    wo, route = create_scheduled_work_order(
        home_id, service_lines, crew_id, route=route,
        scheduled_start_minute=scheduled_start_minute, zone_code=zone_code,
        service_date=service_date, inspect_overrides=inspect_overrides, **wo_overrides)
    lock_route(route["id"])
    get_success_data(api.start_work_order(wo["id"], make_technician_headers(crew_id)))
    wo = get_success_data(api.get_work_order(wo["id"], DI))
    route = get_success_data(api.get_route_plan(route["id"], DI))
    return wo, route


def complete(work_order_id, crew_id, performed_service_lines, **overrides) -> dict:
    return get_success_data(api.complete_work_order(
        work_order_id, complete_payload(performed_service_lines, **overrides),
        make_technician_headers(crew_id)))


def create_completed_work_order(home_id, service_lines, crew_id, route=None,
                                scheduled_start_minute=540, zone_code="Z1",
                                service_date="2026-04-10", inspect_overrides=None,
                                complete_overrides=None, performed_service_lines=None,
                                **wo_overrides):
    """Drive a work order all the way to COMPLETED. Returns (work_order, route)."""
    wo, route = create_in_progress_work_order(
        home_id, service_lines, crew_id, route=route,
        scheduled_start_minute=scheduled_start_minute, zone_code=zone_code,
        service_date=service_date, inspect_overrides=inspect_overrides, **wo_overrides)
    if performed_service_lines is None:
        performed_service_lines = service_lines
    complete(wo["id"], crew_id, performed_service_lines, **(complete_overrides or {}))
    wo = get_success_data(api.get_work_order(wo["id"], DI))
    route = get_success_data(api.get_route_plan(route["id"], DI))
    return wo, route


# ---------------------------------------------------------------------------
# RecurringPlan builders
# ---------------------------------------------------------------------------
def enroll_plan(home_id, cadence_months=12, expected_home_version=None) -> dict:
    """Enroll a Home in a RecurringPlan. Reads the home's live version if not given."""
    if expected_home_version is None:
        expected_home_version = get_success_data(api.get_home(home_id, PA))["version"]
    return get_success_data(api.create_recurring_plan(
        home_id, recurring_plan_payload(cadence_months, expected_home_version), PA))


def create_home_with_active_plan(cadence_months=12, num_systems=1, register_count=5,
                                 zone_code="Z1", square_footage=1500):
    """Home with N ACTIVE systems and one ACTIVE RecurringPlan.

    Returns (home, [systems], plan). The home dict is re-fetched after enrollment.
    """
    home, systems = create_home_with_systems(num_systems, register_count=register_count,
                                             zone_code=zone_code, square_footage=square_footage)
    plan = enroll_plan(home["id"], cadence_months=cadence_months,
                       expected_home_version=home["version"])
    home = get_success_data(api.get_home(home["id"], PA))
    return home, systems, plan


def set_clock(to_iso8601: str):
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, PA))


def create_plan_with_due_reminder(cadence_months=6, clock_to="2026-10-05T00:00:00Z"):
    """ACTIVE plan whose reminder has been forced DUE by advancing the clock.

    Returns (home, plan). Uses refresh-reminder after the clock advance.
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=cadence_months)
    set_clock(clock_to)
    get_success_data(api.refresh_reminder(plan["id"], PA))
    plan = get_success_data(api.list_recurring_plans(home["id"], PA))
    return home, plan


# ---------------------------------------------------------------------------
# UpsellReferral builders
# ---------------------------------------------------------------------------
def create_pending_referral(register_count=8, num_systems=1, dust_severity=5,
                            square_footage=1500):
    """Drive a work order to COMPLETED with recommend_hvac_repair=true to mint a
    PENDING UpsellReferral. Returns (referral, work_order, home, crew).

    register_count/num_systems are chosen by the caller so the risk score reaches
    the referral threshold; the recommend_hvac_repair flag is the gate per the PRD.
    """
    cfg = create_active_pricing_config()
    home, systems = create_home_with_systems(num_systems, register_count=register_count,
                                             square_footage=square_footage)
    crew = create_crew()
    lines = [duct_line(systems[0]["id"])]
    wo, route = create_completed_work_order(
        home["id"], lines, crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": dust_severity},
        complete_overrides={"after_photo_count": 2, "dust_severity": dust_severity,
                            "recommend_hvac_repair": True})
    referrals, _ = _list_referrals(work_order_id=wo["id"])
    referral = referrals[0]
    return referral, wo, home, crew


def _list_referrals(**params):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api.list_upsell_referrals(PA, params=params or None)
    return validate_paginated(resp)
