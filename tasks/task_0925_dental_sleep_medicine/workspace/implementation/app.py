"""Dental Sleep Medicine API — entry point.

Storage is process memory only; every collection starts empty on every boot and
nothing is seeded, preloaded or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError
from routes.appliances import bp as appliances_bp
from routes.billing import bp as billing_bp
from routes.clinical import bp as clinical_bp
from routes.core import bp as core_bp
from routes.efficacy import bp as efficacy_bp
from routes.lab import bp as lab_bp
from routes.paperwork import bp as paperwork_bp
from routes.titration import bp as titration_bp

HTTP_FALLBACK = {
    400: "ERR_VALIDATION",
    401: "ERR_UNAUTHENTICATED",
    403: "ERR_FORBIDDEN_ROLE",
    404: "ERR_RECORD_NOT_FOUND",
    405: "ERR_RECORD_NOT_FOUND",
    409: "ERR_INVALID_STATE",
    415: "ERR_VALIDATION",
    422: "ERR_VALIDATION",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in (core_bp, clinical_bp, paperwork_bp, lab_bp, appliances_bp,
                      titration_bp, efficacy_bp, billing_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 405:
            status = 404
        return error(HTTP_FALLBACK.get(status, "ERR_VALIDATION"),
                     exc.description or "Request could not be served.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error("ERR_VALIDATION", "Unexpected server condition: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
