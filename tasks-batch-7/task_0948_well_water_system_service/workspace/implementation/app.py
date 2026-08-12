"""Well & Water-System Service API.

Entry point: registers every declared endpoint against the shared nine-gate
pipeline and serves the app on a socket bound defensively, so that a per-test
server restart cannot lose a race with the dying listener of the previous
process.
"""

import os
import socket
import sys
import threading
import time
import traceback

from flask import Flask, jsonify

import core
from core import REGISTRY, ApiError, error_response, run_endpoint, success

# Importing the route modules populates core.REGISTRY.
import r_register  # noqa: F401
import r_field  # noqa: F401
import r_quote  # noqa: F401
import r_emerg  # noqa: F401
import r_wo  # noqa: F401
import r_maint  # noqa: F401
import r_bill  # noqa: F401

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

_LOCK = threading.RLock()


def _make_view(ep):
    def view(**path_values):
        try:
            with _LOCK:
                data, pagination = run_endpoint(ep, path_values)
        except ApiError as err:
            return error_response(err)
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc()
            return error_response(ApiError("ERR_VALIDATION", "Unexpected server error."))
        return success(data, ep.code, pagination)

    view.__name__ = "%s_%s" % (ep.method.lower(),
                               ep.path.strip("/").replace("/", "_")
                               .replace("<", "").replace(">", ""))
    return view


_seen = set()
for _ep in REGISTRY:
    _name = "%s %s" % (_ep.method, _ep.path)
    if _name in _seen:
        raise RuntimeError("duplicate endpoint registration: %s" % _name)
    _seen.add(_name)
    app.add_url_rule(_ep.path, endpoint=_name, view_func=_make_view(_ep),
                     methods=[_ep.method])


@app.errorhandler(404)
def _not_found(_error):
    return error_response(ApiError("ERR_VALIDATION", "No such route."))


@app.errorhandler(405)
def _not_allowed(_error):
    return error_response(ApiError("ERR_VALIDATION", "Method not allowed."))


def _bind(port, host="0.0.0.0", timeout=6.0):
    """Bounded retry around creating the listening socket.

    Under --isolation per-test-server the previous process's LISTEN socket may
    still be dying when this one binds.  Retrying briefly with SO_REUSEADDR and
    handing the already-bound socket to the WSGI server keeps a boot race from
    surfacing as an innocent-looking 'server could not be restarted'.
    """
    deadline = time.time() + timeout
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(256)
            return sock
        except OSError:
            sock.close()
            if time.time() >= deadline:
                raise
            time.sleep(0.05)


def main():
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(port)
    from werkzeug.serving import make_server
    server = make_server("0.0.0.0", port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
