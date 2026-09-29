"""Blueprint registration for all fifty declared endpoints (api_prefix '/')."""

from routes import bidders, clock, contracts, events, listings, lots, sellers, trustee

BLUEPRINTS = (
    sellers.bp,
    listings.bp,
    trustee.bp,
    events.bp,
    lots.bp,
    bidders.bp,
    contracts.bp,
    clock.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
