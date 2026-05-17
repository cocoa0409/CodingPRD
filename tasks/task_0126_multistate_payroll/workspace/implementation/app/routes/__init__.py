"""Blueprint registration."""
from flask import Flask

from .clock_routes import bp as clock_bp
from .employees import bp as employees_bp
from .w4_profiles import bp as w4_bp
from .garnishments import bp as garnishments_bp
from .pay_periods import bp as pay_periods_bp
from .payroll_items import bp as payroll_items_bp
from .paychecks import bp as paychecks_bp
from .remittances import bp as remittances_bp
from .tax_brackets import bp as tax_brackets_bp
from .test_reset import bp as test_reset_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(clock_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(w4_bp)
    app.register_blueprint(garnishments_bp)
    app.register_blueprint(pay_periods_bp)
    app.register_blueprint(payroll_items_bp)
    app.register_blueprint(paychecks_bp)
    app.register_blueprint(remittances_bp)
    app.register_blueprint(tax_brackets_bp)
    app.register_blueprint(test_reset_bp)
