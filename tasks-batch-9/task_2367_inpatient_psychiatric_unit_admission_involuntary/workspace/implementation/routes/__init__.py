"""Blueprint registry for the /behavioral-health API surface."""

from routes import (
    admissions,
    consents,
    evaluations,
    holds,
    ops,
    restraints,
    roster,
)

BLUEPRINTS = (
    roster.bp,
    ops.bp,
    evaluations.bp,
    holds.bp,
    admissions.bp,
    restraints.bp,
    consents.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
