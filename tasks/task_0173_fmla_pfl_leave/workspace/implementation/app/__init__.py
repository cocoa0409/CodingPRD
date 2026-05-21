"""Application factory for the FMLA/PFL Leave Management API."""
from flask import Flask

from .errors import register_error_handlers
from .routes.employers import bp_employers
from .routes.worksites import bp_worksites
from .routes.employees import bp_employees
from .routes.leave_cases import bp_leave_cases
from .routes.pfl_claims import bp_pfl_claims
from .routes.benefit_invoices import bp_benefit_invoices
from .routes.system import bp_system


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(bp_employers)
    app.register_blueprint(bp_worksites)
    app.register_blueprint(bp_employees)
    app.register_blueprint(bp_leave_cases)
    app.register_blueprint(bp_pfl_claims)
    app.register_blueprint(bp_benefit_invoices)
    app.register_blueprint(bp_system)

    register_error_handlers(app)
    return app
