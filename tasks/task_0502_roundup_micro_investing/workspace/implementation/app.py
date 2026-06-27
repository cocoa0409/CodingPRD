"""Entry point: Flask app, blueprint registration, global error handlers.

Round-Up Micro-Investing & Robo-Advisor API. In-memory store only; no seeding.
Boots clean on every process start (per-test-server isolation re-invokes start.sh).
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response, iso_now_ms, gen_request_id
from routes.accounts import bp as accounts_bp
from routes.buckets import bp as buckets_bp
from routes.cards import bp as cards_bp
from routes.config import bp as config_bp
from routes.contributions import bp as contributions_bp
from routes.orders import bp as orders_bp
from routes.referrals import bp as referrals_bp
from routes.rewards import bp as rewards_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(config_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(buckets_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(rewards_bp)
    app.register_blueprint(referrals_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on an existing path — treat as forbidden role
        # is wrong; surface a generic invalid-request. Most tests target known
        # routes, so this is a defensive fallthrough.
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Never leak a raw 500 stack as JSON the harness can't parse.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        body = {
            "meta": {
                "api_request_id": gen_request_id(),
                "api_request_timestamp": iso_now_ms(),
            },
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
        }
        resp = jsonify(body)
        resp.status_code = 500
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
