"""Wire all route blueprints into the Flask app."""
from flask import Flask, g

from app.auth import authenticate
from app.routes.cases import bp as cases_bp
from app.routes.clock import bp as clock_bp
from app.routes.disclosures import bp as disclosures_bp
from app.routes.final_judgments import bp as final_judgments_bp
from app.routes.mediation_sessions import bp as mediation_bp
from app.routes.parenting_plans import bp as plans_bp
from app.routes.parties import bp as parties_bp
from app.routes.support_orders import bp as support_bp
from app.routes.temp_orders import bp as temp_orders_bp


def register_routes(app: Flask):
    @app.before_request
    def _auth():
        # PRD §2.1: every endpoint requires the two identity headers.
        authenticate()

    app.register_blueprint(clock_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(mediation_bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(temp_orders_bp)
    app.register_blueprint(final_judgments_bp)
