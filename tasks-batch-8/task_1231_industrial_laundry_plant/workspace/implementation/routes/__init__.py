"""Route registration."""

from routes import core, customers, transit, sort, wash, garments, delivery, billing

BLUEPRINTS = (
    core.bp,
    customers.bp,
    transit.bp,
    sort.bp,
    wash.bp,
    garments.bp,
    delivery.bp,
    billing.bp,
)


def register_all(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
