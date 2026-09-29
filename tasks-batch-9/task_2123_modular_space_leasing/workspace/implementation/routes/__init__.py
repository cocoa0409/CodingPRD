from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.leases import bp as leases_bp
from routes.accessories import bp as accessories_bp
from routes.permits import bp as permits_bp
from routes.logistics import bp as logistics_bp
from routes.assessments import bp as assessments_bp
from routes.refurb import bp as refurb_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = (
    catalog_bp,
    customers_bp,
    leases_bp,
    accessories_bp,
    permits_bp,
    logistics_bp,
    assessments_bp,
    refurb_bp,
    clock_bp,
)


def register_all(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
