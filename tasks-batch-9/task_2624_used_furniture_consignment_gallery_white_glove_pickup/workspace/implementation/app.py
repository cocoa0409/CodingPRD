"""Used-furniture consignment gallery API.

Flask + in-memory dicts only. Every process starts with an empty store and the
logical clock parked at 2026-08-01T00:00:00Z; nothing is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import audits, commerce, items, logistics, ops, schedules, standing


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (standing, schedules, items, logistics, commerce, audits, ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return envelope.error("ERR_VALIDATION", "No such resource path.", 404)
        if status == 405:
            return envelope.error(
                "ERR_VALIDATION", "Method not allowed for this resource path.", 405
            )
        if status == 400:
            return envelope.error(
                "ERR_VALIDATION", "The request could not be parsed.", 400
            )
        return envelope.error("ERR_VALIDATION", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return envelope.error("ERR_VALIDATION", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
