"""Route blueprints registry."""

from routes.dealerships import bp as dealerships_bp
from routes.customers import bp as customers_bp
from routes.units import bp as units_bp
from routes.deals import bp as deals_bp
from routes.pdi import bp as pdi_bp
from routes.service_bays import bp as service_bays_bp
from routes.service_orders import bp as service_orders_bp
from routes.part_items import bp as part_items_bp
from routes.part_reservations import bp as part_reservations_bp
from routes.warranty_plans import bp as warranty_plans_bp
from routes.appointments import bp as appointments_bp
from routes.storage_slots import bp as storage_slots_bp
from routes.recalls import bp as recalls_bp

ALL_BLUEPRINTS = [
    dealerships_bp,
    customers_bp,
    units_bp,
    deals_bp,
    pdi_bp,
    service_bays_bp,
    service_orders_bp,
    part_items_bp,
    part_reservations_bp,
    warranty_plans_bp,
    appointments_bp,
    storage_slots_bp,
    recalls_bp,
]
