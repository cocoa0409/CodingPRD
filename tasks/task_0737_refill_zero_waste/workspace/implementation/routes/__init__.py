"""Route blueprints for the Refill & Zero-Waste Store API."""
from .catalog import bp as catalog_bp
from .members import bp as members_bp
from .containers import bp as containers_bp
from .orders import bp as orders_bp
from .restock import bp as restock_bp
from .subscriptions import bp as subscriptions_bp
from .deliveries import bp as deliveries_bp

ALL_BLUEPRINTS = [
    catalog_bp,
    members_bp,
    containers_bp,
    orders_bp,
    restock_bp,
    subscriptions_bp,
    deliveries_bp,
]
