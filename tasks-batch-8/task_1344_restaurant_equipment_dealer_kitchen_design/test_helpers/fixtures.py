"""Composite setup helpers — multi-step scenario builders.

Every fixture builds preconditions from scratch using PRD-declared endpoints
only (the runner restarts the server before each test). All setup calls go
through get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: quote accept/reject calls are ownership-gated to the
Customer, so every accept path uses make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_customer_payload,
    create_delivery_job_payload,
    create_equipment_item_payload,
    create_layout_payload,
    create_project_payload,
    create_service_agency_payload,
    create_startup_session_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
KD = TEST_USERS["kitchen_designer_headers"]
SR = TEST_USERS["sales_rep_headers"]
PC = TEST_USERS["permit_coordinator_headers"]
FL = TEST_USERS["fabrication_lead_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
ST = TEST_USERS["startup_technician_headers"]
SM = TEST_USERS["service_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: atomic builders
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    """Create a Customer. Returns the customer dict."""
    res = api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_project(customer_id, **overrides):
    """Create a Project under the given customer. Returns the project dict."""
    res = api_client.create_project(create_project_payload(customer_id, **overrides), PM)
    return get_success_data(res)


def create_layout(project_id, **overrides):
    """Create a KitchenLayout (DRAFT, revision_no=1)."""
    res = api_client.create_layout(project_id, create_layout_payload(**overrides), KD)
    return get_success_data(res)


def add_equipment_item(project_id, layout_id, **overrides):
    """Add an EquipmentItem (SCHEDULED) to a layout."""
    res = api_client.create_equipment_item(
        project_id, layout_id, create_equipment_item_payload(**overrides), KD
    )
    return get_success_data(res)


def create_service_agency(**overrides):
    """Register a ServiceAgency (ACTIVE, open_assignment_count=0)."""
    res = api_client.create_service_agency(
        create_service_agency_payload(**overrides), SM
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: hierarchy builders
# ---------------------------------------------------------------------------

def setup_customer_with_project(customer_overrides=None, project_overrides=None):
    """Customer + Project in DESIGN. Returns (customer, project)."""
    customer = create_customer(**(customer_overrides or {}))
    project = create_project(customer["id"], **(project_overrides or {}))
    return customer, project


def setup_project_with_approved_layout(
    item_overrides_list=None,
    customer_overrides=None,
    project_overrides=None,
    layout_overrides=None,
):
    """Customer + Project + Layout with N items, walked to APPROVED.

    Returns (customer, project, layout, items). items is a list of the
    created EquipmentItem dicts in creation order.
    """
    customer, project = setup_customer_with_project(
        customer_overrides=customer_overrides, project_overrides=project_overrides
    )
    layout = create_layout(project["id"], **(layout_overrides or {}))
    items = [
        add_equipment_item(project["id"], layout["id"], **(item or {}))
        for item in (item_overrides_list or [{}])
    ]
    api_client.submit_layout(project["id"], layout["id"], KD)
    layout = get_success_data(
        api_client.approve_layout(project["id"], layout["id"], PM)
    )
    return customer, project, layout, items


# ---------------------------------------------------------------------------
# Tier 3: quote lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_quote_presented(
    item_overrides_list=None,
    customer_overrides=None,
    project_overrides=None,
    layout_overrides=None,
):
    """Full chain up to a PRESENTED quote. Project is now QUOTED.

    Returns (customer, project, layout, items, quote).
    """
    customer, project, layout, items = setup_project_with_approved_layout(
        item_overrides_list=item_overrides_list,
        customer_overrides=customer_overrides,
        project_overrides=project_overrides,
        layout_overrides=layout_overrides,
    )
    quote = get_success_data(api_client.create_quote(project["id"], layout["id"], SR))
    quote = get_success_data(api_client.present_quote(project["id"], quote["id"], SR))
    return customer, project, layout, items, quote


def accept_quote_flow(project, quote, customer):
    """Accept a presented quote with the current project version (OCC).

    Returns the accepted quote dict (variant=FINAL, status=ACCEPTED).
    """
    fresh = get_success_data(api_client.get_project(project["id"], PM))
    res = api_client.accept_quote(
        project["id"],
        quote["id"],
        fresh["version"],
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def setup_quote_accepted(
    item_overrides_list=None,
    customer_overrides=None,
    project_overrides=None,
    layout_overrides=None,
):
    """Full chain to a CONTRACTED project with an ACCEPTED (FINAL) quote.

    Returns (customer, project, layout, items, quote) — project and quote are
    post-acceptance snapshots.
    """
    customer, project, layout, items, quote = setup_quote_presented(
        item_overrides_list=item_overrides_list,
        customer_overrides=customer_overrides,
        project_overrides=project_overrides,
        layout_overrides=layout_overrides,
    )
    quote = accept_quote_flow(project, quote, customer)
    project = get_success_data(api_client.get_project(project["id"], PM))
    return customer, project, layout, items, quote


# ---------------------------------------------------------------------------
# Tier 4: delivery / startup / commissioning builders
# ---------------------------------------------------------------------------

def deliver_project(project, dispatch_kwargs=None):
    """Create + dispatch + site-complete a single DeliveryJob covering the
    project's items. Returns the SITE_COMPLETE job dict."""
    job = get_success_data(
        api_client.create_delivery_job(
            project["id"], create_delivery_job_payload(**(dispatch_kwargs or {})), LC
        )
    )
    get_success_data(api_client.dispatch_delivery_job(project["id"], job["id"], LC))
    return get_success_data(api_client.mark_site_complete(project["id"], job["id"], LC))


