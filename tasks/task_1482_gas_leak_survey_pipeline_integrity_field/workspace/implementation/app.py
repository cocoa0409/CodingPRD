"""Flask entry point: app factory, error handlers, route registration."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from services import process_time_based_events


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _sweep_time_based_events():
        process_time_based_events()

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def _handle_404(e):
        return jsonify(error_body("ERR_NOT_FOUND",
                                  "Referenced entity does not exist")), 404

    @app.errorhandler(405)
    def _handle_405(e):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "Method not allowed")), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, HTTPException):
            return jsonify(error_body("ERR_INVALID_REQUEST",
                                      e.description)), e.code
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  f"Internal error: {e}")), 500

    from routes import bp
    app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
