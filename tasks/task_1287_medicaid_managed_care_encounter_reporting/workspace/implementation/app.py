"""Entry point: Flask app, error handlers, route registration."""
import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError
from response import error_response
from routes.programs import bp as programs_bp
from routes.roster import bp as roster_bp
from routes.cycles import bp as cycles_bp
from routes.encounters import bp as encounters_bp
from routes.batches import bp as batches_bp
from routes.audits import bp as audits_bp
from routes.statements import bp as statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(encounters_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(audits_bp)
    app.register_blueprint(statements_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True, use_reloader=False)
