"""Charity Auction Procurement API — Flask entry point."""

import os
import traceback

from flask import Flask

import errors
import response
from routes.acknowledgments import bp as acknowledgments_bp
from routes.bidders import bp as bidders_bp
from routes.bundles import bp as bundles_bp
from routes.certificates import bp as certificates_bp
from routes.clock_routes import bp as clock_bp
from routes.dispositions import bp as dispositions_bp
from routes.donors import bp as donors_bp
from routes.gala_events import bp as gala_events_bp
from routes.invoices import bp as invoices_bp
from routes.items import bp as items_bp
from routes.solicitations import bp as solicitations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        gala_events_bp,
        donors_bp,
        bidders_bp,
        solicitations_bp,
        items_bp,
        bundles_bp,
        invoices_bp,
        certificates_bp,
        dispositions_bp,
        acknowledgments_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.get("/health")
    def health():
        return response.success_object({"status": "ok"})

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return response.error_response("ERR_INVALID_REQUEST", 400, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_exception(e):
        traceback.print_exc()
        return response.error_response("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # The per-test-server harness kill -9s the previous server on this port
    # and immediately spawns a new one; if the old process's socket teardown
    # races the new bind, retry briefly instead of dying (which the harness
    # would surface as a spurious "could not be restarted").
    for _attempt in range(48):
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except (OSError, SystemExit):
            # werkzeug prints the bind error and sys.exit(1)s on EADDRINUSE.
            time.sleep(0.25)
    else:
        app.run(host="0.0.0.0", port=port)
