"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints. The harness restarts the server (empty DB) before every test, so
fixtures never assume pre-existing state.

All helpers use get_success_data() (lenient 2xx validator) so a setup failure
surfaces as a clear "Setup failed" error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import INVENTORY_MANAGER, PURCHASING_AGENT, BAR_MANAGER
from . import factories as f


# =====================================================================
# Logical clock
# =====================================================================
def set_clock(to_iso8601):
    """Set the server logical clock (PRD §3.9)."""
    return get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), INVENTORY_MANAGER))


# =====================================================================
# Products
# =====================================================================
def create_product(**overrides):
    """Create one ACTIVE product. Returns the Product dict."""
    return get_success_data(api_client.create_product(f.create_product_payload(**overrides), INVENTORY_MANAGER))


def create_keg_product(**overrides):
    """Create a KEG product (half-barrel default volume)."""
    payload = {
        "container_type": "KEG",
        "container_volume_ml": 58670,
        "unit_cost_cents": 15000,
        "name": "House Lager",
    }
    payload.update(overrides)
    return create_product(**payload)


def archive_product(product_id):
    return get_success_data(api_client.archive_product(product_id, INVENTORY_MANAGER))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, INVENTORY_MANAGER))


# =====================================================================
# Par settings
# =====================================================================
def create_par(product_id, par_level_units=24, reorder_point_units=10):
    """Create an ACTIVE par setting for a product (PRD §2.8)."""
    return get_success_data(api_client.create_par_setting(
        f.create_par_setting_payload(product_id, par_level_units, reorder_point_units), INVENTORY_MANAGER))


def create_product_with_par(par_level_units=24, reorder_point_units=10, **product_overrides):
    """Product + ACTIVE par setting. Returns (product, par)."""
    product = create_product(**product_overrides)
    par = create_par(product["id"], par_level_units, reorder_point_units)
    return product, par


# =====================================================================
# Purchase orders / invoices
# =====================================================================
def create_submitted_po(lines, vendor_name="Acme", expected_at="2026-03-02T00:00:00Z"):
    """Create a DRAFT PO, add lines, submit it. Returns the SUBMITTED PO dict.

    `lines` is a list of dicts: {product_id, ordered_qty, unit_cost_cents}.
    """
    po = get_success_data(api_client.create_purchase_order(
        f.create_purchase_order_payload(vendor_name=vendor_name, expected_at=expected_at), PURCHASING_AGENT))
    for line in lines:
        get_success_data(api_client.add_po_line(
            po["id"], f.add_po_line_payload(**line), PURCHASING_AGENT))
    return get_success_data(api_client.submit_purchase_order(po["id"], PURCHASING_AGENT))


def create_draft_invoice_with_lines(po_id, lines, vendor_invoice_no=None, freight_cents=0):
    """Create a DRAFT invoice against a PO and add billed lines. Returns the invoice dict.

    `lines` is a list of dicts: {product_id, received_qty, unit_cost_cents}.
    """
    inv = get_success_data(api_client.create_invoice(
        f.create_invoice_payload(po_id, vendor_invoice_no, freight_cents=freight_cents), PURCHASING_AGENT))
    for line in lines:
        get_success_data(api_client.add_invoice_line(
            inv["id"], f.add_invoice_line_payload(**line), PURCHASING_AGENT))
    return inv


def post_invoice(invoice_id):
    return get_success_data(api_client.post_invoice(invoice_id, PURCHASING_AGENT))


def seed_on_hand_via_posted_invoice(product_id, qty, unit_cost_cents=2000):
    """Create PO -> submit -> invoice -> post so the product gets `qty` on_hand
    at the billed landed cost. Returns (po, invoice).

    Used to put a product at a known on_hand level for reorder/threshold tests.
    """
    po = create_submitted_po([{
        "product_id": product_id, "ordered_qty": qty, "unit_cost_cents": unit_cost_cents}])
    inv = create_draft_invoice_with_lines(po["id"], [{
        "product_id": product_id, "received_qty": qty, "unit_cost_cents": unit_cost_cents}])
    post_invoice(inv["id"])
    return po, inv


def create_posted_invoice(po_lines, invoice_lines, vendor_name="Acme", freight_cents=0):
    """Full chain: submitted PO with `po_lines` -> draft invoice with `invoice_lines` -> post.
    Returns (po, invoice). Each *_lines is a list of line dicts.
    """
    po = create_submitted_po(po_lines, vendor_name=vendor_name)
    inv = create_draft_invoice_with_lines(po["id"], invoice_lines, freight_cents=freight_cents)
    inv = post_invoice(inv["id"])
    return po, inv


