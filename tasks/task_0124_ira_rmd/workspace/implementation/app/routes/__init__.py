"""Blueprint registration."""
from flask import Flask

from .clock_routes import bp as clock_bp
from .participants import bp as participants_bp
from .accounts import bp as accounts_bp
from .contributions import bp as contributions_bp
from .distributions import bp as distributions_bp
from .conversions import bp as conversions_bp
from .claims import bp as claims_bp
from .forms import bp as forms_bp
from .test_infra import bp as test_infra_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(clock_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(conversions_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(forms_bp)
    app.register_blueprint(test_infra_bp)
