"""Retail Media Network Campaign Operations API.

A single Flask process holding all state in memory.  Every boot starts from a
completely empty store with the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, db, err_body
import routes_advertiser
import routes_auction
import routes_billing
import routes_budget
import routes_campaign
import routes_catalog
import routes_fund
import routes_inventory
import routes_measurement
import routes_ops

BLUEPRINTS = (
    routes_advertiser.bp,
    routes_budget.bp,
    routes_fund.bp,
    routes_campaign.bp,
    routes_inventory.bp,
    routes_catalog.bp,
    routes_auction.bp,
    routes_measurement.bp,
    routes_billing.bp,
    routes_ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    # fresh process == empty world (no seeding, ever)
    db.reset()
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        body = err_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(err_body("ERR_VALIDATION", "No such route.")), 404

    @app.errorhandler(405)
    def _bad_method(exc):
        return jsonify(err_body("ERR_VALIDATION",
                                "Method not allowed on this route.")), 405

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return jsonify(err_body("ERR_VALIDATION",
                                    "Malformed request.")), 422
        return jsonify(err_body("ERR_VALIDATION", exc.description)), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return jsonify(err_body("ERR_VALIDATION", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
