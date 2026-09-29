"""Flavor House Sample Development & Formulation API (Flask, in-memory)."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes.batches import bp as batches_bp
from routes.briefs import bp as briefs_bp
from routes.commercial import bp as commercial_bp
from routes.formulas import bp as formulas_bp
from routes.lots import bp as lots_bp
from routes.materials import bp as materials_bp
from routes.shipments import bp as shipments_bp
from routes.tests import bp as tests_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (briefs_bp, materials_bp, formulas_bp, lots_bp, tests_bp,
                      shipments_bp, batches_bp, commercial_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "the requested resource does not exist",
                         404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED",
                         "the method is not allowed for this resource", 405)
        if exc.code and 400 <= exc.code < 500:
            return error("ERR_INVALID_REQUEST", exc.description or "bad request",
                         exc.code)
        return error("ERR_INTERNAL", exc.description or "internal error",
                     exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INTERNAL", "internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
