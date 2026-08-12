"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask
from errors import ApiError, err
from response import error_response

from routes.network import bp as network_bp
from routes.jobs import bp as jobs_bp
from routes.assignments import bp as assignments_bp
from routes.safety import bp as safety_bp
from routes.scope import bp as scope_bp
from routes.services import bp as services_bp
from routes.permits import bp as permits_bp
from routes.documents import bp as documents_bp
from routes.invoices import bp as invoices_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Log unexpected but still respond with envelope
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e), 500)

    app.register_blueprint(network_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(safety_bp)
    app.register_blueprint(scope_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(clock_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False, use_reloader=False)
