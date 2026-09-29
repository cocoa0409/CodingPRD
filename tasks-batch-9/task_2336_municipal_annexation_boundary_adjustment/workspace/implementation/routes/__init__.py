"""Blueprint registration."""

from routes.cases import bp as cases_bp
from routes.config import bp as config_bp
from routes.fiscal import bp as fiscal_bp
from routes.hearings import bp as hearings_bp
from routes.petitions import bp as petitions_bp
from routes.plans import bp as plans_bp
from routes.utilities import bp as utilities_bp

BLUEPRINTS = (
    config_bp,
    cases_bp,
    petitions_bp,
    fiscal_bp,
    plans_bp,
    hearings_bp,
    utilities_bp,
)


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
