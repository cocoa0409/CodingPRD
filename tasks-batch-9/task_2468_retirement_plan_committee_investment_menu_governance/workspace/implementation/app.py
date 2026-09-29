"""Retirement Plan Committee & Investment Menu Governance API.

Flask application factory and process entrypoint. All state lives in memory in
`core.store`; a fresh process therefore starts with an entirely empty system and
no seeded rows of any kind.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response, meta_base

import bp_committee
import bp_fee
import bp_funds
import bp_meeting
import bp_menu
import bp_plan
import bp_replacement
import bp_review

BLUEPRINTS = (
    bp_plan.bp,
    bp_committee.bp,
    bp_menu.bp,
    bp_funds.bp,
    bp_meeting.bp,
    bp_review.bp,
    bp_replacement.bp,
    bp_fee.bp,
)


def _error(error_id, message, status):
    payload = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return _error("ERR_RESOURCE_NOT_FOUND", "the requested path does not exist",
                      404)

    @app.errorhandler(405)
    def _handle_405(err):
        return _error("ERR_INVALID_REQUEST", "method not allowed for this path",
                      405)

    @app.errorhandler(HTTPException)
    def _handle_http(err):
        if err.code == 404:
            return _handle_404(err)
        if err.code == 405:
            return _handle_405(err)
        if err.code and 400 <= err.code < 500:
            return _error("ERR_INVALID_REQUEST", err.description or "bad request",
                          err.code)
        return _error("ERR_INVALID_REQUEST", err.description or "error",
                      err.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return _error("ERR_INVALID_REQUEST", "unexpected error: %s" % err, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
