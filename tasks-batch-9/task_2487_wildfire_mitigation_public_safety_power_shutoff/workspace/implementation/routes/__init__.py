"""Blueprint registration."""

from routes.centers import bp as centers_bp
from routes.circuits import bp as circuits_bp
from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.events import bp as events_bp
from routes.filings import bp as filings_bp
from routes.mitigation import bp as mitigation_bp
from routes.notifications import bp as notifications_bp
from routes.patrol import bp as patrol_bp
from routes.weather import bp as weather_bp

ALL_BLUEPRINTS = (
    circuits_bp,
    weather_bp,
    events_bp,
    customers_bp,
    notifications_bp,
    mitigation_bp,
    patrol_bp,
    centers_bp,
    filings_bp,
    clock_bp,
)


def register_all(app):
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)
