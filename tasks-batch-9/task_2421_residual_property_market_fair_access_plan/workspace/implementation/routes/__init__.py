"""Blueprint registration.  Every resource is mounted under /fair-plan."""

from routes import (
    assessments,
    inspections,
    intake,
    ops,
    policies,
    rates,
    registry,
    takeouts,
)

API_PREFIX = "/fair-plan"

BLUEPRINTS = (
    ops.bp,
    registry.bp,
    intake.bp,
    inspections.bp,
    rates.bp,
    policies.bp,
    takeouts.bp,
    assessments.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
