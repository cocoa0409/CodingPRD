"""Route registration for the 53 declared endpoints."""

from routes import catalogue, entitlements, licenses, misc, publications, sessions, shops


def register_routes(app):
    for module in (catalogue, licenses, shops, entitlements, publications, sessions, misc):
        app.register_blueprint(module.bp)
