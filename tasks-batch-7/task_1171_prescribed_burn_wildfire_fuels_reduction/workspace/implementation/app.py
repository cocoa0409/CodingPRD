"""Prescribed Burn Program API — Flask entry point."""
import os

from flask import Flask, jsonify

from core import ApiError, err_body

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_exec
import routes_money
import routes_orders
import routes_permits
import routes_plans
import routes_registry
import routes_safety

for module in (
    routes_registry,
    routes_plans,
    routes_permits,
    routes_safety,
    routes_orders,
    routes_exec,
    routes_money,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, code = err_body(exc.error_id, exc.message), exc.status
    return jsonify(body), code


@app.errorhandler(404)
def handle_404(_):
    return jsonify(err_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(_):
    return jsonify(err_body("ERR_NOT_FOUND", "Method not allowed")), 405


@app.errorhandler(500)
def handle_500(exc):
    return jsonify(err_body("ERR_INTERNAL", "Internal server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
