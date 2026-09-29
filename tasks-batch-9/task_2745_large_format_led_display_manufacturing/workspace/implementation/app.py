"""Flask entry point: blueprint registration and error handling."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import DEFAULT_MESSAGES, ApiError
from routes.burnin import bp as burnin_bp
from routes.cabinets import bp as cabinets_bp
from routes.catalogue import bp as catalogue_bp
from routes.modules import bp as modules_bp
from routes.projects import bp as projects_bp
from routes.service import bp as service_bp
from routes.visits import bp as visits_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(catalogue_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(modules_bp)
    app.register_blueprint(cabinets_bp)
    app.register_blueprint(burnin_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(service_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error_response("ERR_NOT_FOUND", DEFAULT_MESSAGES["ERR_NOT_FOUND"], 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.error_response("ERR_NOT_FOUND", DEFAULT_MESSAGES["ERR_NOT_FOUND"], 404)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code and 400 <= exc.code < 500:
            return envelope.error_response("ERR_VALIDATION_FAILED",
                                           DEFAULT_MESSAGES["ERR_VALIDATION_FAILED"], 400)
        return envelope.error_response("ERR_INTERNAL", DEFAULT_MESSAGES["ERR_INTERNAL"], 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return envelope.error_response("ERR_INTERNAL", DEFAULT_MESSAGES["ERR_INTERNAL"], 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
