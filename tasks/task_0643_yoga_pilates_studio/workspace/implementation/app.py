"""Yoga & Pilates Studio API — Flask entry point.

Registers all route blueprints and the global error handlers. State lives in the
in-memory Store (db.py), constructed fresh on every process boot — nothing is
seeded. start.sh re-launches this process before every per-test run.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error as error_response
from db import store

from routes.members import bp as members_bp
from routes.rooms import bp as rooms_bp
from routes.teachers import bp as teachers_bp
from routes.intro_offers import bp as intro_offers_bp
from routes.class_sessions import bp as class_sessions_bp
from routes.entitlements import bp as entitlements_bp
from routes.reservations import bp as reservations_bp
from routes.workshops import bp as workshops_bp
from routes.enrollments import bp as enrollments_bp
from routes.fee_charges import bp as fee_charges_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (members_bp, rooms_bp, teachers_bp, intro_offers_bp,
               class_sessions_bp, entitlements_bp, reservations_bp,
               workshops_bp, enrollments_bp, fee_charges_bp, ops_bp):
        app.register_blueprint(bp)

    # Serialize requests so cascading multi-record mutations stay consistent
    # under the test harness's concurrent probing.
    _lock = store.lock

    @app.before_request
    def _acquire_lock():
        _lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        try:
            _lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 422, f"Unexpected error: {e}")

    return app


app = create_app()


def _bind_listen_socket(host, port, retries=200, delay=0.05):
    """Bind a listening socket with SO_REUSEADDR + SO_REUSEPORT, retrying briefly.

    The benchmark harness restarts this server before EVERY test across 8
    concurrent rounds: it SIGKILLs the prior process and immediately re-spawns
    this one on the same port. Two races follow from that and both produce the
    intermittent "Connection reset by peer" / "could not be restarted" failures
    seen in the sweep:

      * the freshly-killed process's listening socket may linger in the kernel
        for a few milliseconds, so a naive bind() races with its teardown;
      * a connection that the harness opens the instant we start listening can
        be reset if the accept loop is not up yet.

    Binding the socket ourselves with SO_REUSEADDR|SO_REUSEPORT lets the new
    process claim the port immediately even while the old socket drains, and a
    short bounded retry loop closes the remaining window deterministically. The
    bound, listening socket is then handed to waitress so the accept loop is
    live the moment we begin serving.
    """
    import socket
    import time
    last_err = None
    for _ in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass  # SO_REUSEPORT unavailable on this platform; SO_REUSEADDR suffices
        try:
            sock.bind((host, port))
            sock.listen(2048)
            sock.setblocking(False)
            return sock
        except OSError as e:
            last_err = e
            sock.close()
            time.sleep(delay)
    raise last_err if last_err else OSError("could not bind listen socket")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    host = "0.0.0.0"
    # Prefer a production-grade WSGI server (waitress) over the Werkzeug dev
    # server. Under the benchmark harness the server is restarted before every
    # test across 8 concurrent rounds, so the listen socket faces connection
    # bursts immediately on boot. Werkzeug's dev server has a tiny listen
    # backlog (request_queue_size == 5) and resets connections beyond it,
    # surfacing as flaky "Connection reset by peer" / "RemoteDisconnected"
    # failures. waitress accepts a deep backlog and is robust under that burst.
    try:
        from waitress import serve
        listen_sock = _bind_listen_socket(host, port)
        serve(app, sockets=[listen_sock], threads=8,
              connection_limit=1000, _quiet=True)
    except Exception:
        # Fall back to the Werkzeug dev server with an enlarged listen backlog.
        try:
            import werkzeug.serving as _ws
            _ws.BaseWSGIServer.request_queue_size = 128
        except Exception:
            pass
        app.run(host=host, port=port, threaded=True)
