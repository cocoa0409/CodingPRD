"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so all preconditions are built from scratch here via the
PRD's public endpoints. All helpers use get_success_data (lenient) so a setup
failure surfaces as a clear setup error rather than a confusing assertion.

Naming tiers:
  Tier 1: state progression (create + activate)
  Tier 2: hierarchy (class + project + equipment)
  Tier 3: full lifecycle shortcuts (assignment through close, repair through complete)
  Tier 4: threshold targeting (meter at exact milli-hours)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_assignment_payload,
    create_damage_report_payload,
    create_equipment_class_payload,
    create_equipment_payload,
    create_lowboy_payload,
    create_mechanic_payload,
    create_project_payload,
    create_reading_payload,
    create_transport_job_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_mechanic_headers

_ADMIN = TEST_USERS["fleet_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN)
    return get_success_data(resp)


def make_class(**overrides):
    resp = api_client.create_equipment_class(create_equipment_class_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def make_project(**overrides):
    resp = api_client.create_project(create_project_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def make_equipment(class_id, **overrides):
    resp = api_client.create_equipment(create_equipment_payload(class_id, **overrides), _ADMIN)
    return get_success_data(resp)


def make_mechanic(home_project_id, **overrides):
    resp = api_client.create_mechanic(create_mechanic_payload(home_project_id, **overrides), _ADMIN)
    return get_success_data(resp)


def make_lowboy(**overrides):
    resp = api_client.create_lowboy(create_lowboy_payload(**overrides), _DISP)
    return get_success_data(resp)


def make_reading(equipment_id, **overrides):
    resp = api_client.create_reading(equipment_id, create_reading_payload(**overrides), _ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: hierarchy bundles
# ---------------------------------------------------------------------------

def make_fleet_bundle(class_overrides=None, project_overrides=None, equipment_overrides=None):
    """Class + project + OWNED equipment. Returns (cls, project, equipment)."""
    cls = make_class(**(class_overrides or {}))
    project = make_project(**(project_overrides or {}))
    equipment = make_equipment(cls["id"], **(equipment_overrides or {}))
    return cls, project, equipment


# ---------------------------------------------------------------------------
# Tier 3: assignment lifecycle
# ---------------------------------------------------------------------------

def make_reserved_assignment(equipment, project, **overrides):
    """Create a RESERVED assignment using the unit's current version."""
    resp = api_client.create_assignment(
        create_assignment_payload(
            equipment["id"], project["id"], equipment["version"], **overrides
        ),
        _ADMIN,
    )
    return get_success_data(resp)


def make_active_assignment(equipment, project, **overrides):
    """Reserve + activate. Returns the ACTIVE assignment."""
    asg = make_reserved_assignment(equipment, project, **overrides)
    resp = api_client.activate_assignment(asg["id"], _ADMIN)
    return get_success_data(resp)


def close_assignment(assignment_id, close_reason="COMPLETED"):
    resp = api_client.close_assignment(assignment_id, {"close_reason": close_reason}, _ADMIN)
    return get_success_data(resp)


def get_equipment(equipment_id):
    return get_success_data(api_client.get_equipment(equipment_id, _ADMIN))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, _ADMIN))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, _ADMIN))


def get_mechanic(mechanic_id):
    return get_success_data(api_client.get_mechanic(mechanic_id, _ADMIN))


def get_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, _ADMIN))


def get_damage_report(damage_report_id):
    return get_success_data(api_client.get_damage_report(damage_report_id, _ADMIN))


# ---------------------------------------------------------------------------
# Tier 3b: work-order lifecycle (dispatch / start / complete by mechanic)
# ---------------------------------------------------------------------------

def make_work_order(equipment_id, kind="REPAIR", **overrides):
    resp = api_client.create_work_order(
        create_work_order_payload(equipment_id, kind=kind, **overrides), _ADMIN
    )
    return get_success_data(resp)


def dispatch_work_order(work_order_id, mechanic_id):
    resp = api_client.dispatch_work_order(work_order_id, {"mechanic_id": mechanic_id}, _ADMIN)
    return get_success_data(resp)


def start_work_order_as_mechanic(work_order_id, mechanic_id):
    resp = api_client.start_work_order(work_order_id, make_mechanic_headers(mechanic_id))
    return get_success_data(resp)


def complete_work_order_as_mechanic(work_order_id, mechanic_id):
    resp = api_client.complete_work_order(work_order_id, make_mechanic_headers(mechanic_id))
    return get_success_data(resp)


def run_repair_to_completion(work_order_id, mechanic_id):
    """Dispatch -> start -> complete as the given mechanic. Returns completed WO."""
    dispatch_work_order(work_order_id, mechanic_id)
    start_work_order_as_mechanic(work_order_id, mechanic_id)
    return complete_work_order_as_mechanic(work_order_id, mechanic_id)


# ---------------------------------------------------------------------------
# Tier 3c: damage lifecycle
# ---------------------------------------------------------------------------

def make_damage_report(equipment_id, project_id, **overrides):
    resp = api_client.create_damage_report(
        create_damage_report_payload(equipment_id, project_id, **overrides), _ADMIN
    )
    return get_success_data(resp)


def assess_damage(damage_report_id):
    return get_success_data(api_client.assess_damage_report(damage_report_id, _ADMIN))


def dispute_damage(damage_report_id, dispute_note="contested"):
    return get_success_data(
        api_client.dispute_damage_report(damage_report_id, {"dispute_note": dispute_note}, _PM)
    )


def reassess_damage(damage_report_id, line_items, expected_damage_report_version):
    return get_success_data(
        api_client.reassess_damage_report(
            damage_report_id,
            {
                "line_items": line_items,
                "expected_damage_report_version": expected_damage_report_version,
            },
            _ADMIN,
        )
    )


def confirm_damage(damage_report_id):
    return get_success_data(api_client.confirm_damage_report(damage_report_id, _ADMIN))


def make_confirmed_damage(equipment_id, project_id, **overrides):
    """File -> assess -> confirm. Returns the CONFIRMED damage report."""
    d = make_damage_report(equipment_id, project_id, **overrides)
    assess_damage(d["id"])
    return confirm_damage(d["id"])


# ---------------------------------------------------------------------------
# Tier 3d: transport lifecycle
# ---------------------------------------------------------------------------

def make_transport_job(equipment_id, from_project_id, to_project_id, lowboy_id, **overrides):
    resp = api_client.create_transport_job(
        create_transport_job_payload(equipment_id, from_project_id, to_project_id, lowboy_id, **overrides),
        _DISP,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: threshold / meter targeting
# ---------------------------------------------------------------------------

def push_meter_to(equipment_id, target_milli, readings):
    """Ingest a sequence of (recorded_date, delta_milli, fuel_ml) readings.

    `readings` is a list of tuples. The caller is responsible for making the
    sum match the target.
    """
    out = []
    for recorded_date, delta_milli, fuel_ml in readings:
        out.append(
            make_reading(
                equipment_id,
                recorded_date=recorded_date,
                engine_hours_delta_milli=delta_milli,
                fuel_used_milliliters=fuel_ml,
            )
        )
    return out
