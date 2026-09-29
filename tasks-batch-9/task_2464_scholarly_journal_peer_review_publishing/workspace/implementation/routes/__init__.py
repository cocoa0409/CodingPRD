"""Blueprint registration for every declared endpoint."""

from routes import (
    assignments,
    decisions,
    ethics,
    fees,
    invitations,
    manuscripts,
    ops,
    production,
    registry,
)

BLUEPRINTS = (
    registry.bp,
    manuscripts.bp,
    assignments.bp,
    invitations.bp,
    decisions.bp,
    ethics.bp,
    fees.bp,
    production.bp,
    ops.bp,
)


def register_blueprints(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
