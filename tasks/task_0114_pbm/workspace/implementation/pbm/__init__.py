"""Pharmacy Benefit Management application factory."""
from flask import Flask

from .errors import APIError
from .envelope import error_response
from .routes import (
    plans_bp,
    drugs_bp,
    members_bp,
    formulary_bp,
    pa_bp,
    claims_bp,
    copay_cards_bp,
    rebate_agreements_bp,
    ledger_bp,
    clock_bp,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    app.register_blueprint(plans_bp)
    app.register_blueprint(drugs_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(formulary_bp)
    app.register_blueprint(pa_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(copay_cards_bp)
    app.register_blueprint(rebate_agreements_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def _on_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _on_404(_err):
        from .errors import ERR_RESOURCE_NOT_FOUND
        return error_response(ERR_RESOURCE_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _on_405(_err):
        from .errors import ERR_RESOURCE_NOT_FOUND
        return error_response(ERR_RESOURCE_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _on_400(_err):
        from .errors import ERR_VALIDATION
        return error_response(ERR_VALIDATION, "Bad request", 422)

    @app.errorhandler(Exception)
    def _on_exception(err):
        # Surface unexpected server errors uniformly without leaking details.
        from .errors import ERR_VALIDATION
        return error_response(ERR_VALIDATION, f"Unhandled error: {err}", 422)

    return app
