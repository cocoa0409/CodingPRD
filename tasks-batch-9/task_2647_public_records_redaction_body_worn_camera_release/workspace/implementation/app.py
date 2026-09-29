"""Public Records Redaction & Body-Worn Camera Release API.

Flask application factory and entrypoint.  All state lives in process memory;
nothing is seeded at startup.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes import (
    assets,
    clock,
    directory,
    endgame,
    fees,
    redaction,
    requests as requests_routes,
    review,
)

BLUEPRINTS = (
    directory.bp,
    assets.bp,
    requests_routes.bp,
    review.bp,
    redaction.bp,
    fees.bp,
    endgame.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - very old Flask
        app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify(error_response(err.error_id, err.message)), err.http_status

    @app.errorhandler(400)
    def _bad_request(err):
        return jsonify(error_response("ERR_VALIDATION",
                                      "the request could not be parsed")), 400

    @app.errorhandler(404)
    def _not_found(err):
        return jsonify(error_response("ERR_VALIDATION",
                                      "no such endpoint")), 404

    @app.errorhandler(405)
    def _not_allowed(err):
        return jsonify(error_response("ERR_VALIDATION",
                                      "method not allowed on this path")), 405

    @app.errorhandler(500)
    def _server_error(err):  # pragma: no cover
        return jsonify(error_response("ERR_VALIDATION",
                                      "internal server error")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
