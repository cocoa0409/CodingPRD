"""Virtual-Address & Mail-Scanning (CMRA) API — entry point."""

import os
import socket
import sys
import time

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body

import routes_admin
import routes_catalogue
import routes_checks
import routes_disposition
import routes_mail
import routes_roster


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_catalogue.bp)
    app.register_blueprint(routes_roster.bp)
    app.register_blueprint(routes_mail.bp)
    app.register_blueprint(routes_disposition.bp)
    app.register_blueprint(routes_checks.bp)
    app.register_blueprint(routes_admin.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_BOX_NOT_FOUND", "No such route.")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_VALIDATION", "Method not allowed.")), 405
        return jsonify(error_body("ERR_VALIDATION", exc.description or "Bad request")), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return jsonify(error_body("ERR_VALIDATION", "Unhandled server error: %s" % exc)), 500

    return app


app = create_app()


def _bind(host, port, attempts=300, delay=0.05):
    """
    EADDRINUSE-safe bind.  Under `--isolation per-test-server` the harness kills
    and relaunches this process before every test, so a fresh process can race
    the dying process's LISTEN socket.  Werkzeug's own bind failure calls
    sys.exit(1), which surfaces as a spurious "could not be restarted" error, so
    we own the socket ourselves and retry.
    """
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(False)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(delay)
    raise SystemExit("could not bind %s:%s after %d attempts: %s"
                     % (host, port, attempts, last))


def main():
    from werkzeug.serving import make_server

    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        try:
            server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
