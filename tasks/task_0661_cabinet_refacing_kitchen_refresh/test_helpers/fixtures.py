"""Composite setup helpers.

These encapsulate the multi-step preambles that most test claims need to reach
an interesting state (a COMPLETED measure, a QUOTED quote, a SOLD project, an
IN_PRODUCTION project with a READY material order, an INSTALLED project, etc.).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before every test. Setup calls
use get_success_data() (lenient) so setup breakage surfaces as a clear failure.

Identity threading: a Customer is the only entity_backed role, so every
ownership-gated call (approve/decline/accept/reject/financing/warranty) uses
make_customer_headers(customer_id) with the real Customer.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)
from . import factories as f
from .constants import CLOCK_DEFAULT

_SALES = TEST_USERS["sales_rep_headers"]
_SCHED = TEST_USERS["scheduler_headers"]
_CREW = TEST_USERS["install_crew_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Move the logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, _ADMIN))


def reset_clock():
    """Set the clock to the documented startup default 2026-04-01T00:00:00Z."""
    return set_clock(CLOCK_DEFAULT)


# ---------------------------------------------------------------------------
# Tier 1: primitive creation
# ---------------------------------------------------------------------------
def create_customer(**overrides):
    return get_success_data(api_client.create_customer(f.create_customer_payload(**overrides), _SALES))


def create_project(customer_id, **overrides):
    return get_success_data(
        api_client.create_project(f.create_project_payload(customer_id, **overrides), _SALES)
    )


def create_customer_and_project(customer_overrides=None, project_overrides=None):
    """Returns (customer, project) — customer in default state, project in LEAD."""
    cust = create_customer(**(customer_overrides or {}))
    proj = create_project(cust["id"], **(project_overrides or {}))
    return cust, proj


def schedule_measure(project_id, **overrides):
    return get_success_data(
        api_client.create_measure(project_id, f.create_measure_payload(**overrides), _SALES)
    )


def complete_measure(project_id, measure_id, **overrides):
    return get_success_data(
        api_client.complete_measure(project_id, measure_id, f.complete_measure_payload(**overrides), _SALES)
    )


# ---------------------------------------------------------------------------
# Tier 2: project with a COMPLETED measure
# ---------------------------------------------------------------------------
def setup_project_with_completed_measure(linear_feet=25, door_count=18,
                                         finish_code="WOOD_VENEER", door_style="SHAKER",
                                         customer_overrides=None):
    """Customer + LEAD project + COMPLETED Measure (dims copied onto project).

    Returns (customer, project, measure). Project will be MEASURED afterward.
    """
    cust, proj = create_customer_and_project(customer_overrides=customer_overrides)
    meas = schedule_measure(proj["id"])
    meas = complete_measure(proj["id"], meas["id"], linear_feet=linear_feet,
                            door_count=door_count, finish_code=finish_code,
                            door_style=door_style)
    return cust, proj, meas


# ---------------------------------------------------------------------------
# Tier 3: quote lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_draft_quote(project_id, measure_id, scope="REFACE"):
    return get_success_data(
        api_client.create_quote(project_id, f.create_quote_payload(measure_id, scope=scope), _SALES)
    )


def setup_draft_quote(scope="REFACE", linear_feet=25, door_count=18,
                      finish_code="WOOD_VENEER", customer_overrides=None):
    """Returns (customer, project, measure, quote) with the quote in DRAFT."""
    cust, proj, meas = setup_project_with_completed_measure(
        linear_feet=linear_feet, door_count=door_count, finish_code=finish_code,
        customer_overrides=customer_overrides)
    quote = create_draft_quote(proj["id"], meas["id"], scope=scope)
    return cust, proj, meas, quote


def setup_quoted_quote(scope="REFACE", linear_feet=25, door_count=18,
                       finish_code="WOOD_VENEER", customer_overrides=None):
    """Returns (customer, project, measure, quote) with the quote QUOTED (issued).

    The returned quote dict carries the post-issue version.
    """
    cust, proj, meas, quote = setup_draft_quote(
        scope=scope, linear_feet=linear_feet, door_count=door_count,
        finish_code=finish_code, customer_overrides=customer_overrides)
    quote = get_success_data(api_client.issue_quote(quote["id"], _SALES))
    return cust, proj, meas, quote


def setup_approved_quote(scope="REFACE", linear_feet=25, door_count=18,
                         finish_code="WOOD_VENEER", customer_overrides=None):
    """Returns (customer, project, measure, quote) with the quote APPROVED and
    the project SOLD. The returned quote dict carries the post-approve version.
    """
    cust, proj, meas, quote = setup_quoted_quote(
        scope=scope, linear_feet=linear_feet, door_count=door_count,
        finish_code=finish_code, customer_overrides=customer_overrides)
    quote = get_success_data(
        api_client.approve_quote(
            quote["id"], {"expected_quote_version": quote["version"]},
            make_customer_headers(cust["id"]))
    )
    return cust, proj, meas, quote


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------
def propose_addon(quote_id, kind="HARDWARE", unit_price_cents=850, quantity=24):
    return get_success_data(
        api_client.create_addon(
            quote_id, f.create_addon_payload(kind=kind, unit_price_cents=unit_price_cents,
                                             quantity=quantity), _SALES)
    )


def approve_addon(addon_id):
    return get_success_data(api_client.approve_addon(addon_id, _SALES))


def remove_addon(addon_id):
    return get_success_data(api_client.remove_addon(addon_id, _SALES))


# ---------------------------------------------------------------------------
# Material orders
# ---------------------------------------------------------------------------
def place_material_order(project_id, quote_id):
    return get_success_data(
        api_client.create_material_order(project_id, f.create_material_order_payload(quote_id), _SCHED)
    )


def setup_in_production(scope="REFACE", linear_feet=25, door_count=18,
                        finish_code="WOOD_VENEER", customer_overrides=None):
    """Reset clock to default, build APPROVED quote, place a MaterialOrder.

    Returns (customer, project, measure, quote, material_order). Project is
    IN_PRODUCTION; the MaterialOrder is PLACED with computed ready_at.
    """
    reset_clock()
    cust, proj, meas, quote = setup_approved_quote(
        scope=scope, linear_feet=linear_feet, door_count=door_count,
        finish_code=finish_code, customer_overrides=customer_overrides)
    mo = place_material_order(proj["id"], quote["id"])
    return cust, proj, meas, quote, mo


def setup_material_order_ready(scope="REFACE", linear_feet=25, door_count=18,
                               finish_code="WOOD_VENEER", ready_clock="2026-06-15T00:00:00Z",
                               customer_overrides=None):
    """IN_PRODUCTION with the MaterialOrder marked READY (clock advanced past
    ready_at). Returns (customer, project, measure, quote, material_order).
    The returned material_order dict carries READY status.
    """
    cust, proj, meas, quote, mo = setup_in_production(
        scope=scope, linear_feet=linear_feet, door_count=door_count,
        finish_code=finish_code, customer_overrides=customer_overrides)
    set_clock(ready_clock)
    mo = get_success_data(api_client.mark_ready_material_order(mo["id"], _SCHED))
    return cust, proj, meas, quote, mo


# ---------------------------------------------------------------------------
# Crews + install jobs
# ---------------------------------------------------------------------------
def create_crew(name="Test Crew", daily_job_capacity=2,
                skill_finishes=("WOOD_VENEER",), is_active=True):
    payload = f.create_crew_payload(name=name, daily_job_capacity=daily_job_capacity,
                                    skill_finishes=list(skill_finishes), is_active=is_active)
    return get_success_data(api_client.create_crew(payload, _SCHED))


def schedule_install_job(project_id, material_order_id, crew_id,
                         window_start="2026-06-16T08:00:00Z",
                         window_end="2026-06-16T17:00:00Z"):
    payload = f.create_install_job_payload(material_order_id, crew_id,
                                           window_start=window_start, window_end=window_end)
    return get_success_data(api_client.create_install_job(project_id, payload, _SCHED))


def setup_scheduled_install(scope="REFACE", linear_feet=25, door_count=18,
                            finish_code="WOOD_VENEER",
                            ready_clock="2026-06-15T00:00:00Z",
                            window_start="2026-06-16T08:00:00Z",
                            window_end="2026-06-16T17:00:00Z",
                            crew_finishes=("WOOD_VENEER",),
                            daily_job_capacity=2,
                            customer_overrides=None):
    """Full chain to a SCHEDULED InstallJob on an IN_PRODUCTION project with a
    READY MaterialOrder and a certified crew.

    Returns (customer, project, measure, quote, material_order, crew, install_job).
    """
    cust, proj, meas, quote, mo = setup_material_order_ready(
        scope=scope, linear_feet=linear_feet, door_count=door_count,
        finish_code=finish_code, ready_clock=ready_clock,
        customer_overrides=customer_overrides)
    crew = create_crew(skill_finishes=crew_finishes, daily_job_capacity=daily_job_capacity)
    ij = schedule_install_job(proj["id"], mo["id"], crew["id"],
                              window_start=window_start, window_end=window_end)
    return cust, proj, meas, quote, mo, crew, ij


def setup_installed_project(scope="REFACE", linear_feet=25, door_count=18,
                            finish_code="WOOD_VENEER",
                            ready_clock="2026-05-05T00:00:00Z",
                            window_start="2026-05-06T08:00:00Z",
                            window_end="2026-05-06T17:00:00Z",
                            start_clock="2026-05-06T08:00:00Z",
                            customer_overrides=None):
    """Drive a project all the way to INSTALLED: schedule install, advance clock
    to window_start, start and complete the install.

    Returns (customer, project, measure, quote, material_order, crew, install_job).
    The install_job dict carries DONE status; the project is INSTALLED.
    """
    cust, proj, meas, quote, mo, crew, ij = setup_scheduled_install(
        scope=scope, linear_feet=linear_feet, door_count=door_count,
        finish_code=finish_code, ready_clock=ready_clock,
        window_start=window_start, window_end=window_end,
        crew_finishes=(finish_code,), customer_overrides=customer_overrides)
    set_clock(start_clock)
    get_success_data(api_client.start_install_job(ij["id"], _CREW))
    ij = get_success_data(api_client.complete_install_job(ij["id"], _CREW))
    return cust, proj, meas, quote, mo, crew, ij


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------
def raise_change_order(quote_id, delta_linear_feet=0, delta_door_count=0, rush=False):
    payload = f.create_change_order_payload(delta_linear_feet=delta_linear_feet,
                                            delta_door_count=delta_door_count, rush=rush)
    return get_success_data(api_client.create_change_order(quote_id, payload, _SALES))


def setup_approved_quote_with_pending_change_order(delta_linear_feet=4, delta_door_count=2,
                                                   rush=False, scope="REFACE",
                                                   linear_feet=25, door_count=18,
                                                   finish_code="WOOD_VENEER"):
    """APPROVED quote on a SOLD project plus a PENDING change order (no material
    order yet). Returns (customer, project, measure, quote, change_order).
    The quote dict carries the post-approve version.
    """
    cust, proj, meas, quote = setup_approved_quote(
        scope=scope, linear_feet=linear_feet, door_count=door_count, finish_code=finish_code)
    co = raise_change_order(quote["id"], delta_linear_feet=delta_linear_feet,
                            delta_door_count=delta_door_count, rush=rush)
    return cust, proj, meas, quote, co


# ---------------------------------------------------------------------------
# Financing
# ---------------------------------------------------------------------------
def submit_financing_application(project_id, customer_id, customer_user_id,
                                 amount_cents=2_000_000, term_months=36):
    payload = f.create_financing_application_payload(customer_id, amount_cents=amount_cents,
                                                     term_months=term_months)
    return get_success_data(
        api_client.create_financing_application(project_id, payload,
                                                make_customer_headers(customer_user_id))
    )


def setup_submitted_financing(annual_income_cents=3_800_000, amount_cents=2_000_000,
                              term_months=36):
    """Customer + project + SUBMITTED FinancingApplication.

    Returns (customer, project, financing_application).
    """
    cust, proj = create_customer_and_project(
        customer_overrides={"annual_income_cents": annual_income_cents})
    fa = submit_financing_application(proj["id"], cust["id"], cust["id"],
                                      amount_cents=amount_cents, term_months=term_months)
    return cust, proj, fa
