import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from response import error_body

import routes_core
import routes_catalog
import routes_rx
import routes_orders
import routes_ship
import routes_infra
import routes_wellness
import routes_insurance
import routes_autoship
import routes_recall
import routes_ops

app = Flask(__name__)

for mod in (routes_core, routes_catalog, routes_rx, routes_orders, routes_ship,
            routes_infra, routes_wellness, routes_insurance, routes_autoship,
            routes_recall, routes_ops):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e)), e.status


@app.errorhandler(404)
def handle_404(e):
    err = ApiError("ERR_NOT_FOUND", "resource not found", 404)
    return jsonify(error_body(err)), 404


@app.errorhandler(405)
def handle_405(e):
    err = ApiError("ERR_NOT_FOUND", "resource not found", 404)
    return jsonify(error_body(err)), 404


@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    err = ApiError("ERR_INVALID_REQUEST", "internal error: {}".format(e), 500)
    return jsonify(error_body(err)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
