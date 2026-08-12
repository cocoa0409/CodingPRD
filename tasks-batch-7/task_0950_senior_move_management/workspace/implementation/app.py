"""Senior Move Management API - entry point.

Boot robustness: the harness runs `--isolation per-test-server`, killing the
previous server and immediately re-launching this one. The listening port lives
in the ephemeral range, so during the kill-to-bind window any other process on
the box - including a sibling test run's keep-alive client socket - can take it
as an outbound source port and hold it for the life of that connection. Two
defences, in this order:

1. The listening socket is bound and put into `listen()` at the very top of this
   module, BEFORE Flask and the ten route blueprints are imported. That shrinks
   the window from a few hundred milliseconds of import time down to interpreter
   start alone, and once the backlog is open a client that connects early simply
   waits instead of being refused.
2. The bind sits in a bounded retry loop with SO_REUSEADDR rather than letting
   werkzeug `sys.exit(1)` on the first `OSError`, so a transient steal is ridden
   out instead of killing the boot.

The already-listening socket is then handed to `make_server(fd=...)`, which
skips its own bind entirely.
"""

import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_PORT = int(os.environ.get("PORT", "10000"))


def _bind_listener(port):
    """Claim the port as early as possible; retry briefly if it is held."""
    last = None
    for _attempt in range(56):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(128)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
            time.sleep(0.25)
    raise last


_LISTENER = _bind_listener(_PORT)

from flask import Flask, request

import envelope
import store
from errors import ApiError, ERROR_HTTP

from routes.core import bp as core_bp
from routes.portal import bp as portal_bp
from routes.destination import bp as destination_bp
from routes.inventory import bp as inventory_bp
from routes.planning import bp as planning_bp
from routes.crew import bp as crew_bp
from routes.vendors import bp as vendors_bp
from routes.consignment import bp as consignment_bp
from routes.billing import bp as billing_bp
from routes.timeline import bp as timeline_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (core_bp, portal_bp, destination_bp, inventory_bp, planning_bp,
                  crew_bp, vendors_bp, consignment_bp, billing_bp, timeline_bp):
    app.register_blueprint(blueprint)


@app.before_request
def _begin():
    store.begin_request()


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _not_found(_exc):
    return envelope.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def _method_not_allowed(_exc):
    return envelope.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)


@app.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, ApiError):
        return _api_error(exc)
    app.logger.exception("unhandled error")
    return envelope.error_response("ERR_VALIDATION", "Request could not be processed.", 400)


def _serve():
    from werkzeug.serving import make_server

    server = make_server("0.0.0.0", _PORT, app, threaded=True, fd=_LISTENER.fileno())
    server.serve_forever()


if __name__ == "__main__":
    _serve()
