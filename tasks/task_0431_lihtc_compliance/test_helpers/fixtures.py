"""Composite setup helpers for multi-step LIHTC test prerequisites.

Most interesting test claims require the system to be in a specific state that takes 5-15
API calls to reach (e.g. a building advanced to FINAL_8609, or a NONCOMPLIANT project with a
reported 8823). These helpers encapsulate those sequences so the tests can focus on
assertions, not plumbing.

All helpers use get_success_data() (the lenient validator) internally so that a setup failure
surfaces a clear "Setup step failed" error rather than a confusing assertion failure. Every
helper builds its preconditions from scratch — each test runs against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_project_payload,
    create_building_payload,
    create_unit_payload,
    create_household_payload,
    create_certification_payload,
    issue_form8609_payload,
    approve_payload,
    create_inspection_payload,
)
from .test_users import TEST_USERS, make_state_hfa_headers

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]

# Default 12-element monthly array whose chronological average fraction equals the
# provisional fraction (used when the test does not care about provisional/final divergence).
FLAT_MONTHLY_QUALIFIED = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
# 8-designated-of-10 dual-variant array: provisional 0.8000, final 0.6000.
DUAL_VARIANT_MONTHLY = [2, 2, 4, 4, 6, 6, 8, 8, 8, 8, 8, 8]


# ─── Tier 1/2: Basic entity hierarchy ─────────────────

def create_project(**overrides) -> dict:
    """Create a DRAFT project. Returns the project."""
    res = api_client.create_project(create_project_payload(**overrides), OWNER)
    return get_success_data(res)


def create_building(project_id: str, **overrides) -> dict:
    """Create a PRE_ALLOCATION building under a project. Returns the building."""
    res = api_client.create_building(
        create_building_payload(project_id, **overrides), OWNER
    )
    return get_success_data(res)


def create_unit(building_id: str, **overrides) -> dict:
    """Create a VACANT_NEVER_OCCUPIED unit under a building. Returns the unit."""
    res = api_client.create_unit(create_unit_payload(building_id, **overrides), OWNER)
    return get_success_data(res)


def create_household(project_id: str, **overrides) -> dict:
    """Register a household within a project. Returns the household."""
    res = api_client.create_household(
        create_household_payload(project_id, **overrides), OWNER
    )
    return get_success_data(res)


def setup_project_building(project_overrides=None, building_overrides=None):
    """Create a DRAFT project + one PRE_ALLOCATION building. Returns (project, building)."""
    project = create_project(**(project_overrides or {}))
    building = create_building(project["id"], **(building_overrides or {}))
    return project, building


def setup_project_building_unit(
    project_overrides=None, building_overrides=None, unit_overrides=None
):
    """Project + building + one unit. Returns (project, building, unit)."""
    project, building = setup_project_building(project_overrides, building_overrides)
    unit = create_unit(building["id"], **(unit_overrides or {}))
    return project, building, unit


# ─── Tier 3: Certification lifecycle shortcuts ────────

def create_submitted_certification(household_id, unit_id, **cert_overrides):
    """Create a certification and submit it (DRAFT -> SUBMITTED). Returns the certification
    after submit."""
    cert = get_success_data(
        api_client.create_certification(
            create_certification_payload(household_id, unit_id, **cert_overrides), OWNER
        )
    )
    submitted = get_success_data(
        api_client.submit_certification(cert["id"], OWNER)
    )
    return submitted


def create_approved_certification(household_id, unit_id, **cert_overrides):
    """Create -> submit -> approve a certification (drives unit li_status side effects).
    Returns the approved certification."""
    cert = get_success_data(
        api_client.create_certification(
            create_certification_payload(household_id, unit_id, **cert_overrides), OWNER
        )
    )
    api_client.submit_certification(cert["id"], OWNER)
    approved = get_success_data(
        api_client.approve_certification(cert["id"], approve_payload("APPROVE"), HFA)
    )
    return approved


def make_qualified_unit(
    project_overrides=None,
    building_overrides=None,
    unit_overrides=None,
    initial_income_cents=3_000_000,
):
    """Project + building + one designated LI unit made QUALIFIED via an approved INITIAL
    certification. Returns (project, building, unit, household)."""
    project, building, unit = setup_project_building_unit(
        project_overrides, building_overrides, unit_overrides
    )
    household = create_household(project["id"])
    create_approved_certification(
        household["id"], unit["id"], cert_type="INITIAL",
        annual_income_cents=initial_income_cents,
        effective_date="2026-01-15T00:00:00Z",
    )
    unit = get_success_data(api_client.get_unit(unit["id"], OWNER))
    return project, building, unit, household


def make_over_income_unit(
    project_overrides=None,
    building_overrides=None,
    unit_overrides=None,
    initial_income_cents=3_000_000,
    recert_income_cents=6_000_000,
):
    """Project + building + one unit driven QUALIFIED then OVER_INCOME via an over-income
    RECERT. Returns (project, building, unit, household)."""
    project, building, unit, household = make_qualified_unit(
        project_overrides, building_overrides, unit_overrides, initial_income_cents
    )
    recert = get_success_data(
        api_client.create_certification(
            create_certification_payload(
                household["id"], unit["id"], cert_type="RECERT",
                annual_income_cents=recert_income_cents,
                effective_date="2027-01-15T00:00:00Z",
            ),
            OWNER,
        )
    )
    api_client.submit_certification(recert["id"], OWNER)
    api_client.approve_certification(recert["id"], approve_payload("APPROVE"), HFA)
    unit = get_success_data(api_client.get_unit(unit["id"], OWNER))
    return project, building, unit, household


# ─── Tier 3: 8609 credit lifecycle shortcuts ──────────

def _create_designated_units(building_id, count, ami_designation="AMI_50"):
    """Create `count` non-MARKET designated units (each 1000 sqft) on a building."""
    units = []
    for i in range(count):
        u = create_unit(
            building_id,
            unit_number=f"U{i + 1}",
            ami_designation=ami_designation,
            bedroom_count=1,
            sqft=1_000,
            utility_allowance_cents=9_000,
        )
        units.append(u)
    return units


def setup_set_aside_met_with_designated_units(
    designated_count=8, total_units=10, total_sqft=10_000, minimum_set_aside="FORTY_SIXTY"
):
    """Project + building + `designated_count` designated units, project advanced to
    SET_ASIDE_MET. Returns (project, building, units)."""
    project = create_project(minimum_set_aside=minimum_set_aside)
    building = create_building(
        project["id"],
        total_residential_units=total_units,
        total_residential_sqft=total_sqft,
    )
    # Spread designations across AMI_50/AMI_60 to satisfy FORTY_SIXTY without affecting count.
    units = []
    for i in range(designated_count):
        band = "AMI_50" if i < (designated_count + 1) // 2 else "AMI_60"
        units.append(
            create_unit(
                building["id"],
                unit_number=f"U{i + 1}",
                ami_designation=band,
                bedroom_count=1,
                sqft=1_000,
                utility_allowance_cents=9_000,
            )
        )
    get_success_data(api_client.certify_set_aside(project["id"], HFA))
    project = get_success_data(api_client.get_project(project["id"], HFA))
    return project, building, units


def issue_provisional_8609(building_id):
    """Issue a PROVISIONAL 8609 (PRE_ALLOCATION -> PROVISIONAL_8609). Returns the Form8609."""
    return get_success_data(
        api_client.issue_form8609(building_id, issue_form8609_payload("PROVISIONAL"), HFA)
    )


def issue_final_8609(building_id, monthly_qualified_units, expected_version=None):
    """Issue a FINAL 8609 (PROVISIONAL_8609 -> FINAL_8609). If expected_version is None,
    reads the building's current version first. Returns the Form8609."""
    if expected_version is None:
        building = get_success_data(api_client.get_building(building_id, HFA))
        expected_version = building["version"]
    return get_success_data(
        api_client.issue_form8609(
            building_id,
            issue_form8609_payload(
                "FINAL",
                monthly_qualified_units=monthly_qualified_units,
                expected_building_version=expected_version,
            ),
            HFA,
        )
    )


