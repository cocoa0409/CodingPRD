"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError, error_body
from logic import run_system_transitions
import routes_core
import routes_people
import routes_scoring
import routes_misc


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_people.bp)
    app.register_blueprint(routes_scoring.bp)
    app.register_blueprint(routes_misc.bp)

    @app.before_request
    def _sweep():
        # Clock-driven transitions fire as the logical clock crosses thresholds.
        run_system_transitions()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.status

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            body = error_body("ERR_RESOURCE_NOT_FOUND", "Resource not found")
        elif err.code == 405:
            body = error_body("ERR_RESOURCE_NOT_FOUND", "Method not allowed")
        elif err.code == 400:
            body = error_body("ERR_INVALID_REQUEST", "Malformed request")
        else:
            body = error_body("ERR_INVALID_REQUEST",
                              getattr(err, "description", "Request failed"))
        return jsonify(body), (err.code if err.code in (400, 404, 405) else 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return jsonify(error_body("ERR_INVALID_REQUEST", str(err))), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