# =====================================================================
# Recipes / menu items
# =====================================================================
def create_draft_recipe_with_lines(name, lines):
    """Create a DRAFT recipe and add pour lines. Returns the recipe dict.

    `lines` is a list of dicts: {product_id, pour_ml}.
    """
    rec = get_success_data(api_client.create_recipe(f.create_recipe_payload(name=name), BAR_MANAGER))
    for line in lines:
        get_success_data(api_client.add_recipe_line(
            rec["id"], f.create_recipe_line_payload(**line), BAR_MANAGER))
    return rec


def create_published_recipe(name, lines):
    """Create a DRAFT recipe, add lines, publish it. Returns the PUBLISHED recipe dict."""
    rec = create_draft_recipe_with_lines(name, lines)
    return get_success_data(api_client.publish_recipe(rec["id"], BAR_MANAGER))


def create_menu_item(recipe_id, menu_price_cents=1300):
    """List a PUBLISHED recipe on the menu. Returns the MenuItem dict."""
    return get_success_data(api_client.create_menu_item(
        f.create_menu_item_payload(recipe_id, menu_price_cents), BAR_MANAGER))


def record_sales(menu_item_id, quantity, sold_at="2026-03-05T00:00:00Z"):
    return get_success_data(api_client.record_sales(
        menu_item_id, f.record_sales_payload(quantity, sold_at), BAR_MANAGER))


def create_published_menu_item(name, lines, menu_price_cents=1300):
    """Published recipe + ACTIVE menu item. Returns (recipe, menu_item)."""
    rec = create_published_recipe(name, lines)
    mi = create_menu_item(rec["id"], menu_price_cents)
    return rec, mi


# =====================================================================
# Count sessions
# =====================================================================
def open_count_session(label="Test Count", counted_at="2026-02-01T00:00:00Z"):
    """Open a count session (OPEN, version 1). Returns the session dict."""
    return get_success_data(api_client.create_count_session(
        f.create_count_session_payload(label, counted_at), INVENTORY_MANAGER))


def add_count_line(count_session_id, product_id, count_method, expected_version, **measure):
    """Add a count line. Pass counted_units= for UNITS or gross_weight_g= for WEIGHT.

    The OCC guard in PRD §2.6/§3.7 is keyed on the *CountSession* version, which
    the add advances by 1 (PRD §2.4). The POST returns the created CountLine
    resource (PRD §2.2), whose own ``version`` is 1 — NOT the session version.
    To give callers the value they must supply as ``expected_count_session_version``
    on the next session write, this helper re-reads the session and returns it
    (so the returned dict's ``version`` is the session's current version)."""
    payload = f.add_count_line_payload(product_id, count_method, expected_version, **measure)
    get_success_data(api_client.add_count_line(count_session_id, payload, INVENTORY_MANAGER))
    return get_success_data(api_client.get_count_session(count_session_id, INVENTORY_MANAGER))


def open_session_with_unit_line(product_id, counted_units, label="C", counted_at="2026-02-01T00:00:00Z"):
    """Open a session and add one UNITS count line. Returns (session, latest_version).

    latest_version is the session version AFTER the line was appended (use for finalize).
    """
    session = open_count_session(label, counted_at)
    session_after = add_count_line(session["id"], product_id, "UNITS", session["version"],
                                   counted_units=counted_units)
    return session, session_after["version"]


def open_session_with_weight_line(product_id, gross_weight_g, label="W", counted_at="2026-02-10T00:00:00Z"):
    """Open a session and add one WEIGHT count line. Returns (session, latest_version)."""
    session = open_count_session(label, counted_at)
    session_after = add_count_line(session["id"], product_id, "WEIGHT", session["version"],
                                   gross_weight_g=gross_weight_g)
    return session, session_after["version"]


def finalize_session(count_session_id, expected_version):
    return get_success_data(api_client.finalize_count_session(
        count_session_id, {"expected_count_session_version": expected_version}, INVENTORY_MANAGER))


def find_count_line_for_product(count_session_id, product_id):
    """Read back the count line for a given product from a session's lines listing."""
    resp = api_client.list_count_lines(count_session_id, INVENTORY_MANAGER)
    data = get_success_data(resp)
    if isinstance(data, dict):
        # Some envelopes wrap arrays; fall through to the raw json data list.
        items = data if isinstance(data, list) else resp.json().get("data", [])
    else:
        items = data
    for line in items:
        if line.get("product_id") == product_id:
            return line
    return None


# =====================================================================
# Keg taps
# =====================================================================
def create_keg_tap(product_id, draft_line_no, tapped_from, tapped_until):
    return get_success_data(api_client.create_keg_tap(
        f.create_keg_tap_payload(product_id, draft_line_no, tapped_from, tapped_until), BAR_MANAGER))
