"""Direct-Mail & Handwritten-Note Fulfillment API.

Boots from a fresh process on every invocation with an empty store.  The
listening socket is created and bound here (rather than by Werkzeug) with an
EADDRINUSE-tolerant retry loop, because the harness kills and relaunches this
server before every single test and a fresh boot routinely races the previous
process's dying LISTEN socket.
"""
import errno
import os
import socket
import time
import traceback

from flask import Flask, jsonify

import envelope
from errors import ApiError

from routes.admin import bp as admin_bp
from routes.campaigns import bp as campaigns_bp
from routes.templates import bp as templates_bp
from routes.lists import bp as lists_bp
from routes.jobs import bp as jobs_bp
from routes.proofs import bp as proofs_bp
from routes.production import bp as production_bp
from routes.drip import bp as drip_bp
from routes.ledger import bp as ledger_bp
from routes.returns import bp as returns_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for bp in (admin_bp, campaigns_bp, templates_bp, lists_bp, jobs_bp,
               proofs_bp, production_bp, drip_bp, ledger_bp, returns_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return envelope.error_response(ApiError("ERR_RESOURCE_NOT_FOUND"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return envelope.error_response(ApiError("ERR_RESOURCE_NOT_FOUND"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err)
        traceback.print_exc()
        body = {
            "meta": envelope._meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


def _bind(host, port):
    """Bind with SO_REUSEADDR, tolerating a still-dying predecessor socket."""
    last = None
    for _ in range(40):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(256)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except Exception:
                pass
            if exc.errno not in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                raise
            time.sleep(0.25)
    raise SystemExit("could not bind %s:%s: %s" % (host, port, last))


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
