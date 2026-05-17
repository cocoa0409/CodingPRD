"""Register all Flask blueprints onto the app."""
from flask import Flask

from .patients import bp as patients_bp
from .vaccine_products import bp as products_bp
from .vaccine_lots import bp as lots_bp
from .doses import bp as doses_bp
from .allergies import bp as allergies_bp
from .adverse_events import bp as ae_bp
from .schedule_rules import bp as schedule_bp
from .certificates import bp as certs_bp
from .provider_orgs import bp as providers_bp
from .test_infra import bp as test_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(patients_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(doses_bp)
    app.register_blueprint(allergies_bp)
    app.register_blueprint(ae_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(certs_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(test_bp)
