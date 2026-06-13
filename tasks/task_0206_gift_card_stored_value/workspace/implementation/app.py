"""Gift Card & Stored-Value Program API — Flask entry point.

In-memory only: all state lives in db.py's process-local dicts and is wiped on
every fresh boot. No seeding, no disk persistence.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from middleware import get_identity

from routes.programs import bp as programs_bp
from routes.customers import bp as customers_bp
from routes.cards import bp as cards_bp
from routes.ledger import bp as ledger_bp
from routes.holds import bp as holds_bp
from routes.redemptions import bp as redemptions_bp
from routes.bulk_orders import bp as bulk_orders_bp
from routes.replacements import bp as replacements_bp
from routes.refunds import bp as refunds_bp
from routes.waivers import bp as waivers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(holds_bp)
    app.register_blueprint(redemptions_bp)
    app.register_blueprint(bulk_orders_bp)
    app.register_blueprint(replacements_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(waivers_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_body(e.error_id, e.message)
        resp = jsonify(body)
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(_e):
        # Unknown route. Auth still comes first per §2.11: if the caller is
        # unauthenticated, surface that; otherwise it's a genuine not-found.
        try:
            get_identity()
        except ApiError as ae:
            body = error_body(ae.error_id, ae.message)
            resp = jsonify(body)
            resp.status_code = ae.http_status
            return resp
        body = error_body("ERR_NOT_FOUND", "Resource not found.")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(_e):
        body = error_body("ERR_NOT_FOUND", "Method not allowed.")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_body("ERR_VALIDATION", f"Unexpected error: {e}")
        resp = jsonify(body)
        resp.status_code = 422
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
