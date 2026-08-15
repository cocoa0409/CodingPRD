"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Facility-version threading: creating plans is OCC-protected on the facility's
version (PRD §2.6), and every child mutation (system registered, deficiency
recorded or remediated, plan created) recomputes facility derived fields and
bumps Facility.version (PRD §2.9). Plan-creating helpers therefore re-read the
facility immediately before POSTing so the expected version is always current.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    assess_payload,
    create_asset_system_payload,
    create_capital_plan_payload,
    create_client_payload,
    create_deficiency_payload,
    create_facility_payload,
    create_funding_scenario_payload,
    run_scenario_payload,
)
from .test_users import TEST_USERS, make_approver_headers, make_capital_planner_headers

CONSULTANT = TEST_USERS["consultant_headers"]
MANAGER = TEST_USERS["facility_manager_headers"]
PLANNER = TEST_USERS["capital_planner_headers"]
APPROVER = TEST_USERS["approver_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_client(**overrides):
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), CONSULTANT))


def create_facility(client_id=None, **overrides):
    """Create a facility (born with zeroed derived fields, assessment_epoch 0)."""
    if client_id is None:
        client_id = create_client()["id"]
    return get_success_data(api_client.create_facility(
        create_facility_payload(client_id, **overrides), CONSULTANT))


def get_facility(facility_id):
    return get_success_data(api_client.get_facility(facility_id, CONSULTANT))


def create_asset_system(facility_id, **overrides):
    """Register a system (born ACTIVE)."""
    return get_success_data(api_client.create_asset_system(
        create_asset_system_payload(facility_id, **overrides), CONSULTANT))


def get_asset_system(system_id):
    return get_success_data(api_client.get_asset_system(system_id, CONSULTANT))


def create_deficiency(asset_system_id, **overrides):
    """Record a deficiency (born OPEN / UNVERIFIED)."""
    return get_success_data(api_client.create_deficiency(
        create_deficiency_payload(asset_system_id, **overrides), CONSULTANT))


def get_deficiency(deficiency_id):
    return get_success_data(api_client.get_deficiency(deficiency_id, CONSULTANT))


def create_draft_plan(facility_id, planner_headers=None, **overrides):
    """Create a DRAFT plan, threading the facility's CURRENT version (OCC)."""
    headers = planner_headers or PLANNER
    facility = get_facility(facility_id)
    payload = create_capital_plan_payload(
        facility_id, facility["version"], **overrides)
    return get_success_data(
        api_client.create_capital_plan(payload, headers), 201)


def get_capital_plan(plan_id):
    return get_success_data(api_client.get_capital_plan(plan_id, PLANNER))


def create_scenario(capital_plan_id, **overrides):
    """Create a CONFIGURED funding scenario under a plan."""
    return get_success_data(api_client.create_funding_scenario(
        create_funding_scenario_payload(capital_plan_id, **overrides),
        PLANNER), 201)


def run_scenario(scenario_id, expected_capital_plan_version=None):
    """Run a scenario's waterfall; defaults to the plan's CURRENT version."""
    if expected_capital_plan_version is None:
        scenario = get_success_data(
            api_client.get_funding_scenario(scenario_id, PLANNER))
        plan = get_capital_plan(scenario["capital_plan_id"])
        expected_capital_plan_version = plan["version"]
    return get_success_data(api_client.run_funding_scenario(
        scenario_id, run_scenario_payload(expected_capital_plan_version),
        PLANNER))


def list_line_items(plan_id, **filters):
    params = {"capital_plan_id": plan_id}
    params.update(filters)
    data, _meta = validate_paginated(api_client.list_line_items(PLANNER, params))
    return data


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (facility + system [+ deficiencies])
# ---------------------------------------------------------------------------

def setup_facility_with_system(system_overrides=None, facility_overrides=None):
    """Client + facility + one ACTIVE system. Returns (facility, system)."""
    facility = create_facility(**(facility_overrides or {}))
    system = create_asset_system(facility["id"], **(system_overrides or {}))
    return facility, system


def setup_system_with_deficiency(deficiency_overrides=None,
                                 system_overrides=None,
                                 facility_overrides=None):
    """Facility + one ACTIVE system + one OPEN deficiency.

    Returns (facility, system, deficiency).
    """
    facility, system = setup_facility_with_system(system_overrides,
                                                  facility_overrides)
    deficiency = create_deficiency(system["id"], **(deficiency_overrides or {}))
    return facility, system, deficiency


