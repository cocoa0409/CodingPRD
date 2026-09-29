"""Industrial battery manufacturing API (PRD task 2592).

Flask entry point: blueprint registration, the response envelope error
handlers and the logical-clock reset that happens implicitly on every boot
(the store is constructed empty -- nothing is ever seeded).
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.assemblies import bp as assemblies_bp
from routes.chargers import bp as chargers_bp
from routes.clock import bp as clock_bp
from routes.designs import bp as designs_bp
from routes.facilities import bp as facilities_bp
from routes.lots import bp as lots_bp
from routes.plants import bp as plants_bp
from routes.runs import bp as runs_bp
from routes.tests import bp as tests_bp
from routes.units import bp as units_bp
from routes.workers import bp as workers_bp

BLUEPRINTS = (
    clock_bp,
    plants_bp,
    workers_bp,
    designs_bp,
    facilities_bp,
    lots_bp,
    assemblies_bp,
    runs_bp,
    tests_bp,
    chargers_bp,
    units_bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_touch_ledger():
        # One version bump per row per request (PRD 2.5): a row mutated by both
        # a write and a cascade in the same request advances `version` once.
        g._touched_rows = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_ROUTE_NOT_FOUND", "No such resource path", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path", 405
            )
        if exc.code in (400, 415):
            return error_response("ERR_VALIDATION", "Malformed request body", 422)
        return error_response(
            "ERR_INTERNAL", exc.description or "Request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error", 500)

    return app


app = create_app()


def _endpoint_count(flask_app):
    seen = set()
    for rule in flask_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for method in rule.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            seen.add((method, str(rule)))
    return len(seen)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print("registered endpoints: %d" % _endpoint_count(app), flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
