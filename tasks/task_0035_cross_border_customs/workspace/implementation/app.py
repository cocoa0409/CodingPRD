"""Cross-Border Customs API — Flask entry point."""

import os

from flask import Flask, request

from errors import APIError, auth_missing
from middleware import VALID_ROLES, extract_auth
from response import error_response


OPEN_PATHS = {"/healthz", "/_health"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth_check():
        if request.method == "OPTIONS":
            return None
        if request.path in OPEN_PATHS:
            return None
        try:
            extract_auth()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
        return None

    # Register blueprints
    from routes.hs_codes import bp as hs_codes_bp
    from routes.classification import bp as classification_bp
    from routes.tariff_rules import bp as tariff_rules_bp
    from routes.exchange_rates import bp as exchange_rates_bp
    from routes.parties import bp as parties_bp
    from routes.orders import bp as orders_bp
    from routes.declarations import bp as declarations_bp
    from routes.queries import bp as queries_bp
    from routes.inspections import bp as inspections_bp
    from routes.payments import bp as payments_bp
    from routes.refunds import bp as refunds_bp
    from routes.audit import bp as audit_bp
    from routes.test_endpoints import bp as test_endpoints_bp

    app.register_blueprint(hs_codes_bp)
    app.register_blueprint(classification_bp)
    app.register_blueprint(tariff_rules_bp)
    app.register_blueprint(exchange_rates_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(declarations_bp)
    app.register_blueprint(queries_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(test_endpoints_bp)

    @app.route("/healthz", methods=["GET"])
    def _healthz():
        return {"status": "ok"}, 200

    @app.errorhandler(APIError)
    def _on_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _on_404(_e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _on_405(_e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)

    @app.errorhandler(Exception)
    def _on_uncaught(exc):
        if isinstance(exc, APIError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
