"""Registered-Agent & Compliance-Calendar API.

Boot contract: `bash start.sh` runs this in the foreground on 0.0.0.0:$PORT
(default 10000).  Storage is in-memory only and NOTHING is seeded -- every
collection starts empty on every boot.
"""

import os
import socket
import sys
import time

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import envelope
from dispatch import ROUTES, make_view
from errors import ApiError

# Importing the route modules is what populates dispatch.ROUTES.
from routes import (  # noqa: F401  (imported for their registration side effect)
    appointments,
    boi_reports,
    clients,
    clock_ops,
    filings,
    legal_entities,
    obligations,
    owners,
    payments,
    registrations,
    reinstatement,
    sop,
    state_rules,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for index, spec in enumerate(ROUTES):
        app.add_url_rule(
            spec.flask_rule,
            endpoint="ep_%d_%s" % (index, spec.method.lower()),
            view_func=make_view(spec),
            methods=[spec.method],
        )

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return envelope.error_response(
            "ERR_RECORD_NOT_FOUND", "No route matches that path.", 404
        )

    @app.errorhandler(405)
    def handle_405(exc):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "That method is not allowed on this path.", 400
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request error.", 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error on %s %s", request.method, request.path)
        return envelope.error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


def _bind_socket(port, attempts=40, delay=0.25):
    """Per-test-server isolation kills and relaunches this process many times a
    round, so the previous LISTEN socket may still be dying.  Bind with
    SO_REUSEADDR in an EADDRINUSE-tolerant retry loop rather than letting
    app.run() abort on the first refusal."""
    last_error = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(256)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
            time.sleep(delay)
    raise SystemExit("could not bind port %s: %s" % (port, last_error))


def main():
    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    sock = _bind_socket(port)
    server = make_server("0.0.0.0", port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        try:
            server.server_close()
        except Exception:  # pragma: no cover
            pass
        sys.stdout.flush()


if __name__ == "__main__":
    main()
