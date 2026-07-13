"""Elevator & Conveyance Inspection API — Flask application entry point.

In-memory store only; a fresh process starts completely empty. The logical
clock defaults to period index 0. No entity data is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

from routes.accidents import bp as accidents_bp
from routes.certificates import bp as certificates_bp
from routes.citations import bp as citations_bp
from routes.clock import bp as clock_bp
from routes.deficiencies import bp as deficiencies_bp
from routes.devices import bp as devices_bp
from routes.fees import bp as fees_bp
from routes.inspections import bp as inspections_bp
from routes.inspectors import bp as inspectors_bp
from routes.oos import bp as oos_bp
from routes.owners import bp as owners_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        owners_bp,
        inspectors_bp,
        devices_bp,
        inspections_bp,
        deficiencies_bp,
        citations_bp,
        certificates_bp,
        oos_bp,
        fees_bp,
        accidents_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Wrap framework-level HTTP errors in the standard envelope.
        return error_response("ERR_HTTP_" + str(err.code), err.description or err.name, err.code)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
