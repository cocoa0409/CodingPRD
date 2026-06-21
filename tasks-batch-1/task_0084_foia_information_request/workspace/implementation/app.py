"""FOIA Information Request API — entry point.

Wires Flask, the auth middleware, the global error handlers, and the route
blueprints. The in-memory store (db.py) starts empty on every boot — no
business entities are ever seeded.
"""

import os

from flask import Flask, request

from errors import APIError
from middleware import extract_identity
from response import err

from routes.actors import bp as bp_actors
from routes.requests import bp as bp_requests
from routes.records import bp as bp_records
from routes.appeals import bp as bp_appeals
from routes.objections import bp as bp_objections
from routes.bookings import bp as bp_bookings
from routes.audit import bp as bp_audit
from routes.system_ops import bp as bp_system_ops


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        if request.method == "OPTIONS":
            return None
        if request.url_rule is None:
            # No matching route; let the 404 handler emit the envelope.
            return None
        try:
            extract_identity()
        except APIError as e:
            return err(e.error_id, e.message, e.http_status)
        return None

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found_handler(_e):
        return err("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return err("ERR_INVALID_REQUEST", "Method not allowed for this path.", 422)

    @app.errorhandler(400)
    def _bad_request(_e):
        return err("ERR_INVALID_REQUEST", "Malformed request.", 422)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        if isinstance(e, APIError):
            return err(e.error_id, e.message, e.http_status)
        code = getattr(e, "code", None)
        if isinstance(code, int):
            if code == 404:
                return err("ERR_NOT_FOUND", "Resource not found.", 404)
            if code in (400, 405, 415):
                return err("ERR_INVALID_REQUEST", "Malformed request.", 422)
        return err("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    app.register_blueprint(bp_actors)
    app.register_blueprint(bp_requests)
    app.register_blueprint(bp_records)
    app.register_blueprint(bp_appeals)
    app.register_blueprint(bp_objections)
    app.register_blueprint(bp_bookings)
    app.register_blueprint(bp_audit)
    app.register_blueprint(bp_system_ops)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
