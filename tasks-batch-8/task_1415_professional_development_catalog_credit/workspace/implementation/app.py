"""PD Catalog & Credit API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). The
harness re-launches this process before every test.
"""
import os

from flask import Flask, jsonify

from envelope import error_response, _meta_base
from errors import ApiError
from routes.admin import bp as admin_bp
from routes.buildings import bp as buildings_bp
from routes.employees import bp as employees_bp
from routes.courses import bp as courses_bp
from routes.sections import bp as sections_bp
from routes.registrations import bp as registrations_bp
from routes.workshops import bp as workshops_bp
from routes.plans import bp as plans_bp
from routes.compliance import bp as compliance_bp
from routes.audit import bp as audit_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (admin_bp, buildings_bp, employees_bp, courses_bp, sections_bp,
           registrations_bp, workshops_bp, plans_bp, compliance_bp, audit_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND",
                 "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND",
                 "message": "method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST",
                 "message": "unexpected error: %s" % type(e).__name__},
    }
    return jsonify(body), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
