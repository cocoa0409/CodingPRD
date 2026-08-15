"""CECL Allowance API — Flask entry point.

In-memory only: every process boot starts with a completely empty store.
"""

import os

from flask import Flask

from errors import ApiError
from response import api_error_response, error_response
from routes import adjustments, evaluations, factors, loss_models, model_runs, portfolio, reports

app = Flask(__name__)

app.register_blueprint(loss_models.bp)
app.register_blueprint(portfolio.bp)
app.register_blueprint(factors.bp)
app.register_blueprint(model_runs.bp)
app.register_blueprint(evaluations.bp)
app.register_blueprint(adjustments.bp)
app.register_blueprint(reports.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return api_error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return api_error_response(err)
    return error_response("ERR_INTERNAL", "Internal server error: %s" % err, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
