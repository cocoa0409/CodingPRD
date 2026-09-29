"""Legislative Bill Drafting & Fiscal Note Preparation API.

Entry point: registers every blueprint, installs the error handlers that render
the PRD S2.2 error envelope, and serialises requests behind a single lock so
the in-memory store stays consistent.  The store starts empty on every boot --
nothing is seeded here or in any imported module.
"""

import os

from flask import Flask, g

import store
from envelope import error_response
from errors import ApiError
import routes_amendments
import routes_bills
import routes_drafting
import routes_enrollment
import routes_fiscal
import routes_reads
import routes_reference


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_reads.bp)
    app.register_blueprint(routes_drafting.bp)
    app.register_blueprint(routes_bills.bp)
    app.register_blueprint(routes_fiscal.bp)
    app.register_blueprint(routes_amendments.bp)
    app.register_blueprint(routes_enrollment.bp)

    @app.before_request
    def _acquire():
        store.LOCK.acquire()
        g._holds_lock = True
        store.begin_request()

    @app.teardown_request
    def _release(exc):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        # The style-noncompliance refusal deliberately persists the recorded
        # finding count (PRD S3.4), so the mutation tracker is flushed even on
        # an error path.
        store.commit()
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        store.rollback()
        return error_response(
            "ERR_INVALID_REQUEST", "Unknown route.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        store.rollback()
        return error_response(
            "ERR_INVALID_REQUEST", "Method not allowed for this route.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        store.rollback()
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    @app.after_request
    def _commit(response):
        if response.status_code < 400:
            store.commit()
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
