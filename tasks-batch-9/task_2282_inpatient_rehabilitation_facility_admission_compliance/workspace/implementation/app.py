"""IRF Admission & Compliance API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: no entity
is seeded, preloaded or hardcoded.  All data arrives through the declared
endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_envelope
from routes import (admissions, assessments, clinicians, clock, conferences, facilities,
                    patients, plans, qrp, reviews, screenings, therapy)

BLUEPRINTS = (
    facilities.bp,
    clinicians.bp,
    patients.bp,
    screenings.bp,
    admissions.bp,
    plans.bp,
    therapy.bp,
    conferences.bp,
    assessments.bp,
    reviews.bp,
    qrp.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_envelope(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return error_envelope("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if error.code == 405:
            return error_envelope("ERR_NOT_FOUND", "The method is not allowed for this path.", 404)
        if error.code == 401:
            return error_envelope("ERR_UNAUTHENTICATED", "Authentication is required.", 401)
        if error.code == 403:
            return error_envelope("ERR_FORBIDDEN_ROLE", "The role is not authorised.", 403)
        if error.code and error.code < 500:
            return error_envelope("ERR_INVALID_REQUEST", "The request could not be processed.", 400)
        return error_envelope("ERR_INVALID_REQUEST", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return error_envelope("ERR_INVALID_REQUEST", "Internal server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
