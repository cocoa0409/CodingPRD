"""Rendering & Byproduct Processing API — Flask entry point."""
import os

from flask import Flask, jsonify

from common import ApiError, error_body
import routes_plants
import routes_permits
import routes_supply
import routes_fleet
import routes_logistics
import routes_production
import routes_sales

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_plants, routes_permits, routes_supply, routes_fleet,
               routes_logistics, routes_production, routes_sales):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(e):
    return jsonify(error_body("ERR_INTERNAL", str(e))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
