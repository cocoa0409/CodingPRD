"""Jury Duty Management API — Flask entry point.

Registers all blueprints, installs error handlers that emit the standard error
envelope (PRD §2.2), and runs the server on 0.0.0.0:$PORT in the foreground. The
in-memory store starts empty on every boot — no seeding, no preloaded entities.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error as error_response

from routes.service_terms import bp as service_terms_bp
from routes.jurors import bp as jurors_bp
from routes.summonses import bp as summonses_bp
from routes.dispositions import bp as dispositions_bp
from routes.trials import bp as trials_bp
from routes.panels import bp as panels_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(service_terms_bp)
    app.register_blueprint(jurors_bp)
    app.register_blueprint(summonses_bp)
    app.register_blueprint(dispositions_bp)
    app.register_blueprint(trials_bp)
    app.register_blueprint(panels_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # An unknown method on a known path resolves to not-found semantics here.
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        code = e.code or 500
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 422)
        return error_response("ERR_INVALID_REQUEST", str(e), code if code >= 400 else 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Internal error: " + str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
