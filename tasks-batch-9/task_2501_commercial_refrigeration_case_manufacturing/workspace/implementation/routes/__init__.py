from routes.catalog import bp as catalog_bp
from routes.design import bp as design_bp
from routes.testing import bp as testing_bp
from routes.plans import bp as plans_bp
from routes.logistics import bp as logistics_bp
from routes.service_network import bp as service_bp

BLUEPRINTS = [
    catalog_bp,
    design_bp,
    testing_bp,
    plans_bp,
    logistics_bp,
    service_bp,
]
