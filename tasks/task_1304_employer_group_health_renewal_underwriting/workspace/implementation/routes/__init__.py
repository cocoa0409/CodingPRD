"""Route registration."""
from routes import (
    cases, brokers, census, claims, plans, quotes,
    stoploss, negotiations, enrollment, disclosures, clock,
)


def register_routes(app):
    for mod in (cases, brokers, census, claims, plans, quotes,
                stoploss, negotiations, enrollment, disclosures, clock):
        app.register_blueprint(mod.bp)