def commission_project(project, items, demo_minutes=30):
    """Drive every supplied item through startup: schedule + complete one
    session per item. Returns the list of COMPLETE session dicts.

    Assumes every item is INSTALLED (i.e., delivery already site-complete)
    and at least one qualifying agency already exists if the project is
    expected to reach COMMISSIONED.
    """
    sessions = []
    for item in items:
        session = get_success_data(
            api_client.create_startup_session(
                project["id"],
                create_startup_session_payload(item["id"], demo_minutes=demo_minutes),
                ST,
            )
        )
        session = get_success_data(
            api_client.complete_startup_session(project["id"], session["id"], ST)
        )
        sessions.append(session)
    return sessions


def setup_delivered_project(
    item_overrides_list=None,
    customer_overrides=None,
    project_overrides=None,
):
    """Chain to Project DELIVERED: accept quote, then one delivery through
    site-complete. Works for all-STOCK layouts (no fabrication needed).

    Returns (customer, project, layout, items, quote, job) — project is a
    post-delivery snapshot.
    """
    customer, project, layout, items, quote = setup_quote_accepted(
        item_overrides_list=item_overrides_list,
        customer_overrides=customer_overrides,
        project_overrides=project_overrides,
    )
    job = deliver_project(project)
    project = get_success_data(api_client.get_project(project["id"], PM))
    return customer, project, layout, items, quote, job


def setup_commissioned_project(
    item_overrides_list=None,
    customer_overrides=None,
    project_overrides=None,
    agency_overrides=None,
    demo_minutes=30,
):
    """Full chain to Project COMMISSIONED: accept, deliver, register a
    qualifying ServiceAgency, then complete startup on every item.

    Returns (customer, project, layout, items, quote, job, agency, sessions)
    with project as a post-commission snapshot. The auto-opened
    ServiceAssignment is NOT returned; fetch via list_service_assignments.
    """
    customer, project, layout, items, quote, job = setup_delivered_project(
        item_overrides_list=item_overrides_list,
        customer_overrides=customer_overrides,
        project_overrides=project_overrides,
    )
    agency_kwargs = {"covered_jurisdictions": [project["health_jurisdiction"]]}
    agency_kwargs.update(agency_overrides or {})
    agency = create_service_agency(**agency_kwargs)
    sessions = commission_project(project, items, demo_minutes=demo_minutes)
    project = get_success_data(api_client.get_project(project["id"], PM))
    return customer, project, layout, items, quote, job, agency, sessions


def setup_fabrication_in_production():
    """Chain to a CONTRACTED project whose CUSTOM_FABRICATION item has an
    auto-spawned FabricationOrder walked to IN_PRODUCTION.

    Returns (customer, project, layout, item, quote, fab_order).
    """
    customer, project, layout, items, quote = setup_quote_accepted(
        item_overrides_list=[
            {
                "model_no": "CUSTOM-SUITE",
                "item_kind": "CUSTOM_FABRICATION",
                "quantity": 1,
                "unit_price_cents": 5_000_000,
                "lead_time_days": 60,
            }
        ]
    )
    fabs = get_success_data(api_client.list_fabrication_orders(project["id"], PM))
    fab = fabs[0]
    # PRD 3.4: shop_drawing_ref is supplied through the approval flow and
    # must be non-empty (ERR_SHOP_DRAWING_MISSING) — provide it here.
    get_success_data(
        api_client.approve_shop_drawing(
            project["id"], fab["id"], PM,
            shop_drawing_ref=DEFAULTS["SHOP_DRAWING_REF"],
        )
    )
    fab = get_success_data(api_client.start_production(project["id"], fab["id"], FL))
    project = get_success_data(api_client.get_project(project["id"], PM))
    return customer, project, layout, items[0], quote, fab
