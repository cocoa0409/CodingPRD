"""Blueprint registration."""

from routes.change import change_bp
from routes.master import master_bp
from routes.production import production_bp
from routes.supply import supply_bp

BLUEPRINTS = (master_bp, supply_bp, production_bp, change_bp)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
