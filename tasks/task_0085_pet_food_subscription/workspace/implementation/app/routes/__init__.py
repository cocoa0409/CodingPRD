"""Register all route blueprints."""
from __future__ import annotations

from flask import Flask

from app.routes import (
    customers,
    pets,
    subscriptions,
    orders,
    feedback,
    adjustments,
    recipes,
    warehouses,
    audit_logs,
    admin,
    recommendations,
)


def register_routes(app: Flask) -> None:
    app.register_blueprint(customers.bp)
    app.register_blueprint(pets.bp)
    app.register_blueprint(subscriptions.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(feedback.bp)
    app.register_blueprint(adjustments.bp)
    app.register_blueprint(recipes.bp)
    app.register_blueprint(warehouses.bp)
    app.register_blueprint(audit_logs.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(recommendations.bp)
