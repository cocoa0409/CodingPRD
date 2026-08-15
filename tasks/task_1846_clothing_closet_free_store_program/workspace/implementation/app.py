"""Clothing Closet & Free Store Program API — Flask entry point.

Mounts all route groups under /closet, renders the standard response
envelope for errors, and listens on 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask, g

import db
from errors import ApiError
from response import error_response
from routes import (
    clients, clock, donations, drives, items, lines, partners, recycling,
    reports, rotations, shifts, visits, volunteers, vouchers, zones,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _acquire_lock():
        db.lock.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc=None):
        if g.get("_lock_held"):
            g._lock_held = False
            db.lock.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def _internal(err):
        return error_response("ERR_INTERNAL", 500, str(err))

    for module in (
        clock, clients, visits, lines, donations, items, zones, rotations,
        volunteers, shifts, partners, vouchers, drives, recycling, reports,
    ):
        app.register_blueprint(module.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
