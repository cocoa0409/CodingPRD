"""Blueprint registration for the /convention-center API surface."""

from routes.blackouts import bp as blackouts_bp
from routes.bookings import bp as bookings_bp
from routes.catering import bp as catering_bp
from routes.holds import bp as holds_bp
from routes.labor import bp as labor_bp
from routes.licenses import bp as licenses_bp
from routes.ops import bp as ops_bp
from routes.registry import bp as registry_bp
from routes.service_orders import bp as service_orders_bp
from routes.settlements import bp as settlements_bp

BLUEPRINTS = (
    registry_bp,
    bookings_bp,
    holds_bp,
    licenses_bp,
    service_orders_bp,
    labor_bp,
    catering_bp,
    settlements_bp,
    blackouts_bp,
    ops_bp,
)


def register(app, prefix="/convention-center"):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=prefix)
