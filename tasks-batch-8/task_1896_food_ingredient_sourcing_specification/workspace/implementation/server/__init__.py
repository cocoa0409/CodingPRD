"""Flask application factory: error handlers and blueprint registration."""
from flask import Flask

from .envelope import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    respond_error,
)


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return respond_error(ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return respond_error(ERR_INVALID_REQUEST, 400, "method not allowed for this path")

    @app.errorhandler(500)
    def handle_500(exc):
        return respond_error("ERR_INTERNAL", 500, "internal server error")

    from . import (
        routes_coas,
        routes_ingredients,
        routes_misc,
        routes_sources,
        routes_subs,
        routes_suppliers,
    )

    app.register_blueprint(routes_ingredients.bp)
    app.register_blueprint(routes_suppliers.bp)
    app.register_blueprint(routes_sources.bp)
    app.register_blueprint(routes_coas.bp)
    app.register_blueprint(routes_subs.bp)
    app.register_blueprint(routes_misc.bp)
    return app
