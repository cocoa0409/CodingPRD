"""Scholarship Review Management API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.scholarships import bp as scholarships_bp
    from routes.reviewers import bp as reviewers_bp
    from routes.applications import bp as applications_bp
    from routes.objections import bp as objections_bp
    from routes.disbursement import bp as disbursement_bp
    from routes.audit_sync import bp as audit_sync_bp
    from routes.system import bp as system_bp

    for bp in (scholarships_bp, reviewers_bp, applications_bp, objections_bp,
               disbursement_bp, audit_sync_bp, system_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_BAD_REQUEST", str(e) or "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
