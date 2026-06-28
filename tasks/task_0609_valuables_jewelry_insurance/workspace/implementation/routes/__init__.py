"""Route registration."""
from routes.catalog import bp as catalog_bp
from routes.policies import bp as policies_bp
from routes.endorsements import bp as endorsements_bp
from routes.claims import bp as claims_bp
from routes.repair_orders import bp as repair_orders_bp
from routes.payments import bp as payments_bp


def register_routes(app):
    app.register_blueprint(catalog_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(endorsements_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(repair_orders_bp)
    app.register_blueprint(payments_bp)
