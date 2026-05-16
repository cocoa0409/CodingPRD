"""Blueprint registration."""
from flask import Flask

from .appeals import bp as appeals_bp
from .authorizations import bp as auth_bp
from .catalog import bp as catalog_bp
from .clock import bp as clock_bp
from .evidence import bp as evidence_bp
from .patients import bp as patients_bp
from .peer_to_peer import bp as p2p_bp
from .providers import bp as providers_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(patients_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(p2p_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(clock_bp)
