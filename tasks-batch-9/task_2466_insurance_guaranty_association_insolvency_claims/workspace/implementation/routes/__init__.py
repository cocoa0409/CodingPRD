"""Flask blueprints covering the 47 declared endpoints."""

from routes.claim_routes import claims_bp
from routes.core import core_bp
from routes.funding import funding_bp
from routes.policy_routes import policies_bp

BLUEPRINTS = (core_bp, policies_bp, claims_bp, funding_bp)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
