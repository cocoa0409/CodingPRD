"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server and empties the database before every
test). Setup steps use get_success_data (lenient) so a broken precondition
surfaces as a clear "Setup step failed" rather than a confusing assertion.

Entity-backed identity threading: after creating a Customer/Designer, every
ownership-gated call uses make_customer_headers(customer["id"]) /
make_designer_headers(designer["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_designer_headers,
)
from .factories import (
    create_customer_payload,
    create_designer_payload,
    create_crew_payload,
    create_project_payload,
    create_design_appointment_payload,
    create_quote_payload,
    create_warranty_claim_payload,
    create_referral_payload,
)

PA = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["install_coordinator_headers"]
FO = TEST_USERS["finance_officer_headers"]

DEFAULT_APPT_START = "2026-05-10T14:00:00Z"
DEFAULT_APPT_END = "2026-05-10T15:00:00Z"
DEFAULT_INSTALL_DATE = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Base creators
# ---------------------------------------------------------------------------

def create_designer(api, **overrides):
    return get_success_data(api.create_designer(create_designer_payload(**overrides), PA))


def create_customer(api, **overrides):
    return get_success_data(api.create_customer(create_customer_payload(**overrides), PA))


def create_crew(api, **overrides):
    return get_success_data(api.create_crew(create_crew_payload(**overrides), PA))


def create_project(api, customer_id, **overrides):
    return get_success_data(api.create_project(create_project_payload(customer_id, **overrides), IC))


def create_referral(api, referrer_customer_id, **overrides):
    return get_success_data(
        api.create_referral(create_referral_payload(referrer_customer_id, **overrides), PA)
    )


def get_project_version(api, project_id):
    project = get_success_data(api.get_project(project_id, IC))
    return project["version"]


def refresh_project(api, project_id):
    return get_success_data(api.get_project(project_id, IC))


def refresh_quote(api, quote_id):
    return get_success_data(api.get_quote(quote_id, IC))


def refresh_referral(api, referral_id):
    return get_success_data(api.get_referral(referral_id, IC))


def refresh_customer(api, customer_id):
    return get_success_data(api.get_customer(customer_id, IC))


def set_clock(api, iso8601):
    return api.set_clock({"to_iso8601": iso8601}, PA)


# ---------------------------------------------------------------------------
# Tier 1/2: reach DESIGN_COMPLETE (measured area recorded)
# ---------------------------------------------------------------------------

def setup_design_complete_project(api, area=100.0, customer=None, designer=None,
                                  appt_start=DEFAULT_APPT_START, appt_end=DEFAULT_APPT_END,
                                  bathroom_type="FULL_BATH"):
    """Designer + customer + project driven to DESIGN_COMPLETE with the measured
    wall area recorded. Returns a context dict with the current project version."""
    designer = designer or create_designer(api)
    customer = customer or create_customer(api)
    project = create_project(api, customer["id"], bathroom_type=bathroom_type)
    appt = get_success_data(api.create_design_appointment(
        create_design_appointment_payload(
            project["id"], designer["id"],
            scheduled_start=appt_start, scheduled_end=appt_end,
        ), IC))
    get_success_data(api.complete_design_appointment(
        appt["id"], {"measured_wall_area_sqft": area}, make_designer_headers(designer["id"])))
    version = get_project_version(api, project["id"])
    return {
        "designer": designer,
        "customer": customer,
        "project": project,
        "appointment": appt,
        "version": version,
    }


# ---------------------------------------------------------------------------
# Tier 3: quote lifecycle (draft -> presented -> accepted)
# ---------------------------------------------------------------------------

def create_quote_on(api, ctx, **quote_over):
    """Create a DRAFT quote on a DESIGN_COMPLETE project using its current version."""
    version = get_project_version(api, ctx["project"]["id"])
    quote = get_success_data(api.create_quote(
        create_quote_payload(ctx["project"]["id"], version, **quote_over),
        make_designer_headers(ctx["designer"]["id"])))
    ctx["version"] = version + 1  # quote create advances the project version by 1
    ctx["quote"] = quote
    return quote


def setup_presented_quote(api, area=100.0, customer=None, **quote_over):
    """DESIGN_COMPLETE project + a PRESENTED quote (project QUOTED). Returns ctx
    with the refreshed presented quote under ctx['quote']."""
    ctx = setup_design_complete_project(api, area=area, customer=customer)
    quote = create_quote_on(api, ctx, **quote_over)
    get_success_data(api.present_quote(quote["id"], make_designer_headers(ctx["designer"]["id"])))
    ctx["quote"] = refresh_quote(api, quote["id"])
    return ctx


def setup_accepted_quote(api, area=100.0, customer=None, **quote_over):
    """PRESENTED quote accepted by the owning customer (project SOLD then branched).
    Returns ctx with refreshed quote and project."""
    ctx = setup_presented_quote(api, area=area, customer=customer, **quote_over)
    get_success_data(api.accept_quote(
        ctx["quote"]["id"], make_customer_headers(ctx["customer"]["id"])))
    ctx["quote"] = refresh_quote(api, ctx["quote"]["id"])
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_install_ready_project(api, area=100.0, customer=None, **quote_over):
    """Accept the quote and, if a permit is required, resolve it APPROVED so the
    project reaches INSTALL_READY. Returns ctx with the INSTALL_READY project."""
    ctx = setup_accepted_quote(api, area=area, customer=customer, **quote_over)
    if ctx["project"].get("permit_required"):
        get_success_data(api.resolve_permit(ctx["project"]["id"], {"outcome": "APPROVED"}, IC))
        ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_scheduled_install(api, area=100.0, crew=None, install_date=DEFAULT_INSTALL_DATE,
                            customer=None, **quote_over):
    """INSTALL_READY project + one BOOKED install (project INSTALL_SCHEDULED)."""
    ctx = setup_install_ready_project(api, area=area, customer=customer, **quote_over)
    crew = crew or create_crew(api, accessibility_certified=True)
    booking = get_success_data(api.create_install_booking(
        {"project_id": ctx["project"]["id"], "crew_id": crew["id"], "install_date": install_date}, IC))
    ctx["crew"] = crew
    ctx["booking"] = booking
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_installed_project(api, area=100.0, customer=None, **quote_over):
    """Full lifecycle through INSTALLED (warranty ACTIVE)."""
    ctx = setup_scheduled_install(api, area=area, customer=customer, **quote_over)
    get_success_data(api.complete_install_booking(ctx["booking"]["id"], IC))
    ctx["booking"] = get_success_data(api.get_install_booking(ctx["booking"]["id"], IC))
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_installed_with_claim(api, area=100.0, defect_type="CRACK",
                               description="hairline crack near the drain", customer=None):
    """INSTALLED project + one SUBMITTED warranty claim."""
    ctx = setup_installed_project(api, area=area, customer=customer)
    claim = get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(ctx["project"]["id"], defect_type=defect_type,
                                       description=description),
        make_customer_headers(ctx["customer"]["id"])))
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: financing
# ---------------------------------------------------------------------------

