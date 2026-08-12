"""Propane Cylinder Exchange API — Flask entry point.

State is fully in-memory (module-level dicts in db.py); every fresh process
boot starts with an empty store and the logical clock at 2026-05-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response

app = Flask(__name__)

from routes.admin import bp as admin_bp
from routes.cylinders import bp as cylinders_bp
from routes.sales import bp as sales_bp
from routes.compliance import bp as compliance_bp
from routes.logistics import bp as logistics_bp
from routes.finance import bp as finance_bp

app.register_blueprint(admin_bp)
app.register_blueprint(cylinders_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(compliance_bp)
app.register_blueprint(logistics_bp)
app.register_blueprint(finance_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    app.logger.exception("unexpected error")
    return error_response(ERR_VALIDATION, 400, "Malformed request")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
