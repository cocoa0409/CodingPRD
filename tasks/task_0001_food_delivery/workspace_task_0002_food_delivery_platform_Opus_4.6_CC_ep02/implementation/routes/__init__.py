from routes.restaurants import bp as restaurants_bp
from routes.menu_items import bp as menu_items_bp
from routes.riders import bp as riders_bp
from routes.customers import bp as customers_bp
from routes.orders import bp as orders_bp
from routes.assignments import bp as assignments_bp
from routes.returns_ import bp as returns_bp
from routes.fines import bp as fines_bp
from routes.work_orders import bp as work_orders_bp
from routes.clock_routes import bp as clock_bp


def register_all(app):
    app.register_blueprint(restaurants_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(riders_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(fines_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(clock_bp)
