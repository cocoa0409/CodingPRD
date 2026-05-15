"""Blueprint registration."""
from flask import Flask

from app.routes import (
    audit_routes,
    clock_routes,
    compliance_routes,
    counterparty_routes,
    limit_routes,
    limit_adjustment_routes,
    market_data_routes,
    settlement_routes,
    stop_loss_routes,
    trade_routes,
    trader_routes,
)


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(trader_routes.bp)
    app.register_blueprint(market_data_routes.bp)
    app.register_blueprint(limit_routes.bp)
    app.register_blueprint(limit_adjustment_routes.bp)
    app.register_blueprint(trade_routes.bp)
    app.register_blueprint(stop_loss_routes.bp)
    app.register_blueprint(counterparty_routes.bp)
    app.register_blueprint(settlement_routes.bp)
    app.register_blueprint(compliance_routes.bp)
    app.register_blueprint(audit_routes.bp)
    app.register_blueprint(clock_routes.bp)
