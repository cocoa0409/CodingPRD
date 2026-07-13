"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup failures
surface as clear "setup failed" errors rather than confusing assertions.

Identity threading: the Organizer and Client roles are entity-backed. After a
fixture creates an Organizer, every ownership-gated organizer call it makes uses
make_organizer_headers(organizer_id); after it creates a Client, client calls use
make_client_headers(client_id). The opaque OperationsManager / BillingAdmin roles
use the shared constants.

The test harness resets the database before every test, so each fixture builds all
of its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload, create_organizer_payload, create_project_payload,
    create_session_payload, create_inventory_item_payload,
    create_product_line_payload, create_invoice_payload,
    create_maintenance_plan_payload,
)
from .test_users import TEST_USERS, make_organizer_headers, make_client_headers


def _om():
    return TEST_USERS["operations_manager_headers"]


def _ba():
    return TEST_USERS["billing_admin_headers"]


# ─── Building blocks ──────────────────────────────────────────────────────────

def new_client(**overrides) -> dict:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), _om()))


def new_organizer(hourly_rate_cents: int = 5000, **overrides) -> dict:
    payload = create_organizer_payload(hourly_rate_cents=hourly_rate_cents, **overrides)
    return get_success_data(api_client.create_organizer(payload, _om()))


def new_project(client_id: str, organizer_id: str, **overrides) -> dict:
    """Create a project (starts in SCOPING). Returns the created project."""
    payload = create_project_payload(client_id, organizer_id, **overrides)
    return get_success_data(api_client.create_project(payload, _om()))


def activate_project(project_id: str) -> dict:
    return get_success_data(api_client.activate_project(project_id, _om()))


def project_version(project_id: str) -> int:
    """Read the target project's current version (for OCC invoice issuance)."""
    return get_success_data(api_client.get_project(project_id, _ba()))["version"]


def new_active_project(billing_mode: str = "HOURLY", hourly_rate_cents: int = 5000,
                       scope_rooms=None, flat_price_cents: int | None = None,
                       move_addon_requested: bool = False, move_box_count: int = 0,
                       **project_overrides):
    """Create a client + organizer + ACTIVE project.

    Returns (client, organizer, project) where project is the activated record.
    """
    if scope_rooms is None:
        scope_rooms = ["Garage"]
    client = new_client()
    organizer = new_organizer(hourly_rate_cents=hourly_rate_cents)
    overrides = dict(project_overrides)
    overrides.update(
        billing_mode=billing_mode,
        scope_rooms=scope_rooms,
        move_addon_requested=move_addon_requested,
        move_box_count=move_box_count,
    )
    if flat_price_cents is not None:
        overrides["flat_price_cents"] = flat_price_cents
    project = new_project(client["id"], organizer["id"], **overrides)
    project = activate_project(project["id"])
    return client, organizer, project


# ─── Sessions ─────────────────────────────────────────────────────────────────

def new_session(project_id: str, organizer_id: str, scheduled_start: str,
                scheduled_end: str) -> dict:
    """Schedule a session (as the assigned organizer). Returns SCHEDULED session."""
    payload = create_session_payload(project_id, organizer_id, scheduled_start, scheduled_end)
    return get_success_data(
        api_client.create_session(payload, make_organizer_headers(organizer_id)))


def start_session(session_id: str, organizer_id: str) -> dict:
    return get_success_data(api_client.patch_session(
        session_id, {"status": "IN_PROGRESS"}, make_organizer_headers(organizer_id)))


def complete_session(session_id: str, organizer_id: str, logged_hours) -> dict:
    return get_success_data(api_client.complete_session(
        session_id, {"logged_hours": logged_hours}, make_organizer_headers(organizer_id)))


def add_completed_session(project_id: str, organizer_id: str, logged_hours,
                          scheduled_start: str, scheduled_end: str) -> dict:
    """Schedule -> start -> complete a session. Returns the COMPLETED session."""
    session = new_session(project_id, organizer_id, scheduled_start, scheduled_end)
    start_session(session["id"], organizer_id)
    return complete_session(session["id"], organizer_id, logged_hours)


def setup_project_with_completed_session(billing_mode: str = "HOURLY", hourly_rate_cents: int = 5000,
                                         logged_hours=3, flat_price_cents: int | None = None,
                                         scheduled_start: str = "2026-03-02T09:00:00Z",
                                         scheduled_end: str = "2026-03-02T12:00:00Z",
                                         move_addon_requested: bool = False, move_box_count: int = 0):
    """Active project with exactly one COMPLETED session — invoice-ready under HOURLY.

    Returns (client, organizer, project, session).
    """
    client, organizer, project = new_active_project(
        billing_mode=billing_mode, hourly_rate_cents=hourly_rate_cents,
        flat_price_cents=flat_price_cents, move_addon_requested=move_addon_requested,
        move_box_count=move_box_count)
    session = add_completed_session(
        project["id"], organizer["id"], logged_hours, scheduled_start, scheduled_end)
    return client, organizer, project, session


