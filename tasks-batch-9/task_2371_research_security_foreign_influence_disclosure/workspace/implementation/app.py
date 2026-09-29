"""Research Security & Foreign Influence Disclosure API.

Flask application factory and process entry point. Storage is in-memory only
(see db.py) and nothing is ever seeded: a fresh boot serves an empty dataset.
"""

import os

from flask import Flask, g

import db
import response
from errors import STATUS, ApiError
from routes import (clock, disclosures, grants, incidents, investigators, items,
                    organizations, personnel, projects, statements, subawards,
                    training, travel)

BLUEPRINTS = (
    investigators.bp,
    organizations.bp,
    projects.bp,
    personnel.bp,
    disclosures.bp,
    items.bp,
    statements.bp,
    travel.bp,
    grants.bp,
    incidents.bp,
    training.bp,
    subawards.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # Every request runs under the store lock, so each request observes and
    # leaves a consistent picture of the derived-field graph.
    @app.before_request
    def _serialize_request():
        db.lock.acquire()
        g._holds_lock = True
        db.begin_request()

    @app.teardown_request
    def _release_request(_exception=None):
        if g.pop("_holds_lock", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message,
                                       error.http_status)

    @app.errorhandler(404)
    def _not_found(_error):
        return response.error_response("ERR_INVALID_REQUEST",
                                       "The requested route does not exist.",
                                       404)

    @app.errorhandler(405)
    def _not_allowed(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST",
            "The HTTP method is not allowed on this route.", 405)

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return _api_error(error)
        status = getattr(error, "code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return response.error_response("ERR_INVALID_REQUEST", str(error),
                                           status)
        app.logger.exception("unhandled error")
        return response.error_response("ERR_INVALID_REQUEST", str(error), 500)

    @app.get("/_health")
    def _health():
        return response.object_response({
            "status": "ok",
            "current_utc": db.clock_str(),
            "error_catalog_size": len(STATUS),
        })

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
