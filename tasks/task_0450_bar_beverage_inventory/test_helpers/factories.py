"""Payload factories — one per entity, input fields only."""
import itertools

# Monotonic counter to make SKUs / invoice numbers unique within a test run.
_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


# ---- Product ----
def create_product_payload(**overrides) -> dict:
    """POST /products input fields (PRD §3.1).

    Required: sku, name, container_type, container_volume_ml, unit_cost_cents.
    Optional (with defaults): empty_container_weight_g, density_g_per_ml, case_pack.
    """
    defaults = {
        "sku": f"SKU-{_next()}",
        "name": "Test Product",
        "container_type": "BOTTLE",
        "container_volume_ml": 750,
        "unit_cost_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


# ---- ParSetting ----
def create_par_setting_payload(product_id, par_level_units=24, reorder_point_units=10, **overrides) -> dict:
    """POST /par-settings input fields (PRD §2.8)."""
    defaults = {
        "product_id": product_id,
        "par_level_units": par_level_units,
        "reorder_point_units": reorder_point_units,
    }
    defaults.update(overrides)
    return defaults


# ---- RecipeSpec ----
def create_recipe_payload(name="Test Recipe", **overrides) -> dict:
    """POST /recipes input fields (PRD §3.3)."""
    defaults = {"name": name}
    defaults.update(overrides)
    return defaults


# ---- RecipeLine ----
def create_recipe_line_payload(product_id, pour_ml=50, **overrides) -> dict:
    """POST /recipes/{id}/lines input fields (PRD §3.3)."""
    defaults = {"product_id": product_id, "pour_ml": pour_ml}
    defaults.update(overrides)
    return defaults


# ---- MenuItem ----
def create_menu_item_payload(recipe_id, menu_price_cents=1300, **overrides) -> dict:
    """POST /menu-items input fields (PRD §3.4)."""
    defaults = {"recipe_id": recipe_id, "menu_price_cents": menu_price_cents}
    defaults.update(overrides)
    return defaults


def record_sales_payload(quantity=10, sold_at="2026-03-05T00:00:00Z", **overrides) -> dict:
    """POST /menu-items/{id}/record-sales input fields (PRD §3.4)."""
    defaults = {"quantity": quantity, "sold_at": sold_at}
    defaults.update(overrides)
    return defaults


# ---- CountSession ----
def create_count_session_payload(label="Test Count", counted_at="2026-02-01T00:00:00Z", **overrides) -> dict:
    """POST /count-sessions input fields (PRD §3.7)."""
    defaults = {"label": label, "counted_at": counted_at}
    defaults.update(overrides)
    return defaults


def add_count_line_payload(product_id, count_method, expected_count_session_version, **overrides) -> dict:
    """POST /count-sessions/{id}/count-lines input fields (PRD §3.7).

    Pass counted_units for UNITS or gross_weight_g for WEIGHT via overrides."""
    defaults = {
        "product_id": product_id,
        "count_method": count_method,
        "expected_count_session_version": expected_count_session_version,
    }
    defaults.update(overrides)
    return defaults


# ---- PurchaseOrder ----
def create_purchase_order_payload(vendor_name="Acme Spirits", expected_at="2026-03-02T00:00:00Z", **overrides) -> dict:
    """POST /purchase-orders input fields (PRD §3.5)."""
    defaults = {"vendor_name": vendor_name, "expected_at": expected_at}
    defaults.update(overrides)
    return defaults


def add_po_line_payload(product_id, ordered_qty=1, unit_cost_cents=2000, **overrides) -> dict:
    """POST /purchase-orders/{id}/lines input fields (PRD §3.5)."""
    defaults = {
        "product_id": product_id,
        "ordered_qty": ordered_qty,
        "unit_cost_cents": unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- Invoice ----
def create_invoice_payload(purchase_order_id, vendor_invoice_no=None, **overrides) -> dict:
    """POST /invoices input fields (PRD §3.6).

    freight_cents is optional (defaults to 0)."""
    defaults = {
        "purchase_order_id": purchase_order_id,
        "vendor_invoice_no": vendor_invoice_no or f"INV-{_next()}",
    }
    defaults.update(overrides)
    return defaults


def add_invoice_line_payload(product_id, received_qty=1, unit_cost_cents=2000, **overrides) -> dict:
    """POST /invoices/{id}/lines input fields (PRD §3.6)."""
    defaults = {
        "product_id": product_id,
        "received_qty": received_qty,
        "unit_cost_cents": unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- WasteLog ----
def create_waste_log_payload(product_id, reason="SPILL", wasted_units=1, **overrides) -> dict:
    """POST /waste-logs input fields (PRD §3.8)."""
    defaults = {
        "product_id": product_id,
        "reason": reason,
        "wasted_units": wasted_units,
    }
    defaults.update(overrides)
    return defaults


# ---- KegTap ----
def create_keg_tap_payload(product_id, draft_line_no=1, tapped_from="2026-03-01T08:00:00Z",
                           tapped_until="2026-03-01T12:00:00Z", **overrides) -> dict:
    """POST /keg-taps input fields (PRD §3.8)."""
    defaults = {
        "product_id": product_id,
        "draft_line_no": draft_line_no,
        "tapped_from": tapped_from,
        "tapped_until": tapped_until,
    }
    defaults.update(overrides)
    return defaults


def keg_yield_params(pour_size_ml, line_loss_pct=None) -> dict:
    """Query params for GET /products/{id}/keg-yield (PRD §3.2)."""
    params = {"pour_size_ml": pour_size_ml}
    if line_loss_pct is not None:
        params["line_loss_pct"] = line_loss_pct
    return params


def set_clock_payload(to_iso8601) -> dict:
    """POST /_clock/set_current_utc input fields (PRD §3.9)."""
    return {"to_iso8601": to_iso8601}
