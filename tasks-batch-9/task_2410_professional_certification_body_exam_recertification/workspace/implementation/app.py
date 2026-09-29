"""Professional Certification Body API.

Flask application factory and process entry point.  Every byte of state lives in
plain dicts inside this process (see db.py): there is no database file, no cache
directory, and no seed data, so relaunching this process resets the world.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from response import _base_meta
from routes import (
    applications,
    candidates,
    certificants,
    ceu,
    cycles,
    discipline,
    forms,
    incidents,
    items,
    ops,
    programs,
    registrations,
    sessions,
)

BLUEPRINTS = (
    programs.bp,
    items.bp,
    forms.bp,
    candidates.bp,
    applications.bp,
    sessions.bp,
    registrations.bp,
    incidents.bp,
    certificants.bp,
    cycles.bp,
    ceu.bp,
    discipline.bp,
    ops.bp,
)


def _envelope(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # An unrouted path or an unsupported method still answers in the standard
        # envelope shape rather than Flask's HTML error page.
        return _envelope("ERR_INVALID_REQUEST", err.description or err.name,
                         err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return _envelope("ERR_INVALID_REQUEST", "Unhandled request: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
