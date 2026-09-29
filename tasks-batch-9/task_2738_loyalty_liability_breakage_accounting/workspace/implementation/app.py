"""Loyalty liability and breakage accounting API.

In-memory only: every process starts with an empty store and a logical clock
reading exactly 2026-08-01T00:00:00Z. Nothing is seeded, cached or persisted.
"""
import os

from flask import Flask, g

import db
from errors import ApiError
from response import error_body
from routes import (breakage_estimates, change_orders, clock, config,
                    partner_agreements, periods, point_lots,
                    redemption_events, settlement_statements)
from routes import programs

BLUEPRINTS = (
    clock.bp,
    programs.bp,
    config.bp,
    periods.bp,
    partner_agreements.bp,
    point_lots.bp,
    redemption_events.bp,
    breakage_estimates.bp,
    settlement_statements.bp,
    change_orders.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_lock():
        db.lock.acquire()
        g._locked = True

    @app.teardown_request
    def _release_lock(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(404)
    def _not_found(_err):
        return error_body("ERR_INVALID_REQUEST", "Unknown resource path."), 404

    @app.errorhandler(405)
    def _bad_method(_err):
        return error_body("ERR_INVALID_REQUEST", "Method not allowed."), 405

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_body(err.error_id, err.message), err.http_status
        return error_body("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
