"""Content Moderation Operations API -- Flask application factory and entrypoint.

Every route lives under the /moderation prefix (PRD §2).  Storage is a set of
in-memory Python dicts held in core.Store: the process starts with an entirely
empty dataset on every boot and nothing is ever seeded or persisted to disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import r_accounts
import r_appeals
import r_cases
import r_detection
import r_policy
import r_qa
import r_reports
import r_workforce
from core import ApiError, error_response

BLUEPRINTS = (
    r_accounts.bp,
    r_policy.bp,
    r_workforce.bp,
    r_detection.bp,
    r_cases.bp,
    r_appeals.bp,
    r_qa.bp,
    r_reports.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/moderation")

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
