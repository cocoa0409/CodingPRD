"""ML Model Deployment & Monitoring API — Flask application entry point.

Storage is entirely in-process (see db.py): every boot starts with a completely
empty store and the logical clock at its documented default, so re-invoking
start.sh wipes every byte of state.  No entity is ever seeded.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.experiments import bp as experiments_bp
from routes.monitoring import bp as monitoring_bp
from routes.registry import bp as registry_bp
from routes.serving import bp as serving_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(registry_bp)
    app.register_blueprint(serving_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(experiments_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(response.error(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
            message = "resource not found"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "method not allowed"
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or "invalid request"
        return jsonify(response.error(error_id, message)), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return jsonify(response.error("ERR_INVALID_REQUEST", str(exc))), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
