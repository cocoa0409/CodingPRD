"""Public serialization of stored records.

Internal-only keys (those prefixed with '_') are stripped before returning a
resource to the client. Public field ordering follows the scaffold entity
definitions but JSON key order is not contractual.
"""

# Public field lists per entity (SCAFFOLD §1.1). Common fields (id, created_at,
# updated_at, version) are appended by _public().
_COMMON = ["id", "created_at", "updated_at", "version"]

_FIELDS = {
    "product": ["sku", "name", "container_type", "container_volume_ml",
                "empty_container_weight_g", "density_g_per_ml", "unit_cost_cents",
                "case_pack", "on_hand_units", "status", "needs_reorder"],
    "par_setting": ["product_id", "par_level_units", "reorder_point_units", "status"],
    "recipe": ["name", "recipe_cost_cents", "status"],
    "recipe_line": ["recipe_id", "product_id", "pour_ml", "line_cost_cents"],
    "menu_item": ["recipe_id", "menu_price_cents", "units_sold", "pour_cost_pct",
                  "menu_class", "status"],
    "count_session": ["label", "counted_at", "status", "total_variance_cost_cents"],
    "count_line": ["count_session_id", "product_id", "count_method", "counted_units",
                   "gross_weight_g", "closing_units", "theoretical_units",
                   "variance_units", "variance_cost_cents"],
    "purchase_order": ["vendor_name", "expected_at", "status", "ordered_total_cents"],
    "po_line": ["purchase_order_id", "product_id", "ordered_qty", "unit_cost_cents"],
    "invoice": ["purchase_order_id", "vendor_invoice_no", "freight_cents", "status",
                "subtotal_cents", "discount_cents", "tax_cents", "invoice_total_cents"],
    "invoice_line": ["invoice_id", "product_id", "received_qty", "unit_cost_cents",
                     "extension_cents"],
    "waste_log": ["product_id", "reason", "wasted_units", "waste_cost_cents"],
    "keg_tap": ["product_id", "draft_line_no", "tapped_from", "tapped_until"],
}


def _public(record, kind):
    out = {}
    for key in _FIELDS[kind]:
        if key in record:
            out[key] = record[key]
    for key in _COMMON:
        if key in record:
            out[key] = record[key]
    return out


def product(r):
    return _public(r, "product")


def par_setting(r):
    return _public(r, "par_setting")


def recipe(r):
    return _public(r, "recipe")


def recipe_line(r):
    return _public(r, "recipe_line")


def menu_item(r):
    return _public(r, "menu_item")


def count_session(r):
    return _public(r, "count_session")


def count_line(r):
    return _public(r, "count_line")


def purchase_order(r):
    return _public(r, "purchase_order")


def po_line(r):
    return _public(r, "po_line")


def invoice(r):
    return _public(r, "invoice")


def invoice_line(r):
    return _public(r, "invoice_line")


def waste_log(r):
    return _public(r, "waste_log")


def keg_tap(r):
    return _public(r, "keg_tap")
