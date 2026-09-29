"""Blueprint registration for all 45 endpoints."""

from routes.amnesty import bp as amnesty_bp
from routes.appeals import bp as appeals_bp
from routes.cases import bp as cases_bp
from routes.clock_control import bp as clock_bp
from routes.employees import bp as employees_bp
from routes.notices import bp as notices_bp
from routes.programs import bp as programs_bp
from routes.recoveries import bp as recoveries_bp
from routes.submissions import bp as submissions_bp

BLUEPRINTS = (
    clock_bp,
    employees_bp,
    programs_bp,
    cases_bp,
    submissions_bp,
    amnesty_bp,
    appeals_bp,
    notices_bp,
    recoveries_bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
