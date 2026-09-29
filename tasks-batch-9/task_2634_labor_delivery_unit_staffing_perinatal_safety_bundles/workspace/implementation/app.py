"""Perinatal safety operations API (PRD task 2634).

Flask application factory and blueprint registration. Storage is in-memory
only: `store.S` starts empty on every boot and nothing is ever seeded, so a
fresh process is always a fresh, empty system.
"""

import os

from flask import Flask, jsonify

import envelope
from errors import ApiError

BLUEPRINTS = (
    "bp_clock", "bp_units", "bp_staff", "bp_shifts", "bp_beds", "bp_encounters",
    "bp_care", "bp_bookings", "bp_sweep", "bp_bundles", "bp_fetal",
    "bp_cesarean", "bp_drills", "bp_reviews", "bp_passes", "bp_snapshots",
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for name in BLUEPRINTS:
        module = __import__(name)
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND",
                             "No resource is mounted at this path.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return envelope.error("ERR_METHOD_NOT_ALLOWED",
                              "That method is not allowed for this path.", 405)

    @app.errorhandler(500)
    def _server_error(exc):  # pragma: no cover - defensive only
        return envelope.error("ERR_INTERNAL", str(exc), 500)

    @app.get("/_health")
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
