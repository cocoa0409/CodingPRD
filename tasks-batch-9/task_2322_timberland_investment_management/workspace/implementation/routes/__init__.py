"""Blueprint registration: every path is mounted under /timberland."""

from routes import (
    carbon,
    certification,
    clock,
    funds,
    harvest,
    hazard,
    hbu,
    leases,
    properties,
    stands,
    underwriting,
)

API_PREFIX = "/timberland"

BLUEPRINTS = (
    clock.bp,
    funds.bp,
    properties.bp,
    underwriting.bp,
    stands.bp,
    harvest.bp,
    carbon.bp,
    hbu.bp,
    leases.bp,
    certification.bp,
    hazard.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
