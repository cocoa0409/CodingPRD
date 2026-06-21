"""Public field projections per entity (PRD §1.1 entity tables).

Records carry internal helper fields (prefixed with _); the response layer also
strips those, but these projectors guarantee the exact public shape per entity.
"""

_COMMON = ("id", "created_at", "updated_at", "version")


def _project(record, fields):
    return {k: record.get(k) for k in fields}


SHOP_FIELDS = ("id", "name", "tax_rate_bps", "rush_surcharge_bps",
               "rush_cutoff_hour_utc", "standard_turnaround_days",
               "rush_turnaround_days", "daily_unit_capacity") + _COMMON[1:]

PRODUCT_FIELDS = ("id", "shop_id", "name", "category", "base_unit_price_cents",
                  "unit_size", "requires_proof", "requires_press", "active") + _COMMON[1:]

PRICING_TIER_FIELDS = ("id", "product_id", "min_quantity", "discount_bps") + _COMMON[1:]

FINISHING_OPTION_FIELDS = ("id", "product_id", "code", "surcharge_kind",
                           "surcharge_cents") + _COMMON[1:]

CUSTOMER_FIELDS = ("id", "email", "name", "shop_id", "completed_order_count",
                   "lifetime_paid_cents", "loyalty_score", "loyalty_tier") + _COMMON[1:]

ORDER_FIELDS = ("id", "shop_id", "customer_id", "reordered_from_order_id",
                "production_status", "payment_status", "subtotal_cents",
                "loyalty_discount_cents", "rush_fee_cents", "tax_cents",
                "total_cents", "promised_ready_date") + _COMMON[1:]

ORDER_LINE_FIELDS = ("id", "order_id", "product_id", "quantity", "finishing_codes",
                     "service_level", "status", "production_units",
                     "estimate_line_cents", "final_line_cents",
                     "rush_surcharge_cents", "promised_ready_date") + _COMMON[1:]

ARTWORK_FIELDS = ("id", "order_line_id", "file_name", "page_count", "dpi",
                  "bleed_mm", "preflight_status", "preflight_reason") + _COMMON[1:]

PROOF_FIELDS = ("id", "order_line_id", "round_number", "status",
                "change_note") + _COMMON[1:]

FULFILLMENT_FIELDS = ("id", "order_id", "method", "ship_address", "ship_fee_cents",
                      "status") + _COMMON[1:]

PRESS_FIELDS = ("id", "shop_id", "name", "cleanup_buffer_minutes") + _COMMON[1:]

PRESS_BOOKING_FIELDS = ("id", "press_id", "order_line_id", "start_utc", "end_utc",
                        "status") + _COMMON[1:]

CAPACITY_RESERVATION_FIELDS = ("id", "shop_id", "order_line_id", "production_date",
                               "units", "status") + _COMMON[1:]


def shop(r): return _project(r, SHOP_FIELDS)
def product(r): return _project(r, PRODUCT_FIELDS)
def pricing_tier(r): return _project(r, PRICING_TIER_FIELDS)
def finishing_option(r): return _project(r, FINISHING_OPTION_FIELDS)
def customer(r): return _project(r, CUSTOMER_FIELDS)
def order(r): return _project(r, ORDER_FIELDS)
def order_line(r): return _project(r, ORDER_LINE_FIELDS)
def artwork(r): return _project(r, ARTWORK_FIELDS)
def proof(r): return _project(r, PROOF_FIELDS)
def fulfillment(r): return _project(r, FULFILLMENT_FIELDS)
def press(r): return _project(r, PRESS_FIELDS)
def press_booking(r): return _project(r, PRESS_BOOKING_FIELDS)
def capacity_reservation(r): return _project(r, CAPACITY_RESERVATION_FIELDS)
