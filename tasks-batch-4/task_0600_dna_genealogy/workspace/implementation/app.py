"""Consumer DNA Genealogy API — entry point.

Storage is in-memory only and starts EMPTY on every boot; nothing is seeded.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INVALID_REQUEST"
        return jsonify(error_body(error_id, exc.description)), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
