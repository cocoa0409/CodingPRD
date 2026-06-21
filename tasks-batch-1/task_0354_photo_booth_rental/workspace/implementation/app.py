"""Entry point: error handlers + blueprint registration. In-memory only,
no seeding — the store starts empty on every boot."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.bookings import bp as bookings_bp
from routes.addon_lines import bp as addon_lines_bp
from routes.attendant_assignments import bp as attendant_assignments_bp
from routes.event_logs import bp as event_logs_bp
from routes.galleries import bp as galleries_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        catalog_bp, customers_bp, bookings_bp, addon_lines_bp,
        attendant_assignments_bp, event_logs_bp, galleries_bp, clock_bp,
    ):
        app.register_blueprint(bp)


    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 422)

    return app


app = create_app()

def _serve_forever(application, host, port):
    """Serve `application` on host:port with a hardened WSGI server.

    Why not the Werkzeug dev server (`app.run`): under the 8-round parallel
    stability sweep (~8x concurrent kill -9 + reboot of this server, once before
    every test), Werkzeug's ThreadingMixIn dev server can occasionally hand the
    client a truncated reply that surfaces as a BadStatusLine / "Connection
    aborted". waitress's async I/O loop drains connections robustly under that
    load and does not truncate.

    Why a *forced-close* waitress: the harness drives the API through a
    session-scoped requests.Session whose urllib3 pool persists across the
    per-test restart. waitress speaks HTTP/1.1 keep-alive by default, so the
    client would pool a socket and, after the restart, reuse it against the
    freshly-rebooted process (or a half-dead one) — a systematic hazard. We
    subclass waitress so every response sets `Connection: close` at the *server*
    layer (legal — it is waitress, not the WSGI app, setting the hop-by-hop
    header) and the channel closes after one request. The client then opens a
    fresh socket for every request and a restart is invisible to it.
    """
    from waitress.server import create_server
    from waitress.channel import HTTPChannel
    from waitress.task import WSGITask

    class _CloseAfterRequestTask(WSGITask):
        def build_response_header(self):
            # Force the connection closed after this single response.
            self.set_close_on_finish()
            return super().build_response_header()

    class _CloseAfterRequestChannel(HTTPChannel):
        task_class = _CloseAfterRequestTask

    server = create_server(application, host=host, port=port, threads=8)
    # Point both the already-bound server and its class at the close-on-finish
    # channel so every accepted connection is single-request.
    server.channel_class = _CloseAfterRequestChannel
    server.run()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _serve_forever(app, "0.0.0.0", port)
