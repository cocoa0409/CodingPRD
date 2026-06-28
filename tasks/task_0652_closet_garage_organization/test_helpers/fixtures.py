"""Composite setup helpers.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every test.
Fixtures use get_success_data() so setup failures surface as clear "Setup failed".

Identity threading: the Customer role is entity-backed, so every ownership-gated
call (accept quote, create deposit/financing, cancel, request-reschedule, file
warranty) uses make_customer_headers(customer_id) with the real Customer.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_designer_headers,
    make_scheduler_headers,
    make_manufacturing_ops_headers,
    make_platform_admin_headers,
)
from . import factories as f

DESIGNER = TEST_USERS["designer_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
MFG_OPS = TEST_USERS["manufacturing_ops_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(iso):
    """Set the server logical clock to an ISO instant (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def create_customer(zip_code="90001", **overrides):
    """Create a customer. zip 90001 -> WEST; 50000 -> EAST; 30301 -> SOUTH; 10001 -> NORTH."""
    payload = f.create_customer_payload(zip_code=zip_code, **overrides)
    return get_success_data(api_client.create_customer(payload))


def create_project(customer_id, room_type="WALK_IN_CLOSET", **overrides):
    payload = f.create_project_payload(customer_id, room_type=room_type, **overrides)
    return get_success_data(api_client.create_project(payload, DESIGNER))


def create_crew(region="WEST", daily_capacity_units=100, crew_name="Test Crew", **overrides):
    payload = f.create_crew_payload(
        region=region, daily_capacity_units=daily_capacity_units,
        crew_name=crew_name, **overrides
    )
    return get_success_data(api_client.create_crew(payload, SCHEDULER))


# ---------------------------------------------------------------------------
# Tier 1/2: project + design + measure + config
# ---------------------------------------------------------------------------
def add_design_consult(project_id):
    payload = f.create_design_consult_payload()
    return get_success_data(api_client.create_design_consult(project_id, payload, DESIGNER))


def add_space_measure(project_id, wall_count=2, linear_feet=12.5, ceiling_height_in=96):
    payload = f.create_space_measure_payload(
        wall_count=wall_count, linear_feet=linear_feet, ceiling_height_in=ceiling_height_in
    )
    return get_success_data(api_client.create_space_measure(project_id, payload, DESIGNER))


def add_component_config(project_id, space_measure_id, material_grade="MELAMINE", line_items=None):
    if line_items is None:
        line_items = [{"component_type": "SHELF", "quantity": 10, "unit_price_cents": 5000}]
    payload = f.create_component_config_payload(
        space_measure_id, material_grade=material_grade, line_items=line_items
    )
    return get_success_data(api_client.create_component_config(project_id, payload, DESIGNER))


def finalize_config(config_id):
    return get_success_data(api_client.finalize_component_config(config_id, DESIGNER))


def add_finalized_config(project_id, material_grade="MELAMINE", line_items=None):
    """Create + finalize a config on a fresh measure. Returns (config, measure)."""
    measure = add_space_measure(project_id)
    cfg = add_component_config(project_id, measure["id"], material_grade=material_grade,
                               line_items=line_items)
    finalize_config(cfg["id"])
    cfg = get_success_data(api_client.get_component_config(cfg["id"], DESIGNER))
    return cfg, measure


# ---------------------------------------------------------------------------
# Quote lifecycle helpers
# ---------------------------------------------------------------------------
def add_quote(project_id, component_config_id, promo_code=None):
    payload = f.create_quote_payload(component_config_id)
    if promo_code is not None:
        payload["promo_code"] = promo_code
    return get_success_data(api_client.create_quote(project_id, payload, DESIGNER))


def issue_quote(quote_id):
    return get_success_data(api_client.issue_quote(quote_id, DESIGNER))


def accept_quote(quote_id, customer_id):
    return get_success_data(api_client.accept_quote(quote_id, make_customer_headers(customer_id)))


# ---------------------------------------------------------------------------
# Composite: project progressed to a target lifecycle state.
# Returns a dict context with the relevant ids.
# ---------------------------------------------------------------------------
def setup_designing_project(zip_code="90001", room_type="WALK_IN_CLOSET"):
    """Customer + project advanced to DESIGNING (first consult). Returns context dict."""
    customer = create_customer(zip_code=zip_code)
    project = create_project(customer["id"], room_type=room_type)
    add_design_consult(project["id"])
    return {"customer": customer, "project": project}


def setup_finalized_config_scenario(zip_code="90001", room_type="WALK_IN_CLOSET",
                                    material_grade="MELAMINE", line_items=None):
    """Customer + DESIGNING project + measure + FINALIZED config.
    Returns context with customer, project, measure, config."""
    ctx = setup_designing_project(zip_code=zip_code, room_type=room_type)
    cfg, measure = add_finalized_config(
        ctx["project"]["id"], material_grade=material_grade, line_items=line_items
    )
    ctx["measure"] = measure
    ctx["config"] = cfg
    return ctx


def setup_issued_quote(zip_code="90001", room_type="WALK_IN_CLOSET",
                       material_grade="MELAMINE", line_items=None, promo_code=None):
    """Through an ISSUED quote (project QUOTED). Returns context + 'quote'."""
    ctx = setup_finalized_config_scenario(
        zip_code=zip_code, room_type=room_type, material_grade=material_grade,
        line_items=line_items
    )
    quote = add_quote(ctx["project"]["id"], ctx["config"]["id"], promo_code=promo_code)
    quote = issue_quote(quote["id"])
    ctx["quote"] = quote
    return ctx


def setup_accepted_quote(zip_code="90001", room_type="WALK_IN_CLOSET",
                         material_grade="MELAMINE", line_items=None, promo_code=None):
    """Through an ACCEPTED quote. Returns context + 'quote' (post-accept, version current)."""
    ctx = setup_issued_quote(
        zip_code=zip_code, room_type=room_type, material_grade=material_grade,
        line_items=line_items, promo_code=promo_code
    )
    quote = accept_quote(ctx["quote"]["id"], ctx["customer"]["id"])
    ctx["quote"] = quote
    return ctx


def create_deposit(project_id, quote_id, amount_cents):
    payload = f.create_deposit_payload(project_id, quote_id, amount_cents)
    return get_success_data(api_client.create_deposit(payload, ADMIN))


def capture_deposit(deposit_id, expected_quote_version):
    payload = {"expected_quote_version": expected_quote_version}
    return get_success_data(api_client.capture_deposit(deposit_id, payload, ADMIN))


def setup_deposit_paid(zip_code="90001", room_type="WALK_IN_CLOSET",
                       material_grade="MELAMINE", line_items=None, deposit_amount=5000000):
    """Through DEPOSIT_PAID: deposit created + captured, ManufactureOrder QUEUED exists.
    Returns context + 'deposit' + 'manufacture_order'."""
    ctx = setup_accepted_quote(
        zip_code=zip_code, room_type=room_type, material_grade=material_grade,
        line_items=line_items
    )
    quote = ctx["quote"]
    dep = create_deposit(ctx["project"]["id"], quote["id"], deposit_amount)
    capture_deposit(dep["id"], quote["version"])
    ctx["deposit"] = dep
    mos, _ = _list_manufacture_orders(ctx["project"]["id"])
    ctx["manufacture_order"] = mos[0]
    return ctx


def _list_manufacture_orders(project_id):
    resp = api_client.list_manufacture_orders(MFG_OPS, params={"project_id": project_id})
    data = get_success_data(resp)
    # list endpoints return data as the array
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data, resp


def get_manufacture_order_for_project(project_id):
    mos, _ = _list_manufacture_orders(project_id)
    return mos[0]


def start_manufacture(order_id):
    return get_success_data(api_client.start_manufacture_order(order_id, MFG_OPS))


def complete_manufacture(order_id):
    return get_success_data(api_client.complete_manufacture_order(order_id, MFG_OPS))


def setup_ready_to_install(zip_code="90001", room_type="WALK_IN_CLOSET",
                           material_grade="MELAMINE", line_items=None,
                           start_clock="2026-04-15T00:00:00Z",
                           ready_clock="2026-05-05T00:00:00Z",
                           deposit_amount=5000000):
    """Through READY_TO_INSTALL: manufacture order started then completed.
    Sets clock to start_clock first, then to ready_clock before completing.
    For the default WALK_IN_CLOSET / MELAMINE / WEST 10-unit config the lead time
    is 20 days, so a start_clock of 2026-04-15 yields promised_ready_date
    2026-05-05 (= the default ready_clock, the inclusive lower bound for both the
    lead-time completion gate and the install window-start check).
    Returns context with customer, project, quote, deposit, manufacture_order (READY)."""
    set_clock(start_clock)
    ctx = setup_deposit_paid(
        zip_code=zip_code, room_type=room_type, material_grade=material_grade,
        line_items=line_items, deposit_amount=deposit_amount
    )
    mo = ctx["manufacture_order"]
    start_manufacture(mo["id"])
    set_clock(ready_clock)
    mo = complete_manufacture(mo["id"])
    ctx["manufacture_order"] = mo
    return ctx


# ---------------------------------------------------------------------------
# Install job lifecycle helpers
# ---------------------------------------------------------------------------
def propose_install_job(project_id, manufacture_order_id, crew_id, window_start, window_end):
    payload = f.create_install_job_payload(
        project_id, manufacture_order_id, crew_id, window_start, window_end
    )
    return get_success_data(api_client.create_install_job(payload, SCHEDULER))


def book_install_job(job_id):
    return get_success_data(api_client.book_install_job(job_id, SCHEDULER))


def setup_booked_install_job(zip_code="90001", room_type="WALK_IN_CLOSET",
                             material_grade="MELAMINE", line_items=None,
                             crew_region="WEST", daily_capacity_units=100,
                             window_start="2026-05-10T08:00:00Z",
                             window_end="2026-05-10T16:00:00Z",
                             crew_name="Booked Crew"):
    """Through a BOOKED install job. Returns context + 'crew' + 'install_job'."""
    ctx = setup_ready_to_install(
        zip_code=zip_code, room_type=room_type, material_grade=material_grade,
        line_items=line_items
    )
    crew = create_crew(region=crew_region, daily_capacity_units=daily_capacity_units,
                       crew_name=crew_name)
    job = propose_install_job(ctx["project"]["id"], ctx["manufacture_order"]["id"],
                              crew["id"], window_start, window_end)
    job = book_install_job(job["id"])
    ctx["crew"] = crew
    ctx["install_job"] = job
    return ctx


def setup_completed_project(zip_code="90001", room_type="WALK_IN_CLOSET",
                            material_grade="MELAMINE", line_items=None,
                            window_start="2026-05-10T08:00:00Z",
                            window_end="2026-05-10T16:00:00Z",
                            install_clock="2026-05-10T08:00:00Z",
                            crew_name="Complete Crew"):
    """Through a COMPLETED project: install booked, started, completed (cascade depth 3).
    Returns context + 'crew' + 'install_job' (DONE) + manufacture_order (INSTALLED)."""
    ctx = setup_booked_install_job(
        zip_code=zip_code, room_type=room_type, material_grade=material_grade,
        line_items=line_items, window_start=window_start, window_end=window_end,
        crew_name=crew_name,
    )
    set_clock(install_clock)
    get_success_data(api_client.start_install_job(ctx["install_job"]["id"], SCHEDULER))
    job = get_success_data(api_client.complete_install_job(ctx["install_job"]["id"], SCHEDULER))
    ctx["install_job"] = job
    return ctx


def setup_approved_warranty_claim(defect_type="FIT", **overrides):
    """COMPLETED project + filed warranty claim (covered) + APPROVED.
    Returns context + 'claim'."""
    ctx = setup_completed_project(**overrides)
    payload = f.create_warranty_claim_payload(
        ctx["project"]["id"], ctx["install_job"]["id"], defect_type
    )
    claim = get_success_data(
        api_client.create_warranty_claim(payload, make_customer_headers(ctx["customer"]["id"]))
    )
    claim = get_success_data(api_client.approve_warranty_claim(claim["id"], MFG_OPS))
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Financing helpers
# ---------------------------------------------------------------------------
def create_financing_application(project_id, quote_id, requested_amount_cents, term_months,
                                 customer_id):
    payload = f.create_financing_application_payload(
        project_id, quote_id, requested_amount_cents, term_months
    )
    return get_success_data(
        api_client.create_financing_application(payload, make_customer_headers(customer_id))
    )


def submit_financing_application(app_id, customer_id):
    return get_success_data(
        api_client.submit_financing_application(app_id, make_customer_headers(customer_id))
    )


def financing_decide(app_id, decision):
    payload = {"financing_application_id": app_id, "decision": decision}
    return get_success_data(api_client.financing_decision(payload, ADMIN))


def fund_financing_application(app_id):
    return get_success_data(api_client.fund_financing_application(app_id, ADMIN))


# ---------------------------------------------------------------------------
# Change order helpers
# ---------------------------------------------------------------------------
def submit_change_order(project_id, base_quote_id, change_type, revised_config_id=None):
    payload = f.create_change_order_payload(project_id, base_quote_id, change_type)
    if revised_config_id is not None:
        payload["revised_config_id"] = revised_config_id
    return get_success_data(api_client.create_change_order(payload, DESIGNER))


def approve_change_order(change_order_id):
    return get_success_data(api_client.approve_change_order(change_order_id, DESIGNER))


def reject_change_order(change_order_id):
    return get_success_data(api_client.reject_change_order(change_order_id, DESIGNER))


# Line-item presets used by difficulty instances (pinned values from the design index).
WOOD_40_UNITS = [
    {"component_type": "SHELF", "quantity": 30, "unit_price_cents": 5000},
    {"component_type": "DRAWER", "quantity": 10, "unit_price_cents": 12000},
    {"component_type": "ACCESSORY", "quantity": 4, "unit_price_cents": 2000},
]
PREMIUM_WOOD_40_UNITS = [
    {"component_type": "SHELF", "quantity": 30, "unit_price_cents": 5000},
    {"component_type": "DRAWER", "quantity": 10, "unit_price_cents": 12000},
]
MELAMINE_18_UNITS = [
    {"component_type": "SHELF", "quantity": 12, "unit_price_cents": 4000},
    {"component_type": "PANEL", "quantity": 6, "unit_price_cents": 3000},
]
