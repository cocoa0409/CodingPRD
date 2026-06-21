"""Quality Management System API — Flask entry point.

Registers all domain blueprints, installs the global error handlers, and binds
0.0.0.0:$PORT in the foreground. Storage is in-memory only; no data is seeded
at startup.
"""
import os
import socket
import time

from flask import Flask

from errors import ApiError
from response import error_response

from routes.personnel import bp as personnel_bp
from routes.suppliers import bp as suppliers_bp
from routes.ncr import bp as ncr_bp
from routes.capa import bp as capa_bp
from routes.scar import bp as scar_bp
from routes.control_plan import bp as control_plan_bp
from routes.inspection import bp as inspection_bp
from routes.audit import bp as audit_bp
from routes.deviation import bp as deviation_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(personnel_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(ncr_bp)
    app.register_blueprint(capa_bp)
    app.register_blueprint(scar_bp)
    app.register_blueprint(control_plan_bp)
    app.register_blueprint(inspection_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(deviation_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()


def _make_server_socket(host, port, retries=50, delay=0.1):
    """Bind a socket with SO_REUSEADDR and a short retry loop so a same-port
    bind race under rapid per-test restarts does not spuriously fail."""
    last_err = None
    for _ in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            last_err = exc
            sock.close()
            time.sleep(delay)
    raise last_err


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    # Pre-bind with SO_REUSEADDR + retry to survive rapid restart bind races,
    # then hand the listening socket to the WSGI server.
    server_socket = _make_server_socket(host, port)
    try:
        from werkzeug.serving import make_server
        httpd = make_server(host, port, app, fd=server_socket.fileno())
        httpd.serve_forever()
    except Exception:
        # Fallback: let Flask bind directly (still 0.0.0.0:$PORT, foreground).
        server_socket.close()
        app.run(host=host, port=port, threaded=True)
