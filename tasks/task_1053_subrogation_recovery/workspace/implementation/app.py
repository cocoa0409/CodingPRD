"""Subrogation & Recovery Vendor API — Flask entry point.

In-memory only; empty on every boot; no seeding. The logical clock defaults to
2026-07-01T00:00:00Z (store.CLOCK_DEFAULT_UTC).
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from envelope import error_body, _meta

from routes.carriers import bp as carriers_bp
from routes.adverse_parties import bp as adverse_bp
from routes.claims import bp as claims_bp
from routes.demands import bp as demands_bp
from routes.arbitrations import bp as arbitrations_bp
from routes.settlements import bp as settlements_bp
from routes.payments import bp as payments_bp
from routes.reimbursements import bp as reimbursements_bp
from routes.statements import bp as statements_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (carriers_bp, adverse_bp, claims_bp, demands_bp, arbitrations_bp,
               settlements_bp, payments_bp, reimbursements_bp, statements_bp,
               clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist"))

    @app.errorhandler(405)
    def handle_405(_e):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        if isinstance(err, ApiError):
            return error_body(err)
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
