"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints, because each test runs against a freshly restarted server. Setup
calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_building_payload,
    create_complaint_payload,
    create_deduction_authorization_payload,
    create_household_member_payload,
    create_household_payload,
    create_housing_unit_payload,
    create_pest_treatment_payload,
    create_regulatory_inspection_payload,
    create_season_window_payload,
    create_tenancy_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_inspector_headers,
    make_maintenance_lead_headers,
    make_site_manager_headers,
)

ADMIN = TEST_USERS["operator_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
LEAD = TEST_USERS["maintenance_lead_headers"]
INSPECTOR = TEST_USERS["compliance_inspector_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_site(name="Harvest Site", state_code="CA") -> dict:
    resp = api_client.create_housing_site({"name": name, "state_code": state_code},
                                          ADMIN)
    return get_success_data(resp)


def create_building(site_id, name="B1") -> dict:
    resp = api_client.create_building(create_building_payload(site_id, name=name),
                                      ADMIN)
    return get_success_data(resp)


def create_unit(site_id, building_id, unit_code="U1", unit_type="FAMILY_UNIT",
                max_occupancy=4, monthly_rent_cents=90000) -> dict:
    payload = create_housing_unit_payload(
        building_id, site_id, unit_code=unit_code, unit_type=unit_type,
        max_occupancy=max_occupancy, monthly_rent_cents=monthly_rent_cents)
    resp = api_client.create_housing_unit(payload, ADMIN)
    return get_success_data(resp)


def get_site(site_id) -> dict:
    return get_success_data(api_client.get_housing_site(site_id, ADMIN))


def get_unit(unit_id) -> dict:
    return get_success_data(api_client.get_housing_unit(unit_id, ADMIN))


def get_household(household_id) -> dict:
    return get_success_data(api_client.get_household(household_id, INTAKE))


def get_tenancy(tenancy_id) -> dict:
    return get_success_data(api_client.get_tenancy(tenancy_id, INTAKE))


def get_statement(tenancy_id) -> dict:
    return get_success_data(api_client.get_tenancy_statement(tenancy_id, INTAKE))


def get_summary(site_id) -> dict:
    return get_success_data(api_client.get_site_compliance_summary(site_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1b: certification lifecycle (PRD §3.2)
# ---------------------------------------------------------------------------

def schedule_certification(unit_id, inspector_id="ci-1") -> dict:
    resp = api_client.create_unit_certification({"unit_id": unit_id},
                                                make_compliance_inspector_headers(inspector_id))
    return get_success_data(resp)


def certify_unit(unit_id, inspector_id="ci-1", deficiency_count=0) -> dict:
    """Schedule a certification and walk it SCHEDULED -> IN_PROGRESS -> PASSED."""
    cert = schedule_certification(unit_id, inspector_id)
    headers = make_compliance_inspector_headers(inspector_id)
    get_success_data(api_client.update_unit_certification(
        cert["id"], {"status": "IN_PROGRESS"}, headers))
    return get_success_data(api_client.update_unit_certification(
        cert["id"], {"status": "PASSED", "deficiency_count": deficiency_count},
        headers))


# ---------------------------------------------------------------------------
# Tier 2: season windows + site lifecycle (PRD §3.1)
# ---------------------------------------------------------------------------

def create_season_window(site_id, label="S", planned_open_date="2026-08-01",
                         planned_close_date="2026-11-30") -> dict:
    """Create a window with a fresh OCC read of the site's version."""
    site = get_site(site_id)
    payload = create_season_window_payload(
        site_id, site["version"], label=label,
        planned_open_date=planned_open_date,
        planned_close_date=planned_close_date)
    return get_success_data(api_client.create_season_window(payload, ADMIN))


def drive_site(site_id, status) -> dict:
    return get_success_data(api_client.update_housing_site(
        site_id, {"status": status}, ADMIN))


def open_site(site_id) -> dict:
    """Drive DRAFT -> OPENING -> OPEN. Requires a covering PLANNED window and
    at least one CERTIFIED unit (PRD §3.1)."""
    drive_site(site_id, "OPENING")
    return drive_site(site_id, "OPEN")


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2b: the workhorse — open site with certified units
# ---------------------------------------------------------------------------

def setup_site_with_units(unit_specs=None, site_name="Harvest Site",
                          state_code="CA", open=True,
                          window=("2026-08-01", "2026-11-30")) -> dict:
    """Site + building + N units, each certified PASSED, then the site opened.

    unit_specs: list of dicts with keys unit_code / unit_type /
    max_occupancy / monthly_rent_cents. Returns a dict with site, building,
    units (list), certs (list), window.
    """
    if unit_specs is None:
        unit_specs = [{"unit_code": "U1"}]
    site = create_site(name=site_name, state_code=state_code)
    building = create_building(site["id"])
    units = []
    certs = []
    for i, spec in enumerate(unit_specs):
        unit = create_unit(
            site["id"], building["id"],
            unit_code=spec.get("unit_code", f"U{i + 1}"),
            unit_type=spec.get("unit_type", "FAMILY_UNIT"),
            max_occupancy=spec.get("max_occupancy", 4),
            monthly_rent_cents=spec.get("monthly_rent_cents", 90000))
        cert = certify_unit(unit["id"])
        units.append(get_unit(unit["id"]))
        certs.append(cert)
    window_obj = None
    if window is not None:
        window_obj = create_season_window(site["id"], "S", window[0], window[1])
    if open:
        site = open_site(site["id"])
    return {"site": get_site(site["id"]), "building": building,
            "units": units, "certs": certs, "window": window_obj}


def setup_certified_site(**kwargs) -> dict:
    """Single-unit variant of setup_site_with_units; exposes `unit`/`cert`."""
    ctx = setup_site_with_units(**kwargs)
    ctx["unit"] = ctx["units"][0]
    ctx["cert"] = ctx["certs"][0]
    return ctx


# ---------------------------------------------------------------------------
# Tier 2c: households, members, authorizations (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------

def create_household(name="Fam Test", income_cents=6000000,
                     ag_work_verified=True) -> dict:
    return get_success_data(api_client.create_household(
        create_household_payload(head_of_household_name=name,
                                 annual_family_income_cents=income_cents,
                                 ag_work_verified=ag_work_verified), INTAKE))


def add_member(household_id, full_name="Member", date_of_birth="1990-01-01",
               relationship="HEAD") -> dict:
    return get_success_data(api_client.create_household_member(
        create_household_member_payload(
            household_id, full_name=full_name, date_of_birth=date_of_birth,
            relationship=relationship), INTAKE))


def set_eligibility(household_id, status) -> dict:
    return get_success_data(api_client.update_household(
        household_id, {"eligibility_status": status}, INTAKE))


def setup_eligible_household(name="Fam Test", income_cents=6000000,
                             members=(("Member One", "1990-01-01", "HEAD"),)) -> dict:
    """Household created with verified ag work, granted ELIGIBLE, with the
    given (name, dob, relationship) members added. Returns the final household
    read plus the member records."""
    household = create_household(name=name, income_cents=income_cents)
    set_eligibility(household["id"], "ELIGIBLE")
    member_records = [
        add_member(household["id"], full_name=n, date_of_birth=d, relationship=r)
        for (n, d, r) in members
    ]
    return {"household": get_household(household["id"]),
            "members": member_records}


def create_authorization(household_id, cap_percent=0.25,
                         purpose="RENT_AND_UTILITIES",
                         effective_date="2026-08-01") -> dict:
    """Create a deduction authorization with a fresh OCC read of the
    household's version (PRD §2.7)."""
    household = get_household(household_id)
    payload = create_deduction_authorization_payload(
        household_id, household["version"], cap_percent=cap_percent,
        purpose=purpose, effective_date=effective_date)
    return get_success_data(api_client.create_deduction_authorization(
        payload, INTAKE))


# ---------------------------------------------------------------------------
# Tier 3: tenancies (PRD §3.4)
# ---------------------------------------------------------------------------

def create_tenancy(household_id, unit_id, move_in_date="2026-08-11") -> dict:
    """Create a PENDING_MOVE_IN tenancy with a fresh OCC read of the unit's
    version."""
    unit = get_unit(unit_id)
    payload = create_tenancy_payload(household_id, unit_id, unit["version"],
                                     move_in_date=move_in_date)
    return get_success_data(api_client.create_tenancy(payload, INTAKE))


def activate_tenancy(tenancy_id) -> dict:
    return get_success_data(api_client.update_tenancy(
        tenancy_id, {"status": "ACTIVE"}, INTAKE))


def setup_active_tenancy(site_name="Harvest Site", unit_spec=None,
                         household_name="Fam Test", income_cents=6000000,
                         members=(("Member One", "1990-01-01", "HEAD"),),
                         move_in_date="2026-08-11") -> dict:
    """Open site + certified unit + ELIGIBLE household + ACTIVE tenancy."""
    specs = [unit_spec or {"unit_code": "U1"}]
    ctx = setup_certified_site(site_name=site_name, unit_specs=specs)
    hh = setup_eligible_household(name=household_name,
                                  income_cents=income_cents, members=members)
    tenancy = create_tenancy(hh["household"]["id"], ctx["unit"]["id"],
                             move_in_date=move_in_date)
    tenancy = activate_tenancy(tenancy["id"])
    ctx.update({"household": hh["household"], "members": hh["members"],
                "tenancy": tenancy})
    return ctx


def setup_pending_tenancy(site_name="Harvest Site", unit_spec=None,
                          household_name="Fam Test", income_cents=6000000,
                          members=(("Member One", "1990-01-01", "HEAD"),),
                          move_in_date="2026-08-11") -> dict:
    """Same as setup_active_tenancy but the tenancy stays PENDING_MOVE_IN."""
    specs = [unit_spec or {"unit_code": "U1"}]
    ctx = setup_certified_site(site_name=site_name, unit_specs=specs)
    hh = setup_eligible_household(name=household_name,
                                  income_cents=income_cents, members=members)
    tenancy = create_tenancy(hh["household"]["id"], ctx["unit"]["id"],
                             move_in_date=move_in_date)
    ctx.update({"household": hh["household"], "members": hh["members"],
                "tenancy": tenancy})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b: work orders (PRD §3.6)
# ---------------------------------------------------------------------------

def create_work_order(unit_id, category="OTHER", severity="MINOR",
                      description="test work order", complaint_id=None,
                      creator=LEAD) -> dict:
    payload = create_work_order_payload(
        unit_id, category=category, severity=severity, description=description)
    if complaint_id is not None:
        payload["complaint_id"] = complaint_id
    return get_success_data(api_client.create_work_order(payload, creator))


def walk_work_order_to_completed(work_order_id, completed_by="ml-1") -> dict:
    """REPORTED -> TRIAGED -> ASSIGNED -> IN_PROGRESS -> COMPLETED.

    completed_by is the X-User-ID worn by the MaintenanceLead on COMPLETED.
    """
    get_success_data(api_client.update_work_order(
        work_order_id, {"status": "TRIAGED"}, LEAD))
    get_success_data(api_client.update_work_order(
        work_order_id, {"status": "ASSIGNED", "assignee_name": "tech-1"}, LEAD))
    get_success_data(api_client.update_work_order(
        work_order_id, {"status": "IN_PROGRESS"}, LEAD))
    return get_success_data(api_client.update_work_order(
        work_order_id, {"status": "COMPLETED"},
        make_maintenance_lead_headers(completed_by)))


def verify_work_order(work_order_id, verified_by="sm-1") -> dict:
    return get_success_data(api_client.update_work_order(
        work_order_id, {"status": "VERIFIED"},
        make_site_manager_headers(verified_by)))


# ---------------------------------------------------------------------------
# Tier 3c: pest treatments (PRD §3.6)
# ---------------------------------------------------------------------------

def create_pest_treatment(unit_id, treatment_type="ROUTINE",
                          scheduled_date="2026-08-01",
                          reentry_buffer_days=0) -> dict:
    return get_success_data(api_client.create_pest_treatment(
        create_pest_treatment_payload(
            unit_id, treatment_type=treatment_type,
            scheduled_date=scheduled_date,
            reentry_buffer_days=reentry_buffer_days), MANAGER))


def apply_pest_treatment(unit_id, treatment_type="ROUTINE",
                         scheduled_date="2026-08-01", reentry_buffer_days=0,
                         apply_clock=None) -> dict:
    """Create a treatment and mark it APPLIED. apply_clock optionally moves
    the logical clock first so applied_date lands on a specific date."""
    treatment = create_pest_treatment(unit_id, treatment_type, scheduled_date,
                                      reentry_buffer_days)
    if apply_clock is not None:
        set_clock(apply_clock)
    return get_success_data(api_client.update_pest_treatment(
        treatment["id"], {"status": "APPLIED"}, MANAGER))


# ---------------------------------------------------------------------------
# Tier 4: complaints, inspections, condemnation (PRD §3.7)
# ---------------------------------------------------------------------------

def create_complaint(tenancy_id, category="OTHER", description="test",
                     creator=None) -> dict:
    return get_success_data(api_client.create_complaint(
        create_complaint_payload(tenancy_id, category=category,
                                 description=description),
        creator or INTAKE))


def create_inspection(site_id, agency="STATE_HOUSING",
                      scheduled_date="2026-08-15", inspector_id="ci-1") -> dict:
    return get_success_data(api_client.create_regulatory_inspection(
        create_regulatory_inspection_payload(
            site_id, agency=agency, scheduled_date=scheduled_date),
        make_compliance_inspector_headers(inspector_id)))


def conduct_inspection(inspection_id, inspector_id="ci-1") -> dict:
    return get_success_data(api_client.update_regulatory_inspection(
        inspection_id, {"status": "CONDUCTED"},
        make_compliance_inspector_headers(inspector_id)))


def issue_findings(inspection_id, findings, inspector_id="ci-1") -> dict:
    return get_success_data(api_client.update_regulatory_inspection(
        inspection_id, {"status": "FINDINGS_ISSUED", "findings": findings},
        make_compliance_inspector_headers(inspector_id)))


def condemn_unit_with_finding(site_id, unit_id, issuer="ci-1",
                              code="ELEC-01") -> dict:
    """Drive an inspection SCHEDULED -> CONDUCTED -> FINDINGS_ISSUED carrying
    one CRITICAL finding against unit_id. The unit lands CONDEMNED (PRD §3.7).
    Requires the site to be OPEN."""
    inspection = create_inspection(site_id, inspector_id=issuer)
    conduct_inspection(inspection["id"], inspector_id=issuer)
    inspection = issue_findings(
        inspection["id"],
        [{"unit_id": unit_id, "severity": "CRITICAL", "code": code}],
        inspector_id=issuer)
    return {"inspection": inspection, "unit": get_unit(unit_id)}
