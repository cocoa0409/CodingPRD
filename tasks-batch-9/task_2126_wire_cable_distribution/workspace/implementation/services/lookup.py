"""Existence resolution (admission ladder position 4).

Path identifiers resolve left to right; body foreign keys resolve in the
declaration order branch_id, customer_id, product_id, truck_id, reel_id,
quote_id, sales_order_id, order_line_id, allocation_id.
"""
import db
from errors import ApiError


def _get(store, ident, error_id):
    rec = store.get(ident) if isinstance(ident, str) else None
    if rec is None:
        raise ApiError(error_id)
    return rec


def branch(ident):
    return _get(db.branches, ident, "ERR_BRANCH_NOT_FOUND")


def customer(ident):
    return _get(db.customers, ident, "ERR_CUSTOMER_NOT_FOUND")


def product(ident):
    return _get(db.products, ident, "ERR_PRODUCT_NOT_FOUND")


def truck(ident):
    return _get(db.trucks, ident, "ERR_TRUCK_NOT_FOUND")


def reel(ident):
    return _get(db.reels, ident, "ERR_REEL_NOT_FOUND")


def quote(ident):
    return _get(db.quotes, ident, "ERR_QUOTE_NOT_FOUND")


def quote_line(ident):
    return _get(db.quote_lines, ident, "ERR_QUOTE_LINE_NOT_FOUND")


def sales_order(ident):
    return _get(db.sales_orders, ident, "ERR_ORDER_NOT_FOUND")


def order_line(ident):
    return _get(db.order_lines, ident, "ERR_ORDER_LINE_NOT_FOUND")


def allocation(ident):
    return _get(db.allocations, ident, "ERR_ALLOCATION_NOT_FOUND")


def delivery_run(ident):
    return _get(db.delivery_runs, ident, "ERR_DELIVERY_RUN_NOT_FOUND")


def copper_index_entry(ident):
    return _get(db.copper_index_entries, ident, "ERR_COPPER_INDEX_NOT_FOUND")


# ------------------------------------------------------------- collections --

def quote_lines_of(quote_id):
    rows = [r for r in db.quote_lines.values() if r["quote_id"] == quote_id]
    return sorted(rows, key=lambda r: r["line_number"])


def order_lines_of(order_id):
    rows = [r for r in db.order_lines.values() if r["sales_order_id"] == order_id]
    return sorted(rows, key=lambda r: r["line_number"])


def allocations_of_order(order_id):
    rows = [r for r in db.allocations.values() if r["sales_order_id"] == order_id]
    return sorted(rows, key=db.sort_key)


def allocations_of_line(order_line_id):
    rows = [r for r in db.allocations.values() if r["order_line_id"] == order_line_id]
    return sorted(rows, key=lambda r: r["sequence_no"])


def orders_of_quote(quote_id):
    rows = [r for r in db.sales_orders.values() if r["quote_id"] == quote_id]
    return sorted(rows, key=db.sort_key)


def orders_of_customer(customer_id):
    rows = [r for r in db.sales_orders.values() if r["customer_id"] == customer_id]
    return sorted(rows, key=db.sort_key)


def quotes_of_customer(customer_id):
    rows = [r for r in db.quotes.values() if r["customer_id"] == customer_id]
    return sorted(rows, key=db.sort_key)


def runs_of_order(order_id):
    rows = [r for r in db.delivery_runs.values() if r["sales_order_id"] == order_id]
    return sorted(rows, key=db.sort_key)


def runs_of_truck(truck_id):
    rows = [r for r in db.delivery_runs.values() if r["truck_id"] == truck_id]
    return sorted(rows, key=db.sort_key)


def index_entry_on_or_before(date_str):
    """The entry with the greatest effective_date on or before date_str."""
    eligible = [e for e in db.copper_index_entries.values() if e["effective_date"] <= date_str]
    if not eligible:
        return None
    return max(eligible, key=lambda e: e["effective_date"])
