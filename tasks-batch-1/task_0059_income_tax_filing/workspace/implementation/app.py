import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.taxpayers import bp as taxpayers_bp
from routes.tax_returns import bp as tax_returns_bp
from routes.children import bp as children_bp
from routes.estimated_payments import bp as estimated_payments_bp
from routes.efilings import bp as efilings_bp
from routes.amended_returns import bp as amended_returns_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (taxpayers_bp, tax_returns_bp, children_bp, estimated_payments_bp,
               efilings_bp, amended_returns_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_RETURN_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 422)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        code = e.code if e.code and e.code >= 400 else 422
        return error_response("ERR_INVALID_REQUEST", e.description or "error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
