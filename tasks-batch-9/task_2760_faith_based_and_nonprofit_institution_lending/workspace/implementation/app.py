"""Faith-based and nonprofit institution lending API.

Flask application factory and process entry point.  All state lives in
process-local dictionaries in store.py; nothing is persisted and nothing is
seeded — every entity is created through a declared endpoint.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import applications, campaigns, collateral, covenants, draws
from routes import governance, institutions, loans, workouts


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(institutions.bp)
    app.register_blueprint(governance.bp)
    app.register_blueprint(campaigns.bp)
    app.register_blueprint(collateral.bp)
    app.register_blueprint(applications.bp)
    app.register_blueprint(loans.bp)
    app.register_blueprint(draws.bp)
    app.register_blueprint(covenants.bp)
    app.register_blueprint(workouts.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message,
                                      exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return envelope.error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The method is not allowed for this path.", 405)
        if exc.code in (400, 415):
            return envelope.error_response(
                "ERR_INVALID_REQUEST",
                "The request body could not be parsed.", 422)
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.",
            exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error: %s", exc)
        return envelope.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
