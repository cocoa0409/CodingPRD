"""Pet Licensing & Animal Control API — entry point.

Boots a completely empty in-memory store on every process start (no seeding,
no preload, no disk). Registers all route blueprints and the standard error
handlers (PRD §2.2 envelope).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# route blueprints
from routes.owners import bp as owners_bp
from routes.pets import bp as pets_bp
from routes.vaccinations import bp as vaccinations_bp
from routes.kennels import bp as kennels_bp
from routes.licenses import bp as licenses_bp
from routes.dangerous import bp as dangerous_bp
from routes.lostfound import bp as lostfound_bp
from routes.audit import bp as audit_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (owners_bp, pets_bp, vaccinations_bp, kennels_bp, licenses_bp,
               dangerous_bp, lostfound_bp, audit_bp, admin_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        # method not allowed on a known path -> treat as not found per flat routing
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(HTTPException)
    def handle_http(e):
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", 400, "Bad request.")
        return error_response("ERR_INVALID_REQUEST", e.code or 400, e.description or "Error.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return e
        return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: {}".format(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
