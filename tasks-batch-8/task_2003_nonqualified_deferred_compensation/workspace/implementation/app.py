"""Flask application entry point: error handlers and route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response, ok_object

app = Flask(__name__)

from routes.plans import bp as plans_bp
from routes.election_windows import bp as windows_bp
from routes.participants import bp as participants_bp
from routes.notional_funds import bp as funds_bp
from routes.deferral_elections import bp as elections_bp
from routes.accounts import bp as accounts_bp
from routes.crediting_runs import bp as crediting_bp
from routes.rabbi_trusts import bp as trusts_bp
from routes.separation_cases import bp as cases_bp
from routes.specified_lists import bp as lists_bp
from routes.distribution_requests import bp as distributions_bp
from routes.cic import bp as cic_bp
from routes.operational_failures import bp as failures_bp
from routes.document_findings import bp as findings_bp
from routes.clock import bp as clock_bp

for bp in (
    plans_bp,
    windows_bp,
    participants_bp,
    funds_bp,
    elections_bp,
    accounts_bp,
    crediting_bp,
    trusts_bp,
    cases_bp,
    lists_bp,
    distributions_bp,
    cic_bp,
    failures_bp,
    findings_bp,
    clock_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
