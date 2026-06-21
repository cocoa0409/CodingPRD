"""Entry point: Flask app, blueprint registration, and error handlers.

In-memory storage only; the store starts EMPTY on every boot. No entity is
seeded, preloaded, or hardcoded — tests build all preconditions via the
declared API surface.
"""

import os

from flask import Flask

import errors
from response import error_response

# Route blueprints.
from routes.customers import bp as customers_bp
from routes.plans import bp as plans_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.clause_templates import bp as clause_templates_bp
from routes.document_projects import bp as document_projects_bp
from routes.assembled_clauses import bp as assembled_clauses_bp
from routes.document_revisions import bp as document_revisions_bp
from routes.attorneys import bp as attorneys_bp
from routes.attorney_reviews import bp as attorney_reviews_bp
from routes.signature_requests import bp as signature_requests_bp
from routes.notary_referrals import bp as notary_referrals_bp
from routes.orders import bp as orders_bp
from routes.update_reminders import bp as update_reminders_bp
from routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        customers_bp,
        plans_bp,
        subscriptions_bp,
        clause_templates_bp,
        document_projects_bp,
        assembled_clauses_bp,
        document_revisions_bp,
        attorneys_bp,
        attorney_reviews_bp,
        signature_requests_bp,
        notary_referrals_bp,
        orders_bp,
        update_reminders_bp,
        system_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface API errors that slipped past the typed handler.
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
