"""Entry point: Flask app, route registration, envelope-aware error handlers."""
import os

from flask import Flask

from errors import APIError, ERR_NOT_FOUND
from response import error
from routes import (
    credit_unions, investments, agreements, offerings, commitments,
    exceptions, remittances, surveillance, exams, loss_events,
    repurchase_cases, ops,
)

app = Flask(__name__)

for bp in (
    credit_unions.bp,
    investments.bp,
    agreements.bp,
    offerings.bp,
    commitments.bp,
    exceptions.bp,
    remittances.bp,
    surveillance.bp,
    exams.bp,
    loss_events.bp,
    repurchase_cases.bp,
    ops.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(APIError)
def handle_api_error(e):
    return error(e)


@app.errorhandler(404)
def handle_404(e):
    return error(APIError(ERR_NOT_FOUND[0], 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error(APIError(ERR_NOT_FOUND[0], 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, APIError):
        return error(e)
    return error(APIError("ERR_INTERNAL", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
