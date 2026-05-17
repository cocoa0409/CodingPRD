"""Route registration aggregator."""
from flask import Flask

from .account_holders import bp as account_holders_bp
from .accounts import bp as accounts_bp
from .audit_events import bp as audit_events_bp
from .claims import bp as claims_bp
from .clock_routes import bp as clock_bp
from .contributions import bp as contributions_bp
from .dependents import bp as dependents_bp
from .ops_runs import bp as ops_runs_bp
from .plan_years import bp as plan_years_bp
from .qualified_expenses import bp as qualified_expenses_bp
from .test_infra import bp as test_infra_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(account_holders_bp)
    app.register_blueprint(dependents_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(plan_years_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(qualified_expenses_bp)
    app.register_blueprint(audit_events_bp)
    app.register_blueprint(ops_runs_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(test_infra_bp)
