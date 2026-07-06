"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"Setup failed" errors, not confusing assertion failures. The test harness restarts the
server (empty DB) before every test, so every helper builds its preconditions from scratch
using only PRD-declared endpoints.

Identity threading: the Diner role is entity_backed:Employee, so POS calls thread the real
employee id via make_diner_headers(employee["id"]). CateringCoordinator is opaque but its
X-User-ID is captured as the order's coordinator_id for the segregation-of-duties check.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_site_payload, create_employee_payload, create_menu_cycle_payload,
    create_menu_item_payload, create_catering_venue_payload, create_service_session_payload,
    create_badge_transaction_payload, create_vendor_payload, create_purchase_order_payload,
    create_catering_order_payload, create_vendor_invoice_payload,
)
from .test_users import TEST_USERS, make_diner_headers, make_coordinator_headers, make_approver_headers

ADMIN = TEST_USERS["site_admin_headers"]
MANAGER = TEST_USERS["cafeteria_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


# ─── Building blocks ──────────────────────────────────────────────────────────
def create_site(**overrides) -> dict:
    return get_success_data(api_client.create_client_site(create_client_site_payload(**overrides), ADMIN))


def create_employee(site_id, **overrides) -> dict:
    return get_success_data(api_client.create_employee(create_employee_payload(site_id, **overrides), ADMIN))


def create_vendor(**overrides) -> dict:
    return get_success_data(api_client.create_vendor(create_vendor_payload(**overrides), ADMIN))


def create_cycle(site_id, **overrides) -> dict:
    return get_success_data(api_client.create_menu_cycle(create_menu_cycle_payload(site_id, **overrides), MANAGER))


def add_item(cycle_id, **overrides) -> dict:
    return get_success_data(api_client.create_menu_item(create_menu_item_payload(cycle_id, **overrides), MANAGER))


def publish_cycle(cycle_id) -> dict:
    return get_success_data(api_client.publish_menu_cycle(cycle_id, MANAGER))


def create_venue(site_id, **overrides) -> dict:
    return get_success_data(api_client.create_catering_venue(create_catering_venue_payload(site_id, **overrides), ADMIN))


def get_site_version(site_id) -> int:
    return get_success_data(api_client.get_client_site(site_id, FINANCE))["version"]


def get_site(site_id) -> dict:
    return get_success_data(api_client.get_client_site(site_id, FINANCE))


def stock_site(site_id, ingredient, qty, unit_cost, vendor_id=None) -> dict:
    """Create -> issue -> receive a single-line PO; return the resulting InventoryLot."""
    if vendor_id is None:
        vendor_id = create_vendor()["id"]
    po = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            vendor_id, site_id,
            [{"ingredient": ingredient, "qty": qty, "unit_cost_cents": unit_cost}]),
        MANAGER))
    get_success_data(api_client.issue_purchase_order(po["id"], MANAGER))
    get_success_data(api_client.receive_purchase_order(po["id"], MANAGER))
    lots = get_success_data(api_client.list_inventory_lots(MANAGER, params={"purchase_order_id": po["id"]}))
    return lots[0]


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, MANAGER))


def create_pos(employee_id, session_id, lines, payment_method="BADGE_PAYROLL") -> dict:
    """Record a POS purchase as the acting Diner (X-User-ID == employee_id)."""
    return get_success_data(api_client.create_badge_transaction(
        create_badge_transaction_payload(employee_id, session_id, lines, payment_method=payment_method),
        make_diner_headers(employee_id)))


# ─── Composite: menu + session ───────────────────────────────────────────────
def setup_published_menu(site_overrides=None, items=None):
    """Site + DRAFT cycle + item(s) + publish. Returns (site, cycle, [items])."""
    site = create_site(**(site_overrides or {}))
    cycle = create_cycle(site["id"])
    item_specs = items if items is not None else [{}]
    created_items = [add_item(cycle["id"], **spec) for spec in item_specs]
    publish_cycle(cycle["id"])
    return site, cycle, created_items


