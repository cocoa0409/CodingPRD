"""Deposit Insurance Resolution API -- application entry point.

Storage is in-memory and starts completely empty on every process start: nothing
is seeded, preloaded or hardcoded here.  Every institution, depositor, account,
determination, certificate, bidder, bid, branch reopening and dividend round is
built by a client call to one of the endpoints declared in PRD section 4.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ERROR_MESSAGES, ApiError
from routes import (
    accounts,
    bidders,
    bids,
    certificates,
    clock,
    depositors,
    determinations,
    dividends,
    institutions,
    readiness,
    reopenings,
)

HTTP_STATUS_TO_ERROR_ID = {
    401: "ERR_UNAUTHENTICATED",
    403: "ERR_UNAUTHORIZED",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        clock,
        institutions,
        readiness,
        depositors,
        accounts,
        determinations,
        certificates,
        bidders,
        bids,
        reopenings,
        dividends,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(
            error.error_id, error.message, error.http_status
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        status = error.code or 500
        error_id = HTTP_STATUS_TO_ERROR_ID.get(status, "ERR_INVALID_REQUEST")
        message = ERROR_MESSAGES.get(error_id, error.description or "Request failed")
        return response.error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        use_reloader=False,
        threaded=True,
    )
