"""De Novo Bank Charter Application service -- entry point.

The store is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here or in any module.  Tests build every
precondition through the declared endpoints.
"""
import os

from flask import Flask, g

import db
import response
from errors import ApiError
from routes import (
    clock,
    deviations,
    exams,
    filings,
    groups,
    plans,
    policies,
    raises,
    reads,
    vendors,
)

BLUEPRINTS = (
    reads.bp,
    groups.bp,
    plans.bp,
    raises.bp,
    filings.bp,
    policies.bp,
    vendors.bp,
    exams.bp,
    deviations.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:  # Flask >= 2.3 moved the flag onto the JSON provider
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover
        pass

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        g.touched = []
        db.LOCK.acquire()
        g.holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "holds_lock", False):
            g.holds_lock = False
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        db.discard()
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        db.discard()
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        db.discard()
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this path.", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        db.discard()
        app.logger.exception("unhandled error")
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request could not be processed: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
