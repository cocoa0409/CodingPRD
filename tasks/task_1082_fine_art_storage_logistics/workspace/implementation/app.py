"""Fine-Art Storage & Logistics API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from envelope import error_response

from routes.core import bp as core_bp
from routes.storage import bp as storage_bp
from routes.valuation import bp as valuation_bp
from routes.logistics import bp as logistics_bp
from routes.loans import bp as loans_bp
from routes.viewing import bp as viewing_bp
from routes.billing import bp as billing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(core_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(valuation_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(viewing_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        resp = error_response(e.error_id, e.message)
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        resp = error_response("ERR_NOT_FOUND", "resource not found")
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        resp = error_response("ERR_NOT_FOUND", "method not allowed")
        resp.status_code = 405
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        resp = error_response("ERR_VALIDATION", "unexpected error: %s" % e)
        resp.status_code = 400
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
