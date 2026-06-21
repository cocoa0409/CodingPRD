"""Document Shredding & Records Storage API — Flask entry point.

In-memory storage only; no seeding at startup. Boots clean on every launch.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints.
from routes.accounts import bp as accounts_bp
from routes.locations import bp as locations_bp
from routes.rate_cards import bp as rate_cards_bp
from routes.containers import bp as containers_bp
from routes.service_orders import bp as service_orders_bp
from routes.weight_tickets import bp as weight_tickets_bp
from routes.custody_events import bp as custody_events_bp
from routes.certificates import bp as certificates_bp
from routes.destruction_invoices import bp as destruction_invoices_bp
from routes.retention_boxes import bp as retention_boxes_bp
from routes.retrieval_requests import bp as retrieval_requests_bp
from routes.compliance_holds import bp as compliance_holds_bp
from routes.storage_invoices import bp as storage_invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(locations_bp)
    app.register_blueprint(rate_cards_bp)
    app.register_blueprint(containers_bp)
    app.register_blueprint(service_orders_bp)
    app.register_blueprint(weight_tickets_bp)
    app.register_blueprint(custody_events_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(destruction_invoices_bp)
    app.register_blueprint(retention_boxes_bp)
    app.register_blueprint(retrieval_requests_bp)
    app.register_blueprint(compliance_holds_bp)
    app.register_blueprint(storage_invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unmatched route -> generic not found in the standard envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Fallback for other werkzeug HTTP errors (keep envelope consistent).
        return error_response("ERR_NOT_FOUND", e.description or "Error", e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
