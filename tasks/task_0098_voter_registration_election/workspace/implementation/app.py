"""Voter Registration & Election Management API — entry point.

Wires Flask, the auth middleware, the global error handlers, and the route
blueprints. The in-memory store starts empty on every boot — see db.py.
No entity is seeded at startup; tests build all preconditions via the API.
"""

import os

from flask import Flask, request

from errors import APIError
from middleware import extract_identity
from response import err

from routes.elections import bp as bp_elections
from routes.precincts import bp as bp_precincts
from routes.registrations import bp as bp_registrations
from routes.ballots import bp as bp_ballots
from routes.cure_cases import bp as bp_cure_cases
from routes.machines import bp as bp_machines
from routes.early_vote import bp as bp_early_vote
from routes.recounts import bp as bp_recounts


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _auth_and_setup():
        if request.method == "OPTIONS":
            return None
        # Let unmatched routes fall through to the 404 handler before auth.
        if request.url_rule is None:
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
        return err("ERR_INVALID_REQUEST", "Method not allowed for this path.", 400)

    @app.errorhandler(400)
    def _bad_request(_e):
        return err("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        if isinstance(e, APIError):
            return err(e.error_id, e.message, e.http_status)
        code = getattr(e, "code", None)
        if isinstance(code, int):
            if code == 404:
                return err("ERR_NOT_FOUND", "Resource not found.", 404)
            if code in (400, 405, 415):
                return err("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return err("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    app.register_blueprint(bp_elections)
    app.register_blueprint(bp_precincts)
    app.register_blueprint(bp_registrations)
    app.register_blueprint(bp_ballots)
    app.register_blueprint(bp_cure_cases)
    app.register_blueprint(bp_machines)
    app.register_blueprint(bp_early_vote)
    app.register_blueprint(bp_recounts)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=False)
