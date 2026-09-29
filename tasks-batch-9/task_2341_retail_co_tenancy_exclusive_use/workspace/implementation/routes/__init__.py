"""Blueprint registration for all 66 endpoints."""
from routes import (centers, clauses, conditions, elections, estoppel, leases,
                    measurements, notices, plans, tenants)

BLUEPRINTS = (
    centers.bp,
    tenants.bp,
    leases.bp,
    conditions.bp,
    clauses.bp,
    notices.bp,
    measurements.bp,
    elections.bp,
    estoppel.bp,
    plans.bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
