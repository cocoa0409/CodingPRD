"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded at startup: every record is constructed via the declared API.
"""

COLLECTIONS = [
    "sites",
    "fleet_accounts",
    "contracts",
    "loyalty_members",
    "vehicles",
    "networks",
    "enrollments",
    "fuel_prices",
    "pumps",
    "fuel_sales",
    "parking_spaces",
    "parking_reservations",
    "service_tickets",
    "scale_tickets",
    "weigh_events",
    "stock_items",
    "vendors",
    "vendor_prices",
    "purchase_orders",
    "technicians",
    "bays",
    "work_orders",
    "work_order_parts",
    "registers",
    "shifts",
    "cash_drops",
    "reconciliations",
    "safe_deposits",
    "payouts",
    "bulk_tanks",
    "bulk_deliveries",
    "store_sales",
    "points_lots",
]

db = {name: {} for name in COLLECTIONS}
