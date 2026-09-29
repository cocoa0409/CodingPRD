"""SALT Apportionment Filing API - entry point."""
import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from web import error_response

import routes_core
import routes_reg
import routes_filing
import routes_money
import routes_notice
import routes_vda


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_reg.bp)
    app.register_blueprint(routes_filing.bp)
    app.register_blueprint(routes_money.bp)
    app.register_blueprint(routes_notice.bp)
    app.register_blueprint(routes_vda.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        status = err.code or 400
        return error_response(ApiError("ERR_INVALID_REQUEST", err.description, status))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc(file=sys.stderr)
        return error_response(ApiError("ERR_INVALID_REQUEST", "The request could not be processed."))

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
