"""Acupuncture & TCM Clinic API — entry point, error handling, route registration.

In-memory only. The store starts EMPTY on every boot; no entities are seeded.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.appointments import bp as appointments_bp
from routes.catalog import bp as catalog_bp
from routes.clock import bp as clock_bp
from routes.dispenses import bp as dispenses_bp
from routes.intakes import bp as intakes_bp
from routes.package_series import bp as package_series_bp
from routes.patients import bp as patients_bp
from routes.treatment_plans import bp as treatment_plans_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(clock_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(patients_bp)
app.register_blueprint(intakes_bp)
app.register_blueprint(treatment_plans_bp)
app.register_blueprint(package_series_bp)
app.register_blueprint(appointments_bp)
app.register_blueprint(dispenses_bp)


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
    body = error_response("ERR_INTERNAL", str(e))
    resp = jsonify(body)
    resp.status_code = 500
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
