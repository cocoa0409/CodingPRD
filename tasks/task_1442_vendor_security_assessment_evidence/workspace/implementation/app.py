"""Vendor Security Assessment API — Flask entry point.

In-memory only: every store lives in module-level dicts in db.py, so a fresh
process boot (start.sh re-invocation) wipes all state. The logical clock
starts at 2026-08-01T00:00:00Z and moves only via POST
/vsa/_clock/set_current_utc. Nothing is seeded at startup.
"""
import os

from flask import Flask, jsonify

import errors
from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    from routes import (acceptances, addenda, admin, attestations, cycles,
                        evidence, exceptions, monitoring, plans, responses,
                        templates, vendors)

    app.register_blueprint(admin.bp)
    app.register_blueprint(templates.bp)
    app.register_blueprint(vendors.bp)
    app.register_blueprint(cycles.bp)
    app.register_blueprint(responses.bp)
    app.register_blueprint(evidence.bp)
    app.register_blueprint(exceptions.bp)
    app.register_blueprint(plans.bp)
    app.register_blueprint(acceptances.bp)
    app.register_blueprint(addenda.bp)
    app.register_blueprint(monitoring.bp)
    app.register_blueprint(attestations.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(error_body(errors.ERR_NOT_FOUND,
                                  "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(error_body(errors.ERR_NOT_FOUND,
                                  "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                  "Unexpected error: %s" % exc)), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
