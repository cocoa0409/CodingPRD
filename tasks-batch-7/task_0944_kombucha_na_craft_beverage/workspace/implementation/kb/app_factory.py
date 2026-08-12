"""Flask application factory: blueprint registration and error handling."""

from flask import Flask
from werkzeug.exceptions import HTTPException

from .envelope import error_response
from .errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    from .routes_accounts import bp as accounts_bp
    from .routes_batches import bp as batches_bp
    from .routes_clock import bp as clock_bp
    from .routes_cultures import bp as cultures_bp
    from .routes_ingredients import bp as ingredients_bp
    from .routes_kegs import bp as kegs_bp
    from .routes_lots import bp as lots_bp
    from .routes_packaging import bp as packaging_bp
    from .routes_qa import bp as qa_bp
    from .routes_recipes import bp as recipes_bp
    from .routes_shipments import bp as shipments_bp
    from .routes_subscriptions import bp as subscriptions_bp
    from .routes_taproom import bp as taproom_bp

    for blueprint in (
        clock_bp,
        recipes_bp,
        cultures_bp,
        ingredients_bp,
        batches_bp,
        qa_bp,
        packaging_bp,
        lots_bp,
        kegs_bp,
        accounts_bp,
        shipments_bp,
        subscriptions_bp,
        taproom_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_COMMERCIAL_RESOURCE_NOT_FOUND", "No such route.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_VALIDATION", "Method not allowed for this route.", 405
            )
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "Malformed request.", 400)
        return error_response(
            "ERR_VALIDATION", exc.description or "Request failed.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % exc, 400)

    return app
