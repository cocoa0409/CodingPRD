"""Blueprint registration."""

from routes.reference import bp as reference_bp
from routes.vendors import bp as vendors_bp
from routes.submissions import bp as submissions_bp
from routes.hours import bp as hours_bp
from routes.measures import bp as measures_bp

BLUEPRINTS = (reference_bp, vendors_bp, submissions_bp, hours_bp, measures_bp)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
