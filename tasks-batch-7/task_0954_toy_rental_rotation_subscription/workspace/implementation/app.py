"""Toy Rental & Rotation Subscription API.

State lives in Python dictionaries and dies with the process: no database
file, no JSON dump, no cache directory, no pickle.  Nothing is seeded at
startup.  The logical clock defaults to exactly 2026-05-01T00:00:00Z and is
repositioned only through POST /toy-rental/_clock/set_current_utc.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_boxes
import routes_catalog
import routes_fees
import routes_items
import routes_members
import routes_ops
import routes_plans
import routes_shipments
import routes_subscriptions
import routes_wishlist
from envelope import error_body, error_response
from errors import ApiError
from store import LOCK


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_members.bp)
    app.register_blueprint(routes_plans.bp)
    app.register_blueprint(routes_subscriptions.bp)
    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_wishlist.bp)
    app.register_blueprint(routes_boxes.bp)
    app.register_blueprint(routes_items.bp)
    app.register_blueprint(routes_shipments.bp)
    app.register_blueprint(routes_fees.bp)
    app.register_blueprint(routes_ops.bp)

    @app.before_request
    def _serialize_requests():
        # In-memory store is not concurrency-safe on its own; serialize.
        LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        LOCK.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return _plain_error("ERR_VALIDATION", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return _plain_error("ERR_VALIDATION", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        return _plain_error("ERR_VALIDATION", err.name, err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return _plain_error("ERR_VALIDATION", "Internal error: %s" % err, 500)

    return app


def _plain_error(error_id, message, status):
    from flask import jsonify
    resp = jsonify(error_body(error_id, message))
    resp.status_code = status
    return resp


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
