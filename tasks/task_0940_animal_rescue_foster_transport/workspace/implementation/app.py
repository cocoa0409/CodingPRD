"""Animal Rescue & Foster/Transport Network API -- entry point.

The store starts EMPTY on every boot: nothing here seeds, preloads, registers
or hardcodes any entity.
"""

import errno
import os
import socket
import sys
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError

from routes.orgs import bp as orgs_bp
from routes.animals import bp as animals_bp
from routes.intake import bp as intake_bp
from routes.foster import bp as foster_bp
from routes.medical import bp as medical_bp
from routes.transport import bp as transport_bp
from routes.adoption import bp as adoption_bp
from routes.outcomes import bp as outcomes_bp
from routes.funding import bp as funding_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in (orgs_bp, animals_bp, intake_bp, foster_bp, medical_bp,
               transport_bp, adoption_bp, outcomes_bp, funding_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope.error("ERR_VALIDATION", "No such route.", 404)
        if exc.code == 405:
            return envelope.error("ERR_VALIDATION", "Method not allowed for this route.", 405)
        if exc.code in (400, 415):
            return envelope.error("ERR_VALIDATION", "The request body is malformed.", 400)
        return envelope.error("ERR_VALIDATION", exc.description or "Request failed.", exc.code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):     # pragma: no cover - defensive
        return envelope.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


def _prebind(host, port):
    """Bind the listening socket ourselves, tolerating EADDRINUSE for a bounded
    window.

    Under `--isolation per-test-server` the harness kill -9's the previous
    server and immediately spawns the replacement WITHOUT waiting for the socket
    to be released.  Werkzeug treats a bind failure as fatal -- it prints to
    stderr and calls sys.exit(1) -- so the replacement dies in milliseconds and
    the harness then polls a dead port for its whole boot budget, blaming an
    innocent test with "API server could not be restarted".  Wrapping app.run()
    in try/except OSError does NOT help: Werkzeug has already converted the
    error into SystemExit.

    The retry window is deliberately bounded at ~6 seconds (24 x 0.25s).  A
    longer loop would outlive the harness readiness probe and turn a rejected
    respawn into a PPID-1 orphan that squats the port and poisons the next round.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for attempt in range(24):
        try:
            sock.bind((host, port))
            sock.listen(256)
            return sock
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
                sock.close()
                raise
            time.sleep(0.25)
    sock.close()
    sys.stderr.write("FATAL: port %d still occupied after the bounded retry window\n" % port)
    sys.stderr.flush()
    sys.exit(1)


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _prebind(host, port)
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:       # pragma: no cover
        pass


if __name__ == "__main__":
    main()
