from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.products import bp as products_bp
from routes.compat_rules import bp as compat_rules_bp
from routes.trailers import bp as trailers_bp
from routes.drivers import bp as drivers_bp
from routes.wash_bays import bp as wash_bays_bp
from routes.wash_certs import bp as wash_certs_bp
from routes.racks import bp as racks_bp
from routes.shipments import bp as shipments_bp
from routes.tickets import bp as tickets_bp
from routes.spill_plans import bp as spill_plans_bp
from routes.incidents import bp as incidents_bp
from routes.agreements import bp as agreements_bp

ALL_BLUEPRINTS = [
    clock_bp, customers_bp, products_bp, compat_rules_bp, trailers_bp,
    drivers_bp, wash_bays_bp, wash_certs_bp, racks_bp, shipments_bp,
    tickets_bp, spill_plans_bp, incidents_bp, agreements_bp,
]
