"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask, jsonify

from core import ApiError, error_body, E_NOT_FOUND, E_INVALID_REQUEST


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_pips
    import routes_outcomes
    import routes_flat
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_pips.bp)
    app.register_blueprint(routes_outcomes.bp)
    app.register_blueprint(routes_flat.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_body(E_NOT_FOUND[0], "resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_body(E_NOT_FOUND[0], "method not allowed")), 404

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify(error_body(E_INVALID_REQUEST[0], "malformed request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return jsonify(error_body(e.error_id, e.message)), e.http_status
        app.logger.exception("unexpected error")
        return jsonify(error_body(E_INVALID_REQUEST[0],
                                  "unexpected server error")), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
