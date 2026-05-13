"""Translation Collab API — Flask entry point."""
from __future__ import annotations

import os
import traceback

from flask import Flask, request

from errors import ApiError, ERROR_HTTP
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register routes
    from routes import clients, translators, projects, project_templates, documents, segments, \
        assignments, terminology, quality_scores, audit_sync, ops
    app.register_blueprint(clients.bp)
    app.register_blueprint(translators.bp)
    app.register_blueprint(projects.bp)
    app.register_blueprint(project_templates.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(segments.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(terminology.bp)
    app.register_blueprint(quality_scores.bp)
    app.register_blueprint(audit_sync.bp)
    app.register_blueprint(ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION_FAILED", str(e), 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        traceback.print_exc()
        return error_response("ERR_VALIDATION_FAILED", str(e) or "internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
