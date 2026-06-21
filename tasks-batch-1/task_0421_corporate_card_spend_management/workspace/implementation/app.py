"""Corporate Card & Spend Management API — Flask entry point."""
import os

from flask import Flask, request

import response
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION, ERR_FORBIDDEN_FOR_ROLE

from routes.setup import bp as setup_bp
from routes.cards import bp as cards_bp
from routes.transactions import bp as transactions_bp
from routes.reimbursements import bp as reimbursements_bp
from routes.billing import bp as billing_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(setup_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(reimbursements_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(misc_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / unresolved resource path.
        return response.error(ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error(ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return response.error(ERR_VALIDATION, "Bad request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return response.error(e.error_id, e.message, e.http_status)
        # Surface unexpected server errors as a generic validation-style error so
        # the envelope is always well-formed.
        return response.error("ERR_INTERNAL", "Internal server error: %s" % e, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
