"""Season pass blockout administration API (Python + Flask, in-memory store)."""

import os
import threading

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.compliance import bp as compliance_bp
from routes.park_ops import bp as park_ops_bp
from routes.passes import bp as passes_bp
from routes.programs import bp as programs_bp


class SerializedApp(object):
    """Serialise request handling so the in-memory store stays consistent."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.RLock()

    def __call__(self, environ, start_response):
        with self.lock:
            return list(self.wsgi_app(environ, start_response))


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(passes_bp)
    app.register_blueprint(park_ops_bp)
    app.register_blueprint(compliance_bp)

    @app.before_request
    def _open_unit_of_work():
        if request.method != "GET":
            db.begin()
        return None

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        return error_response("ERR_INVALID_REQUEST", exc.description, exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    app.wsgi_app = SerializedApp(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
