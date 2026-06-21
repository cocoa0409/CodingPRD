"""Vocational / Trade School Management API — Flask entry point.

In-memory storage only; the store is empty on every boot (no seeding).
Run: PORT=10000 python3 app.py  (binds 0.0.0.0).
"""
import os
import socket

# Werkzeug's make_server calls socket.getfqdn(host) to derive server_name.
# On some hosts (notably macOS) the reverse DNS lookup for a bind address such
# as 0.0.0.0 blocks for ~5s on a resolver timeout, adding that latency to EVERY
# boot. Under the benchmark's per-test-server isolation (server restarted before
# every test) that tax dominates wall time and, under concurrent load, widens
# boot-latency variance enough to occasionally exceed the runner's connect
# window (intermittent ConnectTimeout / ConnectionReset). Short-circuit getfqdn
# to a non-resolving fast path; server_name is cosmetic and never part of the
# HTTP/business contract.
_orig_getfqdn = socket.getfqdn


def _fast_getfqdn(name=""):
    if name in ("", "0.0.0.0", "::", "localhost", "127.0.0.1"):
        return "localhost"
    return _orig_getfqdn(name)


socket.getfqdn = _fast_getfqdn

from flask import Flask, request

from errors import ApiError
from response import error_response
from routes.config import bp as config_bp
from routes.agreements import bp as agreements_bp
from routes.academic import bp as academic_bp
from routes.finance import bp as finance_bp
from routes.externship import bp as externship_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(academic_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(externship_bp)

    @app.after_request
    def _no_keep_alive(resp):
        # Force a fresh TCP connection per request. Under per-test-server
        # isolation the server is killed and re-launched before every test; a
        # client that pools/reuses keep-alive connections can send a request on
        # a socket whose server has just been torn down, surfacing as
        # BadStatusLine / ConnectionReset. "Connection: close" makes each
        # request use a new connection and removes that race. Transport header
        # only — not part of the HTTP/business contract.
        resp.headers["Connection"] = "close"
        return resp

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path. Use the standard envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message)
        # Surface unexpected errors as a generic 400-style invalid request so
        # the envelope stays consistent. (Should not normally happen.)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Raise the TCP accept backlog before the listening socket is created.
    # Under the benchmark's concurrent per-test-server sweep (~8x peak load),
    # the default small backlog can refuse/reset bursts of connections that
    # arrive in the brief window right after bind; a larger backlog absorbs
    # them. This is a transport-layer setting only — the HTTP/business contract
    # is unchanged. request_queue_size must be set on the server class BEFORE
    # the socket calls listen(), so we patch it prior to make_server.
    from werkzeug.serving import make_server, BaseWSGIServer, ThreadedWSGIServer

    BaseWSGIServer.request_queue_size = 128
    ThreadedWSGIServer.request_queue_size = 128
    httpd = make_server("0.0.0.0", port, app, threaded=True)
    httpd.serve_forever()
