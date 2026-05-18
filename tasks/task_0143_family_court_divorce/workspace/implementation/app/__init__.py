"""Flask application factory for the Family Court Divorce API."""
from datetime import datetime, timezone

from flask import Flask, jsonify

from app import store
from app.errors import ApiError, register_error_handlers
from app.routes import register_routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    register_error_handlers(app)
    register_routes(app)

    @app.route("/__test__/reset", methods=["POST"])
    def __test_reset():
        # Clear all in-memory tables and reset the logical clock.
        store.cases.clear()
        store.parties.clear()
        store.disclosures.clear()
        store.parenting_plans.clear()
        store.mediation_sessions.clear()
        store.support_orders.clear()
        store.temp_orders.clear()
        store.final_judgments.clear()
        store.clock._now = datetime.now(timezone.utc).replace(microsecond=0)
        store._docket_seq = 0
        return jsonify({"ok": True}), 200

    return app
