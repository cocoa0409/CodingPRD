"""Route registration. Each module exposes register(app)."""
from routes import config as config_routes
from routes import inventory as inventory_routes
from routes import lockers as locker_routes
from routes import shares as share_routes
from routes import orders as order_routes
from routes import sausage as sausage_routes
from routes import logs as log_routes
from routes import clock as clock_routes


def register_routes(app):
    config_routes.register(app)
    inventory_routes.register(app)
    locker_routes.register(app)
    share_routes.register(app)
    order_routes.register(app)
    sausage_routes.register(app)
    log_routes.register(app)
    clock_routes.register(app)
