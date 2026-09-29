"""Certificate Authority Operations API (Flask entry point)."""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (audits, authorizations, certificates, clock, incidents, partitions,
                    profiles, requests as request_routes, revocations, subscribers)

app = Flask(__name__)
app.url_map.strict_slashes = False

_lock = threading.RLock()


@app.before_request
def _serialize_requests():
    _lock.acquire()


@app.teardown_request
def _release_requests(_exc=None):
    try:
        _lock.release()
    except RuntimeError:
        pass


for blueprint in (
    profiles.bp,
    subscribers.bp,
    authorizations.bp,
    request_routes.bp,
    certificates.bp,
    partitions.bp,
    revocations.bp,
    incidents.bp,
    audits.bp,
    clock.bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    return error_response(
        "ERR_INVALID_REQUEST",
        exc.description or "Request could not be handled.",
        exc.code or 400,
    )


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
