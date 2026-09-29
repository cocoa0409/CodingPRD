"""Affiliate Homeownership Program & Sweat Equity Service.

Flask entrypoint. State lives in process memory only (see store.py) and is
therefore empty on every boot; nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import r_assignment
import r_clock
import r_education
import r_grant
import r_household
import r_mortgage
import r_program
import r_review
import r_shift
import r_site
import r_sweat


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (r_program, r_household, r_review, r_sweat, r_site, r_shift,
                   r_assignment, r_education, r_mortgage, r_grant, r_clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(error):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_not_allowed(error):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        if error.code == 404:
            return handle_not_found(error)
        if error.code == 405:
            return handle_not_allowed(error)
        if error.code in (400, 415):
            return error_response("ERR_VALIDATION",
                                  "The request body could not be parsed.", 422)
        return error_response("ERR_INTERNAL", error.description or "Request failed.",
                              error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return error_response("ERR_INTERNAL", "%s" % (error,), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
