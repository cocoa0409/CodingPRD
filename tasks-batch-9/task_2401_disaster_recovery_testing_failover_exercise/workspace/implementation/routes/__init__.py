"""Blueprint registry."""

from routes.audit import bp as audit_bp
from routes.estate import bp as estate_bp
from routes.exercises import bp as exercises_bp
from routes.groups import bp as groups_bp

BLUEPRINTS = (estate_bp, groups_bp, exercises_bp, audit_bp)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