def setup_building_at_provisional(total_units=2, designated_count=1):
    """Minimal project + building advanced to PROVISIONAL_8609 (set-aside met first).
    Returns (project, building) with the building re-fetched at PROVISIONAL_8609."""
    project = create_project(minimum_set_aside="FORTY_SIXTY")
    building = create_building(
        project["id"],
        total_residential_units=total_units,
        total_residential_sqft=total_units * 1_000,
    )
    _create_designated_units(building["id"], designated_count, "AMI_50")
    get_success_data(api_client.certify_set_aside(project["id"], HFA))
    issue_provisional_8609(building["id"])
    building = get_success_data(api_client.get_building(building["id"], HFA))
    return project, building


def setup_building_at_final(
    total_units=2, designated_count=1, monthly_qualified_units=None
):
    """Minimal project + building advanced to FINAL_8609. Returns (project, building) with the
    building re-fetched at FINAL_8609."""
    project, building = setup_building_at_provisional(total_units, designated_count)
    issue_final_8609(
        building["id"], monthly_qualified_units or FLAT_MONTHLY_QUALIFIED
    )
    building = get_success_data(api_client.get_building(building["id"], HFA))
    return project, building


def setup_dual_variant_building_at_final():
    """Project + building with 8 designated units, advanced to FINAL_8609 using the
    dual-variant monthly array (provisional 0.8000 -> final 0.6000). Returns
    (project, building, provisional_form, final_form)."""
    project, building, _units = setup_set_aside_met_with_designated_units(
        designated_count=8, total_units=10, total_sqft=10_000
    )
    prov_form = issue_provisional_8609(building["id"])
    building = get_success_data(api_client.get_building(building["id"], HFA))
    final_form = issue_final_8609(
        building["id"], DUAL_VARIANT_MONTHLY, expected_version=building["version"]
    )
    building = get_success_data(api_client.get_building(building["id"], HFA))
    return project, building, prov_form, final_form


