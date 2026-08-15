"""CCA Program API — Flask entry point."""

import os

from flask import Flask

from envelope import error_response, ok_object
from errors import ApiError, ERR_NOT_FOUND
from routes.accounts import bp as accounts_bp
from routes.authority import bp as authority_bp
from routes.billing import bp as billing_bp
from routes.contracts import bp as contracts_bp
from routes.filings import bp as filings_bp
from routes.notices import bp as notices_bp
from routes.pools import bp as pools_bp
from routes.products import bp as products_bp
from routes.remittances import bp as remittances_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (authority_bp, accounts_bp, notices_bp, products_bp,
               contracts_bp, billing_bp, remittances_bp, pools_bp, filings_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return error_response(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
