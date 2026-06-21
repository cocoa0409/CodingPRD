"""Public Health Case Investigation & Contact Tracing API entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.config import bp as config_bp
from routes.lab_results import bp as lab_results_bp
from routes.cases import bp as cases_bp
from routes.contacts import bp as contacts_bp
from routes.transfers import bp as transfers_bp
from routes.clusters import bp as clusters_bp
from routes.exports import bp as exports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(lab_results_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(clusters_bp)
    app.register_blueprint(exports_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_PROGRAM_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
