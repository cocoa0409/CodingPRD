"""Developer Marketplace & App-Store Payouts API."""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ApiError, error_response  # noqa: E402
from routes.apps import bp as apps_bp  # noqa: E402
from routes.chargebacks import bp as chargebacks_bp  # noqa: E402
from routes.config_routes import bp as config_bp  # noqa: E402
from routes.developers import bp as developers_bp  # noqa: E402
from routes.ledger import bp as ledger_bp  # noqa: E402
from routes.payouts import bp as payouts_bp  # noqa: E402
from routes.policy_cases import bp as policy_cases_bp  # noqa: E402
from routes.pricing_plans import bp as pricing_plans_bp  # noqa: E402
from routes.purchases import bp as purchases_bp  # noqa: E402
from routes.refunds import bp as refunds_bp  # noqa: E402
from routes.reviews import bp as reviews_bp  # noqa: E402
from routes.tax_forms import bp as tax_forms_bp  # noqa: E402

BLUEPRINTS = (
    config_bp,
    developers_bp,
    apps_bp,
    reviews_bp,
    pricing_plans_bp,
    purchases_bp,
    refunds_bp,
    chargebacks_bp,
    policy_cases_bp,
    payouts_bp,
    ledger_bp,
    tax_forms_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Resource path not found.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request error",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
