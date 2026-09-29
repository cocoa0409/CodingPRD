"""Blueprint registry."""

from routes import claims, disputes, fulfillment, orders, prescriptions, reference, returns, verification

BLUEPRINTS = (
    reference.bp,
    prescriptions.bp,
    verification.bp,
    orders.bp,
    fulfillment.bp,
    returns.bp,
    claims.bp,
    disputes.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
