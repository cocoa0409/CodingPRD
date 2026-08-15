"""Legal Aid Intake API — Flask entry point.

Boot contract: binds 0.0.0.0:$PORT (default 10000), runs in the foreground,
store starts empty on every boot.
"""
import os

from flask import Flask

from db import db
from errors import ApiError, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    # Serialize all request handling: the store is plain dicts.
    @app.before_request
    def _acquire_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    from routes import (applications, cases, clients, conflict_checks, grants,
                        ops, panel, records, referrals, reports, staff,
                        venue_rules)
    for module in (clients, applications, conflict_checks, cases, staff,
                   panel, referrals, grants, reports, venue_rules, records,
                   ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.status)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response(ERR_NOT_FOUND[0], "Resource not found",
                              ERR_NOT_FOUND[1])

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response(ERR_NOT_FOUND[0], "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _internal(err):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True)
