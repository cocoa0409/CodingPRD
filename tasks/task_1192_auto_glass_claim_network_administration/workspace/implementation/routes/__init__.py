from routes.reference import bp as reference_bp
from routes.claims import bp as claims_bp
from routes.workorders import bp as workorders_bp
from routes.invoices import bp as invoices_bp
from routes.fraud import bp as fraud_bp
from routes.warranty import bp as warranty_bp
from routes.clock import bp as clock_bp


def register_routes(app):
    app.register_blueprint(reference_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(workorders_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(fraud_bp)
    app.register_blueprint(warranty_bp)
    app.register_blueprint(clock_bp)
