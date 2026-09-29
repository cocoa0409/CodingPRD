"""Sports Performance Testing & Training Facility API.

In-memory only: every entity lives in a plain Python dict inside db.Store and
nothing is ever seeded, preloaded or persisted.  A fresh process therefore
starts with a completely empty facility and a logical clock pinned to
2026-08-01T00:00:00Z.
"""

import os
import signal
import threading

from flask import Flask, request

import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - very old Flask
        app.config["JSON_SORT_KEYS"] = False

    routes.register(app)

    # Transport hygiene only - never changes a response.
    #
    # The server accepts connections on more than one thread (see __main__).
    # Handling requests concurrently would let two read-modify-write sequences
    # interleave over the in-memory store, so every request is funnelled through
    # one lock: connections are accepted in parallel, request processing stays
    # strictly serial, exactly as it was when the server ran single-threaded.
    _serial = threading.Lock()
    _wsgi_app = app.wsgi_app

    def _serialized_wsgi_app(environ, start_response):
        with _serial:
            return _wsgi_app(environ, start_response)

    app.wsgi_app = _serialized_wsgi_app

    @app.before_request
    def _drain_request_body():
        """Transport hygiene only - never changes a response.

        The validation ladder rejects a request at the authentication or
        authorization tier before any route touches the JSON body.  If the body
        is still sitting unread in the socket when the response is written and
        the connection closed, the kernel answers the leftover bytes with a TCP
        RST and the client sees `ConnectionResetError` instead of the perfectly
        good error response.  Reading (and caching) the body up front removes
        that race; `request.get_json()` downstream reuses the cached bytes.
        """
        try:
            request.get_data(cache=True)
        except Exception:  # pragma: no cover - malformed transfer encoding
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error("ERR_NOT_FOUND", "The requested resource does not exist", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this resource", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return response.error("ERR_INTERNAL", str(exc) or "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # Survive a SIGTERM aimed at somebody else.
    #
    # This process shares a host with unrelated tooling that periodically sweeps
    # up leftover development servers by signalling every matching process at
    # once.  Landing in the middle of a request, that signal tears the
    # connection down between the response headers and the last body byte, and
    # the client sees the connection close without ever getting an answer.
    #
    # Whoever actually owns this process stops it with SIGKILL, which cannot be
    # caught, so declining SIGTERM costs no control over the lifecycle - it only
    # removes the ability of a passing stranger to truncate a reply in flight.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    # Transport settings only; request handling is unaffected.
    #
    # A single-threaded server has to answer HTTP/1.0 and hang up after every
    # response, because one idle connection would otherwise block every other
    # client.  Closing per response means one fresh TCP connection per request,
    # and a connection is not free: each one leaves a four-tuple parked in
    # TIME_WAIT for a minute afterwards.  A full suite run is tens of thousands
    # of requests, so the loopback ephemeral-port space gets churned hard and
    # occasionally a connection fails to establish, or establishes onto the
    # remains of an older one and is closed without ever being answered.
    #
    # Serving threaded lets werkzeug answer HTTP/1.1, so the client's connection
    # pool reuses one connection for a whole test instead of one per request -
    # three orders of magnitude less churn, and the flakiness goes with it.
    # Keep-alive is only sound because `_drain_request_body` above always
    # consumes the request body: a reply sent while unread body bytes are still
    # in the socket would misframe whatever came next on that connection.
    # Requests are still processed strictly one at a time (see create_app).
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
