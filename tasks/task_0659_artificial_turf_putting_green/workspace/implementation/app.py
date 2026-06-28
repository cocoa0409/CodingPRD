"""Turf Install API — entry point, error handling, route registration.

In-memory only. The store starts EMPTY on every boot; no entities are seeded.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.base_prep_scopes import bp as base_prep_scopes_bp
from routes.callbacks import bp as callbacks_bp
from routes.catalog import bp as catalog_bp
from routes.clock import bp as clock_bp
from routes.crews import bp as crews_bp
from routes.customers import bp as customers_bp
from routes.design_layouts import bp as design_layouts_bp
from routes.install_jobs import bp as install_jobs_bp
from routes.payments import bp as payments_bp
from routes.projects import bp as projects_bp
from routes.quotes import bp as quotes_bp
from routes.site_measures import bp as site_measures_bp
from routes.warranty_plans import bp as warranty_plans_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(clock_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(crews_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(site_measures_bp)
app.register_blueprint(design_layouts_bp)
app.register_blueprint(base_prep_scopes_bp)
app.register_blueprint(quotes_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(install_jobs_bp)
app.register_blueprint(warranty_plans_bp)
app.register_blueprint(callbacks_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = error_response(e.error_id, e.message)
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    body = error_response("ERR_NOT_FOUND", "Resource not found.")
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    body = error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")
    resp = jsonify(body)
    resp.status_code = 405
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = error_response("ERR_INTERNAL", "Internal server error.")
    resp = jsonify(body)
    resp.status_code = 500
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded=True so a single boot can service the runner's health-check and
    # the test request concurrently without a connection drop under the 8x
    # concurrent per-test-server sweep.
    app.run(host="0.0.0.0", port=port, threaded=True)
