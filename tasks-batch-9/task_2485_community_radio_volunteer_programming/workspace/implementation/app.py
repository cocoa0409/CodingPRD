"""Community radio volunteer programming API.

Entry point: registers every route group, installs the error handlers, and
serves on 0.0.0.0:$PORT.  The in-memory store starts completely empty on every
boot — nothing is seeded, preloaded, or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from db import begin_request
from errors import ApiError
from routes import (
    development,
    episodes,
    operations,
    programs,
    proposals,
    schedule,
    underwriting,
    volunteers,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _begin():
        begin_request()

    operations.register(app)
    volunteers.register(app)
    proposals.register(app)
    programs.register(app)
    schedule.register(app)
    episodes.register(app)
    underwriting.register(app)
    development.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        error_id = "ERR_VALIDATION" if exc.code and exc.code < 500 else "ERR_INTERNAL"
        wrapped = ApiError("ERR_VALIDATION", exc.description)
        wrapped.error_id = error_id
        wrapped.http_status = exc.code or 500
        return response.error_response(wrapped)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover
        wrapped = ApiError("ERR_VALIDATION", "Unexpected server error: %s" % exc)
        wrapped.error_id = "ERR_INTERNAL"
        wrapped.http_status = 500
        return response.error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