def setup_presented_financed_quote(api, area, financing_plan_code, requested_amount_cents,
                                   stated_annual_income_cents, **quote_over):
    """A PRESENTED quote whose financing is REQUESTED (plan chosen at creation)."""
    return setup_presented_quote(
        api, area=area,
        financing_plan_code=financing_plan_code,
        requested_amount_cents=requested_amount_cents,
        stated_annual_income_cents=stated_annual_income_cents,
        **quote_over)


# ---------------------------------------------------------------------------
# Tier 4/5: referral scenarios and temporal-resource setups
# ---------------------------------------------------------------------------

def setup_referral_registered(api, program_tier="STANDARD"):
    """A referrer with an ISSUED referral, and a referred customer registered via
    the code (referral REGISTERED). Returns referrer, referral, referred customer."""
    referrer = create_customer(api)
    referral = create_referral(api, referrer["id"], program_tier=program_tier)
    referred = create_customer(api, referral_code_used=referral["referral_code"])
    return {"referrer": referrer, "referral": referral, "referred": referred}


def setup_referral_presented_quote(api, program_tier="STANDARD", area=100.0, **quote_over):
    """Referrer + registered referred customer + the referred customer's project
    driven to a PRESENTED quote (ready to accept, which will reward the referral)."""
    ref = setup_referral_registered(api, program_tier=program_tier)
    ctx = setup_presented_quote(api, area=area, customer=ref["referred"], **quote_over)
    ctx["referrer"] = ref["referrer"]
    ctx["referral"] = ref["referral"]
    return ctx


def setup_referral_rewarded(api, program_tier="STANDARD", area=100.0, **quote_over):
    """Referrer credited from a REWARDED referral: the referred customer's project
    is accepted (SOLD), rewarding the referral. Returns the full context."""
    ctx = setup_referral_presented_quote(api, program_tier=program_tier, area=area, **quote_over)
    get_success_data(api.accept_quote(
        ctx["quote"]["id"], make_customer_headers(ctx["customer"]["id"])))
    ctx["quote"] = refresh_quote(api, ctx["quote"]["id"])
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    ctx["referral"] = refresh_referral(api, ctx["referral"]["id"])
    ctx["referrer"] = refresh_customer(api, ctx["referrer"]["id"])
    return ctx


def setup_designer_with_appointment(api, start=DEFAULT_APPT_START, end=DEFAULT_APPT_END):
    """One designer holding a SCHEDULED appointment for project P1, plus a fresh
    LEAD project P2 owned by the same customer to book against the same designer."""
    designer = create_designer(api)
    customer = create_customer(api)
    proj1 = create_project(api, customer["id"])
    appt1 = get_success_data(api.create_design_appointment(
        create_design_appointment_payload(
            proj1["id"], designer["id"], scheduled_start=start, scheduled_end=end), IC))
    proj2 = create_project(api, customer["id"], bathroom_type="SHOWER_ONLY")
    return {"designer": designer, "customer": customer,
            "proj1": proj1, "appt1": appt1, "proj2": proj2}
