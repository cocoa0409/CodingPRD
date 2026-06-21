"""Composite setup helpers — multi-step preambles shared across tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the database is empty at the start of every test). Fixtures use the
lenient get_success_data() so setup failures surface as clear "Setup failed".

Identity threading: entity_backed roles (Homeowner, SolarInstaller, Utility,
SrecBroker) always act through make_<role>_headers(entity_id), never the shared
fallback constant, whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
    make_installer_headers,
    make_utility_headers,
    make_broker_headers,
)
from . import factories as F

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: principal registration
# ---------------------------------------------------------------------------

def register_homeowner(state_code="CA", annual_kwh_usage=12000, email=None):
    payload = F.create_homeowner_payload(
        state_code=state_code, annual_kwh_usage=annual_kwh_usage
    )
    if email is not None:
        payload["email"] = email
    else:
        payload["email"] = f"ho-{_uniq()}@example.com"
    return get_success_data(api_client.create_homeowner(payload, ANON))


def register_installer(licensed_states=("CA",), company_name="SunCo"):
    payload = F.create_installer_payload(
        company_name=company_name, licensed_states=list(licensed_states)
    )
    return get_success_data(api_client.create_installer(payload, ANON))


def register_utility(state_code="CA", feeder_headroom_kw=1000.0,
                     net_metering_rate_cents_per_kwh=15.0, export_credit_ratio=None):
    payload = F.create_utility_payload(
        state_code=state_code,
        feeder_headroom_kw=feeder_headroom_kw,
        net_metering_rate_cents_per_kwh=net_metering_rate_cents_per_kwh,
    )
    if export_credit_ratio is not None:
        payload["export_credit_ratio"] = export_credit_ratio
    return get_success_data(api_client.create_utility(payload, ADMIN))


def register_broker(broker_fee_pct=0.04, operating_states=("CA",), firm_name="GreenBroker"):
    payload = F.create_broker_payload(
        firm_name=firm_name, broker_fee_pct=broker_fee_pct,
        operating_states=list(operating_states),
    )
    return get_success_data(api_client.create_broker(payload, ANON))


_counter = [0]


def _uniq():
    _counter[0] += 1
    return _counter[0]


# ---------------------------------------------------------------------------
# Tier 1: project state progression
# ---------------------------------------------------------------------------

def create_requested_project(homeowner=None, roof_area_sqft=700, state_code="CA"):
    """Returns (homeowner, project). Project at REQUESTED."""
    if homeowner is None:
        homeowner = register_homeowner(state_code=state_code)
    ho_headers = make_homeowner_headers(homeowner["id"])
    project = get_success_data(api_client.create_project(
        F.create_project_payload(homeowner_id=homeowner["id"], roof_area_sqft=roof_area_sqft),
        ho_headers,
    ))
    return homeowner, project


def create_assessed_project(homeowner=None, installer=None, roof_area_sqft=700,
                            shading_factor=0.10, peak_sun_hours=5.0, state_code="CA",
                            installer_states=("CA",)):
    """Returns (homeowner, installer, project). Project at ASSESSED."""
    if homeowner is None:
        homeowner = register_homeowner(state_code=state_code)
    if installer is None:
        installer = register_installer(licensed_states=installer_states)
    _, project = create_requested_project(homeowner=homeowner, roof_area_sqft=roof_area_sqft)
    inst_headers = make_installer_headers(installer["id"])
    get_success_data(api_client.assess_project(
        project["id"],
        F.assess_payload(shading_factor=shading_factor, peak_sun_hours=peak_sun_hours),
        inst_headers,
    ))
    return homeowner, installer, project


def create_designed_project(homeowner=None, installer=None, roof_area_sqft=700,
                            shading_factor=0.10, peak_sun_hours=5.0,
                            gross_system_cost_cents=3000000, state_code="CA",
                            installer_states=("CA",), annual_kwh_usage=12000):
    """Returns (homeowner, installer, project_after_design). Project at DESIGNED."""
    if homeowner is None:
        homeowner = register_homeowner(state_code=state_code, annual_kwh_usage=annual_kwh_usage)
    if installer is None:
        installer = register_installer(licensed_states=installer_states)
    homeowner, installer, project = create_assessed_project(
        homeowner=homeowner, installer=installer, roof_area_sqft=roof_area_sqft,
        shading_factor=shading_factor, peak_sun_hours=peak_sun_hours,
    )
    inst_headers = make_installer_headers(installer["id"])
    designed = get_success_data(api_client.design_project(
        project["id"],
        F.design_payload(installer_id=installer["id"],
                         gross_system_cost_cents=gross_system_cost_cents),
        inst_headers,
    ))
    return homeowner, installer, designed


# ---------------------------------------------------------------------------
# Tier 2: financing
# ---------------------------------------------------------------------------

def create_draft_plan(homeowner, project, model="LEASE", **plan_overrides):
    ho_headers = make_homeowner_headers(homeowner["id"])
    payload = F.create_financing_plan_payload(
        model=model, project_id=project["id"], **plan_overrides
    )
    return get_success_data(api_client.create_financing_plan(payload, ho_headers))


def create_active_plan(homeowner=None, installer=None, model="LEASE",
                       gross_system_cost_cents=3000000, state_code="CA",
                       installer_states=("CA",), annual_kwh_usage=12000,
                       **plan_overrides):
    """Returns (homeowner, installer, designed_project, active_plan)."""
    homeowner, installer, project = create_designed_project(
        homeowner=homeowner, installer=installer,
        gross_system_cost_cents=gross_system_cost_cents, state_code=state_code,
        installer_states=installer_states, annual_kwh_usage=annual_kwh_usage,
    )
    plan = create_draft_plan(homeowner, project, model=model, **plan_overrides)
    ho_headers = make_homeowner_headers(homeowner["id"])
    plan = get_success_data(api_client.activate_financing_plan(
        plan["id"], {"expected_project_version": project["version"]}, ho_headers
    ))
    return homeowner, installer, project, plan


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle to OPERATIONAL
# ---------------------------------------------------------------------------

def drive_to_installed(homeowner, installer, project):
    """From DESIGNED (with ACTIVE plan) through to INSTALLED. Returns nothing new."""
    inst_headers = make_installer_headers(installer["id"])
    get_success_data(api_client.submit_permit(project["id"], inst_headers))
    get_success_data(api_client.approve_permit(project["id"], ADMIN))
    get_success_data(api_client.complete_install(project["id"], inst_headers))


def setup_operational_project(state_code="CA", installer_states=("CA",),
                              feeder_headroom_kw=1000.0,
                              net_metering_rate_cents_per_kwh=15.0,
                              export_credit_ratio=None,
                              requested_export_kw=7.0,
                              model="LEASE",
                              gross_system_cost_cents=3000000,
                              annual_kwh_usage=12000,
                              utility=None):
    """Full lifecycle through OPERATIONAL.

    Returns dict with keys: homeowner, installer, utility, project, plan, app,
    plus ready-made header dicts ho_headers / inst_headers / util_headers.
    The returned `project` is re-fetched so its version/status are current.
    """
    homeowner, installer, project, plan = create_active_plan(
        model=model, gross_system_cost_cents=gross_system_cost_cents,
        state_code=state_code, installer_states=installer_states,
        annual_kwh_usage=annual_kwh_usage,
    )
    if utility is None:
        utility = register_utility(
            state_code=state_code, feeder_headroom_kw=feeder_headroom_kw,
            net_metering_rate_cents_per_kwh=net_metering_rate_cents_per_kwh,
            export_credit_ratio=export_credit_ratio,
        )
    inst_headers = make_installer_headers(installer["id"])
    util_headers = make_utility_headers(utility["id"])
    ho_headers = make_homeowner_headers(homeowner["id"])

    drive_to_installed(homeowner, installer, project)
    app = get_success_data(api_client.create_interconnection_application(
        F.create_interconnection_application_payload(
            project_id=project["id"], utility_id=utility["id"],
            requested_export_kw=requested_export_kw,
        ),
        inst_headers,
    ))
    get_success_data(api_client.begin_review(app["id"], util_headers))
    get_success_data(api_client.approve_interconnection(app["id"], util_headers))
    get_success_data(api_client.inspect_project(project["id"], {"result": "PASS"}, ADMIN))
    get_success_data(api_client.grant_pto(app["id"], util_headers))

    project = get_success_data(api_client.get_project(project["id"], ho_headers))
    return {
        "homeowner": homeowner,
        "installer": installer,
        "utility": utility,
        "project": project,
        "plan": plan,
        "app": app,
        "ho_headers": ho_headers,
        "inst_headers": inst_headers,
        "util_headers": util_headers,
    }


# ---------------------------------------------------------------------------
# Tier 3b: interconnection-only progressions (no operational requirement)
# ---------------------------------------------------------------------------

def setup_under_review_application(feeder_headroom_kw=1000.0, requested_export_kw=7.0,
                                   state_code="CA"):
    """DESIGNED+ACTIVE project driven to INSTALLED, app at UNDER_REVIEW.
    Returns dict: homeowner, installer, utility, project, app, headers."""
    homeowner, installer, project, plan = create_active_plan(state_code=state_code)
    utility = register_utility(state_code=state_code, feeder_headroom_kw=feeder_headroom_kw)
    inst_headers = make_installer_headers(installer["id"])
    util_headers = make_utility_headers(utility["id"])
    drive_to_installed(homeowner, installer, project)
    app = get_success_data(api_client.create_interconnection_application(
        F.create_interconnection_application_payload(
            project_id=project["id"], utility_id=utility["id"],
            requested_export_kw=requested_export_kw,
        ),
        inst_headers,
    ))
    get_success_data(api_client.begin_review(app["id"], util_headers))
    return {
        "homeowner": homeowner, "installer": installer, "utility": utility,
        "project": project, "app": app,
        "ho_headers": make_homeowner_headers(homeowner["id"]),
        "inst_headers": inst_headers, "util_headers": util_headers,
    }


def setup_installed_with_approved_app(feeder_headroom_kw=1000.0, requested_export_kw=7.0,
                                      state_code="CA"):
    """Project at INSTALLED (inspection not run) with its app APPROVED.
    Returns dict: homeowner, installer, utility, project, app, headers."""
    ctx = setup_under_review_application(
        feeder_headroom_kw=feeder_headroom_kw, requested_export_kw=requested_export_kw,
        state_code=state_code,
    )
    get_success_data(api_client.approve_interconnection(ctx["app"]["id"], ctx["util_headers"]))
    return ctx


def setup_pto_pending_with_approved_app(feeder_headroom_kw=1000.0, requested_export_kw=7.0,
                                        state_code="CA"):
    """Project at PTO_PENDING (inspection PASS) with its app APPROVED, PTO not yet granted.
    Returns dict: homeowner, installer, utility, project, app, headers."""
    ctx = setup_installed_with_approved_app(
        feeder_headroom_kw=feeder_headroom_kw, requested_export_kw=requested_export_kw,
        state_code=state_code,
    )
    get_success_data(api_client.inspect_project(ctx["project"]["id"], {"result": "PASS"}, ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: SREC pools, periods, claims on operational projects
# ---------------------------------------------------------------------------

def mint_and_list_srecs(project_id, homeowner_id, count, vintage_year=2026):
    """Mint `count` SRECs and LIST each. Returns list of srec ids."""
    ho_headers = make_homeowner_headers(homeowner_id)
    ids = []
    for _ in range(count):
        srec = get_success_data(api_client.mint_srec(
            {"project_id": project_id, "vintage_year": vintage_year}, ADMIN
        ))
        get_success_data(api_client.list_srec_for_sale(srec["id"], ho_headers))
        ids.append(srec["id"])
    return ids


def mint_srecs(project_id, count, vintage_year=2026):
    """Mint `count` SRECs WITHOUT listing them. Returns list of srec ids."""
    ids = []
    for _ in range(count):
        srec = get_success_data(api_client.mint_srec(
            {"project_id": project_id, "vintage_year": vintage_year}, ADMIN
        ))
        ids.append(srec["id"])
    return ids


def open_period(ctx, period_start, period_end, kwh_produced, kwh_consumed):
    """Create an OPEN net-meter period on the operational project in ctx."""
    return get_success_data(api_client.create_net_meter_period(
        F.create_net_meter_period_payload(
            project_id=ctx["project"]["id"], period_start=period_start,
            period_end=period_end, kwh_produced=kwh_produced, kwh_consumed=kwh_consumed,
        ),
        ctx["util_headers"],
    ))


def settle_period(ctx, period_id):
    return get_success_data(api_client.settle_net_meter_period(period_id, ctx["util_headers"]))


def current_project_version(ctx):
    """Re-read the project and return its current version (for OCC payloads)."""
    proj = get_success_data(api_client.get_project(ctx["project"]["id"], ctx["ho_headers"]))
    return proj["version"]
