"""Therapy Animal Visits API — entry point.

All state is in-memory (db.store). The logical clock starts fixed at
2026-08-01T00:00:00Z and is advanced only via POST /v1/_clock/set_current_utc.
"""
import os
import sys

# Ensure sibling modules import cleanly regardless of invocation directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify

from errors import ApiError
from response import error_response, success_object
from routes import (
    admin, handlers, animals, vaccinations, teams, evaluators, evaluations,
    certifications, facilities, agreements, orientations, policies, waivers,
    requests, visits, incidents, credits,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (admin, handlers, animals, vaccinations, teams, evaluators,
                   evaluations, certifications, facilities, agreements,
                   orientations, policies, waivers, requests, visits, incidents,
                   credits):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(500)
    def handle_500(exc):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