# ─── Invoices ─────────────────────────────────────────────────────────────────

def issue_invoice(project_id: str, expected_version: int | None = None) -> dict:
    """Issue an invoice for a project using its current version (unless overridden).

    Returns the ISSUED invoice. The project moves ACTIVE -> WRAP_UP.
    """
    if expected_version is None:
        expected_version = project_version(project_id)
    payload = create_invoice_payload(project_id, expected_version)
    return get_success_data(api_client.create_invoice(payload, _ba()))


def setup_issued_invoice(billing_mode: str = "HOURLY", hourly_rate_cents: int = 5000,
                         logged_hours=3, flat_price_cents: int | None = None):
    """Full setup through an ISSUED invoice (project in WRAP_UP).

    Returns (client, organizer, project, session, invoice).
    """
    client, organizer, project, session = setup_project_with_completed_session(
        billing_mode=billing_mode, hourly_rate_cents=hourly_rate_cents,
        logged_hours=logged_hours, flat_price_cents=flat_price_cents)
    invoice = issue_invoice(project["id"])
    return client, organizer, project, session, invoice


def setup_paid_ready_with_maintenance_plan(cadence: str = "QUARTERLY", monthly_fee_cents: int = 9900,
                                           logged_hours=4):
    """Active HOURLY project + DRAFT maintenance plan + one COMPLETED session +
    an ISSUED invoice (project in WRAP_UP). Ready for the pay-cascade test.

    Returns (client, organizer, project, plan, invoice).
    """
    client, organizer, project = new_active_project(hourly_rate_cents=5000)
    plan = new_maintenance_plan(project["id"], cadence=cadence, monthly_fee_cents=monthly_fee_cents)
    add_completed_session(project["id"], organizer["id"], logged_hours,
                          "2026-03-02T09:00:00Z", "2026-03-02T13:00:00Z")
    invoice = issue_invoice(project["id"])
    return client, organizer, project, plan, invoice


# ─── Inventory items ──────────────────────────────────────────────────────────

def new_inventory_item(project_id: str, organizer_id: str, disposition: str,
                       **overrides) -> dict:
    payload = create_inventory_item_payload(project_id, disposition, **overrides)
    return get_success_data(
        api_client.create_inventory_item(payload, make_organizer_headers(organizer_id)))


def schedule_item(item_id: str, organizer_id: str) -> dict:
    return get_success_data(
        api_client.schedule_inventory_item(item_id, make_organizer_headers(organizer_id)))


def confirm_item(item_id: str, organizer_id: str, final_value_cents=None) -> dict:
    payload = {} if final_value_cents is None else {"final_value_cents": final_value_cents}
    return get_success_data(
        api_client.confirm_inventory_item(item_id, payload, make_organizer_headers(organizer_id)))


def setup_scheduled_donation_item(estimated_value_cents: int = 10000):
    """Active project with one DONATE item advanced to SCHEDULED_DONATION.

    Returns (client, organizer, project, item).
    """
    client, organizer, project = new_active_project()
    item = new_inventory_item(project["id"], organizer["id"], "DONATE",
                              estimated_value_cents=estimated_value_cents)
    item = schedule_item(item["id"], organizer["id"])
    return client, organizer, project, item


# ─── Product lines ────────────────────────────────────────────────────────────

def new_product_line(project_id: str, organizer_id: str, **overrides) -> dict:
    payload = create_product_line_payload(project_id, **overrides)
    return get_success_data(
        api_client.create_product_line(payload, make_organizer_headers(organizer_id)))


def setup_project_with_quoted_product_line(wholesale_cost_cents: int = 1099,
                                           quantity: int = 3, markup_pct: float = 0.35):
    """Active project with one QUOTED product line.

    Returns (client, organizer, project, product_line).
    """
    client, organizer, project = new_active_project()
    line = new_product_line(project["id"], organizer["id"],
                            wholesale_cost_cents=wholesale_cost_cents,
                            quantity=quantity, markup_pct=markup_pct)
    return client, organizer, project, line


# ─── Maintenance plans ────────────────────────────────────────────────────────

def new_maintenance_plan(project_id: str, cadence: str = "QUARTERLY",
                         monthly_fee_cents: int = 9900, **overrides) -> dict:
    payload = create_maintenance_plan_payload(
        project_id, cadence=cadence, monthly_fee_cents=monthly_fee_cents, **overrides)
    return get_success_data(api_client.create_maintenance_plan(payload, _om()))