def setup_session(stage="IN_SERVICE", site_overrides=None, items=None,
                  employee_overrides=None, session_overrides=None, make_employee=True):
    """Site + published menu + one service session driven to `stage`
    (PLANNED | FORECAST_LOCKED | IN_SERVICE). Optionally registers an employee.

    Returns dict(site, cycle, items, employee, session).
    """
    site, cycle, created_items = setup_published_menu(site_overrides, items)
    employee = create_employee(site["id"], **(employee_overrides or {})) if make_employee else None
    session = get_success_data(api_client.create_service_session(
        create_service_session_payload(site["id"], cycle["id"], **(session_overrides or {})), MANAGER))
    if stage in ("FORECAST_LOCKED", "IN_SERVICE"):
        session = get_success_data(api_client.lock_forecast(session["id"], MANAGER))
    if stage == "IN_SERVICE":
        session = get_success_data(api_client.open_session(session["id"], MANAGER))
    return {"site": site, "cycle": cycle, "items": created_items, "employee": employee, "session": session}


# ─── Composite: catering ─────────────────────────────────────────────────────
def setup_catering_order(target="SUBMITTED", site_overrides=None, items=None,
                         order_overrides=None, venue_overrides=None,
                         coordinator_id="coord-1", approver_id="appr-1",
                         stock=None, reserved=None):
    """Site + venue + menu item(s) + catering order driven to `target`
    (DRAFT | SUBMITTED | APPROVED | CONFIRMED).

    `stock`: optional (ingredient, qty, unit_cost) received into the site before confirm.
    `reserved`: list of {ingredient, qty} used when target == CONFIRMED.
    Returns dict(site, venue, items, order, coordinator_id, approver_id, lot?).
    """
    site = create_site(**(site_overrides or {}))
    cycle = create_cycle(site["id"])
    item_specs = items if items is not None else [{}]
    created_items = [add_item(cycle["id"], **spec) for spec in item_specs]
    venue = create_venue(site["id"], **(venue_overrides or {}))

    lot = None
    if stock is not None:
        ingredient, qty, unit_cost = stock
        lot = stock_site(site["id"], ingredient, qty, unit_cost)

    coord_headers = make_coordinator_headers(coordinator_id)
    order_lines = [{"menu_item_id": created_items[0]["id"], "qty": 1}]
    order_payload = create_catering_order_payload(site["id"], venue["id"], order_lines, **(order_overrides or {}))
    order = get_success_data(api_client.create_catering_order(order_payload, coord_headers))

    result = {"site": site, "venue": venue, "cycle": cycle, "items": created_items,
              "order": order, "coordinator_id": coordinator_id, "approver_id": approver_id, "lot": lot}
    if target == "DRAFT":
        return result

    order = get_success_data(api_client.submit_catering_order(order["id"], coord_headers))
    result["order"] = order
    if target == "SUBMITTED":
        return result

    order = get_success_data(api_client.review_catering_order(
        order["id"], {"decision": "APPROVE"}, make_approver_headers(approver_id)))
    result["order"] = order
    if target == "APPROVED":
        return result

    if target == "CONFIRMED":
        version = get_site_version(site["id"])
        order = get_success_data(api_client.confirm_catering_order(
            order["id"],
            {"expected_client_site_version": version, "reserved_ingredients": reserved or []},
            FINANCE))
        result["order"] = order
        return result

    raise ValueError(f"unknown target {target}")


# ─── Composite: procurement / invoicing ──────────────────────────────────────
def setup_received_po(site_overrides=None, line=("FLOUR", 10, 200)):
    """Site + vendor + PO issued & received. Returns dict(site, vendor, po, po_total)."""
    site = create_site(**(site_overrides or {}))
    vendor = create_vendor()
    ingredient, qty, unit_cost = line
    po = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(vendor["id"], site["id"],
                                      [{"ingredient": ingredient, "qty": qty, "unit_cost_cents": unit_cost}]),
        MANAGER))
    get_success_data(api_client.issue_purchase_order(po["id"], MANAGER))
    po = get_success_data(api_client.receive_purchase_order(po["id"], MANAGER))
    return {"site": site, "vendor": vendor, "po": po, "po_total": qty * unit_cost}


def create_invoice(vendor_id, po_id, invoiced_amount_cents) -> dict:
    return get_success_data(api_client.create_vendor_invoice(
        create_vendor_invoice_payload(vendor_id, po_id, invoiced_amount_cents), FINANCE))


def setup_matched_invoice(invoiced_amount_cents, line=("FLOUR", 10, 200)):
    """Received PO + invoice advanced to MATCHED. Returns dict(site, vendor, po, invoice, po_total)."""
    base = setup_received_po(line=line)
    invoice = create_invoice(base["vendor"]["id"], base["po"]["id"], invoiced_amount_cents)
    invoice = get_success_data(api_client.match_vendor_invoice(invoice["id"], FINANCE))
    base["invoice"] = invoice
    return base
