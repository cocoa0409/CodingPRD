"""Application entry point.

Fuel Tax and Registration Apportionment Reporting API.

Storage is in-memory only: `common.DB` is a plain object holding Python dicts
and is rebuilt empty every time this process starts.  Nothing is ever seeded,
preloaded or persisted, so a fresh boot always begins with an empty world and
every entity is created by a client through the declared endpoints.
"""

import os

from flask import Flask, jsonify

from common import ApiError, err_body
import routes_ref
import routes_mileage
import routes_returns
import routes_registration


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_mileage.bp)
    app.register_blueprint(routes_returns.bp)
    app.register_blueprint(routes_registration.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(err_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def handle_400(exc):
        return jsonify(err_body("ERR_INVALID_REQUEST",
                                "The request payload is not valid.")), 400

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(err_body("ERR_NOT_FOUND",
                                "The requested resource does not exist.")), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(err_body("ERR_METHOD_NOT_ALLOWED",
                                "This method is not allowed for this path.")), 405

    @app.errorhandler(415)
    def handle_415(exc):
        return jsonify(err_body("ERR_INVALID_REQUEST",
                                "The request payload is not valid.")), 415

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        return jsonify(err_body("ERR_INTERNAL",
                                "An unexpected internal error occurred.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True,
            debug=False, use_reloader=False)
