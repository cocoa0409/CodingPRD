"""Government Cloud Authorization Program API — Flask application entry point.

Storage is entirely in-memory (see core.Store); nothing is read from or written to
disk and no entity data is ever seeded at startup.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_assessment
import routes_authorization
import routes_program
from core import ApiError, error_body

app = Flask(__name__)
app.json.sort_keys = False
app.url_map.strict_slashes = False

app.register_blueprint(routes_program.bp)
app.register_blueprint(routes_assessment.bp)
app.register_blueprint(routes_authorization.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err)), err.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    if err.code == 404:
        wrapped = ApiError("ERR_INVALID_REQUEST", "The requested resource does not exist.", 404)
    elif err.code == 405:
        wrapped = ApiError("ERR_INVALID_REQUEST", "The method is not allowed on this path.", 405)
    elif err.code in (400, 415):
        wrapped = ApiError("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
    else:
        wrapped = ApiError("ERR_INVALID_REQUEST", err.description or "Request failed.", err.code)
    return jsonify(error_body(wrapped)), wrapped.http_status


@app.errorhandler(Exception)
def handle_unexpected(err):  # pragma: no cover - defensive
    wrapped = ApiError("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 500)
    return jsonify(error_body(wrapped)), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
