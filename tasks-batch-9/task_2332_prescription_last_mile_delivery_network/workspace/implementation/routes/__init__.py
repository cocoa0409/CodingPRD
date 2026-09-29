"""Flask blueprints, one module per workflow area."""

from routes.assignments import bp as assignments_bp
from routes.deliveries import bp as deliveries_bp
from routes.exceptions import bp as exceptions_bp
from routes.ops import bp as ops_bp
from routes.orders import bp as orders_bp
from routes.reads import bp as reads_bp
from routes.reference import bp as reference_bp

BLUEPRINTS = (
    reference_bp,
    orders_bp,
    deliveries_bp,
    assignments_bp,
    exceptions_bp,
    ops_bp,
    reads_bp,
)
