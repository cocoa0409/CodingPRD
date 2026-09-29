"""Seed Production & Conditioning API.

Flask application factory and process entry point.  All state is held in
process memory only (see store.py) and nothing is ever seeded: a fresh boot
starts with every collection empty and the logical clock at its fixed default.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response, object_response
from errors import ApiError
from routes.certification import bp as certification_bp
from routes.conditioning import bp as conditioning_bp
from routes.contracts import bp as contracts_bp
from routes.harvest import bp as harvest_bp
from routes.inspections import bp as inspections_bp
from routes.reference import bp as reference_bp
from routes.settlements import bp as settlements_bp
from store import db
from validation import Field, authenticate, json_body, parse_fields


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(harvest_bp)
    app.register_blueprint(conditioning_bp)
    app.register_blueprint(certification_bp)
    app.register_blueprint(settlements_bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        authenticate(("ProgramAdmin",))
        data = parse_fields(json_body(), [Field("current_utc", "datetime")])
        db.set_clock(data["current_utc"], data["current_utc__raw"])
        return object_response({"current_utc": db.clock_raw})

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this route.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INTERNAL", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
