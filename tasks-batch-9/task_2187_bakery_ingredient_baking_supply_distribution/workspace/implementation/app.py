"""Dawn Mills bakery ingredient & baking supply distribution service.

Flask application factory. All state lives in process memory (see store.py);
nothing is persisted and nothing is seeded, so relaunching this process wipes
every byte of state.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import api_catalog
import api_contracts
import api_inventory
import api_orders
import api_routes
import api_substitutions
import api_tech
import envelope
import store
from errors import ApiError

API_PREFIX = "/bakery-distribution"

BLUEPRINTS = (
    api_catalog.bp,
    api_contracts.bp,
    api_inventory.bp,
    api_orders.bp,
    api_substitutions.bp,
    api_routes.bp,
    api_tech.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    store.reset()

    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "No such resource", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return envelope.error("ERR_VALIDATION", "Method not allowed on this path", 405)

    @app.errorhandler(400)
    def _bad_request(exc):
        return envelope.error("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return envelope.error("ERR_VALIDATION", exc.description or "Request failed",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return jsonify({
            "meta": {"api_request_id": envelope._request_id(),
                     "api_request_timestamp": store.wall_now_iso()},
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "%s" % exc},
        }), 400

    @app.get("/healthz")
    def _healthz():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
