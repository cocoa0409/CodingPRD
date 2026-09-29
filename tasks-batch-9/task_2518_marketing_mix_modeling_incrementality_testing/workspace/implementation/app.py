"""Marketing Mix Modeling & Incrementality Testing API.

Entry point: registers every blueprint, installs the error handlers and serves on
0.0.0.0:$PORT in the foreground. The in-memory store starts empty on every boot —
nothing is ever seeded.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import (budgets, calibration, channels, clock, experiments, geo_cells,
                     markets, model_runs, observations, reports, windows)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (markets, channels, geo_cells, windows, observations, model_runs,
                   experiments, calibration, budgets, reports, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404
        if exc.code == 405:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST", "Method not allowed for this route.")), 405
        if exc.code == 400:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST", "The request could not be parsed.")), 400
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Request failed.")), \
            exc.code or 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
