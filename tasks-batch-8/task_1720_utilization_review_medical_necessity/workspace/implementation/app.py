"""Utilization Review & Medical Necessity API — Flask entry point."""
import os
from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION_FAILED
from response import error_response

app = Flask(__name__)

from routes.payers import bp as payers_bp
from routes.physicians import bp as physicians_bp
from routes.cases import bp as cases_bp
from routes.admission_reviews import bp as admission_reviews_bp
from routes.authorization_requests import bp as authorization_requests_bp
from routes.concurrent_reviews import bp as concurrent_reviews_bp
from routes.p2p import bp as p2p_bp
from routes.cc44 import bp as cc44_bp
from routes.avoidable_days import bp as avoidable_days_bp
from routes.escalations import bp as escalations_bp
from routes.denials import bp as denials_bp
from routes.appeals import bp as appeals_bp
from routes.audit import bp as audit_bp
from routes.clock import bp as clock_bp

for bp in (
    payers_bp, physicians_bp, cases_bp, admission_reviews_bp,
    authorization_requests_bp, concurrent_reviews_bp, p2p_bp, cc44_bp,
    avoidable_days_bp, escalations_bp, denials_bp, appeals_bp, audit_bp,
    clock_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_VALIDATION_FAILED, "Malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_INTERNAL", str(err), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
