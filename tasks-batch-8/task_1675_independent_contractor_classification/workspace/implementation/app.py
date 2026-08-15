"""Flask entry point — registers blueprints and error handlers."""

import os
from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import error as error_response

from routes.jurisdictions import bp as jurisdictions_bp
from routes.contractors import bp as contractors_bp
from routes.engagements import bp as engagements_bp
from routes.exceptions import bp as exceptions_bp
from routes.contracts import bp as contracts_bp
from routes.reviews import bp as reviews_bp
from routes.audits import bp as audits_bp
from routes.filings import bp as filings_bp
from routes.inquiries import bp as inquiries_bp
from routes.conversions import bp as conversions_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (jurisdictions_bp, contractors_bp, engagements_bp, exceptions_bp,
               contracts_bp, reviews_bp, audits_bp, filings_bp, inquiries_bp,
               conversions_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exception(err):
        return error_response(ERR_INVALID_REQUEST, str(err), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
