"""Entry point: Flask app assembly, error handlers, server bootstrap."""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND
from response import error

app = Flask(__name__)

# Importing the route modules registers every endpoint on the blueprint.
import routes  # noqa: F401,E402
import routes2  # noqa: F401,E402
import routes3  # noqa: F401,E402

app.register_blueprint(routes.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(exc):
    return error(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, HTTPException):
        return error("ERR_INVALID_REQUEST", exc.code or 400, exc.description)
    traceback.print_exc()
    return error("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    import errno
    import socket as _socket
    import time

    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    # The per-test harness SIGKILLs the previous server on this port and
    # respawns immediately; a killed process's listen socket can briefly
    # outlive the process, so a fresh boot can race into EADDRINUSE — which
    # werkzeug handles by exiting the process. Probe the port with retries
    # first (the socket frees in well under a second), then start for real.
    for _ in range(60):  # up to ~15s, within the harness restart window
        probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        probe.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("0.0.0.0", port))
        except OSError as exc:
            probe.close()
            if exc.errno != errno.EADDRINUSE:
                raise
            time.sleep(0.25)
        else:
            probe.close()
            break
    else:
        raise SystemExit("port never became bindable")
    server = make_server("0.0.0.0", port, app)
    server.serve_forever()
