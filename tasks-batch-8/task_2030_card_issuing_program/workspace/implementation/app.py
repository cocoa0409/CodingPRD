"""Card Issuing Program API — Flask entry point."""
import os

from flask import Flask

from core import ApiError, error_response, apply_lazy

app = Flask(__name__)

import routes_programs
import routes_vendors_batches
import routes_accounts_cards
import routes_rules_settlements
import routes_mandates
import routes_campaigns_jobs

for module in (routes_programs, routes_vendors_batches, routes_accounts_cards,
               routes_rules_settlements, routes_mandates, routes_campaigns_jobs):
    app.register_blueprint(module.bp)


@app.before_request
def _lazy_sweep():
    apply_lazy()


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def _method_not_allowed(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def _unhandled(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
