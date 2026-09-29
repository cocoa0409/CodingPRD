"""Home improvement point-of-sale financing program API.

Entry point: registers the route blueprints and the envelope-shaped error
handlers. Storage is in-memory only and starts completely empty on every boot —
no entity is seeded, preloaded or hardcoded here or in any imported module.
"""
import os

from flask import Flask

import routes_credit
import routes_program
import routes_project
from errors import ApiError
from response import error

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_program.bp)
app.register_blueprint(routes_credit.bp)
app.register_blueprint(routes_project.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(400)
def handle_bad_request(exc):
    return error("ERR_INVALID_REQUEST", "The request body could not be parsed.", 400)


@app.errorhandler(404)
def handle_not_found(exc):
    return error("ERR_NOT_FOUND", "No such route.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error("ERR_METHOD_NOT_ALLOWED",
                 "That method is not allowed on this route.", 405)


@app.errorhandler(415)
def handle_unsupported_media(exc):
    return error("ERR_INVALID_REQUEST",
                 "The request body must be JSON.", 400)


@app.errorhandler(500)
def handle_server_error(exc):
    return error("ERR_INTERNAL", "The server failed to complete the request.", 500)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    status = getattr(exc, "code", None)
    if status == 404:
        return handle_not_found(exc)
    if status == 405:
        return handle_method_not_allowed(exc)
    if status == 400:
        return handle_bad_request(exc)
    if status == 415:
        return handle_unsupported_media(exc)
    if isinstance(status, int) and 400 <= status < 600:
        return error("ERR_INTERNAL", str(exc), status)
    return error("ERR_INTERNAL", "The server failed to complete the request.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
