import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.accounts import bp as accounts_bp
from routes.ledger import bp as ledger_bp
from routes.vehicles import bp as vehicles_bp
from routes.transponders import bp as transponders_bp
from routes.bindings import bp as bindings_bp
from routes.hov import bp as hov_bp
from routes.plazas import bp as plazas_bp
from routes.interop import bp as interop_bp
from routes.transactions import bp as transactions_bp
from routes.violations import bp as violations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (accounts_bp, ledger_bp, vehicles_bp, transponders_bp, bindings_bp,
               hov_bp, plazas_bp, interop_bp, transactions_bp, violations_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return error_response("ERR_VALIDATION", e.description or "error",
                              e.code if e.code and e.code >= 400 else 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION", str(e), 422)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
