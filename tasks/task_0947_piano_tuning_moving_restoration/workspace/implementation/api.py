"""Flask application factory: error handling plus blueprint registration."""

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    import routes_admin
    import routes_clients
    import routes_instruments
    import routes_scheduling
    import routes_quotes
    import routes_orders
    import routes_moves
    import routes_warranty
    import routes_consignment

    for module in (routes_admin, routes_clients, routes_instruments,
                   routes_scheduling, routes_quotes, routes_orders,
                   routes_moves, routes_warranty, routes_consignment):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        body = error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            body = error_body("ERR_RESOURCE_NOT_FOUND", "No such route.")
            return jsonify(body), 404
        if exc.code == 405:
            body = error_body("ERR_RESOURCE_NOT_FOUND", "Method not allowed.")
            return jsonify(body), 404
        body = error_body("ERR_VALIDATION", exc.description or "Bad request.")
        return jsonify(body), exc.code if exc.code and exc.code < 500 else 400

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        body = error_body("ERR_VALIDATION", "Unexpected server error: %s" % exc)
        return jsonify(body), 400

    return app
