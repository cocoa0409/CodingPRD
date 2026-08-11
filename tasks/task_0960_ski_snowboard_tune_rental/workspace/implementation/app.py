import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
from routes import register_routes
from services import run_sweeps


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _clock_sweeps():
        # Clock-driven transitions are also evaluated lazily on read.
        run_sweeps()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(HTTPException)
    def _http_error(e):
        if e.code == 404:
            body = error_body("ERR_NOT_FOUND", "Resource not found")
        else:
            body = error_body("ERR_INVALID_REQUEST",
                              e.description or "Bad request")
        return jsonify(body), (e.code or 400)

    @app.errorhandler(Exception)
    def _generic_error(e):
        return jsonify(error_body("ERR_INTERNAL", str(e))), 500

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
