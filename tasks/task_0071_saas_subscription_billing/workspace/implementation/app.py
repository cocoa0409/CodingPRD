"""Flask app entry point for the SaaS Subscription Billing API."""
import os
import traceback

from flask import Flask, request

from errors import APIError, ERR_FORBIDDEN, HTTP_STATUS
from response import error as error_response

from routes.tenants import bp as tenants_bp
from routes.packages import bp as packages_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.invoices import bp as invoices_bp
from routes.credit_notes import bp as credit_notes_bp
from routes.jurisdictions import bp as jurisdictions_bp
from routes.observability import bp as observability_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(tenants_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(credit_notes_bp)
    app.register_blueprint(jurisdictions_bp)
    app.register_blueprint(observability_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_500(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, APIError):
            return handle_api_error(e)
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
