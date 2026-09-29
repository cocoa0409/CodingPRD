"""Subscription Retention & Cancellation Management API.

Flask application factory.  All state lives in process memory (see db.py) and
starts empty on every boot: nothing is seeded or persisted to disk.
"""
import os

from flask import Flask, g, jsonify

from db import store
from errors import ApiError
from response import error_body
from routes import analytics, billing, cancellation, catalog, people, subscriptions, winback

BLUEPRINTS = (catalog.bp, people.bp, subscriptions.bp, billing.bp,
              cancellation.bp, winback.bp, analytics.bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_transaction():
        g.snapshot = store.begin()

    def _rollback():
        store.rollback(getattr(g, "snapshot", None))

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        _rollback()
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _handle_404(exc):
        _rollback()
        return jsonify(error_body("ERR_NOT_FOUND", "The requested route does not exist.")), 404

    @app.errorhandler(405)
    def _handle_405(exc):
        _rollback()
        return jsonify(error_body(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.")), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        _rollback()
        return jsonify(error_body("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
