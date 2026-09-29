"""Beverage Container Deposit Redemption Center API.

Storage is entirely in-memory (plain Python dicts in db.py). Nothing is seeded,
preloaded or persisted: a fresh process always starts with an empty graph.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

routes.register(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return response.error("ERR_NOT_FOUND", "No such route.", 404)
    if exc.code == 405:
        return response.error("ERR_METHOD_NOT_ALLOWED",
                             "That method is not allowed on this route.", 405)
    if exc.code == 400:
        return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
    return response.error("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                          exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unhandled error")
    return response.error("ERR_INTERNAL", "Unexpected server error.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
