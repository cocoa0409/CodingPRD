"""Investor Relations & Shareholder Services API.

Flask application factory and process entry point.  All state lives in memory
(see store.py); a fresh process therefore starts with an empty system and no
seeded data of any kind.
"""
import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from envelope import error_response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes.companies import bp as companies_bp  # noqa: E402
from routes.contacts import bp as contacts_bp  # noqa: E402
from routes.disclosures import bp as disclosures_bp  # noqa: E402
from routes.drafts import bp as drafts_bp  # noqa: E402
from routes.inquiries import bp as inquiries_bp  # noqa: E402
from routes.instructions import bp as instructions_bp  # noqa: E402
from routes.meetings import bp as meetings_bp  # noqa: E402
from routes.roadshow import bp as roadshow_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (companies_bp, contacts_bp, disclosures_bp, inquiries_bp,
                      drafts_bp, roadshow_bp, meetings_bp, instructions_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        message = exc.description or exc.name
        return error_response("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
