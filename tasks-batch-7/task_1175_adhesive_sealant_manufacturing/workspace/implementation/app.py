"""Adhesive & Sealant Manufacturing API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from helpers import error_response

app = Flask(__name__)

from routes_core import bp as core_bp
from routes_production import bp as production_bp
from routes_quality import bp as quality_bp
from routes_requests import bp as requests_bp
from routes_commercial import bp as commercial_bp
from routes_shipments import bp as shipments_bp

for bp in (core_bp, production_bp, quality_bp, requests_bp, commercial_bp, shipments_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Method not allowed", 405))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Internal server error", 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
