"""Composite setup helpers for multi-step test prerequisites.

Almost every interesting claim needs a Unit, which only exists after the full
install pipeline: customer -> technician -> model -> project -> load-assessment
-> size -> permit -> install -> activate. These helpers encapsulate that
9-step preamble and the lifecycle shortcuts that build on it (warranty claims,
repair dispatches, recall campaigns/remediations, maintenance plans/visits).

All setup uses get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion mismatch.

Identity threading: the Customer and Technician roles are entity-backed. When a
fixture creates such an entity and later makes an ownership-gated call, it threads
the real entity id via make_customer_headers / make_technician_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    make_service_manager_headers,
)
from . import factories as f

SM = TEST_USERS["service_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── Tier 0: Onboarding primitives ───────────────────────────────────────────
def create_customer(**overrides):
    return get_success_data(api_client.create_customer(f.create_customer_payload(**overrides), SM))


def create_technician(gas_certified=True, **overrides):
    return get_success_data(
        api_client.create_technician(
            f.create_technician_payload(gas_certified=gas_certified, **overrides), SM
        )
    )


def create_model(rated_kw=26, fuel_types=None, warranty_months=60, **overrides):
    if fuel_types is None:
        fuel_types = ["NG"]
    return get_success_data(
        api_client.create_model(
            f.create_model_payload(
                rated_kw=rated_kw,
                fuel_types=fuel_types,
                warranty_months=warranty_months,
                **overrides,
            ),
            SM,
        )
    )


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, SM))


# ─── Tier 1: Project pipeline ────────────────────────────────────────────────
def create_draft_project(customer_id=None, fuel_type="NG"):
    """Create a customer (if not given) and a DRAFT project. Returns (customer, project)."""
    if customer_id is None:
        customer = create_customer()
        customer_id = customer["id"]
    else:
        customer = {"id": customer_id}
    project = get_success_data(
        api_client.create_project(f.create_project_payload(customer_id, fuel_type=fuel_type), SM)
    )
    return customer, project


def add_load_assessment(project_id, appliances=None, method="STAGGERED"):
    payload = f.create_load_assessment_payload(method=method)
    if appliances is not None:
        payload["appliances"] = appliances
    return get_success_data(api_client.create_load_assessment(project_id, payload, SM))


def setup_activated_unit(
    rated_kw=26,
    fuel_types=None,
    warranty_months=60,
    fuel_type="NG",
    appliances=None,
    monitoring_enabled=False,
    permit_supply_btu=400000,
    customer_id=None,
):
    """Run the entire install pipeline and mint a Unit.

    Returns a dict with: customer, technician, model, project, assessment, unit.
    The install technician is gas-certified and ACTIVE so the install gate passes.
    """
    if fuel_types is None:
        fuel_types = [fuel_type]
    customer, project = create_draft_project(customer_id=customer_id, fuel_type=fuel_type)
    technician = create_technician(gas_certified=True)
    model = create_model(rated_kw=rated_kw, fuel_types=fuel_types, warranty_months=warranty_months)

    assessment = add_load_assessment(project["id"], appliances=appliances)
    get_success_data(
        api_client.size_project(
            project["id"], f.size_payload(assessment["id"], model["id"]), SM
        )
    )
    get_success_data(
        api_client.permit_project(
            project["id"], f.permit_payload(fuel_supply_btu_per_hr=permit_supply_btu), SM
        )
    )
    get_success_data(
        api_client.install_project(project["id"], f.install_payload(technician["id"]), SM)
    )
    activate_body = f.activate_payload(monitoring_enabled=monitoring_enabled)
    activated = get_success_data(
        api_client.activate_project(project["id"], activate_body, SM)
    )
    unit_id = activated["unit_id"]
    unit = get_success_data(api_client.get_unit(unit_id, SM))
    return {
        "customer": customer,
        "technician": technician,
        "model": model,
        "project": activated,
        "assessment": assessment,
        "unit": unit,
    }


def setup_sized_project(rated_kw=30, fuel_type="NG", fuel_types=None, appliances=None):
    """Pipeline up to SIZED only (assessment + model locked, not permitted)."""
    if fuel_types is None:
        fuel_types = [fuel_type]
    customer, project = create_draft_project(fuel_type=fuel_type)
    model = create_model(rated_kw=rated_kw, fuel_types=fuel_types)
    assessment = add_load_assessment(project["id"], appliances=appliances)
    sized = get_success_data(
        api_client.size_project(
            project["id"], f.size_payload(assessment["id"], model["id"]), SM
        )
    )
    return {"customer": customer, "model": model, "project": sized, "assessment": assessment}


def setup_permitted_project(rated_kw=20, fuel_type="NG", gas_certified=True):
    """Pipeline up to PERMITTED, plus a (configurable) technician for the install step.

    Returns dict with customer, technician, model, project (PERMITTED), assessment.
    """
    customer, project = create_draft_project(fuel_type=fuel_type)
    technician = create_technician(gas_certified=gas_certified)
    model = create_model(rated_kw=rated_kw, fuel_types=[fuel_type])
    assessment = add_load_assessment(project["id"])
    get_success_data(
        api_client.size_project(
            project["id"], f.size_payload(assessment["id"], model["id"]), SM
        )
    )
    permitted = get_success_data(
        api_client.permit_project(project["id"], f.permit_payload(), SM)
    )
    return {
        "customer": customer,
        "technician": technician,
        "model": model,
        "project": permitted,
        "assessment": assessment,
    }


def setup_installed_project(rated_kw=20, fuel_type="NG"):
    """Pipeline up to INSTALLED (ready to activate). Returns dict incl. project, technician."""
    permitted = setup_permitted_project(rated_kw=rated_kw, fuel_type=fuel_type)
    installed = get_success_data(
        api_client.install_project(
            permitted["project"]["id"], f.install_payload(permitted["technician"]["id"]), SM
        )
    )
    permitted["project"] = installed
    return permitted


# ─── Tier 2: Unit children ───────────────────────────────────────────────────
def file_warranty_claim(unit_id, description="Defect description", as_customer_id=None):
    """File a warranty claim, reading the current unit version for the OCC field."""
    unit = get_success_data(api_client.get_unit(unit_id, SM))
    payload = f.warranty_claim_payload(unit["version"], description=description)
    if as_customer_id is not None:
        headers = make_customer_headers(as_customer_id)
    else:
        headers = SM
    return get_success_data(api_client.create_warranty_claim(unit_id, payload, headers))


def file_claim_under_review(unit_id, description="Defect description"):
    """File a claim and move it OPEN -> UNDER_REVIEW. Returns the claim id."""
    claim = file_warranty_claim(unit_id, description=description)
    get_success_data(api_client.review_claim(claim["id"], CO))
    return claim


def create_paid_dispatch(unit_id, labor_cents=0, parts_cents=0):
    """Request a PAID dispatch directly on a unit (status REQUESTED)."""
    payload = {}
    if labor_cents:
        payload["labor_cents"] = labor_cents
    if parts_cents:
        payload["parts_cents"] = parts_cents
    return get_success_data(api_client.create_repair_dispatch(unit_id, payload, SM))


def assign_dispatch(dispatch_id, tech_id, expected_version=None):
    """Assign a tech to a dispatch, reading the current version if not supplied."""
    if expected_version is None:
        disp = get_success_data(api_client.get_repair_dispatch(dispatch_id, SM))
        expected_version = disp["version"]
    return get_success_data(
        api_client.assign_dispatch(
            dispatch_id, f.assign_payload(tech_id, expected_version), SM
        )
    )


def dispatch_in_progress(unit_id, tech_id, labor_cents=5000, parts_cents=0):
    """PAID dispatch walked to IN_PROGRESS (request -> assign -> start). Returns dispatch dict."""
    disp = create_paid_dispatch(unit_id, labor_cents=labor_cents, parts_cents=parts_cents)
    assign_dispatch(disp["id"], tech_id)
    started = get_success_data(
        api_client.start_dispatch(disp["id"], make_technician_headers(tech_id))
    )
    return started


def saturate_tech_dispatches(unit_id, tech_id, count=5):
    """Assign `count` PAID dispatches on a unit to one technician so its
    open_dispatch_count reaches `count`. Returns the list of dispatch dicts."""
    dispatches = []
    for _ in range(count):
        disp = create_paid_dispatch(unit_id, labor_cents=100)
        assign_dispatch(disp["id"], tech_id)
        dispatches.append(disp)
    return dispatches


def create_active_plan(unit_id, frequency="ANNUAL", monitoring_bundled=False):
    payload = f.maintenance_plan_payload(frequency=frequency)
    if monitoring_bundled:
        payload["monitoring_bundled"] = True
    return get_success_data(api_client.create_maintenance_plan(unit_id, payload, SM))


def schedule_visit(plan_id, scheduled_for, assigned_tech_id=None):
    payload = f.visit_payload(scheduled_for)
    if assigned_tech_id is not None:
        payload["assigned_tech_id"] = assigned_tech_id
    return get_success_data(api_client.schedule_visit(plan_id, payload, SM))


def add_success_exercise_logs(unit_id, occurred_ats):
    """Append a SUCCESS exercise log per timestamp in occurred_ats."""
    logs = []
    for ts in occurred_ats:
        logs.append(
            get_success_data(
                api_client.create_exercise_log(
                    unit_id, f.exercise_log_payload(ts, "SUCCESS"), SM
                )
            )
        )
    return logs


# ─── Tier 3: Recall campaign / remediation ──────────────────────────────────
def create_open_campaign(model_id, severity="MANDATORY", remediation_window_days=30):
    """Create a DRAFT campaign on a model and open it (fans out remediations)."""
    payload = f.recall_campaign_payload(
        model_id, severity=severity, remediation_window_days=remediation_window_days
    )
    campaign = get_success_data(api_client.create_recall_campaign(payload, CO))
    opened = get_success_data(api_client.open_campaign(campaign["id"], CO))
    return opened


def get_unit_remediation(unit_id):
    """Return the first remediation row targeting a unit (via the unit filter)."""
    resp = api_client.list_recall_remediations(SM, params={"unit_id": unit_id})
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    return rows[0]


def setup_unit_non_compliant_via_mandatory_recall(rated_kw=22):
    """Drive a unit to NON_COMPLIANT / warranty VOID through an overdue MANDATORY recall.

    Steps: activate unit -> open MANDATORY campaign (window 10d) -> advance clock
    past the deadline so the remediation sweeps to OVERDUE.
    Returns dict with unit, model, technician, customer, remediation, campaign.
    """
    setup = setup_activated_unit(rated_kw=rated_kw)
    campaign = create_open_campaign(
        setup["model"]["id"], severity="MANDATORY", remediation_window_days=10
    )
    remediation = get_unit_remediation(setup["unit"]["id"])
    set_clock("2026-02-01T00:00:00Z")
    unit = get_success_data(api_client.get_unit(setup["unit"]["id"], SM))
    setup["campaign"] = campaign
    setup["remediation"] = remediation
    setup["unit"] = unit
    return setup


def setup_recall_dispatch_started(rated_kw=22):
    """Build the full pre-resolve state of the depth-4 recall cascade.

    Unit made NON_COMPLIANT by an OVERDUE MANDATORY remediation, then the
    remediation SCHEDULED (spawning a RECALL dispatch) which is assigned & started.
    Returns dict incl. unit, remediation, recall_dispatch, technician.
    """
    setup = setup_activated_unit(rated_kw=rated_kw)
    tech_id = setup["technician"]["id"]
    campaign = create_open_campaign(
        setup["model"]["id"], severity="MANDATORY", remediation_window_days=30
    )
    remediation = get_unit_remediation(setup["unit"]["id"])
    scheduled = get_success_data(api_client.schedule_remediation(remediation["id"], SM))
    recall_dispatch_id = scheduled["dispatch_id"]
    assign_dispatch(recall_dispatch_id, tech_id)
    get_success_data(
        api_client.start_dispatch(recall_dispatch_id, make_technician_headers(tech_id))
    )
    set_clock("2026-03-01T00:00:00Z")
    setup["campaign"] = campaign
    setup["remediation"] = remediation
    setup["recall_dispatch_id"] = recall_dispatch_id
    return setup
