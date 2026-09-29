"""Route registration. One module per resource group."""
from routes import (
    agreements,
    bookings,
    certifications,
    disputes,
    markets,
    offers,
    overrides,
    packages,
    parity,
    placements,
    ranking,
    rate_plans,
    scorecards,
    suppliers,
    system,
)

MODULES = (
    system,
    markets,
    suppliers,
    agreements,
    certifications,
    rate_plans,
    offers,
    parity,
    overrides,
    placements,
    ranking,
    packages,
    bookings,
    disputes,
    scorecards,
)


def register(app):
    for module in MODULES:
        app.register_blueprint(module.bp)
