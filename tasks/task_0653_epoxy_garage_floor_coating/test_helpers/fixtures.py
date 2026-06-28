"""Composite setup helpers.

The Epoxy domain's interesting claims all sit deep inside a long lifecycle:
catalog -> customer -> project -> assessment -> estimate quote -> send ->
accept -> book install -> start -> complete (creates FINAL quote) ->
mark-cured (creates Warranty, converts Referral). These helpers encapsulate
the multi-step preambles so tests focus on assertions.

All setup calls use get_success_data() (lenient) so a setup miss surfaces as a
clear "Setup failed" rather than a confusing assertion error.

Identity threading: Customer and Crew are entity_backed. Ownership-gated calls
(accept/decline/claim/resubmit for Customer; start/complete for Crew) MUST use
make_customer_headers(customer_id) / make_crew_headers(crew_id) — never the
shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers, make_crew_headers
from .factories import (
    create_coating_system_payload, create_color_option_payload,
    create_financing_plan_payload, create_crew_payload, create_customer_payload,
    create_project_payload, create_assessment_payload, create_quote_payload,
    create_install_job_payload, complete_install_payload, create_claim_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AGENT = TEST_USERS["warranty_agent_headers"]


# --------------------------------------------------------------------------
# Tier 0: logical clock + catalog primitives
# --------------------------------------------------------------------------
def set_clock(iso: str):
    get_success_data(api_client.set_clock(iso, ADMIN))


def create_coating_system(name="Sys", family="FLAKE", sku="FLAKE_STANDARD", **ov):
    payload = create_coating_system_payload(name=name, family=family, sku=sku, **ov)
    return get_success_data(api_client.create_coating_system(payload, ADMIN))


def create_color_option(coating_system_id, name="Color", code="C-01", **ov):
    payload = create_color_option_payload(
        coating_system_id, name=name, flake_blend_code=code, **ov
    )
    return get_success_data(api_client.create_color_option(payload, ADMIN))


def create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD"):
    """Returns (coating_system, color_option) with the color under the system."""
    sys = create_coating_system(name=f"{sku} Sys", family=family, sku=sku)
    color = create_color_option(sys["id"], name=f"{sku} Color", code=f"{sku[:3]}-01")
    return sys, color


def create_financing_plan(name="Plan", apr_bps=999, term_months=36,
                          min_principal_cents=0, **ov):
    payload = create_financing_plan_payload(
        name=name, apr_bps=apr_bps, term_months=term_months,
        min_principal_cents=min_principal_cents, **ov
    )
    return get_success_data(api_client.create_financing_plan(payload, ADMIN))


def create_crew(name="Crew", metallic_certified=False, max_sqft_per_day=1000, **ov):
    payload = create_crew_payload(
        name=name, metallic_certified=metallic_certified,
        max_sqft_per_day=max_sqft_per_day, **ov
    )
    return get_success_data(api_client.create_crew(payload, ADMIN))


def create_customer(full_name="Owner", email=None):
    email = email or f"{full_name.lower().replace(' ', '')}@example.com"
    payload = create_customer_payload(full_name=full_name, email=email)
    return get_success_data(api_client.create_customer(payload, SALES))


# --------------------------------------------------------------------------
# Tier 1: project + assessment
# --------------------------------------------------------------------------
def create_project(customer_id, site_zip="94016", referral_code=None):
    overrides = {"site_zip": site_zip}
    if referral_code is not None:
        overrides["referral_code"] = referral_code
    payload = create_project_payload(customer_id, **overrides)
    return get_success_data(api_client.create_project(payload, SALES))


def record_assessment(project_id, measured_sqft=600, oil_stain_pct=50,
                      crack_density=20, crack_linear_ft=15, spalling=True,
                      moisture_pct=30):
    payload = create_assessment_payload(
        measured_sqft=measured_sqft, oil_stain_pct=oil_stain_pct,
        crack_density=crack_density, crack_linear_ft=crack_linear_ft,
        spalling=spalling, moisture_pct=moisture_pct,
    )
    return get_success_data(api_client.create_assessment(project_id, payload, SALES))


def setup_project_with_assessment(customer_id=None, assessment_kwargs=None,
                                  site_zip="94016", referral_code=None):
    """Customer (if not given) + LEAD project + one APPROVED assessment.
    Returns (customer, project, assessment)."""
    if customer_id is None:
        customer = create_customer("Assess Owner")
        customer_id = customer["id"]
    else:
        customer = get_success_data(api_client.get_customer(customer_id, SALES))
    project = create_project(customer_id, site_zip=site_zip, referral_code=referral_code)
    assessment = record_assessment(project["id"], **(assessment_kwargs or {}))
    return customer, project, assessment


# --------------------------------------------------------------------------
# Tier 2: estimate quote (priced) + send
# --------------------------------------------------------------------------
def create_estimate_quote(project_id, assessment_id, coating_system_id,
                          color_option_id, install_season="STANDARD",
                          financing_plan_id=None):
    overrides = {}
    if financing_plan_id is not None:
        overrides["financing_plan_id"] = financing_plan_id
    payload = create_quote_payload(
        assessment_id, coating_system_id, color_option_id,
        install_season=install_season, **overrides
    )
    return get_success_data(api_client.create_quote(project_id, payload, SALES))


def send_quote(quote_id):
    return get_success_data(api_client.send_quote(quote_id, SALES))


def project_version(project_id, headers=None):
    proj = get_success_data(api_client.get_project(project_id, headers or SALES))
    return proj["version"]


def setup_sent_quote(family="FLAKE", sku="FLAKE_STANDARD", install_season="STANDARD",
                     assessment_kwargs=None, financing_plan_id=None,
                     coating_system_id=None, color_option_id=None,
                     customer_id=None):
    """Catalog + project + assessment + ESTIMATE quote, DRAFT then SENT
    (project moves to QUOTED). Returns dict of all created handles."""
    if coating_system_id is None:
        sys, color = create_system_with_color(family=family, sku=sku)
        coating_system_id, color_option_id = sys["id"], color["id"]
    else:
        sys = get_success_data(api_client.get_coating_system(coating_system_id, SALES))
        color = None
    customer, project, assessment = setup_project_with_assessment(
        customer_id=customer_id, assessment_kwargs=assessment_kwargs
    )
    quote = create_estimate_quote(
        project["id"], assessment["id"], coating_system_id, color_option_id,
        install_season=install_season, financing_plan_id=financing_plan_id,
    )
    send_quote(quote["id"])
    return {
        "system": sys, "color": color, "customer": customer, "project": project,
        "assessment": assessment, "quote": quote,
    }


def setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD",
                           install_season="STANDARD", assessment_kwargs=None,
                           financing_plan_id=None, coating_system_id=None,
                           color_option_id=None, customer_id=None):
    """A project whose sales_status is ACCEPTED (build still PRE_BUILD).
    Returns the same handle dict as setup_sent_quote, plus refreshed project."""
    h = setup_sent_quote(
        family=family, sku=sku, install_season=install_season,
        assessment_kwargs=assessment_kwargs, financing_plan_id=financing_plan_id,
        coating_system_id=coating_system_id, color_option_id=color_option_id,
        customer_id=customer_id,
    )
    cust = h["customer"]
    pv = project_version(h["project"]["id"])
    get_success_data(api_client.accept_quote(
        h["quote"]["id"], {"expected_project_version": pv},
        make_customer_headers(cust["id"]),
    ))
    h["project"] = get_success_data(api_client.get_project(h["project"]["id"], SALES))
    return h


# --------------------------------------------------------------------------
# Tier 3: install lifecycle
# --------------------------------------------------------------------------
def book_install(project_id, crew_id, install_date="2026-05-10T09:00:00Z"):
    payload = create_install_job_payload(crew_id, install_date)
    return get_success_data(api_client.create_install_job(project_id, payload, SCHED))


def setup_booked_install(crew_metallic=False, crew_capacity=1000,
                         install_date="2026-05-10T09:00:00Z", crew_id=None,
                         **accepted_kwargs):
    """Accepted project + a crew + a BOOKED install job.
    Returns handle dict with 'crew' and 'install_job' added."""
    h = setup_accepted_project(**accepted_kwargs)
    if crew_id is None:
        crew = create_crew(
            name="Install Crew", metallic_certified=crew_metallic,
            max_sqft_per_day=crew_capacity,
        )
        crew_id = crew["id"]
    else:
        crew = get_success_data(api_client.get_crew(crew_id, SCHED))
    job = book_install(h["project"]["id"], crew_id, install_date=install_date)
    h["crew"] = crew
    h["install_job"] = job
    return h


def setup_started_install(install_date="2026-05-10T09:00:00Z", **kw):
    """Booked install, clock advanced to install_date, install IN_PROGRESS.
    Returns handle dict."""
    h = setup_booked_install(install_date=install_date, **kw)
    set_clock(install_date)
    get_success_data(api_client.start_install_job(
        h["install_job"]["id"], make_crew_headers(h["crew"]["id"])
    ))
    return h


def setup_completed_install(install_date="2026-05-10T09:00:00Z",
                            as_measured_sqft=600, as_measured_crack_ft=15, **kw):
    """Started install completed with on-site numbers (creates FINAL quote;
    build_status -> CURING). Returns handle dict with 'final_quote'."""
    h = setup_started_install(install_date=install_date, **kw)
    get_success_data(api_client.complete_install_job(
        h["install_job"]["id"],
        complete_install_payload(as_measured_sqft, as_measured_crack_ft),
        make_crew_headers(h["crew"]["id"]),
    ))
    finals = get_success_data(
        api_client.list_quotes(h["project"]["id"], SALES, params={"variant": "FINAL"})
    )
    h["final_quote"] = finals[0] if finals else None
    return h


def setup_cured_project(install_date="2026-05-10T09:00:00Z",
                        cure_instant="2026-05-13T17:00:00Z",
                        as_measured_sqft=600, as_measured_crack_ft=15, **kw):
    """Completed install marked CURED (build_status -> COMPLETE), warranty created.
    cure_instant must be >= the job's vehicle_traffic_ok_at. Returns handle dict
    with 'warranty'."""
    h = setup_completed_install(
        install_date=install_date, as_measured_sqft=as_measured_sqft,
        as_measured_crack_ft=as_measured_crack_ft, **kw
    )
    set_clock(cure_instant)
    get_success_data(api_client.mark_cured(h["install_job"]["id"], SCHED))
    warr = get_success_data(
        api_client.list_project_warranties(h["project"]["id"], AGENT)
    )
    h["warranty"] = warr[0] if warr else None
    return h


# --------------------------------------------------------------------------
# Tier 4: warranty claim helpers
# --------------------------------------------------------------------------
def file_claim(warranty_id, customer_id, defect_type="PEEL"):
    return get_success_data(api_client.create_claim(
        warranty_id, create_claim_payload(defect_type=defect_type),
        make_customer_headers(customer_id),
    ))


def setup_submitted_claim(defect_type="PEEL",
                          install_date="2026-05-10T09:00:00Z",
                          cure_instant="2026-05-13T17:00:00Z",
                          claim_instant=None, **kw):
    """Cured project + warranty + a SUBMITTED claim of the given defect type.
    If claim_instant is set, the clock is advanced to it before filing (so
    months_elapsed can be controlled). Returns handle dict with 'claim'."""
    h = setup_cured_project(install_date=install_date, cure_instant=cure_instant, **kw)
    if claim_instant is not None:
        set_clock(claim_instant)
    h["claim"] = file_claim(
        h["warranty"]["id"], h["customer"]["id"], defect_type=defect_type
    )
    return h


# --------------------------------------------------------------------------
# Tier 5: referral helpers
# --------------------------------------------------------------------------
def setup_referral_pair():
    """Referrer + referred customers. Returns (referrer, referred)."""
    referrer = create_customer("Refa Referrer", email="refa@example.com")
    referred = create_customer("Newt Newcomer", email="newt@example.com")
    return referrer, referred
