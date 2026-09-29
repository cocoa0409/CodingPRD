from routes.clock import bp as clock_bp
from routes.certification import bp as certification_bp
from routes.products import bp as products_bp
from routes.suppliers import bp as suppliers_bp
from routes.machining import bp as machining_bp
from routes.planning import bp as planning_bp
from routes.units import bp as units_bp
from routes.parts import bp as parts_bp

BLUEPRINTS = (
    clock_bp,
    certification_bp,
    products_bp,
    suppliers_bp,
    machining_bp,
    planning_bp,
    units_bp,
    parts_bp,
)
