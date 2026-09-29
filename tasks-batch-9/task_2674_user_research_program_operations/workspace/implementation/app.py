"""User Research Program Operations API.

Entry point: builds the Flask app, registers the route modules and the error
handlers, and serves on 0.0.0.0:$PORT. Nothing is seeded here - the in-memory
store starts empty on every boot and tests build all state through the API.
"""
import os

from flask import Flask

import routes_consent
import routes_decisions
import routes_ops
import routes_pools
import routes_readouts
import routes_recruitments
import routes_repository
import routes_studies
from envelope import error_response
from errors import ApiError
from store import db


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        routes_ops,
        routes_decisions,
        routes_pools,
        routes_studies,
        routes_recruitments,
        routes_consent,
        routes_repository,
        routes_readouts,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _begin():
        db.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        app.logger.exception("Unhandled error")
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
