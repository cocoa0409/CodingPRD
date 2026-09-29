"""Consumer Repair Parts & Self-Service Repair Program API.

Flask application factory and entrypoint. Storage is in-memory only and is
created empty on every boot: nothing is seeded, preloaded, or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import assessments, catalog, compatibilities, compliance, manual_revisions, \
    orders, product_models, providers, returns
from routes.helpers import API_PREFIX

BLUEPRINTS = (
    product_models.bp,
    compliance.bp,
    catalog.bp,
    compatibilities.bp,
    manual_revisions.bp,
    assessments.bp,
    orders.bp,
    providers.bp,
    returns.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this path.", 405))

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        return error_response(ApiError(
            "ERR_INVALID_REQUEST", err.description or "Invalid request.",
            err.code or 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", str(err), 500))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
