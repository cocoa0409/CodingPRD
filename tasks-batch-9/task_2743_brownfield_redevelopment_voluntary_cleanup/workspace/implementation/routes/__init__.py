"""Blueprint registry."""

from routes import (
    admin,
    controls,
    enrollments,
    funding,
    letters,
    monitoring,
    phases,
    plans,
    policies,
    protections,
    sites,
)

MODULES = (
    admin,
    sites,
    phases,
    protections,
    enrollments,
    plans,
    policies,
    controls,
    funding,
    letters,
    monitoring,
)


def register_blueprints(app):
    for module in MODULES:
        app.register_blueprint(module.bp)
    return app
