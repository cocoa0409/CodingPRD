"""Smart-Home Support Subscription API -- entry point.

G4 -- EADDRINUSE-TOLERANT BOOT.  Under ``--isolation per-test-server`` the
harness kill -9's the previous server and relaunches start.sh immediately.  If
the dying process still holds the LISTEN socket, Werkzeug turns the bind
failure into SystemExit before any ``try/except OSError`` around app.run()
could ever see it, and the innocent next test errors with "API server could
not be restarted".  The fix is to own the socket: bind it here with
SO_REUSEADDR inside a BOUNDED EADDRINUSE-tolerant retry loop (24 attempts x
0.25 s = 6 s ceiling, then a hard non-zero exit) and hand the file descriptor
to werkzeug.serving.make_server.  The window is deliberately short and the
failure deliberately hard: a long retry loop that outlives the harness's
readiness probe turns a rejected respawn into a PPID-1 orphan squatting the
port, which is strictly worse than failing fast.
"""

import errno
import os
import socket
import sys
import time

from flask import Flask, jsonify

from errors import ApiError, ERROR_HTTP
from envelope import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes.households import bp as households_bp
    from routes.billing import bp as billing_bp
    from routes.catalog import bp as catalog_bp
    from routes.devices import bp as devices_bp
    from routes.tickets import bp as tickets_bp
    from routes.sessions import bp as sessions_bp
    from routes.dispatch import bp as dispatch_bp
    from routes.firmware import bp as firmware_bp
    from routes.addons import bp as addons_bp
    from routes.rma import bp as rma_bp
    from routes.misc import bp as misc_bp

    for bp in (households_bp, billing_bp, catalog_bp, devices_bp, tickets_bp,
               sessions_bp, dispatch_bp, firmware_bp, addons_bp, rma_bp, misc_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 400

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 400

    @app.errorhandler(400)
    def _bad_request(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request.")), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        import traceback
        traceback.print_exc()
        return jsonify(error_body("ERR_INVALID_REQUEST", "Unhandled: %s" % exc)), 400

    return app


app = create_app()


def _bind(host, port, attempts=24, delay=0.25):
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(2048)
            return sock
        except OSError as exc:
            sock.close()
            last = exc
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            time.sleep(delay)
    sys.stderr.write("FATAL: could not bind %s:%s after %.1fs (%s)\n"
                     % (host, port, attempts * delay, last))
    sys.stderr.flush()
    sys.exit(1)


def main():
    from werkzeug.serving import make_server

    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