# ---------------------------------------------------------------------------
# Tier 3: plan lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_funded_plan(deficiency_specs=None, plan_overrides=None,
                      scenario_overrides=None, system_overrides=None):
    """Facility + one system + deficiencies + DRAFT plan + scenario run.

    deficiency_specs: list of per-deficiency override dicts (default: one
    10,000,000-cent OPEN finding recommended for the plan's start year).
    Returns a workspace dict with facility/system/deficiencies/plan/scenario
    and the run response.
    """
    plan_overrides = dict(plan_overrides or {})
    start_year = plan_overrides.get("start_year", 2027)
    if deficiency_specs is None:
        deficiency_specs = [{
            "cost_estimate_cents": 10_000_000,
            "severity": 3,
            "urgency": 3,
            "recommended_year": start_year,
        }]
    facility, system = setup_facility_with_system(system_overrides)
    deficiencies = [create_deficiency(system["id"], **spec)
                    for spec in deficiency_specs]
    plan = create_draft_plan(facility["id"], **plan_overrides)
    scenario = create_scenario(plan["id"], **(scenario_overrides or {}))
    run = run_scenario(scenario["id"])
    return {
        "facility": facility,
        "system": system,
        "deficiencies": deficiencies,
        "plan": plan,
        "scenario": scenario,
        "run": run,
    }


def submit_plan(plan_id, planner_headers=None):
    return get_success_data(
        api_client.submit_plan(plan_id, planner_headers or PLANNER))


def setup_submitted_plan(submitter_id="test-planner-1", **kwargs):
    """Funded DRAFT plan moved to SUBMITTED. Returns the workspace dict."""
    workspace = setup_funded_plan(**kwargs)
    workspace["submitted"] = submit_plan(
        workspace["plan"]["id"], make_capital_planner_headers(submitter_id))
    workspace["submitter_id"] = submitter_id
    return workspace


def setup_approved_plan(submitter_id="test-planner-1",
                        approver_id="test-approver-1", **kwargs):
    """Plan driven DRAFT -> SUBMITTED -> APPROVED by two distinct identities."""
    workspace = setup_submitted_plan(submitter_id=submitter_id, **kwargs)
    workspace["approved"] = get_success_data(api_client.approve_plan(
        workspace["plan"]["id"], make_approver_headers(approver_id)))
    workspace["approver_id"] = approver_id
    return workspace


def remediate_to_corrected(deficiency_id):
    """Drive a deficiency to CORRECTED. Returns the final row.

    Starts remediation only when the finding is still OPEN: a finding already
    IN_PROGRESS (e.g. advanced there by plan approval, PRD section 3.6) needs
    only the completion leg.
    """
    current = get_deficiency(deficiency_id)
    if current["remediation_status"] == "OPEN":
        get_success_data(api_client.start_remediation(deficiency_id, MANAGER))
    return get_success_data(api_client.complete_remediation(deficiency_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 4: refresh-cycle helpers
# ---------------------------------------------------------------------------

def open_cycle(facility_id):
    """Open the facility's next refresh cycle. Returns the OPEN cycle."""
    return get_success_data(
        api_client.open_refresh_cycle(facility_id, CONSULTANT), 201)


def assess_system(system_id, condition_rating, note=None):
    """Record a reassessment (ACTIVE -> REASSESSED). Returns the system."""
    return get_success_data(api_client.assess_asset_system(
        system_id, assess_payload(condition_rating, note), CONSULTANT))


def accept_assessment(system_id):
    return get_success_data(api_client.accept_assessment(system_id, MANAGER))


def reject_assessment(system_id):
    return get_success_data(api_client.reject_assessment(system_id, MANAGER))


def setup_assessed_system(system_overrides=None, assess_rating=3,
                          facility_overrides=None):
    """Facility + system + open cycle + one accepted reassessment.

    Returns (facility, system, cycle). After this helper the system is ACTIVE
    with last_assessed_epoch equal to the cycle's epoch, so the cycle is
    closable.
    """
    facility, system = setup_facility_with_system(system_overrides,
                                                  facility_overrides)
    cycle = open_cycle(facility["id"])
    assess_system(system["id"], assess_rating)
    accept_assessment(system["id"])
    return facility, system, cycle


def list_system_snapshots(system_id):
    data, _meta = validate_paginated(
        api_client.list_system_snapshots(system_id, CONSULTANT))
    return data


def list_facility_cycles(facility_id):
    data, _meta = validate_paginated(
        api_client.list_facility_refresh_cycles(facility_id, CONSULTANT))
    return data
