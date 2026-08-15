"""Flask application entry point."""
import os
from flask import Flask, jsonify

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.clock import bp as clock_bp
from routes.plans import bp as plans_bp
from routes.accounts import bp as accounts_bp
from routes.profiles import bp as profiles_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.save_offers import bp as save_offers_bp
from routes.billing_events import bp as billing_events_bp
from routes.price_change_notices import bp as price_change_bp
from routes.winback_campaigns import bp as winback_bp
from routes.partner_billing import bp as partner_bp
from routes.signup_attributions import bp as attributions_bp

for bp in (clock_bp, plans_bp, accounts_bp, profiles_bp, subscriptions_bp,
           save_offers_bp, billing_events_bp, price_change_bp, winback_bp,
           partner_bp, attributions_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "method not allowed"))


@app.errorhandler(400)
def handle_400(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, "bad request"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
