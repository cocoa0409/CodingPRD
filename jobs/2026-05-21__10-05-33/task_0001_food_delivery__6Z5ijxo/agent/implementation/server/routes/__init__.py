from .clock import bp as clock_bp
from .restaurants import bp as restaurants_bp
from .menu_items import bp as menu_items_bp
from .riders import bp as riders_bp
from .customers import bp as customers_bp
from .orders import bp as orders_bp
from .assignments import bp as assignments_bp
from .returns_ import bp as returns_bp
from .fines import bp as fines_bp
from .work_orders import bp as work_orders_bp


def register_routes(app):
    for bp in (
        clock_bp,
        restaurants_bp,
        menu_items_bp,
        riders_bp,
        customers_bp,
        orders_bp,
        assignments_bp,
        returns_bp,
        fines_bp,
        work_orders_bp,
    ):
        app.register_blueprint(bp)
