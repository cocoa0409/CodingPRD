"""Juice Bottling Plant API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from util import error_response, _meta

app = Flask(__name__)

import routes_clock
import routes_customers
import routes_formulas
import routes_tanks
import routes_batches
import routes_process
import routes_containers
import routes_lines
import routes_runs
import routes_inventory
import routes_orders
import routes_pallets
import routes_ops

for module in (routes_clock, routes_customers, routes_formulas, routes_tanks,
               routes_batches, routes_process, routes_containers, routes_lines,
               routes_runs, routes_inventory, routes_orders, routes_pallets,
               routes_ops):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_not_found(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_method_not_allowed(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"}}
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
