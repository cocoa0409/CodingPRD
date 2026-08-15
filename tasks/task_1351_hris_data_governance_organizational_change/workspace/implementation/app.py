"""HRIS Data Governance API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from util import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

import routes_dict
import routes_org
import routes_changes
import routes_batches
import routes_ops
import routes_admin

for module in (routes_dict, routes_org, routes_changes, routes_batches,
               routes_ops, routes_admin):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Route not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
