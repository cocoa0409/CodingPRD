"""Furniture Bank Distribution API.

Entry point: registers every route blueprint, renders the error envelope and
serves on 0.0.0.0:$PORT. All state lives in process memory and starts empty on
every boot - nothing is ever seeded here.
"""

import os
import sys

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.ops import bp as ops_bp
    from routes.directory import bp as directory_bp
    from routes.clients import bp as clients_bp
    from routes.referrals import bp as referrals_bp
    from routes.vouchers import bp as vouchers_bp
    from routes.donations import bp as donations_bp
    from routes.runs import bp as runs_bp
    from routes.waitlist import bp as waitlist_bp

    for blueprint in (ops_bp, directory_bp, clients_bp, referrals_bp,
                      vouchers_bp, donations_bp, runs_bp, waitlist_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_touch_ledger():
        g._touched_entities = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _handle_not_found(_error):
        return error_response("ERR_VALIDATION", "No such route.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(_error):
        return error_response("ERR_VALIDATION", "Method not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        if isinstance(error, HTTPException):
            return error_response("ERR_VALIDATION", error.description, error.code)
        app.logger.exception("unhandled error")
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
