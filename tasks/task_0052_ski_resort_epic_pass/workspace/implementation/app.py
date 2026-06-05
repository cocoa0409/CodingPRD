import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.resorts import bp as resorts_bp
from routes.pass_products import bp as pass_products_bp
from routes.passes import bp as passes_bp
from routes.buddy_tickets import bp as buddy_tickets_bp
from routes.refund_requests import bp as refund_requests_bp
from routes.interchange import bp as interchange_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(resorts_bp)
    app.register_blueprint(pass_products_bp)
    app.register_blueprint(passes_bp)
    app.register_blueprint(buddy_tickets_bp)
    app.register_blueprint(refund_requests_bp)
    app.register_blueprint(interchange_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_VALIDATION", str(err), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