# ─── Tier 3: Inspection / finding lifecycle shortcuts ─

def schedule_inspection(building_id, conductor_headers=None, **overrides):
    """Schedule a SCHEDULED inspection on a building. Returns the inspection."""
    headers = conductor_headers or HFA
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(building_id, **overrides), headers
        )
    )


def setup_failed_inspection_with_open_finding(
    conductor_user_id="hfa-1", deduction_points=None, project_overrides=None
):
    """Project + building + a CONDUCTED failing inspection that created an OPEN UPCS_FAIL
    Finding. The inspection's origin_agent_id is `conductor_user_id`. Returns
    (project, building, inspection, finding)."""
    conductor = make_state_hfa_headers(conductor_user_id)
    project = create_project(**(project_overrides or {}))
    building = create_building(project["id"])
    inspection = get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                building["id"],
                deduction_points=deduction_points or [20, 15, 12],
                has_exigent_health_safety=False,
            ),
            conductor,
        )
    )
    get_success_data(api_client.conduct_inspection(inspection["id"], conductor))
    inspection = get_success_data(api_client.get_inspection(inspection["id"], conductor))
    findings, _ = _list_findings_for_inspection(inspection["id"])
    finding = findings[0]
    return project, building, inspection, finding


def _list_findings_for_inspection(inspection_id):
    res = api_client.list_findings(HFA, params={"inspection_id": inspection_id})
    body = res.json()
    return body["data"], body["meta"]


def setup_noncompliant_project_with_final_building(
    total_units=2, designated_count=1, conductor_user_id="hfa-1", reporter_user_id="hfa-2"
):
    """Project advanced to NONCOMPLIANT (a failing inspection raised a finding, then a
    different StateHFA filed the 8823) with a building at FINAL_8609. Returns
    (project, building, finding) with the building re-fetched (carries the post-FINAL
    version)."""
    project, building = setup_building_at_final(total_units, designated_count)
    conductor = make_state_hfa_headers(conductor_user_id)
    reporter = make_state_hfa_headers(reporter_user_id)
    inspection = get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                building["id"],
                deduction_points=[20, 15, 12],
                has_exigent_health_safety=False,
            ),
            conductor,
        )
    )
    api_client.conduct_inspection(inspection["id"], conductor)
    findings, _ = _list_findings_for_inspection(inspection["id"])
    finding = findings[0]
    get_success_data(api_client.report_finding(finding["id"], reporter))
    project = get_success_data(api_client.get_project(project["id"], HFA))
    building = get_success_data(api_client.get_building(building["id"], HFA))
    finding = get_success_data(api_client.get_finding(finding["id"], HFA))
    return project, building, finding
