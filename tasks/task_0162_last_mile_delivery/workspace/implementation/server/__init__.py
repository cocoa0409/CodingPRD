"""Flask app factory."""
from flask import Flask

from .errors import APIError, register_error_handlers
from .routes.customers import bp as customers_bp
from .routes.transit_centers import bp as transit_centers_bp
from .routes.drivers import bp as drivers_bp
from .routes.parcels import bp as parcels_bp
from .routes.routes_routes import bp as routes_bp
from .routes.appointments import bp as appointments_bp
from .routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)

    app.register_blueprint(customers_bp)
    app.register_blueprint(transit_centers_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(parcels_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(clock_bp)

    return app
