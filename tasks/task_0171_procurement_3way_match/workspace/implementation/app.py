"""Procurement 3-Way Match API — Flask entry point.

In-memory only. Fresh process => empty store. No seeding at startup.
"""
import os

from flask import Flask, request

from errors import ApiError
import errors
from response import error_response

from routes.spend_categories import bp as spend_categories_bp
from routes.vendors import bp as vendors_bp
from routes.requisitions import bp as requisitions_bp
from routes.rfqs import bp as rfqs_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.goods_receipts import bp as goods_receipts_bp
from routes.invoices import bp as invoices_bp
from routes.scorecards import bp as scorecards_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(spend_categories_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(requisitions_bp)
    app.register_blueprint(rfqs_bp)
    app.register_blueprint(purchase_orders_bp)
    app.register_blueprint(goods_receipts_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(scorecards_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — still resolve auth-context first per the ladder would
        # require route binding; an unmatched path is a not-found resource.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a production WSGI server) rather than Werkzeug's dev
    # server: under the benchmark's per-test-server isolation the server is
    # rebooted before every test, with 8 sweep rounds running concurrently. The
    # Werkzeug dev server intermittently drops freshly-accepted connections under
    # that load (manifesting as client-side BadStatusLine / connection-aborted).
    # Waitress's larger listen backlog and worker pool serve those connections
    # reliably. Behaviour is unchanged — only the HTTP serving layer differs.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, backlog=256)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
